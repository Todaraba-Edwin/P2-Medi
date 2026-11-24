"""AG-13-41 A: Router 시각·횟수 잡음 규칙 일반화의 **router 단독 전후 비교**(개발셋 150문항, LLM·네트워크·원격 DB 호출 0).

같은 질문·같은 프로필로 `route_input(time_noise=False)`(후보 이전)와 `route_input(time_noise=True)`(후보 켬)를 돌려 엔티티(원문·상태·품목기준코드)·되묻기·분기 라벨이
달라지는 문항을 센다. 보조 문항(`evaluation/eval_set/dev_aux_w32.jsonl`)도 같은 방식으로 따로 센다.

- **개발셋만** 읽는다(`sealed_guard.check_access`가 시험셋 `*.SEALED.jsonl`을 열기 전에 거절한다, RFP-26-04, 9.1절 8번). 세트·manifest는 고치지 않는다.
- 오탐 점검: 켠 쪽에서 **사라진 엔티티가 RESOLVED였거나** 문항의 기대 약(`products`)이 사라졌거나, 되묻기였던 문항이 아닌 쪽으로 바뀐 것은 "확인 필요"로 따로 센다
  (안전 질문이 잘못 달라진 건). 문항 원문은 출력하지 않고 문항 ID·사라진 토큰만 쓴다.
- 소표본이라 유의성을 주장하지 않는다(PJ2-RFP.md 9.1절): k/n만 보고한다.

사용(저장소 루트, 메인 venv):
    backend/.venv/bin/python backend/scripts/ag13_router_ablation.py [--dict-path data/mock/dict/drug_dict.json] [--out-md OUT.md] [--out-json OUT.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evaluation"))

import dev_aux_w32 as AUX  # noqa: E402
import sealed_guard  # noqa: E402

from app.agent import router as R  # noqa: E402
from app.tools.drug_dict import DrugDict, normalize_name  # noqa: E402

DEV_SET = ROOT / "evaluation" / "eval_set" / "dev_set.jsonl"


def _profile(p: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return AUX._graph_profile(p)


def _view(row: Mapping[str, Any], dd: DrugDict, *, time_noise: bool) -> dict[str, Any]:
    res = R.route_input(row["question"], dd, _profile(row.get("profile")), time_noise=time_noise)
    return {"entities": [(e.raw, e.status, e.item_seq) for e in res.entities], "ambiguous": res.ambiguous,
            "clarify": bool(res.clarify), "branch": res.branch_label, "dump": res.model_dump()}


def compare(rows: list[dict[str, Any]], dd: DrugDict) -> dict[str, Any]:
    changed: list[dict[str, Any]] = []
    for r in rows:
        off, on = _view(r, dd, time_noise=False), _view(r, dd, time_noise=True)
        if off["dump"] == on["dump"]:
            continue
        removed = [e for e in off["entities"] if e not in on["entities"]]
        added = [e for e in on["entities"] if e not in off["entities"]]
        expected = [normalize_name(str(p)) for p in r.get("products") or []]
        lost_expected = [e[0] for e in removed if any(normalize_name(e[0]) in p or p in normalize_name(e[0]) for p in expected if p)]
        suspect = bool(any(e[1] == "RESOLVED" for e in removed) or lost_expected or added or (off["ambiguous"] and not on["ambiguous"] and r.get("expected_response_type") == "clarify"))
        changed.append({"id": r.get("id"), "removed": [[e[0], e[1]] for e in removed], "added": [[e[0], e[1]] for e in added],
                        "ambiguous": [off["ambiguous"], on["ambiguous"]], "branch": [off["branch"], on["branch"]],
                        "expected_response_type": r.get("expected_response_type"), "false_positive_suspect": suspect})
    return {"n": len(rows), "k_changed": len(changed), "k_false_positive_suspect": sum(c["false_positive_suspect"] for c in changed), "changed": changed}


def render_md(dev: Mapping[str, Any], aux: Mapping[str, Any], dict_version: str) -> str:
    def block(title: str, rep: Mapping[str, Any]) -> list[str]:
        out = [f"## {title}", "", f"- 달라진 문항 {rep['k_changed']}/{rep['n']}, 오탐 의심(RESOLVED·기대 약이 사라지거나 엔티티가 더해짐, 되묻기 기대 문항의 되묻기 소실) "
               f"{rep['k_false_positive_suspect']}/{rep['n']}"]
        if rep["changed"]:
            out += ["", "| 문항 | 사라진 엔티티(원문·상태) | 되묻기 전→후 | 오탐 의심 |", "|---|---|---|---|"]
            for c in rep["changed"]:
                rem = ", ".join(f"{a}({b})" for a, b in c["removed"]) or "-"
                out.append(f"| {c['id']} | {rem} | {c['ambiguous'][0]}→{c['ambiguous'][1]} | {'예' if c['false_positive_suspect'] else '아니오'} |")
        return [*out, ""]

    lines = ["# AG-13-41 Router 시각·횟수 잡음 일반화: router 단독 전후 비교", "",
             f"- 사전 `{dict_version}`, LLM·네트워크·원격 DB 호출 0. 전 = `time_noise=False`(후보 이전), 후 = `time_noise=True`(후보 켬)", ""]
    lines += block("개발셋 150문항", dev) + block("개발 보조 문항(dev_aux_w32, 시각·횟수·보호 짝·확정 선택)", aux)
    lines += ["소표본이라 유의성을 주장하지 않는다(PJ2-RFP.md 9.1절). 시험셋은 열지 않았다.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dev-set", default=str(DEV_SET))
    ap.add_argument("--dict-path")
    ap.add_argument("--out-md")
    ap.add_argument("--out-json")
    a = ap.parse_args(argv)
    sealed_guard.check_access(a.dev_set, allow_sealed=False)
    rows = [json.loads(line) for line in Path(a.dev_set).read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(r.get("set") != "dev" for r in rows):
        raise SystemExit("개발셋이 아닌 행이 있다(set != dev): 열람·분석하지 않는다")
    dd = DrugDict.load(AUX.find_dict_path(a.dict_path))
    dev = compare(rows, dd)
    aux = compare(AUX.load_aux(), dd)
    md = render_md(dev, aux, str(dd.version))
    print(md)
    if a.out_md:
        Path(a.out_md).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out_md).write_text(md, encoding="utf-8")
    if a.out_json:
        Path(a.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out_json).write_text(json.dumps({"dev": dev, "aux": aux, "dict_version": str(dd.version)}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
