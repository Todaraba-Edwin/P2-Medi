"""AG-24 시나리오 D: 입구·Router 변경이 개발셋 150문항에 주는 영향의 **전후 비교**(LLM·네트워크·원격 DB 호출 0).

같은 질문·같은 프로필로 (1) `guardrail_in(substance_misuse=False)`와 `guardrail_in(substance_misuse=True)`, (2) `route_input`의 시나리오 D 스위치 셋
(`abbrev_alias`·`symptom_noise`·`paren_split`) 모두 끔과 모두 켬을 돌려 결과 딕셔너리가 달라지는 문항을 센다. 보조 문항(`dev_aux_ag24d.jsonl`)은 따로 센다.

- **개발셋만** 읽는다(`sealed_guard.check_access`가 시험셋 `*.SEALED.jsonl`을 열기 전에 거절한다, RFP-26-04, 9.1절 8번). 세트·manifest는 고치지 않는다.
- 문항 원문은 출력하지 않고 문항 ID와 달라진 항목 종류만 쓴다. 소표본이라 유의성을 주장하지 않는다(PJ2-RFP.md 9.1절): k/n만 보고한다.
- 출구 Sensor는 모델 답변이 있어야 하므로 이 스크립트가 재지 못한다(LLM 없이 측정 불가).

사용(저장소 루트, 메인 venv):
    backend/.venv/bin/python backend/scripts/ag24d_ablation.py [--dict-path data/mock/dict/drug_dict.json] [--out-md OUT.md] [--out-json OUT.json]
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

import dev_aux_ag24d as AUX  # noqa: E402
import dev_aux_w32 as W32  # noqa: E402
import sealed_guard  # noqa: E402

from app.agent import guardrail as G  # noqa: E402
from app.agent import router as R  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402

DEV_SET = ROOT / "evaluation" / "eval_set" / "dev_set.jsonl"
OFF = {"abbrev_alias": False, "symptom_noise": False, "paren_split": False}


def compare(rows: list[dict[str, Any]], dd: DrugDict, *, skip_kinds: tuple[str, ...] = ()) -> dict[str, Any]:
    guard_changed: list[str] = []
    router_changed: list[dict[str, Any]] = []
    n = 0
    for r in rows:
        if r.get("kind") in skip_kinds:
            continue
        n += 1
        q, prof = r["question"], W32._graph_profile(r.get("profile"))
        if G.guardrail_in(q, substance_misuse=False) != G.guardrail_in(q, substance_misuse=True):
            guard_changed.append(str(r.get("id")))
        off, on = R.route_input(q, dd, prof, **OFF), R.route_input(q, dd, prof)
        if off.model_dump() != on.model_dump():
            router_changed.append({"id": r.get("id"), "entities_off": [[e.raw, e.status] for e in off.entities], "entities_on": [[e.raw, e.status] for e in on.entities],
                                   "ambiguous": [off.ambiguous, on.ambiguous]})
    return {"n": n, "k_guard_changed": len(guard_changed), "guard_changed": guard_changed, "k_router_changed": len(router_changed), "router_changed": router_changed}


def render_md(dev: Mapping[str, Any], aux: Mapping[str, Any], dict_version: str) -> str:
    lines = ["# AG-24 시나리오 D 입구·Router 전후 비교", "",
             f"- 사전 `{dict_version}`, LLM·네트워크·원격 DB 호출 0. 전 = 입구 `substance_misuse=False`·Router 스위치 셋 모두 끔, 후 = 모두 켬", "",
             "## 개발셋 150문항", "", f"- 입구 결과가 달라진 문항 {dev['k_guard_changed']}/{dev['n']}, Router 결과가 달라진 문항 {dev['k_router_changed']}/{dev['n']}"]
    for c in dev["router_changed"]:
        lines.append(f"  - {c['id']}: 엔티티 {c['entities_off']} → {c['entities_on']}, 되묻기 {c['ambiguous'][0]}→{c['ambiguous'][1]}")
    lines += ["", "## 보조 문항(dev_aux_ag24d, 출구 Sensor 문장 제외)", "",
              f"- 입구 결과가 달라진 문항 {aux['k_guard_changed']}/{aux['n']}, Router 결과가 달라진 문항 {aux['k_router_changed']}/{aux['n']}", "",
              "소표본이라 유의성을 주장하지 않는다(PJ2-RFP.md 9.1절). 시험셋은 열지 않았다.", ""]
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
    dd = DrugDict.load(W32.find_dict_path(a.dict_path))
    dev = compare(rows, dd)
    aux = compare(AUX.load_aux(), dd, skip_kinds=("exit_sensor",))
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
