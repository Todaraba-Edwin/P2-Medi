-- app_users 기본 프로필(대상) 영속화 default_profile_id·default_guest(2026-11-23 사용자 지시 FE-17 U-08). 이미 적용된 DB용.
--   * 기존 행은 (null, false) = 미설정 → 클라이언트가 본인을 고른다(값 UPDATE 없음). 재실행 안전(IF NOT EXISTS, 제약은 이름으로 존재 확인).
--   * RLS 정책은 바꾸지 않는다(app_users_own·app_users_update가 본인 행으로 제한). 새 두 칸에 대한 열 단위 UPDATE 권한만 더한다.
--   * 프로필이 지워지면 FK ON DELETE SET NULL로 미설정이 된다.
--   * 같은 문장이 schema_account.sql에도 있다(신규 설치용). 이 파일은 단계 12로 따로 돌려 열·CHECK·FK 존재를 확인한다.
--   * 롤백(필요할 때만, 수동): ALTER TABLE account.app_users DROP CONSTRAINT IF EXISTS app_users_default_target_check;
--                              ALTER TABLE account.app_users DROP CONSTRAINT IF EXISTS app_users_default_profile_fk;
--                              ALTER TABLE account.app_users DROP COLUMN IF EXISTS default_guest, DROP COLUMN IF EXISTS default_profile_id;
ALTER TABLE account.app_users ADD COLUMN IF NOT EXISTS default_profile_id uuid;
ALTER TABLE account.app_users ADD COLUMN IF NOT EXISTS default_guest boolean NOT NULL DEFAULT false;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'account.app_users'::regclass AND conname = 'app_users_default_profile_fk') THEN
        ALTER TABLE account.app_users ADD CONSTRAINT app_users_default_profile_fk
            FOREIGN KEY (default_profile_id) REFERENCES account.profiles (profile_id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'account.app_users'::regclass AND conname = 'app_users_default_target_check') THEN
        ALTER TABLE account.app_users ADD CONSTRAINT app_users_default_target_check
            CHECK (NOT default_guest OR default_profile_id IS NULL);
    END IF;
END $$;
-- 본인 행의 이 두 칸만 authenticated가 고친다(app_users_update 정책이 행을 본인으로 제한). 역할이 있는 환경에서만
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        GRANT UPDATE (default_profile_id, default_guest) ON account.app_users TO authenticated;
    END IF;
END $$;
