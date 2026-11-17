# ruff: noqa: S101  (시험 파일: assert 허용, backend/pyproject.toml의 "**/tests/**" 규칙과 같은 취지)
"""S-05(보안 점검 2026-11-11): `evaluation/`에서 키·DSN을 읽거나 외부 호출을 하는 스크립트가 진입 시 `install_excepthook()`을 설치하는지.

스크립트 전체를 실행하면 LLM·공공 API를 부르므로 실행하지 않는다. 대신 AST에서 `if __name__ == "__main__":` 블록을 찾아
- 설치 호출이 그 블록 안에만 있고(import만 하면 설치되지 않음), 모듈 수준 작업(`import _common`·클라이언트 생성 등)보다 앞서는지,
- 그 블록의 설치 문장만 떼어 가짜 `__main__` 이름공간에서 실행한 뒤, 가짜 키(`QQQQ…`)가 든 예외를 `sys.excepthook`으로 내보내
  전체 값과 앞·뒤 4자 조각이 가려지는지를 본다. 외부 호출 0, `.env` 내용은 출력하지 않는다.

실행(저장소 루트): `cd backend && .venv/bin/python -m pytest ../evaluation/test_secguard_entrypoints.py -q`
"""

from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parent
ROOT = EVAL.parent
BACKEND = ROOT / "backend"

# 키·DSN을 읽거나 외부 호출을 하는 진입 스크립트(제외 목록과 이유는 보고서 data/mock/briefs/reports/quality-engineer.md)
ENTRY_SCRIPTS = [
    "credit_use/build_pool.py",
    "credit_use/t3_judge_dryrun.py",
    "credit_use/t4_ragas_ko.py",
    "credit_use/t5_upstage_compare.py",
    "eval_runner.py",
    "mock_gen/api_snapshot.py",
    "mock_gen/llm_cache.py",
    "mock_gen/m1_chat.py",
    "mock_gen/m3_judge.py",
    "mock_gen/m3b_extra.py",
    "mock_gen/m4_templates.py",
    "mock_gen/m5_validator.py",
    "mock_gen/vision_pouch_test.py",
]
# 모듈 수준에서 작업하는 스크립트(설치 블록이 첫 비표준 import보다 앞서야 한다)
MODULE_LEVEL = {"credit_use/t3_judge_dryrun.py", "credit_use/t4_ragas_ko.py", "credit_use/t5_upstage_compare.py", "mock_gen/m3b_extra.py"}

FAKE_KEY = "QQQQ" + "7f3a9c1e5b2d8046" + "ZZZZ"  # 가짜 값(실제 키 모양이 아님)


def _is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If):
        return False
    t = node.test
    return (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "__name__"
            and len(t.comparators) == 1 and isinstance(t.comparators[0], ast.Constant) and t.comparators[0].value == "__main__")


def _calls_install(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "install_excepthook" for n in ast.walk(node))


def _guard_and_index(tree: ast.Module) -> tuple[ast.If, int]:
    found = [(i, n) for i, n in enumerate(tree.body) if _is_main_guard(n) and _calls_install(n)]
    assert len(found) == 1, "install_excepthook()을 부르는 `if __name__ == \"__main__\"` 블록이 정확히 하나여야 한다"
    return found[0][1], found[0][0]


@pytest.fixture
def restore_hooks():
    saved_hook, saved_path = sys.excepthook, list(sys.path)
    yield
    sys.excepthook = saved_hook
    sys.path[:] = saved_path
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from app.logging.redact_filter import uninstall_log_redaction

    uninstall_log_redaction()


@pytest.mark.parametrize("rel", ENTRY_SCRIPTS)
def test_entry_script_installs_excepthook_and_redacts(rel, monkeypatch, restore_hooks):
    path = EVAL / rel
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    guard, idx = _guard_and_index(tree)

    # 1) 설치 호출은 __main__ 블록 안에만 있다(import만 할 때는 설치하지 않음)
    outside = [n for i, n in enumerate(tree.body) if i != idx and _calls_install(n)]
    assert not outside, f"{rel}: __main__ 블록 밖에서 install_excepthook()을 부른다"
    # 블록 안에서는 설치가 다른 작업보다 먼저다(앞에는 경로 추가·import·주석만)
    first_install = next(i for i, s in enumerate(guard.body) if _calls_install(s))
    for s in guard.body[:first_install]:
        assert isinstance(s, (ast.Import, ast.ImportFrom, ast.Expr)), f"{rel}: 설치 전에 다른 작업이 있다"

    # 2) 모듈 수준 스크립트는 설치 블록이 _common·외부 SDK import보다 앞선다
    if rel in MODULE_LEVEL:
        local_or_sdk = [i for i, n in enumerate(tree.body)
                        if isinstance(n, (ast.Import, ast.ImportFrom)) and not _is_stdlib_import(n)]
        assert local_or_sdk and idx < min(local_or_sdk), f"{rel}: 설치 블록이 _common·SDK import보다 뒤에 있다"

    # 3) 설치 문장만 가짜 __main__ 이름공간에서 실행 → 가짜 키가 든 예외가 가려지는지
    stmts = guard.body[: first_install + 1]
    code = compile(ast.Module(body=stmts, type_ignores=[]), str(path), "exec")
    sys.excepthook = sys.__excepthook__
    ns = {"__name__": "__main__", "__file__": str(path), "sys": sys, "Path": Path}
    if rel == "eval_runner.py":  # eval_runner는 모듈 머리에서 backend를 sys.path에 넣는다(여기서 같은 상태를 만든다)
        sys.path.insert(0, str(BACKEND))
    exec(code, ns)  # noqa: S102 - 저장소 안 스크립트의 설치 문장만 실행(외부 호출 없음)
    assert sys.excepthook is not sys.__excepthook__, f"{rel}: sys.excepthook이 바뀌지 않았다"

    monkeypatch.setenv("MEDIAGENT_FAKE_TEST_API_KEY", FAKE_KEY)
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    try:
        raise RuntimeError(f"connect failed key={FAKE_KEY} head={FAKE_KEY[:4]}x tail=y{FAKE_KEY[-4:]}")
    except RuntimeError as exc:
        sys.excepthook(type(exc), exc, exc.__traceback__)
    out = err.getvalue()
    assert "RuntimeError" in out
    assert FAKE_KEY not in out
    assert "QQQQ" not in out and "ZZZZ" not in out, f"{rel}: 키 앞·뒤 조각이 남았다"
    assert "***" in out


_STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}


def _is_stdlib_import(node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").split(".")[0] in _STDLIB
    return all(a.name.split(".")[0] in _STDLIB for a in node.names)
