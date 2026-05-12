import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.blindspot_detector import compute_blindspots
from backend.database import get_db
from backend.graph_generator import generate_graph
from backend.graph_generator_v2 import generate_semantic_graph
from backend.llm_client import is_real_llm_enabled
from backend.models import Edge, Node, Session as SessionModel
from backend.schemas import BlindspotItem, EdgeState, GraphData, NodeState, SessionCreate, SessionResponse

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _build_session_response(session: SessionModel, db: Session) -> SessionResponse:
    nodes = db.query(Node).filter(Node.session_id == session.session_id).all()
    edges = db.query(Edge).filter(Edge.session_id == session.session_id).all()
    blindspots = compute_blindspots(nodes, edges)
    activated_count = sum(1 for node in nodes if node.state in {"activated", "explored"})
    explored_count = sum(1 for node in nodes if node.state == "explored")
    total_count = len(nodes)
    coverage_percent = round((explored_count / total_count) * 100, 1) if total_count else 0.0
    return SessionResponse(
        session_id=session.session_id,
        topic=session.topic,
        graph=GraphData(
            nodes=[NodeState.model_validate(node) for node in nodes],
            edges=[EdgeState.model_validate(edge) for edge in edges],
        ),
        blindspots=[BlindspotItem.model_validate(item) for item in blindspots],
        activated_count=activated_count,
        explored_count=explored_count,
        total_count=total_count,
        coverage_percent=coverage_percent,
        created_at=session.created_at,
    )


@router.post("", response_model=SessionResponse, status_code=201)
def create_session(body: SessionCreate, db: Session = Depends(get_db)):
    session = SessionModel(
        session_id=str(uuid.uuid4()),
        topic=body.topic,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    if is_real_llm_enabled():
        generate_semantic_graph(body.topic, session.session_id, db)
    else:
        generate_graph(body.topic, session.session_id, db)
    return _build_session_response(session, db)


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, db: Session = Depends(get_db)):
    session = db.query(SessionModel).filter(SessionModel.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return _build_session_response(session, db)
