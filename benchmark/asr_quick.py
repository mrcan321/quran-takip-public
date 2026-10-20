"""Hizli ASR karsilastirma - 3 model x 3 chunk."""
import sys
import time
import warnings
from pathlib import Path
import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")

SAMPLE_RATE = 16000
CHUNK_SAMPLES = SAMPLE_RATE * 5
NUM_CHUNKS = 3
AUDIO = Path.home() / "projects/quran-asr/server/recordings/session_1777006567.wav"


def now():
    return time.strftime("%H:%M:%S")


def log(msg):
    print(f"[{now()}] {msg}", flush=True)


log("Audio yukleniyor...")
audio, sr = sf.read(str(AUDIO))
if len(audio.shape) > 1:
    audio = audio.mean(axis=1)
audio = audio.astype(np.float32)
chunks = [audio[i * CHUNK_SAMPLES:(i + 1) * CHUNK_SAMPLES] for i in range(NUM_CHUNKS)]
log(f"Audio hazir: {NUM_CHUNKS} chunk x 5sn")

results = []


# Model 1: FastConformer
log("\n--- Model 1: FastConformer Large (mevcut) ---")
log("Yukleniyor...")
t0 = time.time()
import nemo.collections.asr as nemo_asr
import logging
logging.getLogger("nemo_logger").setLevel(logging.ERROR)
fc_model = nemo_asr.models.EncDecHybridRNNTCTCBPEModel.from_pretrained(
    "nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0"
).to("cpu")
fc_model.eval()
fc_model.change_decoding_strategy(decoder_type="rnnt")
log(f"Yuklendi: {time.time() - t0:.1f}s")

import tempfile
fc_times = []
fc_texts = []
for i, chunk in enumerate(chunks):
    log(f"  chunk {i} transkribe...")
    t0 = time.time()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, chunk, SAMPLE_RATE)
        tmp_path = tmp.name
    try:
        out = fc_model.transcribe([tmp_path], verbose=False)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    elapsed = time.time() - t0
    text = out[0].text.strip() if hasattr(out[0], "text") else str(out[0]).strip()
    fc_times.append(elapsed)
    fc_texts.append(text)
    log(f"    {elapsed:.2f}s | {text[:60]}")

results.append(("FastConformer Large", fc_times, fc_texts))
del fc_model
import gc
gc.collect()


# Model 2: Tarteel Whisper-tiny
log("\n--- Model 2: Tarteel Whisper-tiny ---")
log("Yukleniyor...")
t0 = time.time()
from transformers import WhisperProcessor, WhisperForConditionalGeneration
import torch

w_proc = WhisperProcessor.from_pretrained("tarteel-ai/whisper-tiny-ar-quran")
w_model = WhisperForConditionalGeneration.from_pretrained("tarteel-ai/whisper-tiny-ar-quran")
w_model.eval()
log(f"Yuklendi: {time.time() - t0:.1f}s")

w_times = []
w_texts = []
for i, chunk in enumerate(chunks):
    log(f"  chunk {i} transkribe...")
    t0 = time.time()
    inputs = w_proc(chunk, sampling_rate=SAMPLE_RATE, return_tensors="pt")
    with torch.no_grad():
        pred_ids = w_model.generate(inputs.input_features)
    text = w_proc.batch_decode(pred_ids, skip_special_tokens=True)[0].strip()
    elapsed = time.time() - t0
    w_times.append(elapsed)
    w_texts.append(text)
    log(f"    {elapsed:.2f}s | {text[:60]}")

results.append(("Whisper-tiny (Tarteel)", w_times, w_texts))
del w_model, w_proc
gc.collect()


# Model 3: faster-whisper Tarteel base
log("\n--- Model 3: faster-whisper Tarteel base (int8) ---")
log("Yukleniyor...")
t0 = time.time()
from faster_whisper import WhisperModel
fw_model = WhisperModel("OdyAsh/faster-whisper-base-ar-quran", device="cpu", compute_type="int8")
log(f"Yuklendi: {time.time() - t0:.1f}s")

fw_times = []
fw_texts = []
for i, chunk in enumerate(chunks):
    log(f"  chunk {i} transkribe...")
    t0 = time.time()
    segments, _ = fw_model.transcribe(chunk, language="ar", beam_size=1)
    text = " ".join(s.text for s in segments).strip()
    elapsed = time.time() - t0
    fw_times.append(elapsed)
    fw_texts.append(text)
    log(f"    {elapsed:.2f}s | {text[:60]}")

results.append(("faster-whisper-base (Tarteel)", fw_times, fw_texts))


# Ozet
print("\n" + "=" * 80, flush=True)
print("  OZET", flush=True)
print("=" * 80, flush=True)
print(f"{'Model':<35} {'Ortl.':>8} {'RTF':>6}", flush=True)
print("-" * 80, flush=True)
for name, times, _ in results:
    avg = np.mean(times)
    rtf = avg / 5.0
    print(f"{name:<35} {avg:>7.2f}s {rtf:>5.3f}", flush=True)

print("\n" + "=" * 80, flush=True)
print("  TRANSKRIPTLER", flush=True)
print("=" * 80, flush=True)
for ci in range(NUM_CHUNKS):
    print(f"\n--- Chunk {ci} ---", flush=True)
    for name, _, texts in results:
        print(f"  [{name[:30]:<30}] {texts[ci][:70]}", flush=True)
