# backend/tests 개발 하네스 안내 (BE-15)

## 실행
- 시험: `cd backend && .venv/bin/python -m pytest -q`
- 린트: `backend/.venv/bin/ruff check --config backend/pyproject.toml backend` (dev 의존성 설치 뒤)
- pre-commit: 저장소 루트 `.pre-commit-config.yaml`(비밀·`.env`·로컬 전용 폴더 차단, `check_schedule.py`, ruff). 설치는 `pre-commit install`.
- 응답 스냅샷은 `tests/fixtures/api/`를 쓴다.

## 로깅 규칙 (RFP-34, H13)
- **실제 사용자 질문을 개발(dev) trace에 넣지 않는다.** dev·eval trace에는 합성·가상 질문과 mock만 쓴다.
- `MEDIAGENT_MODE`는 `dev|eval|service`(기본 service). `eval`은 `MEDIAGENT_EVAL=1`과 함께만 켠다.
- service 모드는 내용 없는 집계만 남기고 질문·약 이름·모델 출력은 레코드를 만들 때 버린다. 로그는 로컬 `logs/`에만 쓰며 커밋하지 않는다.
- 개발 trace는 14일 뒤 지운다: `cd backend && .venv/bin/python -m app.logging cleanup`.

## LLM 호출·비용
- `LLM_CACHE=off|record|replay`(기본 off). `MEDIAGENT_EVAL=1`이면 항상 off.
- 개발 비용 원장 상한 2.5 USD(`app/llm/ledger.py`, 파일은 `data/mock/openai_ledger.json`). 넘으면 실호출을 중단하고 replay만 쓴다.
