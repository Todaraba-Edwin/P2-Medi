-- BE-05 근거 코퍼스 스키마(RFP 5.1절 (2) ③). Postgres(Supabase) + pgvector 전용 템플릿이다.
--   * embedding 열의 차원 자리표시자는 임베딩 차원(1536 또는 512, BE-05-03 답 뒤 확정). 적재 스크립트 `scripts/load_corpus.py --print-sql [--dim N]`이 채운다.
--   * 멱등: CREATE ... IF NOT EXISTS, 적재는 ON CONFLICT (chunk_id) DO NOTHING. chunk_id는 같은 청크(키+본문)면 같은 값이다.
--   * embedding은 NULL 허용이다. 텍스트·메타를 먼저 넣고 임베딩은 별도 단계로 채운다(이번 단계는 임베딩 호출 없음).
--   * 판정 결과는 넣지 않는다(5.1절 (3)). 이 표는 설명용 문장과 연결 메타만 둔다. 판정 테이블은 schema.sql(BE-09).
--   * 로컬 SQLite 시험용 DDL은 이 파일이 아니라 load_corpus.py가 같은 컬럼으로 만든다(배열·JSON은 TEXT, embedding 열 없음).
-- 주의: 이 파일을 원격 DB에 실행하는 일은 BE-05-03 답과 사용자 승인 뒤다.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS corpus_chunks (
    chunk_id     TEXT PRIMARY KEY,               -- 결정적 해시(종류 접두 + sha1(키+본문)[:16])
    chunk_kind   TEXT NOT NULL,                  -- l2_combo / l2_preg / l2_age / l1_bupyo2_table / l1_bupyo2_row ...
    parent_id    TEXT,                           -- 상위 청크(표→행 등). 없으면 NULL
    refs         JSONB NOT NULL DEFAULT '[]',    -- 참조 대상 chunk_id 목록
    pair_id      TEXT,                           -- 성분코드 두 개 정렬 이어붙임 'lo+hi' (병용 쌍 청크만)
    layer        TEXT NOT NULL,                  -- L1 / L2 / L3
    issuer       TEXT NOT NULL,
    doc_type     TEXT NOT NULL,                  -- 고시 / 파일데이터 / 허가사항 ...
    notice_no    TEXT NOT NULL DEFAULT '',       -- 연도 4자리 + 번호 4자리
    base_date    DATE NOT NULL,                  -- 기준일(데이터 기준 2026-07-21)
    locator      TEXT NOT NULL,                  -- 인용 위치(별표 2 연번 37 / 파일 행 ...)
    ingr_codes   TEXT[] NOT NULL DEFAULT '{}',
    ingr_names   TEXT[] NOT NULL DEFAULT '{}',
    license      TEXT NOT NULL,
    text         TEXT NOT NULL,
    source_ref   TEXT NOT NULL,                  -- 데이터셋|파일 이름
    year         SMALLINT,                       -- 문서 메타 표(doc_meta.py): 고시 개정 연도 또는 기준일 연도. 미확인 NULL
    source_file  TEXT NOT NULL DEFAULT '',       -- 원본 파일 이름(API 청크는 빈 문자열)
    effective_date DATE,                         -- 시행일(확인된 경우만). 미확인 NULL
    item_seq     TEXT NOT NULL DEFAULT '',       -- L3: 품목기준코드(e약은요·허가 상세). 같은 제품의 청크를 모으는 키
    item_name    TEXT NOT NULL DEFAULT '',
    section      TEXT NOT NULL DEFAULT '',       -- L3: 절(항목) 이름 또는 `doc 조항 제목`
    code_status  TEXT NOT NULL DEFAULT '',       -- L3: 성분코드 연결 상태(BE-10 사전 code_link:code_scope, 연결 없으면 none)
    embedding    vector({{DIM}})                 -- 임베딩 단계에서 채움(NULL 허용)
);
CREATE INDEX IF NOT EXISTS idx_corpus_pair_id ON corpus_chunks (pair_id) WHERE pair_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_corpus_parent_id ON corpus_chunks (parent_id) WHERE parent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_corpus_item_seq ON corpus_chunks (item_seq) WHERE item_seq <> '';
CREATE INDEX IF NOT EXISTS idx_corpus_layer_kind ON corpus_chunks (layer, chunk_kind);
CREATE INDEX IF NOT EXISTS idx_corpus_ingr_codes ON corpus_chunks USING GIN (ingr_codes);

-- @@HNSW@@ (별도 단계: 임베딩을 채운 뒤에만 실행. `--print-sql --hnsw`가 이 아래만 출력한다)
CREATE INDEX IF NOT EXISTS idx_corpus_embedding_hnsw ON corpus_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
