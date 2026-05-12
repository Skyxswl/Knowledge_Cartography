import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from backend.blindspot_detector import compute_blindspots
from backend.database import get_db
from backend.models import Edge, ExperimentEvent, GraphSnapshot, Node, Session as SessionModel
from backend.schemas import (
    BlindspotItem,
    EdgeState,
    ExperimentEventCreate,
    ExperimentEventItem,
    GraphData,
    GraphSnapshotCreate,
    GraphSnapshotItem,
    NodeState,
)

router = APIRouter(prefix="/api/sessions", tags=["experiment"])


def _ensure_session(session_id: str, db: DBSession) -> SessionModel:
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _parse_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_blindspots(raw: str | None) -> list[BlindspotItem]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [BlindspotItem.model_validate(item) for item in parsed]


def _parse_graph(raw: str | None) -> GraphData:
    if not raw:
        return GraphData(nodes=[], edges=[])
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return GraphData(nodes=[], edges=[])
    return GraphData.model_validate(parsed)


def _event_to_item(event: ExperimentEvent) -> ExperimentEventItem:
    return ExperimentEventItem(
        event_id=event.event_id,
        session_id=event.session_id,
        event_type=event.event_type,
        node_id=event.node_id,
        turn_id=event.turn_id,
        question_category=event.question_category,
        duration_ms=event.duration_ms,
        metadata=_parse_json_object(event.metadata_json),
        created_at=event.created_at,
    )


def _snapshot_to_item(snapshot: GraphSnapshot) -> GraphSnapshotItem:
    return GraphSnapshotItem(
        snapshot_id=snapshot.snapshot_id,
        session_id=snapshot.session_id,
        label=snapshot.label,
        active_count=int(snapshot.active_count),
        activated_count=int(snapshot.activated_count),
        explored_count=int(snapshot.explored_count),
        total_count=int(snapshot.total_count),
        explored_active_percent=snapshot.explored_active_percent,
        coverage_percent=snapshot.coverage_percent,
        blindspots=_parse_blindspots(snapshot.blindspots_json),
        graph=_parse_graph(snapshot.graph_json),
        created_at=snapshot.created_at,
    )


def _create_snapshot(session_id: str, label: str | None, db: DBSession) -> GraphSnapshot:
    nodes = db.query(Node).filter(Node.session_id == session_id).all()
    edges = db.query(Edge).filter(Edge.session_id == session_id).all()
    blindspots = compute_blindspots(nodes, edges)

    active_count = sum(1 for node in nodes if node.is_visible)
    activated_count = sum(1 for node in nodes if node.state in {"activated", "explored"})
    explored_count = sum(1 for node in nodes if node.state == "explored")
    total_count = len(nodes)
    explored_active_percent = round((explored_count / active_count) * 100, 1) if active_count else 0.0
    coverage_percent = round((explored_count / total_count) * 100, 1) if total_count else 0.0
    graph = GraphData(
        nodes=[NodeState.model_validate(node) for node in nodes],
        edges=[EdgeState.model_validate(edge) for edge in edges],
    )

    snapshot = GraphSnapshot(
        snapshot_id=str(uuid.uuid4()),
        session_id=session_id,
        label=label,
        active_count=active_count,
        activated_count=activated_count,
        explored_count=explored_count,
        total_count=total_count,
        explored_active_percent=explored_active_percent,
        coverage_percent=coverage_percent,
        blindspots_json=json.dumps(blindspots, ensure_ascii=False),
        graph_json=graph.model_dump_json(),
        created_at=datetime.utcnow(),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@router.post("/{session_id}/events", response_model=ExperimentEventItem, status_code=status.HTTP_201_CREATED)
def create_experiment_event(
    session_id: str,
    body: ExperimentEventCreate,
    db: DBSession = Depends(get_db),
) -> ExperimentEventItem:
    _ensure_session(session_id, db)
    if body.node_id:
        node = db.query(Node).filter(Node.session_id == session_id, Node.node_id == body.node_id).first()
        if not node:
            raise HTTPException(status_code=404, detail="Node not found")

    event = ExperimentEvent(
        event_id=str(uuid.uuid4()),
        session_id=session_id,
        event_type=body.event_type,
        node_id=body.node_id,
        turn_id=body.turn_id,
        question_category=body.question_category,
        duration_ms=body.duration_ms,
        metadata_json=json.dumps(body.metadata, ensure_ascii=False),
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return _event_to_item(event)


@router.get("/{session_id}/events", response_model=list[ExperimentEventItem])
def list_experiment_events(session_id: str, db: DBSession = Depends(get_db)) -> list[ExperimentEventItem]:
    _ensure_session(session_id, db)
    events = (
        db.query(ExperimentEvent)
        .filter(ExperimentEvent.session_id == session_id)
        .order_by(ExperimentEvent.created_at.asc())
        .all()
    )
    return [_event_to_item(event) for event in events]


@router.post("/{session_id}/snapshots", response_model=GraphSnapshotItem, status_code=status.HTTP_201_CREATED)
def create_graph_snapshot(
    session_id: str,
    body: GraphSnapshotCreate,
    db: DBSession = Depends(get_db),
) -> GraphSnapshotItem:
    _ensure_session(session_id, db)
    return _snapshot_to_item(_create_snapshot(session_id, body.label, db))


@router.get("/{session_id}/snapshots", response_model=list[GraphSnapshotItem])
def list_graph_snapshots(session_id: str, db: DBSession = Depends(get_db)) -> list[GraphSnapshotItem]:
    _ensure_session(session_id, db)
    snapshots = (
        db.query(GraphSnapshot)
        .filter(GraphSnapshot.session_id == session_id)
        .order_by(GraphSnapshot.created_at.asc())
        .all()
    )
    return [_snapshot_to_item(snapshot) for snapshot in snapshots]
