"""BE-06 개발 전용 가짜 자원 로컬 서버: 실제 키·원격 DB·LLM·공공 API 없이 `/chat` HTTP 계약(`chat_event@v1`)을 실제 HTTP로 낸다.

프런트(Next.js rewrites 프록시)가 MSW 대신 이 서버에 붙어 실연결(프록시·NDJSON 파싱·200/501/error·하트비트·고정 문구 순서)을 먼저 확인하는 용도다.

- **앱 본체(`app/main.py`·`app/api/`)는 고치지 않는다.** 가짜 모드 스위치·환경변수가 없다. 이 스크립트가 따로 `FastAPI` 앱을 만들고
  `chat_api.register`(실제 라우트·오류 처리기)와 `service.make_service_runner(settings, resources_factory=...)`(실제 지연 실행기) 주입점만 쓴다.
  그래프(guardrail_in → router → model ⇄ tools → validator → finalize)·도구 본문·스트림 변환은 실제 코드이고, 바뀌는 것은 자원뿐이다.
- 자원: 가짜 도구 모델·가짜 요약 모델(질문 키워드로 스크립트를 고름) + 합성 소사전·소규모 메모리 SQLite·가짜 `DurClient`
  (`tests/e2e/golden_synth.py`) + 합성 L1 고시 청크 2개짜리 코퍼스. 값은 합성이며 평가 세트·시험셋 문항이 아니다.
- `app.main`을 import하지 않는다(import 때 설정을 읽고, 실제 키가 있으면 실제 실행기가 붙기 때문). 설정 자리에는 비밀이 아닌 자리표시 값을 넣은
  `SimpleNamespace`를 넘긴다(`.env`·환경변수를 읽지 않는다).
- 바인딩은 `127.0.0.1` 고정이다(외부 노출 옵션 없음). 질문·대화 내용은 저장·로그하지 않는다(실제 라우트와 같다).

실행(저장소 루트 또는 `backend/`에서):
    backend/.venv/bin/python backend/scripts/dev_fake_server.py [--port 8000] [--slow-seconds 20]

시나리오(질문 문장의 키워드로 고른다. 위에서부터 먼저 맞는 것):

| 시나리오 | 질문에 넣을 것 | 예시 입력 | 기대 이벤트(type 순서) | end_reason |
|---|---|---|---|---|
| 서버 오류 | `서버오류` | 서버오류 시험: 이지렉트정1.0밀리그램이랑 타이레놀콜드-에스정 같이 먹어도 돼요? | error(INTERNAL_ERROR) → done(HTTP는 200) | 없음 |
| 느린 응답 | `느린응답` | 느린응답 시험: 이지렉트정1.0밀리그램이랑 타이레놀콜드-에스정 같이 먹어도 돼요? | (빈 줄 하트비트) progress×2 → answer → done | NORMAL |
| 응급 | 응급 표현(예: `숨쉬기 힘들어요`) + 두 약 | 숨쉬기 힘들어요. 이지렉트정1.0밀리그램이랑 타이레놀콜드-에스정을 같이 먹었어요 | emergency(seq 0) → progress×2 → answer → done | NORMAL |
| 범위 밖 거절 | `처방해 줘` | 이지렉트정1.0밀리그램 처방해 줘 | answer(route REFUSE) → done | REFUSE |
| 되묻기(후보 2개) | 짧은 이름 `타이레놀` | 타이레놀이랑 이지렉트정1.0밀리그램 같이 먹어도 되나요? | answer(candidates 2개) → done | CLARIFY |
| 되묻기 뒤 재전송 | 위 되묻기 질문 그대로 + `context.confirmed_drugs`에 고른 후보(`item_seq`) | 후보 `타이레놀정500밀리그람`(202106092)을 고름 | progress×2 → answer(조회됨 0건) → done | NORMAL |
|  |  | 후보 `타이레놀콜드-에스정`(202106954)을 고름 | progress×2 → answer(found 1건) → done | NORMAL |
| 오탈자 보정(고지 포함) | 한 글자 틀린 이름 `이지랙트정1.0밀리그램` + `타이레놀콜드-에스정` | 이지랙트정1.0밀리그램이랑 타이레놀콜드-에스정 같이 먹어도 되나요? | progress×2 → answer(found 1건, `name_corrections` 1건) → done | NORMAL |
| 금기 목록에 없음 | `타이레놀정500밀리그람` + `이지렉트정1.0밀리그램` | 타이레놀정500밀리그람이랑 이지렉트정1.0밀리그램 같이 먹어도 되나요? | progress×2 → answer(조회됨 0건) → done | NORMAL |
| 정상(병용금기 1건) | `이지렉트정1.0밀리그램` + `타이레놀콜드-에스정` | 엄마가 이지렉트정1.0밀리그램을 드시는데 감기라서 타이레놀콜드-에스정을 사 왔어요. 같이 먹어도 되나요? | progress×2 → answer(found 1건) → done | NORMAL |

거절·되묻기·응급·오탈자 보정은 실제 guardrail·router가 문장을 보고 정한다(모델 스크립트와 무관). 오탈자 보정은 router가 확정한 코드가
ROUTER_NOTE에 실리고 가짜 도구 모델이 그 코드의 합성 제품명으로 정상 스크립트를 고른다(아래 되묻기 뒤 재전송과 같은 방식). 모델 스크립트는 router를 지난 질문에만 쓰인다.
되묻기 뒤 재전송은 실제 router가 고른 코드로 약을 확정하고(AG-05-03 A), 가짜 도구 모델은 질문 문장에 더해 ROUTER_NOTE의 확정 코드에 해당하는
합성 제품명을 보고 스크립트를 고른다(짧은 이름 `타이레놀`이 어느 약으로 확정됐는지 문장만으로는 알 수 없어서).
`/health`는 200 `{"status": "ok"}`. 실행기가 붙어 있으므로 이 서버의 `/chat`은 501을 내지 않는다(501 확인은 실제 앱을 키 없이 띄우면 된다).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests" / "e2e"))  # 합성 재료(golden_synth)를 시험과 같이 쓴다(값을 복제하지 않는다)

from fastapi import FastAPI  # noqa: E402
from golden_synth import SEQ_AZI, SEQ_COLD, SEQ_T500, FakeDur, golden_conn, golden_dict  # noqa: E402
from langchain_core.language_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402

from app.agent.grade_defs import corpus_grade_def_fn  # noqa: E402
from app.agent.graph.fakes import tool_call  # noqa: E402
from app.agent.graph.nodes import GraphDeps  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.agent.tools.corpus import CorpusIndex  # noqa: E402
from app.api import chat as chat_api  # noqa: E402
from app.api import service  # noqa: E402
from app.api.runner import ChatRunner  # noqa: E402
from app.logging.redact_filter import install_log_redaction  # noqa: E402

HOST = "127.0.0.1"  # 고정. 외부 바인딩 옵션을 두지 않는다
DEFAULT_PORT = 8000
DEFAULT_SLOW_SECONDS = 20.0  # 하트비트 간격(`events.HEARTBEAT_INTERVAL_S` 15초)보다 길게

T500, COLD, AZI = "타이레놀정500밀리그람", "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
AZI_TYPO = "이지랙트정1.0밀리그램"  # `AZI`에서 모음 하나만 다른 합성 오탈자(자모 1칸): 실제 router가 `AZI`로 보정한다(AG-10-02 A)
KW_ERROR, KW_SLOW = "서버오류", "느린응답"
PAIR_EID = "contra_pair:254000ATB:625201ATB"
FAKE_SETTING = "dev-fake-placeholder-not-a-secret"  # 필수 설정 자리를 채우는 자리표시 값(비밀 아님, 어디에도 접속하지 않는다)

# 시나리오별 예시 입력(머리말 표와 같다). 시험·보고·프런트 안내가 이 표를 쓴다
SCENARIOS: dict[str, str] = {
    "normal_found": f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?",
    "not_found": f"{T500}이랑 {AZI} 같이 먹어도 되나요?",
    "clarify": f"타이레놀이랑 {AZI} 같이 먹어도 되나요?",  # 합성 사전에서 `타이레놀` 후보 2개(콜드-에스정·정500)
    "typo": f"{AZI_TYPO}이랑 {COLD} 같이 먹어도 되나요?",  # 서비스 보정 켬일 때 고지 `name_corrections` 1건 + 병용금기 1건(BE-06-35 A 기본 끔이면 되묻기)
    "emergency": f"숨쉬기 힘들어요. {AZI}이랑 {COLD}을 같이 먹었어요",
    "refuse": f"{AZI} 처방해 줘",
    "server_error": f"{KW_ERROR} 시험: {AZI}이랑 {COLD} 같이 먹어도 돼요?",
    "slow": f"{KW_SLOW} 시험: {AZI}이랑 {COLD} 같이 먹어도 돼요?",
}

# 합성 L1 고시 청크(임부금기 등급 정의 공급용). 문장은 합성이며 고시 원문이 아니다
_TITLE = "의약품 병용금기 성분 등의 지정에 관한 규정"
CORPUS_CHUNKS: list[dict[str, Any]] = [
    {"chunk_id": f"dev-fake-{g}", "chunk_kind": "l1_notice_sub", "parent_id": None, "refs": [], "pair_id": None, "layer": "L1",
     "issuer": "식품의약품안전처", "doc_type": "고시", "notice_no": "00000000", "base_date": "2026-07-21", "locator": loc,
     "ingr_codes": [], "ingr_names": [], "text": f"[제3조(정의) 제3호] {mark}. {g}등급: (개발용 합성 문장) {g}등급 정의 자리",
     "source_ref": f"{_TITLE}|dev-fake.md", "item_seq": "", "item_name": "", "section": ""}
    for g, mark, loc in (("1", "가", "제3조 제3호 가목"), ("2", "나", "제3조 제3호 나목"))
]


def _guide() -> dict[str, Any]:
    return {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}


PAIR_DRAFT: dict[str, Any] = {"sentences": [
    {"text": "두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []},
    _guide(),
]}
NOT_FOUND_DRAFT: dict[str, Any] = {"sentences": [
    {"text": "확인한 금기 목록에서 두 약의 조합을 찾지 못했어요. 목록에 없다고 해서 안전하다는 뜻은 아니에요.", "evidence_ids": [],
     "claim_type": "guidance", "citations": []},
    _guide(),
]}


def _pair_script(a: str, b: str) -> list[AIMessage]:
    return [
        AIMessage("", tool_calls=[tool_call("identify_drug", {"name": a}, "c1"), tool_call("identify_drug", {"name": b}, "c2")]),
        AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": a}, {"name": b}]}, "c3")]),
        AIMessage("조회를 마쳤다"),
    ]


_SEQ_NAMES = {SEQ_T500: T500, SEQ_COLD: COLD, SEQ_AZI: AZI}  # 합성 사전의 품목기준코드 → 제품명
_NOTE_RE = re.compile(r"<<<ROUTER_NOTE\n(.*?)\nROUTER_NOTE>>>", re.S)


def _note_product_names(text: str) -> list[str]:
    """ROUTER_NOTE에서 확정(RESOLVED)된 약의 코드를 합성 제품명으로 바꾼다. 되묻기 뒤 재전송에서 짧은 이름이 어느 약으로 확정됐는지 본다."""
    m = _NOTE_RE.search(text)
    if not m:
        return []
    try:
        cands = json.loads(m.group(1)).get("drug_candidates") or []
    except (ValueError, AttributeError):
        return []
    return [_SEQ_NAMES[c["item_seq"]] for c in cands
            if isinstance(c, dict) and c.get("status") == "RESOLVED" and c.get("item_seq") in _SEQ_NAMES]


def _question(messages: Sequence[BaseMessage]) -> str:
    """모델 입력에서 질문 문장(첫 사용자 메시지)을 꺼낸다. 요약 호출은 `질문: ...` 머리가 붙는다.
    ROUTER_NOTE에 확정된 약이 있으면 그 합성 제품명을 뒤에 붙인다(스크립트 선택용, 응답에는 쓰지 않는다)."""
    for m in messages:
        if isinstance(m, HumanMessage):
            text = str(m.content).removeprefix("질문: ")
            return " ".join([text, *_note_product_names(text)])
    return ""


def pick_scenario(question: str) -> str:
    """모델까지 온 질문의 스크립트 이름(거절·되묻기·응급 여부는 실제 guardrail·router가 정한다)."""
    if KW_ERROR in question:
        return "server_error"
    if KW_SLOW in question:
        return "slow"
    if T500 in question and AZI in question:
        return "not_found"
    return "normal_found"


class KeywordToolModel(BaseChatModel):
    """질문 키워드로 스크립트를 고르는 상태 없는 가짜 도구 모델(동시 요청 안전). 단계 = 이미 나온 AI 메시지 수."""

    slow_seconds: float = DEFAULT_SLOW_SECONDS

    @property
    def _llm_type(self) -> str:
        return "dev-fake-keyword-tool-model"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> KeywordToolModel:  # noqa: ARG002
        return self

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None,
                  **kwargs: Any) -> ChatResult:
        name = pick_scenario(_question(messages))
        if name == "server_error":
            raise RuntimeError("dev fake: scripted server error")  # 스트림은 error(INTERNAL_ERROR) → done
        step = sum(isinstance(m, AIMessage) for m in messages)
        if name == "slow" and step == 0:
            time.sleep(self.slow_seconds)  # 첫 이벤트 전 침묵 → 하트비트 빈 줄
        script = _pair_script(T500, AZI) if name == "not_found" else _pair_script(AZI, COLD)
        msg = script[min(step, len(script) - 1)].model_copy(update={"id": None})
        return ChatResult(generations=[ChatGeneration(message=msg)])


class KeywordSummary:
    """질문 키워드로 요약 초안을 고르는 상태 없는 가짜 요약 모델."""

    def invoke(self, messages: Sequence[Any], **kwargs: Any) -> Any:  # noqa: ARG002
        return NOT_FOUND_DRAFT if pick_scenario(_question(messages)) == "not_found" else PAIR_DRAFT


def fake_settings() -> SimpleNamespace:
    """필수 설정 이름을 자리표시 값으로 채운 설정(환경변수·`.env`를 읽지 않는다)."""
    return SimpleNamespace(**{name.lower(): FAKE_SETTING for name in service.REQUIRED_ENV})


def make_fake_resources(slow_seconds: float = DEFAULT_SLOW_SECONDS) -> service.ResourcesFactory:
    def factory(settings: Any) -> GraphDeps:  # noqa: ARG001 - 설정 값은 쓰지 않는다
        dd = golden_dict()
        corpus = CorpusIndex(CORPUS_CHUNKS)
        ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn, corpus=corpus,
                                 vector_search_fn=None, label_provider=None)
        return build_deps(dd, ctx, tool_model=KeywordToolModel(slow_seconds=slow_seconds), summary_model=KeywordSummary(),
                          tracer=None, ledger=None, grade_def_fn=corpus_grade_def_fn(corpus), service=True)

    return factory


def create_app(*, slow_seconds: float = DEFAULT_SLOW_SECONDS, metrics: Any = chat_api._DEFAULT_METRICS) -> FastAPI:
    """가짜 자원으로 실행기를 붙인 개발용 앱. 라우트·오류 처리기·스트림 변환은 실제 코드다."""
    app = FastAPI(title="MediAgent (dev fake server)")
    chat_api.register(app)
    runner: ChatRunner | None = service.make_service_runner(fake_settings(), resources_factory=make_fake_resources(slow_seconds))
    if runner is None:  # 자리표시 값이 다 채워져 있으므로 오지 않는다
        raise RuntimeError("dev fake server: runner was not attached")
    chat_api.set_runner(app, runner, metrics=metrics)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="BE-06 개발 전용 가짜 자원 서버(127.0.0.1 고정, 외부 호출 0)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"포트(기본 {DEFAULT_PORT})")
    p.add_argument("--slow-seconds", type=float, default=DEFAULT_SLOW_SECONDS,
                   help=f"느린응답 시나리오의 첫 이벤트 전 지연 초(기본 {DEFAULT_SLOW_SECONDS:g})")
    args = p.parse_args(argv)
    if not 1 <= args.port <= 65535:
        p.error("--port는 1~65535")
    if args.slow_seconds < 0:
        p.error("--slow-seconds는 0 이상")
    return args


def main(argv: Sequence[str] | None = None) -> None:
    import uvicorn  # noqa: PLC0415 - 서버를 띄울 때만

    args = parse_args(argv)
    install_log_redaction()  # 실제 앱과 같은 로그 가리기
    print(f"dev fake server (BE-06): http://{HOST}:{args.port}  /health  POST /chat  (fake resources, no external calls)")
    # access_log=False: 실서버와 같이 접속 IP·요청 경로를 남기지 않는다(PRD-17 ⑫ ⑧ B)
    uvicorn.run(create_app(slow_seconds=args.slow_seconds), host=HOST, port=args.port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
