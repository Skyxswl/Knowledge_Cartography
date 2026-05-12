import math
import uuid

from sqlalchemy.orm import Session

from backend.embedding_client import embed_texts, embedding_to_json
from backend.models import Edge, Node


_TOPIC_TEMPLATES: dict[str, list[dict[str, object]]] = {
    "细胞生物学": [
        {
            "name": "细胞膜",
            "definition": "控制物质进出并维持细胞边界的结构。",
            "relation": "is-part-of",
            "children": [
                ("磷脂双分子层", "构成细胞膜主体的双层脂质结构。", "is-part-of"),
                ("膜蛋白", "参与运输、识别与信号传递的膜内蛋白。", "is-part-of"),
                ("选择透过性", "让特定物质更容易通过的膜特性。", "leads-to"),
            ],
        },
        {
            "name": "细胞核",
            "definition": "保存遗传信息并调控细胞活动的区域。",
            "relation": "is-part-of",
            "children": [
                ("DNA", "储存遗传信息的分子。", "is-part-of"),
                ("染色体", "DNA 与蛋白质压缩后的结构。", "is-part-of"),
                ("核膜", "包裹细胞核并调节交换的膜。", "is-part-of"),
            ],
        },
        {
            "name": "线粒体",
            "definition": "负责能量转换的重要细胞器。", 
            "relation": "is-part-of",
            "children": [
                ("ATP合成", "为细胞活动提供可用能量的过程。", "leads-to"),
                ("有氧呼吸", "在线粒体中高效释放能量的过程。", "leads-to"),
                ("线粒体基质", "线粒体内部进行代谢反应的空间。", "is-part-of"),
            ],
        },
        {
            "name": "细胞分工",
            "definition": "不同细胞器分工协作维持生命活动。", 
            "relation": "is-related-to",
            "children": [
                ("内质网", "参与蛋白质与脂质加工的细胞器。", "is-related-to"),
                ("高尔基体", "负责加工、分拣与运输的细胞器。", "is-related-to"),
                ("囊泡运输", "在细胞器之间转运物质的过程。", "leads-to"),
            ],
        },
    ],
}


def _fallback_template(topic: str) -> list[dict[str, object]]:
    return [
        {
            "name": f"{topic} 的核心概念",
            "definition": f"{topic} 中最先需要建立的基础概念。",
            "relation": "is-part-of",
            "children": [
                (f"{topic} 的定义", f"解释 {topic} 的基本含义。", "is-part-of"),
                (f"{topic} 的关系", f"说明 {topic} 与周边概念的联系。", "is-related-to"),
                (f"{topic} 的机制", f"解释 {topic} 是如何运作的。", "leads-to"),
            ],
        },
        {
            "name": f"{topic} 的应用",
            "definition": f"{topic} 在真实情境中的典型应用。",
            "relation": "is-related-to",
            "children": [
                (f"{topic} 的案例", f"{topic} 的实际例子。", "is-related-to"),
                (f"{topic} 的影响", f"{topic} 会带来什么影响。", "leads-to"),
                (f"{topic} 的局限", f"{topic} 在使用中的限制。", "is-related-to"),
            ],
        },
    ]


def _lake_positions(count: int, radius: float, y_shift: float, z_scale: float) -> list[tuple[float, float, float]]:
    positions: list[tuple[float, float, float]] = []
    golden = math.pi * (3 - math.sqrt(5))
    for index in range(count):
        angle = golden * index
        local_radius = radius * (0.86 + (index % 3) * 0.14)
        x = math.cos(angle) * local_radius
        z = math.sin(angle) * local_radius * z_scale
        y = y_shift + math.sin(angle * 0.5) * 0.95 + ((index % 2) - 0.5) * 0.28
        positions.append((x, y, z))
    return positions


def _child_positions(parent: tuple[float, float, float], count: int) -> list[tuple[float, float, float]]:
    px, py, pz = parent
    positions: list[tuple[float, float, float]] = []
    parent_angle = math.atan2(pz, px) if px or pz else 0.0
    spread = 1.25 if count > 1 else 0.0
    midpoint = (count - 1) / 2
    for index in range(count):
        offset = (index - midpoint) * spread
        angle = parent_angle + offset
        radius = 2.45 + (index % 2) * 0.42
        positions.append(
            (
                px + math.cos(angle) * radius,
                py + math.sin(offset) * 0.72 + (index - midpoint) * 0.18,
                pz + math.sin(angle) * radius * 0.95,
            )
        )
    return positions


def generate_graph(topic: str, session_id: str, db: Session) -> tuple[list[Node], list[Edge]]:
    nodes: list[Node] = []
    edges: list[Edge] = []
    template = _TOPIC_TEMPLATES.get(topic, _fallback_template(topic))

    center_id = str(uuid.uuid4())
    center = Node(
        node_id=center_id,
        session_id=session_id,
        name=topic,
        short_definition=f"围绕 {topic} 展开的当前学习主题。",
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

    layer1_positions = _lake_positions(len(template), radius=4.8, y_shift=0.0, z_scale=0.78)
    layer1_nodes: list[Node] = []

    for index, item in enumerate(template):
        x, y, z = layer1_positions[index]
        node_id = str(uuid.uuid4())
        node = Node(
            node_id=node_id,
            session_id=session_id,
            name=str(item["name"]),
            short_definition=str(item["definition"]),
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
        layer1_nodes.append(node)

        edge = Edge(
            edge_id=str(uuid.uuid4()),
            session_id=session_id,
            source_node_id=center_id,
            target_node_id=node_id,
            relation_type=str(item["relation"]),
        )
        db.add(edge)
        edges.append(edge)

    for parent, item in zip(layer1_nodes, template):
        child_positions = _child_positions((parent.position_x, parent.position_y, parent.position_z), len(item["children"]))
        for (name, definition, relation_type), (x, y, z) in zip(item["children"], child_positions):
            node_id = str(uuid.uuid4())
            node = Node(
                node_id=node_id,
                session_id=session_id,
                name=name,
                short_definition=definition,
                layer="2",
                parent_id=parent.node_id,
                state="unlit",
                depth_score=0.0,
                is_visible=False,
                lit_at=None,
                position_x=x,
                position_y=y,
                position_z=z,
            )
            db.add(node)
            nodes.append(node)

            edge = Edge(
                edge_id=str(uuid.uuid4()),
                session_id=session_id,
                source_node_id=parent.node_id,
                target_node_id=node_id,
                relation_type=relation_type,
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
