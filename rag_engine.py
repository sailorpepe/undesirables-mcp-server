"""
Local RAG Engine — Retrieval-Augmented Generation for Soul Memory

Indexes soul workspace files (SOUL.md, IDENTITY.md, MEMORY.md, etc.) into a
local LanceDB vector database using all-MiniLM-L6-v2 embeddings (~80MB).

When the agent receives a query, relevant chunks are retrieved and injected
into the system prompt for grounded, context-aware responses.

Architecture inspired by:
- ContextPlus: incremental file hash manifest for change detection
- Project NOMAD: Qdrant RAG pattern (adapted to LanceDB for zero-config)
- Hermes Agent: multi-level memory retrieval

Runs 100% locally. No cloud. No telemetry.
"""

import os
import json
import hashlib
import logging
import numpy as np
from pathlib import Path
from typing import List, Optional
from security import validate_workspace_path, is_safe_symlink

logger = logging.getLogger("rag_engine")

# Lazy-load singletons
_embedder = None
_db = None
_table = None

CHUNK_SIZE = 500       # characters per chunk
CHUNK_OVERLAP = 100    # overlap between chunks
TABLE_NAME = "soul_memory"


def _get_embedder():
    """Lazy-load sentence-transformers model (~80MB, runs on MPS)."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        import torch
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        _embedder = SentenceTransformer("all-MiniLM-L6-v2", device=device)
        logger.info(f"[RAG] Loaded all-MiniLM-L6-v2 on {device}")
    return _embedder


def _get_db(workspace_path: str):
    """Get or create a LanceDB database in the workspace."""
    global _db, _table
    import lancedb

    db_path = os.path.join(workspace_path, ".rag_index")
    _db = lancedb.connect(db_path)

    if TABLE_NAME in _db.table_names():
        _table = _db.open_table(TABLE_NAME)
    else:
        _table = None

    return _db


def _chunk_text(text: str, source: str) -> List[dict]:
    """Split text into overlapping chunks with markdown header awareness."""
    chunks = []
    lines = text.split('\n')
    current_header = ""
    current_chunk = ""

    for line in lines:
        # Track markdown headers for context
        if line.startswith('#'):
            current_header = line.strip()

        current_chunk += line + '\n'

        if len(current_chunk) >= CHUNK_SIZE:
            chunks.append({
                "text": current_chunk.strip(),
                "source": source,
                "header": current_header,
            })
            # Keep overlap
            overlap_start = max(0, len(current_chunk) - CHUNK_OVERLAP)
            current_chunk = current_chunk[overlap_start:]

    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append({
            "text": current_chunk.strip(),
            "source": source,
            "header": current_header,
        })

    return chunks


def _compute_file_hash(filepath: str) -> str:
    """BLAKE2b super-fast hash for change detection (quantum resistant)."""
    with open(filepath, 'rb') as f:
        return hashlib.blake2b(f.read(), digest_size=32).hexdigest()


def index_workspace(workspace_path: str) -> dict:
    """
    Index all markdown/text files in a soul workspace into LanceDB.
    Uses SHA-256 hash manifest to skip unchanged files (incremental indexing).

    Returns: {"indexed": int, "skipped": int, "total_chunks": int}
    """
    global _table
    import lancedb

    workspace_path = validate_workspace_path(workspace_path)
    embedder = _get_embedder()
    db = _get_db(workspace_path)

    # Load existing hash manifest
    manifest_path = os.path.join(workspace_path, ".rag_manifest.json")
    old_manifest = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, 'r') as f:
            old_manifest = json.load(f)

    # Scan workspace for indexable files
    indexable_exts = {'.md', '.txt', '.json'}
    files_to_index = []
    new_manifest = {}
    skipped = 0

    for ext in indexable_exts:
        for filepath in Path(workspace_path).rglob(f'*{ext}'):
            # Skip hidden dirs and the index itself
            if any(part.startswith('.') for part in filepath.parts[len(Path(workspace_path).parts):]):
                continue
            # Skip symlinks pointing outside workspace
            if not is_safe_symlink(str(filepath), workspace_path):
                continue

            filepath_str = str(filepath)
            file_hash = _compute_file_hash(filepath_str)
            new_manifest[filepath_str] = file_hash

            if old_manifest.get(filepath_str) == file_hash:
                skipped += 1
                continue

            files_to_index.append(filepath_str)

    if not files_to_index:
        logger.info("[RAG] All files up to date, nothing to index")
        return {"indexed": 0, "skipped": skipped, "total_chunks": 0}

    # Chunk and embed all changed files
    all_chunks = []
    for filepath in files_to_index:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                text = f.read()
            rel_path = os.path.relpath(filepath, workspace_path)
            chunks = _chunk_text(text, rel_path)
            all_chunks.extend(chunks)
        except Exception as e:
            logger.warning(f"[RAG] Failed to read {filepath}: {e}")

    if not all_chunks:
        return {"indexed": 0, "skipped": skipped, "total_chunks": 0}

    # Batch embed
    texts = [c["text"] for c in all_chunks]
    embeddings = embedder.encode(texts, show_progress_bar=True, batch_size=32)

    # Build records for LanceDB
    records = []
    for i, chunk in enumerate(all_chunks):
        records.append({
            "text": chunk["text"],
            "source": chunk["source"],
            "header": chunk["header"],
            "vector": embeddings[i].tolist(),
        })

    # Upsert into LanceDB
    if _table is None:
        _table = db.create_table(TABLE_NAME, data=records, mode="overwrite")
    else:
        # Delete old chunks from changed files, then add new ones
        changed_sources = set(os.path.relpath(f, workspace_path) for f in files_to_index)
        try:
            for source in changed_sources:
                _table.delete(f'source = "{source.replace(chr(34), "")}"')
        except Exception:
            pass
        _table.add(records)

    # Save manifest
    with open(manifest_path, 'w') as f:
        json.dump(new_manifest, f, indent=2)

    logger.info(f"[RAG] Indexed {len(files_to_index)} files → {len(records)} chunks")
    return {
        "indexed": len(files_to_index),
        "skipped": skipped,
        "total_chunks": len(records),
    }


def search_memory(workspace_path: str, query: str, top_k: int = 5) -> List[dict]:
    """
    Semantic search across indexed soul memory.

    Returns: List of {"text": str, "source": str, "header": str, "score": float}
    """
    global _table

    embedder = _get_embedder()
    db = _get_db(workspace_path)

    if _table is None:
        logger.warning("[RAG] No index found. Run index_workspace first.")
        return []

    # Embed query
    query_embedding = embedder.encode([query])[0].tolist()

    # Search
    results = _table.search(query_embedding).limit(top_k).to_list()

    return [
        {
            "text": r["text"],
            "source": r["source"],
            "header": r.get("header", ""),
            "score": round(float(r.get("_distance", 0)), 4),
        }
        for r in results
    ]


def build_rag_context(workspace_path: str, query: str, max_tokens: int = 1500) -> str:
    """
    Build a RAG context string for injection into the system prompt.
    Retrieves relevant chunks and formats them as a grounded context block.
    """
    results = search_memory(workspace_path, query)

    if not results:
        return ""

    context_parts = ["[MEMORY RETRIEVAL — relevant fragments from your soul workspace]"]
    total_chars = 0

    for r in results:
        chunk = f"\n---\n📄 {r['source']}"
        if r['header']:
            chunk += f" > {r['header']}"
        chunk += f"\n{r['text']}"

        if total_chars + len(chunk) > max_tokens * 4:  # rough char→token estimate
            break

        context_parts.append(chunk)
        total_chars += len(chunk)

    context_parts.append("\n[END MEMORY RETRIEVAL]")
    return '\n'.join(context_parts)
