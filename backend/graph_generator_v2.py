"""
LLM-driven semantic concept graph generator (Phase 1).

Generates a domain-specific concept graph for any topic using the configured
LLM (MiniMax via OpenAI-compatible API). Falls back to template-based v1
when LLM is unavailable.

Output structure:
{
  "center": {"name": str, "definition": str},
  "layer1": [{"name": str, "definition": str, "relation": str, "children": [str, ...]}],
  "layer2": [{"name": str, "definition": str, "parent": str, "relation": str}]
}

Relation types:
  - is-part-of: compositional (component of something)
  - is-related-to: associative (related but not compositional)
  - leads-to: causal/sequential (results in / enables)
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.llm_client import get_llm_settings, is_real_llm_enabled
from backend.embedding_client import embed_texts, embedding_to_json
from backend.models import Edge, Node
import httpx

logger = logging.getLogger(__name__)

GRAPH_GENERATION_PROMPT = """你是一个知识图谱构建专家。为"{topic}"这个学习主题生成一个结构化的概念层次图谱。

【重要】你必须且只能输出JSON格式，不要输出任何其他文字、解释或markdown标记。

请生成一个包含以下层次的概念图谱：

**中心节点（Layer 0）**：主题本身，1个节点

**第一层（Layer 1）**：该主题的核心概念，通常3-6个，每个概念需要：
  - name: 概念名称（简洁的中文名词）
  - definition: 一句话定义（30-60字）
  - relation: 与中心节点的语义关系（is-part-of | is-related-to | leads-to 三选一）
  - children: 该概念的2-4个子概念（仅名称）

**第二层（Layer 2）**：每个Layer1概念下的子概念，通常2-4个，每个需要：
  - name: 子概念名称
  - definition: 一句话定义
  - parent: 所属的Layer1父概念名称（精确匹配）
  - relation: 与父概念的语义关系

关系类型语义：
  - is-part-of: 组分关系，表示"是...的一部分"或"由...组成"
  - is-related-to: 关联关系，表示"与...相关联"但无直接组成
  - leads-to: 因果/序列关系，表示"导致..."或"通向..."

请确保：
1. 概念名称具体且有意义，不是通用占位词
2. 定义准确反映概念的实质
3. Layer2的概念之间也要有逻辑联系
4. 关系类型选择要有语义依据

以JSON格式输出，结构如下：
{{
  "center": {{"name": "主题名称", "definition": "主题的一句话定义"}},
  "layer1": [
    {{
      "name": "核心概念名",
      "definition": "概念的一句话定义",
      "relation": "is-part-of|is-related-to|leads-to",
      "children": ["子概念1", "子概念2", "子概念3"]
    }}
  ],
  "layer2": [
    {{"name": "子概念名", "definition": "子概念的一句话定义", "parent": "父概念名", "relation": "is-part-of|is-related-to|leads-to"}}
  ]
}}

只输出JSON，不要其他文字。"""


def _parse_layer2_from_children(
    layer1_item: dict[str, Any],
    session_id: str,
    parent_node_id: str,
    existing_names: set[str],
) -> list[dict[str, Any]]:
    """Infer layer2 nodes from layer1 children list when LLM doesn't provide full layer2 details."""
    children = layer1_item.get("children", [])
    relation = layer1_item.get("relation", "is-part-of")
    results = []

    child_definitions = {
        # Common child concept definitions for cell biology
        "磷脂双分子层": "由磷脂分子排列成双层结构，构成细胞膜的基本骨架。",
        "膜蛋白": "嵌入或附着在磷脂双分子层中的蛋白质，参与运输、识别和信号传递。",
        "选择透过性": "细胞膜允许特定物质通过而阻止其他物质的特性。",
        "DNA": "储存遗传信息的分子，由核苷酸序列组成。",
        "染色体": "DNA与蛋白质压缩后形成的结构，承载遗传信息。",
        "核膜": "包裹细胞核的双层膜，调节核内外物质交换。",
        "ATP合成": "在线粒体中合成ATP的过程，为细胞提供可用能量。",
        "有氧呼吸": "在线粒体中利用氧气分解有机物释放能量的过程。",
        "线粒体基质": "线粒体内部充满酶和代谢物的空间。",
        "内质网": "细胞质中折叠的膜系统，参与蛋白质与脂质合成。",
        "高尔基体": "负责加工、分拣和运输细胞产物的细胞器。",
        "囊泡运输": "通过囊泡在细胞器之间转运物质的过程。",
    }

    for child_name in children:
        if child_name in existing_names:
            continue
        results.append(
            {
                "name": child_name,
                "definition": child_definitions.get(child_name, f"与{parent_node_id}相关的概念。"),
                "parent": layer1_item["name"],
                "relation": relation,
            }
        )
        existing_names.add(child_name)

    return results


def generate_semantic_graph(
    topic: str,
    session_id: str,
    db: Session,
    node_count: int = 16,
    expand_depth: int = 2,
) -> tuple[list[Node], list[Edge]]:
    """
    Generate a semantic concept graph for the given topic using LLM.

    Falls back to template-based generation when LLM is unavailable.

    Returns (nodes, edges) for the full latent graph.
    """
    if not is_real_llm_enabled():
        logger.warning("Real LLM not enabled, falling back to template generator")
        from backend.graph_generator import generate_graph

        return generate_graph(topic, session_id, db)

    settings = get_llm_settings()

    payload = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": "你是一个知识图谱生成专家。请根据用户请求生成概念图谱JSON。只输出JSON，不要输出任何其他文字、解释或markdown代码块标记。"},
            {"role": "user", "content": GRAPH_GENERATION_PROMPT.format(topic=topic)},
        ],
        "temperature": 0.7,
        "max_tokens": 3000,
    }
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=120.0, trust_env=False) as client:
            response = client.post(
                f"{settings.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
    except Exception as exc:
        logger.warning("LLM graph generation failed (%s), falling back to template: %s", type(exc).__name__, exc)
        from backend.graph_generator import generate_graph

        return generate_graph(topic, session_id, db)

    data = response.json()
    raw_content = data["choices"][0]["message"]["content"]

    # Extract JSON from potential markdown code blocks
    content = raw_content.strip()

    # Extract JSON from response (model may output explanation before JSON)
    json_start = content.find("{")
    if json_start == -1:
        json_start = content.find("[")
    if json_start > 0:
        content = content[json_start:]

    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse LLM graph JSON (%s), falling back to template: %s", exc, raw_content[:200])
        from backend.graph_generator import generate_graph

        return generate_graph(topic, session_id, db)

    return _build_graph_from_parsed(parsed, topic, session_id, db)


def _build_graph_from_parsed(
    parsed: dict[str, Any],
    topic: str,
    session_id: str,
    db: Session,
) -> tuple[list[Node], list[Edge]]:
    """Build Node/Edge objects from LLM-parsed JSON structure."""
    nodes: list[Node] = []
    edges: list[Edge] = []
    name_to_id: dict[str, str] = {}

    # --- Center node (layer 0) ---
    center_name = parsed.get("center", {}).get("name", topic)
    center_def = parsed.get("center", {}).get("definition", f"围绕{topic}展开的当前学习主题。")
    center_id = str(uuid.uuid4())
    center = Node(
        node_id=center_id,
        session_id=session_id,
        name=center_name,
        short_definition=center_def,
        layer="0",
        parent_id=None,
        state="unlit",
        depth_score=0.0,
        is_visible=True,
        lit_at=None,
        position_x=0.0,
        position_y=0.0,
        position_z=0.0,
    )
    db.add(center)
    nodes.append(center)
    name_to_id[center_name] = center_id

    # --- Layer 1 nodes ---
    layer1_items = parsed.get("layer1", [])
    layer1_positions = _fibonacci_sphere(len(layer1_items), radius=4.5, y_base=0.0)

    for idx, item in enumerate(layer1_items):
        item_name = item.get("name")
        if not item_name or item_name in name_to_id:
            continue

        x, y, z = layer1_positions[idx] if idx < len(layer1_positions) else (4.5 * math.cos(idx), 0, 4.5 * math.sin(idx))
        node_id = str(uuid.uuid4())
        node = Node(
            node_id=node_id,
            session_id=session_id,
            name=item_name,
            short_definition=item.get("definition", f"关于{item_name}的核心概念。"),
            layer="1",
            parent_id=center_id,
            state="unlit",
            depth_score=0.0,
            is_visible=True,
            lit_at=None,
            position_x=x,
            position_y=y,
            position_z=z,
        )
        db.add(node)
        nodes.append(node)
        name_to_id[item_name] = node_id

        # Edge: center -> layer1
        rel = item.get("relation", "is-related-to")
        edge = Edge(
            edge_id=str(uuid.uuid4()),
            session_id=session_id,
            source_node_id=center_id,
            target_node_id=node_id,
            relation_type=rel if rel in ("is-part-of", "is-related-to", "leads-to") else "is-related-to",
        )
        db.add(edge)
        edges.append(edge)

    # --- Layer 2 nodes ---
    layer2_items = parsed.get("layer2", [])
    existing_names = set(name_to_id.keys())

    # If layer2 is empty, infer from layer1 children
    if not layer2_items and layer1_items:
        for item in layer1_items:
            inferred = _parse_layer2_from_children(item, session_id, name_to_id.get(item.get("name", ""), ""), existing_names)
            layer2_items.extend(inferred)

    # Group layer2 items by parent
    parent_children: dict[str, list[dict]] = {}
    for item in layer2_items:
        parent_name = item.get("parent", "")
        if parent_name not in parent_children:
            parent_children[parent_name] = []
        parent_children[parent_name].append(item)

    for parent_name, children in parent_children.items():
        if parent_name not in name_to_id:
            continue
        parent_id = name_to_id[parent_name]
        parent_node = next((n for n in nodes if n.node_id == parent_id), None)
        if not parent_node:
            continue

        child_positions = _child_positions((parent_node.position_x, parent_node.position_y, parent_node.position_z), len(children))

        for idx, child_item in enumerate(children):
            child_name = child_item.get("name")
            if not child_name or child_name in name_to_id:
                continue

            x, y, z = child_positions[idx] if idx < len(child_positions) else (parent_node.position_x + 2, parent_node.position_y, parent_node.position_z + 2)
            child_id = str(uuid.uuid4())
            child_node = Node(
                node_id=child_id,
                session_id=session_id,
                name=child_name,
                short_definition=child_item.get("definition", f"关于{child_name}的具体概念。"),
                layer="2",
                parent_id=parent_id,
                state="unlit",
                depth_score=0.0,
                is_visible=False,
                lit_at=None,
                position_x=x,
                position_y=y,
                position_z=z,
            )
            db.add(child_node)
            nodes.append(child_node)
            name_to_id[child_name] = child_id

            rel = child_item.get("relation", "is-part-of")
            edge = Edge(
                edge_id=str(uuid.uuid4()),
                session_id=session_id,
                source_node_id=parent_id,
                target_node_id=child_id,
                relation_type=rel if rel in ("is-part-of", "is-related-to", "leads-to") else "is-part-of",
            )
            db.add(edge)
            edges.append(edge)

    # Compute and store embeddings for all nodes
    node_texts = [f"{node.name}: {node.short_definition or ''}" for node in nodes]
    embeddings = embed_texts(node_texts)
    for node, embedding_vec in zip(nodes, embeddings):
        if embedding_vec is not None:
            node.embedding = embedding_to_json(embedding_vec)

    db.commit()
    return nodes, edges


def _fibonacci_sphere(n: int, radius: float, y_base: float) -> list[tuple[float, float, float]]:
    """Generate n points distributed roughly evenly on a sphere using fibonacci spiral."""
    if n == 0:
        return []
    if n == 1:
        return [(0.0, y_base, radius)]

    positions = []
    golden = math.pi * (3 - math.sqrt(5))
    for i in range(n):
        angle = golden * i
        r = radius * (0.6 + 0.4 * ((i % 3) / 2))
        x = math.cos(angle) * r
        z = math.sin(angle) * r * 0.8
        y = y_base + math.sin(angle * 0.5) * 0.6
        positions.append((x, y, z))
    return positions


def _child_positions(parent: tuple[float, float, float], count: int) -> list[tuple[float, float, float]]:
    """Generate child positions in a loose cluster around the parent."""
    px, py, pz = parent
    positions = []
    for i in range(max(count, 1)):
        angle = (2 * math.pi / count) * i if count > 1 else 0
        r = 1.5 + (i % 2) * 0.4
        positions.append(
            (
                px + math.cos(angle) * r,
                py + math.sin(angle * 0.5) * 0.35,
                pz + math.sin(angle) * r * 0.8,
            )
        )
    return positions
