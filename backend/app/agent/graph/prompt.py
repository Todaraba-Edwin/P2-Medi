"""시스템 프롬프트·요약 프롬프트 파일 로더. 사용자 검토 카드 승인 전(`status: draft`)에는 `allow_draft=True`를 명시해야 읽힌다(PRD-16-01·03)."""

from __future__ import annotations

from pathlib import Path

from app.llm.prompts import PROMPTS_DIR, PromptSetError, load_prompt_set, split_frontmatter

SUMMARY_PROMPT_NAME = "answer_summary"  # 묶음 파일에서 요약 프롬프트를 가리키는 이름(`answer_summary@vN`)


class DraftPromptError(RuntimeError):
    """채택되지 않은 프롬프트를 기준선에 연결하려 할 때."""


def load_system_prompt(name: str = "agent_system@v2", *, allow_draft: bool = False, prompts_dir: Path = PROMPTS_DIR) -> str:
    text = (prompts_dir / f"{name}.md").read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    if fm is None:
        raise PromptSetError(f"{name}: 프런트매터 없음")
    if fm.get("status") != "adopted" and not allow_draft:
        raise DraftPromptError(f"{name}은 status={fm.get('status')}: 사용자 승인(검토 카드) 전에는 연결하지 않는다")
    return body.strip()


def load_summary_instruction(prompt_set: str, *, allow_draft: bool = False, prompts_dir: Path = PROMPTS_DIR) -> str | None:
    """묶음이 나열한 요약 프롬프트(`answer_summary@vN`) 본문. 묶음에 없으면 None(→ 그래프는 코드 상수 `SUMMARY_INSTRUCTION`을 쓴다).

    요약 프롬프트가 `draft`면 `allow_draft=True`를 명시해야 읽힌다(시스템 프롬프트와 같은 규칙).
    """
    ps = load_prompt_set(prompts_dir / f"{prompt_set}.yaml")
    ref = next((r for r in ps.prompts if r.split("@", 1)[0] == SUMMARY_PROMPT_NAME), None)
    if ref is None:
        return None
    return load_system_prompt(ref, allow_draft=allow_draft, prompts_dir=prompts_dir)
