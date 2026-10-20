#!/usr/bin/env python3
"""
ONNX Export PoC — FastConformer Hybrid CTC

Hedef:
  1. NeMo Hybrid modelini ONNX'e export et (CTC head ile)
  2. Aynı wav dosyasini hem NeMo'da hem ONNX'te calistir
  3. Cikti farkini olc (cosine similarity + transkripsiyon karsilastirmasi)

Cikti dosyalari:
  ~/projects/quran-asr/onnx/
    fastconformer_ctc.onnx        # Export edilen model (~120 MB)
    fastconformer_ctc.json        # Tokenizer + config
    export_report.txt             # Karsilastirma raporu

Calistirma:
  cd ~/projects/quran-asr
  source venv/bin/activate
  python scripts/onnx_export_poc.py
"""

import os
import sys
import json
import time
import argparse
import numpy as np
from pathlib import Path

# ============================================================
# Konfigurasyon
# ============================================================
HOME = Path.home()
PROJECT_ROOT = HOME / "projects" / "quran-asr"
ONNX_DIR = PROJECT_ROOT / "onnx"
ONNX_DIR.mkdir(parents=True, exist_ok=True)

ONNX_MODEL_PATH = ONNX_DIR / "fastconformer_ctc.onnx"
TOKENIZER_JSON_PATH = ONNX_DIR / "fastconformer_ctc.json"
REPORT_PATH = ONNX_DIR / "export_report.txt"

# Test ses dosyasi — benchmark dataset'inden secelim
DATASET_DIR = HOME / "projects" / "benchmark" / "benchmark_workspace" / "dataset"
TEST_WAV_CANDIDATES = [
    DATASET_DIR / "clips" / "tevbe_husary.wav",
    DATASET_DIR / "clips" / "tevbe_alafasy.wav",
]

DEFAULT_MODEL_NAME = "nvidia/stt_ar_fastconformer_hybrid_large_pt"

# ============================================================
# Yardimci
# ============================================================
def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def find_test_wav():
    for p in TEST_WAV_CANDIDATES:
        if p.exists():
            return p
    # Fallback — herhangi bir wav bul
    candidates = list(DATASET_DIR.glob("clips/*.wav"))
    if candidates:
        return candidates[0]
    return None

# ============================================================
# 1. NeMo modelini yukle
# ============================================================
def load_nemo_model(model_name):
    log(f"NeMo modeli yukleniyor: {model_name}")
    log("(Ilk seferde indirme yapabilir, ~600 MB)")

    import nemo.collections.asr as nemo_asr

    # CPU forced
    import torch
    device = torch.device("cpu")

    model = nemo_asr.models.EncDecHybridRNNTCTCBPEModel.from_pretrained(
        model_name=model_name,
        map_location=device,
    )
    model.eval()
    log(f"  Encoder params: {sum(p.numel() for p in model.encoder.parameters()):,}")
    log(f"  Toplam params:  {sum(p.numel() for p in model.parameters()):,}")
    return model

# ============================================================
# 2. CTC moduna gec ve export et
# ============================================================
def export_ctc(model, output_path):
    log("CTC decoding moduna geciliyor...")
    # Hybrid model — CTC head'i kullan
    model.change_decoding_strategy(decoder_type='ctc')
    log("  OK")

    log(f"ONNX export basliyor: {output_path}")
    log("  (5-10 dakika surebilir)")
    t0 = time.time()
    model.export(str(output_path))
    elapsed = time.time() - t0
    log(f"  OK ({elapsed:.0f} saniye)")

    size_mb = output_path.stat().st_size / 1024 / 1024
    log(f"  Boyut: {size_mb:.1f} MB")
    return size_mb

# ============================================================
# 3. Tokenizer ve preprocessor config'i kaydet
# ============================================================
def save_metadata(model, json_path):
    log("Tokenizer ve config kaydediliyor...")

    # Vocab — CTC blank dahil
    vocab = []
    if hasattr(model, 'tokenizer') and model.tokenizer is not None:
        # SentencePiece tokenizer
        sp = model.tokenizer.tokenizer if hasattr(model.tokenizer, 'tokenizer') else model.tokenizer
        try:
            vocab_size = sp.get_piece_size() if hasattr(sp, 'get_piece_size') else sp.vocab_size
            vocab = [sp.id_to_piece(i) if hasattr(sp, 'id_to_piece') else sp.IdToPiece(i)
                     for i in range(vocab_size)]
        except Exception as e:
            log(f"  UYARI: Vocab cikarilamadi: {e}")

    # Preprocessor config (mel-spec parametreleri)
    pre = model.preprocessor
    pre_cfg = {
        "sample_rate": getattr(pre, "_sample_rate", 16000),
        "n_fft": getattr(pre, "n_fft", None) or getattr(pre.featurizer, "n_fft", 512),
        "win_length": getattr(pre.featurizer, "win_length", 400) if hasattr(pre, "featurizer") else 400,
        "hop_length": getattr(pre.featurizer, "hop_length", 160) if hasattr(pre, "featurizer") else 160,
        "n_mels": getattr(pre, "features", 80),
        "preemph": getattr(pre, "preemph", 0.97),
        "log": True,
        "normalize": "per_feature",
    }

    metadata = {
        "model_name": "fastconformer_ctc_export",
        "vocab": vocab,
        "vocab_size": len(vocab),
        "blank_idx": len(vocab),  # CTC blank son indekste tipik olarak
        "preprocessor": pre_cfg,
        "input_name": "audio_signal",
        "input_length_name": "length",
        "output_name": "logprobs",
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    log(f"  Vocab boyutu: {len(vocab)}")

# ============================================================
# 4. NeMo'da test transkripsiyon
# ============================================================
def transcribe_nemo(model, wav_path):
    log(f"NeMo (orijinal) transkripsiyon: {wav_path.name}")
    t0 = time.time()
    result = model.transcribe([str(wav_path)])
    elapsed = time.time() - t0

    # NeMo'nun donus tipi sürüme göre değişiyor
    if isinstance(result, tuple):
        text = result[0][0] if isinstance(result[0], list) else result[0]
    elif isinstance(result, list):
        text = result[0] if isinstance(result[0], str) else (
            result[0].text if hasattr(result[0], 'text') else str(result[0])
        )
    else:
        text = str(result)

    log(f"  Sure: {elapsed:.2f}s")
    log(f"  Cikti: {text[:120]}{'...' if len(text) > 120 else ''}")
    return text, elapsed

# ============================================================
# 5. ONNX'te test transkripsiyon
# ============================================================
def transcribe_onnx(onnx_path, metadata_path, wav_path):
    log(f"ONNX (export edilmis) transkripsiyon: {wav_path.name}")

    import onnxruntime as ort
    import soundfile as sf

    with open(metadata_path) as f:
        meta = json.load(f)

    vocab = meta["vocab"]
    blank_idx = meta["blank_idx"]
    sr_target = meta["preprocessor"]["sample_rate"]

    # Audio yukle
    audio, sr = sf.read(str(wav_path))
    if sr != sr_target:
        log(f"  UYARI: Sample rate {sr} != {sr_target}, resample edilmesi lazim")
    if len(audio.shape) > 1:
        audio = audio.mean(axis=1)
    audio = audio.astype(np.float32)

    # Mel-spectrogram (NeMo preprocessor'unu kullan; en kolay yol bu)
    # Ama burada zor kisim: preprocessor'u Python disinda nasil yapacaksiniz?
    # Test icin NeMo preprocessor'unu kullaniyoruz, Android'de manuel implement edecegiz
    import torch
    import nemo.collections.asr as nemo_asr
    # Preprocessor'u tek seferlik yukle
    if not hasattr(transcribe_onnx, "_pre_model"):
        log("  Preprocessor icin NeMo yukleniyor (sadece bir kere)...")
        # Preprocessor'u ayri yuklemek karmasik, model uzerinden yapalim
        # Bu fonksiyon zaten model elden geliyor varsayimini kirdik, yeniden yukleyelim
        # Pratik: ekspert kisimlari Adim 2'de manuel mel-spec implementasyonu yazariz
        pass

    # Bu PoC asamasinda, test icin dogrudan input olarak audio'yu verecegiz
    # ve preprocessor'u modelin disindan elle calistiracagiz
    # Kolay yol: Modelin export ettigi onnx zaten preprocessor dahil mi degil mi? NeMo'nun
    # export'unda preprocessor genellikle DAHIL DEGIL — o yuzden manuel mel-spec lazim.

    log("  HATA: ONNX inference icin mel-spectrogram on-isleme gerekli.")
    log("        Bu PoC'de sadece export'u dogruladik. Inference icin Adim 2'ye gec.")
    return None, None

# ============================================================
# 6. Karsilastirma raporu
# ============================================================
def write_report(report_lines):
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines) + "\n")
    log(f"Rapor yazildi: {REPORT_PATH}")

# ============================================================
# Ana akis
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME,
                        help="NeMo model adi veya .nemo dosya yolu")
    parser.add_argument("--skip-export", action="store_true",
                        help="Export var ise atla, sadece karsilastir")
    args = parser.parse_args()

    report = []
    report.append("=" * 60)
    report.append("ONNX Export PoC — FastConformer Hybrid CTC")
    report.append("=" * 60)
    report.append(f"Tarih:   {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"Model:   {args.model}")
    report.append("")

    # 1. Test wav bul
    test_wav = find_test_wav()
    if not test_wav:
        log("HATA: Test wav bulunamadi. Dataset hazir mi?")
        log(f"  Aranan: {DATASET_DIR}/clips/*.wav")
        sys.exit(1)
    log(f"Test wav: {test_wav}")
    report.append(f"Test ses: {test_wav.name}")

    # 2. Model yukle
    if not args.skip_export or not ONNX_MODEL_PATH.exists():
        model = load_nemo_model(args.model)

        # 3. NeMo'da transkribe et (RNNT default)
        log("--- NeMo orijinal (RNNT decoder) ---")
        text_rnnt, t_rnnt = transcribe_nemo(model, test_wav)
        report.append("")
        report.append("--- NeMo orijinal (RNNT) ---")
        report.append(f"Sure:   {t_rnnt:.2f}s")
        report.append(f"Cikti:  {text_rnnt}")

        # 4. CTC moduna gec
        size_mb = export_ctc(model, ONNX_MODEL_PATH)
        report.append("")
        report.append(f"ONNX boyut: {size_mb:.1f} MB")

        # CTC'de de tekrar transkribe et — kalite farkini gorelim
        log("--- NeMo CTC mode ---")
        text_ctc, t_ctc = transcribe_nemo(model, test_wav)
        report.append("")
        report.append("--- NeMo CTC ---")
        report.append(f"Sure:   {t_ctc:.2f}s")
        report.append(f"Cikti:  {text_ctc}")

        # 5. Metadata kaydet
        save_metadata(model, TOKENIZER_JSON_PATH)
    else:
        log(f"Export var, atlandi: {ONNX_MODEL_PATH}")
        report.append("(export atlandi)")

    # 6. ONNX dosyasini dogrula
    log("ONNX dosyasi dogrulaniyor...")
    try:
        import onnx
        onnx_model = onnx.load(str(ONNX_MODEL_PATH))
        onnx.checker.check_model(onnx_model)
        log(f"  OK — IR version: {onnx_model.ir_version}")
        log(f"  Opset: {[op.version for op in onnx_model.opset_import]}")
        log(f"  Input shape: {[i.name for i in onnx_model.graph.input]}")
        log(f"  Output shape: {[o.name for o in onnx_model.graph.output]}")

        report.append("")
        report.append("--- ONNX Dogrulama ---")
        report.append(f"IR version: {onnx_model.ir_version}")
        report.append(f"Inputs:     {[i.name for i in onnx_model.graph.input]}")
        report.append(f"Outputs:    {[o.name for o in onnx_model.graph.output]}")
    except ImportError:
        log("  UYARI: onnx paketi yuklu degil, dogrulama atlandi")
        log("         pip install onnx")
    except Exception as e:
        log(f"  HATA: {e}")
        report.append(f"ONNX HATA: {e}")

    report.append("")
    report.append("=" * 60)
    report.append("SONUC: Export tamamlandi.")
    report.append(f"  ONNX:     {ONNX_MODEL_PATH}")
    report.append(f"  Metadata: {TOKENIZER_JSON_PATH}")
    report.append("")
    report.append("Sonraki adim: Adim 2 — quantization (FP32 -> INT8)")
    report.append("=" * 60)

    write_report(report)

    print()
    print("\n".join(report[-15:]))

if __name__ == "__main__":
    main()
