# Can I PPiyak (MediAgent)

> **초안(PRD-04, 2026-11-18, documents-writer).** 배포 주소·시연 전 점검 절차·평가 재현 명령의 확정판은 BE-13(배포 리허설)·BE-08 뒤에 채운다. 이 문서의 수치는 `P2-doc/PJ2-RFP.md` 9.6절의 표를 그대로 옮겼고, 환경변수는 이름만 적었다(값은 저장소에 없다).

## Index
- [1. 프로젝트 성격](#1-프로젝트-성격)
- [2. 구조](#2-구조)
- [3. 스택과 이유](#3-스택과-이유)
- [4. 실행 방법](#4-실행-방법)
  - [(1) 준비](#1-준비)
  - [(2) 백엔드](#2-백엔드)
  - [(3) 가짜 자원 서버](#3-가짜-자원-서버)
  - [(4) 프런트](#4-프런트)
  - [(5) 환경변수 이름](#5-환경변수-이름)
- [5. 평가 요약](#5-평가-요약)
  - [(1) AG-11 기준선 확정 값](#1-ag-11-기준선-확정-값)
  - [(2) 평가 실행](#2-평가-실행)
- [6. 데이터 출처와 이용 조건](#6-데이터-출처와-이용-조건)
- [7. 문서](#7-문서)
- [8. 면책과 한계](#8-면책과-한계)

## 1. 프로젝트 성격
금기 판정과 사실은 공공 API·파일 데이터·문서에서 코드가 가져오고, LLM 에이전트는 도구 선택과 근거 탐색, 쉬운 설명·종합만 맡는 근거 기반 질의응답 에이전트다. 임산부·영유아·아동·고령자가 있는 집에서 상비약·보유 의약품을 먹기 전에 병용·연령·임부 금기를 스스로 확인하게 해 오남용을 막는 것이 도메인이다. 서비스 표시 이름은 **Can I PPiyak(삐약)**이고 저장소·코드 이름은 MediAgent다.

- **취업 포트폴리오다.** 핵심 목표는 Agent-RAG를 활용한 AX(AI 전환) 경험, 곧 에이전트(Router, 도구 선택, 근거 고정, Validator)를 직접 설계·구현·평가하고 수치로 개선을 보이는 것이다.
- 원스글로벌 Dr.DI 같은 기존 서비스는 아이디어에 가능성이 있음을 확인한 사례일 뿐이며, 재현하거나 성능을 비교하지 않았다. 같은 문제를 Agent-RAG의 대상 도메인으로 삼아 **3주·1인 개발 규모로 범위를 제어한 축소판**이다.
- 진단·처방·복용량 결정을 하는 서비스가 아니다(8장).

## 2. 구조
ReAct 에이전트가 중심이며 LangGraph 6노드 `guardrail_in → router → model ⇄ tools → validator → finalize`로 구성한다. 판정·고정 문구·119 안내는 프롬프트가 아니라 코드가 강제한다. 대조군 C1(고정 파이프라인)은 같은 노드를 재사용한다. 그림과 데이터 흐름, 환각 방지 장치, 평가 하네스 개요는 [`P2-doc/PJ2-아키텍처.md`](P2-doc/PJ2-아키텍처.md)에 있다.

| 폴더 | 내용 |
|---|---|
| `backend/` | FastAPI 서버. `app/{api,db,tools,agent}`, `prompts/`, `scripts/`, `tests/` |
| `frontend/` | Next.js + TypeScript + pnpm |
| `evaluation/` | 평가 러너·지표·평가 세트(시험셋 제외) |
| `P2-doc/` | RFP·PRD·설계 문서 |
| `tickets/`, `schedule.md` | 티켓과 일정 |

## 3. 스택과 이유
| 항목 | 선택 | 근거 |
|---|---|---|
| 에이전트 | LangGraph(ReAct) | Agent-RAG가 중심이므로 그래프로 노드·분기를 더해 개선한다 |
| LLM | OpenAI 계열 `gpt-6-luna` | RFP 8.2절, `tickets/doc/RFP-22.md` |
| 평가 judge | Claude Sonnet 5.5(`claude-sonnet-5-5`) 고정 | 평가 기간 중 모델·루브릭 변경 금지(RFP-26-01) |
| DB·벡터 | Supabase Pro(Postgres + pgvector, Auth) | 배포 요건(RFP-15-03). 근거 코퍼스 용량 추정 약 970MB가 무료 한도(500MB)를 넘어 Pro로 변경(BE-05-03 D, 2026-11-11) |
| 배포 | Vercel(프런트)·AWS(백엔드) | RFP-15 §7. 최소 구성 배포는 BE-13 |
| 파서·임베딩 | RFP-15 시험 결과 | 확정 값은 `tickets/doc/RFP-15.md`와 아키텍처 문서 4장 |

## 4. 실행 방법
### (1) 준비
- Python 3.11 이상(`backend/pyproject.toml`), Node.js와 pnpm.
- 저장소 루트의 `.env`에 환경변수를 둔다(이름은 (5)). `.env`는 커밋하지 않는다.
- 백엔드 가상환경은 `backend/.venv`를 쓴다고 가정한다(문서·스크립트가 이 경로를 쓴다).

### (2) 백엔드
`backend/app/main.py`의 FastAPI 앱 `app`을 uvicorn으로 띄운다. 가정: 진입점 모듈 경로는 `app.main:app`이며 `backend/`를 작업 디렉터리로 쓴다.

```bash
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --port 8000
```

- 상태 확인: `GET /health`
- 질문 1건: `POST /chat`. 요청·응답 스키마는 서버가 띄우는 `/docs`(OpenAPI)에서 확인한다.
- 시험: `PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests -q -p no:cacheprovider`

### (3) 가짜 자원 서버
외부 호출 0, 127.0.0.1 고정인 개발 전용 서버다. 실제 키·DB 없이 화면과 `/chat` 흐름을 확인할 때 쓴다.

```bash
backend/.venv/bin/python backend/scripts/dev_fake_server.py --port 8000
```

`--slow-seconds`로 느린 응답을 흉내 낼 수 있다. 제공 경로는 `/health`와 `POST /chat`이다.

### (4) 프런트
`frontend/`에서 pnpm 스크립트를 쓴다(`frontend/package.json`).

```bash
pnpm --dir frontend install
pnpm --dir frontend dev
```

- 그 밖의 스크립트: `build`, `start`, `lint`, `test`(vitest), `gen:api`(백엔드 OpenAPI에서 타입 생성).
- 프런트가 백엔드를 부르는 주소는 `MEDIAGENT_BACKEND_ORIGIN`(서버 전용 rewrites 대상)과 `NEXT_PUBLIC_API_BASE_URL`이다. `NEXT_PUBLIC_API_MOCKING`이 `enabled`일 때만 MSW 목을 쓴다.
- 세부는 `frontend/README.md`.

### (5) 환경변수 이름
값은 문서에 쓰지 않는다. 코드는 환경변수로만 읽는다.

| 대상 | 변수 이름 |
|---|---|
| e약은요 서비스 | `DRDEASYDRUG_END_POINT`, `DRDEASYDRUG_API_KEY` |
| DUR 품목정보 | `DURPrdlstInfoService03_END_POINT`, `DURPrdlstInfoService03_API_KEY` |
| DUR 성분정보 | `DURIrdntInfoService03_END_POINT`, `DURIrdntInfoService03_API_KEY` |
| 의약품 제품 허가정보 | `DrugPrdtPrmsnInfoService08_END_POINT`, `DrugPrdtPrmsnInfoService08_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic(평가 judge 전용, 서비스 런타임에는 쓰지 않음) | `ANTHROPIC_API_KEY` |
| Upstage(평가 문항 생성) | `UPSTAGE_API_KEY` |
| Supabase(DB) | `SUPABASE_DB_URL` |
| Supabase(로그인, 확장) | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `SUPABASE_JWKS_URL` |
| 프런트 | `MEDIAGENT_BACKEND_ORIGIN`, `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_API_MOCKING` |

## 5. 평가 요약
평가 기준의 단일 원본은 [`P2-doc/PJ2-RFP.md`](P2-doc/PJ2-RFP.md) 9장이다. 결과는 k/n과 Wilson 95% 구간으로 보고하며, 칸당 n이 8 이하면 유의성을 주장하지 않는다(9.1절).

### (1) AG-11 기준선 확정 값
`P2-doc/PJ2-RFP.md` 9.6절 결과 기록 표를 그대로 옮긴 것이다(시험셋, C2 조건, 2026-11-18). "개선 후"는 측정 전이다.

| 항목 | 기준선 | 개선 후 | 비고 |
|---|---|---|---|
| 검색 정확도 | C2 Context Precision 0.975·Recall 0.891(Ragas 평균 점수) | 측정 전 | 시험셋, 2026-11-18 AG-11 기준선. 평균 점수라 k/n 아님 |
| 답변 충실도 | C2 Faithfulness 0.783(Ragas 평균 점수) | 측정 전 | 시험셋, 같은 측정 |
| 오탈자 견고성 | C2 정상 16/20 [0.58, 0.92] → 오탈자 9/20 [0.26, 0.66], C1(보정 끔) 오탈자 0/20 [0.00, 0.16] | 측정 전 | 시험셋 오탈자 쌍 20, 2026-11-18 AG-11 2차 측정. C1과의 차이는 보정 꺼짐이라는 조건 정의에서 생김 |
| 안전 응답률 | C2 55/75, Wilson 95% [0.62, 0.82](`final_excl_j5` 본 지표) | 측정 전 | 시험셋. C1 57/75(같은 기준). 9.3절 목표(고정 문구·119 100%, 나머지 90% 이상)와는 별도 판정 |
| 금기 판정 정답률 | C2 25/35 | 측정 전 | 시험셋. C1 24/35. 구간은 옮기지 않음 |

- 라우팅 정확도 122/151(C1 110/151), 신뢰성(안전 핵심 40문항 × 3회) `pass^3` 17/40 [0.29, 0.58], `pass@3` 27/40, 판정 일치 40/40.
- 소표본이므로 위 구간 외에 유의성은 주장하지 않는다(9.1절).

### (2) 평가 실행
평가 러너는 `evaluation/eval_runner.py`다. 개발셋 기준 사용 예(저장소 루트)는 아래와 같다. 시험셋은 개선 중에 열람하지 않는다(RFP-26-04). 재현 절차의 확정본은 BE-08 뒤에 채운다.

```bash
backend/.venv/bin/python evaluation/eval_runner.py --set dev --agent offline-fixed --limit 5
```

실제 모델·judge 실행은 비용이 들며 `--max-usd`·`--judge-max-usd` 상한을 반드시 준다(`evaluation/eval_runner.py` 머리 설명).

## 6. 데이터 출처와 이용 조건
- 한국의약품안전관리원(임부금기·병용금기·연령금기·용량주의·수유부주의), 건강보험심사평가원 DUR 품목리스트, 식약처 공공 API(e약은요·DUR·허가정보), 고시·법령 PDF.
- 데이터는 공공저작물 제2유형(출처표시, 상업적 이용금지)이며 저장소로 재배포하지 않는다. `data/`는 커밋하지 않으므로 새 환경에서는 각 출처에서 내려받아 둔다.
- 답변과 문서에는 출처와 기준일(파일별)을 표시한다.

## 7. 문서
- [`P2-doc/PJ2-RFP.md`](P2-doc/PJ2-RFP.md): 제안요청서(요구사항·평가 기준 원본)
- [`P2-doc/PJ2-PRD.md`](P2-doc/PJ2-PRD.md): 제품 요구사항 문서
- [`P2-doc/PJ2-아키텍처.md`](P2-doc/PJ2-아키텍처.md): 구조도·데이터 흐름·평가 하네스
- [`P2-doc/PJ2-Agent-Harness.md`](P2-doc/PJ2-Agent-Harness.md): 하네스 규칙
- [`P2-doc/PJ2-프롬프트-설계.md`](P2-doc/PJ2-프롬프트-설계.md): 프롬프트 설계
- [`P2-doc/PJ2-DUR-RAG-근거설계.md`](P2-doc/PJ2-DUR-RAG-근거설계.md): 근거 코퍼스 설계
- [`schedule.md`](schedule.md), [`tickets/`](tickets/): 일정과 티켓

## 8. 면책과 한계
- **진단·처방·복용량 결정을 하는 서비스가 아니다.** 공공데이터 기반 정보 제공이며 응답은 의료적 판단을 대신하지 않는다. 자세한 확인은 근처 약국·약사에게 한다.
- 금기가 조회되지 않아도 안전하다고 말하지 않는다. 응급 키워드가 있으면 119 안내를 맨 위에 둔다.
- 파일 데이터는 갱신되지 않는 스냅샷이며 기준일 이후의 변경을 추정하지 않는다.
- 위 평가는 소표본이고 목표 수치는 잠정이다(RFP-22-11). 개선 후 값은 측정 전이다.
- 법률 검토를 거치지 않았다. 실제 공개·상용 전에는 검토가 필요하다.
