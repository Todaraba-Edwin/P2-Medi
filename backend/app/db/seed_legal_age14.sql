-- PRD-17 ⑬ 만 14세 이상 확인 문서 시드 v1(PRD-17-12 A: 동의 문서 종류 `age_14`, PRD-17-09 A: 첫 로그인 동의 화면의 별도 필수 체크).
--   * schema_account.sql을 **커밋한 뒤** 따로 실행한다(ALTER TYPE … ADD VALUE로 더한 enum 값은 같은 트랜잭션에서 쓸 수 없다).
--   * 문구 원문: "만 14세 이상입니다." — PRD-17-09 A 승인본(로컬 data/mock/briefs/reports/legal-review.md §3 표
--     "**확정**: [필수 체크] 만 14세 이상입니다.", tickets/frontend/FE-04.md 하위 작업 "문구 \"만 14세 이상입니다.\"").
--     "[필수 체크]"는 화면 표기 설명이라 본문에 넣지 않았다. 제목도 승인 문구 그대로 두었다(새 문구를 짓지 않음, 제목 문구는 확인 필요).
--   * required true(첫 로그인 필수), requires_reconsent false, legal_review는 기본값 not_reviewed(법률 검토 전).
--   * {{EFFECTIVE_AT}}은 v1·v2와 같이 적용 스크립트(account_repo_pg.seed_age14_sql)가 시행 시각으로 채운다. 날짜를 지어내지 않는다.
--   * 멱등: ON CONFLICT (doc_type, version) DO NOTHING. 게시 뒤 문구를 바꾸려면 v2 행을 새로 넣는다(freeze_published_document).
-- 주의: 원격 적용은 승인 flag 절차 뒤다(GROUP-03 4단계 B3, BE-11-23).

INSERT INTO account.legal_documents (doc_type, version, title, body_md, required, requires_reconsent, status, effective_at)
VALUES
('age_14', 1, '만 14세 이상입니다.', $md$만 14세 이상입니다.$md$, true, false, 'published', '{{EFFECTIVE_AT}}')
ON CONFLICT (doc_type, version) DO NOTHING;
