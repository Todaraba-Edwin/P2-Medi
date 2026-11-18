"""BE-08 C0(LLM 단독, PJ2-RFP.md 9.5절) 연결 시험(2026-11-18). 가짜 모델만 쓴다(LLM·원격 DB·공공 API 호출 0).

- C0는 같은 모델에 **질문만** 보낸다: 시스템 프롬프트·도구·Router·Validator·finalize 없음, 고정 문구를 코드가 붙이지 않는다.
- 원격 DB·사전·코퍼스를 읽지 않는다(자원 생성 함수를 부르지 않음). 결과 meta는 C0 규칙 버전·해당 없음 항목(None)·조건표 C0 행.
- 동결 점검(`freeze_check`)은 C0 결과를 통과시키고, C2 기준선과 비교할 때 C0에 없는 항목(사전·코퍼스 등)은 빼고 본다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "evaluation", ROOT / "evaluation" / "judge"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import eval_runner as R  # noqa: E402
import freeze_check as F  # noqa: E402
import sealed_guard as G  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.config import Settings  # noqa: E402

ANSWER = "두 약을 함께 드셔도 괜찮아요."  # 합성 모델 답(안전 단정이 들어 있어 코드 채점이 잡아야 한다)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    for n in ("OPENAI_API_KEY", "SUPABASE_DB_URL", "ANTHROPIC_API_KEY", "MEDIAGENT_MODE", "LLM_CACHE", G.SEALED_ENV):
        for name in (n, n.lower()):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MEDIAGENT_EVAL", "0")
    monkeypatch.setenv("MEDIAGENT_LEDGER_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path / "logs"))


class FakeModel:
    def __init__(self, text: str = ANSWER, fail: bool = False) -> None:
        self.text, self.fail, self.seen = text, fail, []

    def invoke(self, messages: list[Any]) -> AIMessage:
        self.seen.append(messages)
        if self.fail:
            raise RuntimeError("boom")
        return AIMessage(content=self.text, usage_metadata={"input_tokens": 30, "output_tokens": 10, "total_tokens": 40})


class FakeLedger:
    def __init__(self) -> None:
        self.eval = 0.0

    def spent(self, bucket: str) -> float:
        return self.eval


def _set(tmp_path: Path, n: int = 2) -> Path:
    p = tmp_path / "synth.jsonl"
    rows = [{"id": f"syn-{i}", "question": f"합성 질문 {i}", "set": "dev", "set_version": "synth", "branch_label": "정상", "composition_group": "정상-응급",
             "expected_response_type": "emergency", "expected_path": {"required": ["check_contraindications"]},
             "required_elements": ["EMERGENCY_119_TOP", "NO_SAFETY_ASSERTION", "DISCLAIMER"], "answer": {"items": []}} for i in range(n)]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def _run(tmp_path: Path, model: FakeModel, *extra: str, out: str = "c0.json") -> tuple[int, dict[str, Any]]:
    path = tmp_path / out

    def no_resources(*a: Any, **k: Any) -> Any:
        raise AssertionError("C0는 그래프 자원(원격 DB·사전·코퍼스)을 만들지 않는다")

    rc = R.main(["--set", str(_set(tmp_path)), "--agent", "graph", "--condition", "C0", "--max-usd", "1", "--out", str(path), *extra],
                settings_fn=lambda: Settings(_env_file=None, openai_api_key="fake-k"), resources_factory=no_resources,
                c0_model_factory=lambda s: (model, FakeLedger()))
    return rc, (json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})


def test_c0_sends_only_the_question_and_keeps_the_raw_answer(tmp_path):
    model = FakeModel()
    rc, res = _run(tmp_path, model)
    assert rc == 0 and len(model.seen) == 2
    assert all(len(m) == 1 and m[0].type == "human" and m[0].content.startswith("합성 질문") for m in model.seen)  # 시스템 프롬프트 없음
    row = res["items"][0]
    assert row["run"]["answer"] == {"summary": ANSWER, "text": ANSWER} and row["run"]["tool_calls"] == []
    assert fp.DISCLAIMER not in json.dumps(row["run"]["answer"], ensure_ascii=False)  # 코드가 고정 문구를 붙이지 않는다
    els = row["elements"]
    assert els == {"EMERGENCY_119_TOP": False, "NO_SAFETY_ASSERTION": False, "DISCLAIMER": False}
    assert row["trajectory"]["verdict"] == "Fail" and row["cost"]["model_calls"] == 1 and row["cost"]["tokens"] == 40


def test_c0_meta_records_rule_version_and_not_applicable_items(tmp_path):
    _, res = _run(tmp_path, FakeModel())
    m = res["meta"]
    assert m["condition"] == "C0" and m["versions"]["graph"] == R.C0_VERSION and m["prompt_set"] is None
    assert all(m["versions"][k] is None for k in ("prompt", "harness", "dict", "corpus"))
    assert m["versions"]["metrics"].startswith("metrics-src@") and m["typo_correction"]["enabled"] is False
    assert m["harness"]["condition"] == "C0" and m["harness"]["baseline"] == [] and m["run_settings"]["api_enabled"] is False
    rows = F.check_result(res, dict_version=None, require_manifest_match=False)
    assert [r["item"] for r in rows if not r["ok"]] == []


def test_c0_result_with_graph_versions_fails_the_freeze_check(tmp_path):
    _, res = _run(tmp_path, FakeModel())
    res["meta"]["versions"]["dict"] = {"version": "be10-dict-s1-x"}
    bad = [r["item"] for r in F.check_result(res, dict_version=None, require_manifest_match=False) if not r["ok"]]
    assert bad == ["dict_version"]


def test_c0_against_a_c2_baseline_skips_items_c0_does_not_use():
    c2 = {"meta": {"condition": "C2", "set_sha256": "a" * 64, "versions": {"model": {"agent": "m"}, "dict": {"version": "d"},
                                                                          "corpus": {"source": "db", "n_chunks": 1, "sha256": "b" * 64}}}}
    c0 = {"meta": {"condition": "C0", "set_sha256": "a" * 64, "versions": {"model": {"agent": "m"}, "dict": None, "corpus": None}}}
    assert F.freeze_diff(c0, c2) == [] and F.same_freeze(c2, c0) == []
    c0["meta"]["versions"]["model"] = {"agent": "other"}
    assert [d["item"] for d in F.freeze_diff(c0, c2)] == ["model"]


def test_c0_model_errors_count_toward_the_consecutive_error_stop(tmp_path):
    rc, res = _run(tmp_path, FakeModel(fail=True))
    assert rc == 0 and res["errors"]["items"] == 2 and res["items"][0]["run"]["error"] == "RuntimeError"


@pytest.mark.parametrize("extra", [("--agent", "graph", "--typo-correct"), ("--agent", "offline-fixed")])
def test_c0_refuses_typo_correction_and_offline_agent(extra, tmp_path):
    args = ["--set", str(_set(tmp_path)), "--condition", "C0", "--max-usd", "1", "--out", str(tmp_path / "x.json"), *extra]
    assert R.main(args, settings_fn=lambda: Settings(_env_file=None, openai_api_key="fake-k"), c0_model_factory=lambda s: (FakeModel(), FakeLedger())) == 2
    assert not (tmp_path / "x.json").exists()


def test_c0_needs_only_the_openai_key(tmp_path, capsys):
    path = tmp_path / "x.json"
    rc = R.main(["--set", str(_set(tmp_path)), "--agent", "graph", "--condition", "C0", "--max-usd", "1", "--out", str(path)],
                settings_fn=lambda: Settings(_env_file=None), c0_model_factory=lambda s: (FakeModel(), FakeLedger()))
    out = capsys.readouterr().out
    assert rc == 0 and "OPENAI_API_KEY" in out and "SUPABASE" not in out and not path.exists()
