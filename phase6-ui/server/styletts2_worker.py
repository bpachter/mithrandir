"""
styletts2_worker.py — StyleTTS2 inference worker for Mithrandir's fine-tuned voice.

Protocol (same as f5tts_worker.py):
  stdin:  {"text": "...", "voice_path": "/path/to/ref.wav"}
  stdout: {"ok": true, "path": "/tmp/xxx.wav"}
          {"ok": false, "error": "..."}
  Prints "READY" after model load.

Requires:
  - voice-training/styletts2_repo/ (cloned StyleTTS2 repo)
  - voice-training/pretrained/StyleTTS2-LibriTTS/epochs_2nd_00020.pth (base checkpoint)
  - voice-training/logs/mithrandir_voice/epoch_*.pth (fine-tuned checkpoint, preferred)
  - A reference WAV at voice-training/reference_mithrandir.wav (or passed via voice_path)

Reference audio must be 24 kHz mono WAV from a British RP male VCTK speaker.
Run: python install_mithrandir_voice.py <clip.wav> to set up the reference.
"""

import io
import json
import os
import sys
import tempfile
from pathlib import Path

_HERE       = Path(__file__).parent
_TRAINING   = _HERE.parent.parent / "voice-training"
_REPO       = _TRAINING / "styletts2_repo"
_PRETRAINED = _TRAINING / "pretrained" / "StyleTTS2-LibriTTS"
_LOGS       = _TRAINING / "logs" / "mithrandir_elevenlabs"
_DEFAULT_REF = _TRAINING / "reference_mithrandir.wav"

if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

os.chdir(str(_REPO))  # StyleTTS2 expects to be run from its own directory


def _find_checkpoint() -> Path:
    """Return the best fine-tuned checkpoint, or the base pretrained model."""
    if _LOGS.exists():
        # epoch_2nd_00039 = epoch 40, val 0.365 — best saved checkpoint from Apr 26 run
        for name in ["epoch_2nd_00039.pth", "epoch_2nd_00044.pth", "epoch_2nd_00094.pth"]:
            preferred = _LOGS / name
            if preferred.exists():
                return preferred
        ckpts = sorted(_LOGS.glob("epoch_2nd_*.pth"))
        if ckpts:
            return ckpts[-1]
    base = _PRETRAINED / "epochs_2nd_00020.pth"
    if base.exists():
        return base
    raise FileNotFoundError(
        "No StyleTTS2 checkpoint found.\n"
        f"  Fine-tuned: {_LOGS}/epoch_*.pth\n"
        f"  Base: {base}\n"
        "Run voice-training/train.bat first."
    )


def _load_model(checkpoint: Path):
    """Load StyleTTS2 model and return (model, model_params, sampler, phonemizer, cleaner, device)."""
    import torch
    import yaml
    from munch import Munch
    from models import build_model, load_ASR_models, load_F0_models
    from utils import recursive_munch
    from Utils.PLBERT.util import load_plbert
    from text_utils import TextCleaner
    from Modules.diffusion.sampler import DiffusionSampler, ADPM2Sampler, KarrasSchedule
    import phonemizer as ph_lib

    device = "cuda" if torch.cuda.is_available() else "cpu"

    config_path = _PRETRAINED / "config.yml"
    if not config_path.exists():
        raise FileNotFoundError(f"StyleTTS2 config not found: {config_path}")
    config = yaml.safe_load(open(config_path))

    print(f"Loading StyleTTS2 checkpoint: {checkpoint.name}", file=sys.stderr, flush=True)

    text_aligner    = load_ASR_models(config["ASR_path"], config["ASR_config"])
    pitch_extractor = load_F0_models(config["F0_path"])
    plbert          = load_plbert(config["PLBERT_dir"])

    model_params = recursive_munch(config["model_params"])
    model = build_model(model_params, text_aligner, pitch_extractor, plbert)

    params_whole = torch.load(str(checkpoint), map_location="cpu")
    params = params_whole.get("net", params_whole)
    for key in model:
        if key in params:
            try:
                model[key].load_state_dict(params[key])
            except Exception:
                from collections import OrderedDict
                state = OrderedDict((k[7:] if k.startswith("module.") else k, v)
                                    for k, v in params[key].items())
                model[key].load_state_dict(state, strict=False)
        model[key].eval().to(device)

    sampler = DiffusionSampler(
        model.diffusion.diffusion,
        sampler=ADPM2Sampler(),
        sigma_schedule=KarrasSchedule(sigma_min=0.0001, sigma_max=3.0, rho=9.0),
        clamp=False,
    )

    from phonemizer.backend.espeak.espeak import EspeakWrapper
    _espeak_lib = r"C:\Program Files\eSpeak NG\libespeak-ng.dll"
    EspeakWrapper.set_library(_espeak_lib)

    global_phonemizer = ph_lib.backend.EspeakBackend(
        language="en-us", preserve_punctuation=True, with_stress=True
    )
    cleaner = TextCleaner()

    return model, model_params, sampler, global_phonemizer, cleaner, device


def _compute_style(ref_path: str, model, device: str) -> "torch.Tensor":
    import torch
    import librosa
    import torchaudio
    import numpy as np

    to_mel = torchaudio.transforms.MelSpectrogram(
        n_mels=80, n_fft=2048, win_length=1200, hop_length=300
    )
    mean, std = -4, 4

    wave, sr = librosa.load(ref_path, sr=24000)
    audio, _ = librosa.effects.trim(wave, top_db=30)
    mel = to_mel(torch.from_numpy(audio).float())
    mel = (torch.log(1e-5 + mel.unsqueeze(0)) - mean) / std
    mel = mel.to(device)

    with torch.no_grad():
        ref_s = model.style_encoder(mel.unsqueeze(1))
        ref_p = model.predictor_encoder(mel.unsqueeze(1))
    return torch.cat([ref_s, ref_p], dim=1)


def _synthesize(
    text: str,
    ref_s,
    model,
    model_params,
    sampler,
    global_phonemizer,
    cleaner,
    device: str,
    alpha: float = 0.3,
    beta: float  = 0.7,
    diffusion_steps: int = 3,
) -> bytes:
    import io
    import torch
    import numpy as np
    import soundfile as sf
    from nltk.tokenize import word_tokenize

    def length_to_mask(lengths):
        mask = torch.arange(lengths.max()).unsqueeze(0).expand(lengths.shape[0], -1).type_as(lengths)
        return torch.gt(mask + 1, lengths.unsqueeze(1))

    text = text.strip()
    ps = global_phonemizer.phonemize([text])
    ps = word_tokenize(ps[0])
    ps = " ".join(ps)
    tokens = cleaner(ps)
    tokens.insert(0, 0)
    tokens = torch.LongTensor(tokens).to(device).unsqueeze(0)

    with torch.no_grad():
        input_lengths = torch.LongTensor([tokens.shape[-1]]).to(device)
        text_mask = length_to_mask(input_lengths).to(device)

        t_en     = model.text_encoder(tokens, input_lengths, text_mask)
        bert_dur = model.bert(tokens, attention_mask=(~text_mask).int())
        d_en     = model.bert_encoder(bert_dur).transpose(-1, -2)

        s_pred = sampler(
            noise=torch.randn((1, 256)).unsqueeze(1).to(device),
            embedding=bert_dur,
            embedding_scale=1,
            features=ref_s,
            num_steps=diffusion_steps,
        ).squeeze(1)

        s   = beta  * s_pred[:, 128:] + (1 - beta)  * ref_s[:, 128:]
        ref = alpha * s_pred[:, :128] + (1 - alpha) * ref_s[:, :128]

        d = model.predictor.text_encoder(d_en, s, input_lengths, text_mask)
        x, _ = model.predictor.lstm(d)
        duration = torch.sigmoid(model.predictor.duration_proj(x)).sum(axis=-1)
        pred_dur = torch.round(duration.squeeze()).clamp(min=1)

        pred_aln = torch.zeros(input_lengths, int(pred_dur.sum().data))
        c = 0
        for i in range(pred_aln.size(0)):
            pred_aln[i, c:c + int(pred_dur[i].data)] = 1
            c += int(pred_dur[i].data)

        en = d.transpose(-1, -2) @ pred_aln.unsqueeze(0).to(device)
        if model_params.decoder.type == "hifigan":
            en_new = torch.zeros_like(en)
            en_new[:, :, 0] = en[:, :, 0]
            en_new[:, :, 1:] = en[:, :, :-1]
            en = en_new

        F0_pred, N_pred = model.predictor.F0Ntrain(en, s)

        asr = t_en @ pred_aln.unsqueeze(0).to(device)
        if model_params.decoder.type == "hifigan":
            asr_new = torch.zeros_like(asr)
            asr_new[:, :, 0] = asr[:, :, 0]
            asr_new[:, :, 1:] = asr[:, :, :-1]
            asr = asr_new

        out = model.decoder(asr, F0_pred, N_pred, ref.squeeze().unsqueeze(0))

    audio = out.squeeze().cpu().numpy()[..., :-50]
    audio = audio / (np.max(np.abs(audio)) + 1e-8)
    buf = io.BytesIO()
    sf.write(buf, audio, 24000, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _find_default_ref() -> str | None:
    """Find a usable reference audio: explicit > reference_mithrandir.wav > first training wav."""
    if _DEFAULT_REF.exists():
        return str(_DEFAULT_REF)
    for wav_dir in [
        _TRAINING / "training_data" / "wavs",
        _TRAINING / "elevenlabs_data" / "wavs",
    ]:
        if wav_dir.exists():
            wavs = list(wav_dir.rglob("*.wav"))
            if wavs:
                return str(sorted(wavs)[0])
    return None


def main():
    # Ensure NLTK punkt tokenizer is available
    try:
        import nltk
        try:
            nltk.data.find("tokenizers/punkt")
        except LookupError:
            print("Downloading NLTK punkt tokenizer...", file=sys.stderr, flush=True)
            nltk.download("punkt", quiet=True)
            nltk.download("punkt_tab", quiet=True)
    except ImportError:
        pass

    checkpoint = _find_checkpoint()
    model, model_params, sampler, global_phonemizer, cleaner, device = _load_model(checkpoint)

    default_ref = _find_default_ref()
    cached_ref_path = None
    cached_ref_s = None

    if default_ref:
        print(f"Default reference: {Path(default_ref).name}", file=sys.stderr, flush=True)
        cached_ref_path = default_ref
        cached_ref_s = _compute_style(default_ref, model, device)
    else:
        print("WARNING: No reference audio found — voice_path required in each request",
              file=sys.stderr, flush=True)

    print("READY", flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req  = json.loads(line)
            text = req.get("text", "").strip()
            if not text:
                print(json.dumps({"ok": False, "error": "empty text"}), flush=True)
                continue

            vpath = req.get("voice_path") or default_ref
            if not vpath or not Path(vpath).exists():
                print(json.dumps({"ok": False, "error": "no reference audio available"}), flush=True)
                continue

            if vpath != cached_ref_path:
                cached_ref_s    = _compute_style(vpath, model, device)
                cached_ref_path = vpath

            wav_bytes = _synthesize(
                text, cached_ref_s, model, model_params,
                sampler, global_phonemizer, cleaner, device,
            )
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                out_path = f.name
            print(json.dumps({"ok": True, "path": out_path}), flush=True)

        except Exception:
            import traceback
            print(json.dumps({"ok": False, "error": traceback.format_exc()[-600:]}), flush=True)


if __name__ == "__main__":
    main()
