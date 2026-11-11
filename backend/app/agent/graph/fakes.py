"""오프라인 시험용 가짜 모델(LLM·네트워크 호출 0). 시나리오 스크립트대로 응답한다.

- `ScriptedToolModel`: `bind_tools`를 받는 `BaseChatModel`. 호출마다 다음 `AIMessage`(도구 호출 포함)를 돌려준다. 스크립트가 끝나면 마지막 것을 반복하거나(`repeat_last`) 오류를 낸다.
- `ScriptedSummary`: `summary_model`(구조화 출력) 자리. `.invoke(messages)`가 다음 `AnswerDraft` dict를 돌려준다.
- 호출 기록(`calls`)에는 메시지 수만 남긴다(내용 아님).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field, PrivateAttr


def tool_call(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class ScriptedToolModel(BaseChatModel):
    script: list[AIMessage] = Field(default_factory=list)
    repeat_last: bool = False
    _i: int = PrivateAttr(default=0)
    calls: list[int] = Field(default_factory=list)  # 호출마다 입력 메시지 수

    @property
    def _llm_type(self) -> str:
        return "scripted-tool-model"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedToolModel:  # noqa: ARG002
        return self

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        self.calls.append(len(messages))
        if self._i >= len(self.script):
            if not (self.repeat_last and self.script):
                raise RuntimeError("가짜 모델 스크립트가 끝났다")
            msg = self.script[-1].model_copy(update={"id": None})  # 같은 id면 add_messages가 덮어쓰므로 새 메시지로
        else:
            msg = self.script[self._i]
            self._i += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])


class ScriptedSummary:
    def __init__(self, drafts: Sequence[Any], *, repeat_last: bool = True) -> None:
        self.drafts = list(drafts)
        self.repeat_last = repeat_last
        self.calls: list[int] = []
        self._i = 0

    def invoke(self, messages: Sequence[Any], **kwargs: Any) -> Any:  # noqa: ARG002
        self.calls.append(len(messages))
        if self._i >= len(self.drafts):
            if not (self.repeat_last and self.drafts):
                raise RuntimeError("가짜 요약 스크립트가 끝났다")
            return self.drafts[-1]
        d = self.drafts[self._i]
        self._i += 1
        return d
