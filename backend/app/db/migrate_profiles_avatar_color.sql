-- 프로필 병아리 배경색 avatar_color 추가(2026-11-23 사용자 결정, 8색: yellow 기본·coral·pink·purple·blue·teal·green·gray). 이미 적용된 DB용.
--   * 기존 행은 기본값 'yellow'로 채워진다(NOT NULL DEFAULT, 값 UPDATE 없음). 재실행 안전(IF NOT EXISTS, 제약은 이름으로 존재 확인).
--   * RLS 정책·트리거는 바꾸지 않는다(profiles 행 단위 정책이 새 열에도 그대로 적용된다).
--   * 같은 문장이 schema_account.sql에도 있다(신규 설치용). 이 파일은 단계 11로 따로 돌려 열·제약·null 없음을 확인한다.
--   * 롤백(필요할 때만, 수동): ALTER TABLE account.profiles DROP CONSTRAINT IF EXISTS profiles_avatar_color_check;
--                              ALTER TABLE account.profiles DROP COLUMN IF EXISTS avatar_color;
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
