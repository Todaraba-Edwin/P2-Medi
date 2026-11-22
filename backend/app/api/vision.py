"""BE-14 사진 약 이름 추출 변환 함수(`gpt-6-luna` 비전, PRD-08-02·04·06·07 A, 2026-11-22).

에이전트 그래프 **앞**의 변환 단계다. 판정·설명·요약을 하지 않고, `app.agent.tools`·`app.agent.graph`를 import하지 않는다(H19 〔D7〕 A:
사용자가 확인 카드에서 승인하기 전에는 그래프로 들어가는 값이 없다). 엔드포인트는 `app.api.ingest`.

- 지시문·스키마·정리 규칙·확대 전처리는 `evaluation/mock_gen/vision_pouch_test.py`(AG-17 측정 조건)와 같다. 지시문 원본은
  `backend/prompts/pouch_vision@v1.md`(본문 = `vision_pouch_test.SYSTEM`, 시험이 같음을 확인한다).
- 확대 전처리(〔D2〕 A): Pillow로 메모리에서 RGB → 긴 변 1400px(LANCZOS, 작으면 확대·크면 축소) → JPEG q92 → data URL. 파일을 만들지 않는다.
  `resize=False`는 AG-17 원본 조건(받은 바이트 그대로)이다.
- 호출: Chat Completions + 이미지 data URL + `json_schema strict`, `temperature` 없음. 키는 `Settings.openai_api_key`(기존 `OPENAI_API_KEY`)로만,
  새 환경변수 없음. 클라이언트는 주입 가능(`VisionClient`)하고 시험은 가짜만 쓴다. 일시 오류만 2회 재시도, 호출당 30초 한도.
- 비용(〔D4〕 A): 원장 `CostLedger` 구분 `vision`(상한 0.30 USD). 호출 전 최악 비용으로 `guard`, 호출 뒤 실제 `usage`로 `add`.
  원장을 못 읽거나 상한이면 실호출 없이 `UNAVAILABLE`/`CAP_REACHED`.
- 정리(PRD-08-04, 코드가 강제): 허용 필드 3개만, 80자 자름, 용량·제형 어휘가 아닌 `strength_or_form`(색·모양 등) 버림, 개인정보 의심 값 버림,
  상품명·성분명 둘 다 없는 항목 버림, 최대 10개. 모델의 `confidence`는 응답·화면 판단에 쓰지 않는다(`raw`에만 남겨 측정에서 본다).
- **이미지·base64·약 이름·질문·모델 출력은 로그·파일·캐시에 남기지 않는다**(RFP-34-01). `app.llm.cache`를 쓰지 않는다.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from PIL import Image

from app.llm.ledger import BudgetExceeded, CostLedger
from app.llm.prompts import split_frontmatter

MODEL = "gpt-6-luna"
PRICE_IN_PER_M, PRICE_OUT_PER_M = 0.10, 0.50  # USD/100만 토큰, `vision_pouch_test.OPENAI_PRICES`(RFP-15 §8.2, 2026-11-04 조회 값)
MAX_COMPLETION_TOKENS = 4000  # 추론 토큰이 출력에 포함될 수 있어 넉넉히(상한일 뿐), `vision_pouch_test.OPENAI_MAX_COMPLETION`
LONG_SIDE = 1400  # 확대 전처리 긴 변(`vision_pouch_test.UPSCALE_LONG_SIDE`)
JPEG_QUALITY = 92
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 디코드 뒤 8MB(BE-14 §5 "구현 때 정한다", 제안 숫자)
MAX_PIXELS = 40_000_000  # 가로 x 세로 상한(압축 폭탄 차단, 제안 숫자). 머리만 읽고 판단한다
MAX_DRUGS = 10
MAX_STR = 80
TIMEOUT_S = 30.0
RETRIES = 2  # 일시 오류(속도 제한·연결·시간 초과·5xx)만
LEDGER_BUCKET = "vision"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "pouch_vision@v1.md"
PROMPT_ID = "pouch_vision@v1"

ALLOWED_DRUG_FIELDS = ("product_name", "ingredient_name", "strength_or_form", "confidence")
CONFIDENCE = ("high", "medium", "low")
OUT_FIELDS = ALLOWED_DRUG_FIELDS[:3]  # 응답에 싣는 칸(확신도 제외)

# `vision_pouch_test.SCHEMA`와 같다(AG-17 재측정 조건). 환자·병원·약국·연락처 칸은 스키마에 없다
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "drugs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "product_name": {"type": ["string", "null"]},
                    "ingredient_name": {"type": ["string", "null"]},
                    "strength_or_form": {"type": ["string", "null"]},
                    "confidence": {"type": "string", "enum": list(CONFIDENCE)},
                },
                "required": list(ALLOWED_DRUG_FIELDS),
                "additionalProperties": False,
            },
        },
        "unreadable_note": {"type": ["string", "null"]},
    },
    "required": ["drugs", "unreadable_note"],
    "additionalProperties": False,
}
USER_TEXT = "이 사진에 있는 약을 모두 위 규칙대로 JSON으로 적어라."

# 개인정보 유출 의심 패턴(`vision_pouch_test.LEAK_PATTERNS`). 걸린 값은 버린다
LEAK_PATTERNS = {
    "phone": re.compile(r"\d{2,4}-\d{3,4}-\d{4}"),
    "facility": re.compile(r"(병원|의원|약국|보건소|클리닉)"),
    "person_field": re.compile(r"(환자|성명|약사|조제자|주소|연락처)"),
}
STRENGTH_FORM_OK = re.compile(r"^[\d\.\s,/~]*(mg|g|ml|mcg|㎎|㎖|%|밀리그램|정|캡슐|캡셀|정제|필름코팅정제?|경질캡슐|연질캡슐|"
                              r"현탁액|시럽|액|경구액|연고|안연고|크림|산|과립)?[\s\d\.mgl㎎㎖]*$", re.I)

_DATA_URL = re.compile(r"^data:(image/(?:jpeg|jpg|png));base64,", re.I)
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

Status = Literal["OK", "UNREADABLE", "UNAVAILABLE"]
Reason = Literal["NONE_READ", "MODEL_ERROR", "REFUSED", "PARSE_ERROR", "CAP_REACHED"]


class InvalidImage(ValueError):
    """형식·크기·픽셀 위반(→ 422 `INVALID_REQUEST` fields=["image"]). 메시지에 이미지 내용을 담지 않는다."""


class TransientVisionError(RuntimeError):
    """재시도해도 되는 일시 오류(속도 제한·연결·시간 초과·5xx)."""


@dataclass(frozen=True)
class Completion:
    """비전 호출 결과에서 쓰는 값만. `content`는 모델 출력 글자(로그·파일에 남기지 않는다)."""

    content: str | None
    refusal: str | None
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int


class VisionClient(Protocol):
    def complete(self, *, model: str, messages: list[dict[str, Any]], max_completion_tokens: int,
                 response_format: dict[str, Any], timeout: float) -> Completion: ...


@dataclass
class VisionResult:
    status: Status
    reason: Reason | None
    drugs: list[dict[str, str | None]] = field(default_factory=list)  # 허용 3칸만(확신도 없음)
    raw: dict[str, Any] | None = None  # 정리 전 파싱 결과(측정용, 응답·로그에 싣지 않는다)
    in_tokens: int = 0
    out_tokens: int = 0
    usd: float = 0.0
    latency_s: float = 0.0
    attempts: int = 0
    dropped: list[str] = field(default_factory=list)  # 버린 칸·사유 이름(값 없음)


@dataclass(frozen=True)
class ImageInfo:
    format: str  # JPEG | PNG
    width: int
    height: int


# ---------------------------------------------------------------- 요청 검사
def decode_data_url(value: str) -> bytes:
    """`data:image/jpeg|png;base64,…` → 바이트. 형식·크기 위반은 InvalidImage."""
    m = _DATA_URL.match(value or "")
    if not m:
        raise InvalidImage("data URL 형식이 아니다(JPEG·PNG만)")
    b64 = value[m.end():]
    if len(b64) > (MAX_IMAGE_BYTES * 4) // 3 + 8:  # 디코드 전에 크기로 먼저 거른다(메모리)
        raise InvalidImage("크기 초과")
    try:
        data = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise InvalidImage("base64 형식 오류") from None
    if not data:
        raise InvalidImage("빈 이미지")
    return data


def check_image(data: bytes) -> ImageInfo:
    """머리 바이트로 JPEG·PNG만, 8MB 이하, 픽셀 수 상한. 픽셀은 머리만 읽고(디코드 전) 판단한다."""
    if len(data) > MAX_IMAGE_BYTES:
        raise InvalidImage("크기 초과")
    if data.startswith(_JPEG_MAGIC):
        fmt = "JPEG"
    elif data.startswith(_PNG_MAGIC):
        fmt = "PNG"
    else:
        raise InvalidImage("JPEG·PNG가 아니다")
    try:
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            real = im.format
    except (Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        raise InvalidImage("이미지를 열 수 없다") from None
    if real != fmt:
        raise InvalidImage("머리 바이트와 형식이 다르다")
    if w <= 0 or h <= 0 or w * h > MAX_PIXELS:
        raise InvalidImage("픽셀 수 초과")
    return ImageInfo(fmt, w, h)


# ---------------------------------------------------------------- 전처리
def image_tokens_estimate(width: int, height: int) -> int:
    """`vision_pouch_test.image_tokens_estimate`와 같은 근사((가로 x 세로)/750)."""
    return int(width * height / 750) + 1


def prepare_image(data: bytes, info: ImageInfo, *, resize: bool = True) -> tuple[str, int]:
    """(data URL, 예상 이미지 토큰). resize면 긴 변을 1400px로 맞춘 JPEG q92. 메모리만 쓴다(파일 0)."""
    if not resize:
        media = "image/png" if info.format == "PNG" else "image/jpeg"
        return f"data:{media};base64,{base64.standard_b64encode(data).decode()}", image_tokens_estimate(info.width, info.height)
    try:
        with Image.open(io.BytesIO(data)) as im:
            rgb = im.convert("RGB")
    except (Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        raise InvalidImage("이미지를 읽을 수 없다") from None
    scale = LONG_SIDE / max(rgb.size)
    size = (max(1, int(rgb.size[0] * scale)), max(1, int(rgb.size[1] * scale)))
    big = rgb.resize(size, Image.LANCZOS)
    buf = io.BytesIO()
    big.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return f"data:image/jpeg;base64,{base64.standard_b64encode(buf.getvalue()).decode()}", image_tokens_estimate(*size)


# ---------------------------------------------------------------- 지시문·비용
_PROMPT_CACHE: dict[Path, str] = {}


def load_system_prompt(path: Path = PROMPT_PATH) -> str:
    """지시문 본문(프런트매터 제외). 파일은 한 번만 읽는다."""
    if path not in _PROMPT_CACHE:
        _, body = split_frontmatter(path.read_text(encoding="utf-8"))
        _PROMPT_CACHE[path] = body.strip()
    return _PROMPT_CACHE[path]


def worst_cost(system: str, img_tokens: int) -> float:
    """호출 전 최악 비용(`vision_pouch_test.worst_cost`의 openai 식): (글자 토큰 + 이미지 토큰) x 3 + 1000, 출력은 최대치."""
    text_tokens = (len(system) + len(USER_TEXT) + len(json.dumps(SCHEMA))) / 1.5
    in_tok = (text_tokens + img_tokens) * 3 + 1000
    return in_tok * PRICE_IN_PER_M / 1e6 + MAX_COMPLETION_TOKENS * PRICE_OUT_PER_M / 1e6


def actual_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return prompt_tokens * PRICE_IN_PER_M / 1e6 + completion_tokens * PRICE_OUT_PER_M / 1e6


def build_messages(system: str, data_url: str) -> list[dict[str, Any]]:
    return [{"role": "system", "content": system},
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_url}},
                                         {"type": "text", "text": USER_TEXT}]}]


RESPONSE_FORMAT: dict[str, Any] = {"type": "json_schema", "json_schema": {"name": "pouch_drugs", "strict": True, "schema": SCHEMA}}


# ---------------------------------------------------------------- 출력 정리(PRD-08-04)
def _clean_str(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    v = v.strip()
    if not v or v.lower() in {"null", "none", "unknown", "n/a"}:
        return None
    return v[:MAX_STR]


def _leaks(v: str) -> bool:
    return any(p.search(v) for p in LEAK_PATTERNS.values())


def sanitize(raw: Any) -> tuple[list[dict[str, str | None]], list[str]]:
    """허용 3칸만 남긴 약 목록과 버린 칸·사유 이름 목록(값은 담지 않는다)."""
    dropped: list[str] = []
    if not isinstance(raw, dict):
        return [], ["<not-an-object>"]
    dropped += [f"top.{k}" for k in raw if k not in ("drugs", "unreadable_note")]
    items = raw.get("drugs")
    if not isinstance(items, list):
        return [], [*dropped, "drugs.<not-a-list>"]
    out: list[dict[str, str | None]] = []
    for d in items:
        if not isinstance(d, dict):
            dropped.append("drugs[].<not-an-object>")
            continue
        dropped += [f"drugs[].{k}" for k in d if k not in ALLOWED_DRUG_FIELDS]
        item: dict[str, str | None] = {k: _clean_str(d.get(k)) for k in OUT_FIELDS}
        for k in OUT_FIELDS:
            v = item[k]
            if v is not None and _leaks(v):
                item[k] = None
                dropped.append(f"drugs[].{k}:leak")
        sf = item["strength_or_form"]
        if sf is not None and not STRENGTH_FORM_OK.match(re.sub(r"\s+", "", sf)):
            item["strength_or_form"] = None  # 색·모양·복용 횟수 같은 값
            dropped.append("drugs[].strength_or_form:off_field")
        if not (item["product_name"] or item["ingredient_name"]):
            dropped.append("drugs[].<no-name>")
            continue
        out.append(item)
        if len(out) >= MAX_DRUGS:
            break
    return out, dropped


def parse_output(text: str | None) -> dict[str, Any] | None:
    """모델 출력 → JSON 객체. 잘림·형식 오류면 None."""
    t = (text or "").strip()
    if not t:
        return None
    try:
        obj = json.loads(t[t.find("{"): t.rfind("}") + 1])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


# ---------------------------------------------------------------- 기본 클라이언트(OpenAI SDK)
class OpenAIVisionClient:
    """`openai.OpenAI().chat.completions.create` 감싸기. 키는 Settings에서 읽고 출력·기록하지 않는다. SDK 자체 재시도는 끈다."""

    def __init__(self, api_key: str | None = None) -> None:
        import openai

        if api_key is None:
            from app.config import get_settings, reveal

            api_key = reveal(get_settings().openai_api_key)
        self._openai = openai
        self._client = openai.OpenAI(api_key=api_key or "missing", max_retries=0, timeout=TIMEOUT_S)

    def complete(self, *, model: str, messages: list[dict[str, Any]], max_completion_tokens: int,
                 response_format: dict[str, Any], timeout: float) -> Completion:
        o = self._openai
        try:
            r = self._client.chat.completions.create(model=model, messages=messages, max_completion_tokens=max_completion_tokens,  # type: ignore[arg-type]
                                                     response_format=response_format, timeout=timeout)  # type: ignore[arg-type]
        except (o.RateLimitError, o.APIConnectionError, o.APITimeoutError, o.InternalServerError) as exc:
            raise TransientVisionError(type(exc).__name__) from None
        ch = r.choices[0]
        u = r.usage
        return Completion(content=ch.message.content, refusal=getattr(ch.message, "refusal", None), finish_reason=ch.finish_reason,
                          prompt_tokens=int(getattr(u, "prompt_tokens", 0) or 0), completion_tokens=int(getattr(u, "completion_tokens", 0) or 0))


# ---------------------------------------------------------------- 추출
def extract(data: bytes, *, client: VisionClient | Callable[[], VisionClient], ledger: CostLedger, resize: bool = True,
            sleep: Callable[[float], None] = time.sleep, prompt_path: Path = PROMPT_PATH) -> VisionResult:
    """이미지 바이트 1장 → 약 이름 후보(허용 3칸). 형식·크기 위반은 InvalidImage를 올린다(그 밖의 실패는 결과의 status·reason)."""
    info = check_image(data)
    data_url, img_tok = prepare_image(data, info, resize=resize)
    system = load_system_prompt(prompt_path)
    try:
        ledger.guard(worst_cost(system, img_tok), bucket=LEDGER_BUCKET)
    except (BudgetExceeded, OSError, ValueError):  # 상한, 원장 읽기 실패는 닫힌 쪽(호출 없음)
        return VisionResult("UNAVAILABLE", "CAP_REACHED")
    messages = build_messages(system, data_url)
    del data_url
    t0 = time.monotonic()
    comp: Completion | None = None
    attempts = 0
    try:
        cl = client if hasattr(client, "complete") else client()  # 공급자(지연 생성)도 받는다: 키 없음 등 생성 실패는 MODEL_ERROR
        for attempt in range(RETRIES + 1):
            attempts = attempt + 1
            try:
                comp = cl.complete(model=MODEL, messages=messages, max_completion_tokens=MAX_COMPLETION_TOKENS,  # type: ignore[union-attr]
                                   response_format=RESPONSE_FORMAT, timeout=TIMEOUT_S)
                break
            except TransientVisionError:
                if attempt < RETRIES:
                    sleep(0.5 * 2 ** attempt)
    except Exception:  # noqa: BLE001 - 모델·SDK 예외는 "읽지 못함"(호출자가 종류 이름만 기록)
        comp = None
    latency = round(time.monotonic() - t0, 3)
    if comp is None:
        return VisionResult("UNREADABLE", "MODEL_ERROR", latency_s=latency, attempts=attempts)
    usd = actual_cost(comp.prompt_tokens, comp.completion_tokens)
    try:
        ledger.add(usd, bucket=LEDGER_BUCKET)
    except (OSError, ValueError):
        pass  # 기록 실패는 응답을 막지 않는다(다음 호출의 guard가 원장 읽기 실패로 닫힌다)
    base = {"in_tokens": comp.prompt_tokens, "out_tokens": comp.completion_tokens, "usd": round(usd, 6), "latency_s": latency,
            "attempts": attempts}
    if comp.refusal:
        return VisionResult("UNREADABLE", "REFUSED", **base)
    raw = parse_output(comp.content)
    if raw is None or comp.finish_reason == "length":
        return VisionResult("UNREADABLE", "PARSE_ERROR", raw=raw, **base)
    drugs, dropped = sanitize(raw)
    if not drugs:
        return VisionResult("UNREADABLE", "NONE_READ", raw=raw, dropped=dropped, **base)
    return VisionResult("OK", None, drugs=drugs, raw=raw, dropped=dropped, **base)


__all__ = ["LEDGER_BUCKET", "MAX_IMAGE_BYTES", "MAX_PIXELS", "MODEL", "SCHEMA", "Completion", "ImageInfo", "InvalidImage",
           "OpenAIVisionClient", "TransientVisionError", "VisionClient", "VisionResult", "check_image", "decode_data_url", "extract",
           "prepare_image", "sanitize"]
