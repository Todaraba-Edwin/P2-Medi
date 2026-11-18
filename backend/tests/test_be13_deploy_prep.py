"""BE-13 배포 준비 시험(2026-11-18, AWS 계정·Docker 없이 가능한 것). 원격 호출·LLM·DB 0.

- 외부 응답 점검 스크립트(`scripts/be13_health_check.py`)가 실제 앱에 대해 3가지 점검을 통과하고, 고장 난 서버는 잡는다.
- 이미지 배치(Dockerfile이 복사하는 `app/`·`prompts/`·`pyproject.toml`만, `data/`·`evaluation/`·`.env` 없음)에서 앱이 시작되고 `/health`가 200,
  필수 환경변수가 없으면 `/chat`이 501(의도된 상태)이다.
- Dockerfile이 비밀·로컬 데이터를 복사하지 않는다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))

import be13_health_check as H  # noqa: E402

from app.main import app  # noqa: E402


def test_health_check_passes_against_the_real_app_without_settings():
    with TestClient(app) as c:
        rows = H.check("http://testserver", client=c)
    assert [r["ok"] for r in rows] == [True, True, True], rows


def test_health_check_flags_a_broken_server_and_bad_urls(capsys):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "x"})

    assert H.main(["https://api.example.invalid"], transport=httpx.MockTransport(handler)) == 1
    assert "NG" in capsys.readouterr().out
    assert H.main(["ftp://x"]) == 2
    assert H.main(["http://api.example.invalid"], transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "ok"}))) == 1
    assert "https가 아니다" in capsys.readouterr().out


def test_connection_errors_are_reported_without_raising():
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with httpx.Client(transport=httpx.MockTransport(boom)) as c:
        rows = H.check("https://x.invalid", client=c)
    assert all(not r["ok"] and "ConnectError" in r["detail"] for r in rows)


def test_image_layout_starts_and_serves_health_without_data_or_evaluation(tmp_path):
    """Dockerfile과 같은 배치(/srv/backend/{app,prompts,pyproject.toml})를 임시 폴더에 만들고 그 안에서 앱을 띄운다."""
    srv = tmp_path / "srv" / "backend"
    srv.mkdir(parents=True)
    shutil.copytree(BACKEND / "app", srv / "app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(BACKEND / "prompts", srv / "prompts")
    shutil.copy(BACKEND / "pyproject.toml", srv / "pyproject.toml")
    code = ("import json; from fastapi.testclient import TestClient; from app.main import app; from app.llm import prompts as p; "
            "c = TestClient(app); c.__enter__(); "
            "print(json.dumps({'health': c.get('/health').json(), 'chat': c.post('/chat', json={'question': '타이레놀 먹어도 돼요?'}).status_code, "
            "'prompts_dir_ok': p.PROMPTS_DIR.is_dir(), 'app_file': __import__('app').__file__}))")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("OPENAI", "SUPABASE", "DUR", "ANTHROPIC", "UPSTAGE", "DRUG", "DRDEASY"))}
    env.update({"PYTHONPATH": str(srv), "MEDIAGENT_MODE": "service", "MEDIAGENT_EVAL": "0"})
    out = subprocess.run([sys.executable, "-c", code], cwd=srv, env=env, capture_output=True, text=True, timeout=120, check=False)  # noqa: S603
    assert out.returncode == 0, out.stderr[-2000:]
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert res["health"] == {"status": "ok"} and res["chat"] == 501 and res["prompts_dir_ok"] is True
    assert res["app_file"].startswith(str(srv))  # 이미지 배치의 소스를 썼다(저장소 소스가 아님)


def test_dockerfile_copies_only_runtime_files_and_no_secrets():
    text = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    copies = [ln.split()[1] for ln in text.splitlines() if ln.startswith("COPY ")]
    assert copies == ["pyproject.toml", "app", "prompts"]
    assert "ENV OPENAI" not in text and "ARG " not in text and "USER mediagent" in text
    ignore = (BACKEND / ".dockerignore").read_text(encoding="utf-8").split()
    assert ".env" in ignore and ".env.*" in ignore
