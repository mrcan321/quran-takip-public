#!/usr/bin/env python3
"""
Kuran Tilavet Hizalama Prototipi
---------------------------------
Bir ses dosyasından Kuran tilavetini tanır ve hangi ayetin hangi kelimesine
denk geldiğini tespit eder.

Kullanım:
    python quran_align.py --audio tilavet.wav
    python quran_align.py --audio tilavet.wav --surah 1   # Fatiha ile sınırla
    python quran_align.py --record 10                      # 10 sn mikrofondan kaydet

Gereksinimler:
    pip install transformers torch librosa soundfile rapidfuzz pyarabic sounddevice
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import librosa
import numpy as np
import torch
from rapidfuzz import fuzz
from transformers import (
    GenerationConfig,
    WhisperForConditionalGeneration,
    WhisperProcessor,
)

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

MODEL_NAME = "tarteel-ai/whisper-base-ar-quran"
SAMPLE_RATE = 16000
QURAN_JSON_URL = (
    "https://api.alquran.cloud/v1/quran/quran-uthmani"  # sadece ilk indirmede
)
CACHE_DIR = Path.home() / ".cache" / "quran-align"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
QURAN_CACHE = CACHE_DIR / "quran-uthmani.json"


# ---------------------------------------------------------------------------
# Arapça metin normalizasyonu
# ---------------------------------------------------------------------------

# Arapça harekeler, tatvil, süsleme işaretleri - hizalama için temizliyoruz
ARABIC_DIACRITICS = re.compile(
    r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]"
)
# Hemze varyasyonlarını normalize et (أ إ آ ا -> ا), ta-marbuta -> ha vs.
NORMALIZATION_MAP = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ئ": "ي",
    "ؤ": "و",
    "ة": "ه",
})


def normalize_arabic(text: str) -> str:
    """Hareke, tatvil ve benzerleri temizle. Karşılaştırma için."""
    text = ARABIC_DIACRITICS.sub("", text)
    text = text.translate(NORMALIZATION_MAP)
    # Fazla boşlukları topla
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Kuran metin veritabanı
# ---------------------------------------------------------------------------

@dataclass
class QuranWord:
    surah: int
    ayah: int
    word_index: int  # ayetteki kelime sırası (0'dan)
    text: str        # orijinal (harekeli)
    normalized: str  # karşılaştırma için normalize edilmiş


class QuranCorpus:
    """Tüm Kuran'ı kelime listesi olarak tutar. Hizalama bunun üzerinde çalışır."""

    def __init__(self, words: List[QuranWord]):
        self.words = words
        # Hızlı erişim için normalize edilmiş tüm metin
        self.normalized_tokens = [w.normalized for w in words]

    @classmethod
    def load(cls) -> "QuranCorpus":
        """Lokal cache'den yükle, yoksa indir."""
        if not QURAN_CACHE.exists():
            print(f"Kuran metni ilk kez indiriliyor: {QURAN_JSON_URL}", file=sys.stderr)
            import urllib.request
            urllib.request.urlretrieve(QURAN_JSON_URL, QURAN_CACHE)

        with open(QURAN_CACHE, "r", encoding="utf-8") as f:
            data = json.load(f)

        words: List[QuranWord] = []
        for surah in data["data"]["surahs"]:
            s_num = surah["number"]
            for ayah in surah["ayahs"]:
                a_num = ayah["numberInSurah"]
                # Besmele'yi Fatiha dışında ayet başından çıkar (Tevbe hariç zaten yok)
                text = ayah["text"]
                tokens = text.split()
                for idx, tok in enumerate(tokens):
                    norm = normalize_arabic(tok)
                    if not norm:  # sadece hareke kalıntısıysa atla
                        continue
                    words.append(QuranWord(
                        surah=s_num, ayah=a_num,
                        word_index=idx, text=tok, normalized=norm,
                    ))
        print(f"Kuran yüklendi: {len(words)} kelime", file=sys.stderr)
        return cls(words)

    def filter_surah(self, surah: int) -> "QuranCorpus":
        """Sadece belirli bir sureyi içeren alt-korpus döndür."""
        filtered = [w for w in self.words if w.surah == surah]
        return QuranCorpus(filtered)


# ---------------------------------------------------------------------------
# ASR: Whisper ile transkripsiyon
# ---------------------------------------------------------------------------

class QuranASR:
    def __init__(self, model_name: str = MODEL_NAME, device: Optional[str] = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Model yükleniyor: {model_name} ({self.device})", file=sys.stderr)
        self.processor = WhisperProcessor.from_pretrained(model_name)
        self.model = WhisperForConditionalGeneration.from_pretrained(model_name).to(self.device)

        # Tarteel'in fine-tuned modeli eski generation_config ile kaydedilmiş;
        # base Whisper'ın güncel config'ini ödünç alalım (dil/görev/timestamp token'ları için).
        try:
            self.model.generation_config = GenerationConfig.from_pretrained(
                "openai/whisper-base"
            )
        except Exception as e:
            print(f"Uyarı: base generation_config yüklenemedi ({e}); "
                  f"dil argümanı çalışmayabilir.", file=sys.stderr)

        self.model.eval()

    # Özel Whisper token'larını metinden temizleyen regex.
    # skip_special_tokens=True bazen yetmiyor (ör. <|notimestamps|>), burada garantiliyoruz.
    _SPECIAL_TOKEN_RE = re.compile(r"<\|[^|]+\|>")

    def transcribe(self, audio: np.ndarray, sr: int) -> dict:
        """
        Ses dizisini al, Arapça transkripsiyon + kelime-seviyesi zaman damgaları döndür.

        Döndürdüğü dict:
            text  : str — tam transkripsiyon
            words : List[dict] — [{"word": "...", "start": 0.12, "end": 0.48}, ...]
                    (modelin verebildiği ölçüde; bazen boş olabilir)
        """
        if sr != SAMPLE_RATE:
            audio = librosa.resample(audio, orig_sr=sr, target_sr=SAMPLE_RATE)

        proc = self.processor(
            audio, sampling_rate=SAMPLE_RATE, return_tensors="pt",
            return_attention_mask=True,
        )
        input_features = proc.input_features.to(self.device)
        attention_mask = (
            proc.attention_mask.to(self.device) if "attention_mask" in proc else None
        )

        # Tek ve sade generate çağrısı. return_dict_in_generate vermiyoruz;
        # bu haliyle çıktı düz bir token tensor'üdür — decode'da sorun çıkmaz.
        with torch.no_grad():
            gen_kwargs = dict(
                language="ar",
                task="transcribe",
                return_timestamps="word",
                max_new_tokens=440,
            )
            if attention_mask is not None:
                gen_kwargs["attention_mask"] = attention_mask
            output = self.model.generate(input_features, **gen_kwargs)

        # output: torch.LongTensor (batch, seq_len)
        sequences = output

        # --- Düz metin ---
        clean_text = ""
        try:
            decoded = self.processor.batch_decode(sequences, skip_special_tokens=True)
            clean_text = decoded[0] if decoded else ""
        except Exception as e:
            print(f"Uyarı: metin decode başarısız ({e})", file=sys.stderr)

        clean_text = self._SPECIAL_TOKEN_RE.sub("", clean_text).strip()
        clean_text = re.sub(r"\s+", " ", clean_text)

        # --- Kelime-seviyesi timestamp ---
        # Whisper'ın batch_decode'u output_offsets=True ile kelime sınırlarını
        # ve zaman damgalarını "offsets" listesi olarak verir.
        words_with_times: List[dict] = []
        try:
            out = self.processor.batch_decode(
                sequences,
                skip_special_tokens=True,
                output_offsets=True,
                time_precision=0.02,  # Whisper granülaritesi (20ms)
            )
            # out yapısı sürüme göre biraz değişebilir:
            #  - [{"text": "...", "offsets": [...]}, ...]
            first = out[0] if isinstance(out, list) and out else out
            offsets = []
            if isinstance(first, dict):
                offsets = first.get("offsets") or []
            for o in offsets:
                ts = o.get("timestamp") or (None, None)
                text_piece = (o.get("text") or "").strip()
                text_piece = self._SPECIAL_TOKEN_RE.sub("", text_piece).strip()
                if not text_piece:
                    continue
                words_with_times.append({
                    "word": text_piece,
                    "start": ts[0] if len(ts) > 0 else None,
                    "end": ts[1] if len(ts) > 1 else None,
                })
        except Exception as e:
            print(f"Uyarı: kelime-zaman çıkarımı başarısız ({e})", file=sys.stderr)

        return {"text": clean_text, "words": words_with_times}


# ---------------------------------------------------------------------------
# Hizalama: transkripsiyonu Kuran metnine oturt
# ---------------------------------------------------------------------------

@dataclass
class AlignmentMatch:
    start_word_idx: int   # Kuran korpusundaki başlangıç indeksi
    end_word_idx: int     # (dahil) bitiş indeksi
    score: float          # 0-100 benzerlik skoru
    recited_text: str

    def describe(self, corpus: QuranCorpus) -> str:
        start = corpus.words[self.start_word_idx]
        end = corpus.words[self.end_word_idx]
        if start.surah == end.surah and start.ayah == end.ayah:
            return (
                f"Sure {start.surah}, Ayet {start.ayah}, "
                f"kelime {start.word_index+1}–{end.word_index+1}"
            )
        return (
            f"Sure {start.surah}:{start.ayah}:{start.word_index+1} → "
            f"{end.surah}:{end.ayah}:{end.word_index+1}"
        )


def align_transcription(
    transcription: str,
    corpus: QuranCorpus,
    window_slack: int = 5,
    preferred_range: Optional[Tuple[int, int]] = None,
    preferred_bonus: float = 8.0,
) -> Optional[AlignmentMatch]:
    """
    Transkripsiyon metninin Kuran korpusunda nereye denk geldiğini bul.

    Strateji: sliding window + partial ratio kombinasyonu.
    - partial_ratio: ASR birkaç kelimeyi atlasa/yanlış tanısa bile yakın eşleşmeyi yakalar
    - token_set_ratio: kelime sırası biraz kaysa sorun olmaz

    preferred_range: (start, end) verilirse o aralıktaki eşleşmelere bonus puan
                     eklenir. Pozisyon belleği için kullanılır — "kullanıcı Fatiha
                     3. ayetteydi, sonraki chunk da muhtemelen Fatiha civarında"
                     tahmini.
    preferred_bonus: Yakın aralık için eklenecek bonus (0-100 skoruna eklenir).
    """
    recited_tokens = [normalize_arabic(t) for t in transcription.split()]
    recited_tokens = [t for t in recited_tokens if t]
    if not recited_tokens:
        return None

    recited_joined = " ".join(recited_tokens)
    n = len(recited_tokens)

    best_score = -1.0
    best_raw_score = -1.0
    best_span: Tuple[int, int] = (0, 0)

    for window_size in range(max(1, n - window_slack), n + window_slack + 1):
        if window_size > len(corpus.normalized_tokens):
            continue
        for i in range(0, len(corpus.normalized_tokens) - window_size + 1):
            candidate = " ".join(corpus.normalized_tokens[i : i + window_size])
            partial = fuzz.partial_ratio(recited_joined, candidate)
            sorted_ = fuzz.token_sort_ratio(recited_joined, candidate)
            raw_score = 0.6 * partial + 0.4 * sorted_

            # Pozisyon belleği bonusu: eğer bu eşleşme "yakın bölge"deyse
            # küçük bir bonus ekleyerek tercih et.
            score = raw_score
            if preferred_range is not None:
                prange_start, prange_end = preferred_range
                if prange_start <= i <= prange_end:
                    score = min(100.0, raw_score + preferred_bonus)

            if score > best_score:
                best_score = score
                best_raw_score = raw_score
                best_span = (i, i + window_size - 1)
                if raw_score >= 98:
                    return AlignmentMatch(
                        start_word_idx=best_span[0],
                        end_word_idx=best_span[1],
                        score=raw_score,
                        recited_text=transcription,
                    )

    if best_raw_score < 40:
        # Çok düşük ham skor — muhtemelen Kuran değil
        return None

    return AlignmentMatch(
        start_word_idx=best_span[0],
        end_word_idx=best_span[1],
        score=best_raw_score,  # bonus'suz raw skor döndür ki güven hesabı tutarlı kalsın
        recited_text=transcription,
    )


# ---------------------------------------------------------------------------
# Ses yakalama (opsiyonel - mikrofondan kayıt)
# ---------------------------------------------------------------------------

def record_audio(seconds: float) -> Tuple[np.ndarray, int]:
    import sounddevice as sd
    print(f"{seconds} saniye kayıt başlıyor... şimdi okuyun.", file=sys.stderr)
    audio = sd.rec(
        int(seconds * SAMPLE_RATE),
        samplerate=SAMPLE_RATE, channels=1, dtype="float32",
    )
    sd.wait()
    print("Kayıt bitti.", file=sys.stderr)
    return audio.flatten(), SAMPLE_RATE


def load_audio(path: str) -> Tuple[np.ndarray, int]:
    audio, sr = librosa.load(path, sr=SAMPLE_RATE, mono=True)
    return audio, sr


# ---------------------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Kuran tilavet hizalama prototipi")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--audio", type=str, help="Ses dosyası (wav/mp3/flac)")
    src.add_argument("--record", type=float, help="Mikrofondan N saniye kaydet")
    parser.add_argument("--surah", type=int, help="Sadece belirli sure içinde ara (1-114)")
    parser.add_argument("--model", type=str, default=MODEL_NAME)
    args = parser.parse_args()

    # 1) Ses al
    if args.audio:
        audio, sr = load_audio(args.audio)
    else:
        audio, sr = record_audio(args.record)

    duration = len(audio) / sr
    print(f"Ses süresi: {duration:.1f} sn", file=sys.stderr)

    # 2) Modeli yükle ve transkribe et
    asr = QuranASR(args.model)
    t0 = time.time()
    result = asr.transcribe(audio, sr)
    print(f"Transkripsiyon süresi: {time.time() - t0:.1f} sn", file=sys.stderr)

    transcription = result["text"].strip()
    print("\n--- Transkripsiyon ---")
    print(transcription)

    # Kelime-seviyesi zaman damgaları (varsa)
    words = result.get("words") or []
    if words:
        print("\n--- Kelime-Zaman Damgaları ---")
        for w in words:
            start = w.get("start")
            end = w.get("end")
            if start is None or end is None:
                print(f"  {w['word']}  (timestamp yok)")
            else:
                print(f"  {start:6.2f}s - {end:6.2f}s   {w['word']}")

    # 3) Kuran korpusunu yükle (ve gerekirse süreye filtrele)
    corpus = QuranCorpus.load()
    if args.surah:
        corpus = corpus.filter_surah(args.surah)
        print(f"\nArama {args.surah}. sure ile sınırlandırıldı "
              f"({len(corpus.words)} kelime).", file=sys.stderr)

    # 4) Hizala
    t0 = time.time()
    match = align_transcription(transcription, corpus)
    print(f"Hizalama süresi: {time.time() - t0:.1f} sn", file=sys.stderr)

    print("\n--- Hizalama Sonucu ---")
    if match is None:
        print("Eşleşme bulunamadı (muhtemelen Kuran tilaveti değil ya da tanıma bozuk).")
        return

    print(f"Konum  : {match.describe(corpus)}")
    print(f"Skor   : {match.score:.1f}/100")
    print(f"Eşleşen kelimeler:")
    matched = corpus.words[match.start_word_idx : match.end_word_idx + 1]
    print("  " + " ".join(w.text for w in matched))


if __name__ == "__main__":
    main()
