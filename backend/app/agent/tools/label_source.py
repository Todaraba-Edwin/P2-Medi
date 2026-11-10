"""라벨 원문 공급자와 허가 상세 XML 절 추출.

`SnapshotLabelProvider`는 로컬 스냅샷(`data/mock/api_snapshots/prmsn-detail/`, `eyak-all/`)만 읽는다(평가 모드, 네트워크 없음).
`data/`가 없으면 None을 돌려줘 "원문 없음"이 된다. 서비스 근거 데이터가 아니라 개발·평가용이다.
"""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SNAPSHOT_ROOT = Path(__file__).resolve().parents[4] / "data" / "mock" / "api_snapshots"
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

# 허가 상세 절 문서(`*_DOC_DATA`)와 한글 절 이름
PRMSN_DOCS = {"효능": "EE_DOC_DATA", "용법용량": "UD_DOC_DATA", "주의사항": "NB_DOC_DATA"}
PRMSN_DOC_CODE = {"효능": "EE", "용법용량": "UD", "주의사항": "NB"}
# e약은요 필드
EYAK_FIELDS = {"효능": "efcy", "사용법": "use_method", "경고": "atpn_warn", "주의사항": "atpn", "상호작용": "intrc", "부작용": "se"}


def extract_doc_text(xml: str | None) -> str:
    """허가 상세 XML(`<DOC>…<PARAGRAPH><![CDATA[..]]>`)에서 문단 원문을 줄바꿈으로 잇는다. 본문은 고치지 않는다(엔티티만 풀어 쓴다)."""
    if not xml:
        return ""
    parts = [html.unescape(m.group(1)).strip() for m in _CDATA_RE.finditer(xml)]
    if not parts:  # CDATA가 없으면 태그를 걷어낸다
        parts = [html.unescape(_TAG_RE.sub("", xml)).strip()]
    return "\n".join(p for p in parts if p)


class SnapshotLabelProvider:
    def __init__(self, root: Path = SNAPSHOT_ROOT) -> None:
        self.root = Path(root)
        self._eyak_index: dict[str, tuple[Path, dict[str, Any]]] | None = None

    def prmsn_detail(self, item_seq: str) -> dict[str, Any] | None:
        f = self.root / "prmsn-detail" / f"item-{item_seq}.json"
        if not f.is_file():
            return None
        d = json.loads(f.read_text(encoding="utf-8"))
        resp = d.get("response") or []
        if not resp:
            return None
        return {"item": resp[0], "collected_at": d.get("fetched_at"), "source": "snapshot"}

    def _index(self) -> dict[str, tuple[Path, dict[str, Any]]]:
        if self._eyak_index is None:
            idx: dict[str, tuple[Path, dict[str, Any]]] = {}
            for f in sorted((self.root / "eyak-all").glob("page-*.json")):
                for it in json.loads(f.read_text(encoding="utf-8")).get("items", []):
                    idx[str(it.get("item_seq"))] = (f, it)
            self._eyak_index = idx
        return self._eyak_index

    def eyak(self, item_seq: str) -> dict[str, Any] | None:
        hit = self._index().get(item_seq)
        if hit is None:
            return None
        f, it = hit
        ts = datetime.fromtimestamp(f.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")  # 파일 수정 시각을 수집 시각으로 쓴다(스냅샷은 실제 조회가 아니다)
        return {"item": it, "collected_at": ts, "source": "snapshot"}
