# 프론트 기술 스택 (Can I PPiyak)

> 원본: 2026-11-12 사용자 지시(프론트를 Next.js(+TypeScript)로 바꾸고 상태관리 Zustand, 통신 ky, 스타일 Tailwind CSS, 배포 Vercel 유지)와 저장소 문서(`P2-doc/PJ2-PRD.md`, `P2-doc/PJ2-Agent-Harness.md`, `backend/app/api/schemas.py`, `tickets/frontend/FE-01.md`). 정리일 2026-11-12. 정리 방식: documents-writer가 지시서(`data/mock/briefs/2026-11-12-fe-stack-docs.md`, 로컬 전용)로 초안을 쓰고, 같은 날 사용자 답 "FE-01 ①~⑧ 권장대로"(FE-01-05~12)를 지시서 `data/mock/briefs/2026-11-12-fe-stack-docs2.md`(로컬 전용)에 따라 확정 반영했다. 3장 (9)(FE-01-13)만 대기다. 4장(스트리밍 이벤트 소비)을 새로 더했고 그 안의 이벤트 형식은 BE-06과 정할 **초안**이다. 같은 날 지시서 `data/mock/briefs/2026-11-12-artifact2.md`(로컬 전용)에 따라 두 번째 아티팩트(인터랙티브 프로토타입)에서 메인 세션이 읽은 CSS 변수·구성 요소로 10장(디자인 토큰 원본)·11장(참조 구현)을 더했다. 이 에이전트는 아티팩트를 직접 열지 않았다. 값(주소·키)은 쓰지 않고 환경변수 이름만 적었다.

## Index
- [1. 개요와 상태](#1-개요와-상태)
- [2. 확정한 스택](#2-확정한-스택)
- [3. 세부 결정](#3-세부-결정)
  - [(1) 렌더링과 라우팅](#1-렌더링과-라우팅)
  - [(2) 백엔드 연결 방식](#2-백엔드-연결-방식)
  - [(3) 응답 전송 방식](#3-응답-전송-방식)
  - [(4) 브라우저 저장 정책](#4-브라우저-저장-정책)
  - [(5) 컴포넌트 기반](#5-컴포넌트-기반)
  - [(6) 디자인 토큰](#6-디자인-토큰)
  - [(7) API 타입과 검증](#7-api-타입과-검증)
  - [(8) 개발 도구](#8-개발-도구)
  - [(9) 모델과 병렬 실행](#9-모델과-병렬-실행)
- [4. 스트리밍 이벤트 소비](#4-스트리밍-이벤트-소비)
  - [(1) 요청과 줄 단위 파싱](#1-요청과-줄-단위-파싱)
  - [(2) 이벤트별 화면 처리](#2-이벤트별-화면-처리)
  - [(3) 연결 끊김과 재시도 규칙 제안](#3-연결-끊김과-재시도-규칙-제안)
  - [(4) BE-06과 정할 이벤트 형식 초안](#4-be-06과-정할-이벤트-형식-초안)
- [5. 폴더 구조 제안](#5-폴더-구조-제안)
- [6. 환경변수 이름 규칙](#6-환경변수-이름-규칙)
- [7. 화면·정책 규칙 요약](#7-화면정책-규칙-요약)
- [8. 백엔드 계약](#8-백엔드-계약)
- [9. 병렬 작업 분할](#9-병렬-작업-분할)
  - [(1) 작업자별 파일 소유](#1-작업자별-파일-소유)
  - [(2) 착수 게이트](#2-착수-게이트)
- [10. 디자인 토큰 원본](#10-디자인-토큰-원본)
  - [(1) 색 토큰](#1-색-토큰)
  - [(2) 글꼴](#2-글꼴)
  - [(3) 이식 방법(제안)](#3-이식-방법제안)
- [11. 참조 구현](#11-참조-구현)
- [12. 가정과 확인 필요](#12-가정과-확인-필요)
- [13. 관련 문서](#13-관련-문서)

## 1. 개요와 상태

- 프론트는 `frontend/`(CLAUDE.md 7장, 아직 없음)에 Next.js + TypeScript로 만들고 Vercel에 배포한다. 에이전트·판정·고정 문구·서버 API는 FastAPI 백엔드(`backend/`)가 맡고, 프론트는 **백엔드가 내려준 값을 그대로 보여 주는 화면**이다.
- 이 결정은 2026-11-12 사용자 결정(FE-01-01~04)이며 RFP-15-07(2026-11-02, Vite + React(+TypeScript) SPA를 Vercel에 정적 배포)을 대체한다. 반영 위치: `P2-doc/PJ2-RFP.md` 8장 "프론트엔드·배포" 행, `P2-doc/PJ2-PRD.md` 8장 "배포" 행.
- 상태: **확정본(1건 대기)**. 2장과 3장 (1)~(8)(FE-01-05~12)은 2026-11-12 사용자 답 "권장대로"로 확정했다. 3장 (9)(FE-01-13, 모델·병렬 실행)만 대기다. 결정 번호의 원본은 `tickets/frontend/FE-01.md` §6 결정 현황 표다.

## 2. 확정한 스택

| 영역 | 선택 | 결정 번호 | 비고 |
|---|---|---|---|
| 프레임워크 | Next.js | FE-01-01(2026-11-12 사용자 지시), RFP-15-07 대체 | App Router, 3장 (1) |
| 언어 | TypeScript(strict) | FE-01-01, FE-01-12 | API 타입은 3장 (7) |
| 상태관리 | Zustand | FE-01-02 | `persist` 금지, 3장 (4) |
| 통신 | ky | FE-01-03 | NDJSON 스트리밍, 3장 (3)·4장 |
| 스타일 | Tailwind CSS(v4) | FE-01-04, FE-01-10 | CSS 변수 토큰, 다크모드 없음, 3장 (6) |
| 백엔드 연결 | `next.config` rewrites 프록시 | FE-01-06 | 3장 (2) |
| 컴포넌트 기반 | shadcn/ui + Radix 일부 | FE-01-09 | 3장 (5) |
| API 타입·검증 | openapi-typescript + zod | FE-01-11 | 3장 (7) |
| 개발 도구 | pnpm, Node LTS, ESLint + `jsx-a11y`, Vitest + Testing Library, Playwright, MSW | FE-01-12 | 3장 (8) |
| 배포 | Vercel | RFP-15-06(유지) | 백엔드는 AWS 무료 인스턴스 1대, DB는 Supabase(RFP-15-03) |

## 3. 세부 결정

(1)~(8)은 2026-11-12 사용자 답 "FE-01 ①~⑧ 권장대로"로 ★(A)를 확정했다. (9)만 대기이며 선택지는 FE-01 §6 결정 현황 표와 같다.

| 항목 | 결정 번호 | 상태 | 확정 내용(요약) |
|---|---|---|---|
| (1) 렌더링과 라우팅 | FE-01-05 | 완료(A) | App Router, 채팅은 클라이언트 컴포넌트 중심 |
| (2) 백엔드 연결 방식 | FE-01-06 | 완료(A) | `next.config` rewrites로 `/api/*`를 백엔드(AWS)로 프록시 |
| (3) 응답 전송 방식 | FE-01-07 | 완료(B) | NDJSON 스트리밍으로 진행 단계 이벤트, ky `response.body` 리더로 소비 |
| (4) 브라우저 저장 정책 | FE-01-08 | 완료(A) | Zustand `persist` 금지, 대화는 메모리에만 |
| (5) 컴포넌트 기반 | FE-01-09 | 완료(A) | shadcn/ui + Radix를 Dialog·Sheet·Accordion·Tooltip에만 |
| (6) 디자인 토큰 | FE-01-10 | 완료(A) | Tailwind v4 CSS 변수, 다크모드 없음 |
| (7) API 타입과 검증 | FE-01-11 | 완료(A) | openapi-typescript 생성 + zod 런타임 검증 |
| (8) 개발 도구 | FE-01-12 | 완료(A) | pnpm·Node LTS·TS strict·ESLint `jsx-a11y`·Vitest·Testing Library·Playwright·MSW |
| (9) 모델과 병렬 실행 | FE-01-13 | **대기** | 아래 (9) |

### (1) 렌더링과 라우팅

결정: **FE-01-05 A 확정(2026-11-12)**. App Router를 쓰고 채팅은 클라이언트 컴포넌트 중심으로, 정적 안내·약관만 서버 컴포넌트로 둔다.

- 페이지 껍데기(레이아웃·정적 브랜딩)는 서버 컴포넌트 기본을 두고, 채팅·결과·근거 상세는 `'use client'` 컴포넌트에서 FastAPI를 부른다.
- Server Actions·Route Handler로 업무 로직을 만들지 않는다.
- 검토한 다른 선택지: B Pages Router.

이유: App Router가 현재 Next.js의 기본 경로이고, 화면이 대화 상태와 스트리밍 이벤트에 묶여 있어 클라이언트 중심이 맞다. 서버 쪽 로직을 프론트에 두지 않아 판정·고정 문구가 백엔드 한 곳에만 있게 된다.

### (2) 백엔드 연결 방식

결정: **FE-01-06 A 확정(2026-11-12)**. `next.config`의 rewrites로 `/api/*`를 백엔드(AWS)로 프록시한다. 커스텀 Route Handler는 두지 않는다.

- 브라우저는 같은 출처의 `/api/*`를 부르고 Vercel이 FastAPI로 넘긴다. 백엔드 주소는 서버 전용 환경변수에만 둔다(6장).
- 검토한 다른 선택지: B 브라우저가 백엔드에 직접 호출(CORS), C 정적 export(`output: 'export'`, rewrites를 쓸 수 없다).

이유: 같은 출처라 CORS 설정이 필요 없고 백엔드 주소가 브라우저 번들에 들어가지 않는다. HTTPS 페이지에서 HTTP 백엔드를 직접 부르면 브라우저가 막으므로(혼합 콘텐츠), 백엔드 인스턴스에 HTTPS를 붙이기 전에도 쓸 수 있다. 확인 필요: Vercel rewrites를 거칠 때 (3)의 스트리밍이 끊기거나 모였다가 한꺼번에 오지 않는지, 요청 시간 상한에 걸리지 않는지 착수 때 시험한다(BE-13 점검). 문제가 있으면 B로 바꾸는 결정을 새로 올린다.

### (3) 응답 전송 방식

결정: **FE-01-07 B 확정(2026-11-12)**. NDJSON 스트리밍(한 줄 = 한 이벤트)으로 진행 단계("약 찾기 → 금기 확인 중")를 이벤트로 받고, ky는 `response.body` 리더로 소비한다. 응답 형식은 BE-06과 묶어 정하고, 프론트는 이벤트 소스를 추상화한다.

- 프런트 쪽 소비 방식과 이벤트 형식 초안은 4장에 둔다.
- 검토한 다른 선택지: A 단일 JSON + 로딩 단계 문구(가짜 진행 없음). SSE(`text/event-stream`)는 `EventSource`가 GET만 되어 POST 질문에는 `fetch`로 직접 파싱해야 하므로 NDJSON을 쓴다.

이유: 응급이면 119 안내가 **스트리밍의 첫 이벤트**로 먼저 와야 하고(PRD-01-02, `P2-doc/PJ2-PRD.md` 15.1절, BE-06 완료 조건), 일반 질문은 진행 상태(약 찾는 중·금기 확인 중·근거 찾는 중)를 보여야 한다(NFR-06). 단일 JSON은 이 요구를 못 맞춘다. 로컬 mock(`data/mock/chat_responses/streams/*.jsonl`)이 이미 한 줄 한 이벤트(`progress`·`emergency`·`answer`·`error`·`done`)라 모양이 같다.

### (4) 브라우저 저장 정책

결정: **FE-01-08 A 확정(2026-11-12)**. Zustand `persist`를 쓰지 않고 질문·대화·응답은 메모리에만 둔다. `sessionStorage`·`localStorage`에 대화 내용을 쓰지 않고, UI 설정만 `localStorage`에 허용한다. 프로필은 로그인 시 서버에 둔다(확장, BE-11).

- IndexedDB·쿠키에도 질문·대화·답변을 쓰지 않는다. 새로고침하면 사라진다.
- 검토한 다른 선택지: B 세션 단위 저장 허용.

이유: CLAUDE.md 1장 "질문·대화 내용은 저장하지 않는다"와 PRD-07-01 A(같은 대화 안의 상태는 **브라우저 메모리에만** 두고 새로고침하면 사라진다, FE-01 완료 조건)에 맞는다. FE-01 완료 조건대로 대화 상태를 하나의 입력 묶음(스토어 하나)으로 분리해 저장 위치를 나중에 바꿔 끼울 수 있게 한다. 지키는 방법(제안): ESLint `no-restricted-imports`로 `zustand/middleware`의 `persist`를 막고 `localStorage` 직접 사용은 UI 설정 모듈 한 곳에서만 허용하며, 시험에서 대화 뒤 저장소에 대화 내용이 없는지 본다.

### (5) 컴포넌트 기반

결정: **FE-01-09 A 확정(2026-11-12)**. shadcn/ui + Radix primitives를 Dialog·Sheet·Accordion·Tooltip에만 쓰고, 디자인 고유 카드는 직접 만든다.

- shadcn/ui는 소스를 저장소에 복사하는 방식이다. 결과 카드·배지·날짜 줄·119 배너·고정 안내는 직접 만든다.
- 검토한 다른 선택지: B 전부 직접, C UI 라이브러리 전면 채택.

이유: 키보드·스크린리더 동작이 까다로운 상호작용 부품만 검증된 Radix를 빌리고, 안전 규칙이 걸린 영역(119·금기 결과·고정 문구)은 직접 만들어 규칙을 코드에서 바로 확인한다. 소스가 저장소에 있어 고치기 쉽고, 전면 채택은 Tailwind 토큰과 스타일 체계가 둘이 된다.

### (6) 디자인 토큰

결정: **FE-01-10 A 확정(2026-11-12)**. Tailwind v4 CSS 변수(`@theme`)로 디자인의 색·간격을 이식하고 **다크모드는 두지 않는다.**

- 토큰은 한 파일(`src/styles/`)에 둔다.
- 검토한 다른 선택지: B 다크모드 포함.

이유: 디자인 산출물에 다크모드가 없다. v4는 CSS 우선 설정이 기본이고 CSS 변수라 컴포넌트·시험에서 같은 값을 쓴다. 배지 색(병용금기 빨강, 임부금기 보라/자주 계열, PRD-09 G14·G15)과 글자 대비를 한 벌만 검증하면 된다. px·글꼴·색 값은 디자인 세션이 확정한다(PRD-14 §5.4, FE-07). 2026-11-12에 받은 인터랙티브 프로토타입의 CSS 변수를 이식 후보로 10장에 정리했다(FE-07 점검으로 바뀔 수 있음).

### (7) API 타입과 검증

결정: **FE-01-11 A 확정(2026-11-12)**. FastAPI OpenAPI에서 `openapi-typescript`로 타입을 만들고, 응답을 받는 경계에서 `zod`로 런타임 검증한다.

- 최종 응답과 스트림 이벤트 모두 zod로 검증한다(`schema_version` 확인 포함). 검증 실패는 오류 화면으로 보낸다(4장 (3)).
- 검토한 다른 선택지: B 수동 타입.

이유: 백엔드 스키마(`backend/app/api/schemas.py`)가 `extra="forbid"`·`schema_version`(`chat_response@v0`, BE-06 본 작업에서 v1로 고정)으로 엄격하므로 프론트도 모양이 다르면 조용히 넘기지 않고 멈춰야 한다. 엔드포인트가 아직 없어 첫 타입은 `schemas.py`를 보고 손으로 쓰고, BE-06 뒤 생성 타입으로 바꾼다(가정).

### (8) 개발 도구

결정: **FE-01-12 A 확정(2026-11-12)**. pnpm + Node LTS, TypeScript strict, ESLint + `jsx-a11y`, Vitest + Testing Library, Playwright 스모크, 백엔드 mock은 MSW + BE-06 응답 스키마 fixture.

- Node 버전은 착수 때 `.nvmrc`·`engines`로 고정한다. ESLint는 Next 설정에 `jsx-a11y`를 더한다.
- 검토한 다른 선택지: B 다른 구성.

이유: "360px·320px에서 가로 스크롤 없음"(NFR-07, PRD-14 §6, PRD-15 §7) 같은 완료 조건은 실제 브라우저에서만 잴 수 있어 Playwright가 필요하다. 백엔드 엔드포인트가 없으므로 MSW로 mock 응답·스트림을 돌려 LLM 호출 없이 개발한다(RFP-31, 8장). `jsx-a11y`는 접근성 인증이 목표는 아니지만(NFR-07) 기본 실수를 잡는다.

### (9) 모델과 병렬 실행

결정: **FE-01-13 대기**. 질문: 프런트 Auto 작업의 모델·병렬 분할은?

| 선택지 | 내용 |
|---|---|
| **A ★** | 컴포넌트·스토리 단위까지 먼저 병렬, 화면 조립은 FE-07 P2 결과 뒤 |
| B | 전부 FE-07 뒤 |
| C | 지금 화면 조립까지 |

이유(FE-01 §6): FE-07 점검 결과가 확정되기 전에 조립하면 재작업이 생긴다. 모델은 사용자가 "fable 5.2"를 제안했으나 저장소는 `claude-fable-5-1`만 알아 **모델 ID 확인 필요**(정보 요청이라 ★ 권장과 별개).

- 병렬로 돌릴 때의 파일 소유는 9장 (1), 조립 시점은 9장 (2)를 따른다. 공용 설정(스캐폴드 ①)은 다른 작업자보다 먼저 끝나야 같은 바탕에서 시작한다.
- 프론트 전용 정의 파일은 없으므로 일반 에이전트를 쓰고 새 `.claude/` 정의를 만들지 않는다(CLAUDE.md 2장 총량 규칙).

## 4. 스트리밍 이벤트 소비

FE-01-07 B에 따른 프런트 쪽 소비 방식이다. (1)·(2)는 FE-01-07·11의 확정 내용을 구체화한 것이고, (3)의 재시도 규칙과 (4)의 이벤트 형식은 **제안·초안**이다. 최종 이벤트 형식은 BE-06이 응답 스키마와 함께 정하며, 정해지면 이 장을 고친다.

### (1) 요청과 줄 단위 파싱

- 요청: 브라우저는 `POST /api/chat`(rewrites → FastAPI `/chat`, FE-01-06)을 부른다. 헤더 `Accept: application/x-ndjson`(제안). 본문은 질문과 같은 대화 안의 상태만 담고 저장하지 않는다(3장 (4)).
- ky 옵션: 스트리밍 요청은 `timeout: false`(또는 충분히 길게), `retry: 0`(POST 자동 재시도 끔), `signal`에 `AbortController`를 넘긴다. ky의 응답 본문 파싱(`.json()`)은 쓰지 않고 `response.body`(`ReadableStream`)를 직접 읽는다.
- 줄 단위 파싱(NDJSON):
  1. `response.body`를 `TextDecoderStream`(UTF-8)으로 문자열 스트림으로 바꾼다.
  2. 받은 조각을 버퍼에 붙이고 `\n`으로 나눈다. 마지막 조각은 줄이 끝나지 않았을 수 있으므로 버퍼에 남긴다.
  3. 빈 줄은 건너뛰고(끝의 `\r`은 지움), 나머지 줄은 `JSON.parse` 뒤 zod 판별 유니온(`type` 기준)으로 검증한다.
  4. 스트림이 끝나면 버퍼에 남은 내용이 있으면 마지막 한 줄로 처리한다.
  5. `JSON.parse`나 zod 검증이 실패한 줄은 조용히 건너뛰지 않고 오류 상태로 보낸다(3장 (7)).
- 추상화: 파서는 `AsyncIterable<ChatEvent>`를 돌려주는 함수 하나(`src/lib/api/`)로 두고, 화면·스토어는 이 인터페이스만 쓴다. MSW mock과 실제 백엔드가 같은 인터페이스를 거친다(FE-01-07 "이벤트 소스 추상화").

### (2) 이벤트별 화면 처리

| 이벤트 | 화면 처리 |
|---|---|
| `progress` | 진행 표시 문구를 바꾼다(약 찾는 중·금기 확인 중·근거 찾는 중). 문구는 `stage` 값에 대응하는 프론트 상수이며 가짜 진행을 만들지 않는다 |
| `emergency` | 받는 즉시 119 배너를 **맨 위**에 띄운다(전화 걸기 링크). 이후 이벤트가 와도 내리지 않는다. 진행 표시의 마스코트를 숨긴다(7장 마스코트 행) |
| `answer` | 최종 응답(`ChatResponse`)을 zod로 검증한 뒤 결과 카드·근거 상세·고정 안내를 그린다. 응답 안의 `emergency`는 이미 띄운 배너와 같은 자리 하나로만 보인다(중복 표시 없음, 제안) |
| `error` | 오류 상태를 보인다. 문구는 받은 코드 문구를 그대로 쓰고, 이미 띄운 119 배너는 유지한다 |
| `done` | 스트림 정상 종료. 입력창을 다시 연다 |

- 순서 규칙(BE-06 완료 조건): 응급이면 `emergency`가 첫 이벤트다. 프론트는 순서를 바꾸거나 기다리지 않고 받은 순서대로 반영한다.
- 응급 감지는 서버(`guardrail_in`) 한 곳이며 프론트는 질문 문장을 보고 감지하지 않는다(7장).

### (3) 연결 끊김과 재시도 규칙 제안

| 상황 | 처리(제안) |
|---|---|
| 응답 상태가 4xx | 재시도하지 않는다. 오류 상태를 보인다 |
| 응답 상태가 5xx·네트워크 오류(첫 이벤트 전) | 자동 재시도하지 않는다. 오류 상태와 "다시 시도" 버튼을 보인다(사용자가 눌러야 같은 질문을 다시 보낸다) |
| `answer` 전에 스트림이 끊김(`done` 없이 끝남 포함) | 끊김으로 본다. 받은 `emergency`는 유지하고, 진행 표시를 오류 상태로 바꾸며 "다시 시도" 버튼을 보인다. 부분 결과로 결과 카드를 만들지 않는다 |
| `answer` 뒤 `done` 없이 끊김 | 검증을 통과한 `answer`는 그대로 보인다(고정 문구가 응답 안에 있다). 끊김은 로그에만 남긴다 |
| 이벤트가 일정 시간 오지 않음 | 클라이언트 쪽 무응답 상한을 두고 넘으면 `AbortController`로 끊고 위 "끊김"과 같이 처리한다. 상한 값은 BE-06·BE-13(Vercel rewrites 시간 상한)과 정한다 |
| 새 질문을 보내거나 화면을 떠남 | 진행 중인 요청을 `abort()`한다. 한 번에 진행 중인 요청은 하나다 |

- POST 자동 재시도를 끄는 이유(가정): 같은 질문이 두 번 처리되면 LLM 비용이 두 번 들고 결과가 섞일 수 있다.
- "다시 시도"는 사용자의 명시적 행동으로만 한다. 재시도해도 이미 받은 119 안내를 지우지 않는다.

### (4) BE-06과 정할 이벤트 형식 초안

확정 아님. 로컬 mock `m1-v1`의 이벤트 이름(`progress`·`emergency`·`answer`·`error`·`done`)을 그대로 쓰고 필드 이름만 제안한다. BE-06이 응답 스키마(`schemas.py`)와 함께 확정한다.

- 전송 형식: `Content-Type: application/x-ndjson`, UTF-8, 한 줄에 JSON 객체 하나, 줄 끝 `\n`.
- 공통 필드(제안):

| 필드 | 타입 | 뜻 |
|---|---|---|
| `type` | `"progress"` \| `"emergency"` \| `"answer"` \| `"error"` \| `"done"` | 이벤트 종류(zod 판별 키) |
| `seq` | 정수(0부터 1씩 증가) | 이벤트 순번. 빠짐·순서 확인용 |
| `schema_version` | 문자열(예: `chat_event@v0`) | 이벤트 형식 버전. `ChatResponse`의 `chat_response@v0`와 별개 |

- 종류별 필드(제안):

| `type` | 필드 | 뜻 |
|---|---|---|
| `progress` | `stage`: `drug_lookup` \| `contraindication_check` \| `evidence_search` | 진행 단계(약 찾는 중·금기 확인 중·근거 찾는 중) |
| `emergency` | `emergency`: `{text, tel}` | 119 안내. `ChatResponse.emergency`와 같은 모양 |
| `answer` | `response`: `ChatResponse` | 최종 응답 전체(8장 필드) |
| `error` | `code`: 문자열, `message`: 문자열(코드 상수 문구) | 오류. 내부 정보·질문 내용은 싣지 않는다 |
| `done` | `end_reason`: `ChatResponse.end_reason`과 같은 값 또는 없음 | 정상 종료 |

- 예시(형식 초안, 값은 합성):

```
{"type":"emergency","seq":0,"schema_version":"chat_event@v0","emergency":{"text":"…","tel":"119"}}
{"type":"progress","seq":1,"schema_version":"chat_event@v0","stage":"drug_lookup"}
{"type":"progress","seq":2,"schema_version":"chat_event@v0","stage":"contraindication_check"}
{"type":"answer","seq":3,"schema_version":"chat_event@v0","response":{"schema_version":"chat_response@v0","route":"AGENT","…":"…"}}
{"type":"done","seq":4,"schema_version":"chat_event@v0","end_reason":"NORMAL"}
```

- BE-06과 확인할 것: 이벤트 이름과 필드 이름, `stage` 값 목록, `answer`가 `ChatResponse` 전체를 담는지, 오류 코드 목록, 서버가 연결 유지용 빈 줄(하트비트)을 보낼지, mock `m1-v1`의 `answer` 모양(골격과 다름)을 어떻게 맞출지.

## 5. 폴더 구조 제안

FE-01-05·06·08·11 확정 내용에 맞춘 구조다.

```
frontend/
├── package.json, pnpm-lock.yaml, .nvmrc, next.config.ts, tsconfig.json, eslint.config.mjs
├── playwright.config.ts, vitest.config.ts
├── public/                       favicon·앱 아이콘(캡슐 말풍선), 마스코트 이미지(FE-06)
└── src/
    ├── app/                      App Router: layout.tsx, page.tsx(채팅), 오류·빈 상태 페이지
    ├── components/               공용 부품: ui/(shadcn/ui 복사본), 버튼·칩·펼침 등
    ├── features/
    │   ├── chat/                 입력창, 대화 목록, 진행 표시, 되묻기 카드
    │   ├── result/               결과 카드, 배지, 성분 칩, 제품 줄
    │   ├── evidence/             근거 상세 패널, 출처 표, 날짜 줄, 원문 미확보 고지
    │   └── emergency/            119 배너(전화 걸기 링크), 고정 안내 박스
    ├── lib/
    │   └── api/                  ky 클라이언트, NDJSON 스트림 파서, zod 스키마, 생성 타입
    ├── stores/                   Zustand 스토어(메모리 전용, persist 없음)
    ├── styles/                   globals.css, Tailwind @theme 토큰
    └── mocks/                    MSW 핸들러·fixture(합성 데이터만)
```

- `mocks/`의 fixture는 합성·가상 데이터만 둔다. 로컬 전용 `data/mock/chat_responses/`를 그대로 복사해 커밋할지는 정하지 않았다(12장).
- 시험 파일은 각 기능 폴더 옆(`*.test.tsx`)에, Playwright 시험은 `frontend/e2e/`에 둔다(제안).

## 6. 환경변수 이름 규칙

이름만 적는다. 값은 문서·코드·커밋에 쓰지 않는다(CLAUDE.md 3장). 아래 변수 이름은 모두 **제안**이며, **CLAUDE.md 3장 변수 표에 더하는 것은 사용자가 알려 줄 때**다(CLAUDE.md 3장 "변수가 늘면 사용자가 알려 주는 대로 이름만 추가").

- `NEXT_PUBLIC_` 접두사가 붙은 변수는 **빌드 때 브라우저 번들에 들어가 누구나 볼 수 있다.** 비밀값을 넣지 않는다.
- 서버 전용 키(`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `UPSTAGE_API_KEY`, `SUPABASE_SECRET_KEY`, `SUPABASE_DB_URL`, 공공 API 키 전부)는 **프론트에 두지 않는다.** 프론트는 백엔드만 부른다.
- 로컬 값은 `frontend/.env.local`에 둔다. 저장소 `.gitignore`의 `.env`·`.env.*` 패턴이 하위 폴더에도 걸리는지는 `git-actor`가 `git check-ignore`로 확인한다(12장). 배포 값은 Vercel 프로젝트 설정에 둔다.

| 변수 이름(제안) | 공개 여부 | 용도 | 쓰는 경우 |
|---|---|---|---|
| `MEDIAGENT_BACKEND_ORIGIN` | 서버 전용(빌드·Vercel) | rewrites가 넘길 FastAPI 주소 | FE-01-06 A(확정)로 필요 |
| `NEXT_PUBLIC_API_BASE_URL` | 공개 | ky 클라이언트의 기준 주소. rewrites를 쓰므로 비우거나 `/api` | 경로 고정용(선택) |
| `NEXT_PUBLIC_API_MOCKING` | 공개 | `enabled`이면 MSW를 켠다(개발·시험 전용, 배포에서는 끔) | 개발 |
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | 공개(공개용 키) | 이메일 로그인(BE-11, 확장) | 확장 착수 때만 |

CLAUDE.md 3장 변수 표에 더할 항목(제안, 사용자가 알려 줄 때 반영):

| 대상 | 변수 이름 | 용도 |
|---|---|---|
| 프론트(Next.js, Vercel) | `MEDIAGENT_BACKEND_ORIGIN`(서버 전용), `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_API_MOCKING` | 백엔드 연결 주소, mock 켜기. `NEXT_PUBLIC_*`는 브라우저에 공개되므로 비밀값 금지 |

## 7. 화면·정책 규칙 요약

프론트가 지킬 규칙만 모았다. 원본 문서가 기준이며, 다르면 원본을 따른다.

| 규칙 | 프론트가 하는 일 | 원본 |
|---|---|---|
| 고정 문구는 코드 상수 | `fixed_notice[]`(줄 목록: 미확보가 있으면 약사 확인 권고 → 고정 문구), `disclaimer`, `emergency.text`, `findings[].text`, `notice`를 **받은 그대로** 표시한다. 프론트에서 문구를 새로 쓰거나 고치거나 줄이지 않는다 | `backend/app/api/schemas.py`(`Finding` "문구는 코드 상수", `ChatResponse.fixed_notice`), `PJ2-Agent-Harness.md` 4.1 (g), RFP-25-04 A |
| 날짜 줄 | `dates[{label, value}]`를 **한 날짜 = 한 줄**로 그린다. 라벨은 상수(`고시일`·`기준일`·`조회`, 없으면 `날짜 없음`)이고 화면은 문자열을 조립하지 않는다 | `schemas.py` 머리 설명·`DateLine`, PRD-12 §5 |
| 출처 순서 | `citations[]`의 순서를 바꾸지 않는다(순서는 코드가 정함) | `schemas.py` `build_citations`, PRD-12 §4.5 |
| 응급 119 | `emergency` 이벤트가 오면 **맨 위**에, 스크롤 없이 첫 화면에 띄우고 전화 걸기 링크를 둔다. 금기 결과는 그 아래에 이어서 보인다. 응급 감지는 서버(`guardrail_in`) 한 곳이며 프론트는 감지하지 않는다 | PRD-01-02, PRD-07-03 A, NFR-06·07, RFP-35-03, `PJ2-Agent-Harness.md` 4.1 (i), 4장 (2) |
| 마스코트 | 시작·로딩·빈 상태·오류·되묻기(작게) 같은 보조 자리에만 쓴다. 응급·금기 결과·"금기 목록에 없음"·고정 문구 영역에는 쓰지 않는다. 119·금기 결과가 나오면 진행 표시의 돋보기 병아리를 숨긴다 | PRD-06-02, FE-06-01, `PJ2-PRD.md` 1장 |
| 요약에 용량 숫자 없음 | `summary`를 가공 없이 표시한다. 용법용량 원문은 근거 상세에서만 보인다. 내용 검사는 백엔드 Validator 몫이다 | FR-04, RFP-21-03, `schemas.py` 머리 설명 |
| "목록에 없음" | `임부금기 목록에 없음` + "안전하다는 뜻은 아니에요"를 유지한다 | FE-01 완료 조건, PRD-09 §7.1 |
| 원문 미확보 | 원인별 코드 문구를 그대로 보이고, 약국·약사 확인 권고를 접히지 않는 강조 박스로 둔다 | PRD-11-03, `PJ2-PRD.md` 13장 표 |
| 배지 | `badges[]` 값을 그대로 쓰고, 제목 다음 `flex-wrap` 한 규칙으로 배지를 나열한다. 병용·임부가 모두 해당하면 배지 2개 | PRD-09-07, PRD-15-01·02 |
| 화면 폭 | 360px(및 320px)에서 가로 스크롤 없이 입력·요약·근거 펼침이 된다 | NFR-07, RFP-24-04 |
| 저장 금지 | 질문·대화 내용을 브라우저·서버 어디에도 저장하지 않는다 | CLAUDE.md 1장, PRD-07-01 A, FE-01-08 A(3장 (4)) |
| 표시 이름 | 화면에는 Can I PPiyak(한글 삐약 병기). 코드·환경변수는 MediAgent | PRD-06-01 |

## 8. 백엔드 계약

- 엔드포인트 `/chat`은 **아직 없다**(BE-06 본 작업). 현재 있는 것은 응답 스키마 골격 `backend/app/api/schemas.py`(`SCHEMA_VERSION = "chat_response@v0"`)뿐이다. 그래서 프론트는 **MSW mock을 기준으로** 개발하고, BE-06이 확정되면 타입·mock을 맞춘다.
- `ChatResponse` 필드(골격 기준). 스트리밍에서는 `answer` 이벤트의 `response`에 담긴다(4장 (4) 초안):

| 필드 | 타입 | 뜻 |
|---|---|---|
| `schema_version` | `"chat_response@v0"` | 스키마 버전 |
| `route` | `"AGENT"` \| `"REFUSE"` | 처리 경로 |
| `end_reason` | `NORMAL`·`CLARIFY`·`REFUSE`·`LIMIT`·`VALIDATION_FALLBACK` 또는 없음 | 끝난 이유(되묻기·거절·상한 등 화면 분기) |
| `emergency` | `{text, tel}` 또는 없음 | 119 안내 |
| `notice` | 문자열 또는 없음 | 안내 |
| `summary` | 문자열 또는 없음 | 쉬운 요약(검증 통과 LLM 문장 또는 코드 문구) |
| `findings[]` | `bucket`(`found`·`not_listed`·`identified`·`unconfirmed`), `drug`, `text`, `grades[]` 등 | 제품·항목별 판정 줄 |
| `badges[]` | `kind`, `grade`, `text`, `evidence_id`, `note` | 결과 카드 배지 |
| `detail[]` | `evidence_id`, `kind`, `status`, `source_kind`, `dataset`, `publisher`, `dates[]`, `rows[]`, `missing_reason` 등 | 근거 상세 박스(LLM 문장 없음) |
| `citations[]` | `publisher`, `dataset`, `dates[{label, value}]`, `source_kind`, `evidence_ids[]` | 출처 표 한 행(1출처 = 1행) |
| `sentence_refs[]` | `evidence_id`, `sentence_index`, `row_key`, `quotes[{start, end, text}]` | 요약 문장 ↔ 근거 연결 |
| `grade_def_missing[]` | 문자열 | 등급 정의 원문 미확보 목록 |
| `pharmacist_advice[]` | 문자열 | 약사 확인 권고 |
| `fixed_notice[]` | 문자열(1줄 이상, 빈 줄 불가) | 고정 문구 줄 목록 |
| `disclaimer` | 문자열(비어 있지 않음) | 고지 |

- 내부 필드(`events`·`warnings`·`text`)와 질문·메시지는 응답에 싣지 않는다(`schemas.py` 머리 설명, `response_from_state`).
- 스트림 이벤트(로컬 mock `m1-v1` 기준, 최종 형식은 BE-06): `progress`(`stage`: `drug_lookup` 약 찾는 중·`contraindication_check` 금기 확인 중·`evidence_search` 근거 찾는 중), `emergency`, `answer`, `error`, `done`. mock의 `answer` 모양은 위 골격과 다르므로 BE-06 확정 때 맞춘다(FE-01 §5 메모). 필드 이름 제안은 4장 (4).

## 9. 병렬 작업 분할

### (1) 작업자별 파일 소유

같은 파일을 두 작업자가 고치지 않게 소유를 나눈다. 공용 파일(`package.json`, 설정, `styles/`)은 ①만 고치고, 다른 작업자는 필요한 패키지·토큰을 보고에 적어 ①(또는 메인)에 요청한다.

| 작업자 | 맡는 일 | 소유 파일 | 선행 |
|---|---|---|---|
| ① 스캐폴드·설정·토큰 | Next.js·TypeScript·Tailwind v4·ESLint·Vitest·Playwright 설정, 토큰, App Router 껍데기, shadcn/ui 부품 복사 | `frontend/` 루트 설정 파일, `src/app/layout.tsx`, `src/styles/`, `src/components/ui/`, `public/` | FE-01-05~12(확정), FE-01-13 |
| ② 채팅·입력·스트리밍 | 입력창, 대화 목록, 진행 표시, 되묻기 카드, 대화 스토어 | `src/features/chat/`, `src/stores/` | ①, ⑤의 스트림 파서 인터페이스(4장 (1)) |
| ③ 결과 카드·배지·날짜 줄 | 결과 카드, 제품 줄, 배지(`flex-wrap`), 성분 칩, 날짜 줄 부품 | `src/features/result/`, `src/components/DateLines*`(제안) | ① |
| ④ 근거 상세·응급·고정 안내 | 근거 상세 패널, 출처 표, 원문 미확보 고지, 119 배너, 고정 안내 박스 | `src/features/evidence/`, `src/features/emergency/` | ①, ③의 날짜 줄 부품 |
| ⑤ API 클라이언트·MSW·타입·시험 | ky 클라이언트, NDJSON 파서, zod 스키마·타입, MSW 핸들러·fixture, Playwright 화면 폭 시험 | `src/lib/api/`, `src/mocks/`, `frontend/e2e/` | ① |

### (2) 착수 게이트

- **FE-07 점검 결과가 확정되기 전에는 컴포넌트·스토리·시험 단위까지만** 만든다. 부품마다 mock 데이터로 그려 보고 단위 시험을 통과시키는 데까지다.
- **화면 조립(`src/app/page.tsx`에서 부품을 합친 채팅 → 결과 → 근거 상세 흐름)은 FE-07의 수정 지시서가 사용자 승인을 받은 뒤**(FE-07-02 A) 한다. 아트보드가 바뀌면 조립 순서·배치가 바뀌기 때문이다.
- 실제 `/chat` 연결은 BE-06 엔드포인트가 생긴 뒤 한다. 그 전에는 MSW만 쓴다.
- 설정에 묶인 결정(FE-01-05~12)은 2026-11-12에 확정됐다. 작업 분할·모델(FE-01-13)이 대기인 동안에는 구현 위임을 시작하지 않는다.

## 10. 디자인 토큰 원본

출처: 2026-11-12 사용자가 준 두 번째 아티팩트 `https://claude.ai/artifact/STohGPXHmYePhz26i9yaKh`("Can I PPiyak 데스크톱", 단일 페이지 인터랙티브 프로토타입, 번들 HTML이라 소스 없음)의 CSS 변수. 메인 세션이 `Artifact` 도구로 읽은 값을 그대로 옮겼다. **이 값은 FE-01-10 A(Tailwind v4 CSS 변수, 다크모드 없음)로 이식할 후보이며 FE-07 점검 결과(특히 P4 대비 계산)로 바뀔 수 있다.** 대비·크기 검증은 FE-07 P4 몫이고 이 문서는 계산하지 않았다.

### (1) 색 토큰

"Tailwind v4 이름(제안)"은 `@theme`의 `--color-*` 이름 후보다. "용도"는 변수 이름과 3장·7장 규칙에서 읽은 것이며 프로토타입의 실제 쓰임은 FE-07에서 확인한다(가정).

| 프로토타입 변수 | 값 | Tailwind v4 이름(제안) | 용도(가정) |
|---|---|---|---|
| `--bg` | `#FFFFFF` | `--color-bg` | 기본 배경 |
| `--bg-soft` | `#FFF8E1` | `--color-bg-soft` | 옅은 노랑 배경 |
| `--bg-softer` | `#FFFDF5` | `--color-bg-softer` | 더 옅은 배경 |
| `--bubble-me` | `#FFD60A` | `--color-bubble-me` | 내 말풍선 |
| `--yellow` | `#FFCC00` | `--color-yellow` | 브랜드 노랑 |
| `--yellow-2` | `#FFE58F` | `--color-yellow-2` | 보조 노랑 |
| `--tint` | `#FFF4C2` | `--color-tint` | 강조 바탕 |
| `--fixed` | `#FFF8D6` | `--color-fixed` | 고정 안내 영역 바탕 |
| `--line` | `#F3E6B5` | `--color-line` | 구분선 |
| `--line-2` | `#E6D49A` | `--color-line-2` | 진한 구분선 |
| `--ink` | `#000` | `--color-ink` | 본문 글자 |
| `--ink-2` | `#3D3524` | `--color-ink-2` | 보조 글자 |
| `--mute` | `#6B5F3F` | `--color-mute` | 흐린 글자 |
| `--faint` | `#A08C5B` | `--color-faint` | 가장 흐린 글자 |
| `--link` | `#8A6500` | `--color-link` | 링크 |
| `--red` | `#D70015` | `--color-red` | 응급·병용금기 강조(응급 카드 `em-card` 고정 빨강) |
| `--red-ink` | `#B0000F` | `--color-red-ink` | 빨강 계열 글자 |
| `--warn-bg` | `#FFE8CC` | `--color-warn-bg` | 주의 배지 바탕 |
| `--warn-ink` | `#7A4100` | `--color-warn-ink` | 주의 배지 글자 |
| `--blue-bg` | `#E3F2FD` | `--color-blue-bg` | 정보 바탕 |
| `--blue-ink` | `#0D47A1` | `--color-blue-ink` | 정보 글자 |
| `--preg` | `#7B1FA2` | `--color-preg` | 임부금기(보라 계열, PRD-09 G15) |
| `--preg-bg` | `#F3E5F5` | `--color-preg-bg` | 임부금기 배지 바탕 |
| `--preg-ink` | `#6A1B9A` | `--color-preg-ink` | 임부금기 배지 글자 |
| `--combo-bg` | `#FFE5E7` | `--color-combo-bg` | 병용금기 배지 바탕(빨강 계열, PRD-09 G14) |

### (2) 글꼴

| 프로토타입 값 | Tailwind v4 이름(제안) |
|---|---|
| `-apple-system,"SF Pro Text","Apple SD Gothic Neo","Noto Sans KR",system-ui,sans-serif` | `--font-sans` |

- 웹 글꼴 파일을 따로 싣는지는 프로토타입에서 확인하지 않았다(번들 안 `@font-face` 유무는 FE-07 P0 추출에서 본다).

### (3) 이식 방법(제안)

- 위 변수를 `src/styles/globals.css`의 `@theme` 한 곳에 옮기고(5장 폴더 구조), 컴포넌트는 Tailwind 유틸리티(`bg-bg-soft`, `text-preg-ink` 등)로만 쓴다. 색 값을 컴포넌트에 직접 쓰지 않는다.
- 다크모드 변수는 만들지 않는다(FE-01-10 A).
- 크기 값(모바일 최대 430px, 데스크톱 사이드바 272px·접힘 레일 60px·근거 상세 패널 400px)은 프로토타입 레이아웃 값이며 `--spacing-*`·컨테이너 폭 토큰 후보다. 360px·320px 가로 스크롤 없음(NFR-07)은 별도로 Playwright로 시험한다(3장 (8)).
- 프로토타입에 번들된 외부 라이브러리 스타일(react-toastify)은 디자인 토큰이 아니므로 옮기지 않는다. 토스트를 쓸지는 11장 표에서 따로 본다.
- FE-07 점검으로 값이 바뀌면 이 표를 먼저 고치고 `@theme`을 따라 고친다.

## 11. 참조 구현

두 번째 아티팩트(10장 출처)는 FE-01 Next.js 구현의 **참조 구현** 후보다. 번들이라 TSX 원본은 없고, 아래 구성 요소는 메인 세션이 CSS 클래스·DOM 구조·텍스트로 읽은 목록이다. 상태 전환·상호작용은 FE-07 점검(상태·상호작용)에서 확인하며, 렌더링은 확인하지 못했다. 컴포넌트 이름·경로는 제안이다(5장 폴더 구조, 9장 (1) 작업자).

| 프로토타입 구성(클래스) | Next.js 컴포넌트 후보 | 경로(5장) | 작업자(9장 (1)) | 지킬 규칙 |
|---|---|---|---|---|
| 모바일 틀 `.proto.mobile`(최대 430px) | `MobileShell` | `src/app/`, `src/components/` | ① | 360px·320px 가로 스크롤 없음(NFR-07) |
| 데스크톱 틀 `.proto.desktop`(사이드바 272px·접힘 레일 60px·본문·근거 상세 패널 400px 3열) | `DesktopShell`, `Sidebar`, `SidebarRail`, `EvidencePanel` | `src/app/layout.tsx`, `src/components/`, `src/features/evidence/` | ①, ④ | 근거 상세는 펼쳐 보기(CLAUDE.md 1장) |
| 스플래시(마스코트 bob) | `Splash` | `src/features/chat/` | ② | 마스코트는 보조 자리만(PRD-06-02) |
| 홈 히어로·예시 칩 | `HomeHero`, `ExampleChips` | `src/features/chat/` | ② | 표시 이름 Can I PPiyak(PRD-06-01) |
| 입력창 | `ChatInput` | `src/features/chat/` | ② | 질문 저장 금지(FE-01-08 A) |
| 대화 스레드 | `ChatThread`, `MessageBubble` | `src/features/chat/` | ② | 상태는 메모리 스토어만(`src/stores/`) |
| 진행 단계(스피너·체크) | `ProgressSteps` | `src/features/chat/` | ② | `progress` 이벤트로만 진행(4장 (2)), 가짜 진행 없음 |
| 결과 카드, 상태 배지 ok·bad·warn·unk, 임부 `k-preg`, 성분 칩 | `ResultCard`, `StatusBadge`, `IngredientChip` | `src/features/result/` | ③ | `badges[]` 값 그대로, `flex-wrap`(PRD-09-07), "목록에 없음"은 안전 뜻 아님 |
| 근거 상세 `detail`·`pairs`·`tbl`·`permit` | `EvidenceDetail`, `PairTable`, `RowsTable`, `PermitText` | `src/features/evidence/` | ④ | LLM 문장 없음, 용법용량 원문은 여기서만(RFP-21-03) |
| 출처 표 `srcs` | `SourceTable`, `DateLines` | `src/features/evidence/`, `src/components/DateLines*` | ④, ③ | `citations[]` 순서 유지, 한 날짜 = 한 줄(PRD-12) |
| 응급 카드 `em-card`(고정 빨강) | `EmergencyBanner` | `src/features/emergency/` | ④ | 맨 위, 전화 걸기 링크, 마스코트 없음(PRD-01-02) |
| 응급 토스트 `em-toast` | `EmergencyToast`(채택 여부 FE-07에서 판단) | `src/features/emergency/` | ④ | 토스트가 사라져도 119 카드는 남아야 함(가정, FE-07 확인) |
| 드로어·시트·모달 | shadcn/ui `Sheet`·`Dialog` 래퍼 | `src/components/ui/` | ① | FE-01-09 A(Radix 4종만) |
| 프로필 온보딩 `pf-*`(연령 칩·임신 주 스테퍼·가족 칩) | `ProfileOnboarding`, `AgeChips`, `PregnancyWeekStepper`, `FamilyChips` | `src/features/profile/`(제안, 5장에 없음) | 미배정 | 확장(PRD-01-05 B, BE-11). 핵심 뒤에만, 축소 순서 2번째 |
| 사진·음성 `dropzone`·`vpanel` | `PhotoDropzone`, `VoicePanel` | `src/features/input-media/`(제안, 5장에 없음) | 미배정 | 확장(FR-11), 축소 순서 1번째 |
| 약관 표 `ttable` | `TermsTable` | `src/app/`(정적 페이지, 서버 컴포넌트) | ① | FE-01-05 A(정적 안내·약관만 서버 컴포넌트) |
| 법적 고지 푸터 | `LegalFooter` | `src/features/emergency/`(고정 안내와 함께) 또는 `src/components/` | ④ | `disclaimer`·`fixed_notice[]` 받은 그대로(7장) |
| 토스트 스타일(react-toastify 번들) | 채택 여부 미정 | - | - | 라이브러리 추가는 ① 소유(9장 (1)) |

- 프로필·사진·음성은 확장 범위라 5장 폴더 구조와 9장 작업자 표에 없다. 착수하면 폴더와 작업자를 이 문서에 더한다.
- 프로토타입과 캔버스 아트보드가 다르면 FE-07 점검 결과(수정 지시서, FE-07-02 A)를 따른다.

## 12. 가정과 확인 필요

- 확인 필요: 10장 토큰 값과 11장 구성이 FE-07 점검(P2~P4) 뒤에도 유지되는지. 프로토타입은 번들이라 렌더링·상호작용을 확인하지 못했다.
- 확인 필요: FE-01-13의 모델 ID(사용자 제안 "fable 5.2"와 저장소가 아는 `claude-fable-5-1`의 차이, FE-01 §6).
- 확인 필요: Vercel rewrites를 거친 NDJSON 스트리밍이 줄 단위로 바로 전달되는지, 요청 시간 상한(3장 (2), BE-13).
- 확인 필요: 4장 (4) 이벤트 형식 초안(이름·필드·`stage` 값·오류 코드·하트비트)을 BE-06과 확정.
- 확인 필요: 4장 (3) 무응답 상한 값(BE-06·BE-13과 정함).
- 확인 필요: `frontend/.env.local`이 저장소 `.gitignore`(`.env.*`)로 무시되는지(`git-actor`).
- 확인 필요: 로컬 전용 `data/mock/chat_responses/`의 fixture를 `frontend/src/mocks/`에 복사해 커밋해도 되는지(합성 데이터지만 `data/mock/`은 로컬 전용 규칙, CLAUDE.md 4장).
- 가정: ky의 스트리밍 요청은 `timeout`을 끄고 POST 자동 재시도를 끈다(4장 (1)·(3)).
- 가정: 첫 타입은 `schemas.py`를 보고 손으로 쓰고 BE-06 뒤 생성 타입으로 바꾼다(3장 (7)).
- 가정: 6장 환경변수 이름은 제안이며, CLAUDE.md 3장 표 추가는 사용자가 알려 줄 때 한다.

## 13. 관련 문서

- `P2-doc/PJ2-RFP.md` 8장 "프론트엔드·배포" 행(2026-11-12 정정)
- `P2-doc/PJ2-PRD.md` 8장 "배포" 행(2026-11-12 정정), 13장 용어(근거 상세 구역·원문 미확보 고지), 15장 유저플로우와 화면 상태
- `P2-doc/PJ2-Agent-Harness.md` 4.1절(이슈별 제어 표)
- `P2-doc/PJ2-UI-검토-파이프라인.md`(FE-07 절차, §3 (1) 두 번째 아티팩트 읽는 법)
- `backend/app/api/schemas.py`(BE-06 응답 스키마 골격)
- `tickets/frontend/FE-01.md`(§6 결정 현황)·`FE-02.md`·`FE-06.md`·`FE-07.md`, `tickets/backend/BE-06.md`, `tickets/backend/BE-13.md`
