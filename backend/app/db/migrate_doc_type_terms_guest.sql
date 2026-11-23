-- PRD-17-22 A: 이미 적용된 DB의 account.doc_type 열거형에 terms_guest(게스트판 이용약관)를 더한다. 재실행 안전(IF NOT EXISTS).
--   * ALTER TYPE … ADD VALUE로 더한 값은 커밋 뒤에만 쓸 수 있다 → 이 파일은 시드(seed_legal_guest_v1.sql)와 **다른 트랜잭션**에서 먼저 실행한다.
--   * 같은 문장이 schema_account.sql에도 있다(신규 설치·재적용용). 이 파일은 단계 8로 따로 돌려 값이 보이는지 확인한다.
ALTER TYPE account.doc_type ADD VALUE IF NOT EXISTS 'terms_guest';
