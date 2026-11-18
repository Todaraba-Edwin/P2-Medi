"""AG-12 judge 보정 40문항 준비(RFP-26-03) 시험: 선택 규칙·시험셋 가드·라벨 시트·일치율·Cohen's κ.

LLM·judge·공공 API·원격 DB 호출 0. 문항·답변은 모두 **가짜(합성)**이며 개발셋·시험셋 문항이 아니다. 시험셋 파일은 열지 않는다
(SEALED 이름의 가짜 경로가 열리기 전에 막히는지만 본다).
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "evaluation", ROOT / "evaluation" / "judge_calib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import calib_agreement as A  # noqa: E402
import sealed_guard as G  # noqa: E402
import select_calib40 as S  # noqa: E402

# ------------------------------------------------------------------ 가짜 개발셋·결과(합성)

GROUPS: list[tuple[str, str, str, str, int]] = [
    # (branch_label, composition_group, subtype, expected_response_type, n)
    ("정상", "정상-병용", "병용", "judgment", 15), ("정상", "정상-연령", "연령", "judgment", 10), ("정상", "정상-임부", "임부", "judgment", 10),
    ("정상", "정상-목록에없는약", "목록에없는약", "not_listed", 10), ("응급", "정상-응급", "응급", "emergency", 10),
    ("오탈자", "오탈자", "오탈자", "judgment", 20), ("모호", "모호", "이름모호", "clarify", 20), ("오정보", "오정보", "임부 안전 오인", "correct", 20),
    ("근거 없음", "근거 없음", "약 미식별", "no_evidence", 20), ("범위 외", "범위 외", "인젝션", "refuse", 15),
]
END_CYCLE = {"정상": ["NORMAL", "NORMAL", "VALIDATION_FALLBACK"], "응급": ["NORMAL"], "오탈자": ["CLARIFY", "NORMAL"], "모호": ["CLARIFY"],
             "오정보": ["NORMAL", "LIMIT"], "근거 없음": ["CLARIFY", "NORMAL"], "범위 외": ["REFUSE", "NORMAL", "CLARIFY"]}


def make_fake(n_error: int = 2) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """가짜 dev_set 행과 eval_runner 모양의 결과. 처음 n_error개 오정보 문항은 error_found=True."""
    rows: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    k = 0
    err_left = n_error
    for branch, group, subtype, ert, n in GROUPS:
        for i in range(n):
            k += 1
            iid = f"fake-{k:03d}"
            core = group in ("정상-응급", "정상-목록에없는약", "오정보")
            err = False
            if branch == "오정보" and err_left > 0:
                err, err_left = True, err_left - 1
            req = ["PHARMACIST_NOTICE"]
            src: dict[str, Any] = {"id": iid, "branch_label": branch, "composition_group": group, "subtype": subtype, "question": f"가짜 질문 {k}",
                                   "expected_response_type": ert, "required_elements": req, "reference": f"가짜 정답 {k}",
                                   "answer": {"items": []}, "dev_reliability_core": core,
                                   "human_review": {"status": "검수 완료" if err else "검수 전", "error_found": err}}
            if branch == "범위 외" and i == 0:
                src["expected"] = {"required_elements": ["NO_STATE_ASSESSMENT"]}  # 중첩 필드에만 있는 경우
            rows.append(src)
            end = END_CYCLE[branch][i % len(END_CYCLE[branch])]
            summary = "" if end in ("CLARIFY", "REFUSE", "LIMIT") else f"가짜 요약 {k}"
            answer = {"route": "REFUSE" if end == "REFUSE" else "AGENT", "summary": summary, "text": f"{summary}\n고정 문구",
                      "fixed_notice": "고정 문구", "disclaimer": "면책",
                      "detail": [{"evidence_id": f"pregnancy:X{k}", "kind": "pregnancy", "status": "FOUND", "publisher": "가짜", "as_of": "2026-07-21",
                                  "rows": [{"grade": "2", "notice_no": "1", "detail": "가짜 상세"}]}] if summary else [],
                      "entries": [], "grade_defs": []}
            items.append({"id": iid, "branch_label": branch, "composition_group": group, "expected_response_type": ert,
                          "elements": {"PHARMACIST_NOTICE": True}, "run": {"answer": answer, "end_reason": end, "error": None, "tool_evidence_ids": []}})
    result = {"meta": {"set": "dev", "sealed": False, "set_version": "fake", "condition": "C2"}, "items": items}
    return rows, result


@pytest.fixture
def fake_files(tmp_path: Path) -> tuple[Path, Path]:
    rows, result = make_fake()
    set_path = tmp_path / "dev_set.jsonl"
    set_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    res_path = tmp_path / "l3-fake.json"
    res_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return res_path, set_path


# ------------------------------------------------------------------ 선택 규칙

def test_select_fills_40_by_stratum_and_core_ratio(fake_files):
    res_path, set_path = fake_files
    sel = S.select(S.load_result(res_path), S.load_set(set_path))
    assert len(sel["selected"]) == S.N_TOTAL and not sel["shortfall"]
    assert {k: len(v) for k, v in sel["by_stratum"].items()} == {k: v[1] for k, v in S.ALLOC.items()}
    assert sel["core_ratio"] >= S.CORE_MIN_RATIO
    ids = [p["res"]["id"] for p in sel["selected"]]
    assert len(set(ids)) == 40


def test_select_is_deterministic_and_seeded(fake_files):
    res_path, set_path = fake_files
    r, d = S.load_result(res_path), S.load_set(set_path)
    a = S.select(r, d)["by_stratum"]
    b = S.select(r, d)["by_stratum"]
    assert a == b
    # 순위는 sha256(SEED:id)다(mark_dev_subsets.py와 같은 방식)
    assert S._rank("fake-001") == hashlib.sha256(f"{S.SEED}:fake-001".encode()).hexdigest()


def test_select_excludes_error_items_clarify_only_and_ambiguous(fake_files):
    res_path, set_path = fake_files
    sel = S.select(S.load_result(res_path), S.load_set(set_path))
    reasons = {e["id"]: e["reason"] for e in sel["excluded"]}
    chosen = {p["res"]["id"] for p in sel["selected"]}
    assert sum("error_found" in r for r in reasons.values()) == 2
    assert all(iid not in chosen for iid, r in reasons.items())
    # 모호 20문항은 모두 judge 항목이 없어 제외
    amb = [iid for iid, r in reasons.items() if r.startswith("judge 루브릭 항목 없음")]
    assert len(amb) >= 20
    # 선택된 문항은 모두 루브릭이 하나 이상
    assert all(S.rubrics_for(p["res"], p["run"]) for p in sel["selected"])


def test_round_robin_spreads_end_reasons_within_stratum(fake_files):
    res_path, set_path = fake_files
    sel = S.select(S.load_result(res_path), S.load_set(set_path))
    ends = {p["cell"][2] for p in sel["selected"] if p["stratum"] == "J4"}
    assert ends == {"REFUSE", "NORMAL", "CLARIFY"}  # 종료 사유가 한쪽으로 쏠리지 않는다
    j5_ends = {p["cell"][2] for p in sel["selected"] if p["stratum"] == "J5"}
    assert j5_ends == {"CLARIFY", "NORMAL"}


def test_rubrics_for_by_branch_and_claims():
    run_claims = {"end_reason": "NORMAL", "answer": {"summary": "주장", "route": "AGENT"}}
    run_clarify = {"end_reason": "CLARIFY", "answer": {"summary": "비슷한 약이 있어요", "route": "AGENT"}}
    assert S.rubrics_for({"branch_label": "오정보"}, run_claims) == ["J1", "J3"]
    assert S.rubrics_for({"branch_label": "범위 외"}, {"end_reason": "REFUSE", "answer": {"summary": "x", "route": "REFUSE"}}) == ["J4"]
    assert S.rubrics_for({"branch_label": "근거 없음"}, run_clarify) == ["J5"]
    assert S.rubrics_for({"branch_label": "모호"}, run_clarify) == []
    assert S.rubrics_for({"branch_label": "정상"}, run_claims) == ["J1"]


# ------------------------------------------------------------------ 시험셋 가드

def test_result_guard_rejects_sealed_name_before_open(tmp_path: Path, monkeypatch):
    sealed = tmp_path / "l3-test_set.SEALED.json"
    sealed.write_text("{}", encoding="utf-8")

    def boom(self, *a, **k):  # noqa: ARG001
        raise AssertionError(f"파일을 열었다: {self}")

    monkeypatch.setattr(Path, "read_text", boom)
    with pytest.raises(G.SealedAccessError):
        S.load_result(sealed)


def test_result_guard_rejects_non_dev_meta(tmp_path: Path):
    p = tmp_path / "l3-x.json"
    p.write_text(json.dumps({"meta": {"set": "test", "sealed": True}, "items": [{"id": "x"}]}), encoding="utf-8")
    with pytest.raises(G.SealedAccessError):
        S.load_result(p)
    p.write_text(json.dumps({"meta": {"set": "dev", "sealed": False}, "items": []}), encoding="utf-8")
    with pytest.raises(SystemExit):
        S.load_result(p)  # 문항별 기록이 없는 결과(점수만)는 쓸 수 없다


# ------------------------------------------------------------------ 라벨 시트 출력

def test_write_outputs_csv_items_manifest(fake_files, tmp_path: Path):
    res_path, set_path = fake_files
    result = S.load_result(res_path)
    sel = S.select(result, S.load_set(set_path))
    out = tmp_path / "out"
    man = S.write_outputs(sel, out, result_path=res_path, set_path=set_path, result_meta=result["meta"])
    with open(out / S.LABELS_CSV, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 40 and list(rows[0].keys()) == S.HEAD
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        rub = r["적용루브릭"].split("+")
        for rid, cols in S.RUBRIC_COLS.items():
            for c in cols:
                if rid not in rub:
                    assert r[c] == S.NA
                elif c != "J4_R5":
                    assert r[c] == ""
        assert r["질문"].startswith("가짜 질문") and r["정답근거(reference)"].startswith("가짜 정답")
    # J4_R5는 NO_STATE_ASSESSMENT가 있는 문항(중첩 필드 포함)만 열린다
    j4 = [r for r in rows if r["층"] == "J4"]
    opened = [r["id"] for r in j4 if r["J4_R5"] == ""]
    assert opened == ["fake-136"] and all(r["J4_R5"] == S.NA for r in j4 if r["id"] != "fake-136")
    # 코드 판정 열에 judge 몫(None)은 빈 값으로 보인다
    assert "PHARMACIST_NOTICE=True" in rows[0]["코드판정(elements)"]
    items = [json.loads(ln) for ln in (out / S.ITEMS_JSONL).read_text(encoding="utf-8").splitlines()]
    assert [it["id"] for it in items] == [r["id"] for r in rows]
    assert all("condition" not in it for it in items)  # 블라인드: 조건 이름을 judge 입력에 넣지 않는다
    assert man["n"] == 40 and man["select_version"] == S.SELECT_VERSION and man["result_sha256"] and man["set_sha256"]
    assert man["result_meta"]["set"] == "dev" and len(man["excluded"]) >= 22
    assert "fake-136" in by_id
    # 기존 CSV는 덮어쓰지 않는다
    (out / S.LABELS_CSV).write_text("라벨 중", encoding="utf-8")
    S.write_outputs(sel, out, result_path=res_path, set_path=set_path, result_meta=result["meta"])
    assert (out / S.LABELS_CSV).read_text(encoding="utf-8") == "라벨 중"
    S.write_outputs(sel, out, result_path=res_path, set_path=set_path, result_meta=result["meta"], force=True)
    assert (out / S.LABELS_CSV).read_text(encoding="utf-8-sig").startswith("id,")


def test_cli_check_writes_nothing(fake_files, tmp_path: Path, capsys):
    res_path, set_path = fake_files
    out = tmp_path / "nothing"
    assert S.main(["--result", str(res_path), "--set", str(set_path), "--out-dir", str(out), "--check"]) == 0
    assert not out.exists()
    assert "선택 40/40" in capsys.readouterr().out


# ------------------------------------------------------------------ 라벨 파싱·κ·일치율

@pytest.mark.parametrize(("raw", "want"), [("pass", True), ("P", True), ("y", True), ("1", True), ("○", True), ("fail", False), ("F", False),
                                           ("N", False), ("0", False), ("×", False), ("N/A", None), ("", None), ("  ", None),
                                           ("0/4", True), ("1/4", False), ("0/0", None)])
def test_parse_cell(raw, want):
    assert A.parse_cell(raw) is want


@pytest.mark.parametrize("raw", ["maybe", "5/4", "a/b", "-1/3"])
def test_parse_cell_rejects_unknown(raw):
    with pytest.raises(ValueError):
        A.parse_cell(raw)


def test_cohen_kappa_known_values():
    assert A.cohen_kappa(20, 0, 0, 20) == 1.0
    # 교과서 예: a=20 b=5 c=10 d=15 → po=0.7, pe=(25*30+25*20)/2500=0.5 → κ=0.4
    assert round(A.cohen_kappa(20, 5, 10, 15), 4) == 0.4
    assert A.cohen_kappa(10, 0, 0, 0) is None  # 둘 다 모두 pass → pe=1
    assert A.cohen_kappa(0, 0, 0, 0) is None
    assert A.cohen_kappa(0, 10, 10, 0) == -1.0


def _labels_csv(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    p = tmp_path / "labels.csv"
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=S.HEAD)
        w.writeheader()
        for r in rows:
            w.writerow({**{c: S.NA for c in S.ALL_RUBRIC_COLS}, **{c: "" for c in S.INFO_COLS}, "메모": "", **r})
    return p


def test_agreement_with_fake_labels_and_judge(tmp_path: Path):
    human_rows = [
        {"id": "fake-001", "J3_R1": "pass", "J3_R2": "pass", "J3_R3": "fail", "J1(뒷받침안됨/전체주장)": "0/3"},
        {"id": "fake-002", "J3_R1": "fail", "J3_R2": "pass", "J3_R3": "pass", "J1(뒷받침안됨/전체주장)": "1/2"},
        {"id": "fake-003", "J4_R1": "pass", "J4_R2": "fail", "J4_R3": "pass", "J4_R5": ""},  # R5 미완료
        {"id": "fake-004", "J5_R1": "pass", "J5_R2": "pass", "J5_R3": "pass"},
    ]
    labels_path = _labels_csv(tmp_path, human_rows)
    judge = {"meta": {"judge_model": A.JUDGE_MODEL, "rubric_versions": {"J3": "J3@v1"}}, "items": {
        "fake-001": {"J3": {"rubric": "J3@v1", "items": {"R1": {"pass": True, "reason": "전제 거부"}, "R2": {"pass": False, "reason": "출처 없음"},
                                                         "R3": {"pass": False, "reason": ""}}, "overall_pass": False},
                     "J1": {"claims": [{"id": 1, "text": "a", "supported": True}, {"id": 2, "text": "b", "supported": True}], "faithfulness": 1.0}},
        "fake-002": {"J3": {"rubric": "J3@v1", "items": {"R1": {"pass": False, "reason": "x"}, "R2": {"pass": True, "reason": ""}, "R3": {"pass": True, "reason": ""}}},
                     "J1": {"claims": [{"id": 1, "text": "지어낸 위험", "supported": False}]}},
        "fake-003": {"J4": {"rubric": "J4@v1", "items": {"R1": {"pass": True}, "R2": {"pass": False}, "R3": {"pass": True}, "R5": {"pass": True}}}},
        "fake-004": {"J5": {"status": "error"}},
    }}
    judge_path = tmp_path / "judge.json"
    judge_path.write_text(json.dumps(judge, ensure_ascii=False), encoding="utf-8")

    human, unfilled = A.read_labels(labels_path)
    assert unfilled == {"fake-003": ["J4_R5"]}
    jl, jr, jerr = A.judge_to_labels(A.load_judge_results(judge_path))
    assert jerr == [{"id": "fake-004", "rubric": "J5", "status": "error"}]
    assert jl["fake-002"]["J1(뒷받침안됨/전체주장)"] is False and jr["fake-002"]["J1(뒷받침안됨/전체주장)"] == "지어낸 위험"

    rep = A.agreement(human, jl, jr)
    # 사람 11칸(J3 6 + J1 2 + J4 3 + J5 3 = 14) 중 judge 값이 있는 쌍: J3 6 + J1 2 + J4 3 = 11, J5 3칸은 judge 오류라 사람만
    assert rep["n_pairs"] == 11 and rep["human_only"] == 3 and rep["judge_only"] == 1  # judge만: fake-003 R5(사람 미완료)
    dis = {(d["id"], d["item"]) for d in rep["disagreements"]}
    assert dis == {("fake-001", "J3_R2")}
    assert rep["per_item"]["J3_R2"]["agreement"]["k"] == 1 and rep["per_item"]["J3_R2"]["agreement"]["n"] == 2
    assert rep["per_rubric"]["J3"]["agreement"]["k"] == 5 and rep["per_rubric"]["J3"]["agreement"]["n"] == 6
    assert rep["per_rubric"]["J1"]["kappa"] == 1.0 and rep["per_rubric"]["J1"]["meets_provisional"] is True
    assert rep["per_rubric"]["J3"]["meets_provisional"] is False  # 5/6 = 0.833 < 0.85
    assert rep["overall"]["agreement"]["k"] == 10 and rep["overall"]["agreement"]["n"] == 11
    assert "J5" not in rep["per_rubric"]
    assert rep["per_rubric"]["J3"]["agreement"]["claim"] == "유의성 주장 안 함(n≤8)"
    out = A.render(rep)
    assert "불일치 1건" in out and "fake-001 J3_R2" in out

    # CLI: judge 호출 없이 집계 파일을 쓴다
    assert A.main(["--labels", str(labels_path), "--judge", str(judge_path), "--out", str(tmp_path / "agg.json")]) == 0
    agg = json.loads((tmp_path / "agg.json").read_text(encoding="utf-8"))
    assert agg["judge_errors"] == jerr and agg["unfilled_human"] == {"fake-003": ["J4_R5"]} and agg["judge_meta"]["judge_model"] == A.JUDGE_MODEL


def test_not_called_judge_never_calls():
    j = A.NotCalledJudge()
    out = j.score_items([{"id": "fake-001", "rubrics": ["J1", "J3"]}])
    assert out == {"fake-001": {"J1": {"rubric": None, "status": "not_called"}, "J3": {"rubric": None, "status": "not_called"}}}
    assert j.called == 0 and j.model_id == "claude-sonnet-5-5"
    labels, _, errs = A.judge_to_labels({"items": out})
    assert labels == {} and len(errs) == 2


# ------------------------------------------------------------------ 재보정 선택(AG-12-07 A, 2026-11-18): 이미 쓴 문항 제외·층 할당 덮어쓰기·파일 접두

def test_select_recalib_excludes_used_ids_and_uses_alloc_override(fake_files, tmp_path: Path):
    res_path, set_path = fake_files
    result = S.load_result(res_path)
    dev = S.load_set(set_path)
    first = S.select(result, dev)
    out = tmp_path / "out"
    S.write_outputs(first, out, result_path=res_path, set_path=set_path, result_meta=result["meta"])
    used = S.used_ids_from_manifest(out / S.MANIFEST)
    assert len(used) == 40
    alloc = S.parse_alloc("J3=8,J5=7")
    assert {k: v[1] for k, v in alloc.items()} == {"J3": 8, "J5": 7}
    sel = S.select(result, dev, alloc=alloc, exclude_ids=used, rubrics_only={"J3", "J5"})
    assert all(set(p["rubrics"]) <= {"J3", "J5"} for p in sel["selected"]) and sel["rubrics_only"] == ["J3", "J5"]
    ids = [p["res"]["id"] for p in sel["selected"]]
    assert len(ids) == 15 == sel["n_total"] and not (set(ids) & used) and sel["shortfall"] == {}
    assert {p["stratum"] for p in sel["selected"]} == {"J3", "J5"} and len(sel["by_stratum"]["J3"]) == 8 and len(sel["by_stratum"]["J5"]) == 7
    assert sum(1 for e in sel["excluded"] if e["reason"].startswith("앞선 보정")) == 40
    assert all(p["res"]["branch_label"] in ("오정보", "근거 없음") for p in sel["selected"])
    man = S.write_outputs(sel, out, result_path=res_path, set_path=set_path, result_meta=result["meta"], name="calib15-v2",
                          exclude_manifest=out / S.MANIFEST)
    assert (out / "calib15-v2-labels.csv").exists() and (out / "calib15-v2-items.jsonl").exists() and (out / "calib15-v2-manifest.json").exists()
    assert man["n"] == 15 and man["alloc"] == {"J3": 8, "J5": 7} and man["name"] == "calib15-v2" and man["n_excluded_used"] == 40
    assert man["rubrics_only"] == ["J3", "J5"]
    assert (out / S.LABELS_CSV).read_text(encoding="utf-8-sig").startswith("id,")  # 기존 40 라벨 파일은 그대로
    with open(out / "calib15-v2-labels.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 15 and all(r["J4_R1"] == S.NA and r["J1(뒷받침안됨/전체주장)"] == S.NA for r in rows)
    assert all("J1" not in r["적용루브릭"] for r in rows)
    items = [json.loads(ln) for ln in (out / "calib15-v2-items.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all("J1" not in it["rubrics"] for it in items)
    with pytest.raises(SystemExit):
        S.parse_alloc("J9=1")


def test_cli_recalib_options(fake_files, tmp_path: Path, capsys):
    res_path, set_path = fake_files
    out = tmp_path / "o"
    assert S.main(["--result", str(res_path), "--set", str(set_path), "--out-dir", str(out)]) == 0
    assert S.main(["--result", str(res_path), "--set", str(set_path), "--out-dir", str(out), "--alloc", "J3=8,J5=7",
                   "--exclude-manifest", str(out / S.MANIFEST), "--name", "calib15-v2", "--rubrics", "J3,J5"]) == 0
    assert "선택 15/15" in capsys.readouterr().out and (out / "calib15-v2-manifest.json").exists()
