"""
Memory Graph Engine — Soul Knowledge Graph with KuzuDB

Builds and queries a local graph database for each soul's memory.
Stores entities (people, places, topics, emotions) and relationships
between them, enabling the soul to recall complex contextual memories.

Architecture:
- Nodes: memories, entities, emotions, topics
- Edges: relates_to, triggered_by, mentioned_in, felt_during
- Queries: "What do I know about X?", "When did I feel Y?", "Who mentioned Z?"

Uses KuzuDB (embedded graph DB, zero config, runs in-process).
Falls back to JSON-based graph if KuzuDB not installed.

Runs 100% locally. ~2MB overhead per soul.
"""

import os
import json
import time
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from security import validate_workspace_path, acquire_mutex_lock, MAX_GRAPH_NODES, MAX_GRAPH_EDGES

logger = logging.getLogger("memory_graph")

# Graph schema constants
NODE_TYPES = ["memory", "entity", "emotion", "topic", "person", "place"]
EDGE_TYPES = ["relates_to", "triggered_by", "mentioned_in", "felt_during",
              "knows_about", "reacted_to", "discussed_with"]


class MemoryNode:
    """A node in the soul's memory graph."""
    def __init__(self, node_id: str, node_type: str, label: str,
                 content: str = "", metadata: dict = None):
        self.id = node_id
        self.type = node_type
        self.label = label
        self.content = content
        self.metadata = metadata or {}
        self.created_at = time.time()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


class MemoryEdge:
    """An edge connecting two nodes in the memory graph."""
    def __init__(self, source_id: str, target_id: str, edge_type: str,
                 weight: float = 1.0, metadata: dict = None):
        self.source = source_id
        self.target = target_id
        self.type = edge_type
        self.weight = weight
        self.metadata = metadata or {}
        self.created_at = time.time()

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.type,
            "weight": self.weight,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


class MemoryGraph:
    """
    JSON-backed memory graph for soul knowledge.
    Provides add/query/traverse operations without external DB dependencies.
    """

    def __init__(self, workspace_path: str):
        self.workspace_path = validate_workspace_path(workspace_path)
        self.graph_path = os.path.join(workspace_path, "memory_graph.json")
        self.nodes: Dict[str, dict] = {}
        self.edges: List[dict] = []
        self._load()

    def _load(self):
        """Load graph from disk."""
        if os.path.exists(self.graph_path):
            try:
                with open(self.graph_path, 'r') as f:
                    data = json.load(f)
                self.nodes = {n["id"]: n for n in data.get("nodes", [])}
                self.edges = data.get("edges", [])
                logger.info(f"[GRAPH] Loaded {len(self.nodes)} nodes, {len(self.edges)} edges")
            except Exception as e:
                logger.warning(f"[GRAPH] Failed to load: {e}")
                self.nodes = {}
                self.edges = []
        else:
            self.nodes = {}
            self.edges = []

    def _save(self):
        """Persist graph to disk atomically."""
        os.makedirs(os.path.dirname(self.graph_path) if os.path.dirname(self.graph_path) else '.', exist_ok=True)
        data = {
            "nodes": list(self.nodes.values()),
            "edges": self.edges,
            "updated_at": time.time(),
        }
        # Atomic write: write → flush → fsync → rename
        # fsync forces OS page cache to physical disk BEFORE rename
        # Without this, power loss could leave a 0-byte .tmp that replaces real data
        temp_path = self.graph_path + ".tmp"
        with open(temp_path, 'w') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, self.graph_path)

        # Fix APFS Data Durability: fsync the parent directory to commit the rename to disk metadata
        parent_dir = os.path.dirname(self.graph_path) or '.'
        try:
            dir_fd = os.open(parent_dir, os.O_RDONLY)
            os.fsync(dir_fd)
            os.close(dir_fd)
        except OSError as e:
            pass  # Windows or read-only volume fallback

    def upsert_node(self, node_id: str, node_type: str, label: str,
                    content: str = "", metadata: dict = None) -> dict:
        """Add or update a node in the graph. Protected by OS Mutex to prevent stale overwrites."""
        with acquire_mutex_lock(self.graph_path):
            self._load()  # Sync latest state from disk before mutating
            
            if node_type not in NODE_TYPES:
                node_type = "memory"  # fallback
    
            # Enforce node cap
            if node_id not in self.nodes and len(self.nodes) >= MAX_GRAPH_NODES:
                return {"error": f"Node cap reached ({MAX_GRAPH_NODES}). Delete old nodes first."}

            node = MemoryNode(node_id, node_type, label, content, metadata)
            existing = self.nodes.get(node_id)

            if existing:
                # Merge — keep created_at, update rest
                node_dict = node.to_dict()
                node_dict["created_at"] = existing.get("created_at", node.created_at)
                node_dict["updated_at"] = time.time()
                self.nodes[node_id] = node_dict
            else:
                self.nodes[node_id] = node.to_dict()

            self._save()
            return self.nodes[node_id]

    def create_edge(self, source_id: str, target_id: str, edge_type: str,
                    weight: float = 1.0, metadata: dict = None) -> dict:
        """Create a relationship between two nodes. Protected by OS Mutex to prevent stale overwrites."""
        with acquire_mutex_lock(self.graph_path):
            self._load()  # Sync latest state from disk before mutating
            
            if source_id not in self.nodes or target_id not in self.nodes:
                missing = source_id if source_id not in self.nodes else target_id
                return {"error": f"Node '{missing}' not found"}
    
            if edge_type not in EDGE_TYPES:
                edge_type = "relates_to"

            # Enforce edge cap
            if len(self.edges) >= MAX_GRAPH_EDGES:
                return {"error": f"Edge cap reached ({MAX_GRAPH_EDGES}). Delete old edges first."}

            # Check for duplicate edges
            for e in self.edges:
                if e["source"] == source_id and e["target"] == target_id and e["type"] == edge_type:
                    # Update weight
                    e["weight"] = weight
                    self._save()
                    return e

            edge = MemoryEdge(source_id, target_id, edge_type, weight, metadata)
            edge_dict = edge.to_dict()
            self.edges.append(edge_dict)
            self._save()
            return edge_dict

    def get_node(self, node_id: str) -> Optional[dict]:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    def search_nodes(self, query: str, node_type: str = None, limit: int = 10) -> List[dict]:
        """Search nodes by label/content substring match."""
        query_lower = query.lower()
        results = []

        for node in self.nodes.values():
            if node_type and node.get("type") != node_type:
                continue
            score = 0
            if query_lower in node.get("label", "").lower():
                score += 2
            if query_lower in node.get("content", "").lower():
                score += 1
            if score > 0:
                results.append({**node, "_score": score})

        results.sort(key=lambda x: x["_score"], reverse=True)
        return results[:limit]

    def get_neighbors(self, node_id: str, edge_type: str = None,
                      direction: str = "both") -> List[dict]:
        """Get all nodes connected to a given node."""
        neighbors = []

        for edge in self.edges:
            if edge_type and edge["type"] != edge_type:
                continue

            if direction in ("out", "both") and edge["source"] == node_id:
                target = self.nodes.get(edge["target"])
                if target:
                    neighbors.append({
                        "node": target,
                        "edge": edge,
                        "direction": "outgoing",
                    })

            if direction in ("in", "both") and edge["target"] == node_id:
                source = self.nodes.get(edge["source"])
                if source:
                    neighbors.append({
                        "node": source,
                        "edge": edge,
                        "direction": "incoming",
                    })

        # Sort by edge weight (strongest connections first)
        neighbors.sort(key=lambda x: x["edge"].get("weight", 0), reverse=True)
        return neighbors

    def get_subgraph(self, node_id: str, depth: int = 2) -> dict:
        """Get a subgraph around a node up to N levels deep."""
        visited = set()
        nodes_out = {}
        edges_out = []

        def _traverse(nid: str, current_depth: int):
            if nid in visited or current_depth > depth:
                return
            visited.add(nid)
            node = self.nodes.get(nid)
            if node:
                nodes_out[nid] = node

            for edge in self.edges:
                if edge["source"] == nid and edge["target"] not in visited:
                    edges_out.append(edge)
                    _traverse(edge["target"], current_depth + 1)
                elif edge["target"] == nid and edge["source"] not in visited:
                    edges_out.append(edge)
                    _traverse(edge["source"], current_depth + 1)

        _traverse(node_id, 0)
        return {
            "center": node_id,
            "nodes": list(nodes_out.values()),
            "edges": edges_out,
            "total_nodes": len(nodes_out),
            "total_edges": len(edges_out),
        }

    def get_stats(self) -> dict:
        """Get graph statistics."""
        type_counts = {}
        for node in self.nodes.values():
            t = node.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        edge_type_counts = {}
        for edge in self.edges:
            t = edge.get("type", "unknown")
            edge_type_counts[t] = edge_type_counts.get(t, 0) + 1

        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "node_types": type_counts,
            "edge_types": edge_type_counts,
        }

    def delete_node(self, node_id: str) -> bool:
        """Delete a node and all its edges. Protected by OS Mutex."""
        with acquire_mutex_lock(self.graph_path):
            self._load() # Refresh before dropping
            
            if node_id not in self.nodes:
                return False
    
            del self.nodes[node_id]
            self.edges = [e for e in self.edges
                          if e["source"] != node_id and e["target"] != node_id]
            self._save()
        return True


# Convenience functions for MCP tool integration
_graphs: Dict[str, MemoryGraph] = {}

def get_graph(workspace_path: str) -> MemoryGraph:
    """Get or create a MemoryGraph for a workspace (cached)."""
    if workspace_path not in _graphs:
        _graphs[workspace_path] = MemoryGraph(workspace_path)
    return _graphs[workspace_path]
