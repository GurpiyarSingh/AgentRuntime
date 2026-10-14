"""The translation boundary to LangChain, in particular how images travel.

OpenAI only accepts text in tool messages, and requires an assistant's tool
calls to be answered by an unbroken run of tool messages. These tests pin
down that images arrive as one user turn after that run, never inside it.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_runtime.agent.messages import (
    AssistantMessage,
    ImageAttachment,
    Message,
    SystemMessage,
    ToolCall,
    UserMessage,
)
from agent_runtime.agent.messages import ToolMessage as OurToolMessage
from agent_runtime.agent.openai import _to_langchain

PIXEL = ImageAttachment(media_type="image/png", data="AAAA", label="a.png", detail="low")


def _calls(*ids: str) -> AssistantMessage:
    calls = [ToolCall(id=call_id, name="read_image", arguments={}) for call_id in ids]
    return AssistantMessage(tool_calls=calls)


def test_images_follow_the_whole_run_of_tool_messages() -> None:
    messages: list[Message] = [
        SystemMessage(content="sys"),
        UserMessage(content="look"),
        _calls("c1", "c2"),
        OurToolMessage(tool_call_id="c1", name="read_image", content="img 1", images=[PIXEL]),
        OurToolMessage(tool_call_id="c2", name="read_image", content="img 2", images=[PIXEL]),
        AssistantMessage(content="I see two images."),
    ]

    converted = _to_langchain(messages)
    kinds = [type(m) for m in converted]

    assert kinds[2:] == [AIMessage, ToolMessage, ToolMessage, HumanMessage, AIMessage]
    images_turn = converted[5]
    assert isinstance(images_turn.content, list)
    image_parts = [
        part
        for part in images_turn.content
        if isinstance(part, dict) and part["type"] == "image_url"
    ]
    assert len(image_parts) == 2
    assert image_parts[0]["image_url"] == {"url": "data:image/png;base64,AAAA", "detail": "low"}


def test_trailing_images_are_flushed_at_the_end() -> None:
    messages: list[Message] = [
        UserMessage(content="look"),
        _calls("c1"),
        OurToolMessage(tool_call_id="c1", name="read_image", content="img", images=[PIXEL]),
    ]
    converted = _to_langchain(messages)
    assert isinstance(converted[-1], HumanMessage)
    assert isinstance(converted[-2], ToolMessage)


def test_no_extra_turn_without_images() -> None:
    messages: list[Message] = [
        UserMessage(content="list"),
        _calls("c1"),
        OurToolMessage(tool_call_id="c1", name="list_files", content="a.txt"),
    ]
    assert [type(m) for m in _to_langchain(messages)] == [HumanMessage, AIMessage, ToolMessage]
