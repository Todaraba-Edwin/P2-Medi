-- BE-06-24 B 제품·성분 사전 테이블(2026-11-17). 서비스 경로는 사전을 파일(`data/mock/dict/drug_dict.json`)이 아니라 이 테이블에서 읽는다.
-- Postgres(Supabase)와 SQLite(로컬 시험) 양쪽에서 돌도록 공통 문법만 쓴다(JSON은 TEXT로 둔다).
--   * 사전 한 판(version)은 drug_dict_meta 1행 + drug_dict_entry N행이다. version은 빌더가 만든 내용 해시(`be10-dict-s1-…`)라
--     같은 version이면 내용도 같다. 적재는 ON CONFLICT DO NOTHING이고, meta 행은 entry 행을 다 넣은 같은 트랜잭션 끝에 넣는다.
--     따라서 meta 행이 있으면 그 판은 완전하다(읽는 쪽이 행 수로 한 번 더 확인한다).
--   * ord는 파일 안 순서(0부터)다. `DrugDict`는 목록 순서를 색인 번호로 쓰므로(ingredient_ids 등) 순서를 그대로 보존한다.
--   * 판정 테이블(schema.sql)과 따로 둔다. 판정은 이 테이블을 읽지 않는다(이름 → 코드 식별용 사전).
-- 주의: 이 파일을 원격 DB에 실행하는 일은 사용자 승인 뒤다(`scripts/be06_dict_load.py apply --yes` + 승인 파일).

CREATE TABLE IF NOT EXISTS drug_dict_meta (
    version        TEXT PRIMARY KEY,              -- 사전 판(meta.version)
    meta           TEXT NOT NULL,                 -- 사전 meta JSON 원문(form_map·counts·materials 등)
    n_products     INTEGER NOT NULL,
    n_ingredients  INTEGER NOT NULL,
    source_sha256  TEXT NOT NULL,                 -- 적재한 파일의 sha256(같은 version에 다른 파일이 오면 거부)
    loaded_at      TEXT NOT NULL                  -- 적재 시각 ISO(UTC). 여러 판이 있으면 가장 늦은 것을 읽는다
);

CREATE TABLE IF NOT EXISTS drug_dict_entry (
    version   TEXT NOT NULL,
    kind      TEXT NOT NULL CHECK (kind IN ('product', 'ingredient')),
    ord       INTEGER NOT NULL,                   -- 파일 안 순서(0부터)
    data      TEXT NOT NULL,                      -- 항목 JSON 원문
    PRIMARY KEY (version, kind, ord)
);
