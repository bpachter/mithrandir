"""
memory_store.py — Persistent conversation memory for Mithrandir (Phase 4)

Two-layer storage:
  1. SQLite  — structured log of every exchange (timestamp, user msg, assistant msg)
  2. ChromaDB — vector embeddings of every exchange for semantic retrieval

On each new query, retrieve_context() finds the top-k most semantically
similar past exchanges and returns them as a formatted context block for
injection into the system prompt.

Usage:
    from memory_store import save_exchange, retrieve_context

    # After agent responds:
    save_exchange("What is DUK's FCF?", "DUK had FCF of -$1.69B in FY2025...")

    # Before next agent call:
    context = retrieve_context("Duke Energy capital expenditure")
    # Returns formatted string ready for system prompt injection
"""

import os
import sqlite3
import hashlib
import requests
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Optional

import chromadb
from chromadb.config import Settings

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_DB_PATH = os.path.join(_HERE, "memory.db")
_CHROMA_PATH = os.path.join(_HERE, "chroma_db")

_OLLAMA_URL = "http://localhost:11434"
_EMBED_MODEL = "nomic-embed-text"
_COLLECTION_NAME = "conversations"

# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

def _embed(text: str) -> list[float]:
    """Embed text via nomic-embed-text running in Ollama."""
    resp = requests.post(
        f"{_OLLAMA_URL}/api/embed",
        json={"model": _EMBED_MODEL, "input": text},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


# ---------------------------------------------------------------------------
# SQLite — structured log
# ---------------------------------------------------------------------------

@contextmanager
def _get_db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS exchanges (
                id            TEXT PRIMARY KEY,
                timestamp     TEXT NOT NULL,
                user_msg      TEXT NOT NULL,
                asst_msg      TEXT NOT NULL,
                rating        INTEGER,
                user_feedback TEXT,
                auto_score    TEXT
            )
        """)
        # Migrate tables created before rating columns existed
        existing = {r[1] for r in conn.execute("PRAGMA table_info(exchanges)").fetchall()}
        for col, defn in [
            ("rating", "INTEGER"),
            ("user_feedback", "TEXT"),
            ("auto_score", "TEXT"),
        ]:
            if col not in existing:
                conn.execute(f"ALTER TABLE exchanges ADD COLUMN {col} {defn}")
        conn.commit()
        yield conn
        conn.commit()
    finally:
        conn.close()


def _exchange_id(user_msg: str, timestamp: str) -> str:
    """Stable ID for an exchange — hash of timestamp + user message."""
    return hashlib.sha256(f"{timestamp}:{user_msg}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# ChromaDB — vector store
# ---------------------------------------------------------------------------

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
# Public API
# ---------------------------------------------------------------------------

def save_exchange(user_msg: str, assistant_msg: str) -> str:
    """
    Persist a user/assistant exchange to SQLite and ChromaDB.

    The embedded text is the concatenation of both turns — this means
    retrieval finds exchanges that are semantically similar to either
    the question or the answer, not just the question.

    Returns the exchange ID.
    """
    ts = datetime.now().isoformat()
    eid = _exchange_id(user_msg, ts)

    # SQLite log
    with _get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO exchanges (id, timestamp, user_msg, asst_msg) VALUES (?,?,?,?)",
            (eid, ts, user_msg, assistant_msg),
        )

    # ChromaDB vector
    combined = f"User: {user_msg}\nAssistant: {assistant_msg}"
    try:
        embedding = _embed(combined)
        col = _get_collection()
        col.add(
            ids=[eid],
            embeddings=[embedding],
            documents=[combined],
            metadatas=[{"timestamp": ts, "user_msg": user_msg[:200]}],
        )
    except Exception as e:
        # Embedding failure is non-fatal — SQLite log is still intact
        print(f"[memory] embedding failed (will retry next session): {e}")

    return eid


def retrieve_context(query: str, k: int = 3) -> str:
    """
    Retrieve the top-k most semantically similar past exchanges for a query.

    Returns a formatted string ready to inject into the system prompt,
    or an empty string if no relevant history exists.
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
        distances = results["distances"][0]

        # Filter out low-relevance results (cosine distance > 0.5 = < 50% similar)
        relevant = [(doc, dist) for doc, dist in zip(docs, distances) if dist < 0.5]
        if not relevant:
            return ""

        lines = ["[MEMORY — relevant past exchanges]"]
        for doc, dist in relevant:
            similarity = 1 - dist
            lines.append(f"(similarity: {similarity:.0%})\n{doc}")
        lines.append("[END MEMORY]")

        return "\n\n".join(lines)

    except Exception:
        return ""


def get_recent_exchanges(n: int = 5) -> list[dict]:
    """Return the n most recent exchanges from SQLite (for /history command)."""
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT timestamp, user_msg, asst_msg FROM exchanges ORDER BY timestamp DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [{"timestamp": r[0], "user": r[1], "assistant": r[2]} for r in rows]


def rate_exchange(exchange_id: str, rating: int) -> bool:
    """Set thumbs-up (1) or thumbs-down (-1) on an exchange. Returns True if found."""
    with _get_db() as conn:
        cur = conn.execute(
            "UPDATE exchanges SET rating = ? WHERE id = ?",
            (rating, exchange_id),
        )
        return cur.rowcount > 0


def add_user_feedback(exchange_id: str, feedback: str) -> bool:
    """Store free-text feedback from a /rate command. Returns True if found."""
    with _get_db() as conn:
        cur = conn.execute(
            "UPDATE exchanges SET user_feedback = ? WHERE id = ?",
            (feedback.strip(), exchange_id),
        )
        return cur.rowcount > 0


def add_auto_score(exchange_id: str, score_json: str) -> bool:
    """Store a JSON blob of Claude-as-judge scores for an exchange."""
    with _get_db() as conn:
        cur = conn.execute(
            "UPDATE exchanges SET auto_score = ? WHERE id = ?",
            (score_json, exchange_id),
        )
        return cur.rowcount > 0


def memory_stats() -> dict:
    """Return counts for the /stats command."""
    with _get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0]
    try:
        chroma_count = _get_collection().count()
    except Exception:
        chroma_count = 0
    return {"sqlite_exchanges": total, "chroma_vectors": chroma_count}


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Testing memory store...")

    eid = save_exchange(
        "What is DUK's free cash flow?",
        "DUK had FCF of -$1.69B in FY2025. CFO was $12.3B but CapEx was ~$14B.",
    )
    print(f"Saved exchange: {eid}")

    eid2 = save_exchange(
        "Compare NUE and CLF on EV/EBIT.",
        "NUE trades at 6.2x EV/EBIT, CLF at 5.8x. CLF is cheaper on this metric.",
    )
    print(f"Saved exchange: {eid2}")

    ctx = retrieve_context("Duke Energy capital expenditure spending")
    print(f"\nRetrieval for 'Duke Energy capex':\n{ctx}")

    stats = memory_stats()
    print(f"\nStats: {stats}")
