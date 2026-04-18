"""
scan_bmo_voice.py — Download a YouTube video, scan for clean high-pitched
solo-voice segments (BMO's range), rank them, and emit the top candidates.

Usage:
    python scan_bmo_voice.py <youtube_url> [--out bmo] [--top 5]

What it does:
    1. Downloads full audio with yt-dlp.
    2. Converts to mono 24 kHz float32 with ffmpeg.
    3. Splits into 1-second frames; computes per-frame:
         - RMS energy        (silence filter)
         - Fundamental F0    (via autocorrelation — high pitch = BMO)
         - Spectral flatness (low = tonal voice, high = noise/music)
         - Zero-crossing rate (low = voiced speech)
    4. Scores each frame; slides a 6-second window to find the cleanest run.
    5. Extracts the top-N windows, saves them to voices/bmo_candidate_*.wav.
    6. Transcribes each with Whisper and prints a ranked summary.
    7. Auto-selects the best candidate and saves as voices/<out>.wav + .txt.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

_HERE       = Path(__file__).parent
_VOICES_DIR = _HERE / "voices"
_FFMPEG_DIR = os.environ.get(
    "FFMPEG_DIR",
    r"C:\ffmpeg\bin\ffmpeg-master-latest-win64-gpl-shared\ffmpeg-master-latest-win64-gpl-shared\bin",
)
if os.path.isdir(_FFMPEG_DIR) and _FFMPEG_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")

_SR = 24000   # target sample rate (matches Kokoro / F5-TTS)

# ── BMO voice profile ─────────────────────────────────────────────────────────
# Niki Yang's BMO: warm, high-pitched, ~200-450 Hz fundamental.
# Reject frames where F0 is below 160 Hz (other characters, music bass).
_BMO_F0_MIN   = 160   # Hz — minimum fundamental
_BMO_F0_MAX   = 550   # Hz — maximum (avoid squeaks / artefacts)
_MIN_RMS      = 0.015 # silence threshold
_MAX_FLATNESS = 0.35  # spectral flatness — above this = noise / music
_MAX_ZCR      = 0.18  # zero-crossing rate — above this = fricatives / noise


def _run(cmd: list[str], **kw) -> None:
    print(">", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def download_audio(url: str, out_dir: Path) -> Path:
    # Prefer yt-dlp on PATH; fall back to running as a Python module (user installs)
    ytdlp_cmd = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if ytdlp_cmd:
        cmd_prefix = [ytdlp_cmd]
    else:
        # Check user Scripts directory directly
        user_scripts = Path(sys.executable).parent.parent / "Scripts" / "yt-dlp.exe"
        roaming = Path.home() / "AppData" / "Roaming" / "Python" / f"Python{sys.version_info.major}{sys.version_info.minor}" / "Scripts" / "yt-dlp.exe"
        if user_scripts.exists():
            cmd_prefix = [str(user_scripts)]
        elif roaming.exists():
            cmd_prefix = [str(roaming)]
        else:
            cmd_prefix = [sys.executable, "-m", "yt_dlp"]
    out_tpl = str(out_dir / "raw.%(ext)s")
    _run(cmd_prefix + ["-x", "--audio-format", "wav", "-o", out_tpl, url])
    for p in out_dir.iterdir():
        if p.stem == "raw":
            return p
    raise RuntimeError("yt-dlp finished but no raw audio found")


def convert_to_mono_float(src: Path, dst: Path) -> None:
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg not found — set FFMPEG_DIR in .env")
    _run([
        "ffmpeg", "-y", "-i", str(src),
        "-ac", "1", "-ar", str(_SR),
        "-sample_fmt", "f32le",
        "-f", "f32le", str(dst),
    ])


def load_f32(path: Path) -> np.ndarray:
    return np.frombuffer(path.read_bytes(), dtype=np.float32)


def _autocorr_f0(frame: np.ndarray, sr: int) -> float:
    """Estimate fundamental frequency via autocorrelation. Returns 0 if unvoiced."""
    n = len(frame)
    if n < 128:
        return 0.0
    # Hamming window
    windowed = frame * np.hamming(n)
    # Autocorrelation via FFT
    fft = np.fft.rfft(windowed, n=2 * n)
    acf = np.fft.irfft(fft * fft.conj()).real[:n]
    if acf[0] < 1e-10:
        return 0.0
    acf = acf / acf[0]
    # Search in F0 range
    lo = max(1, int(sr / _BMO_F0_MAX))
    hi = min(n - 1, int(sr / _BMO_F0_MIN))
    if lo >= hi:
        return 0.0
    peak_idx = lo + int(np.argmax(acf[lo:hi]))
    peak_val = acf[peak_idx]
    if peak_val < 0.35:   # not voiced enough
        return 0.0
    return float(sr) / float(peak_idx)


def _spectral_flatness(frame: np.ndarray) -> float:
    spec = np.abs(np.fft.rfft(frame * np.hamming(len(frame)))) + 1e-10
    gm = np.exp(np.mean(np.log(spec)))
    am = np.mean(spec)
    return float(gm / am)


def score_audio(audio: np.ndarray, sr: int, frame_sec: float = 0.5) -> np.ndarray:
    """Return a per-frame score array. Higher = more likely clean BMO voice."""
    frame_n = int(sr * frame_sec)
    n_frames = len(audio) // frame_n
    scores = np.zeros(n_frames)

    for i in range(n_frames):
        f = audio[i * frame_n : (i + 1) * frame_n]
        rms = float(np.sqrt(np.mean(f ** 2)))
        if rms < _MIN_RMS:
            continue  # silence

        f0  = _autocorr_f0(f, sr)
        flat = _spectral_flatness(f)
        zcr  = float(np.mean(np.abs(np.diff(np.sign(f)))) / 2)

        if f0 < _BMO_F0_MIN or f0 > _BMO_F0_MAX:
            continue  # wrong pitch range
        if flat > _MAX_FLATNESS:
            continue  # too noisy / music-like
        if zcr > _MAX_ZCR:
            continue  # too fricative / noisy

        # Score: high F0 in range, low flatness, decent energy
        pitch_score   = 1.0 - abs(f0 - 280) / 200   # peak around 280 Hz (BMO sweet-spot)
        clarity_score = 1.0 - flat / _MAX_FLATNESS
        energy_score  = min(1.0, rms / 0.12)
        scores[i] = max(0.0, pitch_score) * clarity_score * energy_score

    return scores


def find_best_windows(
    scores: np.ndarray,
    frame_sec: float,
    window_sec: float = 6.0,
    top_n: int = 5,
) -> list[tuple[float, float, float]]:
    """Slide a window over frame scores and return top-N non-overlapping windows.
    Returns list of (start_sec, end_sec, window_score).
    """
    win_frames = max(1, int(window_sec / frame_sec))
    n = len(scores)
    if n < win_frames:
        return []

    # Sliding sum
    cum = np.cumsum(np.concatenate([[0], scores]))
    win_scores = cum[win_frames:] - cum[:-win_frames]

    results: list[tuple[float, float, float]] = []
    used = np.zeros(n, dtype=bool)

    for _ in range(top_n):
        # Mask out already-used regions
        masked = win_scores.copy()
        for j in range(len(masked)):
            if np.any(used[j : j + win_frames]):
                masked[j] = -1.0
        best = int(np.argmax(masked))
        if masked[best] <= 0:
            break
        start_sec = best * frame_sec
        end_sec   = (best + win_frames) * frame_sec
        results.append((start_sec, end_sec, float(masked[best])))
        used[best : best + win_frames] = True

    return results


def extract_clip(src_raw: Path, start: float, duration: float, dst: Path) -> None:
    _run([
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-i", str(src_raw),
        "-t",  f"{duration:.3f}",
        "-ac", "1", "-ar", str(_SR),
        "-sample_fmt", "s16", str(dst),
    ])


def transcribe_wav(wav: Path) -> str:
    try:
        import soundfile as sf
        from faster_whisper import WhisperModel
    except ImportError:
        return "(whisper not available)"
    audio, sr = sf.read(str(wav), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    try:
        model = WhisperModel("base.en", device="cuda", compute_type="float16")
    except Exception:
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(audio, language="en", beam_size=5, vad_filter=True)
    return " ".join(s.text.strip() for s in segs).strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out",    default="bmo",   help="profile name (saved to voices/<out>.wav)")
    ap.add_argument("--top",    type=int, default=5, help="number of candidates to extract")
    ap.add_argument("--window", type=float, default=6.0, help="candidate window length in seconds")
    args = ap.parse_args()

    _VOICES_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)

        print("\n--- Step 1: Downloading audio ---")
        raw = download_audio(args.url, td_path)

        print("\n--- Step 2: Converting to mono float32 ---")
        pcm_path = td_path / "audio.f32"
        convert_to_mono_float(raw, pcm_path)
        audio = load_f32(pcm_path)
        duration_total = len(audio) / _SR
        print(f"Loaded {duration_total:.1f}s of audio at {_SR} Hz")

        print("\n--- Step 3: Scoring frames for BMO-like voice ---")
        frame_sec = 0.5
        scores = score_audio(audio, _SR, frame_sec=frame_sec)
        voiced_frac = float(np.mean(scores > 0))
        print(f"Scored {len(scores)} frames — {voiced_frac*100:.1f}% passed BMO filter")

        if voiced_frac < 0.01:
            print("WARNING: very few frames passed — the audio may be mostly music/effects.")
            print("Relaxing thresholds and retrying with wider F0 range...")
            # relax globals temporarily
            global _BMO_F0_MIN, _MAX_FLATNESS
            _BMO_F0_MIN   = 130
            _MAX_FLATNESS = 0.50
            scores = score_audio(audio, _SR, frame_sec=frame_sec)
            voiced_frac = float(np.mean(scores > 0))
            print(f"After relaxation: {voiced_frac*100:.1f}% of frames pass")

        print("\n--- Step 4: Finding best candidate windows ---")
        windows = find_best_windows(scores, frame_sec, window_sec=args.window, top_n=args.top)
        if not windows:
            print("No suitable windows found — try a different video or adjust thresholds.")
            sys.exit(1)

        print(f"Top {len(windows)} candidates:")
        for i, (s, e, sc) in enumerate(windows):
            print(f"  #{i+1}  {s:.1f}s – {e:.1f}s  (score={sc:.2f})")

        print("\n--- Step 5: Extracting and transcribing candidates ---")
        transcripts: list[str] = []
        candidate_wavs: list[Path] = []
        for i, (s, e, sc) in enumerate(windows):
            out_wav = _VOICES_DIR / f"{args.out}_candidate_{i+1}.wav"
            extract_clip(raw, s, e - s, out_wav)
            tx = transcribe_wav(out_wav)
            transcripts.append(tx)
            candidate_wavs.append(out_wav)
            print(f"  #{i+1}  {out_wav.name}: {tx[:100] or '(no speech detected)'}")

        print("\n--- Step 6: Selecting best candidate ---")
        # Prefer candidates with actual transcribed speech (not empty)
        best_idx = 0
        for i, tx in enumerate(transcripts):
            if len(tx) > 20:
                best_idx = i
                break

        best_wav = candidate_wavs[best_idx]
        final_wav = _VOICES_DIR / f"{args.out}.wav"
        final_txt = _VOICES_DIR / f"{args.out}.txt"

        import shutil as _shutil
        _shutil.copy2(best_wav, final_wav)
        tx = transcripts[best_idx]
        if tx:
            final_txt.write_text(tx + "\n", encoding="utf-8")
            print(f"Saved transcript: {tx[:120]}")

        print(f"\nBest candidate #{best_idx+1} saved as voices/{args.out}.wav")
        print(f"  All {len(candidate_wavs)} candidates saved as voices/{args.out}_candidate_*.wav")
        print(f"\nRestart the server and switch to the '{args.out}' voice profile to use it.")
        print("To enable F5-TTS cloning in .env: ENKIDU_STREAM_CLONE=1 (slower but more accurate)")


if __name__ == "__main__":
    main()
