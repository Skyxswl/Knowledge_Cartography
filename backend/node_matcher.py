"""
Node matching with LLM-based semantic similarity.

Phase 2 upgrade (updated to Plan C):
- LLM-based semantic matching using Chat API (no embedding API needed)
- Keyword boost for exact name/substring matches as first-pass filter
- Per-node depth_delta based on match quality (not global per-turn)
- Fallback to pure keyword matching when LLM unavailable
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.models import Node

from backend.llm_client import get_llm_settings, is_real_llm_enabled

logger = logging.getLogger(__name__)

_MATCH_WEIGHTS = {
    "mention": 0.18,
    "explain": 0.32,
    "deepen": 0.50,
}

_LLM_SCORE_THRESHOLD = 0.45
_LLM_MAX_DELTA = 0.42

_EXPLAIN_HINTS = ("是", "指", "包括", "作用", "由", "包含", "区别", "定义", "结构", "功能")
_DEEPEN_HINTS = ("为什么", "如何", "机制", "影响", "导致", "例子", "应用", "比较", "差异", "过程")


def _detect_match_type(text: str) -> str:
    """Detect the depth level of the query (global, per-turn classification)."""
    if any(token in text for token in _DEEPEN_HINTS):
        return "deepen"
    if any(token in text for token in _EXPLAIN_HINTS):
        return "explain"
    return "mention"


def _keyword_confidence(text: str, name: str) -> float:
    """Compute keyword-based confidence (exact name match or substring overlap)."""
    if name in text:
        return 0.96
    # Check for significant token overlap (split on common separators)
    separators = ("·", "/", "和", "与", "或", "及")
    for sep in separators:
        if sep in name:
            tokens = name.split(sep)
            overlap = max((len(token) for token in tokens if token and token in text), default=0)
            if overlap >= 2:  # At least 2 tokens matched
                return round(min(0.88, overlap / max(len(name), 1) + 0.25), 3)

    overlap = max((len(token) for token in name.split("·") if token and token in text), default=0)
    if overlap <= 0:
        return 0.0
    return round(min(0.88, overlap / max(len(name), 1) + 0.25), 3)


def _llm_score_nodes(
    text: str,
    nodes: list["Node"],
) -> dict[str, float] | None:
    """
    Use LLM to score semantic relevance between user text and each node.
    Returns dict of node_id -> relevance_score (0-1) or None if LLM unavailable.
    """
    if not is_real_llm_enabled():
        return None

    # Build node context for LLM
    node_items = []
    for node in nodes:
        definition = node.short_definition or "暂无定义"
        node_items.append({
            "node_id": node.node_id,
            "name": node.name,
            "definition": definition[:100],
        })

    # Limit to top 30 most relevant by keyword to keep prompt small
    node_items.sort(key=lambda x: _keyword_confidence(text, x["name"]), reverse=True)
    node_items = node_items[:30]

    prompt = f"""用户问题：「{text}」

请判断每个概念与用户问题的语义相关度（0-1）：
- 1.0 = 高度相关，用户很可能在问这个概念
- 0.7-0.9 = 相关，是话题的一部分
- 0.4-0.6 = 弱相关，可能是背景知识
- 0.0-0.3 = 不相关

概念列表：
{json.dumps(node_items, ensure_ascii=False, indent=2)}

输出JSON（只输出JSON，不要其他文字）：
{{"scores": {{"节点ID": 0.0, ...}}}}

注意：只对列表中的概念打分，不要编造节点ID。"""

    settings = get_llm_settings()

    payload = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": "你是一个语义匹配专家，输出简洁的JSON分数。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 600,
    }
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }

    try:
        import httpx
        with httpx.Client(timeout=30.0, trust_env=False) as client:
            response = client.post(
                f"{settings.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
    except Exception as exc:
        logger.warning("LLM node scoring failed (%s), falling back to keyword-only", exc)
        return None

    data = response.json()
    try:
        raw = data["choices"][0]["message"]["content"].strip()

        # Strip reasoning tags first (e.g., <think>...)
        raw = re.sub(r"<think>.*?", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()

        # Find JSON object by counting braces
        json_start = raw.find("{")
        if json_start < 0:
            logger.warning("No JSON found in LLM scoring response")
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
        scores = parsed.get("scores", {})
        # Convert keys to strings
        return {str(k): float(v) for k, v in scores.items()}
    except Exception as exc:
        logger.warning("Failed to parse LLM scoring response: %s", exc)
        return None


def _compute_depth_delta(llm_score: float | None, keyword_conf: float) -> tuple[float, str]:
    """
    Compute depth_delta per-node based on combined match quality.

    Returns (depth_delta, match_type) where match_type is refined based on
    the actual match quality for this specific node.
    """
    if llm_score is not None and llm_score >= _LLM_SCORE_THRESHOLD:
        # Strong LLM match - determine depth based on score level
        if llm_score >= 0.80:
            return _LLM_MAX_DELTA, "deepen"
        elif llm_score >= 0.65:
            return round(_LLM_MAX_DELTA * 0.75, 3), "explain"
        else:
            return round(_LLM_MAX_DELTA * 0.45, 3), "mention"
    elif keyword_conf >= 0.90:
        # Exact or near-exact name match - treat as "explain" quality
        return 0.28, "explain"
    elif keyword_conf >= 0.50:
        # Moderate keyword match - treat as "mention"
        return 0.12, "mention"
    else:
        return 0.0, "mention"


def match_nodes(text: str, nodes: list["Node"]) -> list[dict[str, float | str]]:
    """
    Match nodes using LLM semantic scoring + keyword filtering.

    - For all nodes: use LLM to score semantic relevance (when available)
    - Keyword matching as first-pass filter and fallback
    - depth_delta is computed per-node (not global per-turn)
    """
    results: list[dict[str, float | str]] = []
    normalized = text.strip()
    if not normalized:
        return results

    # Try LLM-based scoring first (semantic matching)
    llm_scores = _llm_score_nodes(normalized, nodes)
    global_match_type = _detect_match_type(normalized)

    node_map = {node.node_id: node for node in nodes}
    matched_node_ids: set[str] = set()

    for node in nodes:
        keyword_conf = _keyword_confidence(normalized, node.name)

        # Use LLM score if available, otherwise fall back to keyword-only
        llm_score = llm_scores.get(node.node_id) if llm_scores else None

        # Determine if node should be matched
        should_match = False
        final_confidence = 0.0

        if llm_score is not None and llm_score >= _LLM_SCORE_THRESHOLD:
            # Strong LLM match
            should_match = True
            final_confidence = llm_score
        elif keyword_conf >= 0.35:
            # Keyword-based match
            should_match = True
            final_confidence = keyword_conf

        if not should_match:
            continue

        # Compute per-node depth_delta and refined match_type
        depth_delta, refined_match_type = _compute_depth_delta(llm_score, keyword_conf)

        results.append(
            {
                "node_id": node.node_id,
                "match_type": refined_match_type,
                "confidence": final_confidence,
                "depth_delta": depth_delta,
            }
        )
        matched_node_ids.add(node.node_id)

    # Hub parent matching - activate layer 0 parent when child is strongly matched
    hub_matches: list[dict[str, float | str]] = []
    for node_id in list(matched_node_ids):
        node = node_map.get(node_id)
        if not node or node.layer == "0" or not node.parent_id:
            continue
        parent = node_map.get(node.parent_id)
        if not parent or parent.layer != "0" or parent.node_id in matched_node_ids:
            continue

        # Use LLM score for parent if available
        parent_llm_score = llm_scores.get(parent.node_id) if llm_scores else None
        parent_keyword_conf = _keyword_confidence(normalized, parent.name)

        if parent_llm_score is not None and parent_llm_score >= _LLM_SCORE_THRESHOLD:
            hub_matches.append(
                {
                    "node_id": parent.node_id,
                    "match_type": "mention",
                    "confidence": round(parent_llm_score, 4),
                    "depth_delta": 0.12,
                }
            )
        elif parent_keyword_conf >= 0.35:
            hub_matches.append(
                {
                    "node_id": parent.node_id,
                    "match_type": "mention",
                    "confidence": parent_keyword_conf,
                    "depth_delta": _MATCH_WEIGHTS["mention"],
                }
            )
        matched_node_ids.add(parent.node_id)

    results.extend(hub_matches)

    results.sort(key=lambda item: float(item["confidence"]), reverse=True)
    return results