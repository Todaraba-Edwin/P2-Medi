"""시스템 프롬프트 파일 로더. 사용자 검토 카드 승인 전(`status: draft`)에는 `allow_draft=True`를 명시해야 읽힌다(PRD-16-01·03)."""

from __future__ import annotations

from pathlib import Path

from app.llm.prompts import PROMPTS_DIR, PromptSetError, split_frontmatter


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
