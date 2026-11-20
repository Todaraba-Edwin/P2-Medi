"""`.env` 위치 시험(2026-11-17): `cd backend`로 띄워도 저장소 루트 `.env`를 읽는다.

실제 `.env`는 읽지 않는다. `config.REPO_ROOT`를 monkeypatch로 tmp 폴더로 바꾸고 cwd도 tmp 아래로 옮긴다. 값은 모두 가짜다.
"""

import logging
from pathlib import Path

import pytest

from app import config
from app.config import default_env_files, get_settings, reveal

FIELDS = ("SUPABASE_URL", "OPENAI_API_KEY", "MEDIAGENT_API_MODE")


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in FIELDS:
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "repo"
    (root / "backend").mkdir(parents=True)
    (root / ".env").write_text(
        "SUPABASE_URL=http://root.example\nOPENAI_API_KEY=fake-root-key\nMEDIAGENT_API_MODE=snapshot\n", encoding="utf-8"
    )
    monkeypatch.setattr(config, "REPO_ROOT", root)
    return root


def test_repo_root_is_three_levels_up_from_config() -> None:
    real = Path(config.__file__).resolve()
    assert real.parent.name == "app"
    assert real.parent.parent.name == "backend"
    assert config.REPO_ROOT == real.parents[2]
    assert (config.REPO_ROOT / "backend" / "app" / "config.py").is_file()


def test_default_env_files_order_cwd_last(fake_repo: Path) -> None:
    # pydantic-settings는 뒤 파일이 앞 파일을 덮는다 → 현재 폴더 `.env`가 마지막(우선)
    assert default_env_files() == (str(fake_repo / ".env"), ".env")


@pytest.mark.parametrize("sub", [".", "backend"])
def test_same_settings_from_root_or_backend_cwd(fake_repo: Path, monkeypatch: pytest.MonkeyPatch, sub: str) -> None:
    monkeypatch.chdir(fake_repo / sub)
    s = get_settings()
    assert s.supabase_url == "http://root.example"
    assert reveal(s.openai_api_key) == "fake-root-key"
    assert s.mediagent_api_mode == "snapshot"


def test_cwd_env_overrides_repo_root(fake_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (fake_repo / "backend" / ".env").write_text("SUPABASE_URL=http://cwd.example\n", encoding="utf-8")
    monkeypatch.chdir(fake_repo / "backend")
    s = get_settings()
    assert s.supabase_url == "http://cwd.example"  # 현재 폴더 우선
    assert reveal(s.openai_api_key) == "fake-root-key"  # 없는 항목은 루트에서 채움


def test_environ_still_beats_env_files(fake_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "http://environ.example")
    monkeypatch.chdir(fake_repo / "backend")
    assert get_settings().supabase_url == "http://environ.example"


def test_local_pg_dsn_line_in_env_does_not_break_settings(fake_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # BE-11-14 A·18 A: 사용자가 루트 `.env`에 LOCAL_PG_DSN·프런트용 NEXT_PUBLIC_SUPABASE_*를 넣어도 기동이 깨지지 않는다
    # (선언 전에는 extra_forbidden). 값은 모두 가짜다
    for name in ("LOCAL_PG_DSN", "NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY"):
        monkeypatch.delenv(name, raising=False)
    with (fake_repo / ".env").open("a", encoding="utf-8") as f:
        f.write("LOCAL_PG_DSN=postgresql://fake@localhost:5432/fake_db\n"
                "NEXT_PUBLIC_SUPABASE_URL=http://front.example\n"
                "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_fakefront\n")
    monkeypatch.chdir(fake_repo)
    s = get_settings()
    assert reveal(s.local_pg_dsn) == "postgresql://fake@localhost:5432/fake_db"
    assert s.next_public_supabase_url == "http://front.example"
    assert reveal(s.next_public_supabase_publishable_key) == "sb_publishable_fakefront"
    assert "fake_db" not in repr(s) and "fakefront" not in repr(s)


@pytest.mark.parametrize("source", ["env_file", "environ"])
def test_tester_id_loads_and_is_not_exposed(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, source: str
) -> None:
    # 2026-11-20: 루트 `.env`(또는 환경변수)에 TESTER_ID가 있어도 기동이 깨지지 않고, 원문이 repr·str·dump·로그에 나오지 않는다.
    # 값은 가짜다
    fake = "fake-tester-0000"
    monkeypatch.delenv("TESTER_ID", raising=False)
    if source == "env_file":
        with (fake_repo / ".env").open("a", encoding="utf-8") as f:
            f.write(f"TESTER_ID={fake}\n")
    else:
        monkeypatch.setenv("TESTER_ID", fake)
    monkeypatch.chdir(fake_repo)
    s = get_settings()
    assert reveal(s.tester_id) == fake
    assert fake not in repr(s) and fake not in str(s) and fake not in str(s.model_dump())
    with caplog.at_level("DEBUG"):
        logging.getLogger("test.config").info("settings=%s tester=%s", s, s.tester_id)
    assert fake not in caplog.text


def test_no_env_files_anywhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in FIELDS:
        monkeypatch.delenv(name, raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(config, "REPO_ROOT", empty)
    monkeypatch.chdir(empty)
    s = get_settings()
    assert s.supabase_url is None
    assert s.openai_api_key is None
