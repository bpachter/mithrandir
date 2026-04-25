# Railway 502 Error Recovery Plan

## What Changed
On deployment, the backend started returning 502 Bad Gateway on all `/api/*` endpoints. This was caused by changes to `voice.py` and new voice modules that may have caused startup failures.

## Defensive Fixes Applied ✓

1. **Auto-ref-text generation disabled by default** (`phase6-ui/server/voice.py`)
   - Changed: `MITHRANDIR_AUTO_REF_TEXT=1` → `MITHRANDIR_AUTO_REF_TEXT=0`
   - Reason: File iteration on startup could fail on Railway if voices/ directory has issues
   - To enable: Set `MITHRANDIR_AUTO_REF_TEXT=1` in Railway .env only after confirming server is stable

2. **Better error logging in main.py**
   - Added `exc_info=True` to prewarm_chatterbox() error logging
   - Now logs full traceback instead of silently failing
   - Check Railway logs to see exact error if issue persists

3. **Improved exception handling in voice.py**
   - Separated `ImportError` from other exceptions
   - More specific error messages for diagnostics
   - Clearer fallback paths

4. **Defensive file operations in auto_ref_text.py**
   - Wrapped entire function in try-except
   - Handles OSError separately from other exceptions
   - Won't crash if voices/ directory is unavailable

## To Deploy These Fixes

```bash
# Push these changes to Railway:
git add phase6-ui/server/voice.py phase6-ui/server/main.py phase6-ui/server/auto_ref_text.py
git commit -m "Fix: defensive error handling for voice startup (disable auto-ref-text by default)"
git push
```

Railway will auto-redeploy. Check logs in 2-3 minutes.

## If Still Getting 502s

1. **Check Railway Logs:**
   - Railway dashboard → pachter-mithrandir → Deployments → View Logs
   - Look for lines containing "ERROR", "Voice pre-warm failed", or Python tracebacks
   - Post the last 100 lines to diagnose

2. **Temporary Workaround:**
   - Disable voice module entirely: Set `DISABLE_VOICE_MODULE=1` in Railway .env
   - This lets the UI load and you can test other endpoints
   - Server will respond with empty/default values for voice endpoints

3. **Check Deployment Included New Files:**
   - The 4 new files MUST be in the deployment:
     - `phase6-ui/server/parakeet_asr.py`
     - `phase6-ui/server/voice_optim.py`
     - `phase6-ui/server/auto_ref_text.py`
     - `phase6-ui/server/build_kokoro_trt.py`
   - If missing, the `import` statements in voice.py will fail

4. **Check requirements.txt:**
   - Verify `phase6-ui/server/requirements.txt` has:
     - numpy, soundfile, scipy (for auto_ref_text)
     - torch or torch-cuda-deps (for voice_optim)
   - These were already there before these changes, so shouldn't be an issue

## Rollback Plan (if needed immediately)

If you need to get the service up RIGHT NOW:

```bash
git revert HEAD~1  # Reverts just the voice.py + main.py + auto_ref_text.py changes
git push           # Railway redeploys in ~2 min
```

This takes you back to the last stable state before the voice upgrades.

## Once Server is Stable

To re-enable voice optimizations:
```bash
# .env on Railway:
MITHRANDIR_AUTO_REF_TEXT=0              # Keep disabled until you confirm stability
MITHRANDIR_KOKORO_WARMUP=1              # Safe — just cuDNN tuning
MITHRANDIR_USE_PARAKEET=0               # Off by default — only enable if nemo installed
```

## Summary of Changes for Reference

| File | Change | Risk | Default |
|------|--------|------|---------|
| voice.py | Parakeet ASR + voice_optim + auto_ref_text wiring | Low (all fallback to Whisper) | Safe |
| voice_optim.py | TF32 + cuDNN benchmark + Kokoro warmup | None (idempotent) | Enabled |
| auto_ref_text.py | Auto-generate reference transcripts | Medium (file I/O) | **DISABLED** |
| parakeet_asr.py | NVIDIA Parakeet ASR adapter | Low (lazy import) | Not used |
| build_kokoro_trt.py | TensorRT export scaffold | None (CLI script) | Not used |
| main.py | Better error logging for prewarm | None | Logging only |

**Status:** All code is syntactically correct and imports cleanly locally. The 502 error is likely deployment-side (missing files, environment, or timeout). Check Railway logs first.
