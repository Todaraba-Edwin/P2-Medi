# PJ2-약관-초안-검토 · Can I PPiyak (코드명 MediAgent)

**PRD (Product Requirements Document): 제품 요구사항 문서 — PRD-17 산출 문서(약관·개인정보·민감정보 문서 초안 검토 현황)**

> **법률 자문이 아니다.** 이 문서는 개발자가 정리한 초안 검토 현황이며 법률 검토를 거치지 않았다. 법률 검토는 [schedule.md Recap 9](../schedule.md#사용자-작업-순서우선순위)(보류)와 같고 `legal_review`는 계속 `not_reviewed`다. 문서의 "해당 여부"·"필요 여부" 표현은 모두 해석이다.
> 기준일: 2026-11-22(2026-11-20 판을 처리방침 v3·v4, 이용약관 v3, 원격 게시 결과로 현행화). 근거 티켓: [PRD-17](../tickets/doc/PRD-17.md)(§2 완료 조건·§3 하위 작업·§4 결정 현황). 결정의 원본은 티켓 `결정 현황` 표이고 이 문서는 요약만 한다.
> 원천: 시드 `backend/app/db/seed_legal_v2.sql`·`seed_legal_v3.sql`·`seed_legal_v4.sql`·`seed_legal_age14.sql`(현재 원문), 시험 `backend/tests/test_prd17_no_access_log.py`, 프런트 `frontend/src/features/account/Markdown.tsx`, 로컬 전용 보고 `data/mock/briefs/reports/legal-review.md`·`recap45.md`·`prd17-sex.md`·`upstage-legal.md`·`upstage-live-cost.md`·`seed-v4-upstage.md`·`upstage-kr-region.md`(저장소에는 없다), `schedule-done.md` 종결 기록.

## Index
- [1. 목적과 범위](#1-목적과-범위)
- [2. 문서 4종과 age_14 현황](#2-문서-4종과-age_14-현황)
- [3. 결정 요약 (PRD-17-01~20)](#3-결정-요약-prd-17-0120)
- [4. 사실 값 현황](#4-사실-값-현황)
  - [4.1 채운 것](#41-채운-것)
  - [4.2 남은 것](#42-남은-것)
- [5. 축소 범위와 사진 문구](#5-축소-범위와-사진-문구)
- [6. 남은 일](#6-남은-일)
- [7. 출처](#7-출처)

## 1. 목적과 범위
- 목적: 이용약관·개인정보 처리방침·개인정보 수집·이용 동의·민감정보(건강 정보) 처리 동의를 DB(Supabase `account.legal_documents`)에서 관리하기 전에, 지금 문서에 무엇이 들어 있고 무엇이 채워졌고 무엇이 비어 있는지를 한 곳에서 확인한다(PRD-17 §1.1, BE-11-02 A).
- 범위: 개발 단계 반영(초안 검토 → v2 본문 → 시드 SQL → 원격 적용 → 프런트 표시)까지. 서비스는 상용이 아니라 포트폴리오이며 진단·처방·복용량 결정을 하지 않는다.
- 범위 밖: 법률 검토(Recap 9 보류), 법적 필수 기재 여부의 단정, 개인정보 처리방침 작성지침 PDF·개인정보보호위원회 해설서 대조(열지 못함, 아래 7장).
- 모든 본문에는 첫 줄 "초안·법률 검토 전" 안내가 있고 프런트 `LEGAL_NOT_REVIEWED_TAG`(`"초안·법률 검토 전"`)가 그대로 남는다.

## 2. 문서 4종과 age_14 현황
기준: 시드 파일 읽음(2026-11-22)과 티켓 PRD-17의 원격 게시 기록(`verify` 결과, §2·§3 ⑯, 이 문서는 원격 DB를 직접 읽지 않았다). 게시본은 트리거 `freeze_published_document`가 제목·본문·버전·종류 수정을 막으므로 고칠 때는 새 버전 행을 넣는다.

| 문서 종류 | 버전 | 필수·선택 | 재동의(`requires_reconsent`) | 게시 상태 |
|---|---|---|---|---|
| `terms` 이용약관 | v1(`seed_legal_v1.sql`), v2(`seed_legal_v2.sql`), v3(`seed_legal_v3.sql`) | 필수 | v2 false, v3 false(보호책임자 연락처 줄 구분만 변경) | 원격 게시 완료, 현재 시행 v3(2026-11-22) |
| `privacy_policy` 개인정보 처리방침 | v1, v2, v3(`seed_legal_v3.sql`), v4(`seed_legal_v4.sql`) | 동의 대상 아님(고지, `required=false`, PRD-17-02 A) | v2·v3·v4 false | 원격 게시 완료, 현재 시행 v4(2026-11-22 밤, v4는 사진 판독 제공자를 Upstage로 고지) |
| `privacy_consent` 개인정보 수집·이용 동의 | v1, v2 | 필수 | v2 true(수집 항목·외부 AI 전송 추가) | 원격 게시 완료, 현재 시행 v2 |
| `sensitive_consent` 민감정보(건강) 처리 동의 | v1, v2 | 선택(`required=false`) | v2 true | 원격 게시 완료, 현재 시행 v2 |
| `age_14` 만 14세 이상 확인 | v1(`seed_legal_age14.sql`) | 필수(첫 로그인 동의 화면의 별도 체크, PRD-17-09 A) | false | 원격 게시 완료, 현재 시행 v1 |

- **원격 게시 결과(티켓 기록)**: 원격 `account` 스키마 적용(BE-11-23 A) 뒤 v1·v2·`age_14`를 게시하고 `verify`가 정상이었다(2026-11-22). 이어 v3(`terms`·`privacy_policy` 두 행)를 게시해 `legal_documents`가 9행에서 11행이 됐고, v4(`privacy_policy` 1행)를 게시해 12행이 됐다. 최신 `legal_current`는 `age_14` 1·`privacy_consent` 2·`privacy_policy` 4·`sensitive_consent` 2·`terms` 3이고 `verify`의 `terms_v3_privacy_v4_current`가 true다(PRD-17 §3 ⑯). 이 문서를 쓰면서 원격은 다시 읽지 않았다.
- **게시 차단**: `account_repo_pg.assert_publishable`가 `{{…}}` 자리표시(말줄임표 하나인 `{{…}}`는 제외)가 남은 시드의 원격 게시를 막는다(PRD-17-11 A, 허용 목록 없음). v2·v3·v4 시드에 남은 자리표시는 `{{PRIVACY_CONTACT}}`(와 적용 스크립트가 채우는 `{{EFFECTIVE_AT}}`)뿐이며 `{{확인 필요}}`는 남아 있지 않다. 이 칸은 저장소에 값을 넣지 않고 원격 적용 스크립트(`backend/scripts/be11_account_migrate.py`)가 apply 직전에 env `PRIVACY_OFFICER_NAME`·`PRIVACY_OFFICER_EMAIL`에서 채운다(`account_repo_pg.render_privacy_contact`). 값이 없으면 자리표시가 남아 게시가 차단된다. v3부터 `{{PRIVACY_CONTACT}}`는 홀로 선 줄이고 그 위 줄 `Can I PPiyak 운영자(개발자)\`와 함께 세 줄(운영자 / 개인정보 보호책임자 / 문의)로 렌더링된다(`seed_legal_v3.sql` 머리 주석, PRD-17-18 A). 문서에는 실제 이름·이메일을 쓰지 않는다.
- **화면 렌더링**: 약관 화면은 표·인용·강제 줄바꿈(`\`)을 렌더링한다(`frontend/src/features/account/Markdown.tsx`, 커밋 `7a586d5`). 실서버 눈 확인은 티켓 기록에 따르며 이 문서가 직접 보지 않았다.
- `age_14` 제목·본문은 "만 14세 이상입니다."이며 사용자 확인으로 확정됐다(PRD-17 §3 ⑬). `[필수 체크]`는 화면 표기라 본문에 넣지 않았다.
- v2 4종은 2026-11-19 밤(m36) 사용자가 문서별로 원문 승인했다(PRD-17 §3 ②). 이후 2026-11-20 성별 문구·OpenAI 줄·Recap 45 항목 반영도 사용자가 승인했다(4장).

## 3. 결정 요약 (PRD-17-01~20)
결정 번호·결과·날짜만 적는다. 질문·선택지·권장 이유는 [PRD-17 §4](../tickets/doc/PRD-17.md#4-결정-현황)가 원본이다. 01~20 모두 완료이며 16만 B이고 나머지는 A다(티켓 `결정 현황` 표 기준, 2026-11-22).

| 번호 | 결과(A) | 날짜 |
|---|---|---|
| PRD-17-01 | 계정은 만 14세 이상, 게스트는 연령 무관, 자녀 정보는 보호자 계정의 가족 프로필, 법정대리인 동의 흐름 없음 | 2026-11-19 밤 m35 |
| PRD-17-02 | 처리방침은 고지(체크 없음) | 2026-11-19 밤 m35 |
| PRD-17-03 | 외부 AI 전송·국외 이전은 처리방침 3절 표 + 두 동의서 한 줄 + 질문 입력창 근처 한 줄 안내(결정 당시 외부 AI는 OpenAI 기준이며, 사진 판독 수탁자가 Upstage로 바뀐 것은 PRD-17-19·20이 이어서 반영) | 2026-11-19 밤 m35 |
| PRD-17-04 | 보호책임자·문의처는 역할 명칭 + 서비스 전용 이메일(주소는 나중) | 2026-11-19 밤 m35 |
| PRD-17-05 | `seed_legal_v2.sql`로 v2 행 추가, v1 유지 | 2026-11-19 밤 m35 |
| PRD-17-06 | 첫 로그인 뒤 동의 화면의 "만 14세 이상입니다" 필수 체크, 동의 기록에 남김 | 2026-11-19 밤 m35 |
| PRD-17-07 | 입력창 고지 원문 승인 | 2026-11-19 밤 m36 |
| PRD-17-08 | 사이드바 저장 안내 `NOT_SAVED_NOTE` 삭제, 입력창 고지로 대체 | 2026-11-19 밤 m36 |
| PRD-17-09 | 만 14세 체크는 동의 화면의 별도 필수 체크, 동의 기록 종류를 따로 | 2026-11-19 밤 m36 |
| PRD-17-10 | 시작 화면 안내에서 외부 AI 문장을 빼고 입력창 고지 하나로 | 2026-11-20 |
| PRD-17-11 | `{{…}}` 자리표시가 남은 시드는 값 확정 전 원격 게시 차단, 허용 목록 없음 | 2026-11-20 |
| PRD-17-12 | 만 14세 확인 기록은 새 문서 종류 `age_14`로 저장 | 2026-11-20 |
| PRD-17-13 | 성별은 건강 정보 동의가 아니라 개인정보 수집 동의의 선택 항목, 온보딩에서 직접 선택, 간편 로그인 공급자 성별 미사용 | 2026-11-20 |
| PRD-17-14 | Recap 45 ④ 로그인 저장 항목 초안 승인(소셜 Google·Kakao만, 이메일 로그인 문구 없음). 사용자 몫: Supabase 대시보드에서 Email 공급자 끄기 | 2026-11-20 m54 |
| PRD-17-15 | Recap 45 ⑥ 쿠키(로그아웃하지 않으면 최대 400일)와 보안 조치 초안 승인, HTTPS 문장은 배포 방식이 정해진 뒤 | 2026-11-20 m54 |
| PRD-17-16 | 서버 접근 로그를 끈다(B, `--no-access-log`), 본문은 "법령에 따라 보존해야 하는 정보는 없습니다"만 | 2026-11-20 m54 |
| PRD-17-17 | 입력창 고지 마지막 문장을 "질문과 선택한 프로필 값은 외부 AI(OpenAI)로 전송되며 제공자 정책에 따라 일정 기간 보관될 수 있어요"로 교체(구현 `471fa99`, 병합 `ac04b98`) | 2026-11-22 |
| PRD-17-18 | 보호책임자 연락처 줄을 세 줄로 나눈 `terms` v3·`privacy_policy` v3 게시(내용 변경 없음, 재동의 없음) | 2026-11-22 오후 |
| PRD-17-19 | 사진 판독 수탁자 Upstage 변경에 재동의를 받지 않고 처리방침 v4 게시 + 화면 변경 안내(`requires_reconsent=false`). 법률 자문 아님·추정이며 국외 처리가 별도 동의 대상으로 판단되면 B로 다시 연다 | 2026-11-22 |
| PRD-17-20 | 처리방침 v4 문장 승인(2절 마지막 문장, 3절 OpenAI 줄에서 사진 관련 칸 삭제, 3절 Upstage 줄 추가). 처리 국가는 "확인하지 못함"으로 쓴다(글로벌 엔드포인트) | 2026-11-22 |

PRD-17-11·12는 사용자 답 원문이 "PRD-17-11, PRD-17-A"였고 메인이 둘 다 A로 해석했다(schedule-done.md 기록).

## 4. 사실 값 현황
시드의 `{{…}}`를 사실로 채우는 일의 현황이다. 사실은 원천에 있는 것만 쓴다.

### 4.1 채운 것
| 항목 | 채운 값(요지) | 근거·날짜 |
|---|---|---|
| OpenAI 처리자·국가·보관 기간 | 법인 OpenAI OpCo, L.L.C.(미국 캘리포니아주 샌프란시스코). 연락처 privacy@openai.com, 국내대리인 오픈에이아이코리아 유한회사 privacykorea@openai.com. 국가 미국(국외 서버). 보관은 API 남용 모니터링 로그 최대 30일, 모델 학습 미사용. 현재 시드 처리방침 v4 3절 OpenAI 줄(`seed_legal_v4.sql:37`)의 위탁 업무는 "답변 생성"이고 전송 항목은 질문 내용·질문할 때 선택한 프로필 값이다(사진 관련 칸은 v4에서 삭제). 2026-11-20 판의 사진 위탁 업무·이전 항목은 Upstage 줄로 옮겨졌다(5장) | 2026-11-20(Recap 58 종결, PRD-17 §3 ⑫). 출처 7장 |
| 로그인 저장 항목 | Google·Kakao 공급자가 넘기는 계정 식별자·이메일·이름(Kakao는 닉네임)·프로필 사진 주소(Kakao는 선택 동의), 가입·마지막 로그인 시각. 로그인 처리(Supabase)가 보관하고 이 서비스는 계정 식별자만 쓴다는 문장 | 2026-11-20 사용자 승인(반영 진행 중, 시드 머리 주석 `seed_legal_v2.sql:12-13`). 우리 코드 쪽은 코드로 확인했고 Supabase 저장 열은 추정(`recap45.md` §2 확신도 중) |
| 쿠키 | 로그인 상태 유지용 쿠키(`sb-…-auth-token`), 로그인 토큰·사용자 정보(이메일 포함), 로그아웃하지 않으면 최대 400일 | 2026-11-20 사용자 승인(반영 진행 중). 근거 `@supabase/ssr` 설치본 소스(`recap45.md` 확신도 상) |
| 보안 조치 | 행 수준 보안, 서버도 같은 규칙으로 DB 접근, 토큰 서명·만료 확인, 비밀값 비노출, 계정 응답 캐시 금지. HTTPS 문장은 배포 확정 뒤 더하기로 하고 지금은 넣지 않음 | 2026-11-20 사용자 승인(반영 진행 중) |
| 성별(선택) | 처리방침 수집 항목 표·가족 프로필, 수집·이용 동의 수집 항목·목적에 "성별(선택)" 추가. 성별은 질문 화면에서 임신 여부 선택을 보여 줄지 정하는 데만 쓰고 외부 AI로 전송하지 않으며 간편 로그인 공급자에게서 받지 않는다 | 2026-11-20 사용자 "성별 문구 승인"(PRD-17-13 A, 커밋 `4386b21`·병합 `9d878dd`). 로컬 PG 시험은 `LOCAL_PG_DSN` 없는 셸이라 미실행(`prd17-sex.md`) |
| Supabase 줄(Recap 45 ①③④) | 받는 자 `Supabase(Supabase Pte. Ltd. · 문의 privacy@supabase.com)`, 국가 `대한민국(서울, Supabase 리전 ap-northeast-2)`, 보유 기간 "백업은 7일 뒤 순환 삭제, Supabase Pro 일간 백업, Supabase 정책에 따름" | 2026-11-20 사용자 승인, 시드 반영(`seed_legal_v2.sql` privacy_policy §3). 출처 https://supabase.com/privacy, https://supabase.com/docs/guides/platform/backups, https://supabase.com/docs/guides/platform/regions(2026-11-20 읽음) |
| 서버 접속 기록 끄기(⑧ B) | 접근 로그를 남기지 않는 방향(`uvicorn --no-access-log`)으로 정했고 본문은 "법령에 따라 보존해야 하는 정보는 없습니다"로 정리했다. 코드 반영은 시험 `backend/tests/test_prd17_no_access_log.py`가 확인한다: Dockerfile·실행 명령·launchd plist·`dev_fake_server.py`가 접근 로그를 끄고(`--no-access-log`/`access_log=False`), 서비스 모드 `/chat` 한 요청의 로그에 접속 IP·질문 문장이 없음을 본다(이 문서 작성 중 시험을 실행하지는 않았고 파일 존재와 내용만 읽었다) | 2026-11-20 사용자 승인(PRD-17-16 B, `seed_legal_v2.sql:14`의 "접근 로그 끔"). 선택지 A/B 원안은 `recap45.md` §2 ⑧ |
| Upstage 줄(사진 판독, PRD-17-19·20 A) | 받는 자 `Upstage(주식회사 업스테이지, Upstage Co., Ltd., 대한민국 서울특별시 강남구 · 문의 infosec@upstage.ai)`, 위탁 업무 "약봉투 사진에서 약 이름 읽기", 이전 항목은 사진과 사진에서 읽은 글자. 국가 칸: 대한민국 법인이나 글로벌 엔드포인트를 쓰며 처리 국가를 확인하지 못했고 국외(미국 등) 처리 가능성을 밝힌다. 사진은 서비스가 저장하지 않는다. 2절은 사진을 Upstage로 보내고, 사진에서 읽은 약 이름이 확인 뒤 질문에 들어가면 OpenAI로 갈 수 있다고 쓴다(사진 이미지 자체는 OpenAI로 보내지 않음) | `seed_legal_v4.sql:31,38`, 사용자 승인·원격 게시 2026-11-22. 출처 7장 |
| Upstage 요금제 사실 | 사용자 콘솔 확인(2026-11-22): 요금제 Free, API 크레딧 19.63 USD(티켓 BE-14-10 사실 기록). v4 본문은 "이 서비스가 쓰는 이용 요금제를 확인하지 못했다"고 쓴 채 게시됐고, 이용약관 22조는 무료 서비스 입력의 서비스 개선 사용을 허용한다(6항). 사용자는 BE-14-10 B로 유료 전환과 서면 확인 뒤 v5에서 문구를 정리하기로 했다 | 티켓 `tickets/backend/BE-14.md` BE-14-10, 로컬 `upstage-legal.md` §1, `seed-v4-upstage.md`. 본문과 최신 사실이 다르므로 v5 전까지 이 차이를 둔다 |

### 4.2 남은 것
| 자리표시 | 내용 | 맡은 쪽 |
|---|---|---|
| `{{PRIVACY_CONTACT}}`, 보호책임자 | 저장소에는 자리표시로 둔다. env `PRIVACY_OFFICER_NAME`·`PRIVACY_OFFICER_EMAIL`에서 게시 때 채움(v3부터 `개인정보 보호책임자: <이름>\` 줄바꿈 `문의: <이메일>` 두 줄, 위 줄의 운영자 표기와 합쳐 세 줄, plan 출력은 `<설정됨>`). 게시본에는 채워졌으며 이 문서에 값은 쓰지 않는다. 서비스 전용 이메일은 나중(PRD-17 §3 ⑨) | 사용자(PRD-17-04 A, Recap 45 ②, env 방식 2026-11-20 승인) |
| Upstage 처리 국가 | 확인하지 못함. 한국 리전(`kr.api.upstage.ai`)은 Closed Beta로 별도 접근 승인이 필요하고, 2026-11-22 읽기 전용 확인에서 `/v1/models`가 모델 0개를 돌려줬다. 승인 전에는 국가 칸을 "대한민국"으로 바꾸지 않는다 | 사용자(Upstage에 접근 신청·서면 확인 문의, BE-14-10 B ②) |
| Upstage 요금제와 데이터 조건 | Free + API 크레딧(2026-11-22 사용자 확인). 유료 전환과 서면 확인(학습·개선 사용 여부, 보관 기간, 크레딧 계정이 이용약관 22조의 "무료 서비스"인지) 뒤 v5에서 정리 | 사용자(BE-14-10 B ① ②·③) |

확인하지 못한 것(`recap45.md` §3): Supabase Auth가 실제로 저장한 열·값, `auth.sessions`·감사 기록의 IP 보관 기간, Vercel 요청 로그, 백엔드 운영 로그 보관 기간(BE-13 배포 방식 미정, 2026-11-20 보류).

## 5. 축소 범위와 사진 문구
- **정정(사용자 2026-11-20 "사진은 필수기능이야")**: 약봉투 사진은 필수 기능이다. 축소 대상은 음성 입력뿐이다(PJ2-RFP.md 4장 축소 순서 중 음성). 앞서 적은 "FR-11 사진 축소"는 철회한다.
- 2026-11-20 판에서 사진 문구는 OpenAI 전송으로 승인됐으나(`recap45.md` §2 ⑦(a)(b)), 사진 판독 수탁자가 BE-14-09 A(2026-11-22)로 Upstage가 되면서 처리방침 v4가 이를 대체했다. 현재 시드(`seed_legal_v4.sql`)의 모양: 2절 마지막 문장은 사진을 Upstage로 전송한다고 쓰고, 사진 이미지는 OpenAI로 보내지 않지만 사진에서 읽은 약 이름이 확인 뒤 질문에 들어가면 OpenAI로 전송될 수 있다고 쓴다. 3절 표는 OpenAI 줄(답변 생성)과 Upstage 줄(사진에서 약 이름 읽기) 두 줄이다. 코드 근거: 프런트가 읽은 약 이름을 질문 글자로 만들어 `/chat`으로 보내고 그래프 model 노드가 질문을 OpenAI 모델에 보낸다(`seed_legal_v4.sql` 머리 주석).
- Upstage 사실: 법인 Upstage Co., Ltd.(서울특별시 강남구, 한국 법인), 처리방침 시행 2026-11-02, 이용약관 시행 2026-09-21(22조: 입력·출력 데이터는 회원 소유, 무료 서비스 데이터는 서비스 제공·개선·AI R&D에 쓰일 수 있음). 이 서비스는 글로벌 엔드포인트 `api.upstage.ai`를 쓰며 처리 국가를 확인하지 못했다. 한국 리전 `kr.api.upstage.ai`는 Closed Beta로 별도 접근 승인이 필요하고 `solar-pro4`는 지원 목록에 없다고 조사 보고가 기록한다(공식 문서, 읽은 날 2026-11-22, 로컬 `upstage-legal.md`·`upstage-kr-region.md`). 요금제는 Free + API 크레딧(7장·4.1 참고).
- 사진 판독 제공자의 이력: AG-17-02 A(`gpt-6-luna` 유지)를 BE-14-09 A(Upstage)가 대체했고 서비스 기본값은 `upstage`다(`MEDIAGENT_VISION_PROVIDER=openai`로 복귀 가능, 티켓 BE-14 기록).
- 처리방침 2절의 "약봉투 사진과 음성은 저장하지 않습니다."는 유지한다.

## 6. 남은 일
1. **원격 적용(완료)**: v1·v2·`age_14`, v3, v4를 승인 flag 절차(`plan` → `apply --yes` → `verify`)로 게시했고 `verify`는 정상이다(2026-11-22, PRD-17 §2·§3 ⑯, 2장 참고). 이 문서가 원격을 다시 읽지는 않았다.
2. **자리표시 채우기(⑫, 완료)**: 게시본의 `{{PRIVACY_CONTACT}}`는 env 값으로 채워졌다(값은 문서에 쓰지 않는다). 본문 문장 수정은 계속 사용자 승인 대상이다.
3. **프런트 표시 확인(⑤)·`age_14` 체크(⑥)**: 약관 화면이 표·인용·강제 줄바꿈을 렌더링하도록 고쳤고(`7a586d5`) 처리방침 표·Upstage 줄은 사용자 실서버 확인 기록이 있다(티켓·`schedule.md` 기록, 이 문서가 직접 보지 않음). 연락처 세 줄·이메일 줄바꿈·만 14세 체크의 눈 확인은 티켓 기록에 없어 사용자 몫으로 남는다. 성별 항목(FE-04)은 해당 티켓 몫이다.
4. **법률 검토는 보류(Recap 9)**: 개인정보 보호법 조문 대조는 해석이며 처리방침 작성지침 등은 열지 못했다. `legal_review='reviewed'`·"법률 검토 완료" 표현은 어떤 산출물에도 쓰지 않는다.
5. 시드 머리의 승인 줄은 v4 시드도 "원문 승인 2026-11-19(사용자)"이고 v4 승인(2026-11-22, PRD-17-19·20)은 본문 줄에 없다. 날짜를 남길지는 사용자·메인 판단이다(시험이 그 줄을 글자 그대로 검사하므로 고치면 시험도 함께 고쳐야 한다, `prd17-sex.md` §4).
6. **Upstage 정리(v5 후보)**: 사용자는 BE-14-10 B로 유료 전환과 Upstage의 서면 확인을 한 뒤 처리방침 v5에서 처리 국가·요금제 문구를 정리하기로 했다. 한국 리전 접근이 승인되면 국가 칸을 바꾸는 v5가 따로 필요할 수 있다(로컬 `upstage-kr-region.md`).
7. **옮길 내용 메모(미해결, PRD-17 §2 완료 조건 ② ③)**: 티켓은 이 문서에 ③ 빈칸 목록(항목별 "필요함/불필요/미확인"과 근거 조문·URL)과 v2 본문 초안 4종이 있기를 요구하지만, 현재 그 내용은 로컬 전용 `data/mock/briefs/reports/legal-review.md` §2(항목 A-1~C-6)와 §3, 시드 `seed_legal_v2.sql`에만 있다. 옮길 위치는 이 문서 4장 뒤에 "빈칸 목록" 장과 "본문 링크" 장을 새로 두는 것이다(이번에는 옮기지 않음). 옮길 때도 "필요함·불필요" 표현은 해석이며 법적 단정이나 법률 자문이 아니라는 한계를 그대로 유지한다.

## 7. 출처
저장소 파일(읽은 날 2026-11-20, 2026-11-22 현행화 때 아래 중 v3·v4 시드·`BE-14`·`PRD-17` 결정 표·시험 파일을 다시 읽음):
- `tickets/doc/PRD-17.md` §1~§6, `tickets/backend/BE-14.md`(BE-14-09·BE-14-10)
- `backend/app/db/seed_legal_v2.sql`, `seed_legal_v3.sql`, `seed_legal_v4.sql`, `backend/app/db/seed_legal_age14.sql`, (참고) `backend/app/db/seed_legal_v1.sql`
- `backend/tests/test_prd17_no_access_log.py`(머리 설명만 읽음), `frontend/src/features/account/Markdown.tsx`(파일 존재와 커밋 `7a586d5` 제목으로 확인)
- `schedule.md` Recap 9·45, `schedule-done.md` Recap 58 종결 기록(2026-11-20 m41), `tickets/agent/AG-17.md:58`
- `P2-doc/PJ2-계정-프로필-데이터.md`(6~8장, 부록 B)

로컬 전용 보고(저장소에 없음, 독자는 로컬에서만 볼 수 있다): `data/mock/briefs/reports/legal-review.md`(2026-11-19 초안 검토, 개인정보 보호법 [시행 2026. 9. 11.] 제18조 제3항·제21조·제22조·제22조의2·제23조·제26조·제28조의8·제30조·제31조·제34조·제35조 제1항을 읽음), `recap45.md`(2026-11-20 코드·설정 확인), `prd17-sex.md`(2026-11-20).

외부 출처:
- 개인정보 보호법: https://www.law.go.kr/법령/개인정보보호법 (읽은 날 2026-11-19, 제15조·제29조·시행령 제30·31조는 열지 않음)
- OpenAI 개인정보 처리방침(한국어판, 2026-09-10 갱신)과 「OpenAI 대한민국 이용자를 위한 개인정보 처리방침 부록」(2026-03-27 갱신): https://openai.com/policies/privacy-policy (읽은 날 2026-11-20, 사용자가 붙여 넣은 본문을 읽음). 처리방침 서두는 API 같은 비즈니스 제품으로 고객을 대신해 처리하는 콘텐츠에는 고객 계약이 적용된다고 밝힌다(schedule-done.md 메인 판단).
- OpenAI 데이터 관리: https://developers.openai.com/api/docs/guides/your-data (30일 모니터링 로그·학습 미사용·제로 보관 사전 승인, 읽은 날 2026-11-19, 로컬 `reports/docs4h.md` D2 경유), https://developers.openai.com/api/docs/guides/data-residency (한국 `kr.api.openai.com`은 저장만 지원·처리 미지원, 읽은 날 2026-11-19)
- Upstage(조사 보고 `upstage-legal.md`·`upstage-kr-region.md`·`upstage-live-cost.md`가 읽은 날 2026-11-22로 기록한 것을 옮겼다. 이 문서를 쓰면서 URL을 다시 열지는 않았다): 처리방침 https://www.upstage.ai/privacy-policy (2026-11-02 시행), 이용약관 https://upstage.ai/terms-of-service (22조, 2026-09-21 시행), OCR https://console.upstage.ai/docs/models/document-ocr.md, solar-pro4 https://console.upstage.ai/docs/models/solar-pro-4.md, 리전 https://console.upstage.ai/docs/guides/region-usage.md. 한국 리전 접근 신청은 https://www.upstage.ai/contact-us.
- 요금제(Free, API 크레딧 19.63 USD)는 공개 출처가 아니라 사용자가 콘솔을 보고 알린 값이다(2026-11-22, 티켓 BE-14-10 기록).

출처끼리 다른 점: OpenAI 보관 "최대 30일"은 API 문서 기준이고, 처리방침 본문은 API 처리 콘텐츠에 고객 계약이 적용된다고 해 두 출처가 적용 범위를 달리 말한다. 처리방침 본문에는 API 기준 30일을 근거로 적고 이 차이를 여기에 남긴다.
