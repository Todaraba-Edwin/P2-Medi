"""프롬프트 묶음(`prompt_set@vN.yaml`) 로더와 L0 검사(BE-15, PRD-16-01, PJ2-프롬프트-설계.md 6장).

- 프롬프트 파일: `backend/prompts/<이름>@v<n>.md`. 맨 앞에 정적 프런트매터(`---` 블록)가 있다.
- 묶음 파일: `backend/prompts/prompt_set@v<n>.yaml`. 실행 한 번에 쓰는 프롬프트 파일을 나열하고, 로그의 `prompt_set` 필드에 이 묶음 이름을 적는다.
- L0 검사는 코드·정규식만 쓴다(LLM 호출 없음). 위반 상세에는 **문장 원문을 싣지 않는다**(규칙 이름·ID·줄 번호만, 평가 문항·비밀값 비노출).
- 개발셋(`evaluation/eval_set/dev_set.jsonl`)과의 문장 일치만 검사한다. 시험셋(`test_set.SEALED.jsonl`)은 개선 중 열람 금지(RFP-26-04)라 열지 않으며, 검사하지 않는다.
- YAML 라이브러리에 기대지 않는다(의존성 추가 없음). 쓰는 문법은 `key: 값`, `[a, b]`, 블록 목록(`- 값`)뿐이다.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.logging.masking import _PATTERNS as SECRET_PATTERNS

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_DIR = REPO_ROOT / "backend" / "prompts"
DEV_SET_PATH = REPO_ROOT / "evaluation" / "eval_set" / "dev_set.jsonl"

SET_NAME_RE = re.compile(r"^prompt_set@v([0-9]{1,4})$")
FILE_REF_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_\-]*)@v([0-9]{1,4})$")
REQUIRED_FRONTMATTER = ("id", "version", "ticket", "model", "h_rules", "golden_ids", "status")
FORBIDDEN_FRONTMATTER = ("last_eval",)  # `llm_cache`가 파일 내용 해시를 키에 넣으므로 평가 결과를 파일에 적으면 캐시가 무효가 된다
STATUSES = ("draft", "adopted")
DEV_ID_RE = re.compile(r"^dev-[0-9]{3,}$")
MIN_SENTENCE_LEN = 12  # 이보다 짧은 개발셋 질문은 우연 일치가 많아 검사하지 않는다

# 약 이름이 든 실제 질문 형식(휴리스틱): 따옴표 문장이나 `질문:`·`Q:`·`사용자:` 줄 안에 제품명 꼴 + 질문 어미
_PRODUCT_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}(?:정|캡슐|시럽|액|산|주|연고|크림)(?:\s*\d+(?:\.\d+)?\s*(?:mg|밀리그램|g|ml))?")
_QUESTION_END_RE = re.compile(r"(?:\?|요|까|나요|죠)[\"”」'’]?\s*$")
_QUOTED_RE = re.compile(r"[\"“「'‘]([^\"”」'’\n]{6,})[\"”」'’]")
_QUESTION_LINE_RE = re.compile(r"^\s*(?:[-*]\s*)?(?:질문|Q|사용자|User)\s*[:：]\s*(.+)$", re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r"<[^>\n]+>|\{[^}\n]+\}")


class PromptSetError(ValueError):
    """묶음 파일 자체를 읽을 수 없을 때(형식 오류)."""


@dataclass(frozen=True)
class Violation:
    file: str
    rule: str  # SET_FORMAT | MISSING_FILE | FRONTMATTER_MISSING | FRONTMATTER_FORBIDDEN | FRONTMATTER_VALUE | SECRET | DEV_SET_SENTENCE | REAL_QUESTION | GOLDEN_ID
    detail: str = ""  # 규칙 이름·칸 이름·줄 번호·문항 ID만. 원문 문장은 싣지 않는다

    def __str__(self) -> str:
        return f"{self.file}: {self.rule}" + (f" ({self.detail})" if self.detail else "")


@dataclass(frozen=True)
class PromptSet:
    name: str  # prompt_set@vN
    prompts: tuple[str, ...]  # `<이름>@v<n>` 목록
    path: Path

    def files(self, prompts_dir: Path = PROMPTS_DIR) -> list[Path]:
        return [prompts_dir / f"{p}.md" for p in self.prompts]


# --------------------------------------------------------------------------- 미니 파서

def _scalar(text: str) -> Any:
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        return [_scalar(x) for x in inner.split(",")] if inner else []
    if t in ("null", "~", ""):
        return None
    return t


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """`key: 값` / `key: [a, b]` / 블록 목록만 읽는 제한 파서. 중첩 구조는 지원하지 않는다(만나면 PromptSetError)."""
    out: dict[str, Any] = {}
    key: str | None = None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        if line.lstrip().startswith("- "):
            if key is None or not isinstance(out.get(key), list):
                raise PromptSetError(f"{n}줄: 목록 항목이 키 없이 나왔다")
            out[key].append(_scalar(line.lstrip()[2:]))
            continue
        if line[0] in " \t":
            raise PromptSetError(f"{n}줄: 들여쓴 중첩 구조는 지원하지 않는다")
        if ":" not in line:
            raise PromptSetError(f"{n}줄: `키: 값` 형식이 아니다")
        k, _, v = line.partition(":")
        k = k.strip()
        if not k:
            raise PromptSetError(f"{n}줄: 빈 키")
        key = k
        out[k] = [] if not v.strip() else _scalar(v)
    return out


def split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    """(프런트매터 dict 또는 None, 본문). 첫 줄이 `---`가 아니면 프런트매터 없음."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return parse_simple_yaml("\n".join(lines[1:i])), "\n".join(lines[i + 1:])
    raise PromptSetError("프런트매터가 닫히지 않았다(`---` 없음)")


# --------------------------------------------------------------------------- 묶음 로더

def load_prompt_set(path: Path) -> PromptSet:
    """묶음 파일을 읽는다. 형식이 틀리면 PromptSetError."""
    data = parse_simple_yaml(path.read_text(encoding="utf-8"))
    name = data.get("name")
    prompts = data.get("prompts")
    if not isinstance(name, str) or not SET_NAME_RE.match(name):
        raise PromptSetError("`name`은 `prompt_set@v<n>` 형식이어야 한다")
    if name != path.stem:
        raise PromptSetError("`name`이 파일 이름과 다르다")
    if not isinstance(prompts, list) or not prompts:
        raise PromptSetError("`prompts`는 비어 있지 않은 목록이어야 한다")
    refs: list[str] = []
    for item in prompts:
        if not isinstance(item, str) or not FILE_REF_RE.match(item):
            raise PromptSetError("`prompts` 항목은 `<이름>@v<n>` 형식이어야 한다")
        refs.append(item)
    names = [FILE_REF_RE.match(r).group(1) for r in refs]  # type: ignore[union-attr]
    if len(set(names)) != len(names) or len(set(refs)) != len(refs):
        raise PromptSetError("같은 프롬프트 이름이 두 번 나열됐다(버전이 달라도 한 묶음에는 하나만)")
    return PromptSet(name, tuple(refs), path)


def resolve_prompt_files(set_name: str, prompts_dir: Path = PROMPTS_DIR) -> list[str]:
    """`cached_openai_call(prompt_files=...)`에 넘길 파일 경로 목록(묶음이 나열한 순서). 캐시 키가 이 파일 내용 해시를 쓴다."""
    ps = load_prompt_set(prompts_dir / f"{set_name}.yaml")
    return [str(p) for p in ps.files(prompts_dir)]


# --------------------------------------------------------------------------- L0 검사

def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def load_dev_questions(path: Path = DEV_SET_PATH) -> dict[str, str]:
    """{문항 ID: 공백 제거한 질문}. 개발셋만 읽는다. 파일이 없으면 빈 dict."""
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("set", "dev") != "dev":  # 안전장치: 개발셋이 아닌 행은 쓰지 않는다
                continue
            q = _norm(str(row.get("question") or ""))
            if len(q) >= MIN_SENTENCE_LEN:
                out[str(row.get("id"))] = q
    return out


def _frontmatter_violations(name: str, fm: dict[str, Any] | None, expected_version: str) -> list[Violation]:
    if fm is None:
        return [Violation(name, "FRONTMATTER_MISSING", "프런트매터 없음")]
    out = [Violation(name, "FRONTMATTER_MISSING", k) for k in REQUIRED_FRONTMATTER if k not in fm]
    out += [Violation(name, "FRONTMATTER_FORBIDDEN", k) for k in FORBIDDEN_FRONTMATTER if k in fm]
    ver = fm.get("version")
    if ver is not None and str(ver).lstrip("v") != expected_version:
        out.append(Violation(name, "FRONTMATTER_VALUE", "version이 파일 이름의 버전과 다르다"))
    if "status" in fm and fm["status"] not in STATUSES:
        out.append(Violation(name, "FRONTMATTER_VALUE", f"status는 {'|'.join(STATUSES)}"))
    golden = fm.get("golden_ids")
    if golden is not None and (not isinstance(golden, list) or any(not DEV_ID_RE.match(str(g)) for g in golden)):
        out.append(Violation(name, "GOLDEN_ID", "golden_ids는 개발셋 ID(dev-nnn)만"))  # 시험셋 ID·임의 문자열 금지
    if "h_rules" in fm and not isinstance(fm["h_rules"], list):
        out.append(Violation(name, "FRONTMATTER_VALUE", "h_rules는 목록"))
    return out


def _real_question_lines(body: str) -> list[int]:
    """약 이름이 든 실제 질문 꼴(따옴표 문장·`질문:` 줄)의 줄 번호. 자리표시자(<약이름>, {name})는 지우고 본다."""
    hits: list[int] = []
    for n, line in enumerate(body.splitlines(), 1):
        cands = [m.group(1) for m in _QUOTED_RE.finditer(line)]
        m = _QUESTION_LINE_RE.match(line)
        if m:
            cands.append(m.group(1))
        for c in cands:
            c = _PLACEHOLDER_RE.sub("", c)
            if _PRODUCT_RE.search(c) and _QUESTION_END_RE.search(c.strip()):
                hits.append(n)
                break
    return hits


def check_prompt_file(path: Path, *, dev_questions: dict[str, str] | None = None) -> list[Violation]:
    """프롬프트 파일 하나의 L0 검사."""
    name = path.name
    m = re.match(r"^([A-Za-z][A-Za-z0-9_\-]*)@v([0-9]{1,4})\.md$", name)
    if not m:
        return [Violation(name, "SET_FORMAT", "파일 이름은 `<이름>@v<n>.md`")]
    text = path.read_text(encoding="utf-8")
    try:
        fm, body = split_frontmatter(text)
    except PromptSetError as exc:
        return [Violation(name, "FRONTMATTER_MISSING", str(exc))]
    out = _frontmatter_violations(name, fm, m.group(2))
    for n, line in enumerate(text.splitlines(), 1):
        if any(p.search(line) for p in SECRET_PATTERNS):
            out.append(Violation(name, "SECRET", f"{n}줄"))  # 매치된 값은 싣지 않는다
    if dev_questions:
        body_n = _norm(text)
        out += [Violation(name, "DEV_SET_SENTENCE", qid) for qid, q in sorted(dev_questions.items()) if q in body_n]
    out += [Violation(name, "REAL_QUESTION", f"{n}줄") for n in _real_question_lines(body)]
    return out


def check_prompt_set(path: Path, *, prompts_dir: Path | None = None, dev_questions: dict[str, str] | None = None) -> list[Violation]:
    """묶음 파일 하나와 나열된 프롬프트 파일들의 L0 검사. 빈 목록이면 통과."""
    prompts_dir = prompts_dir or path.parent
    try:
        ps = load_prompt_set(path)
    except PromptSetError as exc:
        return [Violation(path.name, "SET_FORMAT", str(exc))]
    out: list[Violation] = []
    for ref, f in zip(ps.prompts, ps.files(prompts_dir), strict=True):
        if not f.is_file():
            out.append(Violation(path.name, "MISSING_FILE", ref))
        else:
            out += check_prompt_file(f, dev_questions=dev_questions)
    return out


def check_all(prompts_dir: Path = PROMPTS_DIR, dev_set_path: Path = DEV_SET_PATH) -> list[Violation]:
    """폴더의 모든 묶음·프롬프트 파일 검사(묶음에 없는 프롬프트 파일도 개별로 본다)."""
    dev_q = load_dev_questions(dev_set_path)
    out: list[Violation] = []
    seen: set[Path] = set()
    for sp in sorted(prompts_dir.glob("prompt_set@v*.yaml")):
        out += check_prompt_set(sp, prompts_dir=prompts_dir, dev_questions=dev_q)
        try:
            seen.update(load_prompt_set(sp).files(prompts_dir))
        except PromptSetError:
            pass
    for f in sorted(prompts_dir.glob("*@v*.md")):
        if f not in seen:
            out += check_prompt_file(f, dev_questions=dev_q)
    return out


def main(argv: list[str] | None = None) -> int:
    """`cd backend && .venv/bin/python -m app.llm.prompts` — 위반이 있으면 1을 돌려준다(pre-commit 훅)."""
    del argv
    bad = check_all()
    for v in bad:
        print(v, file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
