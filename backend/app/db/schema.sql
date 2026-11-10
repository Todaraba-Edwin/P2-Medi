-- BE-09 판정 테이블 스키마 (RFP 5.1절 (2) ① 판정 테이블).
-- Postgres(Supabase)와 SQLite(로컬 시험) 양쪽에서 돌도록 공통 문법만 쓴다.
--   * 행 식별자 row_key = 키 필드의 sha1(16진 40자). 적재 함수가 ON CONFLICT (row_key) DO NOTHING으로
--     넣으므로 적재 스크립트를 다시 돌려도 중복이 생기지 않는다.
--   * 금기등급(grade)은 데이터 값 그대로 '1'·'2'·'M'을 저장한다. M을 1·2로 바꾸지 않는다(RFP-17 M 처리 규칙).
--   * 모든 행에 출처(source)와 기준일(as_of, 파일별)을 둔다(RFP 5.1절 (5)).
--   * 판정은 성분코드 정확 일치다(RFP-17 결정 1). 성분명은 표시용이며 판정 키가 아니다.
--   * 날짜는 ISO 문자열 'YYYY-MM-DD'로 넣는다(Postgres는 date로 암묵 변환).

CREATE TABLE IF NOT EXISTS contra_pair (       -- 병용금기: 성분코드 쌍 단위(제품 쌍 512,464건을 줄인 것)
    row_key      TEXT PRIMARY KEY,
    code_a       TEXT NOT NULL,                -- 원본 방향의 성분코드 A
    code_b       TEXT NOT NULL,
    code_lo      TEXT NOT NULL,                -- 방향 무관 조회용(작은 쪽)
    code_hi      TEXT NOT NULL,
    name_a       TEXT,
    name_b       TEXT,
    notice_no    TEXT,                         -- 고시번호
    notice_date  DATE,                         -- 고시 적용일
    reason       TEXT,                         -- 금기사유 원문
    remark       TEXT,
    source       TEXT NOT NULL,
    as_of        DATE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contra_pair_codes ON contra_pair (code_lo, code_hi);

CREATE TABLE IF NOT EXISTS pregnancy_contra (  -- 임부금기: 성분코드 단위
    row_key      TEXT PRIMARY KEY,
    ingr_code    TEXT NOT NULL,
    ingr_name    TEXT,
    grade        TEXT NOT NULL CHECK (grade IN ('1', '2', 'M')),  -- 원본 값 그대로
    detail       TEXT,                         -- 상세정보 원문
    notice_no    TEXT,
    notice_date  DATE,
    source       TEXT NOT NULL,
    as_of        DATE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pregnancy_code ON pregnancy_contra (ingr_code);

CREATE TABLE IF NOT EXISTS age_contra (        -- 연령금기: 성분코드 + 특정연령·단위·처리조건
    row_key      TEXT PRIMARY KEY,
    ingr_code    TEXT NOT NULL,
    ingr_name    TEXT,
    age_value    INTEGER NOT NULL,             -- 특정연령
    age_unit     TEXT NOT NULL,                -- 주 / 개월 / 세
    age_cond     TEXT NOT NULL,                -- 미만 / 이하 / 이상
    age_days     INTEGER NOT NULL,             -- 비교용 환산값(주=7, 개월=30.4375, 세=365.25 일, 반올림)
    detail       TEXT,
    notice_no    TEXT,
    notice_date  DATE,
    source       TEXT NOT NULL,
    as_of        DATE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_age_code ON age_contra (ingr_code);

-- 확장(권장): 용량주의·수유부주의·노인주의. 성분코드로 주의 여부만 돌려준다.
CREATE TABLE IF NOT EXISTS caution (
    row_key      TEXT PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('dose', 'lactation', 'elderly')),
    ingr_code    TEXT NOT NULL,
    ingr_name    TEXT,
    detail       TEXT,                         -- 용량주의는 '1일 최대투여량' 표시 문자열(조언이 아니라 원문)
    notice_no    TEXT,
    notice_date  DATE,
    source       TEXT NOT NULL,
    as_of        DATE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_caution_code ON caution (kind, ingr_code);

CREATE TABLE IF NOT EXISTS load_log (          -- 적재 이력(파일별 행 수), 재실행 확인용
    source_file  TEXT PRIMARY KEY,
    table_name   TEXT NOT NULL,
    raw_rows     INTEGER NOT NULL,
    loaded_rows  INTEGER NOT NULL,
    as_of        DATE NOT NULL
);
