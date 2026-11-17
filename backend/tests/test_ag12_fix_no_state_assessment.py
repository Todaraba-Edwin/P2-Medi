"""AG-12-02 A: `NO_STATE_ASSESSMENT`를 `expected.required_elements`에서 최상위 `required_elements`로 옮기는 소수정 스크립트 시험.

합성 행만 쓴다(개발셋·시험셋 문항 아님). 시험셋 파일은 열지 않는다(tmp의 가짜 SEALED 이름 파일로 가드만 본다).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "evaluation", ROOT / "evaluation" / "eval_set"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import fix_no_state_assessment as F  # noqa: E402
import sealed_guard as G  # noqa: E402


def _row(iid: str, **kw) -> dict:
    base = {"id": iid, "question": "가짜", "required_elements": ["REFUSAL_WITH_REASON", "PHARMACIST_NOTICE", "DISCLAIMER"], "human_review": {}}
    base.update(kw)
    return base


def _jsonl(rows: list[dict]) -> bytes:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")


def test_fix_moves_element_and_cleans_expected():
    rows = [_row("f-1", expected={"required_elements": ["NO_STATE_ASSESSMENT"]}),  # 대상: 이동 + expected 삭제
            _row("f-2"),  # 대상 아님
            _row("f-3", expected={"required_elements": ["NO_STATE_ASSESSMENT"], "note": "유지"}),  # expected의 다른 키는 남긴다
            _row("f-4", required_elements=["PHARMACIST_NOTICE"], expected={"required_elements": ["NO_STATE_ASSESSMENT"]}),  # 앵커 없음 → 끝
            _row("f-5", required_elements=["REFUSAL_WITH_REASON", "NO_STATE_ASSESSMENT"], expected={"required_elements": ["NO_STATE_ASSESSMENT"]})]
    data, changed = F.fix_lines(_jsonl(rows))
    assert changed == ["f-1", "f-3", "f-4", "f-5"]
    out = {r["id"]: r for r in (json.loads(ln) for ln in data.decode("utf-8").splitlines())}
    assert out["f-1"]["required_elements"] == ["REFUSAL_WITH_REASON", "NO_STATE_ASSESSMENT", "PHARMACIST_NOTICE", "DISCLAIMER"]
    assert "expected" not in out["f-1"]
    assert out["f-2"] == rows[1]
    assert out["f-3"]["expected"] == {"note": "유지"} and "NO_STATE_ASSESSMENT" in out["f-3"]["required_elements"]
    assert out["f-4"]["required_elements"] == ["PHARMACIST_NOTICE", "NO_STATE_ASSESSMENT"]
    assert out["f-5"]["required_elements"] == ["REFUSAL_WITH_REASON", "NO_STATE_ASSESSMENT"] and "expected" not in out["f-5"]
    # 멱등: 다시 돌리면 바뀌는 행 0, 바이트 동일
    again, changed2 = F.fix_lines(data)
    assert changed2 == [] and again == data
    # 바꾸지 않은 줄은 바이트 그대로
    assert _jsonl([rows[1]]) in data


def test_fix_refuses_unexpected_serialization():
    raw = b'{"id": "f-1",  "required_elements": ["REFUSAL_WITH_REASON"], "expected": {"required_elements": ["NO_STATE_ASSESSMENT"]}}\n'
    with pytest.raises(F.FixError):
        F.fix_lines(raw)


def test_cli_check_and_write_with_manifest(tmp_path: Path, capsys):
    set_path = tmp_path / "dev_set.jsonl"
    rows = [_row("f-1", expected={"required_elements": ["NO_STATE_ASSESSMENT"]}), _row("f-2")]
    set_path.write_bytes(_jsonl(rows))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"sets": {"dev": {"file": "dev_set.jsonl", "sha256": "x", "bytes": 0}}, "last_updated": "2026-11-17",
                                    "last_change_reason": "이전 사유"}), encoding="utf-8")
    before = set_path.read_bytes()
    assert F.main(["--set", str(set_path), "--manifest", str(manifest), "--check"]) == 0
    assert set_path.read_bytes() == before and "바뀔 행 1 ids=f-1" in capsys.readouterr().out
    assert F.main(["--set", str(set_path), "--manifest", str(manifest)]) == 0
    data = set_path.read_bytes()
    assert data != before and (tmp_path / "dev_set.jsonl.bak").read_bytes() == before
    man = json.loads(manifest.read_text(encoding="utf-8"))
    assert man["sets"]["dev"]["sha256"] == hashlib.sha256(data).hexdigest() and man["sets"]["dev"]["bytes"] == len(data)
    assert man["last_change_reason"] == F.CHANGE_REASON and man["change_history"] == [{"date": "2026-11-17", "reason": "이전 사유"}]
    # 두 번째 실행: 바뀌는 행 0, 파일·manifest 그대로
    assert F.main(["--set", str(set_path), "--manifest", str(manifest)]) == 0
    assert set_path.read_bytes() == data and "바뀔 행 0" in capsys.readouterr().out


def test_sealed_guard_blocks_before_open(tmp_path: Path, monkeypatch):
    sealed = tmp_path / "test_set.SEALED.jsonl"
    sealed.write_bytes(b"")

    def boom(self, *a, **k):  # noqa: ARG001
        raise AssertionError("파일을 열었다")

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(G.SealedAccessError):
        F.main(["--set", str(sealed), "--check"])
    with pytest.raises(G.SealedAccessError):
        F.main(["--set", str(sealed), "--allow-sealed", "--check"])  # 환경변수 없이 플래그만으로는 안 된다


def test_sealed_output_hides_ids(tmp_path: Path, monkeypatch, capsys):
    sealed = tmp_path / "test_set.SEALED.jsonl"
    sealed.write_bytes(_jsonl([_row("secret-1", expected={"required_elements": ["NO_STATE_ASSESSMENT"]})]))
    monkeypatch.setenv(G.SEALED_ENV, G.SEALED_ENV_VALUE)
    assert F.main(["--set", str(sealed), "--allow-sealed", "--check"]) == 0
    out = capsys.readouterr().out
    assert "test(sealed): 바뀔 행 1" in out and "secret-1" not in out
