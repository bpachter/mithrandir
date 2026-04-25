from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from memory_store import _embed, _get_collection, _get_db


def _now() -> str:
    return datetime.now().isoformat()


def _ensure_exchange_columns(conn) -> None:
    existing = {r[1] for r in conn.execute("PRAGMA table_info(exchanges)").fetchall()}
    for col, defn in [
        ("spoken_msg", "TEXT"),
        ("response_mode", "TEXT"),
        ("voice_profile", "TEXT"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE exchanges ADD COLUMN {col} {defn}")


def _ensure_tables(conn) -> None:
    _ensure_exchange_columns(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lexicon (
            term TEXT PRIMARY KEY,
            spoken TEXT NOT NULL,
            ipa TEXT,
            notes TEXT,
            source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS speech_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exchange_id TEXT,
            timestamp TEXT NOT NULL,
            feedback TEXT NOT NULL,
            corrected_text TEXT,
            issue_tags TEXT,
            original_user TEXT,
            original_assistant TEXT,
            spoken_text TEXT
        )
        """
    )


def upsert_lexicon(term: str, spoken: str, ipa: str = "", notes: str = "", source: str = "user") -> dict:
    term = re.sub(r"\s+", " ", (term or "").strip())
    spoken = re.sub(r"\s+", " ", (spoken or "").strip())
    if not term or not spoken:
        raise ValueError("term and spoken are required")
    ts = _now()
    with _get_db() as conn:
        _ensure_tables(conn)
        conn.execute(
            """
            INSERT INTO lexicon (term, spoken, ipa, notes, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(term) DO UPDATE SET
                spoken = excluded.spoken,
                ipa = excluded.ipa,
                notes = excluded.notes,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (term, spoken, ipa.strip(), notes.strip(), source.strip(), ts, ts),
        )
    return {"term": term, "spoken": spoken, "ipa": ipa.strip(), "notes": notes.strip(), "source": source.strip()}


def list_lexicon(query: str = "", limit: int = 50) -> list[dict]:
    limit = max(1, min(limit, 200))
    like = f"%{(query or '').strip()}%"
    with _get_db() as conn:
        _ensure_tables(conn)
        if query.strip():
            rows = conn.execute(
                """
                SELECT term, spoken, ipa, notes, source, updated_at
                FROM lexicon
                WHERE term LIKE ? OR spoken LIKE ? OR notes LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT term, spoken, ipa, notes, source, updated_at
                FROM lexicon
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [
        {
            "term": r[0],
            "spoken": r[1],
            "ipa": r[2] or "",
            "notes": r[3] or "",
            "source": r[4] or "",
            "updated_at": r[5],
        }
        for r in rows
    ]


def get_lexicon_map() -> dict[str, dict]:
    return {entry["term"]: entry for entry in list_lexicon(limit=500)}


def attach_spoken_exchange(
    user_msg: str,
    assistant_msg: str,
    spoken_msg: str,
    response_mode: str = "spoken",
    voice_profile: str = "",
) -> bool:
    if not user_msg.strip() or not assistant_msg.strip() or not spoken_msg.strip():
        return False
    with _get_db() as conn:
        _ensure_tables(conn)
        row = conn.execute(
            """
            SELECT id FROM exchanges
            WHERE user_msg = ? AND asst_msg = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (user_msg, assistant_msg),
        ).fetchone()
        if not row:
            return False
        exchange_id = row[0]
        conn.execute(
            """
            UPDATE exchanges
            SET spoken_msg = ?, response_mode = ?, voice_profile = ?
            WHERE id = ?
            """,
            (spoken_msg, response_mode, voice_profile, exchange_id),
        )
    try:
        doc = (
            "[SPOKEN STYLE EXAMPLE]\n"
            f"User: {user_msg}\n"
            f"Visual answer: {assistant_msg}\n"
            f"Spoken answer: {spoken_msg}"
        )
        col = _get_collection()
        col.upsert(
            ids=[f"spoken:{exchange_id}"],
            embeddings=[_embed(doc)],
            documents=[doc],
            metadatas=[{"type": "spoken_example", "exchange_id": exchange_id, "timestamp": _now()}],
        )
    except Exception:
        pass
    return True


def _resolve_exchange_id(conn, exchange_id: str, user_msg: str, assistant_msg: str) -> Optional[str]:
    if exchange_id:
        row = conn.execute("SELECT id FROM exchanges WHERE id = ?", (exchange_id,)).fetchone()
        return row[0] if row else None
    if user_msg.strip() and assistant_msg.strip():
        row = conn.execute(
            """
            SELECT id FROM exchanges
            WHERE user_msg = ? AND asst_msg = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (user_msg, assistant_msg),
        ).fetchone()
        return row[0] if row else None
    return None


def record_speech_feedback(
    exchange_id: str = "",
    feedback: str = "",
    corrected_text: str = "",
    issue_tags: str = "",
    user_msg: str = "",
    assistant_msg: str = "",
    spoken_text: str = "",
) -> dict:
    feedback = (feedback or "").strip()
    corrected_text = (corrected_text or "").strip()
    if not feedback and not corrected_text:
        raise ValueError("feedback or corrected_text is required")

    ts = _now()
    with _get_db() as conn:
        _ensure_tables(conn)
        resolved_id = _resolve_exchange_id(conn, exchange_id, user_msg, assistant_msg)
        conn.execute(
            """
            INSERT INTO speech_feedback (
                exchange_id, timestamp, feedback, corrected_text, issue_tags,
                original_user, original_assistant, spoken_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_id,
                ts,
                feedback,
                corrected_text,
                (issue_tags or "").strip(),
                user_msg,
                assistant_msg,
                spoken_text,
            ),
        )
    try:
        doc = (
            "[SPEECH FEEDBACK]\n"
            f"Feedback: {feedback or '[none]'}\n"
            f"Corrected: {corrected_text or '[none]'}\n"
            f"Issues: {issue_tags or '[none]'}\n"
            f"User: {user_msg}\n"
            f"Assistant: {assistant_msg}\n"
            f"Spoken: {spoken_text}"
        )
        feedback_id = f"speech-feedback:{resolved_id or ts}"
        col = _get_collection()
        col.upsert(
            ids=[feedback_id],
            embeddings=[_embed(doc)],
            documents=[doc],
            metadatas=[{"type": "speech_feedback", "exchange_id": resolved_id or "", "timestamp": ts}],
        )
    except Exception:
        pass
    return {"ok": True, "exchange_id": resolved_id}


def retrieve_speech_guidance(query: str, limit: int = 4) -> str:
    terms = [t for t in re.findall(r"[A-Za-z0-9_+-]{3,}", query or "") if len(t) >= 3]
    with _get_db() as conn:
        _ensure_tables(conn)
        lexicon_rows = []
        for term in terms[:8]:
            lexicon_rows.extend(
                conn.execute(
                    "SELECT term, spoken, ipa, notes FROM lexicon WHERE lower(term) = lower(?) LIMIT 1",
                    (term,),
                ).fetchall()
            )
        feedback_rows = conn.execute(
            """
            SELECT feedback, corrected_text, issue_tags
            FROM speech_feedback
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (max(1, min(limit, 12)),),
        ).fetchall()

    lines: list[str] = []
    if lexicon_rows:
        lines.append("[SPEECH LEXICON]")
        for term, spoken, ipa, notes in lexicon_rows:
            suffix = []
            if ipa:
                suffix.append(f"IPA {ipa}")
            if notes:
                suffix.append(notes)
            extra = f" ({'; '.join(suffix)})" if suffix else ""
            lines.append(f"- {term} -> {spoken}{extra}")
    if feedback_rows:
        lines.append("[SPEECH FEEDBACK]")
        for feedback, corrected, tags in feedback_rows[:limit]:
            bits = []
            if feedback:
                bits.append(f"feedback={feedback}")
            if corrected:
                bits.append(f"preferred={corrected}")
            if tags:
                bits.append(f"issues={tags}")
            if bits:
                lines.append("- " + " | ".join(bits))
    return "\n".join(lines).strip()


def export_spoken_lora_dataset(output_path: Optional[str] = None) -> dict:
    export_dir = Path(__file__).parent / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(output_path) if output_path else export_dir / "spoken_style_lora.jsonl"

    with _get_db() as conn:
        _ensure_tables(conn)
        rows = conn.execute(
            """
            SELECT id, user_msg, asst_msg, spoken_msg, rating, user_feedback
            FROM exchanges
            WHERE spoken_msg IS NOT NULL AND trim(spoken_msg) != ''
            ORDER BY timestamp DESC
            """
        ).fetchall()
        corrections = {
            row[0]: row[1]
            for row in conn.execute(
                """
                SELECT exchange_id, corrected_text
                FROM speech_feedback
                WHERE corrected_text IS NOT NULL AND trim(corrected_text) != ''
                ORDER BY timestamp DESC
                """
            ).fetchall()
            if row[0]
        }

    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        for exchange_id, user_msg, asst_msg, spoken_msg, rating, user_feedback in rows:
            target = corrections.get(exchange_id, spoken_msg).strip()
            if not target:
                continue
            record = {
                "id": exchange_id,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Rewrite assistant answers into warm, natural, speech-first prose. "
                            "Avoid markdown, bullet lists, tool traces, and symbol-heavy phrasing. "
                            "Bias toward Gandalf-like calm, dignified explanation."
                        ),
                    },
                    {"role": "user", "content": user_msg},
                    {"role": "assistant", "content": target},
                ],
                "metadata": {
                    "source_answer": asst_msg,
                    "spoken_answer": spoken_msg,
                    "rating": rating,
                    "feedback": user_feedback or "",
                    "corrected": exchange_id in corrections,
                },
            }
            f.write(json.dumps(record, ensure_ascii=True) + "\n")
            count += 1

    return {"ok": True, "path": str(out_path), "examples": count}


def finetune_readiness_report() -> dict:
    with _get_db() as conn:
        _ensure_tables(conn)
        total_exchanges = conn.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0]
        spoken_examples = conn.execute("SELECT COUNT(*) FROM exchanges WHERE spoken_msg IS NOT NULL AND trim(spoken_msg) != ''").fetchone()[0]
        rated = conn.execute("SELECT COUNT(*) FROM exchanges WHERE rating IS NOT NULL").fetchone()[0]
        lexicon_entries = conn.execute("SELECT COUNT(*) FROM lexicon").fetchone()[0]
        speech_feedback = conn.execute("SELECT COUNT(*) FROM speech_feedback").fetchone()[0]
        corrected = conn.execute("SELECT COUNT(*) FROM speech_feedback WHERE corrected_text IS NOT NULL AND trim(corrected_text) != ''").fetchone()[0]

    readiness = "not_ready"
    if spoken_examples >= 50 and corrected >= 15 and lexicon_entries >= 10:
        readiness = "pilot_ready"
    if spoken_examples >= 200 and corrected >= 50 and lexicon_entries >= 25:
        readiness = "train_ready"

    return {
        "readiness": readiness,
        "counts": {
            "total_exchanges": total_exchanges,
            "spoken_examples": spoken_examples,
            "rated": rated,
            "lexicon_entries": lexicon_entries,
            "speech_feedback": speech_feedback,
            "corrected_feedback": corrected,
        },
        "next_steps": [
            "Collect more corrected spoken rewrites if corrected_feedback is low.",
            "Grow lexicon coverage for recurring symbols, tickers, and hardware terms.",
            "Re-export spoken_style_lora.jsonl before any LoRA run.",
            "Re-evaluate repo prompts and TTS behavior before fine-tuning the voice model.",
        ],
    }
