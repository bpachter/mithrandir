# Enkidu

Local AI assistant. Gemma 4 inference + Claude API fallback. Learning CUDA, agentic frameworks, and LLM deployment.

## Architecture

- **Inference**: Ollama + Gemma 4 27B (CUDA 12.x, RTX 4090)
- **Routing**: Local queries → Gemma; complex reasoning → Claude API
- **Memory**: ChromaDB + SQLite
- **Voice** (Phase 4): openwakeword → faster-whisper → Kokoro TTS
- **Orchestration**: OpenClaw (Discord/Telegram interface)

## Build Phases

**Phase 1: Local Inference** (current)
- Ollama + Gemma 4 running on 4090
- Open WebUI for browser chat
- Claude API working as fallback
- Learn: CUDA pipelines, inference speed, VRAM management

**Phase 2: Tool Use**
- Route queries to local or Claude based on complexity
- Build 2-3 real tools (SEC Edgar screener, GIS queries, etc.)
- Actually use it for work
- Learn: Prompt design, tool calling, token economics

**Phase 3: Agency**
- OpenClaw integration (Discord/CLI)
- Multi-step reasoning and routing logic
- Error handling and fallbacks
- Learn: Agentic frameworks, orchestration

**Phase 4: Memory**
- ChromaDB for vector storage + retrieval
- SQLite for conversation history
- Persistent context across sessions
- Learn: RAG, embeddings, state management

**Phase 5: Voice** (optional)
- Wake word detection
- Speech-to-text (faster-whisper)
- Text-to-speech (Kokoro)
- Learn: Audio pipelines, real-time constraints

## Current Status

Phase 1 setup: Claude API auth working, dependencies installed. Next: Docker + Ollama.

## Stack

- Python 3.11
- Anthropic Claude API
- Ollama (Gemma 4 27B)
- ChromaDB + nomic-embed-text
- OpenClaw
- Docker + WSL2
