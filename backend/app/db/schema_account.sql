-- BE-11 계정·프로필·약관·동의 스키마(P2-doc/PJ2-계정-프로필-데이터.md 4~7장, 부록 A 초안 기반). Postgres(Supabase) 15+ 전용.
--   * 사용자 결정(2026-11-18 "권장대로"): BE-11-06 A(`account` 스키마 + 백엔드가 요청마다 SET LOCAL ROLE authenticated·request.jwt.claims),
--     07 A(연령대 11구간), 08 A(관계 self·child·parent·spouse·other), 09 A(임신 주차 열 없음), 10 A(app_users는 첫 GET /me에 생성),
--     12 A(privacy_consent 철회 → 프로필만 삭제), 22 A(탈퇴 시 동의 기록 포함 즉시 전부 파기, 파기 사실은 일자·건수만 식별자 없이).
--   * 부록 A와 다른 점: user_consents FK가 ON DELETE CASCADE(익명화 보관 대신 즉시 삭제, 22 A)이고 anonymized_at 열·익명화 트리거가 없다.
--     파기 집계 표 deletion_log(일자별 건수, 식별자 열 없음)와 본인 탈퇴 함수 delete_my_account()를 더했다. 가족은 3행 상한(본인 1 + 가족 3).
--     signup_provider는 NULL 허용(검증기가 sub만 돌려준다. 채우는 일은 후속).
--   * 2026-11-20 GROUP-03 B1: 프로필 성별 선택 칸 `sex`(enum account.sex 'female'·'male', NULL = 미입력, FE-11-09 C·PRD-17-13 A,
--     건강 정보 아님 → 건강 동의 트리거 대상 아님, privacy_consent 철회 때 프로필과 함께 삭제)와 동의 문서 종류 `age_14`
--     (만 14세 이상 확인, PRD-17-12 A·09 A, 철회는 terms처럼 USE_ACCOUNT_DELETE). 이미 적용된 DB에는 ALTER … IF NOT EXISTS로 더한다.
--   * 멱등: CREATE ... IF NOT EXISTS, enum은 DO 블록에서 존재 확인, 함수는 CREATE OR REPLACE, 트리거·정책은 DROP IF EXISTS 뒤 CREATE.
--   * account 스키마 밖(public 판정·코퍼스·사전, auth)은 건드리지 않는다. auth.users·auth.uid()는 Supabase가 제공한다
--     (로컬 시험은 스텁, backend/tests/test_be11_account_pg.py).
-- 주의: 원격 적용은 승인 flag 절차 뒤다(설계 12장). 이 파일은 적용하지 않은 초안이다.

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
        CREATE TYPE account.doc_type AS ENUM ('terms', 'privacy_policy', 'privacy_consent', 'sensitive_consent', 'age_14', 'terms_guest');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
                   WHERE n.nspname = 'account' AND t.typname = 'sex') THEN
        CREATE TYPE account.sex AS ENUM ('female', 'male');  -- "기타" 없음, NULL = 미입력(FE-11-09 C, 가정)
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

-- 이미 적용된 DB(age_14 이전 enum)에 값을 더한다. PG 12+는 트랜잭션 안에서도 되지만 **새 값은 커밋 뒤에만 쓸 수 있다**:
-- 이 파일 안에서는 'age_14'를 실행 시점에 쓰지 않는다(plpgsql 본문은 호출 때 평가). 시드(seed_legal_age14.sql)는 이 파일을 커밋한 뒤 따로 실행한다
ALTER TYPE account.doc_type ADD VALUE IF NOT EXISTS 'age_14';
-- PRD-17-22 A: 게스트판 이용약관 문서 종류. 시드(seed_legal_guest_v1.sql)는 이 값이 커밋된 뒤 따로 실행한다(migrate_doc_type_terms_guest.sql과 같은 문장)
ALTER TYPE account.doc_type ADD VALUE IF NOT EXISTS 'terms_guest';

-- 문서 본문 해시(생성 열 body_sha256용). convert_to()가 STABLE이라 생성 열에 바로 쓰면 "generation expression is not immutable"로
-- CREATE TABLE이 실패한다(2026-11-19 로컬 PG 17 재현). 결과는 입력 문자열의 UTF-8 바이트에만 달려 IMMUTABLE로 선언한다.
-- plpgsql인 이유: SQL 함수는 인라인된 뒤 가변성 검사를 다시 받아(PG 16+) 같은 오류가 난다. 값은 Python account_repo.body_sha256과 같다
CREATE OR REPLACE FUNCTION account.utf8_sha256_hex(p_body text) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE SET search_path = '' AS $$
BEGIN
    RETURN pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p_body, 'UTF8')), 'hex');
END
$$;

-- 2. 테이블 -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account.app_users (
    user_id                 uuid PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
    signup_provider         account.provider,
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
-- 성별(선택, 2026-11-20 GROUP-03 B1). 새 DB와 이미 적용된 DB 모두 이 한 줄로 더한다(재실행 안전)
ALTER TABLE account.profiles ADD COLUMN IF NOT EXISTS sex account.sex;
-- 병아리 배경색(2026-11-23 사용자 결정, 8색 중 하나). 건강 정보가 아니라 프로필 저장 동의(privacy_consent)만 있으면 저장한다.
-- 새 DB와 이미 적용된 DB 모두 재실행 안전(별도 파일 migrate_profiles_avatar_color.sql과 같은 문장).
ALTER TABLE account.profiles ADD COLUMN IF NOT EXISTS avatar_color text NOT NULL DEFAULT 'yellow';
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'account.profiles'::regclass AND conname = 'profiles_avatar_color_check') THEN
        ALTER TABLE account.profiles ADD CONSTRAINT profiles_avatar_color_check
            CHECK (avatar_color IN ('yellow', 'coral', 'pink', 'purple', 'blue', 'teal', 'green', 'gray'));
    END IF;
END $$;
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
    body_sha256        text GENERATED ALWAYS AS (account.utf8_sha256_hex(body_md)) STORED,
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (doc_type, version)
);
CREATE INDEX IF NOT EXISTS idx_legal_current ON account.legal_documents (doc_type, status, effective_at DESC);

-- 동의 기록: 추가만 한다. 탈퇴(app_users 삭제) 때 CASCADE로 즉시 삭제(BE-11-22 A)
CREATE TABLE IF NOT EXISTS account.user_consents (
    consent_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id       uuid NOT NULL REFERENCES account.app_users (user_id) ON DELETE CASCADE,
    doc_type      account.doc_type NOT NULL,
    doc_version   integer NOT NULL,
    action        account.consent_action NOT NULL,
    channel       text NOT NULL CHECK (channel IN ('onboarding', 'settings', 'reconsent')),
    acted_at      timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (doc_type, doc_version) REFERENCES account.legal_documents (doc_type, version),
    CHECK (doc_type <> 'privacy_policy')
);
CREATE INDEX IF NOT EXISTS idx_consents_user ON account.user_consents (user_id, doc_type, acted_at DESC);

-- 파기 집계: 일자(UTC)별 건수만. 사용자 식별자·시각 열이 없다(BE-11-22 A). 소유 역할만 읽고 쓴다
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

-- 계정당 본인 1 + 가족 3(BE-11-01 B). 같은 계정의 동시 삽입은 advisory lock으로 줄 세운다
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

-- 건강 정보는 sensitive_consent가 있을 때만(BE-11-03 A). API가 먼저 검사하고(422) 이것은 두 번째 방어선이다
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

-- 철회 시 즉시 삭제(6.3절). 호출자(authenticated) 권한으로 돌므로 RLS가 본인 행만 지우게 한다
CREATE OR REPLACE FUNCTION account.on_consent_withdraw() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.action <> 'withdraw' THEN
        RETURN NEW;
    END IF;
    IF NEW.doc_type IN ('terms', 'age_14') THEN  -- 만 14세 확인 철회도 탈퇴로만(PRD-17-12 A)
        RAISE EXCEPTION 'USE_ACCOUNT_DELETE' USING ERRCODE = 'P0001';
    ELSIF NEW.doc_type = 'sensitive_consent' THEN
        UPDATE account.profiles SET pregnancy_status = NULL WHERE user_id = NEW.user_id AND pregnancy_status IS NOT NULL;
        DELETE FROM account.profile_medications WHERE user_id = NEW.user_id;
    ELSIF NEW.doc_type = 'privacy_consent' THEN
        DELETE FROM account.profiles WHERE user_id = NEW.user_id;  -- 약은 CASCADE, 성별도 함께. 계정은 남는다(BE-11-12 A)
    END IF;
    RETURN NEW;
END
$$;

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
DROP TRIGGER IF EXISTS trg_app_users_anonymize ON account.app_users;  -- 부록 A 초안의 익명화 트리거(22 A로 폐기)
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
