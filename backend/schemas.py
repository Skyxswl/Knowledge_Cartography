from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel


NodeStatus = Literal["unlit", "activated", "explored"]
MatchType = Literal["mention", "explain", "deepen"]
BlindspotType = Literal["adjacent", "missing_link", "shallow"]
QuestionCategory = Literal["definition", "relation", "deepen", "explore", "application"]


class NodeState(BaseModel):
    node_id: str
    name: str
    short_definition: Optional[str] = None
    layer: str
    parent_id: Optional[str] = None
    state: NodeStatus
    depth_score: float
    is_visible: bool
    lit_at: Optional[datetime] = None
    position_x: float
    position_y: float
    position_z: float

    model_config = {"from_attributes": True}


class EdgeState(BaseModel):
    edge_id: str
    source_node_id: str
    target_node_id: str
    relation_type: str

    model_config = {"from_attributes": True}


class GraphData(BaseModel):
    nodes: list[NodeState]
    edges: list[EdgeState]


class BlindspotItem(BaseModel):
    node_id: str
    blindspot_type: BlindspotType
    priority: float
    reason: str


class SuggestedQuestion(BaseModel):
    node_id: str
    category: QuestionCategory
    prompt: str


class SessionCreate(BaseModel):
    topic: str


class SessionResponse(BaseModel):
    session_id: str
    topic: str
    graph: GraphData
    blindspots: list[BlindspotItem]
    activated_count: int
    explored_count: int
    total_count: int
    coverage_percent: float
    created_at: datetime

    model_config = {"from_attributes": True}


class TurnCreate(BaseModel):
    content: str
    speaker: str


class TurnItem(BaseModel):
    turn_id: str
    session_id: str
    speaker: str
    content: str
    timestamp: datetime

    model_config = {"from_attributes": True}


class MatchItem(BaseModel):
    node_id: str
    match_type: MatchType
    confidence: float
    depth_delta: float


class TurnResponse(BaseModel):
    turn_id: str
    ai_reply: str
    matches: list[MatchItem]
    updated_nodes: list[NodeState]
    visible_nodes: list[NodeState]
    blindspots: list[BlindspotItem]
    suggested_questions: list[SuggestedQuestion]


class NodeSummaryResponse(BaseModel):
    node_id: str
    name: str
    short_definition: str
    summary: str
    source_turn_ids: list[str]


class TraceTurn(BaseModel):
    turn_id: str
    speaker: str
    content: str
    timestamp: datetime

    model_config = {"from_attributes": True}


class NodeTraceResponse(BaseModel):
    node_id: str
    turns: list[TraceTurn]


class ExpandResponse(BaseModel):
    node_id: str
    activated: bool
    revealed_nodes: list[NodeState]


class QuestionsResponse(BaseModel):
    node_id: str
    questions: list[SuggestedQuestion]


class ExperimentEventCreate(BaseModel):
    event_type: str
    node_id: Optional[str] = None
    turn_id: Optional[str] = None
    question_category: Optional[QuestionCategory] = None
    duration_ms: Optional[float] = None
    metadata: dict[str, Any] = {}


class ExperimentEventItem(BaseModel):
    event_id: str
    session_id: str
    event_type: str
    node_id: Optional[str] = None
    turn_id: Optional[str] = None
    question_category: Optional[str] = None
    duration_ms: Optional[float] = None
    metadata: dict[str, Any]
    created_at: datetime


class GraphSnapshotCreate(BaseModel):
    label: Optional[str] = None


class GraphSnapshotItem(BaseModel):
    snapshot_id: str
    session_id: str
    label: Optional[str] = None
    active_count: int
    activated_count: int
    explored_count: int
    total_count: int
    explored_active_percent: float
    coverage_percent: float
    blindspots: list[BlindspotItem]
    graph: GraphData
    created_at: datetime
