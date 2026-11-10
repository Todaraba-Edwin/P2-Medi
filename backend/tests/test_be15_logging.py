"""BE-15 로깅 모듈(L1) 시험: 서비스 모드 내용 필드 없음(H13), 비밀 마스킹, 모드↔MEDIAGENT_EVAL 일치, 보관 정리."""

import io
import json
from datetime import datetime, timedelta

import pytest

from app.logging import (
    CONTENT_FIELDS,
    Aggregator,
    ModeError,
    SpanLogger,
    build_record,
    cleanup_dev_logs,
    get_mode,
    mask_text,
    mask_value,
)

SECRET = "sk-testSECRETvalue123456"
CONTENT = {
    "input_text": "타이레놀과 이부프로펜 같이 먹어도 되나요",
    "output_text": "답변 원문",
    "input_summary": {"drugs": ["타이레놀"], "profile": {"pregnant": True}},
    "output_summary": {"hits": 1},
    "evidence_ids": ["L2:preg:D000448"],
    "error": "ValueError: 질문 원문이 섞인 메시지",
    "error_message": "메시지",
    "drug_names": ["타이레놀"],
    "question_hash": "abc123",
    "profile": {"pregnant": True},
}


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("MEDIAGENT_MODE", raising=False)
    monkeypatch.delenv("MEDIAGENT_EVAL", raising=False)


# ---- 모드 ----
def test_mode_default_and_invalid_are_service(monkeypatch):
    assert get_mode() == "service"
    monkeypatch.setenv("MEDIAGENT_MODE", "bogus")
    assert get_mode() == "service"
    monkeypatch.setenv("MEDIAGENT_MODE", "dev")
    assert get_mode() == "dev"


def test_eval_mode_requires_eval_flag(monkeypatch):
    monkeypatch.setenv("MEDIAGENT_MODE", "eval")
    with pytest.raises(ModeError):
        get_mode()
    with pytest.raises(ModeError):
        SpanLogger(mode="eval", run_id="r1")
    monkeypatch.setenv("MEDIAGENT_EVAL", "1")
    assert get_mode() == "eval"
    assert SpanLogger(mode="eval", run_id="r1").mode == "eval"


def test_eval_run_id_must_be_safe(monkeypatch):
    monkeypatch.setenv("MEDIAGENT_EVAL", "1")
    for bad in (None, "", "../x", "a/b"):
        with pytest.raises(ValueError):
            SpanLogger(mode="eval", run_id=bad)


# ---- 서비스 모드: 내용 필드 없음 (H13, RFP-34-01) ----
def test_service_record_has_no_content_fields():
    record = build_record("service", {**CONTENT, "node": "tools", "tool": "check_contraindications", "latency_ms": 12})
    assert set(record) == {"node", "tool", "latency_ms"}
    assert not (set(record) & CONTENT_FIELDS)
    serialized = json.dumps(record, ensure_ascii=False)
    for text in ("타이레놀", "pregnant", "D000448", "abc123", "질문 원문"):
        assert text not in serialized


def test_service_harness_event_keeps_rule_id_only():
    record = build_record("service", {"harness_event": {"rule": "H4", "action": "append", "detail": "타이레놀 119"}})
    assert record == {"harness_rule": "H4"}


def test_service_logger_writes_no_file_and_aggregates_without_content(tmp_path):
    out = io.StringIO()
    agg = Aggregator(stream=out)
    logger = SpanLogger(mode="service", aggregator=agg)
    logger.log(**CONTENT, node="model", tool=None, tokens_in=10, tokens_out=5, cost_usd=0.001, error_type="Timeout")
    agg.label_missing("ABSENT")
    line = agg.flush()
    assert line is not None
    assert not (tmp_path / "logs").exists()  # 서비스는 파일을 만들지 않는다
    text = out.getvalue()
    for content in ("타이레놀", "pregnant", "질문 원문", "답변 원문"):
        assert content not in text
    assert line["counts"]["label_missing.ABSENT"] == 1
    assert line["counts"]["error_type=Timeout"] == 1
    assert line["sums"]["tokens_in"] == 10


def test_label_missing_accepts_only_reason_codes():
    agg = Aggregator(stream=io.StringIO())
    for reason in ("ABSENT", "FETCH_FAIL", "SEARCH_MISS", "OUT_OF_SCOPE"):
        agg.label_missing(reason)
    with pytest.raises(ValueError):
        agg.label_missing("타이레놀 라벨 없음")
    assert agg.flush()["counts"] == {f"label_missing.{r}": 1 for r in ("ABSENT", "FETCH_FAIL", "SEARCH_MISS", "OUT_OF_SCOPE")}


def test_aggregator_rolls_per_minute():
    now = [60.0 * 100]
    out = io.StringIO()
    agg = Aggregator(stream=out, clock=lambda: now[0])
    agg.label_missing("ABSENT")
    now[0] += 61
    agg.label_missing("SEARCH_MISS")  # 분이 바뀌면 앞 분을 내보낸다
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    assert len(lines) == 1 and lines[0]["counts"] == {"label_missing.ABSENT": 1}


# ---- dev·eval 기록 ----
def test_dev_writes_whitelisted_jsonl_and_drops_unknown_fields(tmp_path, caplog):
    logger = SpanLogger(mode="dev")
    with caplog.at_level("WARNING"):
        logger.log(input_text="합성 질문", node="model", unknown_field="x")
    path = logger.path()
    assert path is not None and path.parent == tmp_path / "logs" / "dev"
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["schema"] == "mediagent.span@v1" and row["mode"] == "dev"
    assert row["input_text"] == "합성 질문" and "unknown_field" not in row
    assert "unknown_field" in caplog.text


def test_eval_writes_under_run_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAGENT_EVAL", "1")
    logger = SpanLogger(mode="eval", run_id="2026-11-20_C2")
    logger.log(node="tools", item_id="DEV-1")
    path = tmp_path / "logs" / "eval" / "2026-11-20_C2" / "spans.jsonl"
    assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == "2026-11-20_C2"


# ---- 마스킹 ----
def test_masking_patterns():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abc_DEF-123"
    text = f"key={SECRET} url=https://x/api?serviceKey=ABCD%2Bxyz&a=1 db=postgres://u:pw@h:5432/d jwt={jwt}"
    masked = mask_text(text)
    for leaked in (SECRET, "ABCD%2Bxyz", "u:pw@h", jwt):
        assert leaked not in masked
    assert "a=1" in masked


def test_masking_env_values(monkeypatch):
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "plainsecretvalue99")
    monkeypatch.setenv("SOME_DB_URL", "weird-conn-string-12345")
    monkeypatch.setenv("NORMAL_NAME", "plainsecretvalue99-not-secret-name")
    assert mask_text("x plainsecretvalue99 y weird-conn-string-12345") == "x *** y ***"
    assert mask_value({"a": ["plainsecretvalue99"]}) == {"a": ["***"]}


def test_dev_log_masks_secret_values(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "opaque-env-key-value-000")
    logger = SpanLogger(mode="dev")
    logger.log(input_text=f"합성 {SECRET} opaque-env-key-value-000", node="model")
    text = logger.path().read_text(encoding="utf-8")
    assert SECRET not in text and "opaque-env-key-value-000" not in text and "***" in text


def test_masking_failure_drops_line_and_logs_type_only(monkeypatch, caplog):
    import app.logging.spans as spans

    def boom(_):
        raise RuntimeError("질문 원문이 든 메시지")

    monkeypatch.setattr(spans, "mask_value", boom)
    logger = SpanLogger(mode="dev")
    with caplog.at_level("ERROR"):
        assert logger.log(input_text="합성", node="model") is None
    assert not logger.path().exists()
    assert "RuntimeError" in caplog.text and "질문 원문" not in caplog.text


# ---- 보관 ----
def test_cleanup_dev_logs_removes_only_old_dated_files(tmp_path):
    dev = tmp_path / "logs" / "dev"
    dev.mkdir(parents=True)
    now = datetime(2026, 11, 20, 12, 0)
    old = (now - timedelta(days=15)).strftime("%Y-%m-%d")
    keep = (now - timedelta(days=13)).strftime("%Y-%m-%d")
    (dev / f"{old}.jsonl").write_text("x")
    (dev / f"{keep}.jsonl").write_text("x")
    (dev / "notes.jsonl").write_text("x")
    evald = tmp_path / "logs" / "eval" / "r1"
    evald.mkdir(parents=True)
    (evald / "spans.jsonl").write_text("x")
    removed = cleanup_dev_logs(14, now=now)
    assert [p.name for p in removed] == [f"{old}.jsonl"]
    assert (dev / f"{keep}.jsonl").exists() and (dev / "notes.jsonl").exists() and (evald / "spans.jsonl").exists()
