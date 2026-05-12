import json
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from backend.database import get_db
from backend.models import Edge, ExperimentEvent, Node, Session as SessionModel, Turn, TurnNodeMatch
from backend.question_generator import generate_suggested_questions
from backend.schemas import (
    ExpandResponse,
    NodeState,
    NodeSummaryResponse,
    NodeTraceResponse,
    QuestionsResponse,
    SuggestedQuestion,
    TraceTurn,
)

router = APIRouter(prefix="/api/sessions", tags=["nodes"])

_SUMMARY_MAX_CHARS = 320


def _get_session_node(session_id: str, node_id: str, db: DBSession) -> Node:
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    node = db.query(Node).filter(Node.node_id == node_id, Node.session_id == session_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


def _expand_trace_turns(session_id: str, source_turn_ids: list[str], db: DBSession) -> list[Turn]:
    if not source_turn_ids:
        return []

    source_turn_id_set = set(source_turn_ids)
    session_turns = (
        db.query(Turn)
        .filter(Turn.session_id == session_id)
        .order_by(Turn.timestamp.asc())
        .all()
    )

    trace_turns: list[Turn] = []
    seen_turn_ids: set[str] = set()

    for index, turn in enumerate(session_turns):
        if turn.turn_id not in source_turn_id_set:
            continue
        previous_index = index - 1
        if turn.speaker == "assistant" and previous_index >= 0:
            previous_turn = session_turns[previous_index]
            if previous_turn.speaker == "user" and previous_turn.turn_id not in seen_turn_ids:
                trace_turns.append(previous_turn)
                seen_turn_ids.add(previous_turn.turn_id)
        if turn.turn_id not in seen_turn_ids:
            trace_turns.append(turn)
            seen_turn_ids.add(turn.turn_id)

        next_index = index + 1
        if next_index < len(session_turns):
            next_turn = session_turns[next_index]
            if next_turn.speaker == "assistant" and next_turn.turn_id not in seen_turn_ids:
                trace_turns.append(next_turn)
                seen_turn_ids.add(next_turn.turn_id)

    return trace_turns


@router.get("/{session_id}/nodes/{node_id}/summary", response_model=NodeSummaryResponse)
def get_node_summary(session_id: str, node_id: str, db: DBSession = Depends(get_db)) -> NodeSummaryResponse:
    node = _get_session_node(session_id, node_id, db)
    matches = db.query(TurnNodeMatch).filter(TurnNodeMatch.node_id == node_id).order_by(TurnNodeMatch.confidence.desc()).all()

    source_turn_ids: list[str] = []
    seen_turn_ids: set[str] = set()
    for match in matches:
        if match.turn_id not in seen_turn_ids:
            seen_turn_ids.add(match.turn_id)
            source_turn_ids.append(match.turn_id)

    turns = _expand_trace_turns(session_id, source_turn_ids, db)
    raw_summary = " | ".join(f"{turn.speaker}: {turn.content}" for turn in turns)
    if len(raw_summary) > _SUMMARY_MAX_CHARS:
        raw_summary = raw_summary[:_SUMMARY_MAX_CHARS] + "…"

    return NodeSummaryResponse(
        node_id=node.node_id,
        name=node.name,
        short_definition=node.short_definition or "",
        summary=raw_summary,
        source_turn_ids=source_turn_ids,
    )


@router.get("/{session_id}/nodes/{node_id}/trace", response_model=NodeTraceResponse)
def get_node_trace(session_id: str, node_id: str, db: DBSession = Depends(get_db)) -> NodeTraceResponse:
    _get_session_node(session_id, node_id, db)
    matches = db.query(TurnNodeMatch).filter(TurnNodeMatch.node_id == node_id).order_by(TurnNodeMatch.confidence.desc()).all()
    turn_ids = list(dict.fromkeys(match.turn_id for match in matches))
    turns = _expand_trace_turns(session_id, turn_ids, db)
    return NodeTraceResponse(
        node_id=node_id,
        turns=[TraceTurn.model_validate(turn) for turn in turns],
    )


@router.patch("/{session_id}/nodes/{node_id}/expand", response_model=ExpandResponse)
def expand_node(session_id: str, node_id: str, db: DBSession = Depends(get_db)) -> ExpandResponse:
    """
    Expand a node: reveal its children from latent graph and activate it.

    - Activates the target node (unlit → activated)
    - Sets initial depth_score for explicit expansion
    - Makes all child nodes visible (is_visible = True)
    - Returns the activated node and newly visible children
    """
    node = _get_session_node(session_id, node_id, db)
    old_state = node.state
    old_depth = node.depth_score
    old_visible = node.is_visible

    # Activate the node with initial depth
    node.state = "activated"
    # Give initial depth for explicit expansion (user intentionally exploring)
    if node.depth_score < 0.15:
        node.depth_score = 0.15
    node.lit_at = datetime.utcnow()
    if old_state != node.state or old_depth != node.depth_score or old_visible != node.is_visible:
        db.add(
            ExperimentEvent(
                event_id=str(uuid.uuid4()),
                session_id=session_id,
                event_type="NODE_STATE_CHANGE",
                node_id=node.node_id,
                metadata_json=json.dumps(
                    {
                        "source": "explicit_expand",
                        "old_state": old_state,
                        "new_state": node.state,
                        "old_depth_score": old_depth,
                        "new_depth_score": node.depth_score,
                        "depth_delta": round(node.depth_score - old_depth, 3),
                        "old_is_visible": old_visible,
                        "new_is_visible": node.is_visible,
                    },
                    ensure_ascii=False,
                ),
                created_at=datetime.utcnow(),
            )
        )

    # Find and reveal children
    child_edges = (
        db.query(Edge)
        .filter(Edge.session_id == session_id, Edge.source_node_id == node_id)
        .all()
    )
    child_ids = [edge.target_node_id for edge in child_edges]

    revealed_nodes: list[Node] = []
    for child_id in child_ids:
        child = db.query(Node).filter(Node.node_id == child_id).first()
        if child and not child.is_visible:
            child_old_visible = child.is_visible
            child.is_visible = True
            db.add(
                ExperimentEvent(
                    event_id=str(uuid.uuid4()),
                    session_id=session_id,
                    event_type="NODE_STATE_CHANGE",
                    node_id=child.node_id,
                    metadata_json=json.dumps(
                        {
                            "source": "explicit_expand_reveal",
                            "old_state": child.state,
                            "new_state": child.state,
                            "old_depth_score": child.depth_score,
                            "new_depth_score": child.depth_score,
                            "depth_delta": 0.0,
                            "old_is_visible": child_old_visible,
                            "new_is_visible": child.is_visible,
                            "expanded_from_node_id": node_id,
                        },
                        ensure_ascii=False,
                    ),
                    created_at=datetime.utcnow(),
                )
            )
            revealed_nodes.append(child)

    db.commit()

    return ExpandResponse(
        node_id=node.node_id,
        activated=True,
        revealed_nodes=[NodeState.model_validate(n) for n in revealed_nodes],
    )


@router.post("/{session_id}/nodes/{node_id}/questions", response_model=QuestionsResponse)
def get_node_questions(session_id: str, node_id: str, db: DBSession = Depends(get_db)) -> QuestionsResponse:
    """
    Get suggested questions for a specific node.

    Uses LLM to generate contextually relevant questions based on:
    - The node's definition and context in the graph
    - Current graph state (other active/explored nodes)
    - Recent conversation history
    """
    node = _get_session_node(session_id, node_id, db)

    # Get all nodes and recent turns for context
    all_nodes = db.query(Node).filter(Node.session_id == session_id).all()
    recent_turns = (
        db.query(Turn)
        .filter(Turn.session_id == session_id)
        .order_by(Turn.timestamp.desc())
        .limit(6)
        .all()
    )
    recent_turns.reverse()

    # Get session topic
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    topic = session.topic if session else ""

    # Get blindspots for context
    from backend.blindspot_detector import compute_blindspots
    all_edges = db.query(Edge).filter(Edge.session_id == session_id).all()
    blindspots = compute_blindspots(all_nodes, all_edges)

    # Generate questions focused on this node
    questions = generate_suggested_questions(
        target_nodes=[node],
        blindspots=blindspots,
        all_nodes=all_nodes,
        recent_turns=recent_turns,
        topic=topic,
    )

    return QuestionsResponse(
        node_id=node.node_id,
        questions=questions,
    )
