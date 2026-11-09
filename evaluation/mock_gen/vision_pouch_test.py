"""약봉투 사진 약 이름 추출 작은 시험(PRD-08-02 A 후보: Claude Haiku 4.5 비전).

사용:
    .venv/bin/python evaluation/mock_gen/vision_pouch_test.py run      # API 호출(이미지 4장 x 3회), results.json 저장
    .venv/bin/python evaluation/mock_gen/vision_pouch_test.py run --upscale  # 보조 조건: 메모리에서 긴 변 1400px로 확대해 보냄
    .venv/bin/python evaluation/mock_gen/vision_pouch_test.py grade [--upscale]  # 호출 없이 채점만 다시
    .venv/bin/python evaluation/mock_gen/vision_pouch_test.py lookup   # 호출 없이 로컬 DUR CSV·허가정보 스냅샷에서 이름 포함 일치
    .venv/bin/python evaluation/mock_gen/vision_pouch_test.py suggest  # 호출 없이 추출 이름별 사전 후보 top-5에 정답이 드는지
    .venv/bin/python evaluation/mock_gen/vision_pouch_test.py probe --provider openai   # gpt-6-luna 이미지 입력 지원 확인(1회)
    .venv/bin/python evaluation/mock_gen/vision_pouch_test.py run [--upscale] --provider openai  # gpt-6-luna로 같은 시험
    공통 옵션 --provider openai: gpt-6-luna(OPENAI_API_KEY). 결과·채점·원장 파일에 _luna/_openai가 붙어 Haiku 파일과 섞이지 않는다.
    공통 옵션 --labels <경로>: 정답 파일을 고른다(기본 labels_draft.json). labels_<이름>.json이면
    결과는 grade_<이름>[_upscaled].json·lookup_<이름>.json·suggest_<이름>.json으로 따로 쓴다(기존 결과를 덮어쓰지 않음).

원칙
- 키는 환경변수 ANTHROPIC_API_KEY로만 읽는다(_common과 같이 dotenv). 키 값과 이미지 base64는 출력·기록하지 않는다.
- 입력 이미지는 mock/medi-packet/(git 제외)에만 있고, 결과도 mock/vision_test/(git 제외)에만 쓴다.
  이 스크립트에는 이미지 내용·약 이름 정답·개인정보가 들어 있지 않다.
- 비용 상한 1 USD를 별도 원장 mock/vision_test/ledger.json으로 강제한다(호출 전 최악 비용을 더해 넘으면 중단).
- 출력은 JSON 스키마(structured outputs)로 받고, 코드가 다시 허용 필드만 남긴다(PRD-08-04: 약 이름 외 필드는 버린다).
- Haiku 4.5는 temperature를 거부하므로 지정하지 않는다(_common.py 주석, 2026-11-04 확인).
- 소표본(4장)이라 k/n만 기록한다. 정확도 일반화·유의성을 주장하지 않는다(CLAUDE.md 5장).
"""
from __future__ import annotations

import base64
import csv
import hashlib
import json
import re
import sys
import time
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import HAIKU, PRICES  # noqa: E402  (가격표 공유, 원장은 따로 쓴다)

IMG_DIR = ROOT / "mock" / "medi-packet"
OUT = ROOT / "mock" / "vision_test"
LEDGER = OUT / "ledger.json"
CALLS = OUT / "calls.jsonl"
RESULTS = OUT / "results.json"
LABELS = OUT / "labels_draft.json"
GRADE = OUT / "grade.json"
LOOKUP = OUT / "lookup.json"

MODEL = HAIKU
CAP_USD = 1.0
PROVIDER = "anthropic"          # --provider openai 이면 아래 OpenAI 값으로 바뀐다(__main__)
LUNA = "gpt-6-luna"
OPENAI_PRICES = {LUNA: (0.10, 0.50)}  # USD/100만 토큰, tickets/doc/RFP-15.md §8.2(2026-11-04 문서 조회 값)
OPENAI_CAP_USD = 0.5
OPENAI_MAX_COMPLETION = 4000    # 추론 토큰이 출력에 포함될 수 있어 Haiku(1200)보다 넉넉히 둔다(값은 상한일 뿐)
RUNS = 3
MAX_TOKENS = 1200
MAX_STR = 80  # 필드 값 최대 길이(넘으면 자른다)

ALLOWED_DRUG_FIELDS = ("product_name", "ingredient_name", "strength_or_form", "confidence")
CONFIDENCE = ("high", "medium", "low")

SCHEMA = {
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

SYSTEM = (
    "너는 약봉투·복약안내문 사진에서 약 정보만 옮겨 적는 추출기다.\n"
    "규칙:\n"
    "1. 사진에 인쇄된 약 이름(상품명), 성분명, 용량/제형만 뽑는다.\n"
    "2. 환자 이름, 나이, 병원·의원 이름, 약국 이름, 약사·의사 이름, 전화번호, 주소, 금액, 날짜는 절대 쓰지 않는다.\n"
    "3. 사진에 성분명이 인쇄되어 있지 않으면 ingredient_name은 null이다. 상품명을 보고 성분명을 추측해 채우지 않는다.\n"
    "4. 글자가 안 보이거나 흐리면 해당 값은 null로 두고 confidence를 low로 한다. 추측해서 약 이름을 만들지 않는다.\n"
    "5. 읽지 못한 약이 있거나 사진 일부가 잘렸으면 unreadable_note에 짧게 적는다(개인정보 없이). 없으면 null.\n"
    "6. 효능 설명·복용법·주의사항 문구는 옮기지 않는다.\n"
    "출력은 지정된 JSON 스키마만."
)
USER_TEXT = "이 사진에 있는 약을 모두 위 규칙대로 JSON으로 적어라."

# 개인정보 유출 의심 패턴(출력 값에서 검사). 약 이름에 쓰일 일이 거의 없는 것만 둔다.
LEAK_PATTERNS = {
    "phone": re.compile(r"\d{2,4}-\d{3,4}-\d{4}"),
    "facility": re.compile(r"(병원|의원|약국|보건소|클리닉)"),
    "person_field": re.compile(r"(환자|성명|약사|조제자|주소|연락처)"),
}


# ---------------------------------------------------------------- 비용 원장
def spent() -> float:
    return json.loads(LEDGER.read_text())["usd"] if LEDGER.exists() else 0.0


def image_tokens_estimate(path: Path) -> int:
    """Anthropic 안내 근사: (가로 x 세로)/750 토큰. 크기를 못 읽으면 보수적으로 1600."""
    try:
        from PIL import Image  # 선택 의존(.venv에 있음)

        with Image.open(path) as im:
            w, h = im.size
        return int(w * h / 750) + 1
    except Exception:  # noqa: BLE001
        return 1600


def price() -> tuple[float, float]:
    return OPENAI_PRICES[MODEL] if PROVIDER == "openai" else PRICES[MODEL]


def worst_cost(path: Path, img_tok: int | None = None) -> float:
    in_p, out_p = price()
    if PROVIDER == "openai":  # 이미지 토큰 계산 방식이 달라 추정의 3배 + 최대 출력으로 보수적으로 잡는다
        text_tokens = (len(SYSTEM) + len(USER_TEXT) + len(json.dumps(SCHEMA))) / 1.5
        in_tok = (text_tokens + (img_tok or image_tokens_estimate(path))) * 3 + 1000
        return in_tok * in_p / 1e6 + OPENAI_MAX_COMPLETION * out_p / 1e6
    text_tokens = (len(SYSTEM) + len(USER_TEXT) + len(json.dumps(SCHEMA))) / 1.5  # 한글은 글자당 토큰이 많으므로 보수적
    in_tok = (text_tokens + (img_tok or image_tokens_estimate(path))) * 1.5 + 500  # 스키마 시스템 프롬프트 등 여유
    return in_tok * in_p / 1e6 + MAX_TOKENS * out_p / 1e6


# ---------------------------------------------------------------- 출력 검증(PRD-08-04)
def _clean_str(v):
    if v is None:
        return None
    if not isinstance(v, str):
        return None
    v = v.strip()
    if not v or v.lower() in {"null", "none", "unknown", "n/a"}:
        return None
    return v[:MAX_STR]


def sanitize(raw) -> tuple[dict, list[str]]:
    """허용 필드만 남긴다. 버린 키 이름 목록을 함께 돌려준다(값은 기록하지 않는다)."""
    dropped: list[str] = []
    if not isinstance(raw, dict):
        return {"drugs": [], "unreadable_note": None}, ["<not-an-object>"]
    dropped += [f"top.{k}" for k in raw if k not in ("drugs", "unreadable_note")]
    drugs = []
    for d in raw.get("drugs") or []:
        if not isinstance(d, dict):
            dropped.append("drugs[].<not-an-object>")
            continue
        dropped += [f"drugs[].{k}" for k in d if k not in ALLOWED_DRUG_FIELDS]
        item = {k: _clean_str(d.get(k)) for k in ALLOWED_DRUG_FIELDS[:3]}
        conf = d.get("confidence")
        item["confidence"] = conf if conf in CONFIDENCE else "low"
        if any(item[k] for k in ALLOWED_DRUG_FIELDS[:3]):
            drugs.append(item)
    return {"drugs": drugs, "unreadable_note": _clean_str(raw.get("unreadable_note"))}, dropped


STRENGTH_FORM_OK = re.compile(r"^[\d\.\s,/~]*(mg|g|ml|mcg|㎎|㎖|%|밀리그램|정|캡슐|캡셀|정제|필름코팅정제?|경질캡슐|연질캡슐|"
                              r"현탁액|시럽|액|경구액|연고|안연고|크림|산|과립)?[\s\d\.mgl㎎㎖]*$", re.I)


def off_field_values(clean: dict) -> int:
    """strength_or_form 값이 함량·제형 어휘로만 이루어지지 않은 개수(예: 복용 횟수·약효 분류 문구가 들어온 경우)."""
    return sum(1 for d in clean["drugs"] if d.get("strength_or_form") and not STRENGTH_FORM_OK.match(
        re.sub(r"\s+", "", d["strength_or_form"])))


def leak_hits(clean: dict) -> list[str]:
    """정제 뒤 값에서 개인정보 의심 패턴 종류만 돌려준다(값 자체는 돌려주지 않는다)."""
    vals = [clean.get("unreadable_note") or ""]
    for d in clean["drugs"]:
        vals += [d.get(k) or "" for k in ALLOWED_DRUG_FIELDS[:3]]
    hits = set()
    for v in vals:
        for name, pat in LEAK_PATTERNS.items():
            if pat.search(v):
                hits.add(name)
    return sorted(hits)


# ---------------------------------------------------------------- API 호출
UPSCALE_LONG_SIDE = 1400  # 보조 조건: 작은 사진을 메모리에서 확대해 보낸다(파일로 저장하지 않음)


def image_payload(path: Path, upscale: bool) -> tuple[str, str, int]:
    """(media_type, base64, 예상 이미지 토큰). upscale이면 긴 변을 UPSCALE_LONG_SIDE로 LANCZOS 확대한 JPEG."""
    if not upscale:
        media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return media, base64.standard_b64encode(path.read_bytes()).decode(), image_tokens_estimate(path)
    import io

    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        scale = UPSCALE_LONG_SIDE / max(im.size)
        size = (int(im.size[0] * scale), int(im.size[1] * scale))
        big = im.resize(size, Image.LANCZOS)
    buf = io.BytesIO()
    big.save(buf, format="JPEG", quality=92)
    return "image/jpeg", base64.standard_b64encode(buf.getvalue()).decode(), int(size[0] * size[1] / 750) + 1


def call_image_openai(path: Path, tag: str, upscale: bool = False) -> dict:
    """gpt-6-luna Chat Completions: 이미지(data URL) + 같은 지시문, 같은 JSON 스키마를 response_format strict로 받는다.
    temperature·reasoning_effort 등 거부될 수 있는 인자는 넣지 않는다. 키·base64는 기록하지 않는다."""
    import openai
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")  # 값은 읽기만 하고 출력하지 않는다
    media, data, img_tok = image_payload(path, upscale)
    worst = worst_cost(path, img_tok)
    if spent() + worst > CAP_USD:
        raise SystemExit(f"중단: 누적 ${spent():.4f} + 예상 최대 ${worst:.4f} > 상한 ${CAP_USD}")
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{media};base64,{data}"}},
                    {"type": "text", "text": USER_TEXT}]}]
    client = openai.OpenAI()
    r = None
    for attempt in range(4):
        try:
            r = client.chat.completions.create(
                model=MODEL, messages=messages, max_completion_tokens=OPENAI_MAX_COMPLETION,
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "pouch_drugs", "strict": True, "schema": SCHEMA}})
            break
        except (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError):
            time.sleep(2 ** attempt * 2)
    if r is None:
        raise SystemExit("API 재시도 실패")
    u = r.usage
    in_tok, out_tok = u.prompt_tokens, u.completion_tokens
    reasoning = getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", None)
    in_p, out_p = price()
    cost = in_tok * in_p / 1e6 + out_tok * out_p / 1e6
    LEDGER.write_text(json.dumps({"usd": round(spent() + cost, 6), "cap_usd": CAP_USD}))
    ch = r.choices[0]
    refusal = getattr(ch.message, "refusal", None)
    with CALLS.open("a") as f:
        f.write(json.dumps({"ts": time.strftime("%F %T"), "tag": tag, "model": MODEL, "mode": "structured",
                            "in": in_tok, "out": out_tok, "reasoning": reasoning, "usd": round(cost, 6),
                            "image_sha": hashlib.sha1(path.read_bytes()).hexdigest()[:10], "upscale": upscale,
                            "stop_reason": ch.finish_reason, "refusal": bool(refusal)}) + "\n")
    text = ch.message.content or ""
    parse_ok = True
    try:
        raw = json.loads(text[text.find("{"): text.rfind("}") + 1])
    except Exception:  # noqa: BLE001
        raw, parse_ok = None, False
    clean, dropped = sanitize(raw)
    return {"tag": tag, "mode": "structured", "parse_ok": parse_ok, "stop_reason": ch.finish_reason,
            "refusal": bool(refusal), "in_tokens": in_tok, "out_tokens": out_tok, "reasoning_tokens": reasoning,
            "usd": round(cost, 6), "dropped_keys": dropped, "leak_hits": leak_hits(clean), "output": clean}


def probe() -> dict:
    """이미지 1장(가장 작은 004 아님, 001 원본) 1회로 이미지 입력 지원을 확인한다. 실패하면 오류 종류와 메시지 앞부분만 남긴다."""
    import openai

    OUT.mkdir(parents=True, exist_ok=True)
    img = sorted(p for p in IMG_DIR.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))[0]
    rec = {"ts": time.strftime("%F %T"), "model": MODEL, "api": "chat.completions + image_url(data URL) + response_format json_schema strict",
           "image": img.name}
    try:
        res = call_image_openai(img, tag=f"{img.stem}-probe")
        rec.update(supported=True, parse_ok=res["parse_ok"], n_drugs=len(res["output"]["drugs"]), in_tokens=res["in_tokens"],
                   out_tokens=res["out_tokens"], reasoning_tokens=res["reasoning_tokens"], usd=res["usd"],
                   stop_reason=res["stop_reason"], refusal=res["refusal"])
    except openai.APIStatusError as e:  # 키·이미지 내용이 섞이지 않도록 메시지는 앞 200자만, 키 패턴은 가린다
        msg = re.sub(r"sk-[A-Za-z0-9_\-]+", "sk-***", str(getattr(e, "message", e)))[:200]
        # 401·403(인증·권한)은 이미지 지원 여부와 무관하므로 supported=None(확인 못 함). 400 등 요청 거부만 False로 본다.
        supported = None if e.status_code in (401, 403) else False
        rec.update(supported=supported, error_type=type(e).__name__, http_status=e.status_code, error=msg)
    (OUT / "probe_luna.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    print(json.dumps(rec, ensure_ascii=False))
    return rec


def call_image(path: Path, tag: str, upscale: bool = False) -> dict:
    if PROVIDER == "openai":
        return call_image_openai(path, tag, upscale)
    import anthropic
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")  # 값은 읽기만 하고 출력하지 않는다
    media, data, img_tok = image_payload(path, upscale)
    worst = worst_cost(path, img_tok)
    if spent() + worst > CAP_USD:
        raise SystemExit(f"중단: 누적 ${spent():.4f} + 예상 최대 ${worst:.4f} > 상한 ${CAP_USD}")
    messages = [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}},
        {"type": "text", "text": USER_TEXT},
    ]}]
    client = anthropic.Anthropic()
    mode = "structured"
    r = None
    for attempt in range(4):
        try:
            if mode == "structured":
                r = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM, messages=messages,
                                           output_config={"format": {"type": "json_schema", "schema": SCHEMA}})
            else:
                r = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS,
                                           system=SYSTEM + "\nJSON 스키마:\n" + json.dumps(SCHEMA, ensure_ascii=False),
                                           messages=messages)
            break
        except anthropic.BadRequestError as e:  # structured outputs 미지원 등 → 프롬프트 JSON으로 한 번 전환
            if mode == "structured":
                mode = "prompt_json"
                print(f"  structured outputs 거부({type(e).__name__}), 프롬프트 JSON으로 전환")
                continue
            raise
        except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError):
            time.sleep(2 ** attempt * 2)
    if r is None:
        raise SystemExit("API 재시도 실패")
    in_p, out_p = PRICES[MODEL]
    cost = r.usage.input_tokens * in_p / 1e6 + r.usage.output_tokens * out_p / 1e6
    LEDGER.write_text(json.dumps({"usd": round(spent() + cost, 6), "cap_usd": CAP_USD}))
    with CALLS.open("a") as f:
        f.write(json.dumps({"ts": time.strftime("%F %T"), "tag": tag, "model": MODEL, "mode": mode,
                            "in": r.usage.input_tokens, "out": r.usage.output_tokens, "usd": round(cost, 6),
                            "image_sha": hashlib.sha1(path.read_bytes()).hexdigest()[:10], "upscale": upscale,
                            "stop_reason": r.stop_reason}) + "\n")
    text = "".join(b.text for b in r.content if b.type == "text")
    parse_ok = True
    try:
        t = text.strip()
        if t.startswith("```"):
            t = t.split("\n", 1)[1].rsplit("```", 1)[0]
        raw = json.loads(t[t.find("{"): t.rfind("}") + 1])
    except Exception:  # noqa: BLE001
        raw, parse_ok = None, False
    clean, dropped = sanitize(raw)
    return {"tag": tag, "mode": mode, "parse_ok": parse_ok, "stop_reason": r.stop_reason,
            "in_tokens": r.usage.input_tokens, "out_tokens": r.usage.output_tokens, "usd": round(cost, 6),
            "dropped_keys": dropped, "leak_hits": leak_hits(clean), "output": clean}


def labels_tag() -> str:
    """정답 파일이 기본(labels_draft.json)이면 ''. labels_<이름>.json이면 '_<이름>'(출력 파일 이름에 붙인다)."""
    if LABELS.resolve() == (OUT / "labels_draft.json").resolve():
        return ""
    stem = LABELS.stem
    return "_" + (stem[len("labels_"):] if stem.startswith("labels_") else stem)


def paths(upscale: bool) -> tuple[Path, Path]:
    """조건별 결과·채점 파일. 기본(원본 크기)은 results.json·grade.json, 보조(확대)는 *_upscaled.json.
    --labels로 다른 정답을 고르면 채점 파일만 grade_<이름>[_upscaled].json으로 바꾼다(결과 파일은 그대로 읽기만)."""
    t = labels_tag()
    if PROVIDER == "openai":  # gpt-6-luna: results_luna[_upscaled].json, grade_luna<정답>[_upscaled].json
        up = "_upscaled" if upscale else ""
        return OUT / f"results_luna{up}.json", OUT / f"grade_luna{t}{up}.json"
    if not upscale:
        return RESULTS, (OUT / f"grade{t}.json" if t else GRADE)
    return OUT / "results_upscaled.json", OUT / f"grade{t}_upscaled.json"


def run(upscale: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    res_path, _ = paths(upscale)
    images = sorted(p for p in IMG_DIR.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    results = {"model": MODEL, "runs": RUNS, "cap_usd": CAP_USD, "upscale_long_side": UPSCALE_LONG_SIDE if upscale else None,
               "started": time.strftime("%F %T"), "images": {}}
    for p in images:
        results["images"][p.name] = []
        for k in range(1, RUNS + 1):
            res = call_image(p, tag=f"{p.stem}{'-up' if upscale else ''}-run{k}", upscale=upscale)
            results["images"][p.name].append(res)
            print(f"{p.name} run{k}: drugs={len(res['output']['drugs'])} in={res['in_tokens']} "
                  f"out={res['out_tokens']} ${res['usd']:.5f} mode={res['mode']}")
    results["finished"] = time.strftime("%F %T")
    results["ledger_usd"] = spent()
    res_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"저장: {res_path.relative_to(ROOT)}  누적 ${spent():.5f} / 상한 ${CAP_USD}")


# ---------------------------------------------------------------- 채점
# 정규화 규칙(상품명 일치 판정):
#  1) 유니코드 NFKC, 소문자, 모든 공백 제거
#  2) 괄호와 괄호 안 내용 제거: "테라마이신안연고(성형)" -> "테라마이신안연고"
#  3) 함량 표기 제거: 숫자(+소수점) 뒤에 mg|밀리그램|g|그램|ml|밀리리터|mcg|㎎|㎖ -> 삭제 ("150mg" 유무 차이 허용)
#  4) 표기 흔들림 통일: "캡셀" -> "캡슐"
#  5) 끝의 제형 접미사 한 개 제거: 필름코팅정|서방정|연질캡슐|경질캡슐|캡슐|정|현탁액|시럽|안연고|연고|액 ("정" 유무 차이 허용)
#  일치 = 정규화 결과가 같음. 부분 포함은 일치로 보지 않는다(환각 판정을 느슨하게 하지 않기 위해).
NEAR_RATIO = 0.6
FORM_SUFFIX = ("필름코팅정", "서방정", "연질캡슐", "경질캡슐", "캡슐", "정", "현탁액", "시럽", "안연고", "연고", "액")
STRENGTH = re.compile(r"\d+(?:\.\d+)?(?:mg|밀리그램|g|그램|ml|밀리리터|mcg|㎎|㎖)")


def norm_name(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[\(\[\{（][^\)\]\}）]*[\)\]\}）]", "", s)
    s = STRENGTH.sub("", s)
    s = s.replace("캡셀", "캡슐")
    for suf in FORM_SUFFIX:
        if s.endswith(suf) and len(s) > len(suf):
            s = s[: -len(suf)]
            break
    return s.strip("-_/.,[]")


def norm_ingr(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"\s+", "", s)
    return STRENGTH.sub("", s)


def grade(upscale: bool = False) -> dict:
    res_path, grade_path = paths(upscale)
    lab_doc = json.loads(LABELS.read_text())
    labels = lab_doc["images"]
    results = json.loads(res_path.read_text())
    out = {"normalization": "NFKC·소문자·공백 제거, 괄호 내용 제거, 함량(숫자+mg/ml 등) 제거, 캡셀→캡슐, 끝 제형 접미사 1개 제거; 정규화 결과 완전 일치만 인정",
           "labels_file": LABELS.name, "labels_status": lab_doc.get("_meta", {}).get("status", ""), "images": {}, "total": {}}
    T = Counter()
    for img, runs in results["images"].items():
        lab = labels[img]["drugs"]
        gold = {norm_name(d["product_name"]): d for d in lab if d["product_name"] != "unreadable"}
        gold_ingr = {norm_ingr(d["ingredient_name"]) for d in lab if d["ingredient_name"]}
        unclear = {norm_name(d["product_name"]) for d in lab if d.get("legibility") == "unclear"}
        per_run, name_sets = [], []
        for r in runs:
            preds = r["output"]["drugs"]
            pnames = [norm_name(d["product_name"]) for d in preds if d["product_name"]]
            pset = set(pnames)
            name_sets.append(frozenset(pset))
            matched = sorted(pset & set(gold))
            halluc = sorted(pset - set(gold))
            # 근접 오독(참고): 일치하지 않은 예측 중 정답 이름과 글자 유사도(difflib ratio) >= NEAR_RATIO인 것.
            # 사전 매칭·확인 카드로 되살릴 수 있는 후보의 대략적 규모를 보려는 것이며 일치로 세지 않는다.
            near = sum(1 for h in halluc if any(SequenceMatcher(None, h, g).ratio() >= NEAR_RATIO for g in gold))
            ingr_out = [d["ingredient_name"] for d in preds if d["ingredient_name"]]
            ingr_match = len({norm_ingr(x) for x in ingr_out} & gold_ingr)
            # 정직한 불확실 표시: 흐린(unclear) 약에 대해 모델이 low/medium으로 표시했거나, 이름을 null로 두었거나,
            # unreadable_note를 남겼는가. 흐린 약을 high로 확신하며 틀리게 적은 경우가 '정직하지 않음'.
            # 규칙: 흐린 약을 맞게 읽었으면 정직(1). 못 맞혔으면 (a) 틀린 이름을 high로 내지 않았고
            # (b) unreadable_note·이름 null·low/medium 표시 중 하나로 불확실을 드러냈을 때만 정직(1).
            wrong_high = any(norm_name(d["product_name"]) not in gold and d["confidence"] == "high"
                             for d in preds if d["product_name"])
            flagged = bool(r["output"]["unreadable_note"]) or any(
                (not d["product_name"]) or d["confidence"] != "high"
                for d in preds if norm_name(d["product_name"]) not in gold)
            honest = sum(1 for u in unclear if u in pset or (flagged and not wrong_high))
            per_run.append({
                "tag": r["tag"], "n_pred": len(preds), "matched": len(matched), "n_gold": len(gold),
                "hallucinated": len(halluc), "near_miss": near, "hallucinated_norm": halluc, "missed_norm": sorted(set(gold) - pset),
                "ingredient_out": len(ingr_out), "ingredient_match": ingr_match, "ingredient_gold": len(gold_ingr),
                "ingredient_out_values": ingr_out,
                "high_conf_wrong": sum(1 for d in preds if d["product_name"] and norm_name(d["product_name"]) not in gold and d["confidence"] == "high"),
                "unclear_honest": honest, "unclear_n": len(unclear),
                "unreadable_note": r["output"]["unreadable_note"],
                "leak": bool(r["leak_hits"] or r["dropped_keys"]),  # 의심 표시(패턴은 '환자정보 가려짐' 같은 언급에도 걸린다 → 사람 확인) "leak_hits": r["leak_hits"], "dropped_keys": r["dropped_keys"],
                "parse_ok": r["parse_ok"], "off_field_values": off_field_values(r["output"]),
            })
            for k in ("matched", "n_gold", "hallucinated", "near_miss", "ingredient_out", "ingredient_match", "ingredient_gold",
                      "unclear_honest", "unclear_n", "high_conf_wrong", "n_pred", "off_field_values"):
                T[k] += per_run[-1][k]
            T["leak_runs"] += int(per_run[-1]["leak"])
            T["runs"] += 1
            T["parse_ok"] += int(r["parse_ok"])
        hit_once = sorted(g for g in gold if any(g in ns for ns in name_sets))
        T["drugs_hit_once"] += len(hit_once)
        T["drugs_n"] += len(gold)
        modal, cnt = Counter(name_sets).most_common(1)[0]
        out["images"][img] = {"runs": per_run, "agreement": f"{cnt}/{len(runs)}", "drugs_hit_once": hit_once,
                              "modal_name_set": sorted(modal)}
        T["agree_k"] += cnt
        T["agree_n"] += len(runs)
        T["all3_same"] += int(cnt == len(runs))
        T["images"] += 1
    out["total"] = dict(T)
    out["condition"] = "upscaled" if upscale else "original"
    grade_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"[{LABELS.name} / {out['condition']}] 한 번이라도 맞힌 약 {T['drugs_hit_once']}/{T['drugs_n']}, 확신도 high 환각 {T['high_conf_wrong']}, 근접 오독 {T['near_miss']}")
    print(f"상품명 일치 {T['matched']}/{T['n_gold']} (3회 합산), 환각 {T['hallucinated']}건, "
          f"성분명 출력 {T['ingredient_out']}건(정답 성분 {T['ingredient_gold']}), "
          f"유출 의심 실행 {T['leak_runs']}/{T['runs']}, 3회 동일 집합 이미지 {T['all3_same']}/{T['images']}, "
          f"흐린 약 정직 표시 {T['unclear_honest']}/{T['unclear_n']}")
    return out


# ---------------------------------------------------------------- 로컬 사전 조회(API 호출 없음)
def load_catalogs() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(DUR 품목리스트 정규화 이름 -> 제품코드, 허가정보 스냅샷 정규화 이름 -> 품목기준코드). 네트워크를 쓰지 않는다."""
    catalog: dict[str, set[str]] = {}  # 정규화 제품명 -> 제품코드 집합
    dur_files = [f for f in sorted((ROOT / "data").iterdir())  # macOS 파일 이름은 NFD일 수 있어 NFC로 맞춰 고른다
                 if f.suffix == ".csv" and "품목리스트" in unicodedata.normalize("NFC", f.name)]
    for f in dur_files:
        with f.open(encoding="cp949", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh):
                for nk, ck in (("제품명", "제품코드"), ("제품명A", "제품코드A"), ("제품명B", "제품코드B")):
                    if row.get(nk):
                        base = row[nk].split("_")[0]
                        catalog.setdefault(norm_name(base), set()).add(row.get(ck, ""))
    snap_names: dict[str, set[str]] = {}
    for f in (ROOT / "mock" / "api_snapshots" / "drug-prmsn").rglob("*.json"):
        try:
            txt = f.read_text()
        except Exception:  # noqa: BLE001
            continue
        for m in re.finditer(r'"ITEM_NAME"\s*:\s*"([^"]+)".{0,400}?"ITEM_SEQ"\s*:\s*"(\d+)"|"ITEM_SEQ"\s*:\s*"(\d+)".{0,400}?"ITEM_NAME"\s*:\s*"([^"]+)"', txt, re.S):
            name = m.group(1) or m.group(4)
            seq = m.group(2) or m.group(3)
            snap_names.setdefault(norm_name(name), set()).add(seq)
    return catalog, snap_names


def lookup() -> dict:
    """정답 상품명이 로컬 DUR 품목리스트 CSV(CP949)·허가정보 스냅샷에서 이름 포함 일치로 찾히는지.
    DUR 품목리스트는 DUR 대상(금기·주의) 품목만 담으므로 '못 찾음'이 '없는 약'을 뜻하지 않는다."""
    catalog, snap_names = load_catalogs()
    labels = json.loads(LABELS.read_text())["images"]
    rows, found = [], 0
    for img, v in labels.items():
        for d in v["drugs"]:
            key = norm_name(d["product_name"])
            codes = set()
            for cname, cs in catalog.items():
                if key and key in cname:
                    codes |= cs
            for sname, ss in snap_names.items():
                if key and key in sname:
                    codes |= {f"seq:{s}" for s in ss}
            found += int(bool(codes))
            rows.append({"image": img, "norm": key, "candidates": len(codes),
                         "exact_in_dict": key in catalog or key in snap_names})
    out = {"dur_catalog_names": len(catalog), "snapshot_names": len(snap_names), "found": found, "n": len(rows),
           "rows": rows, "note": "이름 포함 일치(정규화 정답 이름이 사전 이름에 포함). 후보 수만 센다."}
    (OUT / f"lookup{labels_tag()}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"로컬 사전 이름 포함 일치 {found}/{len(rows)} (DUR 이름 {len(catalog)}개, 스냅샷 이름 {len(snap_names)}개)")
    return out


# ---------------------------------------------------------------- 사전 후보 제시(API 호출 없음)
TOP_K = 5


def suggest() -> dict:
    """확인 카드가 '추출 이름 → 사전 실존 제품 후보 top-5'를 보여 준다고 가정할 때 정답이 후보에 드는지.
    - 사전: 로컬 DUR 품목리스트 5종 + mock/api_snapshots/drug-prmsn/ 의 정규화 제품명(전체 허가 목록이 아니다).
    - 후보 순위: 정규화 이름 사이 difflib ratio 내림차순(같으면 이름순). 채점 정규화 규칙(norm_name)은 그대로 쓴다.
    - 판정: 같은 실행(run)에서 나온 추출 이름 중 하나라도 그 top-5에 정답 정규화 이름이 있으면 그 약은 '후보에 듦'.
      (사용자가 이름마다 카드를 보고 고른다는 가정이라 관대하다. 정답이 사전에 없으면 원리상 들 수 없다 = 상한.)
    - 오독 이름 하나가 엉뚱한 실존 제품을 top-1으로 끌어오는지도 센다(위험 지표)."""
    catalog, snap_names = load_catalogs()
    names = sorted(set(catalog) | set(snap_names))
    labels = json.loads(LABELS.read_text())["images"]
    cache: dict[str, list[tuple[float, str]]] = {}

    def topk(q: str) -> list[tuple[float, str]]:
        if q not in cache:
            sm = SequenceMatcher(None, "", q)  # b(=q)를 고정해 속도를 얻는다
            scored = []
            for n in names:
                sm.set_seq1(n)
                if sm.real_quick_ratio() < 0.34 or sm.quick_ratio() < 0.34:
                    continue
                scored.append((round(sm.ratio(), 3), n))
            scored.sort(key=lambda x: (-x[0], x[1]))
            cache[q] = scored[:TOP_K]
        return cache[q]

    out = {"labels_file": LABELS.name, "dict_names": len(names), "top_k": TOP_K, "conditions": {}}
    for upscale in (False, True):
        res_path, _ = paths(upscale)
        results = json.loads(res_path.read_text())
        C = Counter()
        per_drug: dict[str, int] = Counter()
        rows = []
        for img, runs in results["images"].items():
            gold = [norm_name(d["product_name"]) for d in labels[img]["drugs"] if d["product_name"] != "unreadable"]
            for r in runs:
                preds = [norm_name(d["product_name"]) for d in r["output"]["drugs"] if d["product_name"]]
                cand = {p: topk(p) for p in preds if p}
                pool = {n for c in cand.values() for _, n in c}
                for g in gold:
                    in_dict = g in catalog or g in snap_names
                    exact = g in preds
                    hit = g in pool
                    C["n"] += 1
                    C["exact"] += int(exact)
                    C["topk"] += int(hit)
                    C["topk_or_exact"] += int(hit or exact)
                    C["gold_in_dict_runs"] += int(in_dict)
                    C["topk_given_in_dict"] += int(hit and in_dict)
                    if hit or exact:
                        per_drug[f"{img}|{g}"] += 1
                for p, c in cand.items():
                    C["pred_names"] += 1
                    top1 = c[0][1] if c else None
                    if p not in gold:
                        C["wrong_pred"] += 1
                        if top1 and top1 not in gold:
                            C["wrong_pred_top1_other_real"] += 1   # 오독이 다른 실존 제품을 1순위로 끌어옴
                rows.append({"tag": r["tag"], "candidates": {p: c for p, c in cand.items()}})
        drugs_once = sum(1 for img in labels for d in labels[img]["drugs"]
                         if per_drug.get(f"{img}|{norm_name(d['product_name'])}", 0) > 0)
        n_drugs = sum(len(labels[img]["drugs"]) for img in labels)
        out["conditions"]["upscaled" if upscale else "original"] = {
            "total": dict(C), "drugs_hit_once_topk_or_exact": f"{drugs_once}/{n_drugs}", "rows": rows}
        print(f"[{'확대' if upscale else '원본'}] 정확 일치 {C['exact']}/{C['n']}, top-{TOP_K} 후보에 정답 {C['topk']}/{C['n']} "
              f"(정답이 사전에 있는 경우만 {C['topk_given_in_dict']}/{C['gold_in_dict_runs']}), 일치 또는 후보 {C['topk_or_exact']}/{C['n']}, "
              f"한 번이라도 {drugs_once}/{n_drugs}, 틀린 이름이 다른 실존 제품을 1순위로 {C['wrong_pred_top1_other_real']}/{C['wrong_pred']}")
    (OUT / f"suggest{'_luna' if PROVIDER == 'openai' else ''}{labels_tag()}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    up = "--upscale" in sys.argv[2:]
    if "--provider" in sys.argv[2:]:
        prov = sys.argv[sys.argv.index("--provider") + 1] if sys.argv.index("--provider") + 1 < len(sys.argv) else ""
        if prov == "openai":
            PROVIDER, MODEL, CAP_USD = "openai", LUNA, OPENAI_CAP_USD
            LEDGER, CALLS = OUT / "ledger_openai.json", OUT / "calls_openai.jsonl"
        elif prov not in ("anthropic", ""):
            raise SystemExit(f"알 수 없는 provider: {prov}")
    if "--labels" in sys.argv[2:]:
        i = sys.argv.index("--labels")
        LABELS = Path(sys.argv[i + 1]).resolve() if i + 1 < len(sys.argv) else LABELS
        if not LABELS.exists():
            raise SystemExit(f"정답 파일 없음: {LABELS}")
    if cmd == "run":
        run(up)
        grade(up)
    elif cmd == "grade":
        grade(up)
    elif cmd == "lookup":
        lookup()
    elif cmd == "probe":
        if PROVIDER != "openai":
            raise SystemExit("probe는 --provider openai 와 함께 쓴다")
        probe()
    elif cmd == "suggest":
        suggest()
    else:
        print(__doc__)
        sys.exit(2)
