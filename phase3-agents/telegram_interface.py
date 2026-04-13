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
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from dotenv import load_dotenv
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
import threading
import telebot
import telebot.apihelper as _apihelper
from telebot.types import Message

load_dotenv()

# Monkey-patch telebot's session factory to fix WinError 10054 (TLS 1.3 reset on Windows).
# Forces TLS 1.2, disables cert verification and hostname checking.
# Safe on a personal home network connecting to api.telegram.org.

class _TLS12Adapter(HTTPAdapter):
    """Forces TLS 1.2 to avoid Windows TLS 1.3 handshake resets (WinError 10054)."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context(ssl_minimum_version=ssl.TLSVersion.TLSv1_2,
                                     ssl_maximum_version=ssl.TLSVersion.TLSv1_2)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)

_tls = threading.local()

def _patched_session(reset=False):
    if reset or not hasattr(_tls, 's'):
        s = requests.Session()
        s.verify = False
        s.mount("https://", _TLS12Adapter())
        _tls.s = s
    return _tls.s

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

# ---------------------------------------------------------------------------
# Bot + session state
# ---------------------------------------------------------------------------

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# Simple session counter (in-memory, per bot process)
_session = {"queries": 0}

# Per-user flag: are we waiting for refresh confirmation?
_awaiting_refresh: dict[int, bool] = {}


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
        "  /start   — greeting\n"
        "  /help    — this message\n"
        "  /stats   — session query count\n"
        "  /refresh — re-run QV pipeline\n\n"
        "Examples:\n"
        "  top 5 undervalued stocks\n"
        "  compare NUE and CLF on EV/EBIT\n"
        "  what is my GPU temperature\n"
        "  calculate CAGR if revenue grew from 10B to 18B over 6 years",
    )


@bot.message_handler(commands=["stats"])
def cmd_stats(message: Message):
    if not _authorized(message):
        return
    bot.reply_to(message, f"Queries this session: {_session['queries']}")


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
# Main message handler — runs the ReAct agent
# ---------------------------------------------------------------------------

@bot.message_handler(func=lambda m: True)
def handle_message(message: Message):
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
        answer[0] = run_agent(text, on_step=on_step)
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
            bot.send_message(chat_id, remainder[:4096])
            remainder = remainder[4096:]

    _session["queries"] += 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set in .env")
        return
    if not ALLOWED_USER_ID:
        print("Error: TELEGRAM_ALLOWED_USER_ID not set in .env")
        return

    print("Enkidu Telegram bot online")
    print(f"Authorized user ID: {ALLOWED_USER_ID}")
    print("Long-polling active — Ctrl+C to stop\n")

    # none_stop=True: keep retrying on transient network errors
    bot.infinity_polling(timeout=20, long_polling_timeout=15, none_stop=True, interval=3)


if __name__ == "__main__":
    main()
