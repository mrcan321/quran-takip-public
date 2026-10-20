#!/usr/bin/env python3
"""
vocab.txt ile manuel detokenize'in NeMo tokenizer ile ayni cikti uretip
uretmedigini dogrular.

Calistirma:
  python scripts/test_vocab_decode.py
"""

from pathlib import Path
import json
import numpy as np
import onnxruntime as ort
import soundfile as sf

HOME = Path.home()
ONNX_PATH = HOME / "projects" / "quran-asr" / "onnx" / "fastconformer_full.onnx"
META_PATH = HOME / "projects" / "quran-asr" / "onnx" / "fastconformer_full.json"
VOCAB_PATH = HOME / "projects" / "quran-asr" / "onnx" / "tokenizer" / "1e7bbe36b91a472896c99283bda08bf3_vocab.txt"
SP_MODEL_PATH = HOME / "projects" / "quran-asr" / "onnx" / "tokenizer" / "43c84e71237048ddab3bb273bdc00fa0_tokenizer.model"

DATASET_DIR = HOME / "projects" / "benchmark" / "benchmark_workspace" / "dataset"
TEST_WAV = DATASET_DIR / "clips" / "base_005.wav"

# === 1. Vocab.txt'yi yukle ===
with open(VOCAB_PATH, "r", encoding="utf-8") as f:
    vocab_txt = [line.rstrip("\n") for line in f]
print(f"vocab.txt: {len(vocab_txt)} token")
print(f"  Ilk 5: {vocab_txt[:5]}")
print(f"  Son 5: {vocab_txt[-5:]}")

# === 2. ONNX inference cikti tokenleri al ===
print(f"\nONNX inference: {TEST_WAV.name}")
audio, sr = sf.read(str(TEST_WAV))
if len(audio.shape) > 1:
    audio = audio.mean(axis=1)
audio = audio.astype(np.float32)

sess = ort.InferenceSession(str(ONNX_PATH), providers=['CPUExecutionProvider'])
result = sess.run(None, {
    "audio_signal": audio[np.newaxis, :].astype(np.float32),
    "length": np.array([audio.shape[0]], dtype=np.int64),
})
logprobs = result[0]
pred_ids = logprobs[0].argmax(axis=-1)

with open(META_PATH) as f:
    meta = json.load(f)
blank_idx = meta["blank_idx"]

# CTC: blank ve duplicate kaldir
decoded_ids = []
prev = -1
for tid in pred_ids:
    if tid != blank_idx and tid != prev:
        decoded_ids.append(int(tid))
    prev = tid

print(f"  Decoded {len(decoded_ids)} token")
print(f"  Ilk 10 ID: {decoded_ids[:10]}")
print(f"  Ilk 10 token (vocab.txt'den): {[vocab_txt[i] for i in decoded_ids[:10]]}")

# === 3. NeMo (SentencePiece) ile decode ===
import sentencepiece as spm
sp = spm.SentencePieceProcessor()
sp.load(str(SP_MODEL_PATH))
nemo_text = sp.decode_ids(decoded_ids)
print(f"\nNeMo SP decode:")
print(f"  {nemo_text[:120]}{'...' if len(nemo_text) > 120 else ''}")

# === 4. Manuel WordPiece-ish decode dene (vocab.txt'den) ===
# Format: ##X = continuation (kelime ici), ▁ = word boundary, X = standalone token
def manual_decode_v1(ids, vocab):
    """En basit yaklasim: ## continuation, diger her sey space ile birlestirilir"""
    pieces = [vocab[i] for i in ids]
    out = []
    for p in pieces:
        if p.startswith("##"):
            # Onceki token'a yapis
            if out:
                out[-1] = out[-1] + p[2:]
            else:
                out.append(p[2:])
        elif p == "▁":
            # Space marker
            out.append(" ")
        else:
            # Yeni kelime — space ile ayir
            if out and not out[-1].endswith(" "):
                out.append(" ")
            out.append(p)
    return "".join(out).strip()

manual_v1 = manual_decode_v1(decoded_ids, vocab_txt)
print(f"\nManuel decode v1:")
print(f"  {manual_v1[:120]}{'...' if len(manual_v1) > 120 else ''}")

# === 5. Karsilastir ===
print(f"\n{'='*60}")
print(f"NeMo:     {nemo_text}")
print(f"Manuel:   {manual_v1}")
print(f"Esit mi:  {'EVET' if nemo_text.strip() == manual_v1.strip() else 'HAYIR'}")

# Detayli fark — eger esit degilse
if nemo_text.strip() != manual_v1.strip():
    nemo_words = nemo_text.split()
    manual_words = manual_v1.split()
    print(f"  NeMo kelime: {len(nemo_words)}, Manuel kelime: {len(manual_words)}")
    # Ilk farkli pozisyon
    for i, (a, b) in enumerate(zip(nemo_words, manual_words)):
        if a != b:
            print(f"  Ilk fark pozisyon {i}: '{a}' vs '{b}'")
            print(f"  Konteks:")
            print(f"    NeMo:   {' '.join(nemo_words[max(0,i-2):i+3])}")
            print(f"    Manuel: {' '.join(manual_words[max(0,i-2):i+3])}")
            break

# === 6. Token bazinda detayli yan yana ===
print(f"\n--- Ilk 30 token (ID, token, NeMo decode) ---")
for i, tid in enumerate(decoded_ids[:30]):
    sp_decoded = sp.decode_ids([tid])
    print(f"  [{i:3d}] ID={tid:5d} vocab='{vocab_txt[tid]}' SP='{sp_decoded}'")
