"""
Blindspot detection for ZoomMind.

Blindspot types (per abstract):
- adjacent: Neighbor of an activated/explored node that hasn't been lit (neighboring gaps)
- missing_link: Bridge node between two connected nodes in the active frontier (broken links)
- shallow: Activated/explored node with very low depth_score (< 0.25)
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.models import Edge, Node


def compute_blindspots(nodes: list[Node], edges: list[Edge]) -> list[dict[str, float | str]]:
    """
    Compute all blindspots in the knowledge graph.

    Returns a list of blindspot dicts sorted by priority (highest first).
    Each blindspot has: node_id, blindspot_type, priority, reason
    """
    node_map = {node.node_id: node for node in nodes}
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacency[edge.source_node_id].add(edge.target_node_id)
        adjacency[edge.target_node_id].add(edge.source_node_id)

    # Track best blindspot per node (key collision fix)
    best_blindspots: dict[str, dict[str, float | str]] = {}

    def _update_blindspot(node_id: str, btype: str, priority: float, reason: str) -> None:
        """Update blindspot only if new priority is higher (per-node dedup)."""
        key = node_id
        if key not in best_blindspots or priority > best_blindspots[key]["priority"]:
            best_blindspots[key] = {
                "node_id": node_id,
                "blindspot_type": btype,
                "priority": round(priority, 4),
                "reason": reason,
            }

    # --- Type 1: Missing link (bridge nodes) FIRST ---
    # Run before adjacent so missing_link takes precedence (higher semantic value)
    # Two activated/explored nodes that have a common unlit neighbor between them
    activated_nodes = [n for n in nodes if n.state in {"activated", "explored"}]
    for node in activated_nodes:
        for neighbor_id in adjacency.get(node.node_id, set()):
            mid = node_map.get(neighbor_id)
            if not mid or mid.state != "unlit":
                continue
            if mid.layer == "0":
                continue
            for second_id in adjacency.get(neighbor_id, set()):
                if second_id == node.node_id:
                    continue
                second = node_map.get(second_id)
                if second and second.state in {"activated", "explored"}:
                    bridge_priority = max(node.depth_score, second.depth_score) * 0.80
                    _update_blindspot(
                        mid.node_id,
                        "missing_link",
                        max(0.35, bridge_priority),
                        f"「{node.name}」与「{second.name}」已被触达，但中间概念「{mid.name}」尚未激活",
                    )

    # --- Type 2: Adjacent blindspots ---
    # From ANY node that is activated or explored, its unlit neighbors are blindspots
    # Skip if already registered as missing_link (already found as a bridge)
    for node in nodes:
        if node.state not in {"activated", "explored"}:
            continue
        for neighbor_id in adjacency.get(node.node_id, set()):
            neighbor = node_map.get(neighbor_id)
            if not neighbor:
                continue
            if neighbor.layer == "0":
                continue
            if neighbor.state == "unlit":
                # Skip if this node is already tracked as a more meaningful missing_link
                if neighbor_id in best_blindspots and best_blindspots[neighbor_id]["blindspot_type"] == "missing_link":
                    continue
                depth_factor = node.depth_score
                priority = max(0.25, depth_factor * 0.80)
                _update_blindspot(
                    neighbor_id,
                    "adjacent",
                    priority,
                    f"「{node.name}」已深入，但相邻的「{neighbor.name}」仍未触达",
                )

    # --- Type 3: Shallow nodes ---
    for node in nodes:
        if node.layer == "0":
            continue
        if node.state in {"activated", "explored"} and node.depth_score < 0.25:
            priority = 0.40 + (0.25 - node.depth_score) * 0.6
            _update_blindspot(
                node.node_id,
                "shallow",
                min(0.65, round(priority, 4)),
                f"「{node.name}」已进入讨论，但理解深度仍较浅",
            )

    result = sorted(best_blindspots.values(), key=lambda item: float(item["priority"]), reverse=True)
    return result