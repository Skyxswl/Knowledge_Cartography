from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Literal

import httpx

from backend.models import Node, Session as SessionModel, Turn


Provider = Literal["mock", "openai-compatible"]


class LLMConfigurationError(RuntimeError):
    pass


class LLMRequestError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMSettings:
    provider: Provider
    api_key: str | None
    base_url: str
    model: str | None
    timeout_seconds: float
    temperature: float
    max_tokens: int
    reasoning_split: bool


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def get_llm_settings() -> LLMSettings:
    _load_dotenv_if_available()
    provider = os.getenv("ZOOMMIND_LLM_PROVIDER", "mock").strip().lower()
    if provider not in {"mock", "openai-compatible"}:
        raise LLMConfigurationError(
            "ZOOMMIND_LLM_PROVIDER must be either 'mock' or 'openai-compatible'."
        )

    return LLMSettings(
        provider=provider,  # type: ignore[arg-type]
        api_key=os.getenv("ZOOMMIND_LLM_API_KEY"),
        base_url=os.getenv("ZOOMMIND_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        model=os.getenv("ZOOMMIND_LLM_MODEL"),
        timeout_seconds=float(os.getenv("ZOOMMIND_LLM_TIMEOUT_SECONDS", "30")),
        temperature=float(os.getenv("ZOOMMIND_LLM_TEMPERATURE", "0.4")),
        max_tokens=int(os.getenv("ZOOMMIND_LLM_MAX_TOKENS", "700")),
        reasoning_split=os.getenv("ZOOMMIND_LLM_REASONING_SPLIT", "false").strip().lower()
        in {"1", "true", "yes", "on"},
    )


def is_real_llm_enabled() -> bool:
    return get_llm_settings().provider != "mock"


def build_learning_messages(
    *,
    session: SessionModel,
    user_content: str,
    all_nodes: list[Node],
    matched_nodes: list[Node],
    recent_turns: list[Turn],
) -> list[dict[str, str]]:
    visible_nodes = [node for node in all_nodes if node.is_visible]
    graph_context = "\n".join(
        f"- {node.name}: {node.short_definition or '暂无定义'}; state={node.state}; layer={node.layer}"
        for node in visible_nodes[:24]
    )
    matched_context = "、".join(node.name for node in matched_nodes[:8]) or "无明确命中"
    history = "\n".join(
        f"{turn.speaker}: {turn.content}"
        for turn in recent_turns[-8:]
    )

    system_prompt = (
        "你是 ZoomMind 的学习型 AI 导师。你的任务不是泛泛聊天，而是帮助学习者围绕当前主题建立可追踪的理解。\n"
        "回答必须满足：\n"
        "1. 使用中文，语气清晰、具体、适合高中到本科低年级学习者。\n"
        "2. 优先围绕已出现的图谱概念回答，不要编造图谱里不存在的系统状态。\n"
        "3. 先直接回答用户问题，再补充概念关系或一个短例子。\n"
        "4. 如果用户问题过宽，主动收束到一个可继续追问的学习问题。\n"
        "5. 控制在 2 到 4 个短段落内。"
    )

    user_prompt = (
        f"当前学习主题：{session.topic}\n\n"
        f"当前可见图谱概念：\n{graph_context or '- 暂无'}\n\n"
        f"本轮命中的图谱概念：{matched_context}\n\n"
        f"最近对话：\n{history or '暂无'}\n\n"
        f"用户本轮问题：{user_content}"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def generate_model_reply(messages: list[dict[str, str]]) -> str:
    settings = get_llm_settings()
    if settings.provider == "mock":
        raise LLMConfigurationError("Real LLM is not enabled.")
    if not settings.api_key:
        raise LLMConfigurationError("ZOOMMIND_LLM_API_KEY is required when real LLM is enabled.")
    if not settings.model:
        raise LLMConfigurationError("ZOOMMIND_LLM_MODEL is required when real LLM is enabled.")

    payload = {
        "model": settings.model,
        "messages": messages,
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
    }
    if settings.reasoning_split:
        payload["reasoning_split"] = True
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=settings.timeout_seconds) as client:
            response = client.post(
                f"{settings.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise LLMRequestError(f"LLM API returned {exc.response.status_code}: {detail}") from exc
    except httpx.HTTPError as exc:
        raise LLMRequestError(f"LLM API request failed: {exc}") from exc

    data = response.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMRequestError("LLM API response did not contain choices[0].message.content.") from exc

    if not isinstance(content, str) or not content.strip():
        raise LLMRequestError("LLM API returned an empty message.")
    return _strip_reasoning_tags(content).strip()


def _strip_reasoning_tags(content: str) -> str:
    return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE)
