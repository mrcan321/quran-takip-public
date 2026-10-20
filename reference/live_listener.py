"""
Canlı Kuran Tilavet Dinleyici (Akıllı Yarım Streaming)
--------------------------------------------------------
Mikrofonu sürekli dinler. Silero-VAD ile konuşma/sessizlik ayrımı yapar,
konuşma parçalarını Tarteel Whisper modeline gönderir, Kuran metnine
hizalar ve terminale basar.

Mimari:
    Mikrofon (frame frame)
        ↓
    Ring buffer (son ~10 sn)
        ↓
    Silero-VAD (her 512-sample frame için)
        ↓
    Segment oluştur (konuşma başı → kısa sessizlik = cümle sınırı)
        ↓
    ASR (Tarteel Whisper)
        ↓
    Güven filtresi (halüsinasyon tespiti)
        ↓
    Hizalama + pozisyon belleği
        ↓
    Terminal çıktısı (live)

Kullanım:
    python live_listener.py
    python live_listener.py --surah 1    # sadece Fatiha'da ara
    python live_listener.py --vad-threshold 0.6  # gürültülü ortam için

Durdurmak için Ctrl+C.

Gereksinimler:
    pip install transformers torch librosa soundfile rapidfuzz
                sounddevice numpy silero-vad
"""
import argparse
import queue
import signal
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import sounddevice as sd
import torch

# Mevcut scriptteki bileşenleri yeniden kullan
from quran_align import (
    QuranASR, QuranCorpus, QuranWord,
    align_transcription, normalize_arabic, AlignmentMatch,
)


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------
SAMPLE_RATE = 16000
VAD_FRAME_SAMPLES = 512       # Silero-VAD 16kHz için 512 sample bekler (32ms)

# Segment boyut kuralları — Whisper-base kısa parçalarda halüsinasyon yapıyor
MIN_SPEECH_SECONDS = 2.5      # Bundan kısa segmentler ASR'ye gitmesin
MAX_SEGMENT_SECONDS = 15.0    # Bu süreden uzun konuşma kesip gönder
SILENCE_HANGOVER_SECONDS = 1.2  # Bu kadar sessizlik = cümle bitti (önceki 0.7 çok kısaydı)
RING_BUFFER_SECONDS = 30.0

# Halüsinasyon filtreleme için eşikler
MIN_WORD_COUNT = 3            # En az 3 kelime çıkmadıysa güvensiz
MIN_CONFIDENCE = 60           # güven skoru eşiği (0-100)

# Pozisyon belleği
POSITION_MEMORY_SECONDS = 60  # Son 60 saniye içinde bulunan konum "yakın" sayılır
POSITION_SEARCH_RADIUS = 200  # Yakın konum civarında ±200 kelime öncelikli aranır


# ---------------------------------------------------------------------------
# Halüsinasyon / güven skoru
# ---------------------------------------------------------------------------

def compute_confidence(
    transcription: str,
    match: Optional[AlignmentMatch],
    corpus_vocab: set,
    duration_sec: float,
) -> dict:
    """
    Birkaç sinyali birleştiren güven skoru döndürür (0-100).

    Sinyaller:
      - fuzzy_score      : hizalama skoru (0-100)
      - vocab_coverage   : üretilen kelimelerin kaçı gerçekten Kuran'da
      - repetition_ok    : aynı kelime 3+ kere tekrarlıyor mu? (halüsinasyon)
      - length_ok        : ses süresine göre makul sayıda kelime üretildi mi?

    Döndürür:
      {confidence: float, signals: dict, reason: str}
    """
    tokens = [normalize_arabic(t) for t in transcription.split()]
    tokens = [t for t in tokens if t]

    if not tokens:
        return {"confidence": 0, "signals": {}, "reason": "boş transkripsiyon"}

    if len(tokens) < MIN_WORD_COUNT:
        return {
            "confidence": 0,
            "signals": {"word_count": len(tokens)},
            "reason": f"çok az kelime ({len(tokens)}<{MIN_WORD_COUNT})",
        }

    # 1) Fuzzy score
    fuzzy_score = match.score if match else 0

    # 2) Vocabulary coverage (Kuran'da var olan kelime oranı)
    in_vocab = sum(1 for t in tokens if t in corpus_vocab)
    vocab_coverage = in_vocab / len(tokens)

    # 3) Tekrar tespiti (halüsinasyon en belirgin işareti)
    unique_ratio = len(set(tokens)) / len(tokens)
    # aynı kelime art arda 3+ kere geçiyorsa ağır ceza
    max_consecutive = 1
    current = 1
    for i in range(1, len(tokens)):
        if tokens[i] == tokens[i - 1]:
            current += 1
            max_consecutive = max(max_consecutive, current)
        else:
            current = 1

    # 4) Uzunluk sağlığı (10sn'lik sesten 1 kelime çıkarsa şüpheli)
    # Tipik Kuran tilavetinde ~1 kelime/saniye (uzun med'ler dahil)
    expected_words = max(2, duration_sec * 0.6)
    length_ratio = min(1.0, len(tokens) / expected_words)

    # Birleşik skor
    # Temel: fuzzy_score. Düzeltmeler çarpan olarak uygulanır.
    confidence = fuzzy_score
    confidence *= vocab_coverage ** 0.5   # vocab düşükse ciddi düşüş
    confidence *= unique_ratio ** 0.3     # tekrar çoksa hafif düşüş
    confidence *= length_ratio ** 0.3     # çok kısaysa hafif düşüş

    # Sert red kuralları
    reason = ""
    if max_consecutive >= 3:
        confidence *= 0.3  # 3+ art arda tekrar = güçlü halüsinasyon sinyali
        reason = f"{max_consecutive}x tekrar"
    if vocab_coverage < 0.3:
        confidence *= 0.5
        reason = reason or f"vocab düşük ({vocab_coverage:.0%})"
    if len(tokens) == 1 and duration_sec > 3:
        confidence *= 0.2  # 3sn'den uzun sesten 1 kelime = sessizlik halüsinasyonu
        reason = reason or "tek kelime / uzun ses"

    return {
        "confidence": round(confidence, 1),
        "signals": {
            "fuzzy": fuzzy_score,
            "vocab_coverage": round(vocab_coverage, 2),
            "unique_ratio": round(unique_ratio, 2),
            "max_consecutive": max_consecutive,
            "length_ratio": round(length_ratio, 2),
            "word_count": len(tokens),
        },
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# VAD yükleme
# ---------------------------------------------------------------------------

def load_vad():
    """
    Silero-VAD modelini yükler.
    pip paketi (silero-vad) ONNX runtime üzerinden çalışır, torch.hub
    yerine bunu tercih ediyoruz (daha hafif, torchaudio bağımlılığı yok).
    """
    print("VAD modeli yükleniyor (silero-vad)...", file=sys.stderr)
    try:
        from silero_vad import load_silero_vad
    except ImportError as e:
        print(f"HATA: silero_vad paketi import edilemedi: {e}", file=sys.stderr)
        print("Kurulum: pip install silero-vad onnxruntime", file=sys.stderr)
        sys.exit(1)

    # ONNX önce — daha hafif ve Android'e taşınabilir.
    # Başarısız olursa JIT (PyTorch) sürümüne düşüyoruz.
    try:
        model = load_silero_vad(onnx=True)
        print("  (ONNX sürümü yüklendi)", file=sys.stderr)
        return model
    except Exception as e:
        print(f"  ONNX yüklenemedi ({type(e).__name__}: {e})", file=sys.stderr)
        print("  JIT (PyTorch) sürümüne geçiliyor...", file=sys.stderr)

    try:
        model = load_silero_vad(onnx=False)
        print("  (JIT sürümü yüklendi)", file=sys.stderr)
        return model
    except Exception as e:
        print(f"HATA: VAD modeli yüklenemedi: {type(e).__name__}: {e}",
              file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Ana dinleyici
# ---------------------------------------------------------------------------

class LiveListener:
    def __init__(
        self,
        asr: QuranASR,
        corpus: QuranCorpus,
        vad_model,
        vad_threshold: float = 0.5,
        surah: Optional[int] = None,
    ):
        self.asr = asr
        self.corpus = corpus
        self.vad_model = vad_model
        self.vad_threshold = vad_threshold
        self.surah = surah

        # Kuran kelime sözlüğü (hızlı vocab coverage kontrolü için)
        self.corpus_vocab = set(corpus.normalized_tokens)

        # Ring buffer — mikrofondan gelen sesi tutar
        self.ring = deque(
            maxlen=int(RING_BUFFER_SECONDS * SAMPLE_RATE / VAD_FRAME_SAMPLES)
        )

        # Durum makinesi
        self.in_speech = False
        self.current_segment: List[np.ndarray] = []
        self.silence_samples = 0  # sessiz frame birikimi (hangover için)

        # Ekrana basılan son pozisyon (tekrarları engellemek için)
        self.last_location_key: Optional[str] = None

        # Pozisyon belleği — "son başarılı eşleşme nerede, ne zaman?"
        # Bu bilgi sonraki segmentte önceliki arama bölgesi olarak kullanılır.
        self.last_match_end_idx: Optional[int] = None
        self.last_match_time: float = 0.0

        # Aynı sürede ardışık segmentleri "okuma oturumu" olarak grupla
        self.session_start_ayah: Optional[Tuple[int, int]] = None  # (sure, ayet)
        self.session_last_ayah: Optional[Tuple[int, int]] = None

        # Kuyruk: audio frame'leri callback → işleme thread
        self.audio_queue: queue.Queue = queue.Queue()
        self.running = True

    # -- Mikrofon callback'i (ayrı thread'de çalışır) --
    def audio_callback(self, indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}", file=sys.stderr)
        # indata shape: (frames, channels). Mono'ya düşür.
        mono = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
        self.audio_queue.put(mono)

    # -- VAD ile konuşma tespiti --
    def is_speech(self, frame: np.ndarray) -> bool:
        tensor = torch.from_numpy(frame).float()
        with torch.no_grad():
            prob = self.vad_model(tensor, SAMPLE_RATE).item()
        return prob >= self.vad_threshold

    # -- Segment ASR'ye gönder --
    def process_segment(self, audio: np.ndarray):
        duration = len(audio) / SAMPLE_RATE
        if duration < MIN_SPEECH_SECONDS:
            return  # çok kısa, yok say

        # Küçük bir işlem göstergesi (çok müdahaleci değil)
        print(f"\r  … {duration:.1f}sn işleniyor",
              end="", file=sys.stderr, flush=True)

        t0 = time.time()
        result = self.asr.transcribe(audio, SAMPLE_RATE)
        asr_time = time.time() - t0
        transcription = result["text"].strip()

        # İşlem göstergesini temizle
        print("\r" + " " * 40 + "\r", end="", file=sys.stderr, flush=True)

        if not transcription:
            return

        # Pozisyon belleğini hazırla — son başarılı eşleşme yakın zamandaysa
        # sonraki aramada o bölgeye bonus ver
        preferred_range = self._get_preferred_range()

        # Hizala
        match = align_transcription(
            transcription, self.corpus,
            preferred_range=preferred_range,
        )

        # Güven skoru
        conf = compute_confidence(
            transcription, match, self.corpus_vocab, duration,
        )

        if conf["confidence"] < MIN_CONFIDENCE:
            # Halüsinasyon veya Kuran değil — tek satır, sade bilgi
            reason = conf["reason"] or f"güven düşük"
            preview = transcription[:40] + ("…" if len(transcription) > 40 else "")
            print(f"·  [{_timestamp()}]  (Kuran değil: {reason})  {preview}",
                  file=sys.stderr, flush=True)
            return

        # Ekrana bas
        self._emit(transcription, match, conf, asr_time)

    def _get_preferred_range(self) -> Optional[Tuple[int, int]]:
        """Son eşleşme yakın zamandaysa arama için öncelikli bölge döndürür."""
        if self.last_match_end_idx is None:
            return None
        if time.time() - self.last_match_time > POSITION_MEMORY_SECONDS:
            return None  # çok eski, unut
        start = max(0, self.last_match_end_idx - POSITION_SEARCH_RADIUS)
        end = min(len(self.corpus.words) - 1,
                  self.last_match_end_idx + POSITION_SEARCH_RADIUS)
        return (start, end)

    # -- Ekrana yazdırma --
    def _emit(
        self,
        transcription: str,
        match: Optional[AlignmentMatch],
        conf: dict,
        asr_time: float,
    ):
        if not match:
            return

        location_key = f"{match.start_word_idx}-{match.end_word_idx}"
        if location_key == self.last_location_key:
            # Aynı yeri ikinci kere yazmayalım
            return
        self.last_location_key = location_key

        # Pozisyon belleğini güncelle
        self.last_match_end_idx = match.end_word_idx
        self.last_match_time = time.time()

        matched_words = self.corpus.words[match.start_word_idx : match.end_word_idx + 1]
        start = matched_words[0]
        end = matched_words[-1]

        # Oturum takibi: aynı sure içinde devam ediyor mu yoksa yeni okuma mı?
        current_ayah = (start.surah, start.ayah)
        continuing_session = (
            self.session_last_ayah is not None
            and self.session_last_ayah[0] == current_ayah[0]
            and abs(self.session_last_ayah[1] - current_ayah[1]) <= 2
        )

        if not continuing_session:
            # Yeni bir okuma oturumu başlıyor — ekrana belirgin ayraç koy
            self.session_start_ayah = current_ayah
            print("\n" + "═" * 72, flush=True)
            print(f"  [Yeni okuma — Sure {start.surah}]", flush=True)
            print("═" * 72, flush=True)

        self.session_last_ayah = (end.surah, end.ayah)

        if start.surah == end.surah and start.ayah == end.ayah:
            loc = (f"Sure {start.surah}:{start.ayah} "
                   f"(kelime {start.word_index+1}-{end.word_index+1})")
        else:
            loc = f"Sure {start.surah}:{start.ayah} → {end.surah}:{end.ayah}"

        matched_text = " ".join(w.text for w in matched_words)

        # Konuşkan olmayan, tek-satırlık çıktı — oturum içinde ardışık ayetler
        # daha akıcı görünür.
        print(f"\n✓ KURAN  [{_timestamp()}]  {loc}")
        print(f"         güven {conf['confidence']:.0f}/100, ASR {asr_time:.1f}s")
        print(f"         {matched_text}", flush=True)

    # -- Ana döngü --
    def run(self):
        print("\n" + "─" * 72, file=sys.stderr)
        print(f"  Dinleme başladı — Durdurmak için Ctrl+C", file=sys.stderr)
        print(f"  VAD eşiği: {self.vad_threshold}  |  "
              f"min segment: {MIN_SPEECH_SECONDS}sn  |  "
              f"güven eşiği: {MIN_CONFIDENCE}/100", file=sys.stderr)
        print("─" * 72, file=sys.stderr)
        print("  İşaretler:   ♪ = konuşma tespit edildi   "
              "·  = Kuran değil   ✓ = Kuran\n", file=sys.stderr, flush=True)

        last_heartbeat = time.time()
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=VAD_FRAME_SAMPLES,
            callback=self.audio_callback,
        )

        with stream:
            while self.running:
                try:
                    frame = self.audio_queue.get(timeout=0.5)
                except queue.Empty:
                    # Heartbeat: her 15sn'de bir "hâlâ dinliyorum" göster
                    if time.time() - last_heartbeat > 15:
                        print(f"·  [{_timestamp()}]  (dinliyor…)",
                              file=sys.stderr, flush=True)
                        last_heartbeat = time.time()
                    continue

                self.ring.append(frame)

                if len(frame) != VAD_FRAME_SAMPLES:
                    continue

                speech = self.is_speech(frame)

                if speech:
                    if not self.in_speech:
                        self.in_speech = True
                        self.current_segment = []
                        self.silence_samples = 0
                        print("♪", end="", flush=True, file=sys.stderr)
                        last_heartbeat = time.time()  # konuşma olursa heartbeat sıfırla
                    self.current_segment.append(frame)
                    self.silence_samples = 0
                else:
                    if self.in_speech:
                        self.current_segment.append(frame)
                        self.silence_samples += VAD_FRAME_SAMPLES
                        if self.silence_samples >= SILENCE_HANGOVER_SECONDS * SAMPLE_RATE:
                            self._finalize_segment()
                            last_heartbeat = time.time()

                if self.in_speech:
                    seg_samples = sum(len(f) for f in self.current_segment)
                    if seg_samples >= MAX_SEGMENT_SECONDS * SAMPLE_RATE:
                        self._finalize_segment()
                        last_heartbeat = time.time()

    def _finalize_segment(self):
        if self.current_segment:
            audio = np.concatenate(self.current_segment)
            # Ayrı thread'de işle ki mikrofon dinlemeye devam etsin
            threading.Thread(
                target=self.process_segment, args=(audio,), daemon=True,
            ).start()
        self.in_speech = False
        self.current_segment = []
        self.silence_samples = 0

    def stop(self):
        self.running = False


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def _timestamp() -> str:
    return time.strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--surah", type=int,
                        help="Sadece belirli sure içinde ara (1-114)")
    parser.add_argument("--vad-threshold", type=float, default=0.6,
                        help="Silero-VAD konuşma eşiği (0-1, varsayılan 0.6)")
    parser.add_argument("--model", type=str, default="tarteel-ai/whisper-base-ar-quran")
    args = parser.parse_args()

    # 1) Modeller
    asr = QuranASR(args.model)
    vad = load_vad()

    # 2) Korpus
    corpus = QuranCorpus.load()
    if args.surah:
        corpus = corpus.filter_surah(args.surah)
        print(f"(Arama {args.surah}. sure ile sınırlı — "
              f"{len(corpus.words)} kelime)", file=sys.stderr)

    # 3) Dinleyici
    listener = LiveListener(
        asr=asr, corpus=corpus, vad_model=vad,
        vad_threshold=args.vad_threshold,
        surah=args.surah,
    )

    # Ctrl+C ile temiz çıkış
    def sigint_handler(signum, frame):
        print("\n\nDinleme durduruldu.", file=sys.stderr)
        listener.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, sigint_handler)

    try:
        listener.run()
    except KeyboardInterrupt:
        listener.stop()


if __name__ == "__main__":
    main()
