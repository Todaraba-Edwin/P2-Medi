"""시험 공통 설정.

- 서버 시작 백그라운드 준비(BE-17-01 A)는 시험에서 기본으로 끈다(`MEDIAGENT_WARMUP=0`). 실제 앱 lifespan을 여는 시험
  (예: `test_be13_deploy_prep.py`)이 루트 `.env`가 있는 체크아웃에서 돌 때 준비 스레드가 실제 자원(원격 DB)을 만들지 않게 한다.
  준비 동작을 보는 시험은 설정에 `mediagent_warmup=True`를 직접 넣는다(생성자 인자가 환경변수보다 앞선다).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _warmup_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIAGENT_WARMUP", "0")
