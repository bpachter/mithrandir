# Phase 4 — Persistent Memory + RAG

**Status:** ✅ Complete (April 13, 2026)

![Memory recall across sessions](../assets/phase4-memory-recall.gif)
<!-- ⤴ Capture: docs/MEDIA_GUIDE.md “Phase 4” -->

> **Plain English:** Out of the box, an LLM forgets *everything* the moment you close the window. This phase gives Mithrandir a memory — a small local database that stores every conversation and lets the agent re-read past chats by *meaning*, not keyword. It also indexes the project's own source code, so when you ask "why did we build X?" it can quote the exact file and decision instead of making something up.

Gives Mithrandir two complementary memory systems: conversation memory across sessions (semantic retrieval + structured history), and document/codebase RAG (index your repo and knowledge base so the agent can cite its own prior work).

---

## Architecture

```
User query
    │
    ▼
mithrandir_agent.py
    │
    ├── memory_bridge.py retrieve <query>   ← semantic search over past conversations
    │       └── memory_store.py            ← ChromaDB conversations + SQLite history
    │
    ├── [system prompt injection]          ← relevant past context prepended
    │
    ├── [ReAct loop runs...]
    │       ├── recall_memory tool         ← agent can explicitly search memory
    │       └── search_docs tool           ← agent can search indexed codebase/docs
    │
    └── [final answer]
            └── memory_bridge.py save      ← saves exchange to both stores (async)
```

---

## Files

| File | Purpose |
|------|---------|
| `memory_store.py` | Dual-write store: SQLite for history, ChromaDB for semantic search |
| `document_indexer.py` | Chunk + embed local files into ChromaDB for codebase RAG |
| `memory_bridge.py` | Subprocess CLI bridge (phase3 calls this via `phase4-memory/.venv`) |
| `.venv/` | Isolated venv with chromadb, onnxruntime (heavy deps) |
| `memory.db` | SQLite conversation history (auto-created) |
| `chroma_db/` | ChromaDB persistent store (auto-created) |

---

## Setup

### 1. Create the phase4 venv and install dependencies

```bash
cd phase4-memory
python -m venv .venv
.venv/Scripts/pip install chromadb requests
```

### 2. Pull the embedding model via Ollama

```bash
ollama pull nomic-embed-text
```

Ollama must be running when memory calls are made (`ollama serve` or via the Ollama desktop app).

### 3. Index your codebase

```bash
.venv/Scripts/python document_indexer.py
```

This recursively indexes the entire Mithrandir repo (~712 chunks from 49 files on first run).
Re-running is safe — chunk IDs are SHA256 hashes of `(source_path, char_offset)`, so already-indexed chunks are skipped.

---

## Memory Bridge CLI

The bridge is called as a subprocess from phase3-agents so heavy deps stay isolated:

```bash
# Save a conversation exchange
.venv/Scripts/python memory_bridge.py save "user message" "assistant reply"

# Retrieve relevant past context for a query
.venv/Scripts/python memory_bridge.py retrieve "DUK capital expenditure"

# Search the document index
.venv/Scripts/python memory_bridge.py search_docs "why did we add HMM regime detection"

# Show memory stats
.venv/Scripts/python memory_bridge.py stats

# Re-index the codebase (e.g. after adding new files)
.venv/Scripts/python memory_bridge.py reindex
```

---

## Agent Tools

Two tools are registered in `phase3-agents/tools/registry.py`:

**`recall_memory`** — semantic search over past conversation history. The agent invokes this when the user references something from a previous session.

**`search_docs`** — semantic search over the indexed codebase + documents. Use when the user asks how something was built, why a decision was made, or references project history.

Both call `memory_bridge.py` as a subprocess and return the result as a plain-text observation.

---

## Automatic Context Injection

Every query automatically retrieves relevant past exchanges and prepends them to the system prompt — no user action required. The agent only needs to explicitly call `recall_memory` when it wants more memory context than was auto-injected.

Thresholds:
- Conversation memory: cosine distance < 0.5 (top 3 results)
- Document index: cosine distance < 0.45 (top 4 results)

---

![/stats output showing memory + doc-index counts](../assets/phase4-stats.png)
<!-- ⤴ Capture: docs/MEDIA_GUIDE.md “Phase 4” -->

## Telegram Commands

| Command | What it does |
|---------|-------------|
| `/stats` | Session query count + memory exchange count + document chunk count |
| `/history` | Last 5 conversation exchanges with timestamps |

---

## Design Notes

**Why a subprocess bridge?** chromadb installs onnxruntime, huggingface-hub, and other heavy packages (~500MB). A dedicated venv keeps these out of the phase3 bot environment and prevents pip file-lock collisions when the bot is running.

**Why dual-store (SQLite + ChromaDB)?** SQLite handles chronological queries (`/history`, recent context) cheaply. ChromaDB handles semantic similarity search. They serve different access patterns.

**Idempotent indexing** — SHA256 chunk IDs mean re-indexing never creates duplicates. Run `reindex` whenever you add new files to the repo.
