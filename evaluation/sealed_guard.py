"""시험셋(`*.SEALED.jsonl`) 열람 가드(RFP-26-04, PJ2-RFP.md 9.1절 8번).

시험셋은 개선 중에 열람·분석하지 않는다. 평가 코드가 시험셋 파일을 열려면 **두 가지가 모두** 있어야 한다.
  1) 환경변수 `MEDIAGENT_ALLOW_SEALED`의 값이 정확히 `SEALED_ENV_VALUE`
  2) 호출하는 쪽의 명시 플래그 `allow_sealed=True`(CLI `--allow-sealed`)
하나라도 없으면 파일을 **열기 전에** `SealedAccessError`를 낸다. 이름 판단은 심볼릭 링크를 따라간 실제 경로와 원래 경로 둘 다 본다.
시험셋으로 돌린 결과는 점수만 저장하고 문항별 기록(실패 사례)은 남기지 않는다(`eval_runner`가 처리).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SEALED_ENV = "MEDIAGENT_ALLOW_SEALED"
SEALED_ENV_VALUE = "final-report-only"  # 값은 비밀이 아니다. 실수로 켜지지 않게 하는 확인 문자열
SEALED_MARK = ".sealed."


class SealedAccessError(PermissionError):
    """시험셋 열람이 허용되지 않았다."""


def is_sealed(path: str | os.PathLike[str]) -> bool:
    p = Path(path)
    names = {p.name.lower()}
    try:
        names.add(p.resolve().name.lower())  # 링크·상대 경로로 이름을 감춰도 실제 파일 이름을 본다
    except OSError:
        pass
    return any(SEALED_MARK in n or n.endswith(".sealed") for n in names)


def sealed_allowed(*, allow_sealed: bool, env: Mapping[str, str] | None = None) -> bool:
    e = os.environ if env is None else env
    return bool(allow_sealed) and e.get(SEALED_ENV, "") == SEALED_ENV_VALUE


def check_access(path: str | os.PathLike[str], *, allow_sealed: bool = False, env: Mapping[str, str] | None = None) -> bool:
    """열어도 되면 시험셋 여부(True/False)를 돌려주고, 시험셋인데 허용되지 않았으면 예외. 파일은 열지 않는다."""
    if not is_sealed(path):
        return False
    if not sealed_allowed(allow_sealed=allow_sealed, env=env):
        raise SealedAccessError(
            f"시험셋 열람 금지(RFP-26-04): {Path(path).name}. 환경변수 {SEALED_ENV}와 명시 플래그(allow_sealed/--allow-sealed)가 모두 있어야 한다"
        )
    return True


def read_bytes(path: str | os.PathLike[str], *, allow_sealed: bool = False, env: Mapping[str, str] | None = None) -> bytes:
    check_access(path, allow_sealed=allow_sealed, env=env)
    return Path(path).read_bytes()


def load_jsonl(path: str | os.PathLike[str], *, allow_sealed: bool = False, env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """가드를 거쳐 JSONL 평가 세트를 읽는다."""
    raw = read_bytes(path, allow_sealed=allow_sealed, env=env)
    return [json.loads(ln) for ln in raw.decode("utf-8").splitlines() if ln.strip()]
