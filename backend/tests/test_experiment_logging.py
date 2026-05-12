import os
import unittest
import uuid
from datetime import datetime

os.environ["ZOOMMIND_LLM_PROVIDER"] = "mock"

from fastapi.testclient import TestClient

from backend.database import SessionLocal, init_db
from backend.main import app
from backend.models import Edge, Node, Session as SessionModel


class ExperimentLoggingTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.client = TestClient(app)
        self.session_id = str(uuid.uuid4())
        self.node_id = str(uuid.uuid4())
        self.other_node_id = str(uuid.uuid4())
        with SessionLocal() as db:
            session = SessionModel(
                session_id=self.session_id,
                topic="行为经济学入门",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            node = Node(
                node_id=self.node_id,
                session_id=self.session_id,
                name="锚定效应",
                short_definition="初始信息会影响后续判断的认知偏差。",
                layer="1",
                state="activated",
                depth_score=0.18,
                is_visible=True,
                position_x=0,
                position_y=0,
                position_z=0,
            )
            other_node = Node(
                node_id=self.other_node_id,
                session_id=self.session_id,
                name="损失厌恶",
                short_definition="损失带来的痛苦通常大于同等收益的快乐。",
                layer="1",
                state="unlit",
                depth_score=0.0,
                is_visible=True,
                position_x=1,
                position_y=0,
                position_z=0,
            )
            edge = Edge(
                edge_id=str(uuid.uuid4()),
                session_id=self.session_id,
                source_node_id=self.node_id,
                target_node_id=self.other_node_id,
                relation_type="is-related-to",
            )
            db.add_all([session, node, other_node, edge])
            db.commit()

    def test_records_and_lists_graph_interaction_events(self):
        response = self.client.post(
            f"/api/sessions/{self.session_id}/events",
            json={
                "event_type": "GI-H",
                "node_id": self.node_id,
                "duration_ms": 1420,
                "metadata": {"source": "hover-card"},
            },
        )

        self.assertEqual(response.status_code, 201)
        created = response.json()
        self.assertEqual(created["event_type"], "GI-H")
        self.assertEqual(created["node_id"], self.node_id)
        self.assertEqual(created["duration_ms"], 1420)

        list_response = self.client.get(f"/api/sessions/{self.session_id}/events")
        self.assertEqual(list_response.status_code, 200)
        events = list_response.json()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["metadata"]["source"], "hover-card")

    def test_creates_graph_snapshot_with_experiment_metrics(self):
        response = self.client.post(
            f"/api/sessions/{self.session_id}/snapshots",
            json={"label": "phase-1-end"},
        )

        self.assertEqual(response.status_code, 201)
        snapshot = response.json()
        self.assertEqual(snapshot["label"], "phase-1-end")
        self.assertEqual(snapshot["active_count"], 2)
        self.assertEqual(snapshot["activated_count"], 1)
        self.assertEqual(snapshot["explored_count"], 0)
        self.assertEqual(snapshot["total_count"], 2)
        self.assertEqual(snapshot["explored_active_percent"], 0.0)
        self.assertIn("blindspots", snapshot)

    def test_explicit_expand_records_state_change_event(self):
        expand_response = self.client.patch(
            f"/api/sessions/{self.session_id}/nodes/{self.other_node_id}/expand",
        )

        self.assertEqual(expand_response.status_code, 200)
        list_response = self.client.get(f"/api/sessions/{self.session_id}/events")
        self.assertEqual(list_response.status_code, 200)
        events = list_response.json()
        state_events = [event for event in events if event["event_type"] == "NODE_STATE_CHANGE"]
        self.assertEqual(len(state_events), 1)
        self.assertEqual(state_events[0]["node_id"], self.other_node_id)
        self.assertEqual(state_events[0]["metadata"]["source"], "explicit_expand")
        self.assertEqual(state_events[0]["metadata"]["old_state"], "unlit")
        self.assertEqual(state_events[0]["metadata"]["new_state"], "activated")


if __name__ == "__main__":
    unittest.main()
