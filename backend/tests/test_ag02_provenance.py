"""AG-02: 표시 계약 상수(`PUBLISHER`·`DATASET_LABELS`·`DATE_LABELS`·`SOURCE_KIND`)의 정의는 `provenance.py` 한 곳이다(PRD-12-03)."""

from __future__ import annotations

import re
from pathlib import Path

from app.tools import provenance as P

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
DEFINE = re.compile(r"^(PUBLISHER|DATASET_LABELS|DATE_LABELS|SOURCE_KIND|DATASET_PUBLISHER|FLAG_NOTES)\s*[:=]", re.MULTILINE)


def test_constants_defined_only_in_provenance():
    hits = [(f.relative_to(ROOT).as_posix(), m.group(1)) for f in APP.rglob("*.py") for m in DEFINE.finditer(f.read_text(encoding="utf-8"))]
    assert hits and {h[0] for h in hits} == {"app/tools/provenance.py"}, hits
    assert {h[1] for h in hits} >= {"PUBLISHER", "DATASET_LABELS", "DATE_LABELS", "SOURCE_KIND"}


def test_dataset_label_strings_appear_once():
    """자료 약칭 문자열 리터럴이 provenance 밖에 없다(grep)."""
    labels = set(P.DATASET_LABELS.values()) - {"의약품 허가정보"}  # 같은 자료가 두 키에 쓰이는 값은 키 단위로 이미 한 곳
    for f in APP.rglob("*.py"):
        if f.name == "provenance.py":
            continue
        text = f.read_text(encoding="utf-8")
        for lab in labels:
            assert f'"{lab}"' not in text, (f.name, lab)


def test_every_dataset_key_in_lookup_has_label_and_publisher():
    from app.tools.lookup import DATASET_KEYS
    assert set(DATASET_KEYS) <= set(P.DATASET_LABELS) and set(DATASET_KEYS) <= set(P.DATASET_PUBLISHER)
    assert set(P.DATASET_LABELS) == set(P.DATASET_PUBLISHER)
    assert set(P.DATASET_PUBLISHER.values()) <= set(P.PUBLISHER)


def test_badge_format():
    assert P.badge("FILE", "contra_pair") == "공식 파일 · 병용금기 파일"
    assert P.badge("CORPUS_QUOTE", "eyak") == "공식 문서 · e약은요 쉬운 설명"
    assert set(P.SOURCE_KIND) == {"API_DIRECT", "FILE", "CORPUS_QUOTE"}
