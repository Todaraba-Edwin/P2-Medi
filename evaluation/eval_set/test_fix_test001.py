"""AG-20-01 A `fix_test001_reference.py` 시험. 합성 jsonl fixture만 쓰고 실제 시험셋은 열지 않는다."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fix_test001_reference as F
import pytest
import sealed_guard as G

MEMO_REF = "아스피린과(와) 와파린은(는) 병용금기 목록에 올라 있다(고시 제2026-1호)(RFP-21 §4.6). 사유: 출혈 위험. 출처 한국의약품안전관리원, 기준일 2026-07-31."
CLEAN_REF = "아스피린과(와) 와파린은(는) 병용금기 목록에 올라 있다(고시 제2026-1호). 사유: 출혈 위험. 출처 한국의약품안전관리원, 기준일 2026-07-31."
OTHER_REF = "다른 문항(RFP-99 §1 참조)은 건드리지 않는다."


def _row(rid: str, ref: str) -> dict:
    return {"id": rid, "set": "test", "question": f"{rid} 질문", "reference": ref, "answer": {"note": "RFP-5 다른 칸"}}


def _write(path: Path, rows: list[dict], trailing: str = "\n") -> bytes:
    data = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8") + trailing.encode("utf-8")
    path.write_bytes(data)
    return data


def _manifest(path: Path, file_name: str, data: bytes) -> Path:
    man = {"sets": {"test": {"file": file_name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}},
           "last_updated": "2026-11-17", "last_change_reason": "이전 이유"}
    path.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def fx(tmp_path: Path):
    rows = [_row("test-000", OTHER_REF), _row("test-001", MEMO_REF), _row("test-002", "정상 문장.")]
    set_path = tmp_path / "fixture_set.jsonl"
    raw = _write(set_path, rows)
    man = _manifest(tmp_path / "manifest.json", set_path.name, raw)
    return set_path, man, raw, tmp_path / "bak"


def _run(set_path: Path, man: Path, bak: Path, *extra: str) -> int:
    return F.main(["--set", str(set_path), "--manifest", str(man), "--backup-dir", str(bak), *extra])


# --- 패턴 ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("src", "want"), [
    (MEMO_REF, CLEAN_REF),
    ("문장이다(RFP-21).", "문장이다."),
    ("문장이다 (RFP-21-02, RFP-23 §5.1).", "문장이다."),
    ("문장이다(내부 메모: RFP-21 §4.6 참조).", "문장이다."),
    ("문장이다(고시 제1호, RFP-21 §4.6).", "문장이다(고시 제1호)."),
    ("문장이다(RFP-21 §4.6 · 고시 제1호).", "문장이다(고시 제1호)."),
    ("RFP-21 §4.6: 문장이다.", "문장이다."),
    ("문장이다, RFP-21 §4.6 참조.", "문장이다."),
    ("문장이다. RFP-21 §4.6", "문장이다."),
    ("메모 없는 문장(고시 2026-1).", "메모 없는 문장(고시 2026-1)."),
])
def test_strip_memo_patterns(src: str, want: str):
    assert F.strip_memo(src) == want
    assert F.strip_memo(want) == want  # 멱등


def test_unknown_form_fails_instead_of_guessing():
    with pytest.raises(F.FixError, match="남아"):
        F.fix_row({"reference": "문장이다(RFP-21 §4.6 확인 필요)."})
    with pytest.raises(F.FixError, match="남아"):
        F.fix_row({"reference": "문장이다 rfp-21."})


def test_empty_after_strip_fails():
    with pytest.raises(F.FixError, match="비어"):
        F.fix_row({"reference": "RFP-21 §4.6"})


def test_non_string_reference_fails():
    with pytest.raises(F.FixError, match="문자열"):
        F.fix_row({"reference": None})


# --- 파일 단위 -------------------------------------------------------------------------------------------
def test_only_test001_reference_changes_and_other_lines_bytes_same(fx):
    set_path, man, raw, bak = fx
    assert _run(set_path, man, bak) == 0
    old, new = raw.decode().splitlines(keepends=True), set_path.read_bytes().decode().splitlines(keepends=True)
    assert len(old) == len(new)
    assert old[0] == new[0] and old[2] == new[2]  # 나머지 줄은 바이트 그대로
    before, after = json.loads(old[1]), json.loads(new[1])
    assert after["reference"] == CLEAN_REF
    assert {k: v for k, v in after.items() if k != "reference"} == {k: v for k, v in before.items() if k != "reference"}
    assert new[1] == json.dumps(after, ensure_ascii=False) + "\n"
    assert set_path.read_bytes().endswith(b"\n")


def test_idempotent_second_run_zero_rows(fx, capsys):
    set_path, man, _raw, bak = fx
    assert _run(set_path, man, bak) == 0
    once = set_path.read_bytes()
    capsys.readouterr()
    assert _run(set_path, man, bak) == 0
    assert set_path.read_bytes() == once
    assert "바뀔 행 0" in capsys.readouterr().out
    assert len(list(bak.iterdir())) == 1  # 두 번째는 백업도 만들지 않는다


def test_no_memo_zero_rows(tmp_path, capsys):
    set_path = tmp_path / "s.jsonl"
    raw = _write(set_path, [_row("test-001", CLEAN_REF)])
    man = _manifest(tmp_path / "manifest.json", set_path.name, raw)
    assert _run(set_path, man, tmp_path / "bak") == 0
    assert set_path.read_bytes() == raw
    assert "바뀔 행 0" in capsys.readouterr().out
    assert not (tmp_path / "bak").exists()


@pytest.mark.parametrize("ids", [["test-001", "test-001"], ["test-000", "test-002"]])
def test_target_row_count_not_one_fails_without_writing(tmp_path, ids, capsys):
    set_path = tmp_path / "s.jsonl"
    raw = _write(set_path, [_row(i, MEMO_REF) for i in ids])
    man = _manifest(tmp_path / "manifest.json", set_path.name, raw)
    man_before = man.read_bytes()
    assert _run(set_path, man, tmp_path / "bak") == 1
    assert set_path.read_bytes() == raw and man.read_bytes() == man_before
    assert "쓰지 않음" in capsys.readouterr().err


def test_leftover_fails_without_writing(tmp_path):
    set_path = tmp_path / "s.jsonl"
    raw = _write(set_path, [_row("test-001", "문장(RFP-21 확인 필요).")])
    man = _manifest(tmp_path / "manifest.json", set_path.name, raw)
    assert _run(set_path, man, tmp_path / "bak") == 1
    assert set_path.read_bytes() == raw


def test_check_mode_does_not_write(fx, capsys):
    set_path, man, raw, bak = fx
    man_before = man.read_bytes()
    assert _run(set_path, man, bak, "--check") == 0
    assert set_path.read_bytes() == raw and man.read_bytes() == man_before and not bak.exists()
    out = capsys.readouterr().out
    assert "바뀔 행 1" in out and "RFP- 남음 0" in out and "ids=test-001" in out


def test_manifest_sha256_updated_and_history_kept(fx):
    set_path, man, _raw, bak = fx
    assert _run(set_path, man, bak) == 0
    data = set_path.read_bytes()
    m = json.loads(man.read_text(encoding="utf-8"))
    assert m["sets"]["test"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert m["sets"]["test"]["bytes"] == len(data)
    assert m["last_change_reason"] == F.CHANGE_REASON and m["last_updated"] == F.CHANGE_DATE
    assert m["change_history"] == [{"date": "2026-11-17", "reason": "이전 이유"}]


def test_backup_is_original_bytes(fx):
    set_path, man, raw, bak = fx
    assert _run(set_path, man, bak) == 0
    (b,) = bak.iterdir()
    assert b.read_bytes() == raw


# --- 시험셋 가드·출력 -------------------------------------------------------------------------------------
def _sealed_fixture(tmp_path: Path) -> tuple[Path, Path, bytes]:
    set_path = tmp_path / "fixture.SEALED.jsonl"  # 합성 fixture. 이름만 시험셋 꼴
    raw = _write(set_path, [_row("test-000", OTHER_REF), _row("test-001", MEMO_REF)])
    return set_path, _manifest(tmp_path / "manifest.json", set_path.name, raw), raw


@pytest.mark.parametrize(("env", "flag"), [(None, True), (G.SEALED_ENV_VALUE, False), ("wrong", True)])
def test_sealed_guard_blocks_before_open(tmp_path, monkeypatch, env, flag):
    set_path, man, _raw = _sealed_fixture(tmp_path)
    if env is None:
        monkeypatch.delenv(G.SEALED_ENV, raising=False)
    else:
        monkeypatch.setenv(G.SEALED_ENV, env)
    opened: list[str] = []
    real = Path.read_bytes

    def spy(self: Path) -> bytes:
        opened.append(self.name)
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", spy)
    args = ["--set", str(set_path), "--manifest", str(man), "--backup-dir", str(tmp_path / "bak")]
    with pytest.raises(G.SealedAccessError):
        F.main([*args, "--allow-sealed"] if flag else args)
    assert set_path.name not in opened


def test_test_keyword_resolves_to_sealed_path_without_opening(monkeypatch):
    assert F.resolve_set("test") == F.TEST
    assert F.TEST.name == "test_set.SEALED.jsonl" and G.is_sealed(F.TEST)
    monkeypatch.delenv(G.SEALED_ENV, raising=False)
    with pytest.raises(G.SealedAccessError):
        F.main(["--set", "test", "--allow-sealed", "--check"])


@pytest.mark.parametrize("check", [True, False])
def test_sealed_output_has_no_id_or_content(tmp_path, monkeypatch, capsys, check):
    set_path, man, _raw = _sealed_fixture(tmp_path)
    monkeypatch.setenv(G.SEALED_ENV, G.SEALED_ENV_VALUE)
    args = ["--set", str(set_path), "--allow-sealed", "--manifest", str(man), "--backup-dir", str(tmp_path / "bak")]
    assert F.main([*args, "--check"] if check else args) == 0
    cap = capsys.readouterr()
    text = cap.out + cap.err
    assert text.startswith("test(sealed): ")
    assert ("바뀔 행 1" if check else "바뀐 행 1") in text and "RFP- 남음 0" in text
    for secret in ("test-001", "test-000", "ids=", "아스피린", "와파린", "RFP-21", "RFP-99"):
        assert secret not in text
    if not check:
        (b,) = (tmp_path / "bak").iterdir()
        assert G.is_sealed(b)  # 백업에도 가드·.gitignore가 걸린다


def test_sealed_failure_message_has_no_content(tmp_path, monkeypatch, capsys):
    set_path = tmp_path / "fixture.SEALED.jsonl"
    _write(set_path, [_row("test-001", "비밀문장(RFP-21 확인 필요).")])
    man = _manifest(tmp_path / "manifest.json", set_path.name, set_path.read_bytes())
    monkeypatch.setenv(G.SEALED_ENV, G.SEALED_ENV_VALUE)
    assert F.main(["--set", str(set_path), "--allow-sealed", "--manifest", str(man)]) == 1
    cap = capsys.readouterr()
    text = cap.out + cap.err
    assert "test(sealed)" in text and "비밀문장" not in text and "test-001" not in text
