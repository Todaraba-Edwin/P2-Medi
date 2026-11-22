"""개발 비용 원장 L5(BE-15, RFP-34-05). `evaluation/mock_gen/_common.py`의 원장과 같은 구조(JSON 누적 USD).

- 개발·디버깅 중 OpenAI 호출 누적 비용(dev)과 평가 실행 몫(eval)을 따로 센다.
- dev 상한 기본 2.5 USD(BE-15-01 A+수정: 크레딧 $8 유지, 본 측정 약 $4.3 / 개발 $2.5 / 예비 약 $1.2).
  넘기려 하면 실호출 전에 BudgetExceeded로 중단하고 replay(캐시 적중)만 허용하도록 안내한다.
- 단가는 이 파일에 적지 않는다(gpt-6-luna 호출 확인 뒤 호출자가 계산한 cost를 넘긴다).
- 원장 위치: data/mock/openai_ledger.json(로컬 전용). 환경변수 MEDIAGENT_LEDGER_PATH로 바꿀 수 있다(시험용).
- 서비스 비전 몫(vision, BE-14 〔D4〕 A 2026-11-22): 사진 약 이름 추출(`app.api.vision`)의 실호출 비용. 상한 기본 0.30 USD를
  구분별 상한(`bucket_caps`)으로 강제한다. dev·eval 동작은 그대로다(dev 상한은 `cap_usd`, eval은 세기만).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path

_log = logging.getLogger(__name__)

DEV_CAP_USD = 2.5
WARN_FRACTION = 0.8
VISION_CAP_USD = 0.30  # BE-14 〔D4〕 A: 서비스 비전 상한(장당 약 0.0006 USD, 약 500장)
BUCKETS = ("dev", "eval", "vision")
DEFAULT_BUCKET_CAPS: dict[str, float] = {"vision": VISION_CAP_USD}  # dev 상한은 cap_usd 인자, eval은 상한 없음
REPO_ROOT = Path(__file__).resolve().parents[3]


class BudgetExceeded(RuntimeError):
    """개발 상한을 넘기려 할 때. 실호출을 막고 LLM_CACHE=replay만 쓰게 한다."""


def default_path() -> Path:
    return Path(os.environ.get("MEDIAGENT_LEDGER_PATH") or (REPO_ROOT / "data" / "mock" / "openai_ledger.json"))


class CostLedger:
    def __init__(self, path: Path | None = None, cap_usd: float = DEV_CAP_USD, bucket_caps: Mapping[str, float] | None = None) -> None:
        self.path = Path(path) if path else default_path()
        self.cap_usd = cap_usd
        self.bucket_caps = {**DEFAULT_BUCKET_CAPS, **(bucket_caps or {})}  # dev 외 구분별 상한(없는 구분은 세기만)
        self._lock = threading.Lock()

    def _read(self) -> dict[str, float]:
        if not self.path.exists():
            return {b: 0.0 for b in BUCKETS}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return {b: float(data.get(b, 0.0)) for b in BUCKETS}

    def _write(self, data: dict[str, float]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({k: round(v, 6) for k, v in data.items()}, f)
        os.replace(tmp, self.path)

    def spent(self, bucket: str = "dev") -> float:
        self._check_bucket(bucket)
        return self._read()[bucket]

    def cap_for(self, bucket: str) -> float | None:
        """구분의 상한. dev는 `cap_usd`, 그 밖은 `bucket_caps`(없으면 None = 세기만)."""
        self._check_bucket(bucket)
        return self.cap_usd if bucket == "dev" else self.bucket_caps.get(bucket)

    def guard(self, estimated_usd: float = 0.0, bucket: str = "dev") -> None:
        """실호출 직전에 부른다. dev 몫과 구분별 상한이 있는 몫(vision)만 상한을 강제하고 eval 몫은 세기만 한다."""
        cap = self.cap_for(bucket)
        if cap is None:
            return
        if bucket != "dev":
            spent_b = self._read()[bucket]
            if spent_b + estimated_usd > cap:
                raise BudgetExceeded(f"{bucket} 비용 상한 초과: 누적 ${spent_b:.4f} + 예상 ${estimated_usd:.4f} > 상한 ${cap}. 실호출을 중단한다.")
            return
        spent = self._read()["dev"]
        if spent + estimated_usd > self.cap_usd:
            raise BudgetExceeded(
                f"개발 비용 상한 초과: 누적 ${spent:.4f} + 예상 ${estimated_usd:.4f} > 상한 ${self.cap_usd}. "
                "실호출을 중단한다. LLM_CACHE=replay로 저장본만 쓰거나, 사용자가 상한을 조정한다."
            )

    def add(self, cost_usd: float, bucket: str = "dev") -> float:
        """호출이 끝난 뒤 실제 비용을 더한다. 누적을 돌려준다. 상한의 80%를 넘으면 경고를 남긴다."""
        self._check_bucket(bucket)
        if cost_usd < 0:
            raise ValueError("비용은 음수일 수 없다")
        with self._lock:
            data = self._read()
            data[bucket] += cost_usd
            self._write(data)
        if bucket == "dev" and data["dev"] >= self.cap_usd * WARN_FRACTION:
            _log.warning("개발 비용 원장: 누적 $%.4f / 상한 $%.2f", data["dev"], self.cap_usd)
        elif bucket != "dev" and (cap := self.bucket_caps.get(bucket)) is not None and data[bucket] >= cap * WARN_FRACTION:
            _log.warning("비용 원장(%s): 누적 $%.4f / 상한 $%.2f", bucket, data[bucket], cap)
        return data[bucket]

    @staticmethod
    def _check_bucket(bucket: str) -> None:
        if bucket not in BUCKETS:
            raise ValueError(f"원장 구분은 {BUCKETS} 중 하나: {bucket!r}")
