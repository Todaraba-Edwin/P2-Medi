-- PRD-17-22 A 게스트판 이용약관 v1(2026-11-23, 사용자 결정 "PRD-17-22~25 권장대로"): 별도 문서 종류 terms_guest.
--   * 본문 원칙(2026-11-23 사용자 지시): 회원판 v3(seed_legal_v3.sql)에서 회원 전용 항목(계정·연령, 계정 해지, 재동의)만 빼거나 "게스트는 저장하지 않음"으로 바꿨다.
--     1절·3절·6절(문의 5절로 번호만 변경)은 v3와 한 글자도 다르지 않고, 2절은 처리방침 v5 2절 문장을 그대로 쓴다(tests/test_guest_terms_seed.py가 diff로 검사).
--     PRD-17-25 B: 회원판에 없는 새 문장(책임의 한계 등)은 넣지 않았다. PRD-17-24 A: 연락처는 {{PRIVACY_CONTACT}} 자리표시자(게시 때 환경변수로 채움).
--   * 동의 대상이 아니다: required=false, requires_reconsent=false. POST /consents에 terms_guest를 받지 않는다(고지·열람용).
--   * enum 값 terms_guest는 migrate_doc_type_terms_guest.sql(스키마와 별도 커밋)로 먼저 더한다. 새 값은 같은 트랜잭션에서 쓸 수 없다.
--   * {{EFFECTIVE_AT}}·멱등(ON CONFLICT DO NOTHING)은 v1~v5 시드와 같다. legal_review는 기본값 not_reviewed(법률 검토 전).
-- 주의: 원격 적용은 승인 flag 절차 뒤다(BE-11-23). 원문 승인 전.

INSERT INTO account.legal_documents (doc_type, version, title, body_md, required, requires_reconsent, status, effective_at)
VALUES
('terms_guest', 1, 'Can I PPiyak 게스트판 이용약관(초안)', $md$
> 초안·법률 검토 전입니다. 실제 공개·상용 전에 법률 검토가 필요합니다.

## 1. 서비스의 성격
Can I PPiyak은 공공데이터(한국의약품안전관리원 DUR 자료, 식품의약품안전처 공개 API 등)를 바탕으로 의약품 정보와 병용·연령·임부 금기 정보를 안내하는 정보 제공 서비스입니다. 진단·처방·복용량 결정을 하지 않으며 의료적 판단을 대신하지 않습니다. 허가사항의 용법·용량은 근거로 원문 그대로 보여 줄 수 있지만, 사용자에게 맞는 용량을 정해 주지 않습니다.

## 2. 로그인하지 않고 쓰는 경우
로그인하지 않고도 모든 핵심 기능을 쓸 수 있습니다. 로그인하지 않고 쓰면 아무것도 저장하지 않습니다. 질문과 대화 내용은 이용하시는 브라우저 탭의 메모리에만 있고, 우리 서버·데이터베이스·브라우저 저장소에 저장하지 않습니다. 새로고침하거나 탭을 닫거나 새 질문을 시작하면 사라집니다. 다만 답변을 만들기 위해 질문 내용은 외부 AI 서비스(OpenAI)로 전송되며, 그곳의 보관은 개인정보 처리방침 3절과 같습니다. 서버 로그에는 시각·걸린 시간·종료 사유·개수만 남고 질문 문장은 남지 않습니다. 약봉투 사진과 음성은 저장하지 않습니다. 약봉투 사진을 올리면 약 이름을 읽기 위해 사진이 외부 AI 서비스(OpenAI)로 전송되며, 그곳의 보관은 개인정보 처리방침 3절과 같습니다.

## 3. 주의
금기 목록에 없다는 것은 안전하다는 뜻이 아닙니다. 요양기관의 DUR 점검을 대체하지 않습니다. 복용 전에는 가까운 약국·약사에게 확인하세요. 응급 상황에서는 119에 연락하세요.

## 4. 약관의 변경
약관을 바꾸면 버전과 시행일을 표시합니다.

## 5. 문의
Can I PPiyak 운영자(개발자)\
{{PRIVACY_CONTACT}}
$md$, false, false, 'published', '{{EFFECTIVE_AT}}')
ON CONFLICT (doc_type, version) DO NOTHING;
