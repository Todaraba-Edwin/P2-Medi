"""BE-11 계정 스키마·약관 시드 원격 적용(GROUP-03 4단계 B3, 2026-11-20). 근거: g3-b1 보고 §7(적용 순서), BE-11-23.

  plan                 (기본) 읽기 전용 연결 1회. 현재 상태(account 스키마·enum·`profiles.sex`·약관 행)와 적용할 단계·SQL 파일·
                       시드별 남은 자리표시를 출력한다. 쓰기 0.
  apply --yes --effective-at <ISO8601+시간대>
                       쓰기. `--yes`와 승인 파일 `data/mock/review/be11-account.flag`(메인이 실행 직전에 만들고 직후 지운다)가
                       **둘 다** 있어야 하고, 시드 아홉 개(v1·v2·age_14·v3·v4·v5·terms_guest v1·v6·최종안)가 모두 `assert_publishable`을 통과해야 한다(연결 전에 확인).
                       단계마다 별도 트랜잭션: ① schema_account.sql → 커밋 → ② seed v1 → ③ seed v2 → ④ seed age_14 → ⑤ seed v3(PRD-17-18 A: terms·privacy_policy v3, 연락처 줄 구분) → ⑥ seed v4(처리방침 v4, 사진 판독 Upstage 전환 고지, BE-14-09 A) → ⑦ seed v5(처리방침 v5, OpenAI만·쿠키 7일·카카오 필수 표기·이름 기본값) → ⑧ migrate_doc_type_terms_guest.sql(열거형에 terms_guest, 커밋) → ⑨ seed terms_guest v1(게스트판 이용약관, PRD-17-22 A, 동의 대상 아님) → ⑩ seed v6(처리방침 v6 = v5 + 게스트 안내 절, PRD-17-23 A) → ⑪ migrate_profiles_avatar_color.sql(프로필 병아리 배경색 열·CHECK, 기존 행 기본 yellow, 2026-11-23, 번호는 기존 단계 유지를 위해 맨 뒤) → ⑫ migrate_app_users_default_target.sql(기본 프로필 default_profile_id·default_guest 열·FK·CHECK·열 UPDATE 권한, 기존 행 미설정, 2026-11-23 FE-17 U-08) → ⑬ seed final legal docs(seed_legal_final.sql: terms v4·privacy_policy v7·privacy_consent v3·sensitive_consent v3·terms_guest v2, 2026-11-23 사용자 지시로 초안·법률 검토 전 문구를 뺀 최종안. 본문 불변·requires_reconsent false·legal_review 기본값 not_reviewed 유지. 번호는 기존 단계 유지를 위해 맨 뒤).
                       (`ALTER TYPE … ADD VALUE 'age_14'`는 같은 트랜잭션에서 쓸 수 없으므로 ④는 ① 커밋 뒤 따로 돈다.)
                       단계 사후 확인이 기대와 다르면 그 단계를 롤백하고 중단한다(다음 단계로 넘어가지 않음).
                       시드의 `{{PRIVACY_CONTACT}}`는 env `PRIVACY_OFFICER_NAME`·`PRIVACY_OFFICER_EMAIL`(Settings)로 채운다
                       (PRD-17 ⑫). 값이 없으면 자리표시가 남아 게시 거부. plan·로그·예외에는 값을 싣지 않는다(`<설정됨>`).
  verify               읽기 전용. age_14 enum·`profiles.sex`·`profiles.avatar_color` 열·CHECK·null 없음·`app_users.default_profile_id`·`default_guest` 열·FK·CHECK(단계 12)·표 6개 RLS·시드 행(v1·v2·age_14·v3·v4·v5)·`legal_current`의 age_14 v1·terms v4·privacy_policy v7·privacy_consent v3·sensitive_consent v3·terms_guest v2(최종안, 단계 13)와 terms_guest enum 값을 확인한다.

  --local-dsn <DSN>    로컬 Postgres 시험용(호스트가 localhost·127.0.0.1·::1·소켓일 때만). 이때는 승인 파일 없이 돈다
                       (`--yes`·자리표시 검사는 그대로). 원격 접속 문자열을 넣으면 거부한다.

재실행 안전: 스키마는 IF NOT EXISTS·CREATE OR REPLACE·DROP IF EXISTS 뒤 CREATE(account 스키마 안의 트리거·정책만),
시드는 ON CONFLICT (doc_type, version) DO NOTHING. 이미 적용된 DB에 다시 돌려도 행이 바뀌지 않는다.
금지(이 스크립트는 하지 않는다): account 밖 스키마 변경, DELETE·TRUNCATE·DROP TABLE·UPDATE.
접속 문자열은 환경변수 SUPABASE_DB_URL(없으면 앱 Settings)에서 프로세스 안에서만 읽고 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from load_corpus import RemoteLoadRefused, resolve_dsn  # noqa: E402

from app.config import get_settings, reveal  # noqa: E402
from app.db.account_repo_pg import (  # noqa: E402
    MIGRATE_AVATAR_COLOR_FILE,
    MIGRATE_DEFAULT_TARGET_FILE,
    MIGRATE_GUEST_ENUM_FILE,
    SCHEMA_FILE,
    SEED_AGE14_FILE,
    SEED_FILES,
    SEED_FINAL_FILE,
    SEED_GUEST_FILE,
    assert_publishable,
    migrate_avatar_color_sql,
    migrate_default_target_sql,
    migrate_guest_enum_sql,
    render_privacy_contact,
    schema_sql,
    seed_age14_sql,
    seed_final_sql,
    seed_guest_sql,
    seed_sql,
    unfilled_placeholders,
)
from app.security.redact import install_excepthook, redact  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DSN_ENV = "SUPABASE_DB_URL"
APPROVAL_FLAG = REPO / "data" / "mock" / "review" / "be11-account.flag"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "/")
TABLES = ("app_users", "profiles", "profile_medications", "legal_documents", "user_consents", "deletion_log")
_SEED_ROW_RE = re.compile(r"^\('([a-z_0-9]+)', (\d+),", re.MULTILINE)


class Refused(RuntimeError):
    """안전장치에 걸려 실행하지 않음(쓰기 전)."""


class StageAbort(RuntimeError):
    """단계 사후 확인이 기대와 다름 → 그 단계 롤백, 이후 단계 실행하지 않음."""


@dataclass(frozen=True)
class Step:
    name: str
    kind: str  # "schema" | "enum"(열거형 값 추가) | "avatar"(profiles.avatar_color 열·CHECK) | "default_target"(app_users 기본 프로필 열·FK·CHECK) | "seed"
    source: Path
    sql: str
    masked: tuple[str, ...] = ()  # 로그·예외 메시지에서 지울 값(보호책임자 이름·이메일)

    @property
    def keys(self) -> list[tuple[str, int]]:
        """시드가 넣는 (doc_type, version). 스키마 단계는 빈 목록."""
        return [(t, int(v)) for t, v in _SEED_ROW_RE.findall(self.sql)] if self.kind == "seed" else []

    @property
    def placeholders(self) -> list[str]:
        return unfilled_placeholders(self.sql) if self.kind == "seed" else []


# --------------------------------------------------------------------------- 단계 구성(로컬, 연결 0)

PrivacyContact = tuple[str | None, str | None]


def privacy_officer() -> PrivacyContact:
    """env `PRIVACY_OFFICER_NAME`·`PRIVACY_OFFICER_EMAIL`(Settings, SecretStr). 값은 프로세스 안에서만 쓰고 출력하지 않는다."""
    s = get_settings()
    return reveal(s.privacy_officer_name), reveal(s.privacy_officer_email)


def contact_set(contact: PrivacyContact | None) -> bool:
    return bool(contact and (contact[0] or "").strip() and (contact[1] or "").strip())


def build_steps(effective_at: datetime, contact: PrivacyContact | None = None) -> list[Step]:
    """g3-b1 §7 순서. 시드의 `{{EFFECTIVE_AT}}`를 채우고, 보호책임자 값이 있으면 `{{PRIVACY_CONTACT}}`도 채운다.

    값이 없으면 `{{PRIVACY_CONTACT}}`를 남겨 두고 assert_publishable이 게시를 막는다. 값이 있는데 형식이 잘못되면 Refused.
    """
    seeds = [("2 seed v1", SEED_FILES[1], seed_sql(effective_at, 1)),
             ("3 seed v2", SEED_FILES[2], seed_sql(effective_at, 2)),
             ("4 seed age_14", SEED_AGE14_FILE, seed_age14_sql(effective_at)),
             ("5 seed v3", SEED_FILES[3], seed_sql(effective_at, 3)),
             ("6 seed v4", SEED_FILES[4], seed_sql(effective_at, 4)),
             ("7 seed v5", SEED_FILES[5], seed_sql(effective_at, 5)),
             # PRD-17-22~25(2026-11-23): 8 열거형은 따로 커밋한 뒤 9·10 시드(새 enum 값은 같은 트랜잭션에서 쓸 수 없다)
             ("9 seed terms_guest v1", SEED_GUEST_FILE, seed_guest_sql(effective_at)),
             ("10 seed v6", SEED_FILES[6], seed_sql(effective_at, 6)),
             # 2026-11-23 최종안 반영: 13은 맨 뒤 번호(기존 단계 번호 유지), 실행은 12 뒤. terms_guest 열거형(8) 이후라야 한다
             ("13 seed final legal docs", SEED_FINAL_FILE, seed_final_sql(effective_at))]  # PRD-17-18 A: terms·privacy_policy v3(연락처 줄 구분). age_14 뒤에 둬 기존 단계 번호 유지. v4는 v3 뒤(처리방침 v4, BE-14-09 A)
    masked: tuple[str, ...] = ()
    if contact_set(contact):
        name, email = (contact[0] or "").strip(), (contact[1] or "").strip()  # type: ignore[index]
        masked = (name, email)
        try:
            seeds = [(n, p, render_privacy_contact(sql, name, email)) for n, p, sql in seeds]
        except ValueError as exc:
            raise Refused(f"보호책임자 값 거부: {exc}") from None
    seed_steps = [Step(n, "seed", p, sql, masked) for n, p, sql in seeds]
    enum_step = Step("8 enum terms_guest", "enum", MIGRATE_GUEST_ENUM_FILE, migrate_guest_enum_sql())
    avatar_step = Step("11 migrate profiles.avatar_color", "avatar", MIGRATE_AVATAR_COLOR_FILE, migrate_avatar_color_sql())  # 2026-11-23 병아리 배경색 8색
    target_step = Step("12 migrate app_users.default_target", "default_target", MIGRATE_DEFAULT_TARGET_FILE, migrate_default_target_sql())  # 2026-11-23 FE-17 U-08
    return [Step("1 schema", "schema", SCHEMA_FILE, schema_sql()), *seed_steps[:6], enum_step, *seed_steps[6:8], avatar_step, target_step, seed_steps[8]]


def scrub(text: str, masked: tuple[str, ...]) -> str:
    """보호책임자 값을 `<설정됨>`으로 가린다(DB 오류 문구에 SQL 조각이 실릴 수 있음)."""
    for v in masked:
        if v:
            text = text.replace(v, "<설정됨>")
    return text


def expected_keys(steps: list[Step]) -> list[tuple[str, int]]:
    return [k for s in steps for k in s.keys]


def check_publishable(steps: list[Step]) -> None:
    """시드마다 assert_publishable. 하나라도 자리표시가 남으면 Refused(어느 시드·어떤 자리표시인지)."""
    bad = []
    for s in steps:
        if s.kind != "seed":
            continue
        try:
            assert_publishable(s.sql)
        except ValueError as exc:
            bad.append(f"{s.source.name}: {exc}")
    if bad:
        raise Refused("자리표시가 남은 시드가 있어 apply 거부 — " + " / ".join(bad))


def parse_effective_at(text: str | None) -> datetime | None:
    if text is None:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise Refused(f"--effective-at 형식이 아니다(ISO 8601): {text!r}") from None
    if dt.tzinfo is None:
        raise Refused("--effective-at에는 시간대가 있어야 한다(예: 2026-11-21T00:00:00+09:00)")
    return dt


def is_local_dsn(dsn: str) -> bool:
    import psycopg  # noqa: PLC0415

    try:
        info = psycopg.conninfo.conninfo_to_dict(dsn)
    except Exception:  # noqa: BLE001 - 형식 오류 문구에 값이 섞일 수 있어 판정만 돌려준다
        return False
    hosts = str(info.get("host") or "/").split(",")
    return all(h.startswith(LOCAL_HOSTS) for h in hosts)


def gate(args: argparse.Namespace, flag: Path, local: bool) -> None:
    """apply 이중 안전장치(연결 전): --yes + 승인 파일(원격만). 로컬 DSN은 승인 파일을 보지 않는다."""
    if not args.yes:
        raise Refused("apply는 --yes가 필요하다")
    if not local and not flag.is_file():
        raise Refused(f"승인 파일이 없다: {flag.name}(메인 세션이 실행 직전에 data/mock/review/에 만들고 직후 지운다)")
    if args.effective_at is None:
        raise Refused("apply는 --effective-at(시행 시각, 시간대 포함)이 필요하다(날짜를 지어내지 않는다)")


# --------------------------------------------------------------------------- 연결·상태(읽기)

def connect(dsn: str, read_only: bool, connect_fn: Callable[[str], Any] | None = None) -> Any:
    if connect_fn is None:
        import psycopg  # noqa: PLC0415

        connect_fn = psycopg.connect
    conn = connect_fn(dsn)
    if read_only:
        conn.read_only = True
    return conn


def _one(cur: Any, sql: str, params: tuple[Any, ...] | None = None) -> Any:
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def state(cur: Any) -> dict[str, Any]:
    """읽기만. 없는 객체는 to_regclass·카탈로그로 확인해 오류 없이 비어 있게 돌려준다."""
    out: dict[str, Any] = {
        "auth_users": bool(_one(cur, "SELECT to_regclass('auth.users') IS NOT NULL")),
        "auth_uid": bool(_one(cur, "SELECT to_regprocedure('auth.uid()') IS NOT NULL")),
    }
    cur.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') ORDER BY 1")
    out["roles"] = [r[0] for r in cur.fetchall()]
    out["account_schema"] = bool(_one(cur, "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'account')"))
    cur.execute(
        "SELECT c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'account' AND c.relkind = 'r' ORDER BY 1")
    rls = {r[0]: bool(r[1]) for r in cur.fetchall()}
    out["tables"] = sorted(rls)
    out["rls_off"] = sorted(t for t in TABLES if t in rls and not rls[t])
    cur.execute(
        "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid JOIN pg_namespace n ON n.oid = t.typnamespace "
        "WHERE n.nspname = 'account' AND t.typname = 'doc_type' ORDER BY e.enumsortorder")
    out["doc_type_values"] = [r[0] for r in cur.fetchall()]
    out["sex_column"] = bool(_one(
        cur, "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
             "WHERE table_schema = 'account' AND table_name = 'profiles' AND column_name = 'sex')"))
    out["avatar_color_column"] = bool(_one(
        cur, "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
             "WHERE table_schema = 'account' AND table_name = 'profiles' AND column_name = 'avatar_color')"))
    out["avatar_color_check"] = bool(_one(
        cur, "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'profiles_avatar_color_check' "
             "AND conrelid = to_regclass('account.profiles'))"))
    # 기존 행 값 확인(null 없음 = 기본값 채움). 열이 없으면 건너뛴다(None). 행 수만 센다(값·식별자 출력 없음)
    out["avatar_color_nulls"] = (int(_one(cur, "SELECT COUNT(*) FROM account.profiles WHERE avatar_color IS NULL"))
                                 if out["avatar_color_column"] else None)
    # 기본 프로필(단계 12): 열 둘·FK·CHECK. 값·식별자는 읽지 않는다
    out["default_target_columns"] = int(_one(
        cur, "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = 'account' AND table_name = 'app_users' "
             "AND column_name IN ('default_profile_id', 'default_guest')"))
    out["default_target_fk"] = bool(_one(
        cur, "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'app_users_default_profile_fk' "
             "AND conrelid = to_regclass('account.app_users'))"))
    out["default_target_check"] = bool(_one(
        cur, "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'app_users_default_target_check' "
             "AND conrelid = to_regclass('account.app_users'))"))
    out["legal_rows"], out["legal_current"] = [], []
    if _one(cur, "SELECT to_regclass('account.legal_documents') IS NOT NULL"):
        cur.execute("SELECT doc_type::text, version, status::text FROM account.legal_documents ORDER BY 1, 2")
        out["legal_rows"] = [[r[0], int(r[1]), r[2]] for r in cur.fetchall()]
    if _one(cur, "SELECT to_regclass('account.legal_current') IS NOT NULL"):
        cur.execute("SELECT doc_type::text, version FROM account.legal_current ORDER BY 1")
        out["legal_current"] = [[r[0], int(r[1])] for r in cur.fetchall()]
    return out


def read_state(conn: Any) -> dict[str, Any]:
    try:
        return state(conn.cursor())
    finally:
        conn.rollback()  # 읽기 트랜잭션 종료


def auth_ready(st: dict[str, Any]) -> bool:
    return st["auth_users"] and st["auth_uid"] and st["roles"] == ["anon", "authenticated"]


def schema_ok(st: dict[str, Any]) -> list[str]:
    """스키마 단계 사후 확인. 문제 목록(빈 목록이면 통과)."""
    problems = []
    missing = [t for t in TABLES if t not in st["tables"]]
    if missing:
        problems.append(f"없는 표 {missing}")
    if st["rls_off"]:
        problems.append(f"RLS 꺼진 표 {st['rls_off']}")
    if "age_14" not in st["doc_type_values"]:
        problems.append("doc_type에 age_14 없음")
    if not st["sex_column"]:
        problems.append("profiles.sex 열 없음")
    return problems


def avatar_problems(st: dict[str, Any]) -> list[str]:
    """단계 11 사후 확인. 열·CHECK 존재, 기존 행에 null 없음."""
    problems = []
    if not st.get("avatar_color_column"):
        problems.append("profiles.avatar_color 열 없음")
    if not st.get("avatar_color_check"):
        problems.append("profiles_avatar_color_check 제약 없음")
    if st.get("avatar_color_nulls"):
        problems.append(f"avatar_color null 행 {st['avatar_color_nulls']}개")
    return problems


def default_target_problems(st: dict[str, Any]) -> list[str]:
    """단계 12 사후 확인. 열 두 개·FK·CHECK 존재."""
    problems = []
    if st.get("default_target_columns") != 2:
        problems.append("app_users.default_profile_id·default_guest 열 없음")
    if not st.get("default_target_fk"):
        problems.append("app_users_default_profile_fk 제약 없음")
    if not st.get("default_target_check"):
        problems.append("app_users_default_target_check 제약 없음")
    return problems


def present_keys(st: dict[str, Any], keys: list[tuple[str, int]]) -> list[tuple[str, int]]:
    have = {(t, v) for t, v, status in st["legal_rows"] if status == "published"}
    return [k for k in keys if k in have]


# --------------------------------------------------------------------------- plan / apply / verify

def step_summary(s: Step) -> dict[str, Any]:
    raw = s.source.read_bytes()
    return {"step": s.name, "file": str(s.source.relative_to(REPO)), "sha256": hashlib.sha256(raw).hexdigest()[:16],
            "bytes": len(raw), "rows": [f"{t} v{v}" for t, v in s.keys], "placeholders_left": s.placeholders}


def do_plan(conn: Any, steps: list[Step], log: Callable[[str], None] = print) -> dict[str, Any]:
    st = read_state(conn)
    keys = expected_keys(steps)
    have = present_keys(st, keys)
    out = {
        "state": st,
        "auth_ready": auth_ready(st),
        "steps": [step_summary(s) for s in steps],
        "schema_needed": bool(schema_ok(st)),
        "avatar_color_needed": bool(avatar_problems(st)),
        "default_target_needed": bool(default_target_problems(st)),
        "seed_rows_to_insert": [f"{t} v{v}" for t, v in keys if (t, v) not in have],
        "publishable": not any(s.placeholders for s in steps),
        "privacy_contact": "<설정됨>" if any(s.masked for s in steps) else "<없음>",  # 값은 출력하지 않는다
    }
    log(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return out


def transaction(conn: Any, name: str, fn: Callable[[Any], dict[str, Any]], log: Callable[[str], None] = print,
                masked: tuple[str, ...] = ()) -> dict[str, Any]:
    """한 트랜잭션으로 fn을 실행한다. 예외면 롤백하고 StageAbort로 올린다. 커밋은 fn이 끝난 뒤 한 번만."""
    cur = conn.cursor()
    try:
        cur.execute("SET LOCAL lock_timeout = '10s'")
        cur.execute("SET LOCAL statement_timeout = '60s'")
        res = fn(cur)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        msg = scrub(redact(str(exc)), masked)[:200]
        log(f"[{name}] 롤백: {type(exc).__name__}: {msg}")
        raise StageAbort(f"{name}: {type(exc).__name__}: {msg}") from None
    log(f"[{name}] 커밋: {json.dumps(res, ensure_ascii=False, default=str)}")
    return res


def run_schema(cur: Any, step: Step) -> dict[str, Any]:
    cur.execute(step.sql)
    return {"file": step.source.name}


def run_seed(cur: Any, step: Step) -> dict[str, Any]:
    assert_publishable(step.sql)  # 실행 직전에 한 번 더(ValueError → 롤백·중단)
    n_before = int(_one(cur, "SELECT COUNT(*) FROM account.legal_documents"))
    cur.execute(step.sql)
    n_after = int(_one(cur, "SELECT COUNT(*) FROM account.legal_documents"))
    cur.execute("SELECT doc_type::text, version, status::text FROM account.legal_documents ORDER BY 1, 2")
    have = {(r[0], int(r[1])) for r in cur.fetchall() if r[2] == "published"}
    missing = [f"{t} v{v}" for t, v in step.keys if (t, v) not in have]
    if missing:
        raise StageAbort(f"게시된 행이 없음: {missing}")
    if not 0 <= n_after - n_before <= len(step.keys):
        raise StageAbort(f"legal_documents 행 수 변화가 기대 밖: {n_before}→{n_after}")
    return {"file": step.source.name, "legal_documents": [n_before, n_after], "inserted": n_after - n_before}


def do_apply(conn: Any, steps: list[Step], log: Callable[[str], None] = print) -> dict[str, Any]:
    check_publishable(steps)  # 연결을 썼더라도 쓰기 전에 한 번 더
    before = read_state(conn)
    if not auth_ready(before):
        raise StageAbort("auth.users·auth.uid()·anon·authenticated 역할이 없다(Supabase가 아니거나 로컬 스텁 미설치)")
    report: dict[str, Any] = {"before": before}
    for s in steps:
        if s.kind == "enum":
            report[s.name] = transaction(conn, s.name, lambda cur, s=s: run_schema(cur, s), log)
            if "terms_guest" not in read_state(conn)["doc_type_values"]:  # ADD VALUE는 커밋 뒤에 보인다
                raise StageAbort(f"{s.name} 사후 확인 실패: doc_type에 terms_guest 없음")
        elif s.kind == "avatar":
            report[s.name] = transaction(conn, s.name, lambda cur, s=s: run_schema(cur, s), log)
            problems = avatar_problems(read_state(conn))
            if problems:
                raise StageAbort(f"{s.name} 사후 확인 실패: {problems}")
        elif s.kind == "default_target":
            report[s.name] = transaction(conn, s.name, lambda cur, s=s: run_schema(cur, s), log)
            problems = default_target_problems(read_state(conn))
            if problems:
                raise StageAbort(f"{s.name} 사후 확인 실패: {problems}")
        elif s.kind == "schema":
            report[s.name] = transaction(conn, s.name, lambda cur, s=s: run_schema(cur, s), log)
            problems = schema_ok(read_state(conn))  # ADD VALUE는 커밋 뒤에 보인다
            if problems:
                raise StageAbort(f"{s.name} 사후 확인 실패: {problems}")
        else:
            report[s.name] = transaction(conn, s.name, lambda cur, s=s: run_seed(cur, s), log, s.masked)
    report["after"] = read_state(conn)
    return report


def do_verify(conn: Any, steps: list[Step], log: Callable[[str], None] = print) -> dict[str, Any]:
    st = read_state(conn)
    keys = expected_keys(steps)
    missing = [f"{t} v{v}" for t, v in keys if (t, v) not in present_keys(st, keys)]
    checks = {
        "auth_ready": auth_ready(st),
        "schema_problems": schema_ok(st),
        "seed_rows_missing": missing,
        "age_14_current": ["age_14", 1] in st["legal_current"],
        # 2026-11-23 최종안 반영: 현재 판은 terms v4·privacy_policy v7·privacy_consent v3·sensitive_consent v3·terms_guest v2(단계 13)
        "final_terms_privacy_current": ["terms", 4] in st["legal_current"] and ["privacy_policy", 7] in st["legal_current"],
        "final_consents_current": ["privacy_consent", 3] in st["legal_current"] and ["sensitive_consent", 3] in st["legal_current"],
        "terms_guest_enum": "terms_guest" in st["doc_type_values"],
        "terms_guest_v2_current": ["terms_guest", 2] in st["legal_current"],
        "avatar_color_problems": avatar_problems(st),
        "default_target_problems": default_target_problems(st),
    }
    ok = (checks["auth_ready"] and not checks["schema_problems"] and not missing and checks["age_14_current"]
          and checks["final_terms_privacy_current"] and checks["final_consents_current"]
          and checks["terms_guest_enum"] and checks["terms_guest_v2_current"]
          and not checks["avatar_color_problems"] and not checks["default_target_problems"])
    out = {"ok": ok, "checks": checks, "state": st}
    log(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return out


# --------------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="plan", choices=("plan", "apply", "verify"))
    ap.add_argument("--yes", action="store_true", help="apply 확인")
    ap.add_argument("--effective-at", help="약관 시행 시각(ISO 8601, 시간대 포함). apply 필수")
    ap.add_argument("--local-dsn", help="로컬 Postgres 시험용 DSN(로컬 호스트만, 승인 파일 불필요)")
    return ap


def main(argv: list[str] | None = None, *, connect_fn: Callable[[str], Any] | None = None, flag: Path = APPROVAL_FLAG,
         log: Callable[[str], None] = print, contact: PrivacyContact | None = None) -> dict[str, Any]:
    """`contact`를 주지 않으면 env(Settings)의 보호책임자 값을 읽는다(시험은 가짜 값을 직접 준다)."""
    args = build_parser().parse_args(argv)
    local = args.local_dsn is not None
    if local and not is_local_dsn(args.local_dsn):
        raise Refused("--local-dsn은 로컬 주소만 받는다(원격은 SUPABASE_DB_URL + 승인 파일)")
    effective_at = parse_effective_at(args.effective_at)
    if args.cmd == "apply":
        gate(args, flag, local)  # 연결 전에 거부
    steps = build_steps(effective_at or datetime.now(UTC), privacy_officer() if contact is None else contact)
    if args.cmd == "apply":
        check_publishable(steps)  # 연결 전에 거부
    dsn = args.local_dsn if local else resolve_dsn(DSN_ENV)
    if not dsn:
        raise Refused(f"{DSN_ENV} 값을 찾지 못했다")
    out: dict[str, Any] = {"cmd": args.cmd, "target": "local" if local else "remote",
                           "effective_at": effective_at.isoformat() if effective_at else None}
    conn = connect(dsn, read_only=args.cmd != "apply", connect_fn=connect_fn)
    try:
        if args.cmd == "plan":
            out["plan"] = do_plan(conn, steps, log)
        elif args.cmd == "verify":
            out["verify"] = do_verify(conn, steps, log)
        else:
            out["apply"] = do_apply(conn, steps, log)
            log(json.dumps({"done": True, "after": out["apply"]["after"]}, ensure_ascii=False, default=str))
    finally:
        conn.close()
    return out


if __name__ == "__main__":
    install_excepthook()  # 처리되지 않은 예외·logging 출력에서 DSN·키 가리기
    try:
        res = main()
        sys.exit(0 if res.get("cmd") != "verify" or res["verify"]["ok"] else 1)
    except (Refused, RemoteLoadRefused) as e:
        print(f"거부: {redact(str(e))}", file=sys.stderr)
        sys.exit(2)
    except StageAbort as e:
        print(f"중단: {redact(str(e))}", file=sys.stderr)
        sys.exit(3)
