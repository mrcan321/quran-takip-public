"""
ASR Model Hız & Kalite Karşılaştırması
---------------------------------------
Karşılaştırılan modeller:
1. FastConformer Large (mevcut, NeMo)
2. Tarteel Whisper-tiny (HuggingFace transformers)
3. Tarteel Whisper-base (HuggingFace transformers)
4. Tarteel Whisper-base (faster-whisper / CTranslate2)
5. Tadabur Whisper-Small (HuggingFace transformers)

Her model 5 saniyelik chunk'lar halinde aynı kayıt üzerinde çalıştırılır.
RTF (Real-Time Factor) = inference_time / audio_duration
RTF 0.1 ideal, RTF < 0.5 kabul edilebilir, RTF >= 1.0 gerçek zamanlı çalışmaz.
"""
import sys
import time
import warnings
from pathlib import Path
from typing import List, Dict, Tuple

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")

# --- Konfigürasyon ---
SAMPLE_RATE = 16000
CHUNK_DURATION_SEC = 5.0
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION_SEC)
NUM_CHUNKS_TO_TEST = 6  # İlk 6 chunk = 30 saniye

AUDIO_PATH = Path.home() / "projects/quran-asr/server/recordings/session_1777006567.wav"


def load_audio_chunks(wav_path: Path, n_chunks: int) -> List[np.ndarray]:
    """Audio'yu yükle ve 5 saniyelik chunk'lara böl."""
    audio, sr = sf.read(str(wav_path))
    if sr != SAMPLE_RATE:
        print(f"UYARI: Sample rate {sr}, beklenen {SAMPLE_RATE}", file=sys.stderr)
    if len(audio.shape) > 1:
        audio = audio.mean(axis=1)
    audio = audio.astype(np.float32)

    chunks = []
    for i in range(n_chunks):
        start = i * CHUNK_SAMPLES
        end = start + CHUNK_SAMPLES
        if end > len(audio):
            break
        chunks.append(audio[start:end])
    return chunks


def benchmark_model(name: str, load_fn, transcribe_fn, chunks: List[np.ndarray]) -> Dict:
    """Bir modeli yükle ve chunk'ları transkribe et, zamanları ölç."""
    print(f"\n{'='*70}")
    print(f"  {name}")
    print('='*70)

    t0 = time.time()
    try:
        model_state = load_fn()
    except Exception as e:
        print(f"  YÜKLEME BAŞARISIZ: {e}")
        return {"name": name, "error": str(e)}
    load_time = time.time() - t0
    print(f"  Yükleme: {load_time:.2f} sn")

    inference_times = []
    transcripts = []

    # Warm-up (ilk inference modelin cache'ini hazırlar)
    print(f"  Warm-up...")
    try:
        _ = transcribe_fn(model_state, chunks[0])
    except Exception as e:
        print(f"  WARM-UP BAŞARISIZ: {e}")
        return {"name": name, "error": f"warmup: {e}"}

    print(f"  {len(chunks)} chunk transkribe ediliyor...")
    for i, chunk in enumerate(chunks):
        t0 = time.time()
        try:
            text = transcribe_fn(model_state, chunk)
        except Exception as e:
            text = f"[HATA: {e}]"
        elapsed = time.time() - t0
        inference_times.append(elapsed)
        transcripts.append(text)
        print(f"    chunk {i}: {elapsed:.3f}s | {text[:60]}")

    avg_time = np.mean(inference_times)
    median_time = np.median(inference_times)
    rtf = avg_time / CHUNK_DURATION_SEC

    return {
        "name": name,
        "load_time": load_time,
        "avg_inference": avg_time,
        "median_inference": median_time,
        "rtf": rtf,
        "transcripts": transcripts,
    }


# ============================================================
# Model 1: FastConformer Large (mevcut)
# ============================================================
def load_fastconformer():
    import nemo.collections.asr as nemo_asr
    import logging
    logging.getLogger("nemo_logger").setLevel(logging.ERROR)
    model = nemo_asr.models.EncDecHybridRNNTCTCBPEModel.from_pretrained(
        model_name="nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0",
    ).to("cpu")
    model.eval()
    model.change_decoding_strategy(decoder_type="rnnt")
    return model


def transcribe_fastconformer(model, audio_np):
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, audio_np, SAMPLE_RATE)
        tmp_path = tmp.name
    try:
        output = model.transcribe([tmp_path], verbose=False)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    text = ""
    if output and hasattr(output[0], "text"):
        text = output[0].text.strip()
    elif output and isinstance(output[0], str):
        text = output[0].strip()
    elif output and isinstance(output[0], list) and output[0]:
        first = output[0][0]
        text = (first.text if hasattr(first, "text") else str(first)).strip()
    return text


# ============================================================
# Model 2-3-5: Whisper varyantları (transformers)
# ============================================================
def make_whisper_loader(model_id):
    def loader():
        from transformers import WhisperProcessor, WhisperForConditionalGeneration
        import torch
        processor = WhisperProcessor.from_pretrained(model_id)
        model = WhisperForConditionalGeneration.from_pretrained(model_id)
        model.eval()
        # Forced decoder ids — Arapça
        try:
            forced_ids = processor.get_decoder_prompt_ids(language="arabic", task="transcribe")
        except Exception:
            forced_ids = None
        return {"processor": processor, "model": model, "forced_ids": forced_ids}
    return loader


def transcribe_whisper(state, audio_np):
    import torch
    processor = state["processor"]
    model = state["model"]
    forced_ids = state["forced_ids"]
    inputs = processor(audio_np, sampling_rate=SAMPLE_RATE, return_tensors="pt")
    with torch.no_grad():
        gen_kwargs = {}
        if forced_ids is not None:
            gen_kwargs["forced_decoder_ids"] = forced_ids
        pred_ids = model.generate(inputs.input_features, **gen_kwargs)
    text = processor.batch_decode(pred_ids, skip_special_tokens=True)[0]
    return text.strip()


# ============================================================
# Model 4: faster-whisper (CTranslate2)
# ============================================================
def load_faster_whisper(model_id="OdyAsh/faster-whisper-base-ar-quran"):
    def loader():
        from faster_whisper import WhisperModel
        # CPU, int8 quantization (en hızlı)
        model = WhisperModel(model_id, device="cpu", compute_type="int8")
        return model
    return loader


def transcribe_faster_whisper(model, audio_np):
    segments, _ = model.transcribe(audio_np, language="ar", beam_size=1)
    text = " ".join(seg.text for seg in segments).strip()
    return text


# ============================================================
# Ana çalıştırma
# ============================================================
def main():
    print(f"Audio: {AUDIO_PATH}")
    if not AUDIO_PATH.exists():
        print(f"HATA: Audio bulunamadı")
        sys.exit(1)

    chunks = load_audio_chunks(AUDIO_PATH, NUM_CHUNKS_TO_TEST)
    print(f"Yüklendi: {len(chunks)} adet 5sn chunk")

    results = []

    # Model 1: FastConformer
    results.append(benchmark_model(
        "FastConformer Large (NeMo) [MEVCUT]",
        load_fastconformer, transcribe_fastconformer, chunks
    ))

    # Model 2: Tarteel Whisper-tiny
    results.append(benchmark_model(
        "Tarteel Whisper-tiny",
        make_whisper_loader("tarteel-ai/whisper-tiny-ar-quran"),
        transcribe_whisper, chunks
    ))

    # Model 3: Tarteel Whisper-base
    results.append(benchmark_model(
        "Tarteel Whisper-base",
        make_whisper_loader("tarteel-ai/whisper-base-ar-quran"),
        transcribe_whisper, chunks
    ))

    # Model 4: faster-whisper Tarteel base (CTranslate2)
    results.append(benchmark_model(
        "Tarteel Whisper-base (faster-whisper, int8)",
        load_faster_whisper("OdyAsh/faster-whisper-base-ar-quran"),
        transcribe_faster_whisper, chunks
    ))

    # Model 5: Tadabur Whisper-Small
    results.append(benchmark_model(
        "Tadabur Whisper-Small",
        make_whisper_loader("FaisaI/Tadabur-Whisper-Small"),
        transcribe_whisper, chunks
    ))

    # ============================================================
    # Özet
    # ============================================================
    print("\n\n")
    print("=" * 90)
    print(f"  ÖZET — {NUM_CHUNKS_TO_TEST} chunk × {CHUNK_DURATION_SEC}sn audio")
    print("=" * 90)
    print(f"{'Model':<48} {'Yükle':>8} {'Ortl.':>8} {'Median':>8} {'RTF':>6}")
    print("-" * 90)
    for r in results:
        if "error" in r:
            print(f"{r['name']:<48} HATA: {r['error']}")
            continue
        print(f"{r['name']:<48} "
              f"{r['load_time']:>7.2f}s "
              f"{r['avg_inference']:>7.3f}s "
              f"{r['median_inference']:>7.3f}s "
              f"{r['rtf']:>5.3f}")

    # Transkript karşılaştırması
    print("\n")
    print("=" * 90)
    print("  TRANSKRİPT KARŞILAŞTIRMASI (Chunk 0-2)")
    print("=" * 90)
    for chunk_idx in range(min(3, NUM_CHUNKS_TO_TEST)):
        print(f"\n--- Chunk {chunk_idx} ---")
        for r in results:
            if "error" in r or chunk_idx >= len(r.get("transcripts", [])):
                continue
            print(f"  [{r['name'][:40]:<40}] {r['transcripts'][chunk_idx][:80]}")


if __name__ == "__main__":
    main()
