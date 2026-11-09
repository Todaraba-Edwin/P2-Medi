"""mock 세트 공통: 레코드 메타(mock·모델·세트 버전)와 manifest 기록."""
import hashlib, json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "mock"


def sha(*parts):
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()[:10]


def stamp(rec, set_name, version, model):
    """모든 레코드에 mock 표시·생성 모델·세트 버전을 넣는다(RFP-31 §4). model은 'code'(코드 생성) 또는 모델 ID."""
    return {"mock": True, "set": set_name, "set_version": version, "generated_by": model, **rec}


def write_jsonl(path, recs):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_manifest(set_dir, set_name, version, models, prompt_hashes, counts, cost_usd, notes=None):
    m = {"mock": True, "set": set_name, "set_version": version, "created": time.strftime("%F %T"),
         "models": models, "prompt_hashes": prompt_hashes, "counts": counts, "cost_usd": round(cost_usd, 4),
         "note": "합성·가상 데이터. W1 개발·테스트용이며 평가 측정 값이 아니다(RFP-31). 값(등급·코드·고시·기준일)은 data/ 파일에서 코드가 가져왔다.",
         **(notes or {})}
    (set_dir / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return m
