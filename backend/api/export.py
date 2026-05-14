import csv
import io
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session as DBSession

from backend.database import get_db
from backend.api.experiment import _create_snapshot
from backend.models import Edge, ExperimentEvent, GraphSnapshot, Node, Session as SessionModel, Turn, TurnNodeMatch

router = APIRouter(prefix="/api/export", tags=["export"])


def _format_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _row(model: Any, fields: list[str]) -> dict[str, Any]:
    return {field: _format_value(getattr(model, field)) for field in fields}


def _json_object(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _utf8_json_response(payload: dict[str, Any], filename: str | None = None) -> Response:
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'} if filename else None
    return Response(
        content=json.dumps(payload, ensure_ascii=False),
        media_type="application/json; charset=utf-8",
        headers=headers,
    )


def _build_export_payload(
    *,
    db: DBSession,
    session_id: str | None = None,
    exported_at: datetime | None = None,
) -> dict[str, Any]:
    session_query = db.query(SessionModel)
    node_query = db.query(Node)
    edge_query = db.query(Edge)
    turn_query = db.query(Turn)
    event_query = db.query(ExperimentEvent)
    snapshot_query = db.query(GraphSnapshot)

    if session_id:
        session_query = session_query.filter(SessionModel.session_id == session_id)
        node_query = node_query.filter(Node.session_id == session_id)
        edge_query = edge_query.filter(Edge.session_id == session_id)
        turn_query = turn_query.filter(Turn.session_id == session_id)
        event_query = event_query.filter(ExperimentEvent.session_id == session_id)
        snapshot_query = snapshot_query.filter(GraphSnapshot.session_id == session_id)

    sessions = session_query.order_by(SessionModel.created_at.asc()).all()
    nodes = node_query.order_by(Node.session_id.asc(), Node.layer.asc(), Node.name.asc()).all()
    edges = edge_query.order_by(Edge.session_id.asc(), Edge.edge_id.asc()).all()
    turns = turn_query.order_by(Turn.session_id.asc(), Turn.timestamp.asc()).all()
    turn_ids = [turn.turn_id for turn in turns]
    matches = []
    if turn_ids:
        matches = (
            db.query(TurnNodeMatch)
            .filter(TurnNodeMatch.turn_id.in_(turn_ids))
            .order_by(TurnNodeMatch.turn_id.asc())
            .all()
        )
    events = event_query.order_by(ExperimentEvent.session_id.asc(), ExperimentEvent.created_at.asc()).all()
    snapshots = snapshot_query.order_by(GraphSnapshot.session_id.asc(), GraphSnapshot.created_at.asc()).all()

    payload = {
        "exported_at": (exported_at or datetime.utcnow()).isoformat(),
        "sessions": [
            _row(session, ["session_id", "topic", "created_at", "updated_at"])
            for session in sessions
        ],
        "nodes": [
            _row(
                node,
                [
                    "node_id",
                    "session_id",
                    "name",
                    "short_definition",
                    "layer",
                    "parent_id",
                    "state",
                    "depth_score",
                    "is_visible",
                    "lit_at",
                    "position_x",
                    "position_y",
                    "position_z",
                ],
            )
            for node in nodes
        ],
        "edges": [
            _row(edge, ["edge_id", "session_id", "source_node_id", "target_node_id", "relation_type"])
            for edge in edges
        ],
        "turns": [
            _row(turn, ["turn_id", "session_id", "speaker", "content", "timestamp"])
            for turn in turns
        ],
        "turn_node_matches": [
            _row(match, ["id", "turn_id", "node_id", "match_type", "confidence", "depth_delta"])
            for match in matches
        ],
        "experiment_events": [
            {
                **_row(
                    event,
                    [
                        "event_id",
                        "session_id",
                        "event_type",
                        "node_id",
                        "turn_id",
                        "question_category",
                        "duration_ms",
                        "created_at",
                    ],
                ),
                "metadata": _json_object(event.metadata_json),
            }
            for event in events
        ],
        "graph_snapshots": [
            {
                **_row(
                    snapshot,
                    [
                        "snapshot_id",
                        "session_id",
                        "label",
                        "active_count",
                        "activated_count",
                        "explored_count",
                        "total_count",
                        "explored_active_percent",
                        "coverage_percent",
                        "created_at",
                    ],
                ),
                "blindspots": _json_object(snapshot.blindspots_json),
                "graph": _json_object(snapshot.graph_json),
            }
            for snapshot in snapshots
        ],
    }
    if session_id:
        payload["session_id"] = session_id
    return payload


@router.get("")
def export_all_data(db: DBSession = Depends(get_db)) -> Response:
    payload = _build_export_payload(db=db)
    return _utf8_json_response(payload)


@router.get("/session/{session_id}/final")
def export_final_session_data(
    session_id: str,
    label: str = "end",
    db: DBSession = Depends(get_db),
) -> Response:
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    exported_at = datetime.utcnow()
    _create_snapshot(session_id, label, db)
    payload = _build_export_payload(db=db, session_id=session_id, exported_at=exported_at)
    safe_label = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in label) or "end"
    filename = f"knowledge-cartography-{session_id}-{safe_label}.json"
    return _utf8_json_response(payload, filename=filename)


@router.get("/events.csv")
def export_events_csv(db: DBSession = Depends(get_db)) -> StreamingResponse:
    events = db.query(ExperimentEvent).order_by(ExperimentEvent.session_id.asc(), ExperimentEvent.created_at.asc()).all()
    output = io.StringIO()
    output.write("\ufeff")
    fieldnames = [
        "event_id",
        "session_id",
        "event_type",
        "node_id",
        "turn_id",
        "question_category",
        "duration_ms",
        "created_at",
        "metadata_json",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for event in events:
        writer.writerow(
            {
                **_row(
                    event,
                    [
                        "event_id",
                        "session_id",
                        "event_type",
                        "node_id",
                        "turn_id",
                        "question_category",
                        "duration_ms",
                        "created_at",
                    ],
                ),
                "metadata_json": event.metadata_json or "",
            }
        )

    output.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="zoommind-events.csv"'}
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8", headers=headers)
