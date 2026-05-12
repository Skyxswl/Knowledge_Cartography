import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

if DATABASE_URL.startswith("sqlite:///"):
    sqlite_path = DATABASE_URL.removeprefix("sqlite:///")
    if sqlite_path and sqlite_path != ":memory:":
        Path(sqlite_path).expanduser().parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_column(connection, table: str, name: str, ddl: str) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns(table)}
    if name not in columns:
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _drop_legacy_is_lit_column(connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("nodes")}
    if "is_lit" not in columns:
        return

    target_columns = [
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
    ]
    select_expressions = {
        "node_id": "node_id",
        "session_id": "session_id",
        "name": "name",
        "short_definition": "short_definition" if "short_definition" in columns else "NULL",
        "layer": "layer",
        "parent_id": "parent_id",
        "state": (
            "COALESCE(state, CASE WHEN is_lit THEN 'activated' ELSE 'unlit' END)"
            if "state" in columns
            else "CASE WHEN is_lit THEN 'activated' ELSE 'unlit' END"
        ),
        "depth_score": (
            "COALESCE(depth_score, CASE WHEN is_lit THEN 0.18 ELSE 0.0 END)"
            if "depth_score" in columns
            else "CASE WHEN is_lit THEN 0.18 ELSE 0.0 END"
        ),
        "is_visible": (
            "COALESCE(is_visible, CASE WHEN layer IN ('0', '1') THEN 1 ELSE 0 END)"
            if "is_visible" in columns
            else "CASE WHEN layer IN ('0', '1') THEN 1 ELSE 0 END"
        ),
        "lit_at": "lit_at" if "lit_at" in columns else "NULL",
        "position_x": "position_x" if "position_x" in columns else "0.0",
        "position_y": "position_y" if "position_y" in columns else "0.0",
        "position_z": "position_z" if "position_z" in columns else "0.0",
    }

    connection.execute(text("DROP TABLE IF EXISTS nodes_new"))
    connection.execute(
        text(
            """
            CREATE TABLE nodes_new (
                node_id VARCHAR NOT NULL,
                session_id VARCHAR NOT NULL,
                name VARCHAR NOT NULL,
                short_definition TEXT,
                layer VARCHAR NOT NULL,
                parent_id VARCHAR,
                state VARCHAR DEFAULT 'unlit' NOT NULL,
                depth_score FLOAT DEFAULT 0.0 NOT NULL,
                is_visible BOOLEAN DEFAULT 0 NOT NULL,
                lit_at DATETIME,
                position_x FLOAT,
                position_y FLOAT,
                position_z FLOAT,
                PRIMARY KEY (node_id),
                FOREIGN KEY(session_id) REFERENCES sessions (session_id),
                FOREIGN KEY(parent_id) REFERENCES nodes (node_id)
            )
            """
        )
    )
    connection.execute(
        text(
            f"""
            INSERT INTO nodes_new ({", ".join(target_columns)})
            SELECT {", ".join(select_expressions[column] for column in target_columns)}
            FROM nodes
            """
        )
    )
    connection.execute(text("DROP TABLE nodes"))
    connection.execute(text("ALTER TABLE nodes_new RENAME TO nodes"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_nodes_node_id ON nodes (node_id)"))


def _migrate_schema() -> None:
    with engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        if "nodes" in tables:
            _drop_legacy_is_lit_column(connection)
            _ensure_column(connection, "nodes", "short_definition", "TEXT")
            _ensure_column(connection, "nodes", "state", "VARCHAR DEFAULT 'unlit' NOT NULL")
            _ensure_column(connection, "nodes", "depth_score", "FLOAT DEFAULT 0.0 NOT NULL")
            _ensure_column(connection, "nodes", "is_visible", "BOOLEAN DEFAULT 0 NOT NULL")
        if "edges" in tables:
            _ensure_column(connection, "edges", "relation_type", "VARCHAR DEFAULT 'is-related-to' NOT NULL")
        if "turn_node_matches" in tables:
            _ensure_column(connection, "turn_node_matches", "match_type", "VARCHAR DEFAULT 'mention' NOT NULL")
            _ensure_column(connection, "turn_node_matches", "depth_delta", "FLOAT DEFAULT 0.0 NOT NULL")


def init_db():
    import backend.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_schema()
