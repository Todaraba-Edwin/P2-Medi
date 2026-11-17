-- BE-06-32 A 사전 테이블 접근 차단(2026-11-17). Postgres(Supabase) 전용: schema_dict.sql 바로 뒤, 적재와 같은 트랜잭션에서 실행한다.
-- SQLite 시험 경로에서는 실행하지 않는다(`drug_dict_store.apply_dict_schema(dialect="sqlite")`).
--   * Supabase는 public 테이블을 Data API(PostgREST)의 anon·authenticated 역할에 기본 권한으로 연다. 이 두 테이블은
--     서비스 백엔드만 읽는 사전이므로 RLS를 켜고 정책을 두지 않으며(= 그 역할들은 행 0), 테이블 권한도 회수한다.
--   * 가정: 백엔드·적재 스크립트는 테이블 소유 역할(SUPABASE_DB_URL의 postgres 계열) DSN으로 접속한다. 소유자는 RLS를
--     우회하므로(FORCE ROW LEVEL SECURITY는 쓰지 않는다) 서비스 읽기·적재에는 영향이 없다. 소유자가 바뀌면 다시 확인한다.
--   * anon·authenticated 역할이 없는 Postgres(로컬 등)에서도 깨지지 않도록 pg_roles로 존재를 확인한 뒤 REVOKE한다.
--   * 모든 문장은 다시 돌려도 안전하다(ENABLE은 멱등, 없는 권한 REVOKE는 무해).

ALTER TABLE drug_dict_meta ENABLE ROW LEVEL SECURITY;
ALTER TABLE drug_dict_entry ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE drug_dict_meta, drug_dict_entry FROM %I', r);
        END IF;
    END LOOP;
END
$$;
