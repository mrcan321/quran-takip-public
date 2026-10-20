"""Whisper modellerinin 5sn chunk'larda davranisini test et."""
import sys, time, warnings
from pathlib import Path
import numpy as np, soundfile as sf

warnings.filterwarnings("ignore")
SAMPLE_RATE = 16000
CHUNK_SAMPLES = SAMPLE_RATE * 5

# Hicr testindeki recording (kullanildiginda dolu) veya Rahman kaydi
WAV = Path.home() / "projects/quran-asr/server/recordings/session_1777006567.wav"

def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

audio, sr = sf.read(WAV)
if len(audio.shape) > 1:
    audio = audio.mean(axis=1)
audio = audio.astype(np.float32)
chunks = [audio[i*CHUNK_SAMPLES:(i+1)*CHUNK_SAMPLES] for i in range(6)]
log(f"Yuklendi: {len(chunks)} chunk x 5sn")


def test_model(name, transcribe_fn):
    log(f"\n=== {name} ===")
    times = []
    for i, c in enumerate(chunks):
        t0 = time.time()
        try:
            txt = transcribe_fn(c)
        except Exception as e:
            txt = f"[HATA: {e}]"
        elapsed = time.time() - t0
        times.append(elapsed)
        log(f"  chunk {i}: {elapsed:.2f}s | {txt[:80]}")
    log(f"  ortalama: {np.mean(times):.2f}s, RTF: {np.mean(times)/5:.3f}")


# Whisper-tiny
log("\n>>> Whisper-tiny yukleniyor...")
from transformers import WhisperProcessor, WhisperForConditionalGeneration
import torch

w_proc = WhisperProcessor.from_pretrained("tarteel-ai/whisper-tiny-ar-quran")
w_model = WhisperForConditionalGeneration.from_pretrained("tarteel-ai/whisper-tiny-ar-quran")
w_model.eval()
forced_ids = w_proc.get_decoder_prompt_ids(language="arabic", task="transcribe")
w_model.config.forced_decoder_ids = forced_ids
w_model.generation_config.forced_decoder_ids = forced_ids
if hasattr(w_model.generation_config, "language"):
    w_model.generation_config.language = None
if hasattr(w_model.generation_config, "task"):
    w_model.generation_config.task = None


def w_tiny(c):
    inp = w_proc(c, sampling_rate=SAMPLE_RATE, return_tensors="pt")
    with torch.no_grad():
        ids = w_model.generate(inp.input_features)
    return w_proc.batch_decode(ids, skip_special_tokens=True)[0].strip()

test_model("Whisper-tiny (Tarteel)", w_tiny)


# faster-whisper
log("\n>>> faster-whisper yukleniyor...")
from faster_whisper import WhisperModel
fw = WhisperModel("OdyAsh/faster-whisper-base-ar-quran", device="cpu", compute_type="int8")

def f_whisper(c):
    segs, _ = fw.transcribe(c, language="ar", beam_size=1)
    return " ".join(s.text for s in segs).strip()

test_model("faster-whisper-base (Tarteel)", f_whisper)
