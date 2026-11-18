"""AG-12 judge 보정(RFP-26-03): 개발셋 답변에서 사람 라벨 40문항을 뽑아 라벨 시트(CSV)를 만든다.

    backend/.venv/bin/python evaluation/judge_calib/select_calib40.py \
        --result logs/eval/l3-dev150-v3-traj2.json [--out-dir data/mock/judge_calib] [--force] [--check]

입력
  - `--result`: `eval_runner.py`가 쓴 **개발셋** 결과 JSON(`meta.set == "dev"`, `meta.sealed == false`). 문항별 답변(`items[].run.answer`)은
    있지만 질문·정답은 없으므로 `evaluation/eval_set/dev_set.jsonl`을 문항 ID로 붙인다(질문·`reference`·정답 `answer`).
  - 시험셋 가드: 결과·세트 경로 모두 `sealed_guard.is_sealed`면 열기 전에 거절하고, 결과 `meta`가 `dev`가 아니면 거절한다(RFP-26-04).
  - **judge 호출 0, LLM·DB·API 호출 0.** 파일만 읽고 쓴다.

뽑는 규칙(`calib40@v1`, 시드 고정 → 같은 입력이면 같은 40문항)
  1. 제외: `human_review.error_found == true`(정답 근거가 틀린 문항은 보정 기준이 될 수 없다), 실행 오류(`run.error`) 문항,
     루브릭 항목이 하나도 없는 문항(모호 분기: 코드만 채점, RFP-26 §6.3. 되묻기로 끝나 주장이 없는 정상·오탈자 문항도 같다).
  2. 층(stratum)과 할당(합 40, `ALLOC`): J3 오정보 10 · J4 범위 외 8 · J5 근거 없음 10 · J1-core(응급·목록에없는약) 6 ·
     J1-other(정상 병용·연령·임부, 오탈자) 6. 루브릭 J1·J3·J4·J5마다 사람 라벨이 충분히 쌓이게 하면서 분기를 고르게 섞는다
     (RFP-26 §7.3 1번 "분기 유형을 고르게"). 안전 핵심(`dev_reliability_core`: 응급·목록에없는약·오정보)이 16/40 = 40% 이상 들어가도록
     J1을 core/other로 나눴다(`CORE_MIN_RATIO`).
  3. 층 안에서는 칸 = (`composition_group`, `subtype`, 종료 사유 `end_reason`)을 이름순으로 돌며 한 문항씩 뽑는다(round-robin).
     칸 안의 순서는 `sha256("{SEED}:{id}")`다(`mark_dev_subsets.py`와 같은 방식). 그래서 하위 유형·종료 사유(NORMAL·CLARIFY·REFUSE·
     VALIDATION_FALLBACK·LIMIT)가 한쪽으로 쏠리지 않는다.
  4. 선택 결과·칸 분포·제외 목록·입력 파일 sha256을 `calib40-manifest.json`에 적는다(측정 뒤 "어느 문항으로 보정했는가"의 증거).

출력(`--out-dir`, 기본 `data/mock/judge_calib/`, 로컬 전용·커밋 안 함)
  - `calib40-labels.csv`: 사람 라벨 시트. 문항 ID·질문·정답 근거·답 요약·근거 상세·코드 판정·루브릭 항목 칸(J1, J3_R1~R3, J4_R1~R3·R5,
    J5_R1~R3)·메모. 적용되지 않는 칸은 `N/A`로 미리 채우고 라벨러는 빈 칸만 채운다(기입 규칙은 README.md).
  - `calib40-items.jsonl`: 같은 40문항의 judge 입력 묶음(질문·기대 응답 유형·정답 근거·답변·사용 근거 ID). judge는 여기서 부르지 않는다.
  - `calib40-manifest.json`: 선택 규칙 버전·시드·입력 해시·층별 ID·칸 분포·안전 핵심 비율·제외 목록.
  이미 있는 CSV는 덮어쓰지 않는다(라벨이 지워지지 않게, `--force`로만 덮어씀). `--check`는 파일을 쓰지 않고 선택 결과만 출력한다.

사람 라벨은 judge 결과를 보기 전에 한다(RFP-26 §7.3 1번). 라벨이 끝나면 `calib_agreement.py`로 일치율·Cohen's κ를 낸다.

재보정(AG-12-06·07 A, 2026-11-18): 같은 규칙·시드로 `--alloc "J3=8,J5=7" --exclude-manifest data/mock/judge_calib/calib40-manifest.json
--rubrics J3,J5 --name calib15-v2`처럼 돌리면 앞선 보정에 쓴 문항을 빼고(README §5 3번) J3·J5 층만 뽑아 라벨·judge 대상도 J3·J5로
좁힌(J1 칸 N/A) `calib15-v2-*` 파일을 만든다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for p in (str(HERE.parent), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

import sealed_guard as G  # noqa: E402

SELECT_VERSION = "calib40@v1"
SEED = 20261117
N_TOTAL = 40
CORE_MIN_RATIO = 0.4  # 안전 핵심(dev_reliability_core) 최소 비율(16/40)
DEFAULT_SET = ROOT / "evaluation" / "eval_set" / "dev_set.jsonl"
DEFAULT_OUT = ROOT / "data" / "mock" / "judge_calib"
LABELS_CSV = "calib40-labels.csv"
ITEMS_JSONL = "calib40-items.jsonl"
MANIFEST = "calib40-manifest.json"

# 층 → (분기 라벨 집합, 할당 수). J1-core/other는 둘 다 J1만 적용되는 층이고 안전 핵심 비율을 위해 나눴다.
ALLOC: dict[str, tuple[frozenset[str], int]] = {
    "J3": (frozenset({"오정보"}), 10),
    "J4": (frozenset({"범위 외"}), 8),
    "J5": (frozenset({"근거 없음"}), 10),
    "J1-core": (frozenset({"정상-응급", "정상-목록에없는약"}), 6),
    "J1-other": (frozenset({"정상-병용", "정상-연령", "정상-임부", "오탈자"}), 6),
}
assert sum(n for _, n in ALLOC.values()) == N_TOTAL  # noqa: S101  (설정 불변식)

# 루브릭 항목 칸(RFP-26 §7.5). R4는 코드가 보므로 사람 라벨 칸에 없다. J2(청크 관련성)는 Ragas 공식용이라 사람 보정 대상이 아니다.
RUBRIC_COLS: dict[str, list[str]] = {
    "J1": ["J1(뒷받침안됨/전체주장)"],
    "J3": ["J3_R1", "J3_R2", "J3_R3"],
    "J4": ["J4_R1", "J4_R2", "J4_R3", "J4_R5"],
    "J5": ["J5_R1", "J5_R2", "J5_R3"],
}
ALL_RUBRIC_COLS = [c for cols in RUBRIC_COLS.values() for c in cols]
INFO_COLS = ["id", "층", "분기", "구성그룹", "하위유형", "종료사유", "안전핵심", "적용루브릭", "질문", "기대응답유형",
             "정답근거(reference)", "답요약(모델)", "답본문(코드부착포함)", "근거상세", "고정문구(코드)", "코드판정(elements)"]
HEAD = [*INFO_COLS, *ALL_RUBRIC_COLS, "메모"]
NA = "N/A"


# --------------------------------------------------------------------------- 읽기(가드)

def load_result(path: Path) -> dict[str, Any]:
    """개발셋 결과 JSON. 시험셋 이름이면 열기 전에 거절, `meta`가 dev가 아니면 거절."""
    G.check_access(path)  # SEALED 이름이면 SealedAccessError(파일을 열지 않음)
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.get("meta") or {}
    if meta.get("set") != "dev" or meta.get("sealed"):
        raise G.SealedAccessError(f"judge 보정은 개발셋 결과만 쓴다(RFP-26-03): meta.set={meta.get('set')!r}, sealed={meta.get('sealed')!r}")
    if not data.get("items"):
        raise SystemExit("결과에 문항별 기록(items)이 없다. 개발셋 결과(`--set dev`)를 지정하라")
    return data


def load_set(path: Path) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in G.load_jsonl(path)}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- 문항 분류

def _rank(item_id: str) -> str:
    return hashlib.sha256(f"{SEED}:{item_id}".encode()).hexdigest()


def has_claims(run: dict[str, Any]) -> bool:
    """J1(근거 충실)을 채점할 주장이 있는가: 모델 요약이 있고 되묻기·거절이 아니다."""
    a = run.get("answer") or {}
    if run.get("end_reason") in ("CLARIFY", "REFUSE") or a.get("route") == "REFUSE":
        return False
    return bool(str(a.get("summary") or "").strip())


def rubrics_for(res: dict[str, Any], run: dict[str, Any]) -> list[str]:
    """문항에 적용되는 루브릭(J1·J3·J4·J5). 판단은 분기와 답변 모양(주장 유무)으로 한다."""
    out: list[str] = []
    if has_claims(run):
        out.append("J1")
    b = res.get("branch_label")
    if b == "오정보":
        out.append("J3")
    elif b == "범위 외":
        out.append("J4")
    elif b == "근거 없음":
        out.append("J5")
    return out


def stratum_of(res: dict[str, Any]) -> str | None:
    key = res.get("composition_group") if str(res.get("branch_label", "")).startswith("정상") or res.get("branch_label") == "응급" \
        else res.get("branch_label")
    for name, (labels, _) in ALLOC.items():
        if key in labels:
            return name
    return None


def required_elements(src: dict[str, Any]) -> set[str]:
    """문항의 필수 요소. 개발셋 일부(dev-141~145)는 AI 수정 때 `expected.required_elements`에 `NO_STATE_ASSESSMENT`를 넣어 두 곳을 합친다."""
    top = src.get("required_elements") or []
    nested = ((src.get("expected") or {}).get("required_elements") or []) if isinstance(src.get("expected"), dict) else []
    return {*top, *nested}


def exclusion_reason(res: dict[str, Any], src: dict[str, Any] | None, run: dict[str, Any]) -> str | None:
    if src is None:
        return "dev_set에 없는 ID"
    if (src.get("human_review") or {}).get("error_found") is True:
        return "human_review.error_found(정답 오류 문항)"
    if run.get("error"):
        return "실행 오류(run.error)"
    if not rubrics_for(res, run):
        return "judge 루브릭 항목 없음(코드만 채점)"
    return None


# --------------------------------------------------------------------------- 선택

def parse_alloc(spec: str | None) -> dict[str, tuple[frozenset[str], int]]:
    """`--alloc "J3=8,J5=7"` → 층별 할당(적지 않은 층은 0). 없으면 기본 `ALLOC`(40문항). 모르는 층 이름은 오류."""
    if not spec:
        return dict(ALLOC)
    out: dict[str, tuple[frozenset[str], int]] = {}
    for part in spec.split(","):
        name, _, n = part.strip().partition("=")
        if name not in ALLOC:
            raise SystemExit(f"모르는 층: {name!r} (가능: {list(ALLOC)})")
        out[name] = (ALLOC[name][0], int(n))
    return out


def used_ids_from_manifest(path: Path) -> set[str]:
    """앞선 보정 manifest(`by_stratum`)의 문항 ID. 재보정은 라벨에 쓴 문항을 다시 쓰지 않는다(README §5 3번, RFP-26 §7.3 3번)."""
    man = json.loads(path.read_text(encoding="utf-8"))
    return {i for ids in (man.get("by_stratum") or {}).values() for i in ids}


def select(result: dict[str, Any], dev: dict[str, dict[str, Any]], *, alloc: dict[str, tuple[frozenset[str], int]] | None = None,
           exclude_ids: set[str] | None = None, rubrics_only: set[str] | None = None) -> dict[str, Any]:
    """층화 round-robin 선택. 반환: {"selected": [...], "by_stratum": {...}, "excluded": [...], "cells": {...}, "core_ratio": float}.
    `alloc`은 층별 할당(기본 ALLOC), `exclude_ids`는 앞선 보정에 이미 쓴 문항(제외 사유를 남긴다), `rubrics_only`는 라벨·judge 대상 루브릭을
    그 집합으로 좁힌다(재보정 J3·J5만: 오정보 NORMAL 답의 J1 칸은 N/A가 되고 judge도 부르지 않는다)."""
    alloc = alloc or ALLOC
    exclude_ids = exclude_ids or set()
    pools: dict[str, dict[tuple[str, str, str], list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    excluded: list[dict[str, str]] = []
    for res in result["items"]:
        run = res.get("run") or {}
        src = dev.get(res["id"])
        why = exclusion_reason(res, src, run)
        if why:
            excluded.append({"id": res["id"], "reason": why})
            continue
        if res["id"] in exclude_ids:
            excluded.append({"id": res["id"], "reason": "앞선 보정 라벨에 이미 쓴 문항(재사용 금지)"})
            continue
        st = stratum_of(res)
        if st is None or st not in alloc:
            excluded.append({"id": res["id"], "reason": f"할당 층 없음(branch={res.get('branch_label')})"})
            continue
        cell = (str(res.get("composition_group")), str(src.get("subtype")), str(run.get("end_reason")))
        rub = [r for r in rubrics_for(res, run) if rubrics_only is None or r in rubrics_only]
        if not rub:
            excluded.append({"id": res["id"], "reason": f"대상 루브릭 없음(rubrics_only={sorted(rubrics_only or [])})"})
            continue
        pools[st][cell].append({"res": res, "src": src, "run": run, "stratum": st, "cell": cell, "rubrics": rub})

    selected: list[dict[str, Any]] = []
    by_stratum: dict[str, list[str]] = {}
    shortfall: dict[str, int] = {}
    for st, (_, quota) in alloc.items():
        cells = {c: sorted(v, key=lambda x: _rank(x["res"]["id"])) for c, v in pools[st].items()}
        order = sorted(cells)  # 칸 이름순(결정적)
        picked: list[dict[str, Any]] = []
        while len(picked) < quota and any(cells[c] for c in order):
            for c in order:
                if len(picked) >= quota:
                    break
                if cells[c]:
                    picked.append(cells[c].pop(0))
        if len(picked) < quota:
            shortfall[st] = quota - len(picked)
        by_stratum[st] = [p["res"]["id"] for p in picked]
        selected.extend(picked)

    core = sum(bool(p["src"].get("dev_reliability_core")) for p in selected)
    cells_count = Counter(f"{p['stratum']}|{'|'.join(p['cell'])}" for p in selected)
    return {"selected": selected, "by_stratum": by_stratum, "excluded": excluded, "shortfall": shortfall,
            "cells": dict(sorted(cells_count.items())), "core_count": core,
            "core_ratio": round(core / len(selected), 4) if selected else 0.0,
            "alloc": {k: v[1] for k, v in alloc.items()}, "n_total": sum(v[1] for v in alloc.values()), "n_excluded_used": len(exclude_ids),
            "rubrics_only": sorted(rubrics_only) if rubrics_only else None}


# --------------------------------------------------------------------------- 시트 렌더링

def _fixed_lines(answer: dict[str, Any]) -> list[str]:
    keys = ("emergency", "fixed_notice", "disclaimer", "pharmacist_advice_fixed")
    lines = [str(answer.get(k)) for k in keys if answer.get(k)]
    lines.extend(str(x) for x in answer.get("not_checked_lines") or [])
    return lines


def render_detail(answer: dict[str, Any]) -> str:
    """근거 상세: 판정 항목(종류·상태·기준일·행 원문)과 라벨 항목(절·이름·미확보 사유). 라벨러가 J1·J5를 판단할 재료."""
    out: list[str] = []
    for d in answer.get("detail") or []:
        if not isinstance(d, dict):
            continue
        head = f"[{d.get('evidence_id')}] {d.get('kind')} {d.get('status')} 출처={d.get('publisher') or d.get('source_kind')} 기준일={d.get('as_of')}"
        extra = [f"{k}={d.get(k)}" for k in ("name", "section", "missing_reason", "input_name") if d.get(k)]
        if extra:
            head += " " + " ".join(extra)
        out.append(head)
        for r in d.get("rows") or []:
            if isinstance(r, dict):
                parts = [f"{k}={r.get(k)}" for k in ("grade", "notice_no", "notice_date", "detail", "reason", "age", "text") if r.get(k)]
                out.append("  - " + (" | ".join(parts) if parts else json.dumps(r, ensure_ascii=False)[:300]))
    for e in answer.get("entries") or []:
        if isinstance(e, dict) and e.get("bucket") not in ("found", "not_listed"):
            out.append(f"[entry] {e.get('drug')} {e.get('bucket')} {e.get('text')}")
    for g in answer.get("grade_defs") or []:
        if isinstance(g, dict):
            out.append(f"[grade_def {g.get('grade')}] {g.get('text') or g.get('missing') or ''}")
    return "\n".join(out)


def render_row(p: dict[str, Any]) -> list[str]:
    res, src, run = p["res"], p["src"], p["run"]
    a = run.get("answer") or {}
    rub = p.get("rubrics") or rubrics_for(res, run)
    elements = res.get("elements") or {}
    code_el = ", ".join(f"{k}={'' if v is None else v}" for k, v in elements.items())
    row = [res["id"], p["stratum"], str(res.get("branch_label")), str(res.get("composition_group")), str(src.get("subtype")),
           str(run.get("end_reason")), "Y" if src.get("dev_reliability_core") else "N", "+".join(rub), str(src.get("question")),
           str(res.get("expected_response_type")), str(src.get("reference") or ""), str(a.get("summary") or ""), str(a.get("text") or ""),
           render_detail(a), " / ".join(_fixed_lines(a)), code_el]
    for r, cols in RUBRIC_COLS.items():
        for c in cols:
            if r not in rub:
                row.append(NA)
            elif c == "J4_R5" and "NO_STATE_ASSESSMENT" not in required_elements(src):
                row.append(NA)  # R5는 중단·감량·의료진 우회 문항에만(RFP-26-07 A)
            else:
                row.append("")
    row.append("")
    return row


def judge_input(p: dict[str, Any]) -> dict[str, Any]:
    """judge 입력 묶음(RFP-26 §7.1 입력: 질문·기대 응답 유형·정답 근거·답변·rubric). 조건 이름은 넣지 않는다(블라인드)."""
    res, src, run = p["res"], p["src"], p["run"]
    a = run.get("answer") or {}
    return {"id": res["id"], "stratum": p["stratum"], "rubrics": p.get("rubrics") or rubrics_for(res, run), "question": src.get("question"),
            "expected_response_type": res.get("expected_response_type"), "required_elements": sorted(required_elements(src)),
            "reference": src.get("reference"), "answer_key": src.get("answer"), "answer_evidence": src.get("answer_evidence"),
            "answer": {"summary": a.get("summary"), "text": a.get("text"), "entries": a.get("entries"), "detail": a.get("detail"),
                       "citations": a.get("citations"), "grade_defs": a.get("grade_defs")},
            "tool_evidence_ids": sorted(run.get("tool_evidence_ids") or []), "end_reason": run.get("end_reason")}


# --------------------------------------------------------------------------- 쓰기

def file_names(name: str = "calib40") -> tuple[str, str, str]:
    """출력 파일 이름(라벨 CSV, judge 입력, manifest). 기본 `calib40-*`, 재보정은 `--name calib15-v2`처럼 접두를 바꾼다."""
    return f"{name}-labels.csv", f"{name}-items.jsonl", f"{name}-manifest.json"


def write_outputs(sel: dict[str, Any], out_dir: Path, *, result_path: Path, set_path: Path, result_meta: dict[str, Any],
                  force: bool = False, name: str = "calib40", exclude_manifest: Path | None = None) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    labels_csv, items_jsonl, manifest_name = file_names(name)
    csv_path = out_dir / labels_csv
    if csv_path.exists() and not force:
        print(f"이미 있음(덮어쓰지 않음, --force로만): {csv_path}")
    else:
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEAD)
            for p in sel["selected"]:
                w.writerow(render_row(p))
    (out_dir / items_jsonl).write_text("".join(json.dumps(judge_input(p), ensure_ascii=False) + "\n" for p in sel["selected"]),
                                       encoding="utf-8")
    manifest = {
        "select_version": SELECT_VERSION, "seed": SEED, "n": len(sel["selected"]), "alloc": sel.get("alloc") or {k: v[1] for k, v in ALLOC.items()},
        "name": name, "exclude_manifest": str(exclude_manifest) if exclude_manifest else None, "n_excluded_used": sel.get("n_excluded_used", 0),
        "rubrics_only": sel.get("rubrics_only"),
        "result_file": str(result_path), "result_sha256": sha256_file(result_path),
        "result_meta": {k: result_meta.get(k) for k in ("set", "set_version", "set_sha256", "condition", "prompt_set", "trajectory_rule",
                                                          "created_utc", "agent_info")},
        "set_file": str(set_path), "set_sha256": sha256_file(set_path),
        "by_stratum": sel["by_stratum"], "cells": sel["cells"], "shortfall": sel["shortfall"],
        "core_count": sel["core_count"], "core_ratio": sel["core_ratio"], "core_min_ratio": CORE_MIN_RATIO,
        "excluded": sel["excluded"], "rubric_cols": RUBRIC_COLS,
        "note": "사람 라벨은 judge 결과를 보기 전에 한다(RFP-26 §7.3). 시험셋은 쓰지 않았다(RFP-26-04). judge 호출 0.",
    }
    (out_dir / manifest_name).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return manifest


def summarize(sel: dict[str, Any]) -> str:
    n_total = sel.get("n_total", N_TOTAL)
    lines = [f"선택 {len(sel['selected'])}/{n_total}, 안전 핵심 {sel['core_count']} ({sel['core_ratio']:.0%}, 기준 ≥ {CORE_MIN_RATIO:.0%})"]
    for st, ids in sel["by_stratum"].items():
        lines.append(f"  {st}: {len(ids)} {ids}")
    if sel["shortfall"]:
        lines.append(f"  부족: {sel['shortfall']}")
    lines.append(f"  제외 {len(sel['excluded'])}: " + ", ".join(f"{e['id']}({e['reason']})" for e in sel["excluded"][:12])
                 + (" …" if len(sel["excluded"]) > 12 else ""))
    lines.append("  칸 분포(층|구성그룹|하위유형|종료사유):")
    lines.extend(f"    {k}: {v}" for k, v in sel["cells"].items())
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--result", required=True, type=Path, help="eval_runner 개발셋 결과 JSON")
    ap.add_argument("--set", type=Path, default=DEFAULT_SET, help="개발셋 jsonl(기본 evaluation/eval_set/dev_set.jsonl)")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--force", action="store_true", help="이미 있는 라벨 CSV를 덮어쓴다(라벨이 지워진다)")
    ap.add_argument("--check", action="store_true", help="파일을 쓰지 않고 선택 결과만 출력")
    ap.add_argument("--alloc", default=None, help='층별 할당 덮어쓰기(예: "J3=8,J5=7". 적지 않은 층은 0). 기본은 40문항 ALLOC')
    ap.add_argument("--exclude-manifest", type=Path, default=None, help="앞선 보정 manifest. 그 by_stratum 문항은 제외(재보정용)")
    ap.add_argument("--name", default="calib40", help="출력 파일 접두(기본 calib40 → calib40-labels.csv 등. 재보정은 calib15-v2)")
    ap.add_argument("--rubrics", default=None, help='라벨·judge 대상 루브릭만(예: "J3,J5"). 기본은 문항에 적용되는 전부')
    a = ap.parse_args(argv)
    result = load_result(a.result)
    dev = load_set(a.set)
    alloc = parse_alloc(a.alloc)
    exclude_ids = used_ids_from_manifest(a.exclude_manifest) if a.exclude_manifest else set()
    rubrics_only = {r.strip() for r in a.rubrics.split(",") if r.strip()} if a.rubrics else None
    if rubrics_only and not rubrics_only <= set(RUBRIC_COLS):
        raise SystemExit(f"모르는 루브릭: {sorted(rubrics_only - set(RUBRIC_COLS))} (가능: {list(RUBRIC_COLS)})")
    sel = select(result, dev, alloc=alloc, exclude_ids=exclude_ids, rubrics_only=rubrics_only)
    print(summarize(sel))
    if sel["core_ratio"] < CORE_MIN_RATIO:
        print(f"경고: 안전 핵심 비율 {sel['core_ratio']:.0%} < {CORE_MIN_RATIO:.0%}")
    if sel["shortfall"] or len(sel["selected"]) != sel["n_total"]:
        print("경고: 할당을 채우지 못했다(위 '부족'). 입력 결과를 확인하라")
    if a.check:
        return 0
    write_outputs(sel, a.out_dir, result_path=a.result, set_path=a.set, result_meta=result.get("meta") or {}, force=a.force,
                  name=a.name, exclude_manifest=a.exclude_manifest)
    print("출력: " + ", ".join(str(a.out_dir / n) for n in file_names(a.name)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
