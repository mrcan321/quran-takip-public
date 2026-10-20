#!/usr/bin/env python3
"""
NeMo FastConformer Arabic — İlk Baseline Test
-----------------------------------------------
Hiç fine-tune olmadan, genel Arapça'da eğitilmiş model Kuran'ı ne kadar tanıyor?
"""
import sys
import time
from pathlib import Path

import torch
import nemo.collections.asr as nemo_asr

device = "cpu"
print(f"Cihaz: {device}", file=sys.stderr)

MODEL_NAME = "nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0"

print(f"\nModel yükleniyor: {MODEL_NAME}", file=sys.stderr)
print("(İlk çalıştırma ~500 MB indirebilir, birkaç dakika sürer)",
      file=sys.stderr)

t0 = time.time()
model = nemo_asr.models.EncDecHybridRNNTCTCBPEModel.from_pretrained(
    model_name=MODEL_NAME,
)
model = model.to(device)
model.eval()

# Hibrit modelin iki decoder'ı var: RNNT (doğru) veya CTC (hızlı)
model.change_decoding_strategy(decoder_type="rnnt")

print(f"Model hazır ({time.time() - t0:.1f} sn).\n", file=sys.stderr)

audio_path = Path.home() / "projects/quran-asr/data/test_fatiha.wav"
if not audio_path.exists():
    print(f"HATA: {audio_path} bulunamadı", file=sys.stderr)
    sys.exit(1)

print(f"Ses dosyası: {audio_path.name}", file=sys.stderr)

t0 = time.time()
output = model.transcribe([str(audio_path)])
inference_time = time.time() - t0

# NeMo output yapısı sürüme göre değişir
if output and hasattr(output[0], "text"):
    text = output[0].text
elif output and isinstance(output[0], str):
    text = output[0]
elif output and isinstance(output[0], list):
    first = output[0][0] if output[0] else ""
    text = first.text if hasattr(first, "text") else str(first)
else:
    text = str(output)

print(f"\n{'=' * 60}")
print(f"  Inference süresi: {inference_time:.1f} sn")
print(f"{'=' * 60}")
print(f"  Transkripsiyon:")
print(f"  {text}")
print(f"{'=' * 60}\n")
