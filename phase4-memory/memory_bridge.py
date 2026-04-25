"""
memory_bridge.py — Thin CLI bridge so phase3-agents can call phase4 memory
without importing chromadb into the phase3 Python environment.

Called as a subprocess by the agent:
    python memory_bridge.py save  <user_msg> <assistant_msg>
    python memory_bridge.py retrieve <query>
    python memory_bridge.py search_docs <query>
    python memory_bridge.py stats

Outputs plain text to stdout. The agent reads stdout as the result.
"""

import sys
import os
import io

# Force UTF-8 stdout so Windows cp1252 terminal doesn't choke on em-dashes
# or other non-ASCII chars in indexed documents. Subprocess callers read raw
# bytes (capture_output=True) so encoding doesn't matter to them — this only
# affects direct terminal invocation on Windows.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

def main():
    if len(sys.argv) < 2:
        print("Usage: memory_bridge.py <command> [args...]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "save":
        from memory_store import save_exchange
        user_msg = sys.argv[2] if len(sys.argv) > 2 else ""
        asst_msg = sys.argv[3] if len(sys.argv) > 3 else ""
        eid = save_exchange(user_msg, asst_msg)
        print(f"saved:{eid}")

    elif cmd == "retrieve":
        from memory_store import retrieve_context
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        print(retrieve_context(query))

    elif cmd == "search_docs":
        from document_indexer import search_docs
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        print(search_docs(query))

    elif cmd == "stats":
        from memory_store import memory_stats
        from document_indexer import index_stats
        ms = memory_stats()
        ds = index_stats()
        print(f"Conversation memory: {ms['sqlite_exchanges']} exchanges, {ms['chroma_vectors']} vectors")
        print(f"Document index: {ds['document_chunks']} chunks")

    elif cmd == "rate":
        from memory_store import rate_exchange
        eid = sys.argv[2] if len(sys.argv) > 2 else ""
        rating = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        ok = rate_exchange(eid, rating)
        print("ok" if ok else "not_found")

    elif cmd == "feedback":
        from memory_store import add_user_feedback
        eid = sys.argv[2] if len(sys.argv) > 2 else ""
        text = sys.argv[3] if len(sys.argv) > 3 else ""
        ok = add_user_feedback(eid, text)
        print("ok" if ok else "not_found")

    elif cmd == "save_spoken":
        from speech_quality import attach_spoken_exchange
        user_msg = sys.argv[2] if len(sys.argv) > 2 else ""
        asst_msg = sys.argv[3] if len(sys.argv) > 3 else ""
        spoken_msg = sys.argv[4] if len(sys.argv) > 4 else ""
        response_mode = sys.argv[5] if len(sys.argv) > 5 else "spoken"
        voice_profile = sys.argv[6] if len(sys.argv) > 6 else ""
        ok = attach_spoken_exchange(user_msg, asst_msg, spoken_msg, response_mode, voice_profile)
        print("ok" if ok else "not_found")

    elif cmd == "speech_feedback":
        from speech_quality import record_speech_feedback
        exchange_id = sys.argv[2] if len(sys.argv) > 2 else ""
        feedback = sys.argv[3] if len(sys.argv) > 3 else ""
        corrected_text = sys.argv[4] if len(sys.argv) > 4 else ""
        issue_tags = sys.argv[5] if len(sys.argv) > 5 else ""
        user_msg = sys.argv[6] if len(sys.argv) > 6 else ""
        asst_msg = sys.argv[7] if len(sys.argv) > 7 else ""
        spoken_text = sys.argv[8] if len(sys.argv) > 8 else ""
        result = record_speech_feedback(exchange_id, feedback, corrected_text, issue_tags, user_msg, asst_msg, spoken_text)
        print(result)

    elif cmd == "speech_guidance":
        from speech_quality import retrieve_speech_guidance
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        print(retrieve_speech_guidance(query))

    elif cmd == "lexicon_add":
        from speech_quality import upsert_lexicon
        term = sys.argv[2] if len(sys.argv) > 2 else ""
        spoken = sys.argv[3] if len(sys.argv) > 3 else ""
        ipa = sys.argv[4] if len(sys.argv) > 4 else ""
        notes = sys.argv[5] if len(sys.argv) > 5 else ""
        source = sys.argv[6] if len(sys.argv) > 6 else "user"
        print(upsert_lexicon(term, spoken, ipa, notes, source))

    elif cmd == "lexicon_list":
        from speech_quality import list_lexicon
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        print(json.dumps(list_lexicon(query), ensure_ascii=False))

    elif cmd == "lexicon_map":
        from speech_quality import get_lexicon_map
        print(json.dumps(get_lexicon_map(), ensure_ascii=False))

    elif cmd == "export_spoken_lora":
        from speech_quality import export_spoken_lora_dataset
        output_path = sys.argv[2] if len(sys.argv) > 2 else ""
        print(export_spoken_lora_dataset(output_path or None))

    elif cmd == "finetune_report":
        from speech_quality import finetune_readiness_report
        print(json.dumps(finetune_readiness_report(), ensure_ascii=False))

    elif cmd == "add_score":
        from memory_store import add_auto_score
        eid = sys.argv[2] if len(sys.argv) > 2 else ""
        score_json = sys.argv[3] if len(sys.argv) > 3 else "{}"
        ok = add_auto_score(eid, score_json)
        print("ok" if ok else "not_found")

    elif cmd == "reindex":
        from document_indexer import index_path
        repo_root = os.path.normpath(os.path.join(_HERE, ".."))
        stats = index_path(repo_root, verbose=False)
        print(f"Reindexed: {stats['files_indexed']} files, {stats['chunks_added']} new chunks")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

if __name__ == "__main__":
    main()
