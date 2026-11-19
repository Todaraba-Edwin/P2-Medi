# PJ2-계정-프로필-데이터 · Can I PPiyak (코드명 MediAgent)

**DATA DESIGN: 계정·프로필·약관·동의 데이터 설계**

> 작성 2026-11-18 밤(사용자 요청: "수퍼베이스의 RDB를 활용하여 user 테이블에 대한 관리", "프로필 설정에 자녀와 부모를 추가", "이용약관, 개인정보, 민감정보 들에 대해서도 RDB에서 관리 … 추후 수정시 DB만 손보면 되기에", "온보딩에서 수집한 정보들에 대해서 처리할 ERD 설계와 DB 적재"). 티켓: [BE-11](../tickets/backend/BE-11.md)·[FE-04](../tickets/frontend/FE-04.md). 상태: **설계 초안, 원격 적용 0.** SQL과 시드는 이 문서 부록(A·B)의 초안이며, 파일로 옮기고 원격에 적용하는 일은 승인 flag 뒤다(12장).
> **2026-11-19 정정**: 결정 BE-11-06~22가 모두 A로 완료(2026-11-18 밤 늦게 사용자 "권장대로")되어 본문·부록을 그 결정에 맞췄다. 14장은 "결정 후보"에서 "결정됨(2026-11-18)"으로 바꿨고(원본은 `tickets/backend/BE-11.md` §6 결정 현황), 오류 본문(9.1절)·탈퇴 때 동의 기록 파기(7장)·`anonymized_at` 열 삭제(4.6절, 부록 A)가 가장 크게 바뀐 곳이다.
> **2026-11-19 2차 정정(Recap 39, 구현 병합 `aef1446` 반영)**: 부록 A `body_sha256`을 `account.utf8_sha256_hex()`로, `signup_provider` NULL 허용, 프로필 가족 3행 + 전체 4행 제한, 탈퇴 파기 집계 표·함수(`deletion_log`·`delete_my_account()`), 오류 코드 표와 상태 번호(422 `PROFILE_LIMIT`·`HEALTH_CONSENT_REQUIRED`, 503 `AUTH_UNAVAILABLE`, 원격 적용 전 `/me` 501), 9.2·9.3절 구현 차이, 온보딩 단계 계산, 시드 자리표시자 `{{EFFECTIVE_AT}}`를 맞췄다. 부록 A는 여전히 초안이며 실제 DDL은 `backend/app/db/schema_account.sql`이다.
> 근거로 삼은 결정: PRD-01-05 B(계정 서버 저장), PRD-01-09 A′(소셜 로그인. 요구서·PRD·CLAUDE.md의 "PRD-01-06 A′" 표기는 PRD-01-09 A′로 정정이 끝났다, 14.1절), AG-10-06 A(프로필·온보딩을 축소 순서에서 뺌, W2~W3), RFP-30-08 A(2일 스프린트 S1~S3), BE-11-01 B·BE-11-02~05 A(2026-11-18), BE-11-06~22 A(2026-11-18 밤 늦게, 1.3절). 법률 검토는 거치지 않았다(PJ2-RFP.md 12장 위험 표 ①②). 이 문서의 약관·동의 문서 본문 시드는 모두 "초안·법률 검토 전"이다.

## Index
- [1. 목적과 범위](#1-목적과-범위)
  - [1.1 목적](#11-목적)
  - [1.2 스프린트 범위(S1~S3)](#12-스프린트-범위s1s3)
  - [1.3 근거 결정](#13-근거-결정)
  - [1.4 범위 밖](#14-범위-밖)
- [2. 데이터 원칙](#2-데이터-원칙)
  - [2.1 저장하는 것](#21-저장하는-것)
  - [2.2 저장하지 않는 것](#22-저장하지-않는-것)
  - [2.3 접근 통제의 두 겹](#23-접근-통제의-두-겹)
- [3. ERD](#3-erd)
- [4. 테이블 정의](#4-테이블-정의)
  - [4.1 enum](#41-enum)
  - [4.2 app_users(계정·온보딩 상태)](#42-app_users계정온보딩-상태)
  - [4.3 profiles(본인·가족 프로필)](#43-profiles본인가족-프로필)
  - [4.4 profile_medications(복용 중인 약)](#44-profile_medications복용-중인-약)
  - [4.5 legal_documents(약관·동의 문서)](#45-legal_documents약관동의-문서)
  - [4.6 user_consents(동의·철회 기록)](#46-user_consents동의철회-기록)
  - [4.7 auth.users(Supabase Auth, 우리가 만들지 않음)](#47-authuserssupabase-auth-우리가-만들지-않음)
  - [4.8 age_band ↔ 나이 구간 대응](#48-age_band--나이-구간-대응)
- [5. RLS 정책](#5-rls-정책)
  - [5.1 정책 표](#51-정책-표)
  - [5.2 백엔드가 RLS 아래에서 도는 방식](#52-백엔드가-rls-아래에서-도는-방식)
- [6. 동의 흐름](#6-동의-흐름)
  - [6.1 필수·선택 동의](#61-필수선택-동의)
  - [6.2 건강 정보 별도 동의(BE-11-03 A)](#62-건강-정보-별도-동의be-11-03-a)
  - [6.3 철회 시 삭제 트리거](#63-철회-시-삭제-트리거)
- [7. 탈퇴·보관](#7-탈퇴보관)
  - [7.1 탈퇴 순서](#71-탈퇴-순서)
  - [7.2 동의 기록 처리(BE-11-22 A)](#72-동의-기록-처리be-11-22-a)
  - [7.3 조사 결과](#73-조사-결과)
- [8. 약관 문서 버전 관리](#8-약관-문서-버전-관리)
- [9. API 계약](#9-api-계약)
  - [9.1 공통(인증 헤더·게스트·오류)](#91-공통인증-헤더게스트오류)
  - [9.2 엔드포인트 표](#92-엔드포인트-표)
  - [9.3 응답 스키마](#93-응답-스키마)
- [10. 온보딩 화면 흐름 ↔ 테이블](#10-온보딩-화면-흐름--테이블)
- [11. chat 연동](#11-chat-연동)
- [12. 마이그레이션·시드 적재 절차](#12-마이그레이션시드-적재-절차)
- [13. 시험 계획](#13-시험-계획)
- [14. 결정됨(2026-11-18)](#14-결정됨2026-11-18)
  - [14.1 확인된 문서 충돌](#141-확인된-문서-충돌)
  - [14.2 결정 현황 표](#142-결정-현황-표)
- [15. 코드 대조·출처](#15-코드-대조출처)
- [부록 A. 마이그레이션 SQL 초안](#부록-a-마이그레이션-sql-초안)
- [부록 B. 약관·동의 문서 시드 초안](#부록-b-약관동의-문서-시드-초안)

## 1. 목적과 범위

### 1.1 목적
로그인한 사용자의 **계정·프로필(본인 + 가족 최대 3명)·복용 중인 약·약관/동의 문서·동의 기록**을 Supabase Postgres에 두는 데이터 구조와, 그것을 다루는 FastAPI 계약을 정한다. 약관·개인정보·민감정보 문서는 DB에 버전으로 두고 프런트는 API로 받아 그리므로, 문구를 고칠 때 **새 버전 행만 넣으면 된다**(BE-11-02 A, 사용자 "추후 수정시 DB만 손보면 되기에").

이 확장은 Agent-RAG 핵심(Router·도구 선택·근거 고정·Validator·평가)을 바꾸지 않는다. 프로필은 `/chat` 요청의 `context`를 채우는 **입력 출처 하나**가 늘어나는 것뿐이다(11장).

### 1.2 스프린트 범위(S1~S3)
RFP-30-08 A의 2일 스프린트에 맞춘 데이터·API 범위다.

| 스프린트 | 화면·인증 | 이 문서의 데이터·API 범위 |
|---|---|---|
| S1 인증 | Google·Kakao 로그인(이메일은 메일 인증을 갖춘 뒤 재검토, PRD-01-10 A 2026-11-19), 게스트 유지 | `app_users`, `legal_documents`(시드), `user_consents`, `GET /legal/*`, `GET /me`, `POST /consents`, `DELETE /me`, 백엔드 JWT 검증 |
| S2 프로필·온보딩 + Naver | 온보딩 단계, 프로필 CRUD, Naver 연동(Supabase Custom OIDC, BE-11-15 A. 반나절 상한을 넘으면 Naver 제외, BE-11-19 A) | `profiles`, `profile_medications`, 프로필 CRUD API, 건강 정보 동의·철회 트리거, `provider='naver'` |
| S3 chat 연동 | "누가 먹나요" 대상 선택 | 프로필 → `context` 변환(프런트), `/chat` 무변경 확인 |

### 1.3 근거 결정
| 번호 | 내용 | 이 문서의 반영 |
|---|---|---|
| PRD-01-05 B | 계정(Supabase Auth)으로 서버 저장 | 4장 전체 |
| PRD-01-09 A′(2026-11-18) | 소셜 로그인 Google·Kakao S1, Naver S2, Apple 제외, 이메일 포함(2026-11-19 PRD-01-10 A로 화면의 이메일 로그인은 숨김, 재검토 전까지 enum 값만 유지) | 4.1절 `provider` enum |
| AG-10-06 A | 프로필·온보딩을 축소 순서에서 빼고 W2~W3 | 1.2절 |
| BE-11-01 B | 본인 + 가족 최대 3명, 관계 칸 | 4.3절 행 수 제한·`relation` |
| BE-11-02 A | `legal_documents` + `user_consents`, 프런트는 API로 받아 표시 | 4.5·4.6·8·9장 |
| BE-11-03 A | 건강 정보(임신 여부·복용 약)는 별도 선택 동의, 미동의면 그 칸 저장 안 함 | 6.2절, 부록 A 트리거 |
| BE-11-04 A → BE-11-22 A | 탈퇴 시 프로필·약 즉시 삭제. 동의 기록은 BE-11-04에서 "식별자를 지운 채 보관(기간은 조사 뒤)"이었으나 조사 뒤 **BE-11-22 A로 동의 기록 포함 즉시 전부 파기**로 확정(2026-11-18, 법률 검토 전) | 7장 |
| BE-11-05 A | 복용 약은 입력 원문 + 사전 확인 시 `item_seq` | 4.4절 |
| BE-11-06 A | 계정 테이블은 `account` 스키마(Data API 비노출) + 요청마다 `SET LOCAL ROLE authenticated`로 RLS 아래에서 실행. 단 `SET ROLE` 가능 여부를 읽기 전용으로 먼저 확인하고 안 되면 B(`WHERE user_id` 코드 검사) | 2.3·5.2절 |
| BE-11-07 A | 연령대 11구간. 확정 전 원격 `age_contra` 분포를 읽기 전용으로 센다 | 4.8절 |
| BE-11-08 A | 관계 5종 `self`·`child`·`parent`·`spouse`·`other` | 4.1절 |
| BE-11-09 A | 임신 주차 열을 지금 만들지 않는다 | 1.4절 |
| BE-11-10 A | `app_users`는 백엔드가 첫 `GET /me`에서 만든다(`auth.users` 트리거 안 씀) | 4.2절 |
| BE-11-11 A | 공급자 동의 항목을 최소로 요청하고 S1에서 실제 저장 항목을 확인해 처리방침에 적는다 | 4.7절 |
| BE-11-12 A | 필수 개인정보 동의 철회 시 프로필 전부 삭제, 계정은 유지 | 6.3절 |
| BE-11-13 A | 복용 약은 기본 끔, 질문마다 "내 복용 약과 함께 확인" 토글 | 11장 |
| BE-11-14 A | RLS 시험은 로컬 Postgres + `auth` 스키마 스텁, 원격은 승인 뒤 스모크만 | 13장 |
| BE-11-15 A | Naver는 Supabase Custom OIDC(`issuer https://nid.naver.com`, 이메일 없음), 실패하면 OAuth2 + userinfo 어댑터 | 4.7·7.3절 |
| BE-11-16 A | Kakao는 이메일을 받지 않는다(닉네임만, "Allow users without an email") | 4.7·7.3절 |
| BE-11-17 A | 백엔드 JWT 검증은 PyJWT(`PyJWKClient`, 새 의존성 승인됨) | 9.1절 |
| BE-11-18 A | `NEXT_PUBLIC_SUPABASE_URL`·`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` 허용(publishable 키는 RLS 전제의 공개 키라 CLAUDE.md 3장 "키 금지"의 예외) | 9.1절 |
| BE-11-19 A | Naver S2는 반나절 상한, 넘으면 Naver 제외 | 1.2절 |
| BE-11-20 A | 토큰 검증 서버 장애는 503 `AUTH_UNAVAILABLE` | 9.1절 |
| BE-11-21 A | 계정 API 오류 본문은 `/chat`과 같은 `{code, fields}` | 9.1절 |
| PRD-07-01 A | 서버는 대화 상태를 저장·로그하지 않고 요청의 `context`만 쓴다 | 11장 |
| FE-07-18 A | 프로필 나이로 연령금기 판정, 특정할 수 없으면 나이별 원문 값 | 4.8·11장 |

### 1.4 범위 밖
질문·대화 이력 저장(PRD-07-01 A, 3주 범위 밖), Apple 로그인, 알레르기(PRD-01-03 A에서 제외), 임신 주차(FE-07-12 B는 "추후 확장". 열을 지금 만들지 않는다, BE-11-09 A. 필요해지면 비파괴 열 추가 마이그레이션), 마케팅 수신 동의, 관리자 화면(약관 수정은 SQL로 새 버전 행 삽입).

## 2. 데이터 원칙

### 2.1 저장하는 것
- **로그인 최소 정보**: Supabase Auth가 `auth.users`에 두는 값(이메일, 공급자 식별자). 우리 테이블에는 **이메일을 복사하지 않는다**(이메일은 로그인에만, PJ2-RFP.md 7장 개인정보 `:331`).
- **일반 프로필(필수 동의 `privacy_consent`)**: 관계(`relation`), 화면 표시용 짧은 이름(`label`, 선택, 실명 대신 "아이"·"엄마" 권장), 연령대(`age_band`).
- **건강 정보(선택 동의 `sensitive_consent`)**: 임신 여부(`pregnancy_status`), 복용 중인 약(`profile_medications`).
- **동의 기록**: 어떤 문서의 몇 번째 버전에 언제 동의·철회했는지.

### 2.2 저장하지 않는 것
- 질문·대화 내용, `/chat` 요청 본문, 모델 출력(NFR-04, PRD-07-01 A). 계정 테이블과 `/chat` 경로는 서로 쓰지 않는다(11장).
- 게스트 사용자의 어떤 값도(게스트는 토큰이 없으므로 계정 API를 부를 수 없다).
- 사진·음성(FR-11, PRD-08-04).
- 프로필 값의 로그: API 접근 로그는 BE-15 비밀값 가드·RFP-34 집계 규칙대로 경로·상태 코드·지연만 남기고 본문은 남기지 않는다.

### 2.3 접근 통제의 두 겹
1. **RLS**: 모든 계정 테이블에 RLS를 켜고 `auth.uid()` 기준으로 본인 행만 허용한다(5장).
2. **노출하지 않는 스키마**: 계정 테이블은 `public`이 아니라 새 스키마 `account`에 둔다. Supabase Data API(PostgREST)는 설정한 스키마만 노출하므로(기본 `public`) 브라우저가 계정 테이블을 직접 부르지 못하고 FastAPI만 거친다. `public`에 둔 사전 테이블을 RLS + REVOKE로 막은 BE-06-32 A(`backend/app/db/schema_dict_pg.sql:3-6`)와 같은 목적이다. 이 구성은 BE-11-06 A로 정해졌다. 노출 스키마 설정은 적용 뒤 사용자가 대시보드에서 확인한다(12장 5번).

백엔드가 테이블 소유 역할(`SUPABASE_DB_URL`의 postgres 계열)로 접속하면 RLS를 **우회한다**(`schema_dict_pg.sql:5-6`의 가정과 같다). 그래서 계정 API는 요청마다 `authenticated` 역할로 내려가 RLS 아래에서 돈다(5.2절). 이렇게 해야 RLS가 장식이 아니라 실제 방어선이 되고, 다른 계정 시험(13장)이 의미를 갖는다.

## 3. ERD

```mermaid
erDiagram
    AUTH_USERS ||--o| APP_USERS : "1:1 (ON DELETE CASCADE)"
    APP_USERS ||--o{ PROFILES : "1:N (본인 1 + 가족 ≤3)"
    PROFILES ||--o{ PROFILE_MEDICATIONS : "1:N (≤10, 건강 동의 필요)"
    APP_USERS ||--o{ USER_CONSENTS : "1:N (탈퇴 시 함께 삭제)"
    LEGAL_DOCUMENTS ||--o{ USER_CONSENTS : "(doc_type, version)"

    AUTH_USERS {
        uuid id PK "Supabase Auth 관리"
        text email "로그인용, 복사하지 않음"
        jsonb raw_user_meta_data "공급자 제공 값"
    }
    APP_USERS {
        uuid user_id PK,FK "auth.users.id"
        provider signup_provider "email|google|kakao|naver"
        text onboarding_step "consent|profile_self|family|done"
        timestamptz onboarding_completed_at
        timestamptz created_at
        timestamptz updated_at
    }
    PROFILES {
        uuid profile_id PK
        uuid user_id FK
        relation relation "self|child|parent|spouse|other"
        text label "선택, ≤20자"
        age_band age_band "선택"
        pregnancy_status pregnancy_status "건강 동의 시만"
        smallint sort_order
        timestamptz created_at
        timestamptz updated_at
    }
    PROFILE_MEDICATIONS {
        uuid medication_id PK
        uuid profile_id FK
        uuid user_id FK "RLS용 중복"
        text input_text "입력 원문 ≤100자"
        char9 item_seq "사전 확인 시"
        timestamptz confirmed_at
        timestamptz created_at
    }
    LEGAL_DOCUMENTS {
        uuid document_id PK
        doc_type doc_type "terms|privacy_policy|privacy_consent|sensitive_consent"
        int version "UNIQUE(doc_type, version)"
        text title
        text body_md
        bool required
        bool requires_reconsent
        doc_status status "draft|published|retired"
        timestamptz effective_at
        text legal_review "not_reviewed|reviewed"
        text body_sha256 "생성 열"
    }
    USER_CONSENTS {
        bigint consent_id PK
        uuid user_id FK "NOT NULL"
        doc_type doc_type FK
        int doc_version FK
        consent_action action "agree|withdraw"
        text channel "onboarding|settings|reconsent"
        timestamptz acted_at
    }
```

`onboarding_state`는 별도 테이블로 두지 않고 `app_users`의 두 열(`onboarding_step`·`onboarding_completed_at`)로 접었다. 계정마다 한 행이고 이력이 필요 없어 1:1 테이블을 하나 더 두면 조인과 RLS 정책만 늘기 때문이다.

## 4. 테이블 정의
모든 테이블은 스키마 `account`에 둔다. 시각은 `timestamptz`(UTC 저장, 화면은 Asia/Seoul). 전체 DDL은 부록 A.

### 4.1 enum
| enum | 값 | 근거·메모 |
|---|---|---|
| `provider` | `email`, `google`, `kakao`, `naver` | Apple 제외(PRD-01-09 A′). `email`은 값만 남기고 화면의 이메일 로그인은 숨겼다(PRD-01-10 A, 2026-11-19). 값은 가입 경로 기록용이며 공급자 연결 목록의 원본은 `auth.identities`다 |
| `relation` | `self`, `child`, `parent`, `spouse`, `other` | BE-11-01 B "관계 칸: 자녀·부모 등". `spouse`·`other`는 "등"에 해당하며 BE-11-08 A로 확정 |
| `pregnancy_status` | `pregnant`, `not_pregnant`, `unknown` | NULL = 입력 안 함 또는 건강 동의 없음. `unknown`은 사용자가 "모름"을 고른 것(판정 입력은 `pregnant=None`과 같다, 11장) |
| `age_band` | 4.8절 표의 11개 | 연령대(PRD-01-03 A). 11구간은 BE-11-07 A로 정해졌고, 경계는 연령금기 기준값에서 흔한 값으로 둔 것이라 원격 분포 확인이 남았다(4.8절) |
| `doc_type` | `terms`, `privacy_policy`, `privacy_consent`, `sensitive_consent` | 사용자 "이용약관, 개인정보, 민감정보". 처리방침(`privacy_policy`)은 공개 고지이고 동의 대상이 아니다. 수집·이용 동의(`privacy_consent`)와 민감정보 동의(`sensitive_consent`)는 따로 둔다 |
| `doc_status` | `draft`, `published`, `retired` | 8장 |
| `consent_action` | `agree`, `withdraw` | 4.6절 |

외부 AI 전송 고지(`START_EXTERNAL_AI_NOTICE`, PJ2-PRD.md 15.3절 (9))는 **DB 문서가 아니라 코드 상수**로 둔다. 고정 문구는 코드로 강제한다는 원칙(CLAUDE.md 1장 하네스 원칙)과 "고지이며 동의 관문이 아니다"(PJ2-PRD.md:362)를 지키기 위해서다. 처리방침 본문에는 같은 사실을 서술한다(부록 B).

### 4.2 app_users(계정·온보딩 상태)
| 열 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `user_id` | uuid | PK, FK → `auth.users(id)` ON DELETE CASCADE | Supabase Auth 사용자와 1:1 |
| `signup_provider` | `provider` | NULL 허용 | 첫 가입 경로. JWT의 `app_metadata.provider`에서 백엔드가 채울 계획이나, 지금 검증기가 `sub`만 돌려줘 **아직 채우지 않는다**(후속, 지금 쓰는 화면 없음). 이전 초안은 NOT NULL이었다(2026-11-19 정정) |
| `onboarding_step` | text | NOT NULL DEFAULT `'consent'`, CHECK ∈ {consent, profile_self, family, done} | 10장 단계 |
| `onboarding_completed_at` | timestamptz | NULL 허용 | `done`이 된 시각 |
| `created_at`·`updated_at` | timestamptz | NOT NULL DEFAULT now() | `updated_at`은 트리거로 갱신 |

행은 **백엔드가 첫 `GET /me`에서 만든다**(INSERT … ON CONFLICT DO NOTHING, BE-11-10 A). `auth.users`에 트리거를 거는 방식(가입과 동시에 행 생성)은 트리거 실패가 가입 자체를 막고 `auth` 스키마를 건드리므로 쓰지 않는다.

### 4.3 profiles(본인·가족 프로필)
| 열 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `profile_id` | uuid | PK DEFAULT gen_random_uuid() | |
| `user_id` | uuid | NOT NULL, FK → `app_users` ON DELETE CASCADE | |
| `relation` | `relation` | NOT NULL | 본인은 `self` |
| `label` | text | NULL 허용, 1~20자 | 화면 표시용. 실명을 권하지 않는다(화면 안내) |
| `age_band` | `age_band` | NULL 허용 | |
| `pregnancy_status` | `pregnancy_status` | NULL 허용, **건강 동의가 있을 때만 NULL이 아닌 값**(트리거) | |
| `sort_order` | smallint | NOT NULL DEFAULT 0, 0~3 | 화면 순서 |
| `created_at`·`updated_at` | timestamptz | | |

- **행 수 제한**: **가족 3행 + 전체 4행**(본인 1 + 가족 3, BE-11-01 B). 이전 초안은 "계정당 4행"만 세어, 본인 없이 가족 4명을 넣을 수 있었다. 이제 `relation <> 'self'`인 행이 3개를 넘어도, 전체가 4개를 넘어도 거부한다. 트리거는 `INSERT OR UPDATE OF relation`에 걸리고(관계 값이 그대로인 UPDATE는 건너뛴다) `pg_advisory_xact_lock`으로 같은 계정의 동시 삽입을 줄 세운 뒤 센다(부록 A `enforce_profile_limit`). 초과는 `P0001 PROFILE_LIMIT` → API **422**(BE-11-25 A, 2026-11-19. 이전 초안은 409).
- **본인 1행**: 부분 유일 색인 `UNIQUE (user_id) WHERE relation = 'self'`.
- 색인: `(user_id)`.

### 4.4 profile_medications(복용 중인 약)
| 열 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `medication_id` | uuid | PK | |
| `profile_id` | uuid | NOT NULL, FK → `profiles` ON DELETE CASCADE | |
| `user_id` | uuid | NOT NULL, FK → `app_users` ON DELETE CASCADE | RLS 정책을 조인 없이 쓰려고 중복 저장. 트리거가 `profiles.user_id`와 같은지 검사 |
| `input_text` | text | NOT NULL, 공백 아님, 1~100자 | 사용자가 입력한 원문(BE-11-05 A). 길이는 `DRUG_NAME_MAX_CHARS`(`backend/app/api/request.py:19`)와 같다 |
| `item_seq` | char(9) | NULL 허용, `^\d{9}$` | 사전(`drug_dict_entry`)에서 확인됐을 때만. 형식은 `ConfirmedDrug.item_seq`(`request.py:49`)와 같다 |
| `confirmed_at` | timestamptz | `item_seq`가 있으면 NOT NULL | 사전 확인 시각 |
| `created_at` | timestamptz | | |

- **건강 동의 필요**: 삽입·수정 때 트리거가 활성 `sensitive_consent`를 확인한다. 없으면 `P0001 CONSENT_REQUIRED:sensitive_consent`(DB 두 번째 방어선). API는 이 검사를 먼저 해서 **422 `HEALTH_CONSENT_REQUIRED`**로 답한다(BE-11-25 A, 2026-11-19. 이전 초안은 403 `CONSENT_REQUIRED`).
- **개수 상한** 프로필당 10개(`CONFIRMED_DRUGS_MAX`, `request.py:18`과 같게 해 그대로 `context.confirmed_drugs`에 실을 수 있게 한다). 초과는 `P0001 MEDICATION_LIMIT` → API 422 `MEDICATION_LIMIT`.
- `item_seq`에 사전 테이블 FK를 걸지 않는다. 사전은 재적재(BE-06-24 B)로 바뀔 수 있고, 사라진 품목도 사용자 입력 원문은 남아야 하기 때문이다.

### 4.5 legal_documents(약관·동의 문서)
| 열 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `document_id` | uuid | PK | |
| `doc_type` | `doc_type` | NOT NULL | |
| `version` | integer | NOT NULL ≥1, `UNIQUE (doc_type, version)` | 1, 2, 3 … |
| `title` | text | NOT NULL | |
| `body_md` | text | NOT NULL | 마크다운 본문. 프런트는 sanitize 후 렌더링(HTML 허용 안 함) |
| `required` | boolean | NOT NULL | 가입·저장에 필수인가(`terms`·`privacy_consent` true, `sensitive_consent` false, `privacy_policy`는 동의 대상이 아니므로 false) |
| `requires_reconsent` | boolean | NOT NULL DEFAULT false | 이 버전이 시행되면 앞 버전 동의자에게 다시 동의를 받는가 |
| `status` | `doc_status` | NOT NULL DEFAULT `draft` | |
| `effective_at` | timestamptz | NOT NULL | 시행 시각 |
| `legal_review` | text | NOT NULL DEFAULT `not_reviewed`, ∈ {not_reviewed, reviewed} | 프런트가 "초안·법률 검토 전" 표지를 그리는 근거 |
| `body_sha256` | text | 생성 열 `account.utf8_sha256_hex(body_md)`(UTF-8 바이트의 SHA-256 16진 문자열) | 동의한 본문이 무엇이었는지 사후 대조. `convert_to()`가 STABLE이라 생성 열에 직접 쓰면 `generation expression is not immutable`로 실패하므로 IMMUTABLE plpgsql 함수로 감쌌다(2026-11-19 로컬 RLS 시험에서 발견·수정, `aef1446`, 부록 A) |
| `created_at` | timestamptz | | |

- **게시 뒤 본문 불변**: `status <> 'draft'`인 행의 `title`·`body_md`·`version`·`doc_type` 수정을 트리거가 막는다. 고칠 때는 새 버전 행을 넣는다(8장).
- 색인: `(doc_type, status, effective_at DESC)`.

### 4.6 user_consents(동의·철회 기록)
| 열 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `consent_id` | bigint | PK, IDENTITY | |
| `user_id` | uuid | NOT NULL, FK → `app_users` ON DELETE CASCADE | 탈퇴 때 `app_users`와 함께 삭제된다(BE-11-22 A, 7장) |
| `doc_type`·`doc_version` | `doc_type`·integer | NOT NULL, FK → `legal_documents(doc_type, version)` | 동의한 바로 그 버전 |
| `action` | `consent_action` | NOT NULL | `agree` 또는 `withdraw` |
| `channel` | text | NOT NULL, ∈ {onboarding, settings, reconsent} | 어디서 했는가 |
| `acted_at` | timestamptz | NOT NULL DEFAULT now() | |

- 이전 초안에 있던 `anonymized_at` 열과 `user_id` NULL 허용은 BE-11-22 A(탈퇴 시 동의 기록 포함 즉시 전부 파기)로 **삭제했다**. 식별자를 지워 남기는 행이 없기 때문이다.
- **추가만 한다**(append-only). `authenticated` 역할에 UPDATE·DELETE 권한과 정책이 없다. 탈퇴 때의 삭제는 `app_users` DELETE의 CASCADE로 서버(소유 역할)가 한다. 현재 상태는 `(user_id, doc_type)`별 가장 최근 행이다(뷰 `account.user_consent_current`, 부록 A).
- `privacy_policy`에는 동의 행을 만들지 않는다(API가 400). 처리방침은 고지 문서다.
- 색인: `(user_id, doc_type, acted_at DESC)`.

### 4.7 auth.users(Supabase Auth, 우리가 만들지 않음)
Supabase Auth가 관리하며 이메일·공급자 identity·`raw_user_meta_data`를 둔다. **Google·Kakao가 넘기는 이름·사진 URL이 `raw_user_meta_data`에 들어갈 수 있다**(가정, 공급자 scope에 따라 다름). 이는 "로그인 최소 정보"(PJ2-RFP.md:331) 밖이므로 공급자 동의 항목을 최소로 요청하고(Kakao는 닉네임만, Google은 Supabase 기본 scope), 실제로 무엇이 저장되는지 S1에서 확인해 처리방침 본문에 맞춘다(BE-11-11 A). 필요하면 로그인 직후 서버가 메타데이터의 이름·사진을 지우는 안을 S1 실측 뒤에 더한다.

- **Kakao**: 이메일을 받지 않는다(BE-11-16 A). 동의 항목은 닉네임(`profile_nickname`)만 요청하고 Supabase의 "Allow users without an email"을 켠다. 그래서 `auth.users.email`이 비어 있을 수 있다.
- **Naver**: Supabase Custom OIDC로 연동한다(`issuer https://nid.naver.com`, 이메일 없음, BE-11-15 A). 실패하면 OAuth2 + userinfo 어댑터로 내리고, S2 반나절 상한을 넘으면 Naver를 제외한다(BE-11-19 A).

### 4.8 age_band ↔ 나이 구간 대응
`/chat`의 `context.age`는 `AgeInput(lower, upper, unit)`이다(`backend/app/api/request.py:29-42`). 프로필의 `age_band`는 아래 표로 바뀐다(프런트 한 곳, 11장). **11구간은 BE-11-07 A로 정해졌다.** 경계 값은 연령금기 기준(`age_contra.age_value`·`age_unit`·`age_cond`, `backend/app/db/schema.sql:44-46`)에서 흔히 쓰일 값으로 **가정**했고, 결정에 따라 확정 전에 원격 `age_contra`의 (기준값·단위·조건) 분포를 읽기 전용으로 세는 일이 남아 있다(아직 세지 않음).

| `age_band` | 화면 표시 | `lower` | `upper` | `unit` |
|---|---|---|---|---|
| `m0_2` | 생후 3개월 미만 | 0 | 2 | 개월 |
| `m3_5` | 생후 3~5개월 | 3 | 5 | 개월 |
| `m6_11` | 생후 6~11개월 | 6 | 11 | 개월 |
| `y1` | 만 1세 | 1 | 1 | 세 |
| `y2` | 만 2세 | 2 | 2 | 세 |
| `y3_5` | 만 3~5세 | 3 | 5 | 세 |
| `y6_11` | 만 6~11세 | 6 | 11 | 세 |
| `y12_14` | 만 12~14세 | 12 | 14 | 세 |
| `y15_18` | 만 15~18세 | 15 | 18 | 세 |
| `y19_64` | 만 19~64세 | 19 | 64 | 세 |
| `y65_plus` | 만 65세 이상 | 65 | 150 | 세 |

- `upper`는 **만 나이 정수의 포함 상한**으로 쓴다(예: `y3_5`는 만 5세 11개월까지). 그래프가 구간을 이렇게 읽는지(특히 "6세 미만" 기준과 `upper=5`)는 AG 몫이며 확인 필요다. 구간이 기준 나이에 걸리면 판정 대신 나이별 원문 값을 보인다(FE-07-18 A).
- 출생 연월을 받으면 정밀해지지만 수집 항목이 늘어 PRD-01-03 A("연령대")와 어긋난다. 받지 않는다.

## 5. RLS 정책

### 5.1 정책 표
`(select auth.uid())`로 감싸 행마다 함수를 다시 부르지 않게 한다.

| 테이블 | anon | authenticated SELECT | INSERT | UPDATE | DELETE |
|---|---|---|---|---|---|
| `legal_documents` | `status='published'`만 SELECT | `status='published'`만 | 없음 | 없음 | 없음 |
| `app_users` | 없음 | `user_id = auth.uid()` | `user_id = auth.uid()` | 본인 행(열 권한은 `onboarding_*`만) | 없음(탈퇴는 7장 경로) |
| `profiles` | 없음 | 본인 | 본인 | 본인 | 본인 |
| `profile_medications` | 없음 | 본인 | 본인 | 본인 | 본인 |
| `user_consents` | 없음 | 본인 | 본인(`user_id = auth.uid()`) | **없음** | **없음** |

시드·약관 새 버전 넣기·탈퇴 삭제는 소유 역할(마이그레이션 스크립트, 서버)만 한다. SQL은 부록 A 5절.

### 5.2 백엔드가 RLS 아래에서 도는 방식
계정 API는 요청마다 한 트랜잭션 안에서 아래를 실행한다.

```sql
BEGIN;
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claims', :claims_json, true);  -- 검증을 통과한 JWT의 claims(sub·role·aud)
-- 이후 account.* 질의는 RLS를 받는다. auth.uid()는 claims의 sub다.
COMMIT;
```

- claims는 **백엔드가 JWKS로 서명을 검증한 뒤의 값만** 넣는다(9.1절). 검증하지 않은 값을 넣으면 RLS가 무의미해진다.
- 확인 필요(읽기 전용 점검): 소유 역할이 `authenticated`로 `SET ROLE`할 수 있는지(`pg_has_role(current_user, 'authenticated', 'MEMBER')`), `auth.uid()`가 `request.jwt.claims`의 `sub`를 읽는지. 둘 중 하나라도 안 되면 대안은 질의마다 `WHERE user_id = :sub`를 코드로 강제하고 RLS는 Data API 방어로만 두는 것이다(BE-11-06 B). BE-11-06 A는 이 점검이 통과한다는 조건으로 정해졌다.
- 연결은 기존 `SUPABASE_DB_URL`(Session pooler)을 쓴다. `SET LOCAL`은 트랜잭션이 끝나면 풀리므로 풀 연결에 역할이 남지 않는다.

## 6. 동의 흐름

### 6.1 필수·선택 동의
| 문서 | 필수 여부 | 받는 때 | 없을 때 |
|---|---|---|---|
| `terms` 이용약관 | 계정 필수 | 온보딩 1단계 | 계정 API 403 `CONSENT_REQUIRED`(게스트 사용은 그대로) |
| `privacy_consent` 개인정보 수집·이용 | 프로필 저장 필수 | 온보딩 1단계 | 프로필 API 403. 동의 없이 대화 중 입력만(PJ2-PRD.md 15.3절 S10 2단계) |
| `sensitive_consent` 민감정보(건강) 처리 | **선택** | 온보딩 1단계(별도 체크), 설정에서 나중에 | 임신 여부·복용 약 칸을 저장하지 않음(BE-11-03 A) |
| `privacy_policy` 처리방침 | 동의 대상 아님(고지) | 온보딩 1단계에 링크로 표시 | 해당 없음 |

화면은 체크박스를 문서마다 따로 두고 "전체 동의" 하나로 선택 동의까지 묶지 않는다(선택 동의를 필수처럼 보이게 하지 않기 위해서다. 법률 검토 전의 보수적 기본값).

### 6.2 건강 정보 별도 동의(BE-11-03 A)
- DB 트리거 두 개가 강제한다(부록 A `enforce_health_consent_*`): `profiles.pregnancy_status`를 NULL이 아닌 값으로 쓰거나 `profile_medications`에 행을 넣을 때, 그 계정의 최신 `sensitive_consent` 기록이 `agree`가 아니면 거부한다.
- API도 같은 검사를 먼저 해서 **422 `HEALTH_CONSENT_REQUIRED`**(`fields: ["pregnancy_status"]` 또는 `["medications"]`, 9.1절, BE-11-25 A, 2026-11-19. 이전 초안은 403 `CONSENT_REQUIRED`)로 답한다. DB 트리거는 API 검사가 빠졌을 때의 두 번째 방어선이다.
- 건강 동의가 없을 때 화면은 임신 여부·복용 약 칸을 **비활성 + 안내**로 두고, 질문할 때는 대화 중 입력으로 같은 값을 쓸 수 있다(저장만 안 할 뿐 기능은 그대로).

### 6.3 철회 시 삭제 트리거
`user_consents`에 `action='withdraw'` 행이 들어오면 AFTER INSERT 트리거(`on_consent_withdraw`)가 같은 트랜잭션에서 지운다.

| 철회 문서 | 즉시 하는 일 |
|---|---|
| `sensitive_consent` | 그 계정의 모든 `profiles.pregnancy_status` → NULL, `profile_medications` 전부 DELETE |
| `privacy_consent` | 그 계정의 `profiles` 전부 DELETE(약은 CASCADE). 계정은 남는다(BE-11-12 A). 계정 삭제는 별도 버튼(`DELETE /me`)으로 받는다 |
| `terms` | 트리거가 거부(`P0001 USE_ACCOUNT_DELETE`) → API 409. 약관 철회는 탈퇴(`DELETE /me`)로만 |

삭제는 즉시이며 휴지통·지연 삭제가 없다. 지운 뒤 API는 갱신된 `GET /me` 모양을 돌려준다.

## 7. 탈퇴·보관

### 7.1 탈퇴 순서
`DELETE /me`(9장) 처리 순서다.

1. JWT 검증(본인).
2. 한 트랜잭션: 함수 `account.delete_my_account()`(SECURITY DEFINER, `search_path=''`, `authenticated`에 EXECUTE만 주고 `app_users` DELETE 권한은 주지 않는다)가 `auth.uid()`의 `app_users` 행을 DELETE → `profiles`·`profile_medications`·`user_consents`가 모두 CASCADE로 **즉시** 삭제된다. 동의 기록도 남기지 않는다(BE-11-22 A, 7.2절). 지우기 전 건수(프로필·복용 약·동의 기록)를 함수가 돌려주고, BEFORE DELETE 트리거 `log_account_deletion`이 파기 사실을 **일자(UTC)별 건수만** 새 표 `account.deletion_log(deleted_on, accounts, profiles, medications, consents)`에 더한다(식별자·시각 열 없음, 소유 역할만 읽고 쓴다, 7.2절). 없는 계정이면 0건이고 멱등이다. `auth.uid()`가 없으면 `P0001 AUTH_REQUIRED`.
3. Supabase Admin API로 `auth.users` 사용자 삭제(서버 전용 `SUPABASE_SECRET_KEY`). 공급자 identity도 함께 지워진다(가정, 확인 필요).
4. 3이 실패하면 502 `AUTH_DELETE_FAILED`를 돌려주고 재시도를 안내한다. 이때 앱 데이터는 이미 지워져 있어 다시 로그인하면 빈 계정이며, 재요청하면 1~3을 다시 한다(멱등). 로그에는 오류 유형만 남긴다.

`auth.users`가 다른 경로로 지워져도 `app_users`가 ON DELETE CASCADE라 프로필·복용 약·동의 기록이 모두 남지 않는다. 이전 초안의 BEFORE DELETE 익명화 트리거(`anonymize_consents`)는 삭제로 바뀌어 부록 A에서 뺐고, 같은 자리에 파기 집계 트리거(`log_account_deletion`)를 두었다. 이 트리거는 `app_users` 행이 지워질 때마다(본인 탈퇴든 `auth.users` 삭제의 CASCADE든) 일자별 건수를 더하므로, 이전 초안의 "이 경로에서는 파기 로그 한 줄이 남지 않는다"는 서술은 더 이상 맞지 않는다(2026-11-19 정정, 근거 `backend/app/db/schema_account.sql:240-288`).

### 7.2 동의 기록 처리(BE-11-22 A)
> **결론(법률 검토 전, 2026-11-18 조사)**: 탈퇴하면 프로필·복용 약과 함께 동의 기록(`user_consents`)도 즉시 삭제한다(BE-11-22 A. 이전 BE-11-04 표의 B와 같은 내용). 이 서비스는 의료기관이 아니고 결제·판매가 없어, 의료법 제22조·전자상거래법 제6조 같은 보존 의무 법령이 해당하지 않는다. 그래서 개인정보 보호법 제21조 제1항과 표준 개인정보 보호지침 제10조 제1항(불필요해진 날부터 5일 이내 파기)을 따른다. 식별자를 지운 동의 기록은 특정인의 동의를 증명하지 못하고, 결합하면 재식별될 수 있어 남기지 않는다. 파기 사실은 식별자 없이 일자·건수만 운영 로그에 남긴다(지침 제10조 제3항). 백업에 남는 기간은 Supabase 백업 보존 기간을 확인해 처리방침에 적는다. 출처는 조사 보고 `auth-research-retention.md`(로컬 전용)다. 법률 검토는 거치지 않았다.

| 안(결정 표 기호) | 내용 | 결과 |
|---|---|---|
| BE-11-22 A (채택) | 탈퇴 시 동의 기록 포함 즉시 전부 파기. 파기 사실은 일자·건수만 식별자 없이 기록 | 보존 법령이 없고 식별자 없는 기록은 동의 입증에 못 쓴다. 단점: 탈퇴 뒤 동의 분쟁 자료가 없고(법률 검토 전) 탈퇴자 동의 이력 집계가 사라진다 |
| BE-11-22 B (기각) | 동의 기록만 식별자를 지운 채 보관 | 식별자가 없어 동의 입증에 못 쓰고 보관 기간의 법적 근거를 찾지 못했으며, 인증 로그와 결합하면 재식별될 수 있다 |

- 번호 주의: 조사 보고의 "A(즉시 전부 파기)"는 BE-11-04 표와 이전 초안 7.2절의 "B"와 같은 내용이다. 이 문서는 결정 번호 BE-11-22 기준으로 쓴다.
- **파기 집계**: DB 트리거가 일자(UTC)와 파기 건수(대상 테이블별)만 `account.deletion_log`에 더한다. 사용자 식별자·이메일·프로필 값은 남기지 않는다(BE-15 redact 규칙).- 집계가 필요해지면 `(문서 종류, 버전)별 동의 건수` 카운터만 남기는 안을 나중에 더할 수 있다(조사 보고의 C안, 지금은 쓰지 않는다).
- 사용자 식별자의 해시를 남기는 안은 쓰지 않는다. 해시도 가명정보로 볼 수 있다(법률 검토 전 판단, 추측).
- **확인 필요**: Supabase Pro 자동 백업에 삭제한 행이 백업 보존 기간 동안 남는지(추정)와 그 기간, 처리방침의 "백업은 N일 뒤 순환 삭제" 문구. 조사에서 읽지 못했다.

### 7.3 조사 결과
> **반영(2026-11-18, 2026-11-19 정정)**: 인증 연동 조사 `data/mock/briefs/reports/auth-research.md`(로컬 전용)와 보관 기간 조사 `data/mock/briefs/reports/auth-research-retention.md`(로컬 전용)를 반영했다. 보관 조사는 7.2절의 BE-11-22 A로 이어졌다.

| 항목 | 조사 결과 | 출처(조사 보고가 적은 URL, 읽은 날짜 2026-11-18) |
|---|---|---|
| 동의 기록 보관 의무·기간 근거 | 보존을 요구하는 법령이 이 서비스에 해당하지 않음(의료법·전자상거래법, 해석). 7.2절 | `auth-research-retention.md` §0·§4(로컬 전용) |
| Admin API 사용자 삭제 | `auth.admin.deleteUser(id)`(기본 `shouldSoftDelete:false`)이면 `auth.users` 행이 지워지고 cascade로 세션·refresh token이 무효가 된다. **이미 발급된 access token은 `exp`까지 유효**하다. service_role 키가 필요하다 | supabase.com/docs/guides/auth/managing-user-data, supabase.com/docs/reference/javascript/auth-admin-deleteuser |
| 탈퇴 뒤 남은 access token | 이 설계에서는 `GET /me`의 `app_users` 생성이 `auth.users` FK에 막혀 실패하므로 401 `AUTH_INVALID`로 답한다(7.1절 보강, 추론). 다른 계정 API는 `app_users`가 없으면 401로 통일 | 위 + 이 문서 4.2절 |
| `auth.users` 트리거 방식의 위험 | 공식 문서가 "If the trigger fails, it could block signups"라고 경고한다(BE-11-10 A의 근거) | supabase.com/docs/guides/auth/managing-user-data |
| 공급자가 넘기는 항목 | Google scope `openid`·`userinfo.email`·`userinfo.profile`, Kakao 동의항목 `profile_nickname`·`profile_image`·`account_email`(이메일은 비즈 앱만). Kakao는 "Allow users without an email"로 **이메일 없이 가입** 가능 → `auth.users.email`이 비어 있을 수 있다. Naver(custom 공급자)는 `email_verified`를 주지 않아 이메일이 미검증으로 저장된다(추정) | auth-google·auth-kakao·custom-oauth-providers 문서, 조사 보고 §1.2·§2·§3.3 |
| 공급자 연결 끊기(unlink) | 미확인 | — |
| JWT | JWKS `…/auth/v1/.well-known/jwks.json`, ES256(권장)·RS256, 레거시 HS256이면 JWKS가 비어 검증 실패. `aud="authenticated"`, `iss=https://<ref>.supabase.co/auth/v1`, 헤더 `kid`. JWKS는 엣지 10분 캐시 | supabase.com/docs/guides/auth/jwts, …/signing-keys, …/jwt-fields |

이 설계는 **이메일에 기대지 않는다**(우리 테이블에 이메일 열이 없고 식별은 `auth.users.id`). 그래서 Kakao 이메일 없는 가입(BE-11-16 A)과 Naver Custom OIDC의 이메일 없음·미검증(BE-11-15 A)이 데이터 구조를 바꾸지 않는다.

## 8. 약관 문서 버전 관리
- **현재본**: `doc_type`별로 `status='published' AND effective_at <= now()`인 행 중 `version`이 가장 큰 것(뷰 `account.legal_current`, 부록 A).
- **예고본**: `status='published' AND effective_at > now()`이면 현재본이 아니고, `GET /legal/{doc_type}?include=upcoming`으로만 보인다(시행 전 고지용).
- **수정**: 게시본은 고치지 않는다. 새 버전 행을 `draft`로 넣고 확인한 뒤 `published`로 바꾼다. 이전 버전은 `retired`로 둘 수 있으나 지우지 않는다(동의 기록이 FK로 가리킨다).
- **재동의 필요 판정**(`GET /me`가 계산): 문서 종류 `t`에 대해, 사용자의 최신 `agree` 버전을 `v_u`, 현재본 버전을 `v_c`라 하면
  - 최신 기록이 `withdraw`이거나 기록 없음 → `needs_consent = true`
  - `v_u < v_c`이고 `(v_u, v_c]` 구간 버전 중 하나라도 `requires_reconsent = true` → `needs_reconsent = true`
  - 그 밖 → 둘 다 false(경미한 수정은 다시 묻지 않는다)
- 필수 문서(`required = true`)에 `needs_consent` 또는 `needs_reconsent`가 있으면 계정 API(동의 API·`GET /me`·`DELETE /me`·`GET /legal` 제외)는 403 `CONSENT_REQUIRED`/`RECONSENT_REQUIRED`를 돌려주고 프런트는 재동의 화면을 띄운다. 게스트 경로와 `/chat`은 막지 않는다.
- 이미 저장한 건강 정보는 `sensitive_consent` 재동의 대기 중에도 지우지 않되 새로 쓰지 못하게 한다(API 검사). 사용자가 재동의를 거부하면 철회로 처리한다(6.3절).

## 9. API 계약

### 9.1 공통(인증 헤더·게스트·오류)
- **인증**: `Authorization: Bearer <Supabase access token>`. 백엔드는 **PyJWT**(`PyJWKClient`, BE-11-17 A로 새 의존성 승인)로 `SUPABASE_JWKS_URL`의 공개 키(헤더 `kid`로 선택)를 받아 서명을 검증하고 알고리즘을 `ES256`·`RS256`으로 제한하며 `aud = "authenticated"`, `iss = {SUPABASE_URL}/auth/v1`, `exp`를 확인한다. 검증기 교체는 `backend/app/security/auth.py`의 `build_verifier` 한 곳이다(요청마다 네트워크 왕복이 없는 로컬 검증). JWKS는 10분보다 길게 캐시하지 않는다(7.3절 조사 결과). 프로젝트 서명 키가 레거시 HS256이면 JWKS가 비므로 S1 전에 사용자가 대시보드에서 확인한다. 서버 설정 필드는 이미 있다(`backend/app/config.py:62-66`). 검증 서버(Supabase)에 닿지 못하면 사용자 잘못이 아니므로 401로 로그아웃시키지 않고 503 `AUTH_UNAVAILABLE`로 답한다(BE-11-20 A).
- **게스트**: 토큰이 없으면 계정 API는 401 `AUTH_REQUIRED`. 헤더가 있는데 검증에 실패하면 게스트로 떨어뜨리지 않고 401 `AUTH_INVALID`. `/chat`·`/legal/*`는 토큰 없이 동작하며, `/chat`은 토큰이 붙어 와도 **읽지 않는다**(11장).
- **프런트 키**: 브라우저는 `NEXT_PUBLIC_SUPABASE_URL`·`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`(공개용 publishable 키, RLS 전제, `@supabase/ssr` 로그인용)만 쓸 수 있다. 이는 CLAUDE.md 3장 "`NEXT_PUBLIC_*`에 키 금지"의 **예외**다(BE-11-18 A, 2026-11-18). `SUPABASE_SECRET_KEY`는 서버 전용이며 `NEXT_PUBLIC_*`에 두지 않는다. 계정 데이터는 모두 FastAPI(`/api/*` rewrites)를 거친다.
- **오류 본문**: 기존 `/chat`과 같은 `{"code": "...", "fields": ["..."]}`다(BE-11-21 A, 구현 `backend/app/api/chat.py:43` `ErrorBody`: `code: str`, `fields: list[str] = []`). 이전 초안의 `{"error": {"code", "message"}}`는 쓰지 않는다. `message` 칸은 없다(문구 상수는 승인 전). 입력 값을 되돌려 주지 않는다(`request.py:8`의 원칙). `fields`에는 칸 이름 또는 문서 종류(`doc_type`)만 싣는다(예 `{"code": "CONSENT_REQUIRED", "fields": ["privacy_consent"]}`). 코드와 상태 번호는 아래 표다(구현 기준, 2026-11-19 정정. 근거 `data/mock/briefs/reports/n-be-e.md` §1.1).
- **로그**: 본문을 로그에 남기지 않는다. 접근 로그는 경로 템플릿(`/profiles/{profile_id}`)으로 남겨 ID도 남기지 않는다(BE-15 redact 규칙 재사용).
- **캐시**: 계정 응답은 `Cache-Control: no-store`. `/legal/*`는 `max-age=300`.
- **원격 적용 전 `/me`**: 원격 `account` 스키마를 적용하기 전에는 계정 저장소를 붙이지 않아, 토큰이 붙은 `/me`가 **501 `NOT_IMPLEMENTED`**로 답한다(S1 골격이 `user_id`만 200으로 돌려주던 것과 다르다). 적용 뒤 `PostgresAccountRepo.from_dsn(SUPABASE_DB_URL)` 한 줄로 연결한다(BE-11-23 A, 2026-11-19. 메모리 저장소로 임시 연결하지 않는다: 재시작 때 지워져 사용자가 저장됐다고 오해할 수 있다).

오류 코드 표(`ErrorBody{code, fields}`, 구현 `backend/app/api/account.py`):

| 상태 | code | fields | 언제 |
|---|---|---|---|
| 401 | `AUTH_REQUIRED` / `AUTH_INVALID` | [] | 토큰 없음(게스트) / 검증 실패·만료·계정 행 없음(첫 `/me` 전, 탈퇴 뒤 남은 토큰) |
| 403 | `CONSENT_REQUIRED` / `RECONSENT_REQUIRED` | 문서 종류 | 프로필 쓰기에 `terms`·`privacy_consent` 동의가 없음 / 재동의 대기 |
| 404 | `NOT_FOUND` | []·문서 종류 | 없는 프로필(남의 것 포함), 게시본 없는 문서 |
| 409 | `VERSION_MISMATCH`·`USE_ACCOUNT_DELETE`·`SELF_EXISTS`·`SELF_REQUIRED`·`SELF_FIXED` | 문서 종류·`relation` | 현재본이 아닌 버전, 약관 철회, 본인 2개, 본인 삭제, 본인↔가족 관계 변경 |
| 422 | `INVALID_REQUEST`·`PROFILE_LIMIT`·`MEDICATION_LIMIT`·`HEALTH_CONSENT_REQUIRED` | 칸 이름 | 형식 오류, 4번째 가족(본인 1 + 가족 3), 약 11개, 건강 동의 없이 임신 여부·복용 약 저장(BE-11-25 A, 2026-11-19. `PROFILE_LIMIT`은 이전 초안에서 409, 건강 동의 없는 저장은 403 `CONSENT_REQUIRED`) |
| 501 | `NOT_IMPLEMENTED` | [] | 검증기 또는 계정 저장소 미설정(원격 적용 전 `/me`, BE-11-23 A) |
| 502 | `AUTH_DELETE_FAILED` | [] | 탈퇴 3단계(Admin API) 실패(7.1절, 설계 코드) |
| 503 | `AUTH_UNAVAILABLE` / `ACCOUNT_UNAVAILABLE` | [] | JWKS 조회 실패, 검증 서버 장애(BE-11-20 A) / 저장소 장애 |

`/chat`의 422 처리는 기존 함수 그대로이며, 계정 경로의 422 `fields`는 계정 요청 모델의 칸 이름만 싣는다.

### 9.2 엔드포인트 표
| 메서드·경로 | 인증 | 요청 | 응답 | 스프린트 |
|---|---|---|---|---|
| `GET /legal` | 없음 | — | `LegalSummary[]`(문서 종류별 현재본 요약, 본문 제외). **미구현**(2026-11-19 구현 기준, 후속) | S1(설계) |
| `GET /legal/{doc_type}` | 없음(토큰을 읽지 않음) | `?version=n`(선택). `?include=upcoming`은 **미구현** | `LegalDocumentOut`(`Cache-Control: public, max-age=300`) | S1 |
| `GET /me` | 필요 | — | `MeResponse`(첫 호출이면 `app_users` 행 생성). 원격 적용 전에는 501(9.1절) | S1 |
| `PATCH /me/onboarding` | 필요 | `{"step": "profile_self"}` | `MeResponse`. **미구현**(건너뛰기로 `done`이 되는 경로, 후속) | S2 |
| `POST /consents` | 필요 | `ConsentRequest` | `MeResponse`(201) | S1 |
| `DELETE /me` | 필요 | — | 204(멱등) | S1 |
| `GET /profiles` | 필요(동의 검사 없이 계정만 확인, 쓰기만 403) | — | `ProfileOut[]` | S2 |
| `POST /profiles` | 필요 + `privacy_consent` | `ProfileCreate`(`medications` 포함 가능) | `ProfileOut`(201) | S2 |
| `PATCH /profiles/{profile_id}` | 필요 + `privacy_consent` | `ProfileUpdate`(`medications`를 보내면 목록 전체 교체) | `ProfileOut` | S2 |
| `DELETE /profiles/{profile_id}` | 필요 | — | 204(본인 프로필 삭제는 409 `SELF_REQUIRED`, 계정을 남기려면 본인 행은 수정만) | S2 |

복용 약을 한 건씩 넣고 빼는 대신 **목록 전체 교체**로 둔다. 프로필당 10개 이하라 비용이 작고, 화면 편집 결과를 그대로 보내면 되어 프런트·백엔드 모두 단순하다. 이전 초안의 `PUT /profiles/{profile_id}/medications`는 만들지 않고, `POST`·`PATCH /profiles`의 `medications`로 같은 일을 한다(2026-11-19 정정, 근거 `n-be-e.md` §4 7항). 복용 약 저장에는 `sensitive_consent`가 필요하다(없으면 422 `HEALTH_CONSENT_REQUIRED`, 9.1절).

### 9.3 응답 스키마
Pydantic 모델 초안이다. 칸 이름은 기존 응답 스키마처럼 snake_case(`request.py:5`). 구현(`backend/app/api/account.py`)의 클래스 이름은 `MeResponse`·`LegalDocumentOut`·`ProfileOut` 등이고 칸은 아래 초안에서 2026-11-19에 다음과 같이 달라졌다: `Me`에 `is_guest`·`onboarding_completed_at` 추가, `signup_provider`·`profiles` 칸 없음(프로필은 `GET /profiles`), `ConsentState`에 `required`, `LegalDocument`에 `requires_reconsent` 추가. 아래 코드 블록은 이 차이를 반영해 고쳤다(근거 `n-be-e.md` §4 8항·§5).

```python
class LegalDocument(BaseModel):
    doc_type: Literal["terms", "privacy_policy", "privacy_consent", "sensitive_consent"]
    version: int
    title: str
    body_md: str
    required: bool
    requires_reconsent: bool         # 2026-11-19 추가
    effective_at: datetime
    legal_review: Literal["not_reviewed", "reviewed"]  # not_reviewed면 프런트가 "초안·법률 검토 전" 표지
    body_sha256: str

class ConsentState(BaseModel):
    doc_type: Literal["terms", "privacy_consent", "sensitive_consent"]
    required: bool                   # 2026-11-19 추가
    agreed_version: int | None       # 최신 기록이 agree면 그 버전, 아니면 None
    acted_at: datetime | None
    current_version: int
    needs_consent: bool
    needs_reconsent: bool

class ConsentItem(_Strict):
    doc_type: Literal["terms", "privacy_consent", "sensitive_consent"]
    version: int                     # 현재본과 다르면 409 VERSION_MISMATCH(오래된 화면에서 동의 방지)
    action: Literal["agree", "withdraw"]

class ConsentRequest(_Strict):
    items: list[ConsentItem] = Field(min_length=1, max_length=3)
    channel: Literal["onboarding", "settings", "reconsent"]

class Medication(BaseModel):
    medication_id: UUID
    input_text: str
    item_seq: str | None             # ^\d{9}$
    confirmed_at: datetime | None

class Profile(BaseModel):
    profile_id: UUID
    relation: Literal["self", "child", "parent", "spouse", "other"]
    label: str | None
    age_band: AgeBand | None         # 4.8절 11개 값
    pregnancy_status: Literal["pregnant", "not_pregnant", "unknown"] | None
    medications: list[Medication]    # 건강 동의 없으면 항상 []
    sort_order: int

class ProfileCreate(_Strict):
    relation: ...; label: str | None = None; age_band: AgeBand | None = None
    pregnancy_status: ... | None = None   # 건강 동의 없이 값이 오면 422 HEALTH_CONSENT_REQUIRED(조용히 버리지 않음)
    medications: list[MedicationIn] | None = Field(default=None, max_length=10)  # 2026-11-19: 별도 PUT 대신 여기로. 건강 동의 없으면 422. PATCH에서 보내면 목록 전체 교체

class MedicationIn(_Strict):
    input_text: str = Field(min_length=1, max_length=100)
    item_seq: str | None = Field(default=None, pattern=r"^\d{9}$")  # 서버가 사전에서 존재를 다시 확인, 없으면 None으로 저장

# 2026-11-19: MedicationsPut은 만들지 않았다(9.2절). 이전 초안: items: list[MedicationIn] = Field(max_length=10)

class Me(BaseModel):
    user_id: UUID
    is_guest: bool                   # 2026-11-19 추가
    # signup_provider·profiles 칸은 없다(2026-11-19: 검증기가 sub만 돌려줘 provider를 채우지 않고, 프로필은 GET /profiles)
    onboarding_step: Literal["consent", "profile_self", "family", "done"]
    onboarding_completed_at: datetime | None   # 2026-11-19 추가
    consents: list[ConsentState]
    health_consent_active: bool
    profile_limit: int = 4
```

- `Me`에 이메일을 넣지 않는다. 화면에 로그인 계정을 보여 줘야 하면 프런트가 Supabase 세션에서 읽는다(서버 응답에 개인정보를 하나 덜 싣는다).
- `pregnancy_status`(또는 `medications`)가 건강 동의 없이 들어오면 **조용히 버리지 않고 422 `HEALTH_CONSENT_REQUIRED`**로 알린다(BE-11-25 A, 이전 초안은 403). 사용자가 저장됐다고 오해하지 않게 하기 위해서다.
- `item_seq` 재확인: 서버가 `drug_dict_entry`(DB, BE-06-24 B)에서 품목이 있는지 보고, 없으면 `item_seq=None`·`confirmed_at=None`으로 원문만 저장한다.

## 10. 온보딩 화면 흐름 ↔ 테이블
PJ2-PRD.md 15.3절 (10) S10의 단계에 맞춘다. 모달 코너 규칙은 PRD-13 그대로다.

| S10 단계 | 화면 | API | 테이블 쓰기 | `onboarding_step` |
|---|---|---|---|---|
| 0 | 게스트로 바로 질문 | 없음(`/chat`만) | **없음** | — |
| 1 | 로그인·가입(Google·Kakao, S2에 Naver, 이메일은 재검토 전까지 숨김, PRD-01-10 A 2026-11-19) | Supabase Auth SDK → `GET /me` | `auth.users`(Supabase), `app_users` 1행 | `consent` |
| 2 | 약관·동의(필수 2 + 선택 1, 처리방침 링크) | `GET /legal` → `GET /legal/{t}` → `POST /consents` | `user_consents` 2~3행 | `profile_self` |
| 3a | 본인 프로필(관계 `self` 고정, 연령대, 건강 동의 시 임신 여부·복용 약) | `POST /profiles`(`medications` 포함 가능, 2026-11-19: 별도 `PUT …/medications` 없음) | `profiles` 1행, `profile_medications` 0~10행 | `family` |
| 3b | (선택) 가족 추가 최대 3명 | `POST /profiles` 반복 | `profiles` ≤3행 | `done`(건너뛰기 포함) |
| 4 | 질문할 때 "누가 먹나요" | `GET /me`(캐시) | 없음 | — |
| 5 | 프로필 수정·삭제, 동의 철회, 계정 삭제 | `PATCH`·`DELETE /profiles/…`, `POST /consents`(withdraw), `DELETE /me` | 6.3·7장 | — |

- **`onboarding_step`은 코드가 현재 상태에서 다시 계산한다**(2026-11-19 정정, 근거 `n-be-e.md` §4 10항): 필수 동의가 없으면 `consent`, 본인 프로필이 없으면 `profile_self`, 가족이 3명이면 `done`(`onboarding_completed_at`을 채운다), 그 밖은 `family`. 이전 초안의 3b "건너뛰기 포함 `done`"은 `PATCH /me/onboarding`(미구현, 9.2절)으로만 일어난다.
- 2단계에서 필수 동의를 하지 않고 닫으면 계정은 남고 프로필은 저장되지 않는다(로그인 상태의 게스트와 같은 기능). 다음 로그인 때 `GET /me`의 `needs_consent`로 다시 2단계를 보인다.
- 어느 단계에서 닫아도 `onboarding_step`으로 이어서 시작한다.
- 응급 질문은 어느 단계에서도 막지 않는다(PJ2-PRD.md:78).

## 11. chat 연동
**원칙: `/chat`은 바꾸지 않는다.** 서버는 요청의 `context`만 쓰고 대화 상태를 저장·로그하지 않는다(PRD-07-01 A, `backend/app/api/request.py:3-4`). 프로필은 프런트가 `context`로 옮겨 싣는다.

| 프로필 값 | `context` 칸 | 변환 |
|---|---|---|
| `age_band` | `age: AgeInput` | 4.8절 표. NULL이면 `age=None`(대화 중 입력·되묻기) |
| `pregnancy_status` | `pregnant: bool \| None` | `pregnant`→true, `not_pregnant`→false, `unknown`·NULL→None |
| `profile_medications` | `confirmed_drugs` | **기본은 싣지 않는다.** 화면의 "내 복용 약과 함께 확인" 토글을 켠 질문에만 `{name: input_text, item_seq}`로 싣는다(BE-11-13 A) |

- 변환은 프런트 `buildChatRequest` 한 곳에서 한다(`request.py:5`의 기존 규칙과 같은 자리). `/chat`에 `profile_id`를 보내고 서버가 DB에서 읽는 방식은 쓰지 않는다. 그러면 `/chat`이 인증·DB 읽기를 갖게 되어 게스트 경로와 갈라지고, "요청에 실린 값만 쓴다"는 원칙이 깨진다.
- 프로필 값은 질문과 함께 외부 LLM으로 전송된다. 시작 화면 고지(`START_EXTERNAL_AI_NOTICE`)가 이미 "입력한 프로필"을 포함한다(PJ2-PRD.md:365).
- 평가에는 영향이 없다. 평가 러너는 `context`를 직접 만들고 계정 경로를 거치지 않는다(PJ2-RFP.md 9장 비교 조건 불변).

## 12. 마이그레이션·시드 적재 절차
1. **파일 만들기(코드 작업, 승인 불필요)**: 부록 A를 `backend/app/db/schema_account.sql`로, 부록 B를 `backend/app/db/seed_legal_v1.sql`로 옮긴다(파일 위치는 `backend/app/db` 규칙, CLAUDE.md 7장). 둘 다 멱등(`IF NOT EXISTS`, 시드는 `ON CONFLICT (doc_type, version) DO NOTHING`).
2. **로컬 시험**: 13장의 Postgres 시험이 통과.
3. **원격 적용 스크립트**: `backend/scripts/be11_account_migrate.py`(새 파일). 기존 `be16_remote_migrate.py`(`:1-12`)와 같은 형태로 `plan`(읽기 전용: 스키마 존재·적용할 SQL 출력) / `apply --yes` / `verify`(읽기 전용: 테이블·정책·enum·시드 4행 확인)를 둔다. `apply`는 `--yes`와 승인 flag `data/mock/review/be11-account.flag`가 **모두** 있어야 돈다. flag는 메인이 실행 직전에 만들고 직후 지운다(CLAUDE.md 7장 `backend/scripts/` 규칙).
4. **적용 범위 제한**: 이 스크립트는 `account` 스키마 안의 CREATE와 시드 INSERT만 한다. `public`의 판정·코퍼스·사전 테이블과 `auth` 스키마는 건드리지 않는다(DROP·TRUNCATE 금지).
5. **Data API 노출 확인**: 적용 뒤 Supabase 대시보드에서 노출 스키마에 `account`가 없는지 사용자가 확인한다(대시보드 설정이라 스크립트로 확인하지 못하면 체크리스트로).
6. **약관 개정(운영)**: 새 버전은 SQL 한 문장(`INSERT INTO account.legal_documents …`)으로 `draft`로 넣고 확인 뒤 `UPDATE … SET status='published'`. 이것도 원격 쓰기이므로 같은 승인 flag 규칙을 따른다.

## 13. 시험 계획
| 묶음 | 환경 | 확인할 것 |
|---|---|---|
| T1 RLS | 로컬 Postgres + `auth` 스텁(BE-11-14 A) | 계정 A·B를 만들고 B의 claims로 A의 `profiles`·`profile_medications`·`user_consents` SELECT 0행, UPDATE·DELETE 0행, A의 `user_id`로 INSERT 거부. anon은 `legal_documents` published만. `user_consents` UPDATE·DELETE 권한 오류 |
| T2 제약 | 같은 환경 | 프로필 5번째 INSERT → `PROFILE_LIMIT`, 가족 4번째 INSERT(본인 없이도) → `PROFILE_LIMIT`(가족 3행 + 전체 4행), 동시 INSERT 2건(advisory lock), `self` 2행 거부, 건강 동의 없이 `pregnancy_status`·약 INSERT 거부, 게시 문서 본문 UPDATE 거부, `item_seq` 형식 |
| T3 철회·탈퇴 | 같은 환경 | `sensitive_consent` 철회 → 임신 NULL·약 0행, `privacy_consent` 철회 → 프로필 0행·계정 유지, `terms` 철회 거부, `app_users` 삭제 → 프로필 0행·복용 약 0행·동의 기록 0행(BE-11-22 A) |
| T4 API | pytest + FastAPI TestClient, 저장소 계층은 가짜(DB 없음) | 토큰 없음 401, 서명 틀림·`aud` 틀림·만료 401, 남의 `profile_id` 404, 필수 동의 없는 프로필 저장 403, 건강 동의 없는 임신 여부·복용 약 저장 422 `HEALTH_CONSENT_REQUIRED`, 4번째 가족 422 `PROFILE_LIMIT`, `VERSION_MISMATCH` 409, 검증 서버 장애 503 `AUTH_UNAVAILABLE`, 원격 적용 전 `/me` 501, 오류 본문에 입력 값 없음, 로그에 본문·ID 없음 |
| T5 게스트·chat | 기존 `/chat` 시험에 추가 | 토큰 없이 `/chat` 정상, 토큰을 붙여도 계정 모듈을 부르지 않음(가짜 저장소 호출 0), `/chat` 처리 중 계정 테이블 쓰기 0 |
| T6 변환 | 프런트 단위 시험 | 4.8절 11개 값 → `AgeInput` 왕복, `pregnancy_status` 3값 + NULL, 약 토글 꺼짐이면 `confirmed_drugs=[]` |
| T7 원격 스모크 | 원격(승인 뒤) | `verify` 읽기 전용 점검 + 시험 계정 2개로 T1 축약판(쓰기이므로 flag 필요, 끝나면 두 계정 `DELETE /me`) |

pytest 실행은 공통 규칙의 메인 venv 명령을 쓴다. T1~T3은 Postgres가 없으면 skip하고 그 사실을 보고에 적는다. **이 Mac에는 로컬 Postgres가 설치되어 있지 않다**(메인 확인, Recap 40). 설치와 로컬 DSN 환경변수 이름은 사용자 확인 뒤 정하므로 그때까지 T1~T3은 skip이다.

## 14. 결정됨(2026-11-18)
이 장의 후보 BE-11-06~14·BE-11-04 후속은 2026-11-18 밤 늦게 사용자 "권장대로"로 모두 A(★)로 **완료**됐고, 같은 날 BE-11-15~22도 완료됐다. 결정의 **원본은 `tickets/backend/BE-11.md` §6 결정 현황**이며, 이 장은 그 결정 17건(BE-11-06~22)을 이 문서의 어느 절에 반영했는지 보여 준다.

### 14.1 확인된 문서 충돌
| 충돌 | 근거 | 제안 |
|---|---|---|
| 소셜 로그인 결정은 PRD-01에 **PRD-01-09**로 등록됐다(`PRD-01-06`은 2026-11-04 NFR-09·10 결정에 이미 쓰임). 이 문서를 처음 쓸 때는 요구서·PRD·CLAUDE.md가 "PRD-01-06 A′"로 적고 있었다 | `tickets/doc/PRD-01.md:83,86`, `P2-doc/PJ2-RFP.md:56,79,321,331,359,662`, `P2-doc/PJ2-PRD.md:133,157,374`, `CLAUDE.md:15` | **해결(2026-11-19 확인)**: 위 세 문서는 모두 PRD-01-09 A′로 정정이 끝났다(`PJ2-RFP.md:56,79,321,331,359,662`, `PJ2-PRD.md:133,157,374`, `CLAUDE.md:15`를 읽어 확인). 이 문서도 PRD-01-09로 쓴다 |
| 설계 문서 9.1절 오류 본문 `{"error": {"code","message"}}`는 "기존 `/chat` 오류 형식과 같게"라는 같은 문장과 충돌했다(실제 `/chat`은 `{code, fields}`) | `backend/app/api/chat.py:43` | 해결: BE-11-21 A로 `{code, fields}`, 9.1절을 정정했다 |
| BE-11 §2 완료 조건은 "설계 문서 뒤 상세 재작성" 상태이며 "본인 포함 여부는 설계 문서에서 확정"이 열려 있다 | `tickets/backend/BE-11.md:34,38` | 이 문서 4.3절: **본인 1 + 가족 3 = 계정당 4행**. 재작성 초안은 `eve-erd` 보고서에 있고 `schedule-writer`가 반영 |
| BE-11 하위 작업 일부가 옛 기준(무료 플랜 등)으로 남아 있을 수 있다(티켓 자체가 그렇게 밝힘) | `tickets/backend/BE-11.md:34` | 위와 같이 `schedule-writer`가 반영 |

### 14.2 결정 현황 표
상태는 모두 **완료**(2026-11-18 밤 늦게, 사용자 "권장대로", 선택 A). 질문·선택지는 이 문서가 올린 후보 원문을 줄여 옮겼다.

| 번호 | 질문 | 선택지 | 결과(A) | 반영한 곳 |
|---|---|---|---|---|
| BE-11-06 | 계정 테이블을 어디에 두고 RLS를 어떻게 적용할까? | A) `account` 스키마 + 요청마다 `SET LOCAL ROLE authenticated` / B) `public` + 소유 역할 `WHERE user_id` 코드 검사 | A. 단 `SET ROLE` 가능 여부를 읽기 전용으로 먼저 확인하고 안 되면 B | 2.3·5.2절 |
| BE-11-07 | 연령대 구간을 어떻게 나눌까? | A) 11구간(영아 3구간 포함) / B) 영아를 "1세 미만" 한 구간으로 줄인 9구간 | A. 확정 전 원격 `age_contra`의 (기준값·단위·조건) 분포를 읽기 전용으로 센다 | 4.8절 |
| BE-11-08 | 관계 값에 배우자·기타를 둘까? | A) `self`·`child`·`parent`·`spouse`·`other` / B) `self`·`child`·`parent`만 | A | 4.1절 |
| BE-11-09 | 임신 주차 열을 지금 만들까(FE-07-12 B "추후 확장")? | A) 지금 만들지 않는다 / B) NULL 허용 열을 미리 만든다 | A | 1.4절 |
| BE-11-10 | `app_users` 행을 언제 만들까? | A) 백엔드 첫 `GET /me`에서 / B) `auth.users` INSERT 트리거 | A | 4.2절 |
| BE-11-11 | 공급자가 넘기는 이름·사진(`raw_user_meta_data`)을 어떻게 할까? | A) 동의 항목 최소 요청 + S1 실측 뒤 처리방침에 적음 / B) 로그인 직후 서버가 메타데이터를 지움 | A. 필요하면 S1 실측 뒤 B를 더한다 | 4.7절 |
| BE-11-12 | 필수 개인정보 동의를 철회하면? | A) 프로필 전부 삭제, 계정 유지 / B) 계정 삭제까지 | A | 6.3절 |
| BE-11-13 | 프로필의 복용 약을 질문에 자동으로 실을까? | A) 기본 끔, 질문마다 토글 / B) 프로필을 고르면 항상 실음 | A | 11장 |
| BE-11-14 | RLS 시험(T1~T3)을 어디서 돌릴까? | A) 로컬 Postgres + `auth` 스키마 스텁 / B) Supabase CLI 로컬 스택(Docker) / C) 원격 시험 스키마 | A. 이 Mac에는 Postgres가 없어 설치와 로컬 DSN 변수 이름은 사용자 확인 필요(Recap 40) | 13장 |
| BE-11-15 | Naver 연동 방식은? | A) Supabase Custom OIDC(실패하면 OAuth2 + userinfo 어댑터) / B) 백엔드 직접 OAuth + Admin API 세션 / C) Naver 제외 | A | 4.7·7.3절 |
| BE-11-16 | Kakao에서 이메일을 받을까? | A) 받지 않음(닉네임만) / B) 비즈 앱으로 `account_email` 받음 | A | 4.7·7.3절 |
| BE-11-17 | 백엔드 JWT 검증 라이브러리는? | A) PyJWT(`PyJWKClient`, 새 의존성) / B) 의존성 없이 `httpx`로 `/auth/v1/user` 호출 | A | 9.1절 |
| BE-11-18 | `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`를 허용할까(CLAUDE.md 3장 예외)? | A) 허용 / B) 프런트는 Supabase를 직접 부르지 않고 백엔드가 OAuth 대행 | A. CLAUDE.md 3장에 예외를 추가함 | 9.1절 |
| BE-11-19 | Naver S2에 시간 상한을 둘까? | A) 반나절 상한, 넘으면 Naver 제외 / B) 상한 없이 끝까지 | A | 1.2·4.7절 |
| BE-11-20 | 토큰 검증 서버 장애 때 상태 코드는? | A) 503 `AUTH_UNAVAILABLE` / B) 401 `AUTH_INVALID`로 통일 | A | 9.1절 |
| BE-11-21 | 계정 API 오류 본문 형식은? | A) `/chat`과 같은 `{code, fields}` / B) `{"error": {"code","message"}}` | A | 9.1절 |
| BE-11-22 | 탈퇴 시 동의 기록도 즉시 파기할까(BE-11-04 후속)? | A) 즉시 전부 파기(파기 사실은 일자·건수만) / B) 동의 기록만 식별자 제거 후 보관 | A. 법률 검토 전 | 7장, 4.6절, 부록 A·B |

## 15. 코드 대조·출처
| 사실 | 출처 |
|---|---|
| `/chat`은 `context`(age·pregnant·confirmed_drugs) 한 묶음만 받고 저장·로그하지 않는다, `extra="forbid"` | `backend/app/api/request.py:3-4,25-26,59-64` |
| 나이 입력 형식 `AgeInput(lower, upper, unit ∈ 세·개월·주)`, 상한 150세 | `backend/app/api/request.py:20-21,29-42` |
| 약 이름 100자, 확인 약 10개, `item_seq` 9자리 숫자 | `backend/app/api/request.py:18-19,45-49` |
| Supabase 설정 필드(`supabase_db_url`·`supabase_url`·`supabase_publishable_key`·`supabase_secret_key`·`supabase_jwks_url`), 키는 `SecretStr` | `backend/app/config.py:4,62-66` |
| 사전 테이블은 RLS + REVOKE로 anon·authenticated를 막고, 소유 역할은 RLS를 우회한다는 가정 | `backend/app/db/schema_dict_pg.sql:3-8,10-23` |
| 연령금기 열 `age_value`·`age_unit`·`age_cond`·`age_days` | `backend/app/db/schema.sql:40-47` |
| 원격 이행 스크립트 형태(plan/apply --yes/verify, 금지 목록, DSN은 환경변수에서만) | `backend/scripts/be16_remote_migrate.py:1-12` |
| 저장 범위·RLS·약관 DB 관리·건강 정보 별도 동의·탈퇴 보관 조사 뒤 확정 | `P2-doc/PJ2-RFP.md:331`(작업 트리 수정본, 2026-11-18 읽음) |
| FR-09 가족 최대 3명·소셜 로그인 Google·Kakao S1, Naver S2 | `P2-doc/PJ2-RFP.md:56,321` |
| 축소 순서에서 프로필·온보딩 제외(AG-10-06 A) | `P2-doc/PJ2-RFP.md:85` |
| 법률 검토 보류 ①②⑤ | `P2-doc/PJ2-RFP.md:679`(2026-11-19 RFP 편집으로 이전 673에서 밀림) |
| S10 온보딩 단계, 동의를 받는 곳은 프로필 저장 하나, 외부 AI 고지는 동의 관문 아님 | `P2-doc/PJ2-PRD.md:362,370-378` |
| 외부 AI 고지 상수 `START_EXTERNAL_AI_NOTICE` | `P2-doc/PJ2-PRD.md:365`(상수 위치 `backend/app/agent/fixed_phrases.py:28`는 PRD 인용이며 이 작업에서 열지 않음) |
| 연령금기는 프로필 나이로, 특정 불가 시 나이별 원문 | `tickets/frontend/FE-07.md:117`(FE-07-18 A) |
| PRD-01-06 번호의 기존 결정(NFR-09·10), 소셜 로그인 결정 PRD-01-09. 요구서·PRD·CLAUDE.md의 표기는 PRD-01-09 A′로 정정 완료(2026-11-19 확인) | `tickets/doc/PRD-01.md:83,86`, `P2-doc/PJ2-RFP.md:56,362`, `P2-doc/PJ2-PRD.md:374`, `CLAUDE.md:15` |
| 인증 연동 조사(공급자·JWT·탈퇴·RLS 우회 위험 R4) | `data/mock/briefs/reports/auth-research.md`(로컬 전용, 2026-11-18, 외부 URL은 그 보고가 읽은 것이며 이 작업에서 다시 열지 않음) |
| 동의 기록 보관 조사(개인정보 보호법 제21조·표준지침 제10조·의료법·전자상거래법, 국내 헬스케어 앱 처리방침) | `data/mock/briefs/reports/auth-research-retention.md` §0·§4·§6(로컬 전용, 2026-11-18, 법률 자문 아님) |
| 오류 본문 `ErrorBody`(`code`, `fields`) | `backend/app/api/chat.py:43-47` |
| 검증 서버 장애 503 `AUTH_UNAVAILABLE`·검증 실패 401 `AUTH_INVALID` | `backend/app/security/auth.py:39-40,204-234` |
| 결정 BE-11-06~22(모두 A, 2026-11-18 밤 늦게) | `tickets/backend/BE-11.md` §6 결정 현황 |

**확인하지 못한 것**: Supabase에서 소유 역할의 `SET ROLE authenticated` 가능 여부와 `auth.uid()`의 claims 읽기 방식, Data API 노출 스키마 설정, 현재 프로젝트의 JWT 서명 키 종류, 공급자 연결 끊기, 공급자 메타데이터의 실제 저장 항목(S1 실측), 원격 `age_contra` 기준값 분포, Supabase 백업 보존 기간(삭제한 행이 백업에 남는 기간), 동의 분쟁 가능성에 대한 법적 판단(법률 검토 대상). 모두 이 문서에서 "확인 필요"·"가정"으로 표시했다.

## 부록 A. 마이그레이션 SQL 초안
> 초안이다. 원격 적용은 12장 절차와 승인 flag 뒤다. Postgres 15+ 가정(Supabase). `gen_random_uuid()`는 Postgres 13+ 기본 제공.

```sql
-- BE-11 계정·프로필·약관·동의 스키마 초안(P2-doc/PJ2-계정-프로필-데이터.md 4~6장).
-- 멱등: CREATE ... IF NOT EXISTS, enum은 DO 블록에서 존재를 확인한다. account 스키마 밖은 건드리지 않는다.

CREATE SCHEMA IF NOT EXISTS account;

-- 1. enum ---------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
                   WHERE n.nspname = 'account' AND t.typname = 'provider') THEN
        CREATE TYPE account.provider AS ENUM ('email', 'google', 'kakao', 'naver');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
                   WHERE n.nspname = 'account' AND t.typname = 'relation') THEN
        CREATE TYPE account.relation AS ENUM ('self', 'child', 'parent', 'spouse', 'other');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
                   WHERE n.nspname = 'account' AND t.typname = 'pregnancy_status') THEN
        CREATE TYPE account.pregnancy_status AS ENUM ('pregnant', 'not_pregnant', 'unknown');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
                   WHERE n.nspname = 'account' AND t.typname = 'age_band') THEN
        CREATE TYPE account.age_band AS ENUM (
            'm0_2', 'm3_5', 'm6_11', 'y1', 'y2', 'y3_5', 'y6_11', 'y12_14', 'y15_18', 'y19_64', 'y65_plus');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
                   WHERE n.nspname = 'account' AND t.typname = 'doc_type') THEN
        CREATE TYPE account.doc_type AS ENUM ('terms', 'privacy_policy', 'privacy_consent', 'sensitive_consent');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
                   WHERE n.nspname = 'account' AND t.typname = 'doc_status') THEN
        CREATE TYPE account.doc_status AS ENUM ('draft', 'published', 'retired');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
                   WHERE n.nspname = 'account' AND t.typname = 'consent_action') THEN
        CREATE TYPE account.consent_action AS ENUM ('agree', 'withdraw');
    END IF;
END
$$;

-- 문서 본문 해시(생성 열 body_sha256용). convert_to()가 STABLE이라 생성 열에 바로 쓰면 "generation expression is not immutable"로
-- CREATE TABLE이 실패한다(2026-11-19 로컬 PG 17 재현). 결과는 입력 문자열의 UTF-8 바이트에만 달려 IMMUTABLE로 선언한다.
-- plpgsql인 이유: SQL 함수는 인라인된 뒤 가변성 검사를 다시 받아(PG 16+) 같은 오류가 난다.
CREATE OR REPLACE FUNCTION account.utf8_sha256_hex(p_body text) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE SET search_path = '' AS $$
BEGIN
    RETURN pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p_body, 'UTF8')), 'hex');
END
$$;

-- 2. 테이블 -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account.app_users (
    user_id                 uuid PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
    signup_provider         account.provider,  -- NULL 허용(2026-11-19 정정: 검증기가 sub만 돌려줘 아직 채우지 않는다)
    onboarding_step         text NOT NULL DEFAULT 'consent'
                            CHECK (onboarding_step IN ('consent', 'profile_self', 'family', 'done')),
    onboarding_completed_at timestamptz,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS account.profiles (
    profile_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          uuid NOT NULL REFERENCES account.app_users (user_id) ON DELETE CASCADE,
    relation         account.relation NOT NULL,
    label            text CHECK (label IS NULL OR char_length(btrim(label)) BETWEEN 1 AND 20),
    age_band         account.age_band,
    pregnancy_status account.pregnancy_status,
    sort_order       smallint NOT NULL DEFAULT 0 CHECK (sort_order BETWEEN 0 AND 3),
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_profiles_user ON account.profiles (user_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_profiles_self ON account.profiles (user_id) WHERE relation = 'self';

CREATE TABLE IF NOT EXISTS account.profile_medications (
    medication_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id    uuid NOT NULL REFERENCES account.profiles (profile_id) ON DELETE CASCADE,
    user_id       uuid NOT NULL REFERENCES account.app_users (user_id) ON DELETE CASCADE,
    input_text    text NOT NULL CHECK (char_length(btrim(input_text)) BETWEEN 1 AND 100),
    item_seq      char(9) CHECK (item_seq IS NULL OR item_seq ~ '^[0-9]{9}$'),
    confirmed_at  timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CHECK (item_seq IS NULL OR confirmed_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_medications_profile ON account.profile_medications (profile_id);
CREATE INDEX IF NOT EXISTS idx_medications_user ON account.profile_medications (user_id);

CREATE TABLE IF NOT EXISTS account.legal_documents (
    document_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_type           account.doc_type NOT NULL,
    version            integer NOT NULL CHECK (version >= 1),
    title              text NOT NULL,
    body_md            text NOT NULL,
    required           boolean NOT NULL,
    requires_reconsent boolean NOT NULL DEFAULT false,
    status             account.doc_status NOT NULL DEFAULT 'draft',
    effective_at       timestamptz NOT NULL,
    legal_review       text NOT NULL DEFAULT 'not_reviewed' CHECK (legal_review IN ('not_reviewed', 'reviewed')),
    body_sha256        text GENERATED ALWAYS AS (account.utf8_sha256_hex(body_md)) STORED,  -- IMMUTABLE 함수(2절 앞, 2026-11-19 정정)
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (doc_type, version)
);
CREATE INDEX IF NOT EXISTS idx_legal_current ON account.legal_documents (doc_type, status, effective_at DESC);

CREATE TABLE IF NOT EXISTS account.user_consents (
    consent_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id       uuid NOT NULL REFERENCES account.app_users (user_id) ON DELETE CASCADE,  -- 탈퇴 때 동의 기록도 함께 삭제(BE-11-22 A)
    doc_type      account.doc_type NOT NULL,
    doc_version   integer NOT NULL,
    action        account.consent_action NOT NULL,
    channel       text NOT NULL CHECK (channel IN ('onboarding', 'settings', 'reconsent')),
    acted_at      timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (doc_type, doc_version) REFERENCES account.legal_documents (doc_type, version),
    CHECK (doc_type <> 'privacy_policy')
);
CREATE INDEX IF NOT EXISTS idx_consents_user ON account.user_consents (user_id, doc_type, acted_at DESC);

-- 파기 집계: 일자(UTC)별 건수만. 사용자 식별자·시각 열이 없다(BE-11-22 A, 2026-11-19 추가). 소유 역할만 읽고 쓴다
CREATE TABLE IF NOT EXISTS account.deletion_log (
    deleted_on  date PRIMARY KEY,
    accounts    integer NOT NULL DEFAULT 0 CHECK (accounts >= 0),
    profiles    integer NOT NULL DEFAULT 0 CHECK (profiles >= 0),
    medications integer NOT NULL DEFAULT 0 CHECK (medications >= 0),
    consents    integer NOT NULL DEFAULT 0 CHECK (consents >= 0)
);

-- 3. 뷰 -----------------------------------------------------------------
CREATE OR REPLACE VIEW account.legal_current WITH (security_invoker = true) AS
SELECT DISTINCT ON (doc_type) *
FROM account.legal_documents
WHERE status = 'published' AND effective_at <= now()
ORDER BY doc_type, version DESC;

CREATE OR REPLACE VIEW account.user_consent_current WITH (security_invoker = true) AS
SELECT DISTINCT ON (user_id, doc_type) user_id, doc_type, doc_version, action, channel, acted_at
FROM account.user_consents
ORDER BY user_id, doc_type, acted_at DESC, consent_id DESC;

-- 4. 함수·트리거 --------------------------------------------------------
CREATE OR REPLACE FUNCTION account.touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION account.has_active_consent(p_user uuid, p_type account.doc_type)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT coalesce((SELECT action = 'agree' FROM account.user_consent_current
                     WHERE user_id = p_user AND doc_type = p_type), false);
$$;

-- 계정당 본인 1 + 가족 3(BE-11-01 B). 가족 3행 + 전체 4행 모두 막는다(2026-11-19 정정: 본인 없이 가족 4명 방지).
-- 같은 계정의 동시 삽입은 advisory lock으로 줄 세운다
CREATE OR REPLACE FUNCTION account.enforce_profile_limit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.relation = OLD.relation THEN
        RETURN NEW;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.user_id::text, 0));
    IF NEW.relation <> 'self' AND (SELECT count(*) FROM account.profiles
                                   WHERE user_id = NEW.user_id AND relation <> 'self'
                                     AND profile_id <> NEW.profile_id) >= 3 THEN
        RAISE EXCEPTION 'PROFILE_LIMIT' USING ERRCODE = 'P0001';
    END IF;
    IF (SELECT count(*) FROM account.profiles WHERE user_id = NEW.user_id AND profile_id <> NEW.profile_id) >= 4 THEN
        RAISE EXCEPTION 'PROFILE_LIMIT' USING ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
END
$$;

-- 건강 정보는 sensitive_consent가 있을 때만(BE-11-03 A)
CREATE OR REPLACE FUNCTION account.enforce_health_consent_profile() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.pregnancy_status IS NOT NULL
       AND (TG_OP = 'INSERT' OR NEW.pregnancy_status IS DISTINCT FROM OLD.pregnancy_status)
       AND NOT account.has_active_consent(NEW.user_id, 'sensitive_consent') THEN
        RAISE EXCEPTION 'CONSENT_REQUIRED:sensitive_consent' USING ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION account.enforce_health_consent_medication() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.user_id IS DISTINCT FROM (SELECT user_id FROM account.profiles WHERE profile_id = NEW.profile_id) THEN
        RAISE EXCEPTION 'PROFILE_OWNER_MISMATCH' USING ERRCODE = 'P0001';
    END IF;
    IF NOT account.has_active_consent(NEW.user_id, 'sensitive_consent') THEN
        RAISE EXCEPTION 'CONSENT_REQUIRED:sensitive_consent' USING ERRCODE = 'P0001';
    END IF;
    IF TG_OP = 'INSERT'
       AND (SELECT count(*) FROM account.profile_medications WHERE profile_id = NEW.profile_id) >= 10 THEN
        RAISE EXCEPTION 'MEDICATION_LIMIT' USING ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
END
$$;

-- 게시된 문서는 본문 불변(8장)
CREATE OR REPLACE FUNCTION account.freeze_published_document() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'draft' AND (NEW.title, NEW.body_md, NEW.version, NEW.doc_type)
                                 IS DISTINCT FROM (OLD.title, OLD.body_md, OLD.version, OLD.doc_type) THEN
        RAISE EXCEPTION 'DOCUMENT_FROZEN' USING ERRCODE = 'P0001';
    END IF;
    RETURN NEW;
END
$$;

-- 철회 시 즉시 삭제(6.3절)
CREATE OR REPLACE FUNCTION account.on_consent_withdraw() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.action <> 'withdraw' THEN
        RETURN NEW;
    END IF;
    IF NEW.doc_type = 'terms' THEN
        RAISE EXCEPTION 'USE_ACCOUNT_DELETE' USING ERRCODE = 'P0001';
    ELSIF NEW.doc_type = 'sensitive_consent' THEN
        UPDATE account.profiles SET pregnancy_status = NULL WHERE user_id = NEW.user_id;
        DELETE FROM account.profile_medications WHERE user_id = NEW.user_id;
    ELSIF NEW.doc_type = 'privacy_consent' THEN
        DELETE FROM account.profiles WHERE user_id = NEW.user_id;
    END IF;
    RETURN NEW;
END
$$;

-- 탈퇴(app_users 삭제) 때 동의 기록도 user_consents의 ON DELETE CASCADE로 함께 지워진다(7.1·7.2절, BE-11-22 A).
-- 이전 초안의 익명화 함수·트리거(anonymize_consents)와 anonymized_at 열은 삭제했다.

-- 파기 집계(BE-11-22 A): app_users 행이 지워질 때(본인 탈퇴든 auth.users 삭제 CASCADE든) 일자별 건수만 더한다.
-- deletion_log에는 authenticated 권한이 없으므로 SECURITY DEFINER로 돈다. search_path를 비워 이름 가로채기를 막는다
CREATE OR REPLACE FUNCTION account.log_account_deletion() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    v_profiles integer;
    v_medications integer;
    v_consents integer;
BEGIN
    SELECT count(*) INTO v_profiles FROM account.profiles WHERE user_id = OLD.user_id;
    SELECT count(*) INTO v_medications FROM account.profile_medications WHERE user_id = OLD.user_id;
    SELECT count(*) INTO v_consents FROM account.user_consents WHERE user_id = OLD.user_id;
    INSERT INTO account.deletion_log AS l (deleted_on, accounts, profiles, medications, consents)
    VALUES ((now() AT TIME ZONE 'UTC')::date, 1, v_profiles, v_medications, v_consents)
    ON CONFLICT (deleted_on) DO UPDATE
        SET accounts = l.accounts + 1,
            profiles = l.profiles + EXCLUDED.profiles,
            medications = l.medications + EXCLUDED.medications,
            consents = l.consents + EXCLUDED.consents;
    RETURN OLD;
END
$$;

-- 본인 탈퇴(DELETE /me): auth.uid()의 계정 행을 지운다 → 프로필·약·동의 기록 CASCADE, 집계는 위 트리거.
-- authenticated에 app_users DELETE 권한을 주지 않고 이 함수만 실행하게 한다. 없는 계정이면 0건(멱등)
CREATE OR REPLACE FUNCTION account.delete_my_account()
RETURNS TABLE (n_profiles integer, n_medications integer, n_consents integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    v_uid uuid := auth.uid();
BEGIN
    IF v_uid IS NULL THEN
        RAISE EXCEPTION 'AUTH_REQUIRED' USING ERRCODE = 'P0001';
    END IF;
    SELECT count(*) INTO n_profiles FROM account.profiles WHERE user_id = v_uid;
    SELECT count(*) INTO n_medications FROM account.profile_medications WHERE user_id = v_uid;
    SELECT count(*) INTO n_consents FROM account.user_consents WHERE user_id = v_uid;
    DELETE FROM account.app_users WHERE user_id = v_uid;
    RETURN NEXT;
END
$$;

DROP TRIGGER IF EXISTS trg_app_users_touch ON account.app_users;
CREATE TRIGGER trg_app_users_touch BEFORE UPDATE ON account.app_users
    FOR EACH ROW EXECUTE FUNCTION account.touch_updated_at();
DROP TRIGGER IF EXISTS trg_app_users_anonymize ON account.app_users;  -- 이전 초안에서 만든 트리거가 있으면 지운다(멱등)
DROP TRIGGER IF EXISTS trg_app_users_deletion_log ON account.app_users;
CREATE TRIGGER trg_app_users_deletion_log BEFORE DELETE ON account.app_users
    FOR EACH ROW EXECUTE FUNCTION account.log_account_deletion();

DROP TRIGGER IF EXISTS trg_profiles_touch ON account.profiles;
CREATE TRIGGER trg_profiles_touch BEFORE UPDATE ON account.profiles
    FOR EACH ROW EXECUTE FUNCTION account.touch_updated_at();
DROP TRIGGER IF EXISTS trg_profiles_limit ON account.profiles;
CREATE TRIGGER trg_profiles_limit BEFORE INSERT OR UPDATE OF relation ON account.profiles
    FOR EACH ROW EXECUTE FUNCTION account.enforce_profile_limit();
DROP TRIGGER IF EXISTS trg_profiles_health ON account.profiles;
CREATE TRIGGER trg_profiles_health BEFORE INSERT OR UPDATE ON account.profiles
    FOR EACH ROW EXECUTE FUNCTION account.enforce_health_consent_profile();

DROP TRIGGER IF EXISTS trg_medications_health ON account.profile_medications;
CREATE TRIGGER trg_medications_health BEFORE INSERT OR UPDATE ON account.profile_medications
    FOR EACH ROW EXECUTE FUNCTION account.enforce_health_consent_medication();

DROP TRIGGER IF EXISTS trg_legal_freeze ON account.legal_documents;
CREATE TRIGGER trg_legal_freeze BEFORE UPDATE ON account.legal_documents
    FOR EACH ROW EXECUTE FUNCTION account.freeze_published_document();

DROP TRIGGER IF EXISTS trg_consent_withdraw ON account.user_consents;
CREATE TRIGGER trg_consent_withdraw AFTER INSERT ON account.user_consents
    FOR EACH ROW EXECUTE FUNCTION account.on_consent_withdraw();

-- 5. RLS·권한 -----------------------------------------------------------
ALTER TABLE account.app_users           ENABLE ROW LEVEL SECURITY;
ALTER TABLE account.profiles            ENABLE ROW LEVEL SECURITY;
ALTER TABLE account.profile_medications ENABLE ROW LEVEL SECURITY;
ALTER TABLE account.legal_documents     ENABLE ROW LEVEL SECURITY;
ALTER TABLE account.user_consents       ENABLE ROW LEVEL SECURITY;
ALTER TABLE account.deletion_log        ENABLE ROW LEVEL SECURITY;  -- 정책 없음 = anon·authenticated 0행

DROP POLICY IF EXISTS legal_read ON account.legal_documents;
CREATE POLICY legal_read ON account.legal_documents FOR SELECT TO anon, authenticated
    USING (status = 'published');

DROP POLICY IF EXISTS app_users_own ON account.app_users;
CREATE POLICY app_users_own ON account.app_users FOR SELECT TO authenticated
    USING (user_id = (SELECT auth.uid()));
DROP POLICY IF EXISTS app_users_insert ON account.app_users;
CREATE POLICY app_users_insert ON account.app_users FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT auth.uid()));
DROP POLICY IF EXISTS app_users_update ON account.app_users;
CREATE POLICY app_users_update ON account.app_users FOR UPDATE TO authenticated
    USING (user_id = (SELECT auth.uid())) WITH CHECK (user_id = (SELECT auth.uid()));

DROP POLICY IF EXISTS profiles_own ON account.profiles;
CREATE POLICY profiles_own ON account.profiles FOR ALL TO authenticated
    USING (user_id = (SELECT auth.uid())) WITH CHECK (user_id = (SELECT auth.uid()));

DROP POLICY IF EXISTS medications_own ON account.profile_medications;
CREATE POLICY medications_own ON account.profile_medications FOR ALL TO authenticated
    USING (user_id = (SELECT auth.uid())) WITH CHECK (user_id = (SELECT auth.uid()));

DROP POLICY IF EXISTS consents_read ON account.user_consents;
CREATE POLICY consents_read ON account.user_consents FOR SELECT TO authenticated
    USING (user_id = (SELECT auth.uid()));
DROP POLICY IF EXISTS consents_insert ON account.user_consents;
CREATE POLICY consents_insert ON account.user_consents FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT auth.uid()));

-- 함수 실행 권한: 기본 PUBLIC 실행을 거두고 필요한 역할에만 준다
REVOKE ALL ON FUNCTION account.delete_my_account() FROM PUBLIC;
REVOKE ALL ON FUNCTION account.log_account_deletion() FROM PUBLIC;

-- 권한: anon·authenticated가 있는 환경에서만(로컬 Postgres 대비, schema_dict_pg.sql과 같은 방식)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        GRANT USAGE ON SCHEMA account TO authenticated;
        GRANT SELECT ON account.legal_documents, account.legal_current, account.user_consent_current TO authenticated;
        GRANT SELECT, INSERT ON account.app_users TO authenticated;
        GRANT UPDATE (onboarding_step, onboarding_completed_at) ON account.app_users TO authenticated;
        REVOKE DELETE ON account.app_users FROM authenticated;
        GRANT SELECT, INSERT, UPDATE, DELETE ON account.profiles, account.profile_medications TO authenticated;
        GRANT SELECT, INSERT ON account.user_consents TO authenticated;
        REVOKE UPDATE, DELETE ON account.user_consents FROM authenticated;
        REVOKE ALL ON account.deletion_log FROM authenticated;
        GRANT EXECUTE ON FUNCTION account.delete_my_account() TO authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        GRANT USAGE ON SCHEMA account TO anon;
        GRANT SELECT ON account.legal_documents, account.legal_current TO anon;
        REVOKE ALL ON account.deletion_log FROM anon;
    END IF;
END
$$;
```

메모:
- `has_active_consent`는 버전과 관계없이 최신 기록이 `agree`인지만 본다. 현재본 재동의 여부는 API가 8장 규칙으로 판정한다(DB 트리거는 최소 방어선).
- `on_consent_withdraw`는 호출자 권한으로 돈다. 철회 행의 `user_id`는 RLS WITH CHECK로 본인이므로 지우는 행도 본인 것뿐이다.
- 탈퇴 때 동의 기록 삭제는 `user_consents.user_id`의 ON DELETE CASCADE가 한다(BE-11-22 A). `authenticated`에는 `user_consents` UPDATE·DELETE 권한이 없고 `app_users` DELETE 권한도 주지 않았으므로 탈퇴 삭제는 서버(소유 역할) 경로에서만 일어난다. 위의 `DROP TRIGGER … trg_app_users_anonymize`는 이전 초안을 적용한 환경이 있을 때만 의미가 있다(원격 적용은 0이라 지금은 no-op).
- `auth.uid()`·`auth.users`는 Supabase가 제공한다. 로컬 시험(BE-11-14 A)에서는 스텁으로 같은 이름을 만든다.

## 부록 B. 약관·동의 문서 시드 초안
> 모든 본문은 **"초안·법률 검토 전"**이다(PJ2-RFP.md:679 ①②). `legal_review='not_reviewed'`로 넣고 프런트는 이 값으로 표지를 그린다. 보관 기간 등 확정되지 않은 값은 본문에 "확정 전"으로 쓰고 숫자를 지어내지 않는다. 시행 시각은 원격 적용 날짜로 바꾼다(아래 `{{EFFECTIVE_AT}}` 자리표시자. 이전 초안의 `:effective_at`을 2026-11-19에 바꿨다).

```sql
INSERT INTO account.legal_documents (doc_type, version, title, body_md, required, status, effective_at)
VALUES
('terms', 1, 'Can I PPiyak 이용약관(초안)', $md$
> 초안·법률 검토 전입니다. 실제 공개·상용 전에 법률 검토가 필요합니다.

## 1. 서비스의 성격
Can I PPiyak은 공공데이터(한국의약품안전관리원 DUR 자료, 식품의약품안전처 공개 API 등)를 바탕으로 의약품 정보와 병용·연령·임부 금기 정보를 안내하는 정보 제공 서비스입니다. 진단·처방·복용량 결정을 하지 않으며 의료적 판단을 대신하지 않습니다.

## 2. 이용 방법
로그인하지 않고도 모든 핵심 기능을 쓸 수 있습니다. 계정은 프로필을 저장해 다시 입력하지 않으려는 분을 위한 선택 기능입니다.

## 3. 주의
금기 목록에 없다는 것은 안전하다는 뜻이 아닙니다. 요양기관의 DUR 점검을 대체하지 않습니다. 복용 전에는 가까운 약국·약사에게 확인하세요. 응급 상황에서는 119에 연락하세요.

## 4. 계정 해지
설정에서 언제든 계정을 삭제할 수 있으며, 삭제하면 저장한 프로필·복용 약 정보와 동의 기록이 즉시 지워집니다.
$md$, true, 'published', {{EFFECTIVE_AT}}),

('privacy_policy', 1, '개인정보 처리방침(초안)', $md$
> 초안·법률 검토 전입니다. 실제 공개·상용 전에 법률 검토가 필요합니다.

## 1. 처리하는 항목
- 로그인 정보: 소셜 로그인 공급자(Google·Kakao·Naver)의 계정 식별자(PRD-01-10 A, 2026-11-19: 이메일 가입은 메일 인증을 갖춘 뒤 재검토). 공급자가 넘기는 그 밖의 항목은 확인 후 이 문서에 적습니다(확정 전).
- 프로필(동의한 경우): 관계, 표시 이름(선택), 연령대.
- 건강 정보(별도 동의한 경우): 임신 여부, 복용 중인 약.
- 동의 기록: 동의·철회한 문서와 버전, 시각(계정을 삭제하면 함께 지웁니다).

## 2. 처리하지 않는 항목
질문과 대화 내용은 저장하지 않습니다. 로그인하지 않고 쓰면 아무것도 저장하지 않습니다. 약봉투 사진과 음성은 저장하지 않습니다.

## 3. 외부 AI 전송
질문과 질문할 때 선택한 프로필 값은 답변을 만들기 위해 외부 AI 서비스(OpenAI)로 전송되며, 제공자의 정책에 따라 일정 기간 보관될 수 있습니다.

## 4. 보관과 파기
프로필과 복용 약 정보는 삭제하거나 동의를 철회하거나 계정을 삭제하면 즉시 지웁니다. 계정을 삭제하면 동의 기록도 함께 즉시 지우며, 지운 사실은 일자와 건수만 개인을 알아볼 수 없게 기록합니다. 백업에 남는 기간은 확인 후 이 문서에 적습니다(확정 전).

## 5. 저장 위치와 접근
데이터는 Supabase(Postgres)에 저장되며 본인 계정만 읽고 수정·삭제할 수 있도록 행 수준 보안을 적용합니다.
$md$, false, 'published', {{EFFECTIVE_AT}}),

('privacy_consent', 1, '개인정보 수집·이용 동의(필수, 초안)', $md$
> 초안·법률 검토 전입니다.

- 수집 항목: 관계, 표시 이름(선택), 연령대
- 목적: 질문할 때 대상(누가 먹나요)을 고르면 연령대를 자동으로 채워 연령금기를 확인하기 위함
- 보유 기간: 프로필 삭제·동의 철회·계정 삭제 시까지(즉시 삭제)
- 동의하지 않아도 로그인하지 않은 상태와 같은 방식으로 모든 핵심 기능을 쓸 수 있습니다(프로필 저장만 할 수 없습니다).
$md$, true, 'published', {{EFFECTIVE_AT}}),

('sensitive_consent', 1, '건강 정보(민감정보) 처리 동의(선택, 초안)', $md$
> 초안·법률 검토 전입니다. 건강 관련 정보에 별도 동의가 법적으로 필요한지는 아직 검토하지 않았으며, 보수적으로 별도 선택 동의를 받습니다.

- 수집 항목: 임신 여부, 복용 중인 약(입력한 이름과 확인된 경우 품목기준코드)
- 목적: 임부금기와 함께 먹는 약의 병용금기를 확인할 때 다시 입력하지 않게 하기 위함
- 보유 기간: 해당 정보 삭제·동의 철회·계정 삭제 시까지(즉시 삭제)
- 선택 동의입니다. 동의하지 않으면 이 정보는 저장되지 않으며, 질문할 때 직접 입력해 같은 확인을 할 수 있습니다.
$md$, false, 'published', {{EFFECTIVE_AT}})
ON CONFLICT (doc_type, version) DO NOTHING;
```

- 본문 문장은 기존 승인 문구(외부 AI 고지 PRD-07-02 A, "금기 목록에 없다는 것이 안전하다는 뜻이 아님" 등 PJ2-RFP.md 7장 고지)를 풀어 쓴 초안이며, 화면 고정 문구 상수를 대체하지 않는다. 문구 확정은 사용자 승인 대상이다.
- `{{EFFECTIVE_AT}}`는 `schema_corpus.sql`의 `{{DIM}}` 방식처럼 적용 코드(`seed_sql(datetime_tz)`)가 시행 시각으로 채우는 자리표시자다(초안에서 날짜를 정하지 않음, `backend/app/db/seed_legal_v1.sql`).
