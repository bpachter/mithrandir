"""
telegram_interface.py — Telegram bot for Enkidu (Phase 3)

Uses pyTelegramBotAPI (telebot) with requests-based HTTP — avoids the
anyio/Windows TLS incompatibility in python-telegram-bot v21+.

Architecture:
    Telegram message arrives → authorized user check → run_agent() in
    thread → on_step callbacks edit a "thinking" placeholder live →
    final answer replaces it when done.

Setup:
    1. Create bot via @BotFather → TELEGRAM_BOT_TOKEN in .env
    2. Get user ID via @userinfobot → TELEGRAM_ALLOWED_USER_ID in .env
    3. Run: python telegram_interface.py

Commands:
    /start   — greeting
    /help    — command list
    /stats   — session query count
    /refresh — re-run the QV pipeline (prompts for confirmation)
"""

import os
import sys
import time
import threading
import logging
from typing import Optional

import ssl
import subprocess
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from dotenv import load_dotenv
import requests
from requests.adapters import HTTPAdapter
import telebot
import telebot.apihelper as _apihelper
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

# Monkey-patch telebot's session factory to fix WinError 10054 (TLS 1.3 reset on Windows).
# Forces TLS 1.2, disables cert verification and hostname checking.
# Safe on a personal home network connecting to api.telegram.org.

class _NoALPNContext:
    """
    Wrapper around ssl.SSLContext that silences set_alpn_protocols().

    urllib3 unconditionally calls context.set_alpn_protocols(["http/1.1"])
    on whatever ssl_context we provide.  On this machine that ALPN header
    causes api.telegram.org to TCP-reset the TLS 1.2 handshake (WinError
    10054).  Wrapping the context and no-op'ing set_alpn_protocols is the
    minimal, targeted fix — all other SSL behaviour is unchanged.
    """
    def __init__(self, ctx: ssl.SSLContext):
        self._ctx = ctx

    def set_alpn_protocols(self, protocols):
        pass  # intentional no-op — ALPN triggers server reset on TLS 1.2

    def wrap_socket(self, *args, **kwargs):
        return self._ctx.wrap_socket(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._ctx, name)


class _TLSAdapter(HTTPAdapter):
    """
    Custom TLS adapter: forces TLS 1.2 and suppresses ALPN negotiation.

    Root cause of WinError 10054 on this machine:
      1. ssl.create_default_context() negotiates TLS 1.3 — Telegram resets it.
      2. urllib3 adds ALPN http/1.1 to any context we provide — Telegram also
         resets TLS 1.2 when ALPN is present.
    Both are fixed here: TLS 1.2 is pinned, ALPN is suppressed via _NoALPNContext.
    """
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        kwargs["ssl_context"] = _NoALPNContext(ctx)
        super().init_poolmanager(*args, **kwargs)

_cached_session: Optional[requests.Session] = None

def _patched_session(reset=False):
    global _cached_session
    if reset or _cached_session is None:
        s = requests.Session()
        s.verify = False
        s.mount("https://", _TLSAdapter())
        # Disable TCP keep-alive: each request gets its own connection so
        # there's no stale socket for the server to reset mid-poll.
        s.headers.update({"Connection": "close"})
        _cached_session = s
    return _cached_session

_apihelper._get_req_session = _patched_session

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("enkidu.telegram")
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("TeleBot").setLevel(logging.WARNING)


class _ConnectionResetFilter(logging.Filter):
    """Suppress ConnectionReset / ConnectionError noise from the TeleBot logger.

    infinity_polling recovers from these automatically; logging them as ERROR
    is misleading and fills the terminal with red noise.
    """
    _SUPPRESS = ("ConnectionResetError", "ConnectionError", "10054", "RemoteDisconnected")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(kw in msg for kw in self._SUPPRESS)


logging.getLogger("TeleBot").addFilter(_ConnectionResetFilter())

# ---------------------------------------------------------------------------
# Config from .env
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
try:
    ALLOWED_USER_ID = int(os.environ.get("TELEGRAM_ALLOWED_USER_ID", "0"))
except ValueError:
    ALLOWED_USER_ID = 0

# Add phase3-agents/ to path so enkidu_agent can be imported
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from enkidu_agent import run_agent  # noqa: E402

# Lighting initialize — sets idle blue at startup (optional, no-op if unavailable)
try:
    _lighting_path = os.path.normpath(os.path.join(_here, "..", "phase2-tool-use", "tools"))
    if _lighting_path not in sys.path:
        sys.path.insert(0, _lighting_path)
    from lighting import initialize as _lighting_init
except Exception:
    def _lighting_init(): pass

# ---------------------------------------------------------------------------
# Memory bridge — subprocess into phase4 venv (same pattern as registry.py)
# ---------------------------------------------------------------------------

_PHASE4_PYTHON = os.path.normpath(os.path.join(_here, "..", "phase4-memory", ".venv", "Scripts", "python.exe"))
_MEMORY_BRIDGE = os.path.normpath(os.path.join(_here, "..", "phase4-memory", "memory_bridge.py"))

# Whether to run Claude-as-judge auto-scoring after every exchange.
# Costs ~$0.001/exchange. Set AUTO_SCORE_RESPONSES=true in .env to enable.
_AUTO_SCORE = os.environ.get("AUTO_SCORE_RESPONSES", "false").lower() == "true"


def _mem(timeout: int = 15, *args) -> str:
    """Call memory_bridge.py via the phase4 venv. Returns stdout."""
    if not os.path.exists(_PHASE4_PYTHON):
        return "[memory unavailable]"
    try:
        r = subprocess.run(
            [_PHASE4_PYTHON, _MEMORY_BRIDGE] + list(args),
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return r.stdout.strip() or r.stderr.strip()
    except Exception as e:
        return f"[memory error: {e}]"


def _save_exchange(user_msg: str, asst_msg: str) -> str:
    """Save exchange synchronously, return the exchange ID (or empty string)."""
    result = _mem(20, "save", user_msg, asst_msg)
    if result.startswith("saved:"):
        return result[6:]
    return ""


def _auto_score_exchange(eid: str, user_msg: str, asst_msg: str) -> None:
    """
    Call Claude to score the exchange on three axes, store result in DB.
    Runs in a background thread — never blocks the bot.
    """
    try:
        from anthropic import Anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return
        client = Anthropic(api_key=api_key)
        prompt = (
            "You are an objective evaluator of AI assistant responses. "
            "Score the following exchange on three axes, each 1–5:\n"
            "  accuracy   — factual correctness and precision\n"
            "  tone       — warmth, personality, felt like a real conversation\n"
            "  helpfulness — actually addressed what the user needed\n\n"
            f"User: {user_msg}\n\nAssistant: {asst_msg}\n\n"
            "Reply with ONLY valid JSON, no prose:\n"
            '{"accuracy": <1-5>, "tone": <1-5>, "helpfulness": <1-5>, "note": "<one sentence>"}'
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        score_json = resp.content[0].text.strip()
        _mem(10, "add_score", eid, score_json)
    except Exception as e:
        logger.debug(f"auto_score failed: {e}")


# ---------------------------------------------------------------------------
# Bot + session state
# ---------------------------------------------------------------------------

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# Simple session counter (in-memory, per bot process)
_session = {"queries": 0}

# Per-user flag: are we waiting for refresh confirmation?
_awaiting_refresh: dict[int, bool] = {}

# Last exchange ID per user — used by /rate and rating buttons
_last_eid: dict[int, str] = {}


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

def _authorized(message: Message) -> bool:
    if message.from_user.id != ALLOWED_USER_ID:
        bot.reply_to(message, "Unauthorized.")
        return False
    return True


# ---------------------------------------------------------------------------
# Safe message edit — rate limited, silently ignores "not modified"
# ---------------------------------------------------------------------------

def _safe_edit(chat_id: int, message_id: int, text: str) -> None:
    try:
        bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" not in str(e).lower():
            logger.debug(f"edit_message_text: {e}")
    except Exception as e:
        logger.debug(f"edit_message_text failed: {e}")


def _safe_send(chat_id: int, text: str, **kwargs) -> None:
    """Send a message, swallowing network errors so they don't crash the worker pool."""
    try:
        bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.debug(f"send_message failed: {e}")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["start"])
def cmd_start(message: Message):
    if not _authorized(message):
        return
    bot.reply_to(
        message,
        "Enkidu online.\n\n"
        "Ask me anything about stocks, the QV portfolio, or your system.\n"
        "Commands: /help /stats /refresh",
    )


@bot.message_handler(commands=["help"])
def cmd_help(message: Message):
    if not _authorized(message):
        return
    bot.reply_to(
        message,
        "Commands:\n"
        "  /start       — greeting\n"
        "  /help        — this message\n"
        "  /stats       — session + memory stats\n"
        "  /watchlist   — current QV top-25 picks\n"
        "  /performance — signal track record vs SPY\n"
        "  /history     — last 5 conversation exchanges\n"
        "  /refresh     — re-run QV data pipeline\n"
        "  /rate <text> — add written feedback on last response\n\n"
        "Examples:\n"
        "  top 10 undervalued stocks\n"
        "  compare HPQ and BBY on EV/EBIT\n"
        "  how has the QV model performed?\n"
        "  what is my GPU temperature\n"
        "  calculate CAGR if revenue grew from 10B to 18B over 6 years",
    )


@bot.message_handler(commands=["stats"])
def cmd_stats(message: Message):
    if not _authorized(message):
        return
    # Include memory stats if available
    _phase4_python = os.path.normpath(os.path.join(_here, "..", "phase4-memory", ".venv", "Scripts", "python.exe"))
    _bridge = os.path.normpath(os.path.join(_here, "..", "phase4-memory", "memory_bridge.py"))
    mem_stats = ""
    if os.path.exists(_phase4_python):
        import subprocess
        try:
            r = subprocess.run([_phase4_python, _bridge, "stats"], capture_output=True, text=True, timeout=8)
            if r.stdout.strip():
                mem_stats = f"\n{r.stdout.strip()}"
        except Exception:
            pass
    bot.reply_to(message, f"Queries this session: {_session['queries']}{mem_stats}")


@bot.message_handler(commands=["history"])
def cmd_history(message: Message):
    if not _authorized(message):
        return
    _phase4_python = os.path.normpath(os.path.join(_here, "..", "phase4-memory", ".venv", "Scripts", "python.exe"))
    _bridge = os.path.normpath(os.path.join(_here, "..", "phase4-memory", "memory_bridge.py"))
    if not os.path.exists(_phase4_python):
        bot.reply_to(message, "Memory not available.")
        return
    import subprocess
    try:
        # Use python_sandbox approach — call memory_store directly
        script = (
            "import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(sys.argv[0])));"
            "from memory_store import get_recent_exchanges;"
            "rows = get_recent_exchanges(5);"
            "[print(f\"{r['timestamp'][:16]}  {r['user'][:80]}\") for r in rows]"
        )
        r = subprocess.run(
            [_phase4_python, "-c", script],
            capture_output=True, text=True, timeout=8,
            cwd=os.path.normpath(os.path.join(_here, "..", "phase4-memory")),
        )
        text = r.stdout.strip() or "No history yet."
        bot.reply_to(message, f"Last 5 exchanges:\n\n{text}")
    except Exception as e:
        bot.reply_to(message, f"Could not retrieve history: {e}")


@bot.message_handler(commands=["performance"])
def cmd_performance(message: Message):
    if not _authorized(message):
        return
    status = bot.reply_to(message, "Fetching performance data...")
    try:
        _phase5 = os.path.normpath(os.path.join(_here, "..", "phase5-intelligence"))
        if _phase5 not in sys.path:
            sys.path.insert(0, _phase5)
        _phase2_tools = os.path.normpath(os.path.join(_here, "..", "phase2-tool-use", "tools"))
        if _phase2_tools not in sys.path:
            sys.path.insert(0, _phase2_tools)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "performance_tracker",
            os.path.join(_phase5, "performance_tracker.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Update returns then summarize
        mod.update_returns(verbose=False)
        text = mod.performance_report()
    except Exception as e:
        text = f"Could not load performance data: {e}"
    _safe_edit(message.chat.id, status.message_id, text[:4090])


@bot.message_handler(commands=["watchlist"])
def cmd_watchlist(message: Message):
    if not _authorized(message):
        return
    try:
        _phase5 = os.path.normpath(os.path.join(_here, "..", "phase5-intelligence"))
        if _phase5 not in sys.path:
            sys.path.insert(0, _phase5)
        _phase2_tools = os.path.normpath(os.path.join(_here, "..", "phase2-tool-use", "tools"))
        if _phase2_tools not in sys.path:
            sys.path.insert(0, _phase2_tools)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "signal_logger",
            os.path.join(_phase5, "signal_logger.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        snaps = mod.get_snapshot()
        if not snaps:
            bot.reply_to(message, "No watchlist yet. Signals are logged daily.")
            return
        lines = [f"QV Watchlist ({snaps[0]['snapshot_dt']}):\n"]
        for s in snaps[:15]:  # top 15 for readability
            flags = f"  [{s['quality_flags']}]" if s.get('quality_flags') else ""
            lines.append(
                f"#{s['rank']:2d} {s['ticker']:<6} {s.get('sector','')[:16]:<16} "
                f"EV/EBIT:{s.get('ev_ebit', 0):.1f}  VC:{s.get('value_composite', 0):.0f}{flags}"
            )
        bot.reply_to(message, "\n".join(lines))
    except Exception as e:
        bot.reply_to(message, f"Could not load watchlist: {e}")


@bot.message_handler(commands=["refresh"])
def cmd_refresh(message: Message):
    if not _authorized(message):
        return
    _phase2 = os.path.normpath(os.path.join(_here, "..", "phase2-tool-use"))
    if _phase2 not in sys.path:
        sys.path.insert(0, _phase2)
    try:
        from tools.edgar_screener import estimate_refresh_time  # noqa: E402
        est = estimate_refresh_time(force_redownload=True)
        bot.reply_to(
            message,
            f"QV pipeline refresh:\n"
            f"  Companies: {est['companies_to_fetch']}\n"
            f"  Estimated time: {est['total']}\n\n"
            f"Reply 'yes' to start.",
        )
        _awaiting_refresh[message.from_user.id] = True
    except Exception as e:
        bot.reply_to(message, f"Could not estimate refresh time: {e}")


# ---------------------------------------------------------------------------
# /rate command — store free-text feedback on the most recent exchange
# ---------------------------------------------------------------------------

@bot.message_handler(commands=["rate"])
def cmd_rate(message: Message):
    if not _authorized(message):
        return
    user_id = message.from_user.id
    eid = _last_eid.get(user_id, "")
    if not eid:
        bot.reply_to(message, "No recent response to rate. Ask me something first.")
        return
    # Strip the "/rate " prefix
    feedback = message.text.partition(" ")[2].strip()
    if not feedback:
        bot.reply_to(message, "Usage: /rate <your feedback>\nExample: /rate too verbose but accurate")
        return
    result = _mem(10, "feedback", eid, feedback)
    if result == "ok":
        bot.reply_to(message, "Feedback saved. This will shape future training.")
    else:
        bot.reply_to(message, f"Could not save feedback (exchange not found).")


# ---------------------------------------------------------------------------
# Inline keyboard callback — 👍 / 👎 rating buttons
# ---------------------------------------------------------------------------

@bot.callback_query_handler(func=lambda call: call.data.startswith("rate:"))
def handle_rating(call):
    if call.from_user.id != ALLOWED_USER_ID:
        bot.answer_callback_query(call.id, "Unauthorized.")
        return

    parts = call.data.split(":", 2)  # "rate", "+1/-1", "eid"
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "Malformed callback.")
        return

    _, rating_str, eid = parts
    rating = int(rating_str)
    label = "👍" if rating == 1 else "👎"

    result = _mem(10, "rate", eid, str(rating))
    if result == "ok":
        bot.edit_message_text(
            f"Rated {label}  |  Use /rate <text> to add detail.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
        )
        bot.answer_callback_query(call.id, f"Saved {label}")

        # Trigger auto-score in background if enabled
        if _AUTO_SCORE:
            user_id = call.from_user.id
            # Retrieve the exchange text for scoring
            threading.Thread(
                target=_auto_score_by_eid,
                args=(eid,),
                daemon=True,
            ).start()
    else:
        bot.answer_callback_query(call.id, "Could not save rating.")


def _auto_score_by_eid(eid: str) -> None:
    """Look up exchange text from DB and run auto-score."""
    try:
        import sqlite3 as _sq
        db_path = os.path.normpath(os.path.join(_here, "..", "phase4-memory", "memory.db"))
        conn = _sq.connect(db_path)
        row = conn.execute(
            "SELECT user_msg, asst_msg FROM exchanges WHERE id = ?", (eid,)
        ).fetchone()
        conn.close()
        if row:
            _auto_score_exchange(eid, row[0], row[1])
    except Exception as e:
        logger.debug(f"_auto_score_by_eid failed: {e}")


# ---------------------------------------------------------------------------
# Main message handler — runs the ReAct agent
# ---------------------------------------------------------------------------

@bot.message_handler(func=lambda m: True)
def handle_message(message: Message):
    try:
        _handle_message_inner(message)
    except Exception as e:
        logger.error(f"handle_message unhandled error: {e}", exc_info=True)


def _handle_message_inner(message: Message):
    if not _authorized(message):
        return

    user_id = message.from_user.id
    text = message.text.strip()
    if not text:
        return

    # --- Refresh confirmation ---
    if _awaiting_refresh.get(user_id):
        _awaiting_refresh[user_id] = False
        if text.lower() == "yes":
            status = bot.reply_to(message, "Running QV pipeline... (~2 hours)")
            _phase2 = os.path.normpath(os.path.join(_here, "..", "phase2-tool-use"))
            if _phase2 not in sys.path:
                sys.path.insert(0, _phase2)

            def _do_refresh():
                from tools.edgar_screener import refresh_data  # noqa: E402
                result = refresh_data(force_redownload=True)
                _safe_edit(
                    message.chat.id,
                    status.message_id,
                    f"Refresh complete.\n"
                    f"Status: {result.get('status')}\n"
                    f"Time: {result.get('elapsed', 'N/A')}",
                )

            threading.Thread(target=_do_refresh, daemon=True).start()
        else:
            bot.reply_to(message, "Refresh cancelled.")
        return

    # --- Run the ReAct agent ---
    status = bot.reply_to(message, "Thinking...")
    chat_id = message.chat.id
    status_id = status.message_id

    # Collect step updates from the agent thread, rate-limit Telegram edits
    step_updates: list[str] = []
    last_edit: list[float] = [0.0]
    answer: list[Optional[str]] = [None]
    done_event = threading.Event()

    def on_step(msg: str) -> None:
        step_updates.append(msg)

    def _run_agent():
        answer[0] = run_agent(text, on_step=on_step, save_memory=False)
        done_event.set()

    agent_thread = threading.Thread(target=_run_agent, daemon=True)
    agent_thread.start()

    # Poll for step updates while agent runs
    while not done_event.wait(timeout=0.5):
        if step_updates:
            now = time.monotonic()
            if now - last_edit[0] >= 1.2:   # max ~50 edits/min to stay under rate limit
                latest = step_updates[-1]
                step_updates.clear()
                last_edit[0] = now
                _safe_edit(chat_id, status_id, latest)

    # Send final answer
    final = answer[0] or "No answer returned."

    if len(final) <= 4096:
        _safe_edit(chat_id, status_id, final)
    else:
        # Replace status with first chunk, send rest as follow-ups
        _safe_edit(chat_id, status_id, final[:4090] + "\n[...]")
        remainder = final[4090:]
        while remainder:
            _safe_send(chat_id, remainder[:4096])
            remainder = remainder[4096:]

    _session["queries"] += 1

    # Save exchange and capture ID for rating
    eid = _save_exchange(text, final)
    if eid:
        _last_eid[user_id] = eid
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("👍", callback_data=f"rate:1:{eid}"),
            InlineKeyboardButton("👎", callback_data=f"rate:-1:{eid}"),
        )
        _safe_send(chat_id, "Rate this response:", reply_markup=markup)

        # Auto-score immediately if enabled (no need to wait for rating)
        if _AUTO_SCORE:
            threading.Thread(
                target=_auto_score_exchange,
                args=(eid, text, final),
                daemon=True,
            ).start()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _wait_for_network(host: str = "api.telegram.org", port: int = 443, timeout: int = 5) -> None:
    """Block until a TCP connection to Telegram's API succeeds (network is ready)."""
    import socket
    attempt = 0
    while True:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                if attempt > 0:
                    logger.info(f"Network ready after {attempt} attempt(s).")
                return
        except OSError:
            attempt += 1
            delay = min(attempt * 2, 30)
            logger.info(f"Network not ready (attempt {attempt}), retrying in {delay}s...")
            time.sleep(delay)


def main():
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set in .env")
        return
    if not ALLOWED_USER_ID:
        print("Error: TELEGRAM_ALLOWED_USER_ID not set in .env")
        return

    print("Enkidu Telegram bot online")
    print(f"Authorized user ID: {ALLOWED_USER_ID}")

    _wait_for_network()
    _lighting_init()

    print("Long-polling active — Ctrl+C to stop\n")

    # Outer retry loop: non_stop=True handles API/handler errors but
    # requests.exceptions.ConnectionError (WinError 10054 TLS reset) can
    # escape the polling thread and crash the process. Catch it here and
    # restart polling after a short back-off.
    while True:
        try:
            # long_polling_timeout=0: pure short-polling. Windows resets
            # long-lived TLS connections (WinError 10054), so we don't keep
            # the getUpdates connection open at all. Telegram responds
            # immediately with any pending updates or an empty list.
            bot.infinity_polling(timeout=10, long_polling_timeout=0, interval=1, skip_pending=True)
        except KeyboardInterrupt:
            print("\nBot stopped.")
            break
        except Exception as e:
            logger.warning(f"Polling crashed ({type(e).__name__}: {e}), restarting in 5s...")
            time.sleep(2)


if __name__ == "__main__":
    main()
