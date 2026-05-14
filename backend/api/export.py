import csv
import io
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session as DBSession

from backend.database import get_db
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


def _utf8_json_response(payload: dict[str, Any]) -> Response:
    return Response(
        content=json.dumps(payload, ensure_ascii=False),
        media_type="application/json; charset=utf-8",
    )


@router.get("")
def export_all_data(db: DBSession = Depends(get_db)) -> Response:
    sessions = db.query(SessionModel).order_by(SessionModel.created_at.asc()).all()
    nodes = db.query(Node).order_by(Node.session_id.asc(), Node.layer.asc(), Node.name.asc()).all()
    edges = db.query(Edge).order_by(Edge.session_id.asc(), Edge.edge_id.asc()).all()
    turns = db.query(Turn).order_by(Turn.session_id.asc(), Turn.timestamp.asc()).all()
    matches = db.query(TurnNodeMatch).order_by(TurnNodeMatch.turn_id.asc()).all()
    events = db.query(ExperimentEvent).order_by(ExperimentEvent.session_id.asc(), ExperimentEvent.created_at.asc()).all()
    snapshots = db.query(GraphSnapshot).order_by(GraphSnapshot.session_id.asc(), GraphSnapshot.created_at.asc()).all()

    payload = {
        "exported_at": datetime.utcnow().isoformat(),
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
    return _utf8_json_response(payload)


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
