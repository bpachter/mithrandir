# Enkidu in Open WebUI

This setup exposes the Phase 3 Enkidu agent inside Open WebUI without using OpenAI or any OpenAI-compatible API.

Architecture:

```
Open WebUI function
    -> host.docker.internal:8011/chat
    -> enkidu_openwebui_bridge.py
    -> enkidu_agent.py
    -> existing Enkidu tools + Ollama + Claude fallback + memory
```

## What this is

- `enkidu_openwebui_bridge.py` runs on your Windows host and exposes a small local HTTP endpoint.
- `openwebui_enkidu_function.py` is a native Open WebUI function you import into the UI.
- Telegram keeps working unchanged.
- Open WebUI becomes a second interface to the same Enkidu agent stack.

## What this is not

- Not an OpenAI API wrapper.
- Not an OpenAI-compatible `/v1/chat/completions` server.
- Not a replacement for Ollama in Open WebUI.

## 1. Start the bridge on Windows

From the repo root:

```powershell
.\start_enkidu_openwebui_bridge.bat
```

Or directly:

```powershell
cd phase3-agents
C:\Python312\python.exe enkidu_openwebui_bridge.py
```

Default address:

```text
http://127.0.0.1:8011
```

Health check:

```powershell
Invoke-WebRequest http://127.0.0.1:8011/health | Select-Object -ExpandProperty Content
```

## 2. Import the function into Open WebUI

In Open WebUI:

1. Open `Admin Panel`
2. Open `Functions`
3. Create a new function
4. Paste the contents of `phase3-agents/openwebui_enkidu_function.py`
5. Save and enable it

After that, `Enkidu Agent` should appear in the model picker.

## 3. Configure the function valves

Open the valves/settings for the function and confirm:

- `BRIDGE_URL = http://host.docker.internal:8011/chat`
- `REQUEST_TIMEOUT_SECONDS = 600`
- `SAVE_MEMORY = true`

`host.docker.internal` is the correct host alias for Docker Desktop on Windows, which is what your Open WebUI container uses.

## 4. Use it

Pick `Enkidu Agent` from the model dropdown in Open WebUI and chat normally.

The function passes your current Open WebUI conversation into the host bridge, which converts recent chat turns into a prompt for `enkidu_agent.py`.

## Notes

- Open WebUI chat history and Enkidu Phase 4 memory are separate systems. With `SAVE_MEMORY = true`, Open WebUI conversations will also be stored in Enkidu memory.
- The current bridge returns the final answer once the agent finishes. It does not stream tool-by-tool output into Open WebUI.
- Telegram and Open WebUI can run at the same time.

## Troubleshooting

### Open WebUI says it cannot reach the bridge

- Confirm the bridge is running on Windows.
- Test `http://127.0.0.1:8011/health` on the host.
- Keep `BRIDGE_URL` as `http://host.docker.internal:8011/chat` inside Open WebUI.

### The agent answers but forgets browser chat context

- The bridge currently compresses recent Open WebUI turns into a single prompt before calling `run_agent()`.
- If you want full multi-turn agent state later, that would require extending Enkidu from single-message entry to conversation-native state management.

### The function imports but does not appear as a model

- Make sure the function is saved as a `Pipe` and enabled.
- Re-open the chat or refresh Open WebUI after saving.