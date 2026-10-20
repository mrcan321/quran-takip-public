#!/usr/bin/env python3
"""
v0.1 — NeMo + Kuran hizalama
-----------------------------
Bir veya daha fazla ses dosyası alır:
  1. NeMo FastConformer ile Arapça'ya transkribe eder
  2. Çıktıyı Kuran metnine hizalar
  3. Hangi sure/ayet/kelime olduğunu söyler
  4. Basit bir güven skoru verir

Kullanım:
    python scripts/v01_align.py data/test_fatiha.wav
    python scripts/v01_align.py data/*.wav
"""
import argparse
import sys
import time
from pathlib import Path

# aligner modülü aynı scripts/ altında
sys.path.insert(0, str(Path(__file__).parent))
from aligner import (
    QuranCorpus, align_transcription, format_match, normalize_arabic,
)

import nemo.collections.asr as nemo_asr

MODEL_NAME = "nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0"
MIN_WORD_COUNT = 2          # bundan az kelimeli transkripsiyonu reddet
MIN_CONFIDENCE = 50         # 0-100, altında "Kuran değil" sayılır


def compute_confidence(
    transcription: str,
    match,
    corpus_vocab: set,
) -> dict:
    """Basit güven skoru (0-100)."""
    tokens = [normalize_arabic(t) for t in transcription.split()]
    tokens = [t for t in tokens if t]

    if not tokens:
        return {"score": 0, "reason": "boş"}
    if len(tokens) < MIN_WORD_COUNT:
        return {"score": 0, "reason": f"çok az kelime ({len(tokens)})"}

    fuzzy = match.score if match else 0
    in_vocab = sum(1 for t in tokens if t in corpus_vocab)
    vocab_coverage = in_vocab / len(tokens)

    unique_ratio = len(set(tokens)) / len(tokens)
    max_consec = 1
    c = 1
    for i in range(1, len(tokens)):
        if tokens[i] == tokens[i - 1]:
            c += 1
            max_consec = max(max_consec, c)
        else:
            c = 1

    score = fuzzy
    score *= vocab_coverage ** 0.5
    score *= unique_ratio ** 0.3

    reason = ""
    if max_consec >= 3:
        score *= 0.3
        reason = f"{max_consec}x tekrar"
    if vocab_coverage < 0.3:
        score *= 0.5
        reason = reason or f"vocab düşük ({vocab_coverage:.0%})"

    return {
        "score": round(score, 1),
        "fuzzy": fuzzy,
        "vocab_coverage": round(vocab_coverage, 2),
        "word_count": len(tokens),
        "reason": reason,
    }


def transcribe(model, audio_path: str, decoder: str = "rnnt") -> str:
    """Ses dosyasını metne çevir."""
    model.change_decoding_strategy(decoder_type=decoder)
    output = model.transcribe([audio_path], verbose=False)
    if output and hasattr(output[0], "text"):
        return output[0].text.strip()
    if output and isinstance(output[0], str):
        return output[0].strip()
    if output and isinstance(output[0], list) and output[0]:
        first = output[0][0]
        return (first.text if hasattr(first, "text") else str(first)).strip()
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_files", nargs="+")
    parser.add_argument("--surah", type=int, help="Sadece belirli sure")
    parser.add_argument("--decoder", choices=["rnnt", "ctc"], default="rnnt")
    args = parser.parse_args()

    # 1) Modeli yükle
    print(f"Model yükleniyor ({args.decoder.upper()}): {MODEL_NAME}", file=sys.stderr)
    t0 = time.time()
    model = nemo_asr.models.EncDecHybridRNNTCTCBPEModel.from_pretrained(
        model_name=MODEL_NAME,
    )
    model = model.to("cpu")
    model.eval()
    print(f"Model hazır ({time.time() - t0:.1f} sn)\n", file=sys.stderr)

    # 2) Kuran korpusu
    corpus = QuranCorpus.load()
    if args.surah:
        corpus = corpus.filter_surah(args.surah)
        print(f"(Arama {args.surah}. sure ile sınırlı)\n", file=sys.stderr)
    corpus_vocab = set(corpus.normalized_tokens)

    # 3) Her dosyayı işle
    for audio_path in args.audio_files:
        path = Path(audio_path)
        if not path.exists():
            print(f"✗ {audio_path} bulunamadı", file=sys.stderr)
            continue

        print("═" * 70)
        print(f"  📄 {path.name}")
        print("═" * 70)

        # Transkribe
        t0 = time.time()
        text = transcribe(model, str(path), args.decoder)
        asr_time = time.time() - t0

        if not text:
            print(f"  (boş transkripsiyon, {asr_time:.2f} sn) — Kuran değil veya ses yok")
            print()
            continue

        print(f"  🗣  Transkripsiyon ({asr_time:.2f} sn):")
        print(f"      {text}")

        # Hizala
        match = align_transcription(text, corpus)
        conf = compute_confidence(text, match, corpus_vocab)

        if conf["score"] < MIN_CONFIDENCE:
            reason = conf.get("reason") or f"skor düşük ({conf['score']})"
            print(f"  ⊘ Kuran olarak sayılmadı: {reason}")
            print()
            continue

        # Başarılı
        if match:
            print(f"  ✓ KURAN TESPİT EDİLDİ (güven {conf['score']}/100)")
            print(f"      Fuzzy: {conf['fuzzy']:.0f}, Vocab: {conf['vocab_coverage']:.0%}, "
                  f"Kelime: {conf['word_count']}")
            print()
            print(f"  📖 {format_match(match, corpus)}")
        else:
            print(f"  ⊘ Kuran metninde eşleşme bulunamadı")
        print()


if __name__ == "__main__":
    main()
