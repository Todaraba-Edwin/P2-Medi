# Can I PPiyak (MediAgent)

> **초안(PRD-04, 2026-11-19 W2 성과 반영).** 배포 주소·시연 전 점검 절차·평가 재현 명령의 확정판은 BE-13(배포 리허설)·BE-08 뒤에 채운다. 이 문서의 평가 수치는 `P2-doc/PJ2-RFP.md` 9.6절의 표를 그대로 옮겼고, 환경변수는 이름만 적었다(값은 저장소에 없다).

## Index
- [1. 프로젝트 성격](#1-프로젝트-성격)
- [2. 구조](#2-구조)
- [3. 스택과 이유](#3-스택과-이유)
- [4. 실행 방법](#4-실행-방법)
  - [(1) 준비](#1-준비)
  - [(2) 백엔드(실서버)](#2-백엔드실서버)
  - [(3) 가짜 자원 서버](#3-가짜-자원-서버)
  - [(4) 프런트](#4-프런트)
  - [(5) 환경변수 이름](#5-환경변수-이름)
- [5. 평가 요약](#5-평가-요약)
  - [(1) AG-11 기준선 확정 값](#1-ag-11-기준선-확정-값)
  - [(2) 평가 실행](#2-평가-실행)
- [6. 개선 사례](#6-개선-사례)
- [7. 데이터 출처와 이용 조건](#7-데이터-출처와-이용-조건)
- [8. 문서](#8-문서)
- [9. 면책과 한계](#9-면책과-한계)

## 1. 프로젝트 성격
금기 판정과 사실은 공공 API·파일 데이터·문서에서 코드가 가져오고, LLM 에이전트는 도구 선택과 근거 탐색, 쉬운 설명·종합만 맡는 근거 기반 질의응답 에이전트다. 임산부·영유아·아동·고령자가 있는 집에서 상비약·보유 의약품을 먹기 전에 병용·연령·임부 금기를 스스로 확인하게 해 오남용을 막는 것이 도메인이다. 서비스 표시 이름은 **Can I PPiyak(삐약)**이고 저장소·코드 이름은 MediAgent다.

- **취업 포트폴리오다.** 핵심 목표는 Agent-RAG를 활용한 AX(AI 전환) 경험, 곧 에이전트(Router, 도구 선택, 근거 고정, Validator)를 직접 설계·구현·평가하고 수치로 개선을 보이는 것이다.
- 원스글로벌 Dr.DI 같은 기존 서비스는 아이디어에 가능성이 있음을 확인한 사례일 뿐이며, 재현하거나 성능을 비교하지 않았다. 같은 문제를 Agent-RAG의 대상 도메인으로 삼아 **3주·1인 개발 규모로 범위를 제어한 축소판**이다.
- 로그인은 소셜 로그인 Google·Kakao만 쓰고 이메일 로그인·가입은 화면에서 숨겼다(메일 인증을 갖춘 뒤 재검토, PRD-01-10 A, 2026-11-19). 로그인 없이(게스트) 핵심 기능을 쓸 수 있다.
- 진단·처방·복용량 결정을 하는 서비스가 아니다(9장).

## 2. 구조
ReAct 에이전트가 중심이며 LangGraph 6노드 `guardrail_in → router → model ⇄ tools → validator → finalize`로 구성한다. 판정·고정 문구·119 안내는 프롬프트가 아니라 코드가 강제한다. 대조군 C1(고정 파이프라인)은 같은 노드를 재사용한다. 그림과 데이터 흐름, 환각 방지 장치, 평가 하네스 개요는 [`P2-doc/PJ2-아키텍처.md`](P2-doc/PJ2-아키텍처.md)에 있다.

근거 검색은 **BM25 단독**이다(BE-06-26 A, 서비스 유지 BE-17-07 A, 2026-11-19). pgvector HNSW 색인은 DB에 만들어 두었지만 런타임에서 쓰지 않으며, 하이브리드(BM25 + HNSW)는 평가 수치와 함께 올리는 AG-13 개선 후보다(평가 러너도 BM25 단독이라 서비스와 평가 조건이 같다). 서버가 실행 중에 읽는 데이터(판정 테이블·근거 코퍼스·약품명 사전)는 Supabase에서 읽는다. 코퍼스의 생성·적재·런타임 준비 단계와 시간은 [`P2-doc/PJ2-코퍼스-적재와-준비.md`](P2-doc/PJ2-코퍼스-적재와-준비.md)에 있다.

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
| 약봉투 사진 판독 | 기본 제공자 OpenAI(`gpt-6-luna` 비전, 환경변수 `MEDIAGENT_VISION_PROVIDER` 기본 `openai`) | BE-14-12 A(2026-11-23 사용자 최종 결정). Upstage는 코드 전환만 유지하며 켜기 전에 처리방침·사진 고지·요금제 조건을 맞춰야 한다. 사진은 서버에 저장하지 않는다 |
| 평가 judge | Claude Sonnet 5.5(`claude-sonnet-5-5`) 고정 | 평가 기간 중 모델·루브릭 변경 금지(RFP-26-01) |
| DB·벡터 | Supabase Pro(Postgres + pgvector, Auth) | 배포 요건(RFP-15-03). 근거 코퍼스 용량 추정 약 970MB가 무료 한도(500MB)를 넘어 Pro로 변경(BE-05-03 D, 2026-11-11) |
| 로그인 | Supabase Auth, 소셜 Google·Kakao | PRD-01-10 A. 이메일 로그인은 숨김 |
| 배포 | 로컬 Mac 상시 + 터널(백엔드), 클라우드는 추후 | BE-13-05 A(2026-11-19). 프런트는 Vercel 계획(RFP-15 §7), 최소 구성 배포는 BE-13 |
| 파서·임베딩 | RFP-15 시험 결과 | 확정 값은 `tickets/doc/RFP-15.md`와 아키텍처 문서 4장 |

## 4. 실행 방법
### (1) 준비
- Python 3.11 이상(`backend/pyproject.toml`), Node.js와 pnpm.
- 저장소 루트의 `.env`에 환경변수를 둔다(이름은 (5)). `.env`는 커밋하지 않는다.
- 백엔드 가상환경은 `backend/.venv`를 쓴다(문서·스크립트가 이 경로를 쓴다). 의존성은 `backend/pyproject.toml`에 있다(`dev`: 시험·린트, `eval`: 평가 judge용 `anthropic`).

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -e "backend[dev]"
```

### (2) 백엔드(실서버)
`backend/app/main.py`의 FastAPI 앱 `app`을 uvicorn으로 띄운다. 가정: 진입점 모듈 경로는 `app.main:app`이며 `backend/`를 작업 디렉터리로 쓴다.

```bash
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --port 8000 --no-access-log
```

- `--no-access-log`: 접속 IP·요청 경로를 서버 로그에 남기지 않는다(개인정보 처리방침 v2 §4, PRD-17 ⑫ ⑧ B). 빼지 않는다.

- 상태 확인: `GET /health`
- 질문 1건: `POST /chat`(게스트 허용). 요청·응답 스키마는 서버가 띄우는 `/docs`(OpenAPI)에서 확인한다. 필요한 환경변수(5)가 갖춰지지 않으면 `/chat`은 501을 돌려준다(의도된 상태, `backend/app/main.py` 머리 설명).
- 로그인 사용자 확인: `GET /me`(BE-11 S1, 로그인 필수). 토큰 검증기가 없으면 토큰이 온 요청은 501.
- 서버 시작 준비: 서버가 뜨면 백그라운드 스레드가 코퍼스·약품명 사전·검색 색인을 미리 만든다(BE-17-01 A). 시작 로그의 `warmup starting` … `warmup done in N.Ns`(실패면 `warmup failed`)로 끝난 시점을 확인한다. 환경변수 `MEDIAGENT_WARMUP`(선택, 기본 켬)을 `0`·`false`·`off`로 두면 끄고 첫 요청에서 만든다(`backend/app/api/service.py`).
- 배포(로컬 Mac 상시 + 터널)는 안내서 `P2-doc/PJ2-배포-로컬-터널.md`를 따른다(2026-11-19 작성 중, 아직 저장소에 없을 수 있다).
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
- rewrites(`frontend/next.config.ts`): `MEDIAGENT_BACKEND_ORIGIN`이 있으면 `/api/:path*` 요청을 `{MEDIAGENT_BACKEND_ORIGIN}/:path*`로 넘긴다. 없으면 rewrites는 비어 있다(개발은 MSW 목).
- 가짜 서버(3) 또는 실서버(2)와 함께 쓰려면 `MEDIAGENT_BACKEND_ORIGIN`을 `http://127.0.0.1:8000`처럼 그 서버 주소로 두고 프런트를 띄운다.
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
| Supabase(로그인·JWT 검증, 백엔드) | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`(서버 전용), `SUPABASE_JWKS_URL` |
| 프런트 | `MEDIAGENT_BACKEND_ORIGIN`(서버 전용), `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_API_MOCKING` |
| 프런트 로그인(공개용, BE-11-18 A) | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` |
| 서버 시작 준비(선택, 비밀값 아님, BE-17-01 A) | `MEDIAGENT_WARMUP` |

- `NEXT_PUBLIC_*`에는 비밀 키를 넣지 않는다. 위 두 변수는 공개용 publishable 키로 RLS를 전제하는 예외이며, `SUPABASE_SECRET_KEY`는 `NEXT_PUBLIC_*`에 두지 않는다.

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
- 기준선 판 변경 예정: AG-22(주의 조회를 코드 규칙으로 바꿈, 개발셋 `entries` 55/150 변경)가 병합되면 그 뒤 코드를 새 기준선 판 `c2@caution-rule-v1`로 9장에 기록하고 AG-11 기준선과 분리하는 안이 대기 중이다(AG-13-30, 결정 전). 위 수치는 바꾸지 않았으며 새 판의 재측정 값은 측정 뒤에 반영한다.

### (2) 평가 실행
평가 러너는 `evaluation/eval_runner.py`다. 개발셋 기준 사용 예(저장소 루트)는 아래와 같다. 시험셋은 개선 중에 열람하지 않는다(RFP-26-04). 재현 절차의 확정본은 BE-08 뒤에 채운다(자리만 둔다).

```bash
backend/.venv/bin/python evaluation/eval_runner.py --set dev --agent offline-fixed --limit 5
```

실제 모델·judge 실행은 비용이 들며 `--max-usd`·`--judge-max-usd` 상한을 반드시 준다(`evaluation/eval_runner.py` 머리 설명).

## 6. 개선 사례
문제를 측정하고, 원인을 찾고, 결정하고, 구현한 사례다. 규칙마다 Guide(프롬프트)와 Sensor(코드 검사)를 짝짓고 고정 문구·판정은 프롬프트가 아니라 코드로 강제하는 하네스 원칙(`P2-doc/PJ2-Agent-Harness.md`)을 그대로 따른다. 수치는 해당 티켓·문서의 기록이며 대부분 1회 관찰이나 개발셋 기준이라 일반화하지 않는다.

### (1) 첫 응답 27.84초 → 57ms
- **문제**: 서버를 띄운 뒤 첫 질문의 응답이 27.84초 걸리고 "약 찾는 중" 표시가 멈춰 보였다(2026-11-19 사용자 관찰, 측정 위치는 확인하지 못함).
- **원인(측정)**: 첫 요청에서 자원을 만드는 시간이었다. 코퍼스 SELECT 16.07초, 약품명 사전 SELECT 7.94초, BM25 색인 구성 2.56초. 되묻기 경로 자체의 계산은 0.02초이고 LLM 호출이 없다.
- **결정**: 서버 시작 뒤 백그라운드 warm-up(BE-17-01 A). 스플래시 준비 신호는 두지 않았고(BE-17-06 A), BM25 색인을 빌드 때 이미지에 넣는 안도 쓰지 않았다(BE-17-09 A, 시간 대부분이 색인이 아니라 DB 전송이라서).
- **구현**: 서버 시작 시 백그라운드 스레드가 자원을 한 번 만든다(`MEDIAGENT_WARMUP`으로 끔).
- **결과**: 사용자 1회 확인에서 첫 되묻기가 57ms로 응답했다(L4 `latency_ms` 측정이 아니라 사용자 관찰이며 1회라 일반화하지 않는다).
- **하네스와의 관계**: 서비스 전용 변경이라 평가 조건(9장)에 영향이 없다.
- 출처: [`P2-doc/PJ2-코퍼스-적재와-준비.md`](P2-doc/PJ2-코퍼스-적재와-준비.md) §2.2·§4, `tickets/backend/BE-17.md`.

### (2) 여러 약 되묻기를 한 번에
- **문제**: 약 이름이 둘 이상 모호하면 되묻기가 한 이름씩만 와서 같은 질문에 요청을 3번 보내야 했다(FE-09, 화면 이슈 ISSUE-020).
- **원인**: 버그가 아니라 설계였다. Router가 첫 후보만 담고 나머지를 다음 차례로 넘겼다(조사 결과 `tickets/frontend/FE-09.md`).
- **결정·구현**: 약 이름별(`input_name`) 묶음을 모두 담아 한 번에 되묻는다(커밋 `3fb5baf`, 병합 `01269d0`). 묶음 간 후보가 겹치면 고른 약이 금기 조회에서 빠지는 **안전 문제**가 재현되어, 요청에 `confirmed_drugs[].input_name`을 두고 서버가 이름별로 매칭하게 했다(FE-09-05 A).
- **결과**: 요청 3번 → 1번(설계상 기대. 사용자 화면 확인은 병합 뒤 예정).
- **하네스와의 관계**: 순서에 기대지 않고 계약(`input_name` 매칭)으로 막는 Sensor 성격의 수정이다.

### (3) 이전 차례 선택 약을 조용히 확정하던 위험 → 확인 되묻기
- **문제**: 이전 차례에 고른 약을 이번 질문에서 말없이 확정해 쓰면 사용자가 다른 약을 뜻했을 때 잘못된 약으로 금기를 조회한다(AG-21).
- **결정·구현**: 이전 차례 선택 약을 쓰기 전에 확인 되묻기를 하고, 시각 표현 잡음 규칙을 정리했다(커밋 `db2205d`, 병합 `9f879a0`, GROUP-01 1단계).
- **결과**: 개발셋 Router 출력 변화 0/150, `P2-doc/PJ2-RFP.md` 9장 변경 없음(`tickets/agent/AG-21.md`).
- **하네스와의 관계**: 모르면 안전한 쪽(확인)으로 가고, 약 확정은 LLM이 아니라 코드 규칙이 한다.

### (4) 용량주의 표현과 주의 조회 — 구현·병합 완료
- **문제**: 재복용·추가 복용 질문(예: 점심에 먹은 뒤 오후에 또 먹어도 되는지)이 입구 용량 패턴에 걸리지 않아 에이전트 경로로 가고, 용량주의가 "판정"처럼 보일 수 있었다. 주의 3종 조회를 LLM의 `include_cautions` 선택에 맡겨 실행마다 조회 행 수가 달라질 수 있었다(AG-22).
- **결정·구현**: 용량주의를 성분 속성 고지 + 예/아니요 되묻기로 보이게 하고, 주의 조회를 LLM 선택에서 코드 규칙으로 옮겼다. 복용 여부·용량을 정해 주지 않는 원칙은 출구 Sensor가 지킨다.
- **상태**: GROUP-01 2·3단계는 **구현 완료·develop 병합 완료**다. 개발셋에서 주의 규칙 변경으로 `entries`가 바뀌는 문항은 55/150이고 9장 지표는 불변으로 추정한다(측정 전, `tickets/agent/AG-22.md` §5). 병합 뒤 새 기준선 판을 둘지는 AG-13-30에서 정한다(5장).
- **하네스와의 관계**: 고정 문구와 판정은 프롬프트가 아니라 코드가 강제한다는 원칙의 적용이다.

## 7. 데이터 출처와 이용 조건
- 한국의약품안전관리원(임부금기·병용금기·연령금기·용량주의·수유부주의), 건강보험심사평가원 DUR 품목리스트, 식약처 공공 API(e약은요·DUR·허가정보), 고시·법령 PDF.
- 데이터는 공공저작물 제2유형(출처표시, 상업적 이용금지)이며 저장소로 재배포하지 않는다. `data/`는 커밋하지 않으므로 새 환경에서는 각 출처에서 내려받아 둔다.
- 답변과 문서에는 출처와 기준일(파일별)을 표시한다.

## 8. 문서
- [`P2-doc/PJ2-RFP.md`](P2-doc/PJ2-RFP.md): 제안요청서(요구사항·평가 기준 원본)
- [`P2-doc/PJ2-PRD.md`](P2-doc/PJ2-PRD.md): 제품 요구사항 문서
- [`P2-doc/PJ2-아키텍처.md`](P2-doc/PJ2-아키텍처.md): 구조도·데이터 흐름·평가 하네스
- [`P2-doc/PJ2-Agent-Harness.md`](P2-doc/PJ2-Agent-Harness.md): 하네스 규칙
- [`P2-doc/PJ2-프롬프트-설계.md`](P2-doc/PJ2-프롬프트-설계.md): 프롬프트 설계
- [`P2-doc/PJ2-DUR-RAG-근거설계.md`](P2-doc/PJ2-DUR-RAG-근거설계.md): 근거 코퍼스 설계
- [`P2-doc/PJ2-코퍼스-적재와-준비.md`](P2-doc/PJ2-코퍼스-적재와-준비.md): 코퍼스 생성·적재·런타임 준비, 첫 요청 지연 사례, BM25·HNSW 결정
- [`P2-doc/PJ2-배포-로컬-터널.md`](P2-doc/PJ2-배포-로컬-터널.md): 로컬 Mac 상시 + 터널 배포 안내서(작성 중)
- [`P2-doc/PJ2-API-엔티티.md`](P2-doc/PJ2-API-엔티티.md): API·엔티티
- [`P2-doc/PJ2-Agent-로깅-전략.md`](P2-doc/PJ2-Agent-로깅-전략.md): 로깅 전략
- [`P2-doc/PJ2-프론트-기술스택.md`](P2-doc/PJ2-프론트-기술스택.md): 프런트 기술 스택
- [`P2-doc/MFDS_병용금기_지정규정_고시.md`](P2-doc/MFDS_병용금기_지정규정_고시.md): 병용금기 지정 규정 고시 정리본
- [`schedule.md`](schedule.md), [`tickets/`](tickets/): 일정과 티켓

## 9. 면책과 한계
- **진단·처방·복용량 결정을 하는 서비스가 아니다.** 공공데이터 기반 정보 제공이며 응답은 의료적 판단을 대신하지 않는다. 자세한 확인은 근처 약국·약사에게 한다.
- 금기가 조회되지 않아도 안전하다고 말하지 않는다. 응급 키워드가 있으면 119 안내를 맨 위에 둔다.
- 파일 데이터는 갱신되지 않는 스냅샷이며 기준일 이후의 변경을 추정하지 않는다.
- 위 평가는 소표본이고 목표 수치는 잠정이다(RFP-22-11). 개선 후 값은 측정 전이다.
- 법률 검토를 거치지 않았다. 실제 공개·상용 전에는 검토가 필요하다.
