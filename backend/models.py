from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class Session(Base):
    __tablename__ = "sessions"

    session_id = Column(String, primary_key=True, index=True)
    topic = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    nodes = relationship("Node", back_populates="session", cascade="all, delete-orphan")
    edges = relationship("Edge", back_populates="session", cascade="all, delete-orphan")
    turns = relationship("Turn", back_populates="session", cascade="all, delete-orphan")


class Node(Base):
    __tablename__ = "nodes"

    node_id = Column(String, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False)
    name = Column(String, nullable=False)
    short_definition = Column(Text, nullable=True)
    layer = Column(String, nullable=False)
    parent_id = Column(String, ForeignKey("nodes.node_id"), nullable=True)
    state = Column(String, nullable=False, default="unlit")
    depth_score = Column(Float, nullable=False, default=0.0)
    is_visible = Column(Boolean, nullable=False, default=False)
    lit_at = Column(DateTime, nullable=True)
    position_x = Column(Float, default=0.0)
    position_y = Column(Float, default=0.0)
    position_z = Column(Float, default=0.0)
    embedding = Column(Text, nullable=True)

    session = relationship("Session", back_populates="nodes")
    matches = relationship("TurnNodeMatch", back_populates="node", cascade="all, delete-orphan")


class Edge(Base):
    __tablename__ = "edges"

    edge_id = Column(String, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False)
    source_node_id = Column(String, ForeignKey("nodes.node_id"), nullable=False)
    target_node_id = Column(String, ForeignKey("nodes.node_id"), nullable=False)
    relation_type = Column(String, nullable=False, default="is-related-to")

    session = relationship("Session", back_populates="edges")


class Turn(Base):
    __tablename__ = "turns"

    turn_id = Column(String, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False)
    speaker = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="turns")
    matches = relationship("TurnNodeMatch", back_populates="turn", cascade="all, delete-orphan")


class TurnNodeMatch(Base):
    __tablename__ = "turn_node_matches"

    id = Column(String, primary_key=True, index=True)
    turn_id = Column(String, ForeignKey("turns.turn_id"), nullable=False)
    node_id = Column(String, ForeignKey("nodes.node_id"), nullable=False)
    match_type = Column(String, nullable=False, default="mention")
    confidence = Column(Float, nullable=False, default=1.0)
    depth_delta = Column(Float, nullable=False, default=0.0)

    turn = relationship("Turn", back_populates="matches")
    node = relationship("Node", back_populates="matches")


class ExperimentEvent(Base):
    __tablename__ = "experiment_events"

    event_id = Column(String, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False, index=True)
    event_type = Column(String, nullable=False)
    node_id = Column(String, ForeignKey("nodes.node_id"), nullable=True)
    turn_id = Column(String, ForeignKey("turns.turn_id"), nullable=True)
    question_category = Column(String, nullable=True)
    duration_ms = Column(Float, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class GraphSnapshot(Base):
    __tablename__ = "graph_snapshots"

    snapshot_id = Column(String, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("sessions.session_id"), nullable=False, index=True)
    label = Column(String, nullable=True)
    active_count = Column(Float, nullable=False, default=0.0)
    activated_count = Column(Float, nullable=False, default=0.0)
    explored_count = Column(Float, nullable=False, default=0.0)
    total_count = Column(Float, nullable=False, default=0.0)
    explored_active_percent = Column(Float, nullable=False, default=0.0)
    coverage_percent = Column(Float, nullable=False, default=0.0)
    blindspots_json = Column(Text, nullable=False, default="[]")
    graph_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
