import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from backend.blindspot_detector import compute_blindspots
from backend.database import get_db
from backend.llm_client import (
    LLMConfigurationError,
    LLMRequestError,
    build_learning_messages,
    generate_model_reply,
    is_real_llm_enabled,
)
from backend.models import Edge, ExperimentEvent, Node, Session as SessionModel, Turn, TurnNodeMatch
from backend.node_matcher import match_nodes
from backend.question_generator import generate_suggested_questions
from backend.schemas import BlindspotItem, MatchItem, NodeState, SuggestedQuestion, TurnCreate, TurnItem, TurnResponse

router = APIRouter(prefix="/api/sessions", tags=["turns"])
logger = logging.getLogger(__name__)


def _mock_ai_reply(user_content: str, matched_names: list[str], fallback_note: str | None = None) -> str:
    if matched_names:
        names = "、".join(matched_names[:3])
        reply = (
            f"可以先从 {names} 入手。"
            "把这些概念讲清楚后，再顺着它们之间的关系继续追问，会更容易形成完整理解。"
        )
    else:
        reply = "这个问题可以先拆成一个核心概念、一个相关关系和一个具体例子来理解。"

    if fallback_note:
        return f"{reply}\n\n{fallback_note}"
    return reply


def _generate_ai_reply(
    *,
    session: SessionModel,
    user_content: str,
    all_nodes: list[Node],
    matched_nodes: list[Node],
    recent_turns: list[Turn],
) -> str:
    if not is_real_llm_enabled():
        return _mock_ai_reply(user_content, [node.name for node in matched_nodes])

    messages = build_learning_messages(
        session=session,
        user_content=user_content,
        all_nodes=all_nodes,
        matched_nodes=matched_nodes,
        recent_turns=recent_turns,
    )
    try:
        return generate_model_reply(messages)
    except LLMConfigurationError as exc:
        logger.warning("ZoomMind real LLM disabled by configuration, falling back to mock reply: %s", exc)
        return _mock_ai_reply(
            user_content,
            [node.name for node in matched_nodes],
            "我们可以先用这条路径继续推进理解，再根据你的下一轮问题聚焦到更具体的概念。",
        )
    except LLMRequestError as exc:
        logger.warning("ZoomMind real LLM request failed, falling back to mock reply: %s", exc)
        return _mock_ai_reply(
            user_content,
            [node.name for node in matched_nodes],
            "我们可以先用这条路径继续推进理解，再根据你的下一轮问题聚焦到更具体的概念。",
        )


def _promote_node(node: Node, match_type: str, depth_delta: float, now: datetime) -> bool:
    was_unlit = node.state == "unlit"
    node.depth_score = min(1.0, round(node.depth_score + depth_delta, 3))
    if match_type == "mention":
        if node.state == "unlit":
            node.state = "activated"
    else:
        node.state = "explored"
    node.lit_at = now
    return was_unlit


def _expand_neighbors(session_id: str, newly_activated_ids: list[str], db: DBSession) -> list[Node]:
    if not newly_activated_ids:
        return []
    edges = db.query(Edge).filter(Edge.session_id == session_id).all()
    neighbors: dict[str, Node] = {}
    all_nodes = {node.node_id: node for node in db.query(Node).filter(Node.session_id == session_id).all()}
    for edge in edges:
        if edge.source_node_id in newly_activated_ids:
            node = all_nodes.get(edge.target_node_id)
            if node and not node.is_visible:
                node.is_visible = True
                neighbors[node.node_id] = node
        if edge.target_node_id in newly_activated_ids:
            node = all_nodes.get(edge.source_node_id)
            if node and not node.is_visible:
                node.is_visible = True
                neighbors[node.node_id] = node
    return list(neighbors.values())


def _nodes_from_matches(all_nodes: list[Node], matches: list[dict[str, float | str]]) -> list[Node]:
    node_map = {node.node_id: node for node in all_nodes}
    return [
        node_map[str(item["node_id"])]
        for item in matches
        if str(item["node_id"]) in node_map
    ]


def _add_state_change_event(
    *,
    session_id: str,
    turn_id: str | None,
    node: Node,
    old_state: str,
    old_depth: float,
    old_visible: bool,
    source: str,
    db: DBSession,
    extra: dict | None = None,
) -> None:
    if old_state == node.state and old_depth == node.depth_score and old_visible == node.is_visible:
        return

    metadata = {
        "source": source,
        "old_state": old_state,
        "new_state": node.state,
        "old_depth_score": old_depth,
        "new_depth_score": node.depth_score,
        "depth_delta": round(node.depth_score - old_depth, 3),
        "old_is_visible": old_visible,
        "new_is_visible": node.is_visible,
    }
    if extra:
        metadata.update(extra)

    db.add(
        ExperimentEvent(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            event_type="NODE_STATE_CHANGE",
            node_id=node.node_id,
            turn_id=turn_id,
            metadata_json=json.dumps(metadata, ensure_ascii=False),
            created_at=datetime.utcnow(),
        )
    )


@router.post("/{session_id}/turns", response_model=TurnResponse, status_code=201)
def create_turn(session_id: str, body: TurnCreate, db: DBSession = Depends(get_db)) -> TurnResponse:
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    recent_turns = (
        db.query(Turn)
        .filter(Turn.session_id == session_id)
        .order_by(Turn.timestamp.desc())
        .limit(8)
        .all()
    )
    recent_turns.reverse()

    user_turn_id = str(uuid.uuid4())
    user_turn = Turn(
        turn_id=user_turn_id,
        session_id=session_id,
        speaker="user",
        content=body.content,
        timestamp=datetime.utcnow(),
    )
    db.add(user_turn)
    db.flush()

    all_nodes = db.query(Node).filter(Node.session_id == session_id).all()
    node_map = {node.node_id: node for node in all_nodes}
    user_matches = match_nodes(body.content, all_nodes)
    matched_nodes = _nodes_from_matches(all_nodes, user_matches)
    ai_reply = _generate_ai_reply(
        session=session,
        user_content=body.content,
        all_nodes=all_nodes,
        matched_nodes=matched_nodes,
        recent_turns=recent_turns,
    )

    ai_turn = Turn(
        turn_id=str(uuid.uuid4()),
        session_id=session_id,
        speaker="assistant",
        content=ai_reply,
        timestamp=datetime.utcnow(),
    )
    db.add(ai_turn)
    db.flush()

    assistant_matches = match_nodes(ai_reply, all_nodes)

    # Only USER matches update depth_score and node state (user understanding)
    # AI matches are stored for tracking but don't affect depth
    updated_nodes: list[Node] = []
    updated_node_ids: set[str] = set()
    newly_activated_ids: list[str] = []
    newly_activated_id_set: set[str] = set()
    now = datetime.utcnow()
    match_items: list[MatchItem] = []

    # Process USER matches - these update understanding depth
    for item in user_matches:
        node = node_map.get(str(item["node_id"]))
        if not node:
            continue
        old_state = node.state
        old_depth = node.depth_score
        old_visible = node.is_visible
        # Make invisible nodes visible when user discusses them
        if not node.is_visible:
            node.is_visible = True
        was_unlit = _promote_node(node, str(item["match_type"]), float(item["depth_delta"]), now)
        _add_state_change_event(
            session_id=session_id,
            turn_id=user_turn_id,
            node=node,
            old_state=old_state,
            old_depth=old_depth,
            old_visible=old_visible,
            source="user_match",
            db=db,
            extra={
                "match_type": str(item["match_type"]),
                "confidence": float(item["confidence"]),
            },
        )
        if was_unlit and node.node_id not in newly_activated_id_set:
            newly_activated_ids.append(node.node_id)
            newly_activated_id_set.add(node.node_id)
        if node.node_id not in updated_node_ids:
            updated_nodes.append(node)
            updated_node_ids.add(node.node_id)
        db.add(
            TurnNodeMatch(
                id=str(uuid.uuid4()),
                turn_id=user_turn_id,
                node_id=node.node_id,
                match_type=str(item["match_type"]),
                confidence=float(item["confidence"]),
                depth_delta=float(item["depth_delta"]),
            )
        )
        match_items.append(MatchItem.model_validate(item))

    # Process AI matches - only stored for tracking, no depth update
    for item in assistant_matches:
        node = node_map.get(str(item["node_id"]))
        if not node:
            continue
        db.add(
            TurnNodeMatch(
                id=str(uuid.uuid4()),
                turn_id=ai_turn.turn_id,
                node_id=node.node_id,
                match_type=str(item["match_type"]),
                confidence=float(item["confidence"]),
                depth_delta=0.0,  # No depth update from AI response
            )
        )
        # Still report AI matches in match_items but mark as AI-sourced
        item_copy = dict(item)
        item_copy["depth_delta"] = 0.0  # Zero depth for AI matches
        match_items.append(MatchItem.model_validate(item_copy))

    visible_nodes = _expand_neighbors(session_id, newly_activated_ids, db)
    db.commit()

    all_nodes = db.query(Node).filter(Node.session_id == session_id).all()
    all_edges = db.query(Edge).filter(Edge.session_id == session_id).all()
    blindspots = compute_blindspots(all_nodes, all_edges)
    focus_nodes = sorted(updated_nodes, key=lambda node: node.depth_score, reverse=True)

    return TurnResponse(
        turn_id=user_turn_id,
        ai_reply=ai_reply,
        matches=match_items,
        updated_nodes=[NodeState.model_validate(node) for node in updated_nodes],
        visible_nodes=[NodeState.model_validate(node) for node in visible_nodes],
        blindspots=[BlindspotItem.model_validate(item) for item in blindspots],
        suggested_questions=generate_suggested_questions(
            target_nodes=focus_nodes,
            blindspots=blindspots,
            all_nodes=all_nodes,
            recent_turns=recent_turns,
            topic=session.topic,
        ),
    )


@router.get("/{session_id}/turns", response_model=list[TurnItem])
def list_turns(session_id: str, db: DBSession = Depends(get_db)) -> list[TurnItem]:
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    turns = db.query(Turn).filter(Turn.session_id == session_id).order_by(Turn.timestamp.asc()).all()
    return [TurnItem.model_validate(turn) for turn in turns]
