"""BE-06-24 B 시험(2026-11-17): 제품·성분 사전 DB 적재·읽기와 서비스 경로의 DB 사전.

원격 DB·LLM·공공 API 호출 0, `.env` 미사용. DB는 메모리 SQLite(가짜 연결)다. psycopg `format`(`%s`) 경로는
`%s`를 `?`로 바꾸는 얇은 감싸개(`FmtConn`)로 흉내 낸다. 사전은 합성 소사전(`e2e/golden_synth.py`)이다.

확인하는 것(지시서 §2):
  - 적재 → 읽기 왕복이 파일 사전과 같다, 적재 멱등(다시 넣어도 0행), 같은 판에 다른 원본이면 거부, 끊긴 적재를 이어 넣음
  - 판이 없거나 불완전하면 빈 사전 대신 예외
  - 사전 파일이 없는 환경에서 서비스 첫 요청이 `FileNotFoundError` 없이 DB로 사전을 만든다(`service.default_resources` 실제 실행)
  - 적재 스크립트: 기본 dry-run(연결 0), `--yes`·승인 파일 둘 다 없으면 apply 거부(연결 전)
  - 평가 러너의 사전 경로(`DrugDict.load`)는 그대로다
"""

from __future__ import annotations

import builtins
import hashlib
import importlib.util
import io
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import FakeDur, golden_conn, golden_dict  # noqa: E402

from app.agent import llm  # noqa: E402
from app.agent.graph.fakes import ScriptedToolModel, tool_call  # noqa: E402
from app.agent.tools import corpus as corpus_mod  # noqa: E402
from app.api import chat as chat_api  # noqa: E402
from app.api import events as ev  # noqa: E402
from app.api import service  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import drug_dict_store as store  # noqa: E402
from app.tools import dur as dur_mod  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
Q_PAIR = f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"
PAIR_EID = "contra_pair:254000ATB:625201ATB"
ENV_NAMES = ("OPENAI_API_KEY", "SUPABASE_DB_URL", "DURPrdlstInfoService03_END_POINT", "DURPrdlstInfoService03_API_KEY",
             "DURIrdntInfoService03_END_POINT", "DURIrdntInfoService03_API_KEY")
PAIR_DRAFT = {"sentences": [
    {"text": "두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []},
    {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []},
]}


def _payload() -> dict[str, Any]:
    dd = golden_dict()
    return {"meta": dict(dd.meta), "products": [dict(p) for p in dd.products], "ingredients": [dict(i) for i in dd.ingredients]}


def _sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _db(payload: dict[str, Any] | None = None, *, now: str = "2026-11-17T00:00:00+00:00") -> sqlite3.Connection:
    c = sqlite3.connect(":memory:", check_same_thread=False)
    store.apply_dict_schema(c)
    if payload is not None:
        store.load_payload(c, payload, _sha(payload), now=now)
        c.commit()
    return c


class FmtCursor:
    def __init__(self, conn: FmtConn) -> None:
        self._conn = conn
        self._cur = conn.raw.cursor()

    def execute(self, sql: str, params: Any = None) -> FmtCursor:
        if params is None and sql.count(";") > 1:
            self._conn.raw.executescript(sql)
            return self
        self._cur.execute(sql.replace("%s", "?"), tuple(params or ()))
        return self

    def executemany(self, sql: str, seq: Any) -> None:
        self._cur.executemany(sql.replace("%s", "?"), list(seq))

    def fetchone(self) -> Any:
        return self._cur.fetchone()

    def fetchall(self) -> Any:
        return self._cur.fetchall()

    def fetchmany(self, n: int) -> Any:
        return self._cur.fetchmany(n)

    @property
    def description(self) -> Any:
        return self._cur.description


class FmtConn:
    """psycopg `format` 흉내(메모리 SQLite 공유). `close`는 기록만 하고 밑 연결은 닫지 않는다."""

    def __init__(self, raw: sqlite3.Connection, log: list[str] | None = None) -> None:
        self.raw, self.read_only, self.log = raw, False, log if log is not None else []
        self.log.append("open")

    def cursor(self) -> FmtCursor:
        return FmtCursor(self)

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        self.log.append("close")


# --------------------------------------------------------------------------- 저장소 왕복·멱등
def test_load_then_read_roundtrip_matches_file_dict():
    payload = _payload()
    c = _db(payload)
    got = store.read_payload(c)
    assert got == payload
    a, b = DrugDict(payload), DrugDict(got)
    assert a.version == b.version == "golden-synth-v1"
    for name in (COLD, AZI, "타이레놀", "슈도에페드린"):
        assert a.lookup_name(name).to_dict() == b.lookup_name(name).to_dict()


def test_from_db_format_paramstyle_opens_once_and_closes():
    raw = _db(_payload())
    log: list[str] = []
    dd = DrugDict.from_db(lambda: FmtConn(raw, log), paramstyle="format")
    assert dd.version == "golden-synth-v1" and len(dd.products) == 4 and log == ["open", "close"]


def test_load_is_idempotent():
    payload = _payload()
    c = _db()
    first = store.load_payload(c, payload, _sha(payload))
    c.commit()
    second = store.load_payload(c, payload, _sha(payload))
    c.commit()
    assert first["status"] == "loaded" and first["inserted_entries"] == 4 + 5
    assert second == {**second, "status": "already_loaded", "inserted_entries": 0}
    assert c.execute("SELECT COUNT(*) FROM drug_dict_entry").fetchone()[0] == 9
    assert c.execute("SELECT COUNT(*) FROM drug_dict_meta").fetchone()[0] == 1


def test_schema_is_rerunnable():
    c = _db(_payload())
    store.apply_dict_schema(c)
    store.apply_dict_schema(c)
    assert store.read_payload(c)["meta"]["version"] == "golden-synth-v1"


def test_same_version_different_source_is_refused():
    payload = _payload()
    c = _db(payload)
    with pytest.raises(store.DictConflict):
        store.load_payload(c, payload, "f" * 64)


def test_interrupted_load_is_completed_on_rerun():
    payload = _payload()
    c = _db()
    rows = list(store.entry_rows(payload))[:3]  # 앞 3행만 들어간 상태(meta 없음)
    c.executemany("INSERT INTO drug_dict_entry (version, kind, ord, data) VALUES (?, ?, ?, ?)", rows)
    c.commit()
    with pytest.raises(store.DictNotLoaded):
        store.read_payload(c)  # meta가 없으면 읽지 않는다
    res = store.load_payload(c, payload, _sha(payload))
    c.commit()
    assert res["status"] == "loaded" and res["inserted_entries"] == 9 - 3
    assert store.read_payload(c) == payload


def test_failed_load_check_leaves_no_meta_row(monkeypatch):
    payload = _payload()
    c = _db()
    monkeypatch.setattr(store, "entry_counts", lambda cur, version, ph: {"product": 0, "ingredient": 0})
    with pytest.raises(store.DictIncomplete):
        store.load_payload(c, payload, _sha(payload))
    c.rollback()
    assert c.execute("SELECT COUNT(*) FROM drug_dict_meta").fetchone()[0] == 0


def test_latest_loaded_version_is_read():
    old, new = _payload(), _payload()
    new["meta"]["version"] = "golden-synth-v2"
    new["products"] = new["products"][:3]
    c = _db(old, now="2026-11-16T00:00:00+00:00")
    store.load_payload(c, new, _sha(new), now="2026-11-17T00:00:00+00:00")
    c.commit()
    assert store.read_payload(c)["meta"]["version"] == "golden-synth-v2" and len(store.read_payload(c)["products"]) == 3
    assert store.read_payload(c, version="golden-synth-v1") == old


# --------------------------------------------------------------------------- 미적재·불완전은 예외
def test_empty_table_raises_not_loaded():
    with pytest.raises(store.DictNotLoaded):
        DrugDict.from_db(lambda: FmtConn(_db()), paramstyle="format")


def test_missing_rows_raise_incomplete():
    c = _db(_payload())
    c.execute("DELETE FROM drug_dict_entry WHERE kind = 'ingredient' AND ord = 2")
    c.commit()
    with pytest.raises(store.DictIncomplete):
        store.read_payload(c)


def test_missing_table_is_a_db_error_not_file_not_found():
    with pytest.raises(sqlite3.OperationalError):
        DrugDict.from_db(lambda: FmtConn(sqlite3.connect(":memory:")), paramstyle="format")


@pytest.mark.parametrize("bad", [{"meta": {}, "products": [{}], "ingredients": []},
                                 {"meta": {"version": "v"}, "products": [], "ingredients": []},
                                 {"meta": {"version": "v"}, "products": "x", "ingredients": []}])
def test_payload_shape_is_checked(bad):
    with pytest.raises(ValueError):
        store.payload_summary(bad)


# --------------------------------------------------------------------------- 서비스 첫 요청: 파일 없이 DB 사전
class RawSummary:
    def invoke(self, messages: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ARG002
        return {"raw": AIMessage("{}"), "parsed": PAIR_DRAFT, "parsing_error": None}


class FakeChat:
    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedToolModel:  # noqa: ARG002
        return ScriptedToolModel(script=[
            AIMessage("", tool_calls=[tool_call("identify_drug", {"name": AZI}, "c1"), tool_call("identify_drug", {"name": COLD}, "c2")]),
            AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": AZI}, {"name": COLD}]}, "c3")]),
            AIMessage("조회를 마쳤다"),
        ])

    def with_structured_output(self, *args: Any, **kwargs: Any) -> RawSummary:  # noqa: ARG002
        return RawSummary()


def test_service_first_request_builds_dict_from_db_without_dict_file(monkeypatch):
    """실제 `service.default_resources`를 돌린다. 접속(`psycopg.connect`)·코퍼스·DUR·모델 생성만 가짜로 바꾸고, 사전 파일 열기는 막는다."""
    import psycopg

    for n in ENV_NAMES:
        monkeypatch.delenv(n, raising=False)
    for name in ("MEDIAGENT_MODE", "MEDIAGENT_EVAL", "LLM_CACHE"):
        monkeypatch.delenv(name, raising=False)
    raw = golden_conn()  # 판정 테이블(합성)
    raw2 = sqlite3.connect(":memory:", check_same_thread=False)
    raw2.executescript("".join(raw.iterdump()))  # 스레드 사이 공유 가능한 복사본
    store.apply_dict_schema(raw2)
    payload = _payload()
    store.load_payload(raw2, payload, _sha(payload))
    raw2.commit()
    opened: list[str] = []
    real_open = builtins.open

    def guarded_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        p = os.fspath(file) if isinstance(file, (str, os.PathLike)) else ""
        if "drug_dict" in p or (os.sep + os.path.join("data", "mock")) in p:
            opened.append(p)
            raise FileNotFoundError(p)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    monkeypatch.setattr(psycopg, "connect", lambda dsn: FmtConn(raw2))
    monkeypatch.setattr(corpus_mod.CorpusIndex, "from_db", classmethod(lambda cls, conn_factory, **kw: cls([])))
    monkeypatch.setattr(dur_mod.DurClient, "from_settings", classmethod(lambda cls, settings: FakeDur()))
    monkeypatch.setattr(llm, "make_chat_model", lambda settings, purpose="tools", **kw: FakeChat())  # noqa: ARG005
    built: list[Any] = []
    real_default = service.default_resources

    def spy(settings: Any) -> Any:
        deps = real_default(settings)
        built.append(deps)
        return deps

    settings = Settings(_env_file=None, **{n.lower(): f"가짜값-{i}" for i, n in enumerate(ENV_NAMES)})
    runner = service.make_service_runner(settings, resources_factory=spy)
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, runner, metrics=None)
    r = TestClient(app).post("/chat", json={"question": Q_PAIR})
    events = [ev.ChatEvent.model_validate_json(x) for x in r.content.split(b"\n") if x]
    types_ = [e.root.type for e in events]
    assert r.status_code == 200 and "error" not in types_, types_
    assert types_[-2:] == ["answer", "done"] and events[-1].root.end_reason == "NORMAL"
    assert opened == []  # 사전 파일·data/mock을 열지 않았다
    deps = built[0]
    assert deps.drug_dict.version == "golden-synth-v1" and deps.tool_model.service and deps.summary_model.service
    a = next(e.root.response for e in events if e.root.type == "answer")
    assert any(f.bucket == "found" and f.target == "pair" for f in a.findings), a.model_dump_json()  # DB 사전으로 식별한 두 약의 병용금기가 답에 실렸다


# --------------------------------------------------------------------------- 적재 스크립트
def _script() -> Any:
    spec = importlib.util.spec_from_file_location("be06_dict_load_t", BACKEND / "scripts" / "be06_dict_load.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def dict_file(tmp_path):
    p = tmp_path / "drug_dict.json"
    p.write_text(json.dumps(_payload(), ensure_ascii=False), encoding="utf-8")
    return p


def _no_connect(dsn: str) -> Any:
    raise AssertionError("연결하면 안 된다")


def test_script_default_is_dry_run_without_connection(dict_file):
    mod = _script()
    out = mod.main(["--dict-path", str(dict_file)], connect_fn=_no_connect, log=lambda s: None)
    assert out["cmd"] == "plan" and out["remote_connections"] == 0
    assert out["local"]["entry_rows"] == 9 and out["local"]["products"] == 4 and out["local"]["version"] == "golden-synth-v1"


def test_script_print_sql_needs_no_file_or_connection(tmp_path):
    seen: list[str] = []
    out = _script().main(["--print-sql", "--dict-path", str(tmp_path / "none.json")], connect_fn=_no_connect, log=seen.append)
    assert out["remote_connections"] == 0 and "CREATE TABLE IF NOT EXISTS drug_dict_entry" in seen[0]


@pytest.mark.parametrize("with_yes,with_flag", [(False, False), (True, False), (False, True)])
def test_script_apply_refused_without_yes_and_flag(dict_file, tmp_path, with_yes, with_flag):
    mod = _script()
    flag = tmp_path / "be06_dict_approved.flag"
    if with_flag:
        flag.write_text("ok", encoding="utf-8")
    argv = ["apply", "--dict-path", str(dict_file)] + (["--yes"] if with_yes else [])
    with pytest.raises(mod.Refused):
        mod.main(argv, connect_fn=_no_connect, flag=flag, log=lambda s: None)


def test_script_flag_path_is_the_agreed_one():
    mod = _script()
    assert mod.APPROVAL_FLAG == REPO / "data" / "mock" / "review" / "be06_dict_approved.flag"


def test_script_apply_with_yes_and_flag_is_idempotent(dict_file, tmp_path, monkeypatch):
    mod = _script()
    monkeypatch.setenv("SUPABASE_DB_URL", "가짜-접속-문자열")
    flag = tmp_path / "be06_dict_approved.flag"
    flag.write_text("ok", encoding="utf-8")
    raw = sqlite3.connect(":memory:")
    log: list[str] = []
    argv = ["apply", "--yes", "--dict-path", str(dict_file)]
    first = mod.main(argv, connect_fn=lambda dsn: FmtConn(raw), flag=flag, log=log.append)
    second = mod.main(argv, connect_fn=lambda dsn: FmtConn(raw), flag=flag, log=log.append)
    assert first["apply"]["status"] == "loaded" and first["apply"]["inserted_entries"] == 9
    assert second["apply"]["status"] == "already_loaded" and second["apply"]["inserted_entries"] == 0
    assert raw.execute("SELECT COUNT(*) FROM drug_dict_entry").fetchone()[0] == 9
    assert not any("가짜-접속-문자열" in s for s in log)

    present = lambda cur: {t: bool(cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = %s", (t,)).fetchone()[0])  # noqa: E731
                           for t in (store.META_TABLE, store.ENTRY_TABLE)}
    plan = mod.main(["plan", "--remote", "--dict-path", str(dict_file)], connect_fn=lambda dsn: FmtConn(raw), log=lambda s: None,
                    present_fn=present)
    assert plan["remote_connections"] == 1 and plan["remote"]["to_insert_entries"] == 0 and plan["remote"]["remote_meta"]["same_source"]
    ver = mod.main(["verify", "--dict-path", str(dict_file)], connect_fn=lambda dsn: FmtConn(raw), log=lambda s: None)
    assert ver["remote"]["ok"] is True


def test_script_apply_conflict_rolls_back(dict_file, tmp_path, monkeypatch):
    mod = _script()
    monkeypatch.setenv("SUPABASE_DB_URL", "가짜")
    flag = tmp_path / "f.flag"
    flag.write_text("ok", encoding="utf-8")
    raw = _db(_payload())  # 같은 판, 다른 sha로 이미 있음
    with pytest.raises(store.DictConflict):
        mod.main(["apply", "--yes", "--dict-path", str(dict_file)], connect_fn=lambda dsn: FmtConn(raw), flag=flag, log=lambda s: None)
    assert raw.execute("SELECT COUNT(*) FROM drug_dict_meta").fetchone()[0] == 1


# --------------------------------------------------------------------------- 평가 경로 그대로
def test_eval_runner_dict_path_is_unchanged():
    src = (REPO / "evaluation" / "eval_runner.py").read_text(encoding="utf-8")
    assert "DrugDict.from_db" not in src and "service=True" not in src
    assert "def load(" in Path(sys.modules[DrugDict.__module__].__file__).read_text(encoding="utf-8")
