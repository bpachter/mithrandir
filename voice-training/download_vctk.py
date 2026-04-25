"""
download_vctk.py — Download VCTK corpus and extract British male RP speakers.

VCTK is the University of Edinburgh Voice Cloning Toolkit corpus:
  - 109 speakers, many British, CC BY 4.0 license
  - ~400 sentences per speaker at studio quality
  - Each speaker has accent/region info in speaker-info.txt

We filter for English male speakers with Southern/RP British accents —
the group most likely to approximate the deep, authoritative RP baritone
we want for Mithrandir's voice.

Usage:
    python download_vctk.py [--out-dir ./vctk_data]

Outputs:
    vctk_data/
        wavs/          filtered WAV files (renamed to spkr_sentence.wav)
        transcripts/   matching .txt files
        speaker_info.csv
"""

import argparse
import csv
import io
import os
import re
import shutil
import tarfile
import urllib.request
import warnings
import zipfile
from pathlib import Path

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", message="Unverified HTTPS")

_SESSION = requests.Session()
_SESSION.verify = False
_SESSION.headers.update({"User-Agent": "Mozilla/5.0", "Connection": "close"})

# Official Edinburgh DataShare source — no authentication required, CC BY 4.0
VCTK_URL = "https://datashare.ed.ac.uk/bitstream/handle/10283/3443/VCTK-Corpus-0.92.zip?sequence=2&isAllowed=y"

# VCTK speaker info — accent key: "English" = RP/Southern British for our purposes.
# Male speakers with English (RP-adjacent) accent in VCTK-0.92.
# Source: speaker-info.txt from the corpus.
# We pick the ones most likely to have deeper, more RP voices based on
# region (London / South England) where noted, excluding Scottish/Irish/Northern.
TARGET_SPEAKERS = {
    # id   : (gender, accent_note)
    "p237": ("M", "English"),
    "p252": ("M", "English"),
    "p259": ("M", "English"),
    "p260": ("M", "English"),
    "p284": ("M", "English"),
    "p285": ("M", "English"),
    "p286": ("M", "English"),
    "p287": ("M", "English"),
    "p292": ("M", "English"),
    "p298": ("M", "English"),
    "p302": ("M", "English"),
    "p304": ("M", "English"),
    "p326": ("M", "English"),
    "p334": ("M", "English"),
    "p347": ("M", "English"),
    "p360": ("M", "English"),
    "p362": ("M", "English"),
    "p374": ("M", "English"),
    "p376": ("M", "English"),
}


def _download(url: str, dest: Path, desc: str) -> None:
    print(f"Downloading {desc}")
    print(f"  URL: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _SESSION.get(url, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    mb  = downloaded // (1 << 20)
                    print(f"\r  {pct}%  ({mb} MB / {total // (1<<20)} MB)", end="", flush=True)
    print(f"\r  done ({dest.stat().st_size // (1<<20)} MB)          ")


def _extract_archive(archive: Path, out_dir: Path, speakers: set) -> dict[str, list[Path]]:
    """Extract target-speaker WAVs and txt transcripts from the VCTK zip/tar archive."""
    print(f"Extracting {archive.name} (filtering to {len(speakers)} speakers)...")
    out_dir.mkdir(parents=True, exist_ok=True)
    found: dict[str, list[Path]] = {s: [] for s in speakers}

    # txt files go to out_dir.parent/txt/<speaker>/
    txt_root = out_dir.parent / "txt"

    def _should_extract(parts):
        """Return (spkr, is_wav, is_txt) or (None, False, False)."""
        for p in parts:
            if re.match(r'^p\d{3}$', p):
                # audio: in wav48_silence_trimmed or wav48
                is_wav = any(x in parts for x in ("wav48_silence_trimmed", "wav48"))
                is_txt = "txt" in parts
                return p, is_wav, is_txt
        return None, False, False

    suffix = archive.suffix.lower()
    if suffix == ".zip":
        import zipfile
        with zipfile.ZipFile(archive, "r") as zf:
            members = zf.infolist()
            total = len(members)
            for i, m in enumerate(members):
                if i % 5000 == 0:
                    print(f"  scanning {i}/{total}...", end="\r", flush=True)
                if m.is_dir():
                    continue
                parts = Path(m.filename).parts
                spkr, is_wav, is_txt = _should_extract(parts)
                if spkr not in speakers:
                    continue
                if is_wav:
                    dest = out_dir / spkr / Path(m.filename).name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(zf.read(m.filename))
                    found[spkr].append(dest)
                elif is_txt:
                    dest = txt_root / spkr / Path(m.filename).name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(zf.read(m.filename))
    else:
        with tarfile.open(archive, "r:gz") as tf:
            members = tf.getmembers()
            total = len(members)
            for i, m in enumerate(members):
                if i % 5000 == 0:
                    print(f"  scanning {i}/{total}...", end="\r", flush=True)
                if not m.isfile():
                    continue
                parts = Path(m.name).parts
                spkr, is_wav, is_txt = _should_extract(parts)
                if spkr not in speakers:
                    continue
                f = tf.extractfile(m)
                if not f:
                    continue
                if is_wav:
                    dest = out_dir / spkr / Path(m.name).name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(f.read())
                    found[spkr].append(dest)
                elif is_txt:
                    dest = txt_root / spkr / Path(m.name).name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(f.read())
    print()
    return found


def _fetch_transcripts(vctk_txt_url: str, out_dir: Path) -> dict[str, dict[str, str]]:
    """Download the VCTK txt transcripts from the official source."""
    # Transcripts are in txt/<speaker>/<speaker>_NNN.txt
    # We'll use the HF dataset which includes them.
    # For offline usage, return empty and we'll fall back to PROMPTS.txt.
    return {}


def _load_prompts(prompts_file: Path) -> dict[str, str]:
    """Load sentence ID → text from VCTK's prompts file."""
    mapping = {}
    if not prompts_file.exists():
        return mapping
    with prompts_file.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                mapping[parts[0]] = parts[1]
    return mapping


def prepare_training_list(
    wav_dir: Path,
    txt_dir: Path,
    speakers: set,
    out_dir: Path,
) -> Path:
    """Create filelist.txt in StyleTTS2 format: path|speaker_id|text"""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    speaker_ids = {s: i for i, s in enumerate(sorted(speakers))}

    for spkr in sorted(speakers):
        spkr_wav = wav_dir / spkr
        spkr_txt = txt_dir / spkr
        if not spkr_wav.exists():
            continue
        for wav_file in sorted(spkr_wav.glob("*.wav")):
            stem = wav_file.stem
            # strip _mic1 / _mic2 suffix that VCTK appends
            base = re.sub(r"_mic\d$", "", stem)
            txt_file = spkr_txt / f"{base}.txt"
            if not txt_file.exists():
                continue
            text = txt_file.read_text(encoding="utf-8").strip()
            if not text:
                continue
            rows.append(f"{wav_file}|{speaker_ids[spkr]}|{text}\n")

    out_file = out_dir / "filelist.txt"
    out_file.write_text("".join(rows), encoding="utf-8")
    print(f"Wrote {len(rows)} entries to {out_file}")
    return out_file


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="./vctk_data", help="Output directory")
    ap.add_argument("--skip-download", action="store_true",
                    help="Skip download if archive already exists")
    args = ap.parse_args()

    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    archive = out / "VCTK-Corpus-0.92.zip"

    if not args.skip_download or not archive.exists():
        print("=" * 60)
        print("VCTK Corpus Download")
        print("License: CC BY 4.0 — free for research and commercial use")
        print("Size: ~11 GB compressed")
        print("=" * 60)
        _download(VCTK_URL, archive, "VCTK-Corpus-0.92 (Edinburgh DataShare)")

    speakers = set(TARGET_SPEAKERS.keys())
    wav_out = out / "wavs_raw"
    found = _extract_archive(archive, wav_out, speakers)

    total_files = sum(len(v) for v in found.values())
    print(f"\nExtracted {total_files} audio files across {len(found)} speakers:")
    for spkr, files in sorted(found.items()):
        print(f"  {spkr}: {len(files)} clips")

    print("\nDone. Run prepare_training_data.py next to resample and build filelists.")


if __name__ == "__main__":
    main()
