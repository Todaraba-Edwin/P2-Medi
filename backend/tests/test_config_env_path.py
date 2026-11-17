"""`.env` 위치 시험(2026-11-17): `cd backend`로 띄워도 저장소 루트 `.env`를 읽는다.

실제 `.env`는 읽지 않는다. `config.REPO_ROOT`를 monkeypatch로 tmp 폴더로 바꾸고 cwd도 tmp 아래로 옮긴다. 값은 모두 가짜다.
"""

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
