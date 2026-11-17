"""2026-11-17 정합성 점검 반영(H-2·H-3·H-6) 시험.

- H-2: `eval_runner --condition`은 연결된 조건만 받는다(다른 값은 세트를 읽기 전에 종료 코드 2). 2026-11-18 C1(AG-16 고정 파이프라인)을 연결해
  C2·C1을 받고, C1은 `--agent graph`에서만 받는다(offline-fixed는 조건과 무관한 연결 확인용). C1+·C0·C3는 여전히 거부한다.
- H-3: `build_eval_set`은 출력 파일이 이미 있으면 덮어쓰기를 거부한다(`--overwrite-frozen`과 환경변수가 둘 다 있어야 허용).
  임시 폴더의 가짜 파일만 쓰고, 실제 빌드(`build_and_write`)는 부르지 않으며 시험셋 파일은 열지 않는다(존재 여부만 본다).
- H-6: 도구 모듈의 문자열(모델 입력이 되는 노트 포함)에 화면 금지 용어(한글 문구)가 없다. 주석은 보지 않는다(AST 문자열 상수만).

LLM·judge·공공 API·원격 DB 호출 0.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "evaluation", ROOT / "evaluation" / "eval_set"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import build_eval_set as B  # noqa: E402
import eval_runner as R  # noqa: E402
import sealed_guard as G  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402

ALLOW_ENV = {B.OVERWRITE_ENV: B.OVERWRITE_ENV_VALUE}


# ------------------------------------------------------------------ H-2 비교 조건 가드

def test_connected_conditions_are_c2_and_c1():
    assert R.SUPPORTED_CONDITIONS == ("C2", "C1") and R.DEFAULT_CONDITION == "C2"


@pytest.mark.parametrize("cond", ["C1+", "c2", "c1", "C0", "C3", ""])
def test_unconnected_condition_is_refused_before_reading_set(cond, tmp_path, capsys):
    missing = tmp_path / "does_not_exist.jsonl"  # 세트를 읽으려 했다면 FileNotFoundError가 났을 것
    rc = R.main(["--set", str(missing), "--condition", cond, "--out", str(tmp_path / "out.json")])
    assert rc == 2
    out = capsys.readouterr().out
    assert "C2" in out and "실행하지 않았다" in out
    assert not (tmp_path / "out.json").exists()


def test_c1_is_refused_for_offline_agent_before_reading_set(tmp_path, capsys):
    """C1은 그래프를 실제로 만들 때만 뜻이 있다. offline-fixed 결과에 C1 표기가 붙지 않게 세트를 읽기 전에 막는다."""
    rc = R.main(["--set", str(tmp_path / "does_not_exist.jsonl"), "--condition", "C1", "--out", str(tmp_path / "out.json")])
    assert rc == 2
    out = capsys.readouterr().out
    assert "C1" in out and "graph" in out and "실행하지 않았다" in out
    assert not (tmp_path / "out.json").exists()


@pytest.mark.parametrize("cond", ["C1+", "C3"])
def test_unconnected_condition_refused_for_graph_agent_too(cond, tmp_path, capsys):
    rc = R.main(["--set", str(tmp_path / "x.jsonl"), "--agent", R.GRAPH_AGENT, "--condition", cond, "--max-usd", "0.01"])
    assert rc == 2
    assert cond in capsys.readouterr().out


def test_default_condition_c2_still_runs(tmp_path):
    src = ROOT / "evaluation" / "eval_set" / "dev_set.jsonl"
    if not src.exists():
        pytest.skip("개발셋 파일 없음")
    out = tmp_path / "res.json"
    assert R.main(["--set", "dev", "--limit", "2", "--out", str(out)]) == 0
    assert out.exists()


# ------------------------------------------------------------------ H-3 고정 세트 덮어쓰기 가드

def _fake_outputs(tmp_path: Path) -> list[Path]:
    return [tmp_path / "dev_set.jsonl", tmp_path / "test_set.SEALED.jsonl", tmp_path / "manifest.json"]


def test_no_existing_outputs_is_allowed_without_flag(tmp_path):
    assert B.check_frozen_outputs(_fake_outputs(tmp_path), overwrite_frozen=False, env={}) == []


@pytest.mark.parametrize("flag,env", [(False, {}), (True, {}), (False, ALLOW_ENV),
                                      (True, {B.OVERWRITE_ENV: "yes"})])
def test_existing_output_is_refused_unless_flag_and_env(tmp_path, flag, env):
    paths = _fake_outputs(tmp_path)
    paths[1].write_text("{}\n", encoding="utf-8")  # 가짜 SEALED 파일(존재만 본다)
    with pytest.raises(B.FrozenSetError) as ei:
        B.check_frozen_outputs(paths, overwrite_frozen=flag, env=env)
    msg = str(ei.value)
    assert "test_set.SEALED.jsonl" in msg and "--overwrite-frozen" in msg and B.OVERWRITE_ENV in msg


def test_existing_output_allowed_with_flag_and_env(tmp_path):
    paths = _fake_outputs(tmp_path)
    paths[0].write_text("{}\n", encoding="utf-8")
    assert B.check_frozen_outputs(paths, overwrite_frozen=True, env=ALLOW_ENV) == [paths[0]]


def test_broken_symlink_counts_as_existing(tmp_path):
    paths = _fake_outputs(tmp_path)
    paths[0].symlink_to(tmp_path / "nowhere.jsonl")
    with pytest.raises(B.FrozenSetError):
        B.check_frozen_outputs(paths, overwrite_frozen=False, env={})


def test_guard_does_not_open_files(tmp_path, monkeypatch):
    paths = _fake_outputs(tmp_path)
    paths[1].write_text("{}\n", encoding="utf-8")

    def boom(*_a, **_k):  # pragma: no cover - 불리면 실패
        raise AssertionError("가드가 파일을 열었다")

    monkeypatch.setattr("builtins.open", boom)
    monkeypatch.setattr(Path, "read_bytes", boom)
    monkeypatch.setattr(Path, "read_text", boom)
    with pytest.raises(B.FrozenSetError):
        B.check_frozen_outputs(paths, overwrite_frozen=False, env={})


@pytest.fixture
def tmp_builder(tmp_path, monkeypatch):
    """빌더 출력 경로를 임시 폴더로 돌리고 실제 빌드는 기록만 하는 가짜로 바꾼다."""
    paths = _fake_outputs(tmp_path)
    monkeypatch.setattr(B, "OUT", {"dev": paths[0], "test": paths[1]})
    monkeypatch.setattr(B, "MANIFEST_OUT", paths[2])
    calls: list[int] = []
    monkeypatch.setattr(B, "build_and_write", lambda: calls.append(1))
    return paths, calls


def test_main_refuses_by_default_and_does_not_build(tmp_builder, capsys):
    paths, calls = tmp_builder
    paths[2].write_text("{}", encoding="utf-8")
    assert B.main([], env=ALLOW_ENV) == 2  # 환경변수만으로는 부족
    assert B.main(["--overwrite-frozen"], env={}) == 2  # 플래그만으로도 부족
    assert calls == []
    assert "덮어쓰지 않았다" in capsys.readouterr().err


def test_main_builds_when_no_outputs(tmp_builder):
    _, calls = tmp_builder
    assert B.main([], env={}) == 0
    assert calls == [1]


def test_main_overwrites_only_with_both(tmp_builder):
    paths, calls = tmp_builder
    paths[0].write_text("{}\n", encoding="utf-8")
    assert B.main(["--overwrite-frozen"], env=ALLOW_ENV) == 0
    assert calls == [1]


def test_real_frozen_outputs_are_protected_by_default():
    """실제 경로: 개발셋이 있으면 기본 호출은 막힌다(빌드 없음, 시험셋은 존재 여부만)."""
    if not B.OUT["dev"].exists():
        pytest.skip("개발셋 파일 없음")
    with pytest.raises(B.FrozenSetError):
        B.check_frozen_outputs([B.OUT["dev"], B.OUT["test"], B.MANIFEST_OUT], overwrite_frozen=False, env={})


# ------------------------------------------------------------------ 2차: test_build.py 시험셋 열람 가드
# 실제 시험셋은 열지 않는다. B.OUT을 임시 폴더의 가짜 파일로 돌리고 open·read_bytes를 감시한다.

@pytest.fixture
def open_spy(monkeypatch):
    """builtins.open과 Path.read_bytes로 연 경로를 기록한다(원래 동작은 그대로)."""
    import builtins

    opened: list[str] = []
    real_open, real_read_bytes = builtins.open, Path.read_bytes

    def spy_open(file, *a, **k):
        opened.append(str(file))
        return real_open(file, *a, **k)

    def spy_read_bytes(self):
        opened.append(str(self))
        return real_read_bytes(self)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(Path, "read_bytes", spy_read_bytes)
    return opened


def _sealed_opens(opened: list[str]) -> list[str]:
    return [p for p in opened if ".sealed." in Path(p).name.lower()]


def _fresh_test_build():
    import importlib

    sys.modules.pop("test_build", None)
    return importlib.import_module("test_build")


@pytest.fixture
def fake_sets(tmp_path, monkeypatch):
    """가짜 개발셋·시험셋(합성 1문항)으로 B.OUT을 돌리고 test_build를 새로 import한다. 허용 환경변수는 지운다."""
    dev, sealed = tmp_path / "dev_set.jsonl", tmp_path / "test_set.SEALED.jsonl"
    dev.write_text('{"id": "fake-dev-1"}\n', encoding="utf-8")
    sealed.write_text('{"id": "fake-test-1"}\n', encoding="utf-8")
    monkeypatch.setattr(B, "OUT", {"dev": dev, "test": sealed})
    monkeypatch.delenv(G.SEALED_ENV, raising=False)
    monkeypatch.delenv("MEDIAGENT_TEST_BUILD_ALLOW_SEALED", raising=False)
    yield _fresh_test_build()
    sys.modules.pop("test_build", None)


def test_test_build_import_opens_no_eval_set(open_spy, tmp_path, monkeypatch):
    monkeypatch.setattr(B, "OUT", {"dev": tmp_path / "dev_set.jsonl", "test": tmp_path / "test_set.SEALED.jsonl"})
    try:
        _fresh_test_build()  # 예전에는 모듈 수준에서 두 세트를 열었다
    finally:
        sys.modules.pop("test_build", None)
    assert [p for p in open_spy if str(tmp_path) in p] == []


@pytest.mark.parametrize("guard_env,flag_env", [(False, False), (True, False), (False, True)])
def test_sealed_checks_skip_without_both_permissions(fake_sets, open_spy, monkeypatch, guard_env, flag_env):
    tb = fake_sets
    if guard_env:
        monkeypatch.setenv(G.SEALED_ENV, G.SEALED_ENV_VALUE)
    if flag_env:
        monkeypatch.setenv(tb.FLAG_ENV, "1")
    for fn in (tb.test_items, tb.test_golden, tb.test_reliability_core, tb.test_multihop,
               tb.test_dev_test_disjoint, tb.test_rederive_sample, tb.test_sealed_checks_need_permission):
        with pytest.raises(pytest.skip.Exception):
            fn()
    assert set(tb.sets()) == {"dev"}  # 두 세트를 도는 검사는 개발셋만
    assert tb.dev_items() == [{"id": "fake-dev-1"}]
    assert _sealed_opens(open_spy) == []


def test_sealed_items_load_only_with_both_permissions(fake_sets, open_spy, monkeypatch):
    tb = fake_sets
    monkeypatch.setenv(G.SEALED_ENV, G.SEALED_ENV_VALUE)
    monkeypatch.setenv(tb.FLAG_ENV, "1")
    assert tb.test_items() == [{"id": "fake-test-1"}]  # 임시 폴더의 가짜 SEALED 파일
    assert set(tb.sets()) == {"dev", "test"}
    assert len(_sealed_opens(open_spy)) == 1  # 캐시: 한 번만 연다


def test_test_items_helper_is_not_collected(fake_sets):
    assert fake_sets.test_items.__test__ is False
    assert fake_sets.test_items not in fake_sets.ALL


# ------------------------------------------------------------------ H-6 도구 문자열의 화면 금지 용어

# 상태명·`L1`·`L3`·"단계"는 코드 상수·내부 키로 쓰이므로 여기서는 한글 문구만 본다(화면 검사는 finalize 시험이 맡는다).
_KOREAN_FORBIDDEN = [t for t in fp.FORBIDDEN_SCREEN_TERMS if any("가" <= ch <= "힣" for ch in t) and t != "단계"]


def _string_constants(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [(n.lineno, n.value) for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_korean_forbidden_terms_list_is_not_empty():
    assert "허가 라벨" in _KOREAN_FORBIDDEN


@pytest.mark.parametrize("path", sorted((ROOT / "backend" / "app" / "tools").glob("*.py")), ids=lambda p: p.name)
def test_tool_strings_have_no_screen_forbidden_terms(path):
    hits = [(ln, t) for ln, s in _string_constants(path) for t in _KOREAN_FORBIDDEN if t in s]
    assert hits == [], f"{path.name}: {hits}"
