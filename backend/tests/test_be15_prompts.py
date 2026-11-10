"""BE-15 PRD-16-01: 로그 `prompt_set` 필드, 묶음 로더, 프롬프트 L0 검사. 합성 프롬프트만 쓴다(실제 질문·시험셋 문항 없음)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.llm import prompts as P
from app.logging.spans import SpanLogger, build_record

GOOD_FM = """---
id: P-AG01-model
version: v1
ticket: AG-01
model: gpt-6-luna
h_rules: [H1, H2]
golden_ids: [dev-001, dev-002]
status: draft
---
당신은 공공 의약품 데이터 근거로만 답하는 도우미입니다.
예시 형식: 질문: <약이름>과 <약이름>을 같이 먹어도 되나요?
"""


def write(d: Path, name: str, text: str) -> Path:
    (d / name).write_text(text, encoding="utf-8")
    return d / name


@pytest.fixture()
def pdir(tmp_path):
    write(tmp_path, "agent_system@v1.md", GOOD_FM)
    write(tmp_path, "router@v1.md", GOOD_FM.replace("P-AG01-model", "P-AG01-router"))
    write(tmp_path, "prompt_set@v1.yaml", "name: prompt_set@v1\nprompts:\n  - agent_system@v1\n  - router@v1\n")
    return tmp_path


def rules(vs):
    return {v.rule for v in vs}


# --------------------------------------------------------------------------- 로그 필드
@pytest.mark.parametrize("mode", ["dev", "eval", "service"])
def test_prompt_set_recorded_in_every_mode(mode):
    rec = build_record(mode, {"prompt_set": "prompt_set@v1", "node": "model"})
    assert rec["prompt_set"] == "prompt_set@v1"


def test_service_prompt_set_is_version_string_only_and_counted(tmp_path):
    for bad in ("agent_system@v1", "prompt_set@v1 타이레놀", "임의 문자열", 3, None):
        assert "prompt_set" not in build_record("service", {"prompt_set": bad, "node": "model"})
    from app.logging.spans import Aggregator

    agg = Aggregator(stream=None)
    agg.add_record(build_record("service", {"prompt_set": "prompt_set@v2", "node": "model", "input_text": "질문"}))
    line = agg.flush()
    assert line["counts"]["prompt_set=prompt_set@v2"] == 1 and "input_text" not in str(line)


def test_dev_logger_writes_prompt_set_and_keeps_prompt_version(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAGENT_LOG_DIR", str(tmp_path))
    logger = SpanLogger(mode="dev")
    logger.log(node="model", prompt_set="prompt_set@v1", prompt_version="agent_system@v1")
    import json

    rows = [json.loads(x) for f in tmp_path.rglob("*.jsonl") for x in f.read_text(encoding="utf-8").splitlines()]
    assert rows and rows[0]["prompt_set"] == "prompt_set@v1" and rows[0]["prompt_version"] == "agent_system@v1"


# --------------------------------------------------------------------------- 로더
def test_load_prompt_set_and_resolve_files(pdir):
    ps = P.load_prompt_set(pdir / "prompt_set@v1.yaml")
    assert ps.name == "prompt_set@v1" and ps.prompts == ("agent_system@v1", "router@v1")
    assert [Path(f).name for f in P.resolve_prompt_files("prompt_set@v1", pdir)] == ["agent_system@v1.md", "router@v1.md"]


@pytest.mark.parametrize("text", [
    "name: prompt_set@v2\nprompts:\n  - a@v1\n",  # 파일 이름과 다름
    "name: prompt_set@v1\nprompts:\n",  # 빈 목록
    "name: prompt_set@v1\nprompts:\n  - agent_system\n",  # 버전 없음
    "name: prompt_set@v1\nprompts:\n  - a@v1\n  - a@v2\n",  # 같은 이름 두 버전
    "name: set1\nprompts:\n  - a@v1\n",
])
def test_bad_sets_are_rejected(tmp_path, text):
    p = write(tmp_path, "prompt_set@v1.yaml", text)
    with pytest.raises(P.PromptSetError):
        P.load_prompt_set(p)
    assert rules(P.check_prompt_set(p)) == {"SET_FORMAT"}


def test_mini_yaml_inline_list_and_unsupported_nesting():
    assert P.parse_simple_yaml("a: [x, y]\nb: 'q'\nc:\n  - 1\n") == {"a": ["x", "y"], "b": "q", "c": ["1"]}
    with pytest.raises(P.PromptSetError):
        P.parse_simple_yaml("a:\n  b: 1\n")


# --------------------------------------------------------------------------- L0
def test_good_set_passes(pdir):
    assert P.check_prompt_set(pdir / "prompt_set@v1.yaml") == []
    assert P.check_all(pdir, pdir / "none.jsonl") == []


def test_missing_prompt_file(pdir):
    (pdir / "router@v1.md").unlink()
    vs = P.check_prompt_set(pdir / "prompt_set@v1.yaml")
    assert [(v.rule, v.detail) for v in vs] == [("MISSING_FILE", "router@v1")]


def test_frontmatter_required_and_forbidden(tmp_path):
    f = write(tmp_path, "a@v1.md", "---\nid: X\nversion: v1\nlast_eval: 2026-11-10 k/n\n---\n본문\n")
    vs = P.check_prompt_file(f)
    missing = {v.detail for v in vs if v.rule == "FRONTMATTER_MISSING"}
    assert missing == {"ticket", "model", "h_rules", "golden_ids", "status"}
    assert any(v.rule == "FRONTMATTER_FORBIDDEN" and v.detail == "last_eval" for v in vs)
    assert rules(P.check_prompt_file(write(tmp_path, "b@v1.md", "본문만\n"))) == {"FRONTMATTER_MISSING"}


def test_version_status_and_golden_ids(tmp_path):
    f = write(tmp_path, "a@v2.md", GOOD_FM.replace("golden_ids: [dev-001, dev-002]", "golden_ids: [test-001]").replace("status: draft", "status: ok"))
    vs = P.check_prompt_file(f)
    assert {"FRONTMATTER_VALUE", "GOLDEN_ID"} <= rules(vs) and sum(v.rule == "FRONTMATTER_VALUE" for v in vs) == 2  # version v1≠@v2, status


def test_secret_detected_without_echoing_value(tmp_path):
    secret = "sk-" + "A1b2C3d4E5f6"
    f = write(tmp_path, "a@v1.md", GOOD_FM + f"키: {secret}\n")
    vs = P.check_prompt_file(f)
    assert [v.rule for v in vs] == ["SECRET"] and secret not in str(vs[0])


def test_dev_set_sentence_detected_by_id_not_text(tmp_path):
    sentence = "임신 중인데 합성약정을 먹어도 되는지 알려 주세요"
    dev = {"dev-777": P._norm(sentence)}
    f = write(tmp_path, "a@v1.md", GOOD_FM + f"예: {sentence}\n")
    vs = P.check_prompt_file(f, dev_questions=dev)
    assert [(v.rule, v.detail) for v in vs] == [("DEV_SET_SENTENCE", "dev-777")] and "합성약정" not in str(vs[0])
    assert P.check_prompt_file(f, dev_questions={"dev-1": P._norm("전혀 다른 문장입니다 정말로")}) == []  # 다른 문장은 통과


def test_real_question_with_product_name_detected_placeholder_allowed(tmp_path):
    ok = write(tmp_path, "a@v1.md", GOOD_FM + '예시: "<약이름> 먹어도 되나요?"\n지시: 타이레놀정 같은 제품명은 사전으로 확인한다.\n')
    assert P.check_prompt_file(ok) == []
    bad = write(tmp_path, "b@v1.md", GOOD_FM + '예시: "어제부터 타이레놀정500mg을 먹었는데 같이 먹어도 되나요?"\n질문: 아이에게 어린이부루펜시럽 줘도 되나요?\n')
    vs = P.check_prompt_file(bad)
    assert [v.rule for v in vs] == ["REAL_QUESTION", "REAL_QUESTION"] and all("타이레놀" not in str(v) for v in vs)


def test_check_all_includes_unlisted_prompt_files(pdir):
    write(pdir, "extra@v1.md", "---\nid: X\n---\n")
    assert any(v.file == "extra@v1.md" for v in P.check_all(pdir, pdir / "none.jsonl"))


def test_real_dev_set_loads_and_repo_prompts_pass():
    """개발셋(시험셋 아님)을 읽어 검사에 쓴다. 저장소의 현재 프롬프트 파일은 위반이 없어야 한다."""
    dev = P.load_dev_questions()
    assert dev == {} or all(k.startswith("dev-") for k in dev)
    assert P.check_all() == []
