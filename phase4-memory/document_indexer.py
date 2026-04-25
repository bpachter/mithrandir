"""
document_indexer.py — Document and codebase RAG for Mithrandir (Phase 4)

Indexes local files into ChromaDB so the agent can retrieve relevant
context from your own documents — JOURNEY.md, research notes, the Mithrandir
codebase itself, or any other text files you point it at.

Inspired by Matthew Busel's approach: index your entire codebase (or knowledge
base) into a local vector DB so the LLM can answer questions grounded in your
own work rather than general knowledge.

Usage:
    # Index documents once (or re-run to refresh):
    from document_indexer import index_path, search_docs

    index_path("C:/path/to/mithrandir")  # whole repo
    index_path("C:/path/to/mithrandir/JOURNEY.md")  # single file

    # Retrieve relevant chunks at query time:
    results = search_docs("Why did DUK fail the QV screen?")
    # Returns formatted string with source file + chunk content
"""

import os
import hashlib
import requests
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_CHROMA_PATH = os.path.join(_HERE, "chroma_db")

_OLLAMA_URL = "http://localhost:11434"
_EMBED_MODEL = "nomic-embed-text"
_COLLECTION_NAME = "documents"

# File extensions to index
_INDEXABLE = {".py", ".md", ".txt", ".rst", ".toml", ".yaml", ".yml", ".env.example"}

# Directories to skip
_SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    "node_modules", "chroma_db", "data", "archive",
}

# Chunk size in characters — ~400 chars ≈ ~100 tokens, good retrieval granularity
_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 150

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _embed(text: str) -> list[float]:
    resp = requests.post(
        f"{_OLLAMA_URL}/api/embed",
        json={"model": _EMBED_MODEL, "input": text},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


def _chunk_text(text: str, source: str) -> list[dict]:
    """
    Split text into overlapping chunks. Each chunk carries its source path
    and character offset so we can show the user where a result came from.
    """
    chunks = []
    start = 0
    while start < len(text):
        end = start + _CHUNK_SIZE
        chunk = text[start:end]
        if chunk.strip():
            chunks.append({
                "text": chunk,
                "source": source,
                "offset": start,
            })
        start += _CHUNK_SIZE - _CHUNK_OVERLAP
    return chunks


def _chunk_id(source: str, offset: int) -> str:
    return hashlib.sha256(f"{source}:{offset}".encode()).hexdigest()[:16]


def _get_collection():
    client = chromadb.PersistentClient(
        path=_CHROMA_PATH,
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection(
        name=_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def index_file(file_path: str) -> int:
    """
    Index a single file into ChromaDB. Returns number of chunks added.
    Skips already-indexed chunks (idempotent — safe to re-run).
    """
    path = Path(file_path)
    if path.suffix.lower() not in _INDEXABLE:
        return 0

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0

    if not text.strip():
        return 0

    chunks = _chunk_text(text, str(path))
    if not chunks:
        return 0

    col = _get_collection()
    existing_ids = set(col.get(include=[])["ids"])

    new_ids, new_embeddings, new_docs, new_metas = [], [], [], []
    for chunk in chunks:
        cid = _chunk_id(chunk["source"], chunk["offset"])
        if cid in existing_ids:
            continue  # already indexed
        try:
            emb = _embed(chunk["text"])
        except Exception:
            continue
        new_ids.append(cid)
        new_embeddings.append(emb)
        new_docs.append(chunk["text"])
        new_metas.append({
            "source": chunk["source"],
            "offset": chunk["offset"],
            "filename": path.name,
        })

    if new_ids:
        col.add(ids=new_ids, embeddings=new_embeddings,
                documents=new_docs, metadatas=new_metas)

    return len(new_ids)


def index_path(root: str, verbose: bool = True) -> dict:
    """
    Recursively index all indexable files under root.
    Returns summary: {files_scanned, chunks_added, files_indexed}.
    """
    root_path = Path(root)
    stats = {"files_scanned": 0, "chunks_added": 0, "files_indexed": 0}

    if root_path.is_file():
        added = index_file(str(root_path))
        if verbose:
            print(f"  {root_path.name}: {added} chunks")
        stats["files_scanned"] = 1
        stats["chunks_added"] = added
        stats["files_indexed"] = 1 if added > 0 else 0
        return stats

    for path in sorted(root_path.rglob("*")):
        # Skip hidden dirs and known noise dirs
        if any(part in _SKIP_DIRS or part.startswith(".") for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() not in _INDEXABLE:
            continue

        stats["files_scanned"] += 1
        added = index_file(str(path))
        if added > 0:
            stats["files_indexed"] += 1
            stats["chunks_added"] += added
            if verbose:
                rel = path.relative_to(root_path)
                print(f"  {rel}: {added} chunks")

    return stats


def clear_index() -> None:
    """Delete and recreate the documents collection. Use before a full re-index."""
    client = chromadb.PersistentClient(
        path=_CHROMA_PATH,
        settings=Settings(anonymized_telemetry=False),
    )
    try:
        client.delete_collection(_COLLECTION_NAME)
    except Exception:
        pass
    client.get_or_create_collection(
        name=_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    print("Document index cleared.")


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def search_docs(query: str, k: int = 4) -> str:
    """
    Retrieve the top-k most relevant document chunks for a query.

    Returns a formatted string ready for system prompt injection,
    or empty string if index is empty or no relevant results.
    """
    try:
        col = _get_collection()
        if col.count() == 0:
            return ""

        embedding = _embed(query)
        results = col.query(
            query_embeddings=[embedding],
            n_results=min(k, col.count()),
            include=["documents", "metadatas", "distances"],
        )

        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]

        # Filter low-relevance results
        relevant = [
            (doc, meta, dist)
            for doc, meta, dist in zip(docs, metas, distances)
            if dist < 0.45
        ]
        if not relevant:
            return ""

        lines = ["[DOCUMENT CONTEXT — retrieved from local knowledge base]"]
        for doc, meta, dist in relevant:
            similarity = 1 - dist
            source = Path(meta["source"]).name
            lines.append(f"Source: {source} (similarity: {similarity:.0%})\n{doc.strip()}")
        lines.append("[END DOCUMENT CONTEXT]")

        return "\n\n---\n\n".join(lines)

    except Exception:
        return ""


def index_stats() -> dict:
    """Return document index stats."""
    try:
        col = _get_collection()
        count = col.count()
    except Exception:
        count = 0
    return {"document_chunks": count}


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    repo_root = os.path.normpath(os.path.join(_HERE, ".."))

    if len(sys.argv) > 1 and sys.argv[1] == "clear":
        clear_index()

    print(f"Indexing {repo_root} ...")
    stats = index_path(repo_root, verbose=True)
    print(f"\nDone: {stats['files_indexed']} files, {stats['chunks_added']} chunks added")

    print("\nTest query: 'Why did DUK fail the QV screen?'")
    result = search_docs("Why did DUK fail the QV screen?")
    safe = (result[:800] if result else "(no results)").encode("ascii", "replace").decode("ascii")
    print(safe)

    print(f"\nIndex stats: {index_stats()}")
