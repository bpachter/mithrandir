from __future__ import annotations

import re
from typing import Any

try:
    from speech_quality import get_lexicon_map
except Exception:  # pragma: no cover - server can still run without memory extras
    get_lexicon_map = None


_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_WHITESPACE_RE = re.compile(r"\s+")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+")
_ORDERED_RE = re.compile(r"^\s*\d+[.)]\s+")
_MULTI_PUNCT_RE = re.compile(r"([.!?]){2,}")
_SYMBOL_EXPANSIONS = {
    "GPU": "G P U",
    "CPU": "C P U",
    "VRAM": "V RAM",
    "RAM": "RAM",
    "API": "A P I",
    "JSON": "Jason",
    "CUDA": "Coo Duh",
    "WS": "websocket",
    "TTS": "T T S",
    "STT": "S T T",
    "LLM": "L L M",
    "MoE": "mixture of experts",
    "Q4_K_M": "Q four K M",
    "Q8": "Q eight",
    "FP16": "F P sixteen",
    "BF16": "B F sixteen",
}


def _sentence_chunks(text: str) -> list[str]:
    pieces = [p.strip(" ,") for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    return pieces


def _replace_case_insensitive(text: str, source: str, target: str) -> str:
    escaped = re.escape(source)
    if re.fullmatch(r"[A-Za-z0-9 ]+", source):
        pattern = re.compile(rf"\b{escaped}\b", re.IGNORECASE)
    else:
        pattern = re.compile(escaped, re.IGNORECASE)
    return pattern.sub(target, text)


def _apply_lexicon(text: str) -> str:
    if get_lexicon_map is None:
        return text
    try:
        lexicon = get_lexicon_map()
    except Exception:
        return text

    for term in sorted(lexicon.keys(), key=len, reverse=True):
        spoken = (lexicon[term] or {}).get("spoken", "").strip()
        if spoken:
            text = _replace_case_insensitive(text, term, spoken)
    return text


def rewrite_for_speech(text: str, user_query: str = "") -> dict[str, Any]:
    original = (text or "").strip()
    if not original:
        return {"spoken_text": "", "notes": []}

    notes: list[str] = []
    spoken = original

    cleaned = _CODE_FENCE_RE.sub(" ", spoken)
    if cleaned != spoken:
        notes.append("removed_code_fences")
        spoken = cleaned

    cleaned = _MARKDOWN_LINK_RE.sub(r"\1", spoken)
    cleaned = _INLINE_CODE_RE.sub(r"\1", cleaned)
    cleaned = _URL_RE.sub("", cleaned)
    if cleaned != spoken:
        notes.append("flattened_markdown")
        spoken = cleaned

    lines: list[str] = []
    for raw_line in spoken.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        line = _BULLET_RE.sub("", line)
        line = _ORDERED_RE.sub("", line)
        if line.lower().startswith(("routing:", "local react", "tool call:", "observation:")):
            notes.append("removed_operator_trace")
            continue
        lines.append(line)
    spoken = ". ".join(lines)

    spoken = spoken.replace("&", " and ")
    spoken = re.sub(r"\bvs\.\b", "versus", spoken, flags=re.IGNORECASE)
    spoken = re.sub(r"\be\.g\.\b", "for example", spoken, flags=re.IGNORECASE)
    spoken = re.sub(r"\bi\.e\.\b", "that is", spoken, flags=re.IGNORECASE)
    spoken = re.sub(r"\bRTX\s*4090\b", "R T X 4090", spoken, flags=re.IGNORECASE)

    for symbol, expanded in _SYMBOL_EXPANSIONS.items():
        spoken = _replace_case_insensitive(spoken, symbol, expanded)

    spoken = _apply_lexicon(spoken)
    spoken = re.sub(r"\(([^)]*)\)", lambda m: f", {m.group(1)}," if len(m.group(1).split()) <= 6 else "", spoken)
    spoken = spoken.replace(";", ". ")
    spoken = spoken.replace(":", ". ")
    spoken = spoken.replace("/", " slash ")
    spoken = _MULTI_PUNCT_RE.sub(r"\1", spoken)
    spoken = _WHITESPACE_RE.sub(" ", spoken).strip(" ,")

    sentences = []
    for chunk in _sentence_chunks(spoken):
        if len(chunk) < 120:
            sentences.append(chunk)
            continue
        mid = chunk.rfind(",", 0, 120)
        if mid > 40:
            sentences.extend([chunk[:mid].strip(), chunk[mid + 1 :].strip()])
        else:
            sentences.append(chunk)

    spoken = ". ".join(part for part in sentences if part).strip()
    if spoken and spoken[-1] not in ".!?":
        spoken += "."

    if user_query and any(term in user_query.lower() for term in ["spell", "pronounce", "say"]):
        notes.append("speech_query_grounded")

    return {"spoken_text": spoken, "notes": notes}
