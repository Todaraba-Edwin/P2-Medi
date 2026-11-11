"""로깅 모듈 L1(BE-15, RFP-34-01·02·03, PJ2-Agent-로깅-전략.md 3·4장).

- 모드: MEDIAGENT_MODE = dev | eval | service. 값이 없거나 틀리면 service(가장 엄격).
  eval은 MEDIAGENT_EVAL=1과 함께여야 한다(어긋나면 ModeError, llm_cache가 캐시를 끄는 신호와 같은 값).
- service: span을 만들지 않는다. 질문·해시·약 이름·프로필·모델 출력·도구 결과·오류 메시지는 **레코드를 만들 때** 버리고
  내용 없는 집계(분 단위 카운트·합계)만 남긴다. 집계 출력은 표준 출력(호스트 로그)이며 앱이 파일로 저장하지 않는다.
- dev·eval: 화이트리스트 필드만 JSONL로 `logs/` 아래에 쓴다. 비밀 마스킹은 모든 모드에 적용한다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

from app.logging.masking import mask_value

_log = logging.getLogger(__name__)

SCHEMA = "mediagent.span@v1"
MODES = ("dev", "eval", "service")
DEFAULT_MODE = "service"
DEV_RETENTION_DAYS = 14  # RFP-34-03 A

REPO_ROOT = Path(__file__).resolve().parents[3]

# 필드 화이트리스트(로깅 전략 4장 (2)). 모르는 필드는 버리고 WARN을 남긴다.
CONTENT_FIELDS = frozenset(
    {
        "input_text",
        "output_text",
        "input_summary",
        "output_summary",
        "evidence_ids",
        "error",
        "error_message",
    }
)
CONTENT_FREE_FIELDS = frozenset(
    {
        "schema", "mode", "run_id", "trace_id", "span_id", "parent_id",
        "item_id", "condition", "repeat_idx", "branch_type",
        "node", "tool", "step", "route", "intent",
        "latency_ms", "tokens_in", "tokens_out", "tokens_cached", "cost_usd",
        "model", "provider", "cache", "cache_key12", "retry", "error_type",
        "model_calls_so_far", "rollbacks_so_far", "harness_event",
        "verdict", "violations", "source", "file_api_match", "data_as_of",
        "end_reason", "prompt_version", "prompt_set", "tool_schema_version", "graph_version",
        "input_source",
        # AG-01 L2(2026-11-11, 가산): trace 머리 레코드(로깅 전략 2장 (3))
        "api_enabled", "total_latency_ms", "total_cost_usd",
    }
)  # fmt: skip
ALLOWED_FIELDS = CONTENT_FREE_FIELDS | CONTENT_FIELDS

# service 집계에 남기는 필드(숫자·열거형 이름뿐). 자유 문자열이 실릴 수 있는 필드는 넣지 않는다.
SERVICE_FIELDS = frozenset(
    {"node", "tool", "latency_ms", "tokens_in", "tokens_out", "cost_usd", "model", "provider", "cache", "retry", "error_type", "end_reason", "prompt_set"}
)

# `prompt_set`은 버전 문자열(`prompt_set@v1`)이라 서비스 모드에도 남는다(RFP-34 충돌 없음, 설계 문서 6장). 자유 문자열이 새지 않게 형식이 맞을 때만 기록한다.
# `prompt_version`은 개별 프롬프트 파일 하나(`agent_system@v1`)를 가리키는 기존 필드로 dev·eval에서만 남고, 실행 한 번의 프롬프트 묶음은 `prompt_set`이다.
PROMPT_SET_RE = re.compile(r"^prompt_set@v[0-9]{1,4}$")

LABEL_MISSING_REASONS = ("ABSENT", "FETCH_FAIL", "SEARCH_MISS", "OUT_OF_SCOPE")  # PRD-11-04
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")  # 경로 이탈 방지


class ModeError(RuntimeError):
    """MEDIAGENT_MODE와 MEDIAGENT_EVAL이 어긋날 때(시작하지 않는다)."""


def _eval_flag() -> bool:
    return os.environ.get("MEDIAGENT_EVAL", "").strip() not in ("", "0", "false", "False")


def get_mode() -> str:
    mode = os.environ.get("MEDIAGENT_MODE", "").strip().lower()
    if mode not in MODES:
        mode = DEFAULT_MODE
    if mode == "eval" and not _eval_flag():
        raise ModeError("MEDIAGENT_MODE=eval이면 MEDIAGENT_EVAL=1도 켜야 한다(llm_cache 강제 off와 짝)")
    return mode


def log_root() -> Path:
    return Path(os.environ.get("MEDIAGENT_LOG_DIR") or (REPO_ROOT / "logs"))


def build_record(mode: str, fields: dict[str, Any]) -> dict[str, Any]:
    """화이트리스트·모드 필터를 적용한 레코드를 만든다. service에서는 내용 필드를 만들 때부터 제외한다."""
    if mode not in MODES:
        raise ValueError(f"알 수 없는 모드: {mode!r}")
    allowed = SERVICE_FIELDS if mode == "service" else ALLOWED_FIELDS
    record: dict[str, Any] = {}
    dropped = []
    for key, value in fields.items():
        if key == "prompt_set" and not (isinstance(value, str) and PROMPT_SET_RE.match(value)):
            dropped.append(key)  # 형식이 다르면 기록하지 않는다(내용이 섞이지 않게)
        elif key in allowed:
            record[key] = value
        else:
            dropped.append(key)
    if dropped and mode != "service":  # service는 이름만으로도 내용이 새지 않게 조용히 버린다
        _log.warning("로깅 화이트리스트에 없는 필드를 버렸다: %s", sorted(dropped))
    if mode == "service":
        if isinstance(fields.get("harness_event"), dict) and "rule" in fields["harness_event"]:
            record["harness_rule"] = str(fields["harness_event"]["rule"])[:8]  # 규칙 ID만(상세 문구는 버림)
        return record
    record["schema"] = SCHEMA
    record["mode"] = mode
    return record


class Aggregator:
    """service 모드의 내용 없는 집계. 분 단위 카운트·합계만 들고 stdout으로 내보낸다."""

    def __init__(self, stream: TextIO | None = None, clock=time.time) -> None:
        self._stream = stream
        self._clock = clock
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._sums: dict[str, float] = {}
        self._minute = int(self._clock() // 60)

    def add_record(self, record: dict[str, Any]) -> None:
        """build_record('service', ...)의 결과를 받는다(요청별 행을 남기지 않고 합산만 한다)."""
        with self._lock:
            self._roll()
            self._inc("spans")
            for key in ("node", "tool", "error_type", "end_reason", "harness_rule", "cache", "model", "prompt_set"):
                if record.get(key) is not None:
                    self._inc(f"{key}={record[key]}")
            for key in ("latency_ms", "tokens_in", "tokens_out", "cost_usd"):
                if isinstance(record.get(key), (int, float)):
                    self._sums[key] = self._sums.get(key, 0.0) + float(record[key])

    def label_missing(self, reason: str) -> None:
        """PRD-11-04 A: 미확보 사유 건수. 사유 코드 이외의 값은 거부한다(내용이 섞이지 않게)."""
        if reason not in LABEL_MISSING_REASONS:
            raise ValueError(f"label_missing 사유 코드가 아니다: {reason!r}")
        with self._lock:
            self._roll()
            self._inc(f"label_missing.{reason}")

    def flush(self) -> dict[str, Any] | None:
        with self._lock:
            return self._emit()

    def _inc(self, name: str) -> None:
        self._counts[name] = self._counts.get(name, 0) + 1

    def _roll(self) -> None:
        minute = int(self._clock() // 60)
        if minute != self._minute:
            self._emit()
            self._minute = minute

    def _emit(self) -> dict[str, Any] | None:
        if not self._counts and not self._sums:
            return None
        line = {
            "schema": "mediagent.agg@v1",
            "mode": "service",
            "minute": datetime.fromtimestamp(self._minute * 60).strftime("%Y-%m-%dT%H:%M"),
            "counts": dict(self._counts),
            "sums": {k: round(v, 6) for k, v in self._sums.items()},
        }
        self._counts.clear()
        self._sums.clear()
        stream = self._stream or sys.stdout
        stream.write(json.dumps(line, ensure_ascii=False) + "\n")
        stream.flush()
        return line


class SpanLogger:
    """모드별 기록기. service에서는 파일을 만들지 않고 Aggregator에만 합산한다."""

    def __init__(self, mode: str | None = None, run_id: str | None = None, aggregator: Aggregator | None = None) -> None:
        self.mode = mode if mode is not None else get_mode()
        if self.mode == "eval":
            if not _eval_flag():
                raise ModeError("eval 모드는 MEDIAGENT_EVAL=1이 필요하다")
            if not run_id or not _RUN_ID_RE.match(run_id):
                raise ValueError("eval 모드는 안전한 run_id(영숫자·_ . -)가 필요하다")
        self.run_id = run_id
        self.aggregator = aggregator or Aggregator()
        self._lock = threading.Lock()

    def path(self) -> Path | None:
        if self.mode == "dev":
            return log_root() / "dev" / f"{datetime.now():%Y-%m-%d}.jsonl"
        if self.mode == "eval":
            return log_root() / "eval" / str(self.run_id) / "spans.jsonl"
        return None

    def log(self, **fields: Any) -> dict[str, Any] | None:
        if self.mode == "eval" and self.run_id:
            fields.setdefault("run_id", self.run_id)
        record = build_record(self.mode, fields)
        if self.mode == "service":
            self.aggregator.add_record(record)
            return record
        try:
            line = json.dumps(mask_value(record), ensure_ascii=False, default=str)
        except Exception as exc:  # noqa: BLE001 - 마스킹 실패는 줄을 버리고 유형만 남긴다
            _log.error("로그 줄을 버렸다(마스킹 실패): %s", type(exc).__name__)
            return None
        path = self.path()
        assert path is not None
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        return record


def cleanup_dev_logs(retention_days: int = DEV_RETENTION_DAYS, now: datetime | None = None) -> list[Path]:
    """logs/dev/ 에서 보관 기간을 넘긴 YYYY-MM-DD.jsonl을 지운다. 지운 파일 목록을 돌려준다(평가 trace는 건드리지 않는다)."""
    cutoff = (now or datetime.now()) - timedelta(days=retention_days)
    removed: list[Path] = []
    dev_dir = log_root() / "dev"
    if not dev_dir.is_dir():
        return removed
    for p in sorted(dev_dir.glob("*.jsonl")):
        try:
            day = datetime.strptime(p.stem, "%Y-%m-%d")
        except ValueError:
            continue  # 날짜 이름이 아니면 건드리지 않는다
        if day < cutoff.replace(hour=0, minute=0, second=0, microsecond=0):
            p.unlink()
            removed.append(p)
    return removed
