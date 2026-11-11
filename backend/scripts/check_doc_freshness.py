"""데이터 파일 최신본 점검(읽기 전용, BE-16). 로컬 파일 저장 시각(mtime)과 doc_meta의 포털 수정일을 비교해 표로 낸다.

'최신본 아님' = mtime 날짜 < 수정일 → 포털에서 수정된 뒤에 받은 파일이 아니므로 다시 내려받아 확인해야 한다.
'확인 필요'가 나오는 파일이 있어도 종료 코드는 0이다(점검용). 파일·DB·네트워크를 쓰지 않는다.

사용(작업 위치 `backend/`): `.venv/bin/python scripts/check_doc_freshness.py [--data-dir ../data]`
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.doc_meta import DOC_META  # noqa: E402

DEFAULT_DATA = Path(__file__).resolve().parents[2] / "data"
STALE = "최신본 아님(확인 필요)"
OK = "최신"
NO_FILE = "파일 없음"


def _mtime_date(path: Path) -> date:
    return datetime.fromtimestamp(path.stat().st_mtime).date()


def check(data_dir: Path, mtime_of: Callable[[Path], date] = _mtime_date) -> list[dict[str, str]]:
    """수정일이 적힌 문서만 점검한다. `mtime_of`는 시험에서 가짜로 바꾼다."""
    rows = []
    for m in DOC_META.values():
        if not m.modified_date:
            continue
        path = data_dir / m.source_file
        if not path.exists():
            rows.append({"file": m.source_file, "mtime": "-", "modified": m.modified_date, "status": NO_FILE})
            continue
        mt = mtime_of(path)
        status = STALE if mt < date.fromisoformat(m.modified_date) else OK
        rows.append({"file": m.source_file, "mtime": mt.isoformat(), "modified": m.modified_date, "status": status})
    return rows


def render(rows: Sequence[dict[str, str]]) -> str:
    out = ["| 파일 | 로컬 저장 시각 | 포털 수정일 | 판정 |", "|---|---|---|---|"]
    out += [f"| {r['file']} | {r['mtime']} | {r['modified']} | {r['status']} |" for r in rows]
    return "\n".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    args = ap.parse_args(argv)
    rows = check(args.data_dir)
    print(render(rows))
    stale = [r for r in rows if r["status"] == STALE]
    print(f"\n최신본 아님 {len(stale)}건 / 점검 {len(rows)}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
