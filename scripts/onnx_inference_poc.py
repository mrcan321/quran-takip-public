#!/usr/bin/env python3
"""
ONNX Inference PoC — Adim 2a + 2b

Hedef:
  1. NeMo preprocessor'unu kullanarak mel-spec uret
  2. ONNX Runtime ile inference yap
  3. Cikti NeMo'nun kendi inference'iyla ayni mi karsilastir
  4. Sonra: numpy ile manuel mel-spec yap, NeMo'nunkiyle %1 icinde eslesiyor mu kontrol et

Cikti:
  - Konsol log'u + karsilastirma raporu
  - ~/projects/quran-asr/onnx/inference_report.txt
"""

import os
import sys
import json
import time
import numpy as np
from pathlib import Path

HOME = Path.home()
PROJECT_ROOT = HOME / "projects" / "quran-asr"
ONNX_DIR = PROJECT_ROOT / "onnx"

ONNX_MODEL_PATH = ONNX_DIR / "fastconformer_ctc.onnx"
TOKENIZER_JSON_PATH = ONNX_DIR / "fastconformer_ctc.json"
REPORT_PATH = ONNX_DIR / "inference_report.txt"

DATASET_DIR = HOME / "projects" / "benchmark" / "benchmark_workspace" / "dataset"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# ============================================================
# 1. CTC greedy decode (numpy)
# ============================================================
def ctc_greedy_decode(logprobs, blank_idx, vocab):
    """
    logprobs: [T, V] numpy array
    Donus: token id'leri (blank ve duplicate'lar cikarilmis)
    """
    pred_ids = np.argmax(logprobs, axis=-1)  # [T]
    # Collapse duplicates + remove blank
    decoded = []
    prev = -1
    for tid in pred_ids:
        if tid != blank_idx and tid != prev:
            decoded.append(int(tid))
        prev = tid
    return decoded

def tokens_to_text(token_ids, vocab):
    """SentencePiece'in '_' (U+2581) karakterini bosluga cevir"""
    pieces = [vocab[tid] for tid in token_ids]
    text = "".join(pieces).replace("\u2581", " ").strip()
    return text

# ============================================================
# 2. ONNX Runtime inference
# ============================================================
def run_onnx_inference(onnx_path, mel_features, mel_lengths):
    """
    mel_features: [B, n_mels, T]  (NeMo formati)
    mel_lengths:  [B]              (her sample'in T uzunlugu)
    Donus: logprobs [B, T_out, V]
    """
    import onnxruntime as ort

    log(f"ONNX session olusturuluyor: {onnx_path.name}")
    t0 = time.time()
    sess_opts = ort.SessionOptions()
    sess_opts.intra_op_num_threads = 4
    session = ort.InferenceSession(str(onnx_path), sess_opts, providers=["CPUExecutionProvider"])
    log(f"  Session yuklendi ({time.time()-t0:.2f}s)")

    # Input/output isimlerini al
    inputs = {i.name: i.shape for i in session.get_inputs()}
    outputs = {o.name: o.shape for o in session.get_outputs()}
    log(f"  Inputs: {inputs}")
    log(f"  Outputs: {outputs}")

    log("Inference calisiyor...")
    t0 = time.time()
    feed = {
        "audio_signal": mel_features.astype(np.float32),
        "length": mel_lengths.astype(np.int64),
    }
    result = session.run(None, feed)
    elapsed = time.time() - t0
    log(f"  Inference suresi: {elapsed:.3f}s")
    return result[0], elapsed  # logprobs

# ============================================================
# 3. NeMo preprocessor ile mel-spec
# ============================================================
def get_mel_via_nemo(model, audio, sr=16000):
    """
    audio: [N] float32 numpy
    Donus: mel [1, n_mels, T], length [1]
    """
    import torch

    audio_tensor = torch.from_numpy(audio).unsqueeze(0).float()  # [1, N]
    length_tensor = torch.tensor([audio.shape[0]], dtype=torch.long)

    with torch.no_grad():
        mel, mel_len = model.preprocessor(
            input_signal=audio_tensor,
            length=length_tensor,
        )
    return mel.cpu().numpy(), mel_len.cpu().numpy()

# ============================================================
# 4. Manuel numpy mel-spec (Kotlin port'u icin referans)
# ============================================================
def get_mel_manual(audio, sr=16000, n_fft=512, win_length=400, hop_length=160,
                   n_mels=80, preemph=0.97):
    """
    NeMo'nun AudioToMelSpectrogramPreprocessor'una EŞDEĞER manuel implementasyon.

    Bu fonksiyonun çıktısı NeMo preprocessor'un çıktısıyla %1 içinde eşleşmeli.
    Eşleşmezse paramteler yanlış demektir.

    Donus: mel [1, n_mels, T], length [1]
    """
    # Pre-emphasis
    audio_pe = np.append(audio[0], audio[1:] - preemph * audio[:-1])

    # Reflect padding for centered STFT
    pad = n_fft // 2
    audio_padded = np.pad(audio_pe, (pad, pad), mode='reflect')

    # Hann window
    window = np.hanning(win_length).astype(np.float32)
    # NeMo (default) periodic Hann; numpy hanning sym=True. Periodic icin:
    # window = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(win_length) / win_length)

    # Win'i n_fft'e padle (sag tarafi 0)
    win_padded = np.zeros(n_fft, dtype=np.float32)
    win_padded[:win_length] = window

    # STFT (numpy)
    n_frames = 1 + (audio_padded.shape[0] - n_fft) // hop_length
    stft = np.zeros((n_fft // 2 + 1, n_frames), dtype=np.complex64)
    for i in range(n_frames):
        frame = audio_padded[i * hop_length : i * hop_length + n_fft] * win_padded
        stft[:, i] = np.fft.rfft(frame, n=n_fft)

    # Magnitude squared
    power = (np.abs(stft) ** 2).astype(np.float32)

    # Mel filterbank
    mel_fb = mel_filterbank(sr=sr, n_fft=n_fft, n_mels=n_mels)
    # mel_fb: [n_mels, n_fft//2+1]
    mel = mel_fb @ power  # [n_mels, T]

    # Log
    mel_log = np.log(mel + 1e-5)

    # Per-feature normalization (NeMo default)
    mean = mel_log.mean(axis=1, keepdims=True)
    std = mel_log.std(axis=1, keepdims=True)
    mel_norm = (mel_log - mean) / (std + 1e-5)

    return mel_norm[np.newaxis, :, :].astype(np.float32), np.array([n_frames], dtype=np.int64)

def mel_filterbank(sr=16000, n_fft=512, n_mels=80, fmin=0.0, fmax=None):
    """Slaney-style mel filterbank, librosa/torchaudio uyumlu."""
    if fmax is None:
        fmax = sr / 2

    def hz_to_mel(hz):
        return 1127.0 * np.log(1.0 + hz / 700.0)
    def mel_to_hz(m):
        return 700.0 * (np.exp(m / 1127.0) - 1.0)

    mel_min = hz_to_mel(fmin)
    mel_max = hz_to_mel(fmax)
    mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
    hz_points = mel_to_hz(mel_points)

    # FFT bin frekanslari
    bin_freqs = np.linspace(0, sr / 2, n_fft // 2 + 1)

    fb = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for m in range(n_mels):
        left, center, right = hz_points[m], hz_points[m+1], hz_points[m+2]
        for k, f in enumerate(bin_freqs):
            if left <= f <= center:
                fb[m, k] = (f - left) / (center - left + 1e-10)
            elif center <= f <= right:
                fb[m, k] = (right - f) / (right - center + 1e-10)
        # Slaney normalization (energy preservation)
        denom = right - left
        if denom > 0:
            fb[m] *= 2.0 / denom
    return fb

# ============================================================
# 5. Karsilastirma yardimcilari
# ============================================================
def compare_mels(mel_nemo, mel_manual, label=""):
    """Iki mel-spec'i karsilastir, MAE ve max fark dondur."""
    if mel_nemo.shape != mel_manual.shape:
        log(f"  UYARI {label}: shape farkli — NeMo {mel_nemo.shape}, Manual {mel_manual.shape}")
        # Boyutlari esitle
        T_min = min(mel_nemo.shape[-1], mel_manual.shape[-1])
        mel_nemo = mel_nemo[..., :T_min]
        mel_manual = mel_manual[..., :T_min]

    diff = np.abs(mel_nemo - mel_manual)
    mae = diff.mean()
    max_diff = diff.max()
    cosine = np.sum(mel_nemo * mel_manual) / (
        np.linalg.norm(mel_nemo) * np.linalg.norm(mel_manual) + 1e-10
    )
    log(f"  {label} — MAE: {mae:.4f}, max diff: {max_diff:.4f}, cosine: {cosine:.4f}")
    return {"mae": float(mae), "max_diff": float(max_diff), "cosine": float(cosine)}

# ============================================================
# Ana
# ============================================================
def main():
    if not ONNX_MODEL_PATH.exists():
        log(f"HATA: ONNX modeli yok: {ONNX_MODEL_PATH}")
        log("Once 'python scripts/onnx_export_poc.py' calistir.")
        sys.exit(1)

    if not TOKENIZER_JSON_PATH.exists():
        log(f"HATA: Metadata yok: {TOKENIZER_JSON_PATH}")
        sys.exit(1)

    # Test wav bul
    test_wav = DATASET_DIR / "clips" / "base_005.wav"
    if not test_wav.exists():
        candidates = list((DATASET_DIR / "clips").glob("*.wav"))
        if not candidates:
            log("HATA: Test wav yok")
            sys.exit(1)
        test_wav = candidates[0]
    log(f"Test wav: {test_wav.name}")

    # Audio yukle
    import soundfile as sf
    audio, sr = sf.read(str(test_wav))
    if len(audio.shape) > 1:
        audio = audio.mean(axis=1)
    audio = audio.astype(np.float32)
    if sr != 16000:
        log(f"HATA: SR {sr} != 16000, resample gerekli")
        sys.exit(1)
    log(f"  Suresi: {audio.shape[0]/sr:.2f}s")

    # Metadata
    with open(TOKENIZER_JSON_PATH) as f:
        meta = json.load(f)
    vocab = meta["vocab"]
    blank_idx = meta["blank_idx"]
    log(f"  Vocab: {len(vocab)}, blank_idx: {blank_idx}")

    report = []
    report.append("=" * 60)
    report.append("ONNX Inference PoC — Adim 2a + 2b")
    report.append("=" * 60)
    report.append(f"Tarih: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"Wav:   {test_wav.name} ({audio.shape[0]/sr:.2f}s)")
    report.append("")

    # === Adim 2a: NeMo preprocessor + ONNX inference ===
    log("")
    log("=" * 50)
    log("Adim 2a: NeMo preprocessor + ONNX Runtime inference")
    log("=" * 50)

    log("NeMo modeli (preprocessor icin) yukleniyor...")
    import nemo.collections.asr as nemo_asr
    import torch
    model = nemo_asr.models.EncDecHybridRNNTCTCBPEModel.from_pretrained(
        model_name="nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0",
        map_location=torch.device("cpu"),
    )
    model.eval()
    model.change_decoding_strategy(decoder_type='ctc')

    # NeMo orijinal CTC inference (ground truth)
    log("NeMo CTC referans transkripsiyon...")
    nemo_text = model.transcribe([str(test_wav)])
    if isinstance(nemo_text, list):
        nemo_text = nemo_text[0] if isinstance(nemo_text[0], str) else (
            nemo_text[0].text if hasattr(nemo_text[0], 'text') else str(nemo_text[0])
        )
    log(f"  NeMo CTC: {nemo_text[:80]}...")

    # NeMo preprocessor ile mel
    log("NeMo preprocessor ile mel-spec...")
    mel_nemo, mel_len_nemo = get_mel_via_nemo(model, audio, sr=16000)
    log(f"  Shape: {mel_nemo.shape}, length: {mel_len_nemo}")

    # ONNX inference
    log("ONNX Runtime inference...")
    logprobs, ort_time = run_onnx_inference(ONNX_MODEL_PATH, mel_nemo, mel_len_nemo)
    log(f"  Output shape: {logprobs.shape}")

    # CTC decode
    log("CTC greedy decode...")
    token_ids = ctc_greedy_decode(logprobs[0], blank_idx, vocab)
    log(f"  Token sayisi (blank/dup sonrasi): {len(token_ids)}")

    # NeMo'nun tokenizer'ini kullan (vocab json belki incomplete)
    onnx_text = model.tokenizer.ids_to_text(token_ids)
    log(f"  ONNX cikti: {onnx_text[:120]}...")

    report.append("--- Adim 2a: NeMo preproc + ONNX Runtime ---")
    report.append(f"NeMo CTC referans:  {nemo_text}")
    report.append(f"ONNX cikti:         {onnx_text}")
    report.append(f"ONNX inference:     {ort_time*1000:.0f}ms")
    report.append(f"Esit mi: {'EVET' if nemo_text.strip() == onnx_text.strip() else 'HAYIR'}")
    report.append("")

    if nemo_text.strip() == onnx_text.strip():
        log("")
        log("✓ ONNX cikti NeMo CTC ile AYNI")
    else:
        log("")
        log("✗ ONNX cikti NeMo CTC'den FARKLI")
        log("  Bu pre-processor uyumsuzlugundan kaynaklanabilir")

    # === Adim 2b: Manuel numpy mel-spec ===
    log("")
    log("=" * 50)
    log("Adim 2b: Manuel numpy mel-spec")
    log("=" * 50)

    pre_cfg = meta["preprocessor"]
    log(f"Preprocessor config: {pre_cfg}")

    log("Manuel mel-spec hesaplaniyor...")
    mel_manual, mel_len_manual = get_mel_manual(
        audio,
        sr=pre_cfg["sample_rate"],
        n_fft=pre_cfg.get("n_fft", 512) or 512,
        win_length=pre_cfg.get("win_length", 400) or 400,
        hop_length=pre_cfg.get("hop_length", 160) or 160,
        n_mels=pre_cfg.get("n_mels", 80),
        preemph=pre_cfg.get("preemph", 0.97) or 0.97,
    )
    log(f"  Shape: {mel_manual.shape}, length: {mel_len_manual}")

    # Karsilastir
    log("NeMo vs manuel mel-spec karsilastirmasi:")
    cmp = compare_mels(mel_nemo, mel_manual, label="mel")
    report.append("--- Adim 2b: Manuel numpy mel-spec ---")
    report.append(f"NeMo mel shape:   {mel_nemo.shape}")
    report.append(f"Manuel mel shape: {mel_manual.shape}")
    report.append(f"MAE:        {cmp['mae']:.4f}")
    report.append(f"Max diff:   {cmp['max_diff']:.4f}")
    report.append(f"Cosine sim: {cmp['cosine']:.4f}")
    report.append("")

    # Manuel mel ile ONNX inference de yap
    log("Manuel mel ile ONNX inference...")
    logprobs_manual, _ = run_onnx_inference(ONNX_MODEL_PATH, mel_manual, mel_len_manual)
    token_ids_manual = ctc_greedy_decode(logprobs_manual[0], blank_idx, vocab)
    onnx_text_manual = model.tokenizer.ids_to_text(token_ids_manual)
    log(f"  Manuel mel ONNX cikti: {onnx_text_manual[:120]}...")

    report.append(f"Manuel mel ONNX:  {onnx_text_manual}")
    report.append(f"NeMo mel ONNX'le esit mi: {'EVET' if onnx_text_manual.strip() == onnx_text.strip() else 'HAYIR'}")
    report.append("")

    if onnx_text_manual.strip() == onnx_text.strip():
        log("✓ Manuel mel-spec NeMo preprocessor'la EŞIT cikti veriyor")
        log("  Kotlin port'u guvenle yapilabilir")
    else:
        log("✗ Manuel mel-spec FARKLI cikti veriyor")
        log("  Mel filterbank veya STFT parametrelerinde uyumsuzluk var")
        log("  Bunu duzeltmemiz lazim")

    report.append("=" * 60)
    report.append("Adim 2a + 2b sonuc:")
    if nemo_text.strip() == onnx_text.strip():
        report.append("  ✓ ONNX Runtime NeMo ile ayni cikti veriyor")
    else:
        report.append("  ✗ ONNX cikti NeMo'dan farkli")

    if onnx_text_manual.strip() == onnx_text.strip():
        report.append("  ✓ Manuel mel-spec dogru calisiyor")
    else:
        report.append("  ✗ Manuel mel-spec farkli — ayar gerekli")
    report.append("=" * 60)

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")

    print("\n".join(report[-15:]))
    log(f"\nRapor: {REPORT_PATH}")

if __name__ == "__main__":
    main()
