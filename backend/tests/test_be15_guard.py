"""BE-15 pre-commit 가드(scripts/precommit_guard.py) 시험. 비밀 값은 시험 안에서 조립해 저장소에 남기지 않는다."""

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("precommit_guard", Path(__file__).resolve().parents[2] / "scripts" / "precommit_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def test_blocks_env_and_local_only_paths(tmp_path):
    for rel in (".env", ".env.local", "backend/.env", "data/x.csv", "P2-doc/report/a.md", "tickets/issues/ISSUE-001.png", "logs/dev/a.jsonl"):
        assert guard.check(rel, tmp_path), rel
    for rel in (".env.example", "backend/app/main.py", "P2-doc/PJ2-RFP.md", "tickets/backend/BE-15.md"):
        assert not guard.check(rel, tmp_path), rel


def test_blocks_secret_patterns(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("KEY = '" + "sk-" + "A" * 30 + "'\n")
    assert any("sk-" in p for p in guard.check("a.py", tmp_path))
    f.write_text("url = 'https://x?service" + "Key=" + "Ab1+" * 5 + "'\n")
    assert guard.check("a.py", tmp_path)
    f.write_text("db = 'postgres" + "://user:pw@host:5432/db'\n")
    assert guard.check("a.py", tmp_path)
    f.write_text("print('hello')\n")
    assert not guard.check("a.py", tmp_path)


def test_blocks_big_files(tmp_path):
    (tmp_path / "big.bin").write_bytes(b"0" * (guard.MAX_BYTES + 1))
    assert guard.check("big.bin", tmp_path)
