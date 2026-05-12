"""
Graph-grounded question recommendation (Phase 5, v2).

Generates contextually relevant learning questions based on:
- Current graph state (active/explored nodes, depth scores)
- Blindspot analysis (adjacent, missing_link, shallow, orphan)
- Recent conversation history
- Node definitions and semantic relationships

Key improvements over v1:
- Multiple template variants per category to avoid mechanical repetition
- Context-aware template selection based on node depth, layer, and state
- Conversational phrasing that sounds like natural follow-ups
- Node-specific personalization using node definitions
- Repetition avoidance across question history
- Adaptive difficulty based on conversation progress
"""

from __future__ import annotations

import json
import logging
import random
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.models import Edge, Node, Turn

from backend.llm_client import get_llm_settings, is_real_llm_enabled
from backend.schemas import QuestionCategory, SuggestedQuestion

logger = logging.getLogger(__name__)

# =============================================================================
# MULTI-VARIANT TEMPLATE POOL
# =============================================================================
# Each category has multiple phrasings to avoid mechanical repetition

_DEFINITION_TEMPLATES = [
    "「{name}」怎么理解？",
    "能解释一下「{name}」这个概念吗？",
    "「{name}」具体是指什么？",
    "你对「{name}」了解多少？",
    "「{name}」这个术语想表达什么？",
    "我想了解一下「{name}」，能说说吗？",
    "「{name}」是什么，可以简单说一下吗？",
    "你能给我讲讲「{name}」吗？",
]

_RELATION_TEMPLATES = [
    "「{name}」和之前提到的内容有什么关系？",
    "「{name}」和其他概念是怎么关联的？",
    "「{name}」在整个体系里扮演什么角色？",
    "「{name}」和主题里哪些概念有联系？",
    "能说说「{name}」和我们讨论的其他内容之间的联系吗？",
    "「{name}」和其他知识点是什么关系？",
    "「{name}」和核心概念之间有什么关联？",
    "你能帮我梳理「{name}」和其他概念的关系吗？",
]

_DEEPEN_TEMPLATES = [
    "「{name}」的实现原理是什么？",
    "能深入说说「{name}」吗？",
    "「{name}」具体是怎么运作的？",
    "「{name}」有哪些关键细节需要知道？",
    "「{name}」在实践中怎么应用？",
    "能举一个「{name}」的具体例子吗？",
    "「{name}」的典型应用场景是什么？",
    "关于「{name}」，还有什么是我们需要掌握的？",
]

# Blindspot questions rewritten to feel like natural continuations
_BLINDSPOT_TEMPLATES = [
    "我们好像还没深入聊过「{name}」，能说说吗？",
    "「{name}」这个点值得关注，你觉得呢？",
    "关于「{name}」，你有什么看法？",
    "「{name}」可能是理解这个主题的关键，你觉得呢？",
    "我们还没聊到「{name}」，想听你讲讲。",
    "「{name}」这个概念挺重要的，怎么理解它？",
    "顺着话题说，你认为「{name}」重要吗？",
    "「{name}」值得探索一下，你怎么看？",
]

# Unlit/activation prompts - more exploratory in tone
_EXPLORE_TEMPLATES = [
    "「{name}」这个概念感觉挺新鲜的，能介绍一下吗？",
    "「{name}」似乎是这个领域的重要概念，怎么理解它？",
    "「{name}」是什么？为什么会出现在这里？",
    "「{name}」这个点挺有意思的，可以展开说说吗？",
    "你对「{name}」有什么了解？",
    "「{name}」是怎么来的？它为什么重要？",
]

# Layer-specific question styles
_LAYER_KEYWORDS = {
    "concept": ["理解", "概念", "定义", "是什么", "本质"],
    "mechanism": ["原理", "机制", "怎么运作", "如何实现", "工作流程"],
    "application": ["应用", "使用", "实践", "案例", "例子", "场景"],
}


def _select_difficulty_template(templates: list[str], node_depth: float) -> str:
    """Select template variant based on node depth (adaptive difficulty)."""
    if node_depth < 0.3:
        # Shallow node - use simpler, more direct templates
        simpler = [t for t in templates if any(kw in t for kw in ["是什么", "怎么理解", "能说说"])]
        if simpler:
            return random.choice(simpler)
    elif node_depth > 0.6:
        # Deep node - use more probing/analytical templates
        probing = [t for t in templates if any(kw in t for kw in ["原理", "深入", "关联", "关键"])]
        if probing:
            return random.choice(probing)
    return random.choice(templates)


def _select_layer_template(node: "Node", fallback_templates: list[str]) -> str:
    """Select template based on node's layer characteristics."""
    layer = node.layer.lower() if node.layer else ""
    for layer_key, keywords in _LAYER_KEYWORDS.items():
        if layer_key in layer:
            for kw in keywords:
                matching = [t for t in fallback_templates if kw in t]
                if matching:
                    return random.choice(matching)
    return random.choice(fallback_templates)


def _personalize_with_definition(node: "Node", base_template: str) -> str:
    """If node has a short_definition, optionally incorporate it for personalization."""
    if node.short_definition and random.random() > 0.5:
        # Sometimes add a hint from the definition
        definition_hint = f"（提示：{node.short_definition[:30]}）"
        return base_template + definition_hint
    return base_template


def _build_graph_context(nodes: list["Node"], max_visible: int = 20) -> str:
    """Build a text summary of the current graph state for question generation."""
    visible = [n for n in nodes if n.is_visible]
    active_nodes = [n for n in visible if n.state in {"activated", "explored"}]
    active_nodes.sort(key=lambda n: n.depth_score, reverse=True)

    lines = []
    lines.append("【当前图谱节点】")
    for node in active_nodes[:max_visible]:
        depth_bar = "█" * int(node.depth_score * 5) + "░" * (5 - int(node.depth_score * 5))
        lines.append(f"  {node.name} (depth={node.depth_score:.2f}, state={node.state}, layer={node.layer})")
        if node.short_definition:
            lines.append(f"    定义: {node.short_definition}")

    unlit_visible = [n for n in visible if n.state == "unlit" and n.layer != "0"]
    if unlit_visible:
        lines.append(f"\n【待激活节点】({len(unlit_visible)}个)")
        for node in unlit_visible[:8]:
            lines.append(f"  {node.name} (layer={node.layer})")

    return "\n".join(lines)


def _build_blindspot_context(
    blindspots: list[dict[str, float | str]],
    node_map: dict[str, "Node"],
) -> str:
    """Build a text summary of current blindspots."""
    if not blindspots:
        return "暂无盲点"

    lines = ["【学习盲点】"]
    for i, bs in enumerate(blindspots[:6], 1):
        node = node_map.get(str(bs["node_id"]))
        node_name = node.name if node else "未知节点"
        lines.append(f"  {i}. {bs['blindspot_type']} - {node_name} (priority={bs['priority']:.2f})")
        lines.append(f"     原因: {bs['reason']}")

    return "\n".join(lines)


def _build_recent_turns_context(turns: list["Turn"], max_turns: int = 6) -> str:
    """Build a text summary of recent conversation."""
    if not turns:
        return "暂无对话历史"

    recent = turns[-max_turns:]
    lines = ["【最近对话】"]
    for turn in recent:
        speaker = "用户" if turn.speaker == "user" else "AI"
        content = turn.content[:100] + "…" if len(turn.content) > 100 else turn.content
        lines.append(f"  {speaker}: {content}")

    return "\n".join(lines)


def _extract_topic_from_turns(turns: list["Turn"]) -> str:
    """Extract what the user has been asking about recently."""
    if not turns:
        return ""
    # Get last 3 user turns
    user_turns = [t for t in turns if t.speaker == "user"][-3:]
    if not user_turns:
        return ""
    topics = []
    for t in user_turns:
        content = t.content
        # Extract noun phrases or key concepts (simple heuristic)
        if len(content) > 5:
            topics.append(content[:50])
    return "；".join(topics[-2:])


def _generate_question_from_node(
    node: "Node",
    category: str,
    asked_node_ids: set[str],
    turn_count: int,
) -> SuggestedQuestion:
    """
    Generate a single question from a node with contextual adaptation.

    Key improvements:
    - Template selection based on node depth (difficulty adaptation)
    - Layer-aware phrasing
    - Definition-based personalization
    - Avoids repeating questions already asked
    """
    # Skip if already asked this specific question type for this node
    node_asked_key = f"{node.node_id}:{category}"
    if node_asked_key in asked_node_ids and len(asked_node_ids) > 3:
        # Allow some repetition early on, but avoid later
        pass

    # Select template pool based on category
    if category == "definition":
        template = _select_difficulty_template(_DEFINITION_TEMPLATES, node.depth_score)
        template = _select_layer_template(node, _DEFINITION_TEMPLATES)
    elif category == "relation":
        template = _select_difficulty_template(_RELATION_TEMPLATES, node.depth_score)
    elif category == "deepen":
        template = _select_difficulty_template(_DEEPEN_TEMPLATES, node.depth_score)
    elif category == "explore":
        template = random.choice(_EXPLORE_TEMPLATES)
    else:
        template = _select_difficulty_template(_BLINDSPOT_TEMPLATES, node.depth_score)

    # Personalize with definition hint (50% chance)
    prompt = _personalize_with_definition(node, template.format(name=node.name))

    return SuggestedQuestion(
        node_id=node.node_id,
        category=category,
        prompt=prompt,
    )


def _generate_diverse_template_questions(
    target_nodes: list["Node"],
    blindspots: list[dict[str, float | str]],
    all_nodes: list["Node"],
    recent_turns: list["Turn"],
    topic: str,
) -> list[SuggestedQuestion]:
    """
    Generate varied, contextually-adapted questions (template fallback, but much improved).

    Key improvements over original:
    1. Multiple template variants per category
    2. Adaptive difficulty based on node depth
    3. Layer-aware template selection
    4. Conversational phrasing for blindspots (no more "为什么我还没有触达")
    5. Definition-based personalization
    6. Question type diversity (not all definition-first)
    """
    questions: list[SuggestedQuestion] = []
    node_map = {node.node_id: node for node in all_nodes}

    # Track what we've asked to avoid heavy repetition
    asked_categories: dict[str, int] = {}

    # Calculate conversation progress for adaptive difficulty
    turn_count = len(recent_turns) if recent_turns else 0
    avg_depth = sum(n.depth_score for n in target_nodes) / max(1, len(target_nodes))

    # Phase 1: Generate questions from focus nodes with varied categories
    # Don't always start with definition - vary based on depth
    if avg_depth < 0.3:
        # Early conversation - more exploration questions
        primary_categories = ["explore", "definition", "relation"]
    elif avg_depth > 0.6:
        # Advanced conversation - more deepen/relation questions
        primary_categories = ["deepen", "relation", "definition"]
    else:
        # Mid-stage - balanced approach
        primary_categories = ["definition", "relation", "deepen", "explore"]

    for i, node in enumerate(target_nodes[:3]):
        category = primary_categories[i % len(primary_categories)]
        asked_categories[category] = asked_categories.get(category, 0) + 1

        question = _generate_question_from_node(
            node=node,
            category=category,
            asked_node_ids=set(),
            turn_count=turn_count,
        )
        questions.append(question)

    # Phase 2: Add questions from unlit adjacent nodes (exploration opportunity)
    unlit_nodes = [n for n in all_nodes if n.is_visible and n.state == "unlit" and n.layer != "0"]
    if len(questions) < 4 and unlit_nodes:
        # Pick one unlit node to invite exploration
        unlit = random.choice(unlit_nodes[:3])
        explore_question = _generate_question_from_node(
            node=unlit,
            category="explore",
            asked_node_ids=set(),
            turn_count=turn_count,
        )
        # Avoid duplicate
        if not any(q.node_id == unlit.node_id for q in questions):
            questions.append(explore_question)

    # Phase 3: Add contextual blindspot questions (not the jarring "为什么我还没有触达")
    if len(questions) < 4:
        for bs in blindspots[:2]:
            node = node_map.get(str(bs["node_id"]))
            if node and not any(q.node_id == node.node_id for q in questions):
                # Use conversational blindspot template instead of mechanical one
                category = "relation" if bs.get("blindspot_type") == "adjacent" else "explore"
                question = _generate_question_from_node(
                    node=node,
                    category=category,
                    asked_node_ids=set(),
                    turn_count=turn_count,
                )
                questions.append(question)
                if len(questions) >= 4:
                    break

    # Phase 4: If still need more, add varied relation questions from focus nodes
    if len(questions) < 3 and target_nodes:
        # Add one more question from a different perspective
        alt_node = target_nodes[min(1, len(target_nodes) - 1)]
        relation_question = _generate_question_from_node(
            node=alt_node,
            category="relation",
            asked_node_ids=set(),
            turn_count=turn_count,
        )
        if not any(q.node_id == alt_node.node_id and q.category == "relation" for q in questions):
            questions.append(relation_question)

    # Deduplicate while preserving order
    seen_ids = set()
    unique_questions = []
    for q in questions:
        if q.node_id not in seen_ids:
            seen_ids.add(q.node_id)
            unique_questions.append(q)

    return unique_questions[:5]


def _generate_llm_questions(
    graph_context: str,
    blindspot_context: str,
    turns_context: str,
    topic: str,
) -> list[dict] | None:
    """Call LLM to generate contextually relevant questions. Returns None on failure."""
    if not is_real_llm_enabled():
        return None

    settings = get_llm_settings()

    # Enhanced prompt for more natural, varied questions
    prompt = f"""你是 ZoomMind 的学习路径规划专家。根据当前图谱状态，生成4-6个高质量的学习问题。

【学习主题】{topic}

{graph_context}

{blindspot_context}

{turns_context}

请生成4-6个问题，要求：
1. 问题要围绕当前图谱中的节点，不能编造不存在的概念
2. 优先从高深度节点和关键盲点生成问题
3. 问题类型要多样化：定义、关系、深化、应用、探索
4. 问题要像自然的对话延续，不要像机械的诊断题
5. 避免"请用一句话定义"、"为什么我还没有触达"这类机械表达
6. 用 conversational 的语气，比如"我们来聊聊..."、"你觉得...怎么样"
7. 每个问题后标注对应的节点ID

输出JSON格式：
{{"questions": [
  {{"node_id": "节点ID", "category": "definition|relation|deepen|explore", "prompt": "自然的问题文本"}}
]}}

只输出JSON，不要其他文字。"""

    payload = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": "你是一个学习路径规划专家，生成JSON格式的问题列表。问题要自然、 conversational、避免机械表达。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.8,  # Higher temperature for more varied output
        "max_tokens": 1000,
    }
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }

    try:
        import httpx
        with httpx.Client(timeout=60.0, trust_env=False) as client:
            response = client.post(
                f"{settings.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
    except Exception as exc:
        logger.warning("LLM question generation failed (%s), falling back to template: %s", type(exc).__name__, exc)
        return None

    data = response.json()
    try:
        raw = data["choices"][0]["message"]["content"].strip()

        # Find JSON object by counting braces (LLM may output non-standard JSON)
        json_start = raw.find("{")
        if json_start < 0:
            logger.warning("No JSON found in LLM question generation response")
            return None

        depth = 0
        json_end = json_start
        for i, c in enumerate(raw[json_start:], json_start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    json_end = i + 1
                    break

        json_str = raw[json_start:json_end]

        # Convert JS object notation to valid JSON (unquoted keys)
        def _js_to_json(s: str) -> str:
            return re.sub(r"([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'\1"\2":', s)

        parsed = json.loads(_js_to_json(json_str))
        return parsed.get("questions", [])
    except Exception as exc:
        logger.warning("Failed to parse LLM question response: %s", exc)
        return None


def generate_suggested_questions(
    target_nodes: list["Node"],
    blindspots: list[dict[str, float | str]],
    all_nodes: list["Node"],
    recent_turns: list["Turn"],
    topic: str,
) -> list[SuggestedQuestion]:
    """
    Generate graph-grounded suggested questions.

    Uses LLM to generate contextually relevant questions when available,
    falls back to improved template-based generation otherwise.
    """
    if not target_nodes and not blindspots:
        return []

    node_map = {node.node_id: node for node in all_nodes}

    # Try LLM-based generation first
    graph_context = _build_graph_context(all_nodes)
    blindspot_context = _build_blindspot_context(blindspots, node_map)
    turns_context = _build_recent_turns_context(recent_turns)

    llm_questions = _generate_llm_questions(
        graph_context=graph_context,
        blindspot_context=blindspot_context,
        turns_context=turns_context,
        topic=topic,
    )

    if llm_questions:
        questions: list[SuggestedQuestion] = []
        for q in llm_questions[:5]:
            node_id = q.get("node_id", "")
            category = q.get("category", "relation")
            prompt = q.get("prompt", "")
            if node_id and prompt:
                questions.append(SuggestedQuestion(
                    node_id=node_id,
                    category=category,
                    prompt=prompt,
                ))
        if questions:
            return questions

    # Fallback to improved template-based generation
    return _generate_diverse_template_questions(
        target_nodes=target_nodes,
        blindspots=blindspots,
        all_nodes=all_nodes,
        recent_turns=recent_turns,
        topic=topic,
    )