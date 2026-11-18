# MediAgent 백엔드(FastAPI) 이미지 초안(BE-13, 2026-11-18). 빌드 맥락은 `backend/`다: `docker build -t mediagent-backend backend/`
#
# - 런타임에 필요한 것만 담는다: `app/`(코드)와 `prompts/`(프롬프트 파일, `app.llm.prompts.PROMPTS_DIR`).
#   `data/`·`evaluation/`·`logs/`·`.env`는 넣지 않는다(서비스는 DB를 원칙으로 읽는다, BE-06-24 B. 비밀은 플랫폼 환경변수로만).
# - 경로 규칙: 코드가 `app/..`의 상위 폴더를 저장소 루트로 보므로(`parents[3]`) `/srv/backend/app`에 둔다(`PROMPTS_DIR = /srv/backend/prompts`).
#   패키지로 설치하면 경로가 site-packages로 바뀌므로 의존성만 설치하고 소스는 그대로 둔다.
# - 시작 때 어디에도 접속하지 않는다(lifespan, BE-06-22 A). 필수 환경변수가 없으면 `/chat`은 501, `/health`는 200이다.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MEDIAGENT_MODE=service

WORKDIR /srv/backend

# 의존성: pyproject.toml의 [project].dependencies만(dev·eval extra 제외). 소스보다 먼저 복사해 층 캐시를 살린다
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY app ./app
COPY prompts ./prompts

RUN useradd --system --uid 10001 --no-create-home mediagent
USER mediagent

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# 프록시(로드밸런서·Caddy 등) 뒤에서 HTTPS를 끝낸다. 워커 1개(요청별 그래프, 지연 자원은 프로세스당 1회 생성)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--workers", "1"]
