"""
v0.3 — Namaz Akış Otomatı (parametrik ASR)
-----------------------------------------------
Kullanım:
  python app.py                       # default: fastconformer
  python app.py --asr fastconformer
  python app.py --asr whisper-tiny
  python app.py --asr whisper-base
  python app.py --asr faster-whisper
  python app.py --asr tadabur

Özellikler:
- Besmele filtreleme (aligner.py)
- Kilit terk: 6 ardışık miss → preferred_range geçici None
- İlk kilit için ARDIŞIK İKİ TUTARLI MATCH zorunluluğu (PendingMatch)
- MIN_WORD_COUNT_FIRST_LOCK = 3 (eskiden 4)
- BEKLEME'de aday penceresinde tutmayan chunk tum Kuran'da da aranir (aday degisir)
- Kilitliyken pencere emin degilse (<80) tum Kuran'da da aranir: sure gecisi (Fatiha sonu → zamm,
  sure sonu → sure basi hemen; digerleri bir sonraki chunk dogrularsa). Istiaze kelimeleri cikarilir.
- ASR motoru CLI argümanı ile değiştirilebilir
"""
import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple, Callable

import numpy as np
import soundfile as sf
from flask import Flask, render_template, request
from flask_sock import Sock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from aligner import (
    QuranCorpus, align_transcription, normalize_arabic,
)

# ============================================================
# CLI argparse
# ============================================================
parser = argparse.ArgumentParser()
parser.add_argument(
    "--asr",
    default="fastconformer",
    choices=["fastconformer", "whisper-tiny", "whisper-base",
             "faster-whisper", "tadabur"],
    help="ASR backend (default: fastconformer)"
)
parser.add_argument("--port", type=int, default=5000)
ARGS = parser.parse_args()

print(f"\n{'='*60}", file=sys.stderr)
print(f"  ASR Backend: {ARGS.asr}", file=sys.stderr)
print(f"{'='*60}\n", file=sys.stderr)

# ============================================================
# Konfigürasyon
# ============================================================
SAMPLE_RATE = 16000
CHUNK_DURATION_SEC = 5.0
OVERLAP_DURATION_SEC = 1.0
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION_SEC)
OVERLAP_SAMPLES = int(SAMPLE_RATE * OVERLAP_DURATION_SEC)

MIN_RMS_ENERGY = 0.005
MIN_WORD_COUNT_COLD = 3
MIN_WORD_COUNT_HOT = 2
# eval: 4 → 3 ile yavas okunan chunk'lar (tertil: 5 sn'de 3 kelime) kilit verir, yanlis kilit yok
MIN_WORD_COUNT_FIRST_LOCK = 3

MIN_CONFIDENCE = 55  # ayar denemesi 27.10 (tuning/run-10, K6): 50 → 55, zorlamada yanlis kilitli parca azaliyor
MIN_CONFIDENCE_FIRST_LOCK = 90

PREFERRED_AYAH_WINDOW_BASE = 2
PREFERRED_AYAH_WINDOW_MAX = 6
PREFERRED_AYAH_WINDOW_ARA = 3

ABANDON_LOCK_AFTER_LOST = 6
PENDING_VERIFY_AYAH_WINDOW = 4

PREFERRED_BONUS = 30
ARA_AFTER_LOST_CHUNKS = 12
MAX_GAP_FILL = 3

FATIHA_WORD_RANGE = (0, 30)
# Fatiha icinde geri gidilmez: pencere son eslesmenin bu kadar kelime gerisinden baslar ("الرحمن الرحيم"
# hem 1:1'de hem 1:3'te — 1:2'den sonra 1:1'e eslesip ekran geri zipliyordu)
FATIHA_BACK_WORDS = 3
SURAH_END_THRESHOLD = 2
# Fatiha'nin bu ayetinden sonra (6-7) pencere disi guclu eslesme = zamm suresine gecis (hemen)
FATIHA_END_AYAH = 6
# Kilitliyken pencere skoru bunun altindaysa tum Kuran'da da ara (sure gecisi / pencere cop eslesmesi)
JUMP_SEARCH_BELOW = 75  # ayar denemesi 27.10 (tuning/run-10, K6): 80 → 75
# Pencere disindaki eslesme pencereden en az bu kadar iyi olmali
JUMP_MARGIN = 15
# Namazda sesli okunan ilk sey Fatiha: BEKLEME'de Fatiha basina (1:1-3) bu kadar guclu eslesme
# (skor ve kelime) dogrulama beklemeden kilit verir (~5 sn erken). 3 kelime → ilahi yanlis kilit.
FATIHA_FAST_LOCK_MIN_SCORE = 85  # ayar denemesi 27.10 (tuning/run-10, K6): 90 → 85 (Rifai Tevbe Fatiha 5 sn erken)
FATIHA_FAST_LOCK_MIN_WORDS = 4
# Kilit kaybolduktan sonra (rukû/secde/sessiz rekat) yeniden kilit ilk kilit gibi dogrulamali; istisnalar:
# rekat basi Fatiha (herhangi bir ayet, skor >= FATIHA_FAST_LOCK_MIN_SCORE, >= MIN_WORD_COUNT_FIRST_LOCK kelime)
# ve kalinan yerden devam (ayni sure, son ayetin -RESUME_BACK..+PREFERRED_AYAH_WINDOW_ARA arasi)
RESUME_BACK = 2
# Dogal gecis noktasinda (Fatiha sonu / sure sonu) yavas okumada parcaya 2 kelime sigiyor ("لإيلاف قريش",
# "أعطيناك الكوثر"). 2 kelimelik parca da atlayabilir: ifade Kuran'da TEK yerde gecmeli, skor >=
# JUMP_SHORT_MIN_SCORE ve hedef dogal gecis olmali (Kotlin / build_state_machine_fixture ile birebir).
JUMP_SHORT_WORDS = 2
JUMP_SHORT_MIN_SCORE = 90
# Dogal gecis dogrulamasiz gecer, ama skor bunun altindaysa sadece aday (cuma: "لا يسمعون عصيس" → 7:100 74.5
# yanlis dogal gecis; eval'deki 28 dogru gecisin en dusugu 79.3). Kotlin / build_state_machine_fixture ile birebir.
NATURAL_MIN_SCORE = 77
# Sure basi (cuma #2): gecis noktasinda hizalama bir surenin acilisindan basliyorsa ham hizalama skoru (sozluk cezasiz)
# >= OPENING_MIN_FUZZY yeter → dogal gecis ("ألهاكم التجاد" → 102:1, "والعص إن الإنسان لعام" → 103:1-2; referans:
# scripts/build_state_machine_fixture.py)
OPENING_MIN_FUZZY = 75
OPENING_START_SLACK = 1
# Iki surenin acilisi ayni ifadeyse ("قل أعوذ برب" 113:1 / 114:1) dogal gecis tahmin etmez: eslesme ve baska suredeki
# ikinci yer sure acilisi, ham hizalama farki bundan azsa gecis adayi (referans: build_state_machine_fixture)
OPENING_TIE_MARGIN = 2.0
# Fatiha sonundaki dogal geciste en iyi eslesme ayet ortasindan basliyorsa ve ayet basindan baslayan ikinci yer en fazla bu
# kadar geride ise ikincisi alinir: imam zamm'a ayet basindan baslar (referans: build_state_machine_fixture)
AYAH_START_TIE_MARGIN = 2.0
# Huruf-u mukattaa (1. ayetin ilk kelimesi, normalize): ASR cogu zaman yazmiyor — ayet basi sayilirken atlanabilir
MUQATTAAT = {"الم", "المص", "الر", "المر", "كهيعص", "طه", "طسم", "طس", "يس", "ص", "حم", "ق", "ن"}
# Hatimle teravih: Fatiha sonunda onceki zamm'in kaldigi yerden devam (son zamm konumu .. +CONTINUE_AHEAD ayet, sure
# biterse sonraki surenin basina tasar) tum Kuran eslesmesinden en fazla CONTINUE_MARGIN kotu ve >= NATURAL_MIN_SCORE
# ise secilir (normal namazda 2. rekatta mushaf sirasiyla sonraki sure de buna uyar)
CONTINUE_AHEAD = 6
CONTINUE_MARGIN = 2.0
# Devam onceligi: devam penceresi >= ilk kilit esigi ve tum Kuran'dan en fazla bu kadar kotu ise (en iyi yer sure acilisi
# degilse) devam (yatsi 21.10: 21:24 "أم اتطعتم من دونه" → Yunus 10:38 77.3, devam penceresi 72.2)
CONTINUE_PRIOR_MARGIN = 6.0
# Fatiha sonunda sure acilisi onceligi: dogal gecis acilis olmayan yere oturduysa ilk kelimesi parcanin ilk 2 kelimesinden
# biri olan surelerin acilisi (1-2. ayet) tum Kuran'dan en fazla bu kadar kotuyse acilis (aksam 22.10: "قل يا أيها الرحم"
# 7:158 / 109:1 esit)
OPENING_PREFER_MARGIN = 1.0
# Taze gecisin yeniden kontrolu: Fatiha sonunda acilis / devam olmayan yere gecisten sonraki FRESH_JUMP_CHUNKS parcada
# pencere < MIN_CONFIDENCE ise (2 kelime de) tum Kuran; baska surenin 1-2. ayeti >= FRESH_JUMP_MIN_SCORE ve gecis
# parcasi o acilisa >= ilk kilit esigi oturuyorsa gecilir (aksam 22.10: "فما جاء النصر" 15:61 → "والله والفتح" 110:1)
FRESH_JUMP_CHUNKS = 2
FRESH_JUMP_MIN_SCORE = 80
# Erken Fatiha: zamm'da son saglam eslesmeden (>= 3 kelime, >= ilk kilit esigi) bu kadar parca gecmeden gelen, Fatiha'nin
# 1-2. ayetinde biten eslesme gecis adayi olur, sonraki parca dogrularsa gecilir (aksam 22.10: secde tekbiri basi ASR'de
# "الحمد لله رب العالمين" → "yeni rekat")
FATIHA_MIN_GAP_CHUNKS = 6
FATIHA_EARLY_MAX_AYAH = 2
# Gecis adayi varken yeni parca adayin +-PENDING_VERIFY_AYAH_WINDOW ayetinde tum Kuran eslesmesinden en fazla bu kadar
# kotu (ve >= ilk kilit esigi) eslesiyorsa aday dogrulanir
CANDIDATE_WINDOW_MARGIN = 2.0
# Namaz yapisi sinyalleri (namaz_signal): kamet/ezan → kilit sifirlanir + KAMET_HOLD_CHUNKS parca sadece Fatiha;
# selam (kilit yokken) → ayni sifirlama, RUKU_HOLD_CHUNKS; semiallah → ARA + RUKU_HOLD_CHUNKS parca sadece Fatiha
# ya da kalinan yerden devam (skor >= HOLD_RESUME_MIN_SCORE); tek basina tekbir sinyal degil (sadece atilir).
# Ayrintisi: scripts/build_state_machine_fixture.py.
KAMET_HOLD_CHUNKS = 12
RUKU_HOLD_CHUNKS = 24
# Tek parcada ilk kilit (fark payi): BEKLEME'de skor >= UNIQUE_LOCK_MIN_SCORE, >= UNIQUE_LOCK_MIN_WORDS kelime ve en iyi
# eslesmenin disindaki en iyi yer >= UNIQUE_LOCK_MARGIN geride → dogrulamasiz kilit (scripts/build_state_machine_fixture.py)
UNIQUE_LOCK_MIN_SCORE = 90
UNIQUE_LOCK_MIN_WORDS = 3
UNIQUE_LOCK_MARGIN = 8  # ayar denemesi 27.10 (tuning/run-10, K6): 12 → 8 (Celil / Collak Ihlas 5 sn erken)
# Ayirt edici kelime: fark >= EXCLUSIVE_LOCK_MARGIN ve parcada en iyi yerin ayetlerinde birebir gecip ikinci yerin
# ayetlerinde gecmeyen besmele disi bir kelime ("قل أعوذ برب الفلق": 113:1 / 114:1 farki 8.6, "الفلق") → tek parcada kilit
EXCLUSIVE_LOCK_MARGIN = 5
EXCLUSIVE_MIN_LETTERS = 3
BESMELE_TOKENS = {"بسم", "الله", "الرحمن", "الرحيم"}
# Birikmis metin: BEKLEME'de kilit vermeyen son SEARCH_CONCAT_CHUNKS parcanin metni yeni parcayla birlestirilip tum
# Kuran'da hizalanir, sadece tek parcada kilit kuralini gecerse kilit (yavas okuma: "خلق الإنسان" | "علمه البيان")
SEARCH_CONCAT_CHUNKS = 2
SEARCH_CONCAT_MAX_OVERLAP = 4
# BEKLEME'de aday dogrulamasi: pencere eslesmesi tum Kuran'daki en iyi yerden bu kadar zayifsa dogrulama sayilmaz
VERIFY_GLOBAL_MARGIN = 15
# ARA'da / kilidi kaybolmus zamm'da Fatiha yoklamasi pencere disindaki en iyi yerden bu kadar dusuk olsa da kazanir
FATIHA_ARA_MARGIN = 8
# BEKLEME'de (bekleme yokken) en iyi eslesme Fatiha disi ama belirsizse (ikinci yer AMBIGUOUS_MARGIN icinde) ve Fatiha'nin 1-3.
# ayetine >= FATIHA_FAST_LOCK_MIN_SCORE, en iyiden en fazla FATIHA_ARA_MARGIN kotu oturuyorsa Fatiha (yatsi 22.10: kamet onceki
# oturumda, "والحمد لله رب العالمين" 6:45 / 37:182 esit → Fatiha 5 sn gec). Bekleyen aday varken uygulanmaz (gurultu testi: asr
# 37:181 adayini 37:182 dogruluyordu)


def _runner_up_match(text, match):
    """En iyi eslesmenin araligina degmeyen en iyi ikinci yer (tum Kuran) ya da None."""
    return align_transcription(text, CORPUS, preferred_range=None, preferred_bonus=PREFERRED_BONUS,
                               exclude_range=(match.start_word_idx, match.end_word_idx))


def _match_ayah_words(match):
    """Eslesmenin kapsadigi ayetlerin tum normalize kelimeleri."""
    words = set()
    for s_, a_ in collect_verses(match.start_word_idx, match.end_word_idx):
        lo, hi = AYAH_TO_CORPUS_RANGE[(s_, a_)]
        for i in range(lo, hi + 1):
            words.update(CORPUS.words[i].normalized.split())
    return words


# Belirsiz aday (UI): BEKLEME / kilit kaybi adayinda ikinci yer bu kadar yakinsa aday ekranda gosterilmez
# (referans: build_state_machine_fixture.AMBIGUOUS_MARGIN)
AMBIGUOUS_MARGIN = 3.0


def is_ambiguous_candidate(text, match, score):
    ru = _runner_up_match(text, match)
    return bool(ru) and score - score_transcription(text, ru)[0] < AMBIGUOUS_MARGIN


def mark_ambiguous(result, text, match, score, pending):
    """Belirsiz aday → result["ambiguous"] + adaya ikinci yerin son ayeti (geriye dogrulama yasagi icin)."""
    ru = _runner_up_match(text, match)
    if ru and score - score_transcription(text, ru)[0] < AMBIGUOUS_MARGIN:
        result["ambiguous"] = True
        pending.alt_surah, pending.alt_ayah = collect_verses(ru.start_word_idx, ru.end_word_idx)[-1]


def is_unique_match(text, match, score, word_count):
    """Tek parcada kilit: ikinci yerden UNIQUE_LOCK_MARGIN fark ya da EXCLUSIVE_LOCK_MARGIN fark + ayirt edici kelime."""
    if score < UNIQUE_LOCK_MIN_SCORE or word_count < UNIQUE_LOCK_MIN_WORDS:
        return False
    ru = _runner_up_match(text, match)
    margin = score - (score_transcription(text, ru)[0] if ru else 0.0)
    if margin >= UNIQUE_LOCK_MARGIN:
        return True
    if margin < EXCLUSIVE_LOCK_MARGIN or ru is None:
        return False
    best, other = _match_ayah_words(match), _match_ayah_words(ru)
    return any(len(t) >= EXCLUSIVE_MIN_LETTERS and t not in BESMELE_TOKENS and t in best and t not in other
               for t in (bare_token(w) for w in text.split()))
HOLD_RESUME_MIN_SCORE = 80

RECORDINGS_DIR = Path(__file__).parent / "recordings"
RECORDINGS_DIR.mkdir(exist_ok=True)

CACHE_DIR = Path.home() / ".cache" / "quran-align"
from download_meal import MEAL_CACHE  # noqa: E402  (baski: tr.bulac, ayet ayet ayrik)
SURAH_NAMES_CACHE = CACHE_DIR / "surah-names.json"

app = Flask(__name__)
sock = Sock(app)


class NamazState(str, Enum):
    BEKLEME = "BEKLEME"
    FATIHA = "FATIHA"
    ZAMM = "ZAMM"
    ARA = "ARA"


@dataclass
class PendingMatch:
    surah: int
    ayah: int
    word_index: int
    chunk_index: int
    # Belirsiz aday: ikinci yerin son ayeti (referans: build_state_machine_fixture.PendingMatch)
    alt_surah: Optional[int] = None
    alt_ayah: Optional[int] = None


@dataclass
class SessionState:
    state: NamazState = NamazState.BEKLEME
    last_word_index: Optional[int] = None
    last_surah: Optional[int] = None
    last_ayah: Optional[int] = None
    lost_chunks: int = 0
    total_chunks: int = 0
    matched_chunks: int = 0
    state_transitions: List[str] = field(default_factory=list)
    pending_match: Optional[PendingMatch] = None
    # Kilitliyken pencere disinda bulunan aday konum (sure gecisi) — bir sonraki chunk dogrularsa gecilir
    jump_candidate: Optional[PendingMatch] = None
    # Kilitli suredeki en ileri ayet (geri dogru cop eslesmeler dogal gecis kararini bozmasin)
    max_ayah: Optional[int] = None
    # Namaz sinyali beklemesi (kamet / rukû / selam): bu parca indeksine kadar sadece Fatiha ya da kalinan yerden devam
    hold_until: Optional[int] = None
    # BEKLEME'de kilit vermeyen son parcalarin temiz metni: [(parca indeksi, metin)] — bkz. SEARCH_CONCAT_CHUNKS
    search_texts: List[Tuple[int, str]] = field(default_factory=list)
    # Son zamm konumu (hatimle teravihte sonraki rekat buradan devam eder) — selam/kamette silinmez
    zamm_surah: Optional[int] = None
    zamm_ayah: Optional[int] = None
    # Son "sadece tekbir" parcasinin indeksi — bkz. TEKBIR_TEVHID_CHUNKS
    last_tekbir_chunk: Optional[int] = None
    # Fatiha sonundaki taze (acilis / devam olmayan) dogal gecis: (parca indeksi, temiz metin) — bkz. FRESH_JUMP_CHUNKS
    fresh_jump: Optional[Tuple[int, str]] = None
    # Son kabul edilen eslesmenin parca indeksi — bkz. TILAVET_END_NAMAZ_GAP
    last_match_chunk: Optional[int] = None
    # Son saglam (>= MIN_WORD_COUNT_FIRST_LOCK kelime, >= ilk kilit esigi) eslesmenin parca indeksi — bkz. FATIHA_MIN_GAP_CHUNKS
    last_solid_chunk: Optional[int] = None


# ============================================================
# ASR backend yükleme
# ============================================================
ASR_TRANSCRIBE_FN: Optional[Callable[[np.ndarray], str]] = None


def _load_fastconformer():
    import nemo.collections.asr as nemo_asr
    print("FastConformer Large yukleniyor...", file=sys.stderr)
    t0 = time.time()
    model = nemo_asr.models.EncDecHybridRNNTCTCBPEModel.from_pretrained(
        model_name="nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0",
    ).to("cpu")
    model.eval()
    model.change_decoding_strategy(decoder_type="rnnt")
    print(f"FastConformer hazir ({time.time() - t0:.1f}s)", file=sys.stderr)

    import tempfile

    def transcribe(audio_np):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, audio_np, SAMPLE_RATE)
            tmp_path = tmp.name
        try:
            output = model.transcribe([tmp_path], verbose=False)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        if not output:
            return ""
        if hasattr(output[0], "text"):
            return output[0].text.strip()
        if isinstance(output[0], str):
            return output[0].strip()
        if isinstance(output[0], list) and output[0]:
            first = output[0][0]
            return (first.text if hasattr(first, "text") else str(first)).strip()
        return ""

    return transcribe


def _load_whisper_transformers(model_id, label):
    from transformers import WhisperProcessor, WhisperForConditionalGeneration
    import torch
    print(f"{label} yukleniyor ({model_id})...", file=sys.stderr)
    t0 = time.time()
    proc = WhisperProcessor.from_pretrained(model_id)
    model = WhisperForConditionalGeneration.from_pretrained(model_id)
    model.eval()
    forced_ids = proc.get_decoder_prompt_ids(language="arabic", task="transcribe")
    model.config.forced_decoder_ids = forced_ids
    model.generation_config.forced_decoder_ids = forced_ids
    if hasattr(model.generation_config, "language"):
        model.generation_config.language = None
    if hasattr(model.generation_config, "task"):
        model.generation_config.task = None
    print(f"{label} hazir ({time.time() - t0:.1f}s)", file=sys.stderr)

    def transcribe(audio_np):
        inputs = proc(audio_np, sampling_rate=SAMPLE_RATE, return_tensors="pt")
        with torch.no_grad():
            ids = model.generate(inputs.input_features)
        return proc.batch_decode(ids, skip_special_tokens=True)[0].strip()

    return transcribe


def _load_faster_whisper():
    from faster_whisper import WhisperModel
    print("faster-whisper-base yukleniyor...", file=sys.stderr)
    t0 = time.time()
    model = WhisperModel(
        "OdyAsh/faster-whisper-base-ar-quran",
        device="cpu",
        compute_type="int8",
    )
    print(f"faster-whisper hazir ({time.time() - t0:.1f}s)", file=sys.stderr)

    def transcribe(audio_np):
        segments, _ = model.transcribe(audio_np, language="ar", beam_size=1)
        return " ".join(s.text for s in segments).strip()

    return transcribe


# Backend seçimi
if ARGS.asr == "fastconformer":
    ASR_TRANSCRIBE_FN = _load_fastconformer()
elif ARGS.asr == "whisper-tiny":
    ASR_TRANSCRIBE_FN = _load_whisper_transformers(
        "tarteel-ai/whisper-tiny-ar-quran", "Whisper-tiny (Tarteel)"
    )
elif ARGS.asr == "whisper-base":
    ASR_TRANSCRIBE_FN = _load_whisper_transformers(
        "tarteel-ai/whisper-base-ar-quran", "Whisper-base (Tarteel)"
    )
elif ARGS.asr == "faster-whisper":
    ASR_TRANSCRIBE_FN = _load_faster_whisper()
elif ARGS.asr == "tadabur":
    ASR_TRANSCRIBE_FN = _load_whisper_transformers(
        "FaisaI/Tadabur-Whisper-Small", "Tadabur Whisper-Small"
    )

ASR_LABEL = {
    "fastconformer": "FastConformer Large",
    "whisper-tiny": "Whisper-tiny (Tarteel)",
    "whisper-base": "Whisper-base (Tarteel)",
    "faster-whisper": "faster-whisper-base (Tarteel int8)",
    "tadabur": "Tadabur Whisper-Small",
}[ARGS.asr]


# ============================================================
# Korpus, meal, sure isimleri
# ============================================================
print("Kuran korpusu yukleniyor...", file=sys.stderr)
CORPUS = QuranCorpus.load()
CORPUS_VOCAB = CORPUS.vocab  # imla'i parcalar ("يا ايها" → يا, ايها)
print("Korpus hazir.", file=sys.stderr)

AYAH_TO_CORPUS_RANGE = {}
for idx, w in enumerate(CORPUS.words):
    key = (w.surah, w.ayah)
    if key not in AYAH_TO_CORPUS_RANGE:
        AYAH_TO_CORPUS_RANGE[key] = [idx, idx]
    else:
        AYAH_TO_CORPUS_RANGE[key][1] = idx

SURAH_AYAH_COUNTS = {}
for w in CORPUS.words:
    prev = SURAH_AYAH_COUNTS.get(w.surah, 0)
    if w.ayah > prev:
        SURAH_AYAH_COUNTS[w.surah] = w.ayah

with open(MEAL_CACHE, "r", encoding="utf-8") as f:
    MEALS = json.load(f)
with open(SURAH_NAMES_CACHE, "r", encoding="utf-8") as f:
    SURAH_NAMES = json.load(f)
print(f"Meal+sure isimleri hazir.", file=sys.stderr)


# ============================================================
# Yardimcilar
# ============================================================
def compute_rms(audio_np: np.ndarray) -> float:
    if len(audio_np) == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio_np ** 2)))


def transcribe_chunk(audio_np: np.ndarray):
    timings = {}
    t0 = time.time()
    text = ASR_TRANSCRIBE_FN(audio_np)
    timings["asr_total"] = time.time() - t0
    return text, timings


def score_transcription(text: str, match) -> Tuple[float, dict]:
    tokens = [normalize_arabic(t) for t in text.split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return 0.0, {"reason": "bos", "word_count": 0}

    fuzzy = match.score if match else 0
    in_vocab = sum(1 for t in tokens if t in CORPUS_VOCAB)
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

    score = fuzzy * (vocab_coverage ** 0.5) * (unique_ratio ** 0.3)
    reason = ""
    if max_consec >= 3:
        score *= 0.3
        reason = f"{max_consec}x tekrar"
    if vocab_coverage < 0.3:
        score *= 0.5
        reason = reason or f"vocab dusuk ({vocab_coverage:.0%})"

    return round(score, 1), {
        "fuzzy": fuzzy,
        "vocab_coverage": round(vocab_coverage, 2),
        "word_count": len(tokens),
        "reason": reason,
    }


def get_surah_info(surah_num: int) -> dict:
    info = SURAH_NAMES.get(str(surah_num), {})
    return {
        "number": surah_num,
        "name_tr": info.get("turkish", f"Sure {surah_num}"),
        "name_ar": info.get("arabic", ""),
        "name_en": info.get("english", ""),
    }


def collect_verses(start_idx: int, end_idx: int):
    seen = set()
    verses = []
    for i in range(start_idx, end_idx + 1):
        w = CORPUS.words[i]
        key = (w.surah, w.ayah)
        if key not in seen:
            seen.add(key)
            verses.append(key)
    return verses


def build_verse_payload(surah: int, ayah: int,
                        match_start_idx: Optional[int] = None,
                        match_end_idx: Optional[int] = None):
    ayah_range = AYAH_TO_CORPUS_RANGE.get((surah, ayah))
    if ayah_range is None:
        return {
            "surah": surah, "ayah": ayah,
            "surah_name_tr": get_surah_info(surah)["name_tr"],
            "surah_name_ar": get_surah_info(surah)["name_ar"],
            "arabic_words": [],
            "meal": MEALS.get(f"{surah}:{ayah}", ""),
        }
    ayah_start, ayah_end = ayah_range
    arabic_words = []
    for corpus_idx in range(ayah_start, ayah_end + 1):
        w = CORPUS.words[corpus_idx]
        is_highlighted = False
        if match_start_idx is not None and match_end_idx is not None:
            is_highlighted = (match_start_idx <= corpus_idx <= match_end_idx)
        arabic_words.append({"text": w.text, "highlighted": is_highlighted})
    surah_info = get_surah_info(surah)
    return {
        "surah": surah, "ayah": ayah,
        "surah_name_tr": surah_info["name_tr"],
        "surah_name_ar": surah_info["name_ar"],
        "arabic_words": arabic_words,
        "meal": MEALS.get(f"{surah}:{ayah}", ""),
    }


def is_near_surah_end(surah: int, ayah: int) -> bool:
    if surah not in SURAH_AYAH_COUNTS:
        return False
    return (SURAH_AYAH_COUNTS[surah] - ayah) < SURAH_END_THRESHOLD


def _continue_window(surah: int, ayah: int) -> Optional[Tuple[int, int]]:
    """Hatim devam penceresi: son zamm ayeti .. +CONTINUE_AHEAD ayet; sure biterse sonraki surenin basina tasar."""
    total = SURAH_AYAH_COUNTS.get(surah)
    if not total or (surah, ayah) not in AYAH_TO_CORPUS_RANGE:
        return None
    start = AYAH_TO_CORPUS_RANGE[(surah, ayah)][0]
    end_ayah = ayah + CONTINUE_AHEAD
    if end_ayah <= total:
        return (start, AYAH_TO_CORPUS_RANGE[(surah, end_ayah)][1])
    if surah + 1 in SURAH_AYAH_COUNTS:
        return (start, AYAH_TO_CORPUS_RANGE[(surah + 1, min(SURAH_AYAH_COUNTS[surah + 1], end_ayah - total))][1])
    return (start, AYAH_TO_CORPUS_RANGE[(surah, total)][1])


def _ayah_window(surah: int, ayah: int, back: int, forward: int) -> Optional[Tuple[int, int]]:
    if surah not in SURAH_AYAH_COUNTS:
        return None
    total_ayahs = SURAH_AYAH_COUNTS[surah]
    start_ayah = max(1, ayah - back)
    end_ayah = min(total_ayahs, ayah + forward)
    start_range = AYAH_TO_CORPUS_RANGE.get((surah, start_ayah))
    end_range = AYAH_TO_CORPUS_RANGE.get((surah, end_ayah))
    if start_range is None or end_range is None:
        return None
    return (start_range[0], end_range[1])


def compute_preferred_range(state: SessionState) -> Optional[Tuple[int, int]]:
    if state.lost_chunks >= ABANDON_LOCK_AFTER_LOST:
        return None
    if state.state == NamazState.BEKLEME and state.pending_match is not None:
        pm = state.pending_match
        window = _ayah_window(pm.surah, pm.ayah,
                              back=PENDING_VERIFY_AYAH_WINDOW,
                              forward=PENDING_VERIFY_AYAH_WINDOW)
        if window is not None:
            return window
    if state.state == NamazState.FATIHA:
        # Pencere Fatiha'nin son kelimesinde biter (FATIHA_WORD_RANGE 30'a kadar Bakara 2:1-2'yi de kapsiyordu)
        f_end = AYAH_TO_CORPUS_RANGE[(1, 7)][1] if (1, 7) in AYAH_TO_CORPUS_RANGE else FATIHA_WORD_RANGE[1]
        start = FATIHA_WORD_RANGE[0]
        lw = state.last_word_index
        if lw is not None and start <= lw <= f_end:
            start = max(start, lw - FATIHA_BACK_WORDS)
        return (start, f_end)
    if state.state == NamazState.ZAMM:
        if state.last_word_index is None:
            return None
        if state.last_surah is not None and state.last_ayah is not None:
            adaptive_window = min(
                PREFERRED_AYAH_WINDOW_BASE + state.lost_chunks,
                PREFERRED_AYAH_WINDOW_MAX,
            )
            window = _ayah_window(state.last_surah, state.last_ayah,
                                  back=0, forward=adaptive_window)
            if window is not None:
                return window
        return (state.last_word_index, state.last_word_index + 60)
    if state.state == NamazState.ARA:
        if state.last_surah is not None and state.last_ayah is not None:
            window = _ayah_window(state.last_surah, state.last_ayah,
                                  back=2, forward=PREFERRED_AYAH_WINDOW_ARA)
            if window is not None:
                return window
        if state.last_word_index is not None:
            return (max(0, state.last_word_index - 30),
                    state.last_word_index + 90)
        return None
    return None


def transition_state(state: SessionState, matched: bool,
                     first_surah: Optional[int],
                     first_ayah: Optional[int]) -> NamazState:
    current = state.state
    if matched:
        # Fatiha'nin herhangi bir ayeti (2. rekat Fatiha'si ortasindan da yakalanabilir: 1:4) → FATIHA
        if first_surah == 1:
            return NamazState.FATIHA
        if current == NamazState.FATIHA:
            if first_surah == 1:
                return NamazState.FATIHA
            return NamazState.ZAMM
        if current in (NamazState.ZAMM, NamazState.ARA, NamazState.BEKLEME):
            return NamazState.ZAMM
    else:
        if current in (NamazState.FATIHA, NamazState.ZAMM):
            if state.lost_chunks >= ARA_AFTER_LOST_CHUNKS:
                return NamazState.ARA
    return current


CORPUS_TOKENS = [t for w in CORPUS.words for t in w.normalized.split()]


def phrase_count(tokens, limit: int = 2) -> int:
    """Normalize kelime dizisi korpusta birebir kac kez geciyor (limit'te durur)."""
    n = len(tokens)
    if n == 0:
        return 0
    c = 0
    for i in range(len(CORPUS_TOKENS) - n + 1):
        if CORPUS_TOKENS[i] == tokens[0] and CORPUS_TOKENS[i:i + n] == tokens:
            c += 1
            if c >= limit:
                break
    return c


def at_transition_point(state: SessionState) -> bool:
    """Kilitli surede dogal gecis noktasinda miyiz: Fatiha sonu ya da zamm suresinin son ayetleri."""
    far = state.max_ayah or state.last_ayah or 0
    if state.state == NamazState.FATIHA:
        return state.last_surah == 1 and far >= FATIHA_END_AYAH
    if state.state == NamazState.ZAMM and state.last_surah and far:
        return is_near_surah_end(state.last_surah, far)
    return False


def is_natural_transition(state: SessionState, surah: int, ayah: int) -> bool:
    """Kilitliyken dogal gecis noktasi mi (dogrulama beklemeden gecilir):
    Fatiha sonu → baska herhangi bir yer (zamm suresi), sure sonu → bir surenin 1-2. ayeti."""
    far = state.max_ayah or state.last_ayah or 0
    if state.state == NamazState.FATIHA:
        return surah != 1 and state.last_surah == 1 and far >= FATIHA_END_AYAH
    if state.state in (NamazState.ZAMM, NamazState.ARA) and state.last_surah and far:
        return ayah <= 2 and is_near_surah_end(state.last_surah, far)
    return False


def _cleanup_stale_candidates(state: SessionState, chunk_index: int):
    # Aday BEKLEME'de ve kilit kaybolduktan sonraki yeniden kilitte olusur; 2 chunk icinde dogrulanmazsa biter
    if state.pending_match is not None:
        if chunk_index - state.pending_match.chunk_index >= 2:
            state.pending_match = None
    if state.jump_candidate is not None and chunk_index - state.jump_candidate.chunk_index >= 2:
        state.jump_candidate = None


# Istiaze ayet degil ama "من الشيطان الرجيم" 16:98'e aday uretiyordu. Chunk sinirinda bolunebilir:
# "الشيطان" iceren >=3 kelimelik ardisik parcalari cikar.
ISTIAZE_TOKENS = ["اعوذ", "بالله", "من", "الشيطان", "الرجيم"]
ISTIAZE_KEY = 3  # "الشيطان"


def strip_istiaze(text: str) -> Tuple[str, int]:
    words = text.split()
    norms = [normalize_arabic(w) for w in words]
    keep, removed, i = [], 0, 0
    while i < len(words):
        best = 0
        for a in range(len(ISTIAZE_TOKENS)):
            n = 0
            while a + n < len(ISTIAZE_TOKENS) and i + n < len(norms) and norms[i + n] == ISTIAZE_TOKENS[a + n]:
                n += 1
            if n >= 3 and a <= ISTIAZE_KEY < a + n and n > best:
                best = n
        if best:
            i += best
            removed += best
        else:
            keep.append(words[i])
            i += 1
    return " ".join(keep), removed


# Namaz zikirleri Kuran degil ama ayete "eslesiyordu" (gercek aksam namazi kaydi, 27.09): selam → 6:54,
# "سمع الله لمن حمده" → 3:181. Kuran'da "السلام عليكم/عليك" ve "ربنا (و)لك الحمد" hic gecmiyor, "سمع الله" hep
# "قول" ile devam ediyor → cikarilir. "الله اكبر" 3 ayette geciyor → sadece parca tamamen tekbirse atilir.
SELAM_TAIL = {"و", "ورحمه", "رحمه", "الله", "وبركاته", "بركاته"}
SELAM_MAX_WORDS = 5
# ASR sessizlik/gurultu/tekbirde video girisi uyduruyor ("شركة الهدى للخدمات التقنية", "موسوعة النابلسي",
# "لا تنسوا مشاركة ..."); bu kelimeler Kuran'da yok → iceren parca bos sayilir.
ASR_HALLUCINATION_TOKENS = {"شركه", "للخدمات", "الخدمات", "التقنيه", "موسوعه", "النابلسي", "مشاركه",
                            "لاتنسوا", "للاعجاب"}
# Namaz sonu duasi (imam, selamdan hemen sonra): "اللهم انت السلام ومنك السلام تباركت يا ذا الجلال والاكرام".
# Gercek namaz #2 (01.10): "السلام منك السلام" → 59:23 ADAY, "تباركت يا ذا الجلال والاكرام" → 55:27 ADAY.
# Kuran'da "انت السلام", "(و)منك السلام", "تباركت", "ذا الجلال" yok (korpusla dogrulandi; Kuran'da ذو/ذي الجلال)
# → cikarilir. Dua basi parcada kaldiysa ("اللهم انت السلام") geriye dogru da silinir.
DUA_HEAD = {"اللهم", "انت", "السلام"}
DUA_TAIL = {"يا", "ذا", "ذو", "ذي", "الجلال", "والاكرام"}
DUA_HEAD_MAX = 3
# Tek kelimelik ASR uydurmasi: tekbir/gurultu/titresimde "المصدر كتاب", "المصدر صور من" (namaz #2'de 8 kez, ezanda da).
# "المصدر" Kuran'da yok; sadece kelime cikarilir (kalan kisa parca too_short olur, "كتاب" 13:43'e eslesmez).
ASR_NOISE_WORDS = {"المصدر"}
# Ders girisi uydurmasi ("تفسير سورة الأعراف الدرس الثامن ...", "نهاية الدرس"), cogu zaman gercek okumayla ayni parcada:
# "تفسير", "الدرس", "نهاية" ve siralama kelimeleri Kuran'da yok → sadece giris kelimeleri cikarilir (referans:
# build_state_machine_fixture.LECTURE_ORDINAL_PREFIXES)
LECTURE_ORDINAL_PREFIXES = ("الاول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع", "الثامن", "التاسع",
                            "العاشر", "الثلا", "العشر", "الاربع")
# Tekbir: ASR "الله اغبر" de yaziyor. Kamet / ezan: Kuran'da HIC gecmeyen kelime ve ikililer (korpusla dogrulandi).
TEKBIR_WORDS = {"اكبر", "اغبر", "اكبار"}
# Bozuk semiallah ("يدع الله لمن حمده", "سمع القول لمن حمد"): "لمن حمد…" ve "حمده" Kuran'da yok; onundeki en fazla
# SEMIALLAH_HEAD_MAX kisa kelime (<= SEMIALLAH_HEAD_LEN harf) da atilir
SEMIALLAH_HEAD_MAX = 2
SEMIALLAH_HEAD_LEN = 5
# Tek basina semiallah sonu ("حمده", "حميده"); "لمن حم…" (Kuran'da "لمن"den sonra sadece "حارب", "حوله"; yatsi 22.10 "لمَن حميده")
SEMIALLAH_TAIL = {"حمده", "حميده"}
KAMET_WORDS = {"الفلاح", "قامت", "محمدا"}
KAMET_PAIRS = {("اشهد", "ان"), ("اشهد", "انه"), ("اشهد", "لا"), ("ان", "محمد"), ("الله", "محمد"), ("قد", "قام"),
               ("قام", "الصلاه"), ("قام", "بالصلاه"), ("حي", "علي"), ("حي", "الصلاه"), ("الصلاه", "حي"),
               ("حي", "الفلاح"), ("الصلاه", "خير"), ("من", "النوم"),
               ("علي", "الصلاه"), ("خير", "الصلاه"), ("مضت", "الصلاه")}   # cuma #2: "خير الصلاة على الصلاة", "مضت الصلاة"
_NON_LETTER = re.compile(r"[^\u0621-\u064A]")
# Felak "قل أعوذ برب الفلق" → ASR "أعوذ برب الفلاح" kamet degil (yatsi 19.10 vaazi)
FALAQ_PREV = {"برب", "رب"}
# Aksam 26.10: rukûdan kalkista tek basina "محمدا" ("ربنا لك الحمد حمدا…") kamet sayiliyordu; kamet / ezanda hep "ان" ile
MUHAMMAD_PREV = {"ان", "وان", "انه", "اشهد", "واشهد"}
MUHAMMAD_NEXT_PREFIXES = ("رسول", "ورسول", "عبد", "وعبد")


def is_kamet_word(toks, i):
    """toks[i] kamet kelimesi mi ("الفلاح" Felak'ta degil, "محمدا" sadece sehadet baglaminda)."""
    t = toks[i]
    if t not in KAMET_WORDS:
        return False
    if t == "الفلاح":
        return not (i > 0 and toks[i - 1] in FALAQ_PREV)
    if t == "محمدا":
        return (i > 0 and toks[i - 1] in MUHAMMAD_PREV) or \
            (i + 1 < len(toks) and toks[i + 1].startswith(MUHAMMAD_NEXT_PREFIXES))
    return True


def bare_token(word: str) -> str:
    return _NON_LETTER.sub("", normalize_arabic(word))


def is_asr_hallucination(text: str) -> bool:
    return any(bare_token(w) in ASR_HALLUCINATION_TOKENS for w in text.split())


# Uydurma ifade gercek okumayla ayni parcada (sabah 21.10: "والحمد لله رب العالمين شركة الهدى للخدمات التقنية"):
# "شركة" / "موسوعة" + marka kelimesi + devam kelimeleri cikarilir; kalan (istiaze / namaz zikirleri haric) en az
# MIN_WORD_COUNT_FIRST_LOCK kelimeyse o metin, yoksa bos (referans: build_state_machine_fixture.strip_asr_hallucination)
HALLUCINATION_HEADS = {"شركه", "موسوعه"}
HALLUCINATION_CONT = {"للخدمات", "الخدمات", "التقنيه", "التاريخ", "التاريخيه", "للعلوم", "الاسلاميه", "للبناء",
                      "للنوم", "للاعجاب", "شريك"}
# Tilavet sonu "صدق الله العظيم" (Kuran'da yok): ifade cikarilir, kilit / adaylar biter (asr 21.10). Son saglam eslesmeden
# sonra tekbir duyulduysa (namazda rukû / secde) ve son eslesmeden en az TILAVET_END_NAMAZ_GAP parca gectiyse sadece cikarilir
# (yatsi 22.10: secdede, son eslesmeden 8 parca sonra uydurma; asr 21.10'da gercek tilavet sonu 2 parca sonra)
TILAVET_END_NAMAZ_GAP = 5
TILAVET_END = ("صدق", "الله", "العظيم")


def tekbir_after_reading(state) -> bool:
    """Son saglam eslesmeden sonra tekbir duyuldu mu (namazda rukû / secde) — bkz. TILAVET_END."""
    return (state.last_tekbir_chunk is not None and state.last_solid_chunk is not None
            and state.last_tekbir_chunk > state.last_solid_chunk)


def strip_tilavet_end(text: str) -> Tuple[str, bool]:
    words = text.split()
    toks = [bare_token(w) for w in words]
    n = len(TILAVET_END)
    for i in range(len(toks) - n + 1):
        if tuple(toks[i:i + n]) == TILAVET_END:
            return " ".join(words[:i] + words[i + n:]), True
    return text, False


def strip_asr_hallucination(text: str) -> str:
    if not text or not is_asr_hallucination(text):
        return text
    words = text.split()
    out = []
    i = 0
    while i < len(words):
        if bare_token(words[i]) in HALLUCINATION_HEADS:
            i += 2
            while i < len(words) and bare_token(words[i]) in HALLUCINATION_CONT:
                i += 1
            continue
        out.append(words[i])
        i += 1
    rest = " ".join(out)
    if not rest or is_asr_hallucination(rest):
        return ""
    t, _ = strip_istiaze(rest)
    t, _ = strip_namaz_phrases(t)
    if len([w for w in (normalize_arabic(x) for x in t.split()) if w]) < MIN_WORD_COUNT_FIRST_LOCK:
        return ""
    return rest


# Kuran'da gecen ama namazda / ezan-kamette / sohbette tek basina soylenen ifadeler: zamm kilitli degilken parca
# sadece bunlardan biriyse (+ en fazla DHIKR_EXTRA_MAX kelime) bos sayilir; kelime-i sehadet BEKLEME'de kamet sayilir,
# bekleme surerken gelen zikir beklemeyi uzatir (referans: build_state_machine_fixture.DHIKR_PHRASES)
# + ezan sonu "الله أكبر X" (9:72'ye kilitleniyordu), kesik tevhid "إله إلا الله"; tamamen tekbir olan parca zikir sayilmaz
# + namaz sonu tesbihati "(لا حول) ولا قوة إلا بالله" (Kuran'da sadece 18:39 "ما شاء الله لا قوة إلا بالله"; aksam 22.10)
# + tesbihat "(الحمد) لله ولا إله إلا الله" ("ولا اله الا الله" Kuran'da hic yok)
DHIKR_PHRASES = (("محمد", "رسول", "الله"), ("محمدا", "رسول", "الله"), ("لا", "اله", "الا", "الله"), ("ان", "شاء", "الله"),
                 ("اله", "الا", "الله"), ("الله", "اكبر"), ("قوه", "الا", "بالله"),
                 ("حول", "ولا", "قوه", "الا", "بالله"), ("ولا", "اله", "الا", "الله"), ("لله", "ولا", "اله", "الا", "الله"))
DHIKR_EXTRA_MAX = 1

# Kamet / ezan basi: zamm kilitli degilken (BEKLEME / ARA) ve bekleme yokken son TEKBIR_TEVHID_CHUNKS parcada sadece
# tekbir duyulduysa tek basina tevhid kamet/ezan sayilir (yatsi 19.10: kamet 24 sn geç tanindi; referans:
# build_state_machine_fixture.TEKBIR_TEVHID_CHUNKS)
TEKBIR_TEVHID_CHUNKS = 2
# Kilit kaybolmussa zikir / tekbir + tevhid kurali ZAMM'da da (yatsi #2) ve zamm okunurken ara verildiyse kisa + zayif
# eslesme devam sayilmaz (FATIHA'da degil) — bkz. scripts/build_state_machine_fixture.py PAUSE_LOST_CHUNKS
PAUSE_LOST_CHUNKS = 2
# Kilitliyken parca sadece "(و)الحمد لله" ve pencere eslesmesi < ilk kilit esigi → okuma degil (yatsi 22.10: 21:79 sonu kuyruk
# parcasi → 21:80-81'e 62.1, rukûda ekranda okunmamis ayet)
STOCK_PHRASES = {("الحمد", "لله"), ("والحمد", "لله")}
# Okumadan sonra tekbir duyulduysa (rukû) ZAMM'da kisa (< 3 kelime) eslesme ancak >= bu skorla okumanin devami (yatsi 22.10 sabit
# parca: semiallah "لمن قبله" 21:82'ye 76 → 2. rekat devam penceresi 21:80'i kacirdi)
TEKBIR_SHORT_MIN_SCORE = 90


def is_tevhid(text: str) -> bool:
    toks = [t for t in (bare_token(w) for w in text.split()) if t]
    return any(tuple(toks[i:i + 3]) == ("اله", "الا", "الله") for i in range(len(toks) - 2))


def _drop_leading_tekbir(toks):
    """Bastaki tekbir (kamet / ezan kapanisi "الله أكبر الله أكبر لا إله إلا الله" — Kuran'da tekbirden hemen sonra tevhid yok):
    yatsi 21.10'da kayit kamet sonunda basladi, "الله اغبر لا اله الا الله" zikir sayilmadi → 37:35 / 28:88 belirsiz aday (Kotlin
    aligner'inin aday budamasi farkli yer buluyordu). Kalan kelimeler zikir ifadesiyse zikir (dhikr_only)."""
    while len(toks) > 1 and (toks[0] in TEKBIR_WORDS or (toks[0] == "الله" and toks[1] in TEKBIR_WORDS)):
        toks = toks[1:] if toks[0] in TEKBIR_WORDS else toks[2:]
    return toks


def dhikr_only(text: str) -> Tuple[bool, bool]:
    """→ (sadece zikir ifadesi mi, kelime-i sehadet mi)"""
    toks = [t for t in (bare_token(w) for w in text.split()) if t]
    if is_tekbir_only(toks):
        return False, False
    for cand in (toks, _drop_leading_tekbir(toks)):
        for ph in DHIKR_PHRASES:
            n = len(ph)
            if len(cand) - n <= DHIKR_EXTRA_MAX and any(tuple(cand[i:i + n]) == ph for i in range(len(cand) - n + 1)):
                return True, ph[1] == "رسول"
    return False, False


def strip_namaz_phrases(text: str) -> Tuple[str, int]:
    """Namaz zikirlerini (selam, semiallah, rabbena lekel hamd, tek basina tekbir), namaz sonu duasini
    ("اللهم انت السلام ومنك السلام تباركت يا ذا الجلال والاكرام"), tek kelimelik ASR uydurmasini ("المصدر") ve ders
    girisi uydurmasini ("تفسير سورة الأعراف الدرس") cikar."""
    words = text.split()
    norms = [bare_token(w) for w in words]
    n = len(words)
    keep, removed, i = [], 0, 0
    while i < n:
        k = 0
        if norms[i] == "السلام" and i + 1 < n and norms[i + 1] in ("عليكم", "عليك"):
            k = 2
            while i + k < n and k < SELAM_MAX_WORDS and norms[i + k] in SELAM_TAIL:
                k += 1
        elif norms[i] in ("عليكم", "عليك") and i + 1 < n and norms[i + 1] in ("ورحمه", "رحمه"):
            # Parca sinirinda bolunen selam ("السلام" onceki parcada): "عليكم ورحمة الله" (cuma #2, sabit parca → 1:1
            # ADAY). "عليكم/عليك + (و)رحمه" Kuran'da yok.
            k = 2
            while i + k < n and k < SELAM_MAX_WORDS and norms[i + k] in SELAM_TAIL:
                k += 1
        elif norms[i] == "سمع" and i + 2 < n and norms[i + 1] == "الله":
            if norms[i + 2].startswith("حمد"):
                k = 3
            elif norms[i + 2] == "لمن":
                k = 4 if i + 3 < n and norms[i + 3].startswith("حمد") else 3
        elif norms[i] == "ربنا" and i + 2 < n and norms[i + 1] in ("لك", "ولك") and norms[i + 2] == "الحمد":
            k = 3
        elif norms[i] == "لمن" and i + 1 < n and norms[i + 1].startswith("حم"):
            k = 2
            back = 0
            while keep and back < SEMIALLAH_HEAD_MAX and len(bare_token(keep[-1])) <= SEMIALLAH_HEAD_LEN:
                keep.pop()
                back += 1
            removed += back
        elif norms[i] in SEMIALLAH_TAIL:
            k = 1
        elif norms[i] in ASR_NOISE_WORDS:
            k = 1
        elif norms[i] == "تفسير":
            k = 1
            if i + 1 < n and norms[i + 1] == "سوره":
                k = 3 if i + 2 < n and norms[i + 2] != "الدرس" else 2
        elif norms[i] == "نهايه" and i + 1 < n and norms[i + 1] == "الدرس":
            k = 2
        elif norms[i] == "الدرس":
            k = 1
            if len(keep) >= 2 and bare_token(keep[-2]) == "سوره":
                keep.pop()
                keep.pop()
                removed += 2
        elif norms[i] in ("انت", "منك", "ومنك") and i + 1 < n and norms[i + 1] == "السلام":
            k = 2
            back = 0
            while keep and back < DUA_HEAD_MAX and bare_token(keep[-1]) in DUA_HEAD:
                keep.pop()
                back += 1
            removed += back
        elif norms[i] == "تباركت":
            k = 1
            while i + k < n and norms[i + k] in DUA_TAIL:
                k += 1
        elif norms[i] == "ذا" and i + 1 < n and norms[i + 1] == "الجلال":
            k = 3 if i + 2 < n and norms[i + 2] == "والاكرام" else 2
            if keep and bare_token(keep[-1]) == "يا":
                keep.pop()
                removed += 1
        if k and norms[i + k - 1] == "الدرس" and i + k < n and norms[i + k].startswith(LECTURE_ORDINAL_PREFIXES):
            k += 1      # "الدرس الثامن"
        if k:
            i += k
            removed += k
        else:
            keep.append(words[i])
            i += 1
    if is_tekbir_only(keep):
        removed += len(keep)
        keep = []
    return " ".join(keep), removed


def is_tekbir_only(words) -> bool:
    kept = [t for t in (bare_token(w) for w in words) if t]
    return bool(kept) and any(t in TEKBIR_WORDS for t in kept) and all(t == "الله" or t in TEKBIR_WORDS for t in kept)


def namaz_signal(text: str) -> Optional[str]:
    """"kamet" (kamet/ezan), "selam", "ruku" (semiallah) ya da None. Semiallah, sonra kamet."""
    toks = [t for t in (bare_token(w) for w in text.split()) if t]
    # Semiallah kametten once: Kuran'da "سمع الله" hep "قول" ile devam ediyor (3:181, 58:1); "سمع الله لنا محمدا"
    # kamet sayiliyordu ("محمدا"), "سمع الله من حمداً" hicbir kaliba uymuyordu
    if any(toks[i] == "سمع" and toks[i + 1] == "الله" and toks[i + 2] != "قول" for i in range(len(toks) - 2)):
        return "ruku"
    # "استمع الله" (aksam 22.10): Kuran'da "استمع" sadece 72:1'de ("استمع نفر")
    if any(a == "استمع" and b == "الله" for a, b in zip(toks, toks[1:])):
        return "ruku"
    if any(is_kamet_word(toks, i) for i in range(len(toks))) or any(p in KAMET_PAIRS for p in zip(toks, toks[1:])):
        return "kamet"
    # Bolunmus / bozuk selam: "عليكم ورحمة الله" ("السلام" onceki parcada; yatsi 27.10, cuma #2), "ساء عليكم ورحمة",
    # "سلام عليكم ورحمة" — "عليكم/عليك + (و)رحمه" Kuran'da yok (strip_namaz_phrases ile ayni kural)
    if any((a == "السلام" and b in ("عليكم", "عليك")) or (a in ("عليكم", "عليك") and b in ("ورحمه", "رحمه"))
           for a, b in zip(toks, toks[1:])):
        return "selam"
    if any(t in SEMIALLAH_TAIL for t in toks) or any(a == "لمن" and b.startswith("حم") for a, b in zip(toks, toks[1:])):
        return "ruku"
    return None


def reset_for_new_namaz(state: SessionState, chunk_index: int, hold_chunks: int):
    """Kamet / namaz sonu: onceki kilit ve adaylar silinir, BEKLEME + Fatiha beklemesi."""
    if state.state != NamazState.BEKLEME:
        state.state_transitions.append(f"{state.state.value} → {NamazState.BEKLEME.value}")
    state.state = NamazState.BEKLEME
    state.last_word_index = None
    state.last_surah = None
    state.last_ayah = None
    state.max_ayah = None
    state.lost_chunks = 0
    state.pending_match = None
    state.jump_candidate = None
    state.hold_until = chunk_index + hold_chunks


FATIHA_RANGE = (AYAH_TO_CORPUS_RANGE[(1, 1)][0], AYAH_TO_CORPUS_RANGE[(1, 7)][1])


BESMELE_NORMALIZED = ["بسم", "الله", "الرحمن", "الرحيم"]
BESMELE_POSITIONS = set()
for (_s, _a), (_st, _en) in AYAH_TO_CORPUS_RANGE.items():
    if _a == 1 and _s not in (1, 9) and _en - _st + 1 > 4 and \
            [CORPUS.words[_st + _k].normalized for _k in range(4)] == BESMELE_NORMALIZED:
        BESMELE_POSITIONS.update(range(_st, _st + 4))


def is_opening_match(match) -> bool:
    """Eslesme bir surenin acilisindan mi basliyor (besmele ya da 1. ayetin besmele disi ilk OPENING_START_SLACK+1
    kelimesi)."""
    w = CORPUS.words[match.start_word_idx]
    if w.ayah != 1:
        return False
    st, en = AYAH_TO_CORPUS_RANGE[(w.surah, 1)]
    first = st
    while first < en and first in BESMELE_POSITIONS:
        first += 1
    return st <= match.start_word_idx <= first + OPENING_START_SLACK


def starts_ayah(match) -> bool:
    """Eslesme bir ayetin ilk kelimesinden mi basliyor (1. ayetlerde besmele ve huruf-u mukattaa disi ilk kelime)."""
    w = CORPUS.words[match.start_word_idx]
    st, en = AYAH_TO_CORPUS_RANGE[(w.surah, w.ayah)]
    first = st
    if w.ayah == 1:
        while first < en and first in BESMELE_POSITIONS:
            first += 1
    if match.start_word_idx == first:
        return True
    return w.ayah == 1 and match.start_word_idx == first + 1 and CORPUS.words[first].normalized in MUQATTAAT


def opening_tie(text, match) -> bool:
    """Gecis eslesmesi baska bir surenin acilisina da ayni ham skorla oturuyor mu (bkz. OPENING_TIE_MARGIN)."""
    ru = _runner_up_match(text, match)
    return (ru is not None and CORPUS.words[ru.start_word_idx].surah != CORPUS.words[match.start_word_idx].surah
            and is_opening_match(ru) and ru.score >= match.score - OPENING_TIE_MARGIN)


def _opening_first_word(surah: int) -> int:
    st, en = AYAH_TO_CORPUS_RANGE[(surah, 1)]
    p = st
    while p < en and p in BESMELE_POSITIONS:
        p += 1
    return p


OPENING_FIRST_TOKENS = {s: bare_token(CORPUS.words[_opening_first_word(s)].normalized.split()[0])
                        for s in range(1, 115) if (s, 1) in AYAH_TO_CORPUS_RANGE}


def opening_preference(text):
    """Fatiha sonu: ilk kelimesi parcanin ilk 2 kelimesinden biri olan surelerin acilisinda (1-2. ayet) en iyi eslesme
    → (eslesme, skor, ayrinti) ya da (None, -1, None) — bkz. OPENING_PREFER_MARGIN."""
    toks = [t for t in (bare_token(w) for w in text.split()) if t][:2]
    best, best_s, best_d = None, -1.0, None
    for s, fw in OPENING_FIRST_TOKENS.items():
        if s == 1 or fw not in toks:
            continue
        ow = (AYAH_TO_CORPUS_RANGE[(s, 1)][0], AYAH_TO_CORPUS_RANGE[(s, min(2, SURAH_AYAH_COUNTS[s]))][1])
        m = align_transcription(text, CORPUS, preferred_range=ow, preferred_bonus=PREFERRED_BONUS)
        if m is None or m.score < OPENING_MIN_FUZZY or not is_opening_match(m):
            continue
        sc, d = score_transcription(text, m)
        if sc > best_s:
            best, best_s, best_d = m, sc, d
    return best, best_s, best_d


def early_fatiha(state: SessionState, chunk_index: int, fatiha_ayah: int) -> bool:
    """Zamm'da son saglam eslesmeden FATIHA_MIN_GAP_CHUNKS parca gecmeden Fatiha'nin 1-2. ayetinde biten eslesme ve onceki
    parcalarda Fatiha gecis adayi yok → erken (gecis adayi olur)."""
    if state.state != NamazState.ZAMM or state.last_solid_chunk is None or fatiha_ayah > FATIHA_EARLY_MAX_AYAH:
        return False
    if chunk_index - state.last_solid_chunk >= FATIHA_MIN_GAP_CHUNKS:
        return False
    jc = state.jump_candidate
    return not (jc is not None and jc.surah == 1 and chunk_index - jc.chunk_index <= 2)


def content_word_count(match) -> int:
    """Eslesmedeki besmele-disi kelime sayisi (sadece besmeleye oturan eslesme sure gecisi sayilmaz)."""
    return sum(1 for p in range(match.start_word_idx, match.end_word_idx + 1) if p not in BESMELE_POSITIONS)


def _verify_pending(pending: PendingMatch, new_surah: int, new_ayah: int) -> bool:
    if new_surah != pending.surah:
        return False
    return abs(new_ayah - pending.ayah) <= PENDING_VERIFY_AYAH_WINDOW


def clean_chunk_text(text: str) -> str:
    """Hizalanacak temiz metin: ASR uydurmasi bos, istiaze ve namaz zikirleri cikarilmis."""
    text = strip_asr_hallucination(text)
    if not text:
        return ""
    t, _ = strip_tilavet_end(text)
    t, _ = strip_istiaze(t)
    t, _ = strip_namaz_phrases(t)
    return t.strip()


def join_search_texts(texts) -> str:
    """Ardisik parca metinlerini birlestir; sinirda tekrar eden (bindirme) kelimeler bir kez sayilir."""
    out = []
    for t in texts:
        w = t.split()
        if out:
            a = [bare_token(x) for x in out]
            b = [bare_token(x) for x in w]
            for k in range(min(SEARCH_CONCAT_MAX_OVERLAP, len(a), len(b)), 0, -1):
                if a[-k:] == b[:k]:
                    w = w[k:]
                    break
        out.extend(w)
    return " ".join(out)


def process_chunk(audio_np, chunk_index, state: SessionState, chunk_start_time: float):
    """Parcayi isle; kilit vermezse BEKLEME'de birikmis metinle (onceki parcalar + bu parca) tek parcada kilit dene
    (referans: scripts/build_state_machine_fixture.py process_chunk_simulated)."""
    was_search = state.state == NamazState.BEKLEME
    result = _process_chunk_core(audio_np, chunk_index, state, chunk_start_time)
    hold = state.hold_until is not None and chunk_index <= state.hold_until
    if not (was_search and state.state == NamazState.BEKLEME and not hold and not result.get("namaz_signal")
            and result["status"] in ("too_short", "low_confidence", "pending", "empty")):
        state.search_texts = []
        return result
    if result["status"] == "empty":
        return result
    clean = clean_chunk_text(result.get("text") or "")
    prev = [t for k, t in state.search_texts if chunk_index - k <= SEARCH_CONCAT_CHUNKS]
    state.search_texts = [(k, t) for k, t in state.search_texts if chunk_index - k < SEARCH_CONCAT_CHUNKS]
    if clean:
        state.search_texts.append((chunk_index, clean))
    if not prev or not clean:
        return result
    comb = join_search_texts(prev + [clean])
    comb_words = len([t for t in (normalize_arabic(x) for x in comb.split()) if t])
    if comb == clean or comb_words < UNIQUE_LOCK_MIN_WORDS:
        return result
    g = align_transcription(comb, CORPUS, preferred_range=None, preferred_bonus=PREFERRED_BONUS)
    gs, _ = score_transcription(comb, g)
    if not g or not is_unique_match(comb, g, gs, comb_words):
        return result
    state.search_texts = []
    for key in ("pending_surah", "pending_ayah"):
        result.pop(key, None)
    result["combined_text"] = comb
    result["confidence"] = gs
    result["word_count"] = comb_words
    result["reason"] = "birikmis metinle tek parcada kilit"
    return _commit_match(state, g, gs, None, result)


def _commit_match(state: SessionState, match, score, jump, result):
    """Eslesmeyi kabul et: durum gecisi, en ileri ayet, bosluk doldurma, ayet bilgisi, son konum."""
    verses = collect_verses(match.start_word_idx, match.end_word_idx)
    first_surah, first_ayah = verses[0] if verses else (None, None)
    last_surah, last_ayah = verses[-1] if verses else (None, None)
    new_state = transition_state(state, True, first_surah, first_ayah)
    if new_state != state.state:
        state.state_transitions.append(f"{state.state.value} → {new_state.value}")
        state.state = new_state

    state.pending_match = None
    state.hold_until = None
    # Aday, gecis yapildiysa ya da pencere emin eslestiyse biter; zayif pencere eslesmesinde bekler
    if jump in ("natural", "verified") or score >= JUMP_SEARCH_BELOW:
        state.jump_candidate = None
    # En ileri ayet: sure degisince / Fatiha'ya yeni girince sifirdan
    if state.last_surah != last_surah or (state.state == NamazState.FATIHA and
                                          result["state_before"] != NamazState.FATIHA.value):
        state.max_ayah = last_ayah
    else:
        state.max_ayah = max(state.max_ayah or 0, last_ayah)

    gap_filled_count = 0
    if verses and state.last_surah is not None and state.last_ayah is not None:
        fs, fa = verses[0]
        if fs == state.last_surah:
            gap = fa - state.last_ayah - 1
            if 0 < gap <= MAX_GAP_FILL:
                filled = [(state.last_surah, state.last_ayah + i + 1) for i in range(gap)]
                verses = filled + verses
                gap_filled_count = gap
                result["gap_filled"] = gap

    verses_payload = []
    for i, (s, a) in enumerate(verses):
        if i < gap_filled_count:
            verses_payload.append(build_verse_payload(s, a))
        else:
            verses_payload.append(build_verse_payload(
                s, a,
                match_start_idx=match.start_word_idx,
                match_end_idx=match.end_word_idx,
            ))

    result["status"] = "matched"
    result["verses"] = verses_payload
    result["state"] = state.state.value

    if state.state == NamazState.ZAMM:
        if state.zamm_surah == last_surah and state.zamm_ayah is not None:
            state.zamm_ayah = max(state.zamm_ayah, last_ayah)
        else:
            state.zamm_surah, state.zamm_ayah = last_surah, last_ayah
    state.last_word_index = match.end_word_idx
    state.last_surah = last_surah
    state.last_ayah = last_ayah
    state.lost_chunks = 0
    state.matched_chunks += 1
    state.fresh_jump = None
    state.last_match_chunk = result["index"]
    if result.get("word_count", 0) >= MIN_WORD_COUNT_FIRST_LOCK and score >= MIN_CONFIDENCE_FIRST_LOCK:
        state.last_solid_chunk = result["index"]
    return result


def _process_chunk_core(audio_np, chunk_index, state: SessionState, chunk_start_time: float):
    t_start = time.time()
    state.total_chunks += 1
    timings = {}
    result = {"type": "chunk", "index": chunk_index, "state_before": state.state.value}

    rms = compute_rms(audio_np)
    result["rms"] = round(rms, 4)

    if rms < MIN_RMS_ENERGY:
        result["status"] = "silent"
        result["reason"] = f"sessiz (RMS={rms:.4f})"
        if state.state in (NamazState.FATIHA, NamazState.ZAMM):
            state.lost_chunks += 1
        _cleanup_stale_candidates(state, chunk_index)
        new_state = transition_state(state, False, None, None)
        if new_state != state.state:
            state.state_transitions.append(f"{state.state.value} → {new_state.value}")
            state.state = new_state
        result["state"] = state.state.value
        timings["total"] = time.time() - t_start
        result["timings"] = timings
        return result

    t0 = time.time()
    text, asr_timings = transcribe_chunk(audio_np)
    timings["asr"] = time.time() - t0
    timings.update(asr_timings)
    result["text"] = text

    # ASR uydurmasi (Kuran'da olmayan video girisi kelimeleri) → ifade cikarilir, okuma kalmazsa bos sayilir
    if text and is_asr_hallucination(text):
        result["asr_hallucination"] = True
        text = strip_asr_hallucination(text)
    # Tilavet sonu ("صدق الله العظيم") → kilit / adaylar biter
    if text:
        text, tilavet_end = strip_tilavet_end(text)
        if (tilavet_end and state.last_tekbir_chunk is not None and state.last_match_chunk is not None
                and state.last_tekbir_chunk > state.last_match_chunk
                and chunk_index - state.last_match_chunk >= TILAVET_END_NAMAZ_GAP):
            tilavet_end = False
            result["tilavet_end_in_namaz"] = True
        if tilavet_end:
            result["tilavet_end"] = True
            reset_for_new_namaz(state, chunk_index, 0)
            state.hold_until = None
            state.search_texts = []

    if not text:
        result["status"] = "empty"
        state.lost_chunks += 1
        _cleanup_stale_candidates(state, chunk_index)
        new_state = transition_state(state, False, None, None)
        if new_state != state.state:
            state.state_transitions.append(f"{state.state.value} → {new_state.value}")
            state.state = new_state
        result["state"] = state.state.value
        timings["total"] = time.time() - t_start
        result["timings"] = timings
        return result

    # Namaz yapisi sinyali (kamet / selam / rukû)
    signal = namaz_signal(text)
    # Zamm kilitli degilken (ya da kilit kaybolmusken) tek basina zikir ifadesi — bkz. DHIKR_PHRASES
    abandoned = (state.lost_chunks >= ABANDON_LOCK_AFTER_LOST and state.state in (NamazState.FATIHA, NamazState.ZAMM))
    dhikr, sehadet = (dhikr_only(text) if signal is None and (state.state != NamazState.ZAMM or abandoned)
                      else (False, False))
    in_hold = state.hold_until is not None and chunk_index <= state.hold_until
    tekbir_tevhid = (dhikr and not in_hold and (state.state in (NamazState.BEKLEME, NamazState.ARA) or abandoned)
                     and state.last_tekbir_chunk is not None
                     and chunk_index - state.last_tekbir_chunk <= TEKBIR_TEVHID_CHUNKS and is_tevhid(text))
    if is_tekbir_only([t for t in (bare_token(w) for w in text.split()) if t]):
        state.last_tekbir_chunk = chunk_index
    if (dhikr and sehadet and state.state == NamazState.BEKLEME) or tekbir_tevhid:
        signal = "kamet"
    if signal:
        result["namaz_signal"] = signal
    if signal == "kamet":
        reset_for_new_namaz(state, chunk_index, KAMET_HOLD_CHUNKS)
        result["status"] = "empty"
        result["reason"] = "kamet/ezan — yeni namaz, Fatiha bekleniyor"
        result["state"] = state.state.value
        timings["total"] = time.time() - t_start
        result["timings"] = timings
        return result
    if dhikr:
        # Bekleme surerken zikir: namaz baslamadi, Fatiha beklemesi uzar
        if state.hold_until is not None and chunk_index <= state.hold_until:
            state.hold_until = max(state.hold_until, chunk_index + KAMET_HOLD_CHUNKS)
        result["status"] = "empty"
        result["reason"] = "zikir ifadesi (zamm kilidi yok)"
        state.lost_chunks += 1
        _cleanup_stale_candidates(state, chunk_index)
        new_state = transition_state(state, False, None, None)
        if new_state != state.state:
            state.state_transitions.append(f"{state.state.value} → {new_state.value}")
            state.state = new_state
        result["state"] = state.state.value
        timings["total"] = time.time() - t_start
        result["timings"] = timings
        return result
    if signal == "selam" and state.state in (NamazState.BEKLEME, NamazState.ARA):
        reset_for_new_namaz(state, chunk_index, RUKU_HOLD_CHUNKS)
    elif signal == "ruku":
        if state.state in (NamazState.FATIHA, NamazState.ZAMM):
            state.state_transitions.append(f"{state.state.value} → {NamazState.ARA.value}")
            state.state = NamazState.ARA
        state.pending_match = None
        state.jump_candidate = None
        state.hold_until = chunk_index + RUKU_HOLD_CHUNKS
    hold = state.hold_until is not None and chunk_index <= state.hold_until
    result["hold"] = hold

    # Istiaze kelimelerini cikar (hepsi istiazeyse kelime sayisi 0 → too_short)
    text, n_istiaze = strip_istiaze(text)
    if n_istiaze:
        result["istiaze_removed"] = n_istiaze
    text, n_zikir = strip_namaz_phrases(text)
    if n_zikir:
        result["namaz_zikir_removed"] = n_zikir
    tokens = [normalize_arabic(t) for t in text.split() if t]
    word_count = len([t for t in tokens if t])
    is_hot = state.state in (NamazState.FATIHA, NamazState.ZAMM)
    min_words = MIN_WORD_COUNT_HOT if is_hot else MIN_WORD_COUNT_COLD
    if word_count < min_words:
        result["status"] = "too_short"
        result["reason"] = f"{word_count} kelime (min {min_words})"
        result["state"] = state.state.value
        timings["total"] = time.time() - t_start
        result["timings"] = timings
        return result

    preferred_range = compute_preferred_range(state)
    result["preferred_range"] = preferred_range

    lock_abandoned = (state.lost_chunks >= ABANDON_LOCK_AFTER_LOST and
                      state.state in (NamazState.FATIHA, NamazState.ZAMM))
    result["lock_abandoned"] = lock_abandoned

    if state.state == NamazState.ZAMM and state.last_surah and state.last_ayah:
        result["near_surah_end"] = is_near_surah_end(state.last_surah, state.last_ayah)

    t0 = time.time()
    resumed = False   # kilit kaybinda kalinan yerin penceresi secildi (Fatiha yoklamasinda pencere ici sayilir)
    if hold:
        # Kamet / rukû / selam sonrasi: sadece Fatiha ya da kalinan yerden devam. Tum Kuran aranmaz.
        match = align_transcription(text, CORPUS, preferred_range=FATIHA_RANGE, preferred_bonus=PREFERRED_BONUS)
        score, score_details = score_transcription(text, match)
        if state.state == NamazState.ARA and state.last_surah and state.last_ayah:
            rw = _ayah_window(state.last_surah, state.last_ayah, RESUME_BACK, PREFERRED_AYAH_WINDOW_ARA)
            if rw:
                rm = align_transcription(text, CORPUS, preferred_range=rw, preferred_bonus=PREFERRED_BONUS)
                rs, r_details = score_transcription(text, rm)
                if rm and rs >= HOLD_RESUME_MIN_SCORE and rs > score:
                    match, score, score_details = rm, rs, r_details
    else:
        match = align_transcription(text, CORPUS,
                                    preferred_range=preferred_range,
                                    preferred_bonus=PREFERRED_BONUS)
        score, score_details = score_transcription(text, match)
        # Kilit kaybolmus: kalinan yerin penceresi tum Kuran'la neredeyse esitse (CONTINUE_MARGIN) devam (asr 21.10: Hasr
        # 59:24 "الا وهو العزيز" → 3:6 / 3:18 93.9, 59:24 93.3)
        if (lock_abandoned and state.last_surah and state.last_ayah and word_count >= MIN_WORD_COUNT_FIRST_LOCK
                and match is not None):
            rw = _ayah_window(state.last_surah, state.last_ayah, RESUME_BACK, PREFERRED_AYAH_WINDOW_ARA)
            if rw and not rw[0] <= match.start_word_idx <= rw[1]:
                rm = align_transcription(text, CORPUS, preferred_range=rw, preferred_bonus=PREFERRED_BONUS)
                rs, r_details = score_transcription(text, rm)
                if (rm and rw[0] <= rm.start_word_idx <= rw[1] and rs >= HOLD_RESUME_MIN_SCORE
                        and rs >= score - CONTINUE_MARGIN):
                    match, score, score_details = rm, rs, r_details
                    resumed = True
                    result["resumed"] = True

    # Kilitliyken (ZAMM/ARA) pencere emin degilse Fatiha'yi ayrica dene: yeni rekat Fatiha ile baslar
    # (tum Kuran aramasi "الحمد لله رب العالمين"i baska yere de oturtabiliyor)
    # ZAMM'da en az FATIHA_FAST_LOCK_MIN_WORDS kelime ("وإلى رب العالمين" 94:8 → Fatiha 92.6)
    fatiha_jump = False
    fatiha_cand = None   # erken Fatiha (bkz. FATIHA_MIN_GAP_CHUNKS): gecis adayi, sonraki parca dogrular
    # Kilidi kaybolmus zamm ARA gibi (yeni rekat beklenir; sabah 21.10 2. rekat "والحمد لله رب العالمين" → 6:45)
    ara_like = state.state == NamazState.ARA or (state.state == NamazState.ZAMM and lock_abandoned)
    probe_words = MIN_WORD_COUNT_FIRST_LOCK if ara_like else FATIHA_FAST_LOCK_MIN_WORDS
    if (not hold and state.state in (NamazState.ZAMM, NamazState.ARA) and word_count >= probe_words
            and (not match or score < JUMP_SEARCH_BELOW or ara_like)):
        fm = align_transcription(text, CORPUS, preferred_range=FATIHA_RANGE, preferred_bonus=PREFERRED_BONUS)
        fs, f_details = score_transcription(text, fm)
        base = score if match else 0.0
        # ARA'da esitlikte Fatiha kazanir; kalinan yerin penceresindeki eslesme haric (37:182 = 1:2 metni)
        in_window = resumed or (bool(match) and bool(preferred_range)
                                and preferred_range[0] <= match.start_word_idx <= preferred_range[1])
        if ara_like:
            # pencere disi: Fatiha'ya FATIHA_ARA_MARGIN pay (ASR basa "و" ekliyor: "والحمد" 6:45 100, Fatiha 92.4)
            better = fs > base if in_window else fs >= base - FATIHA_ARA_MARGIN
        else:
            better = fs >= base + JUMP_MARGIN
        if fm and fs >= FATIHA_FAST_LOCK_MIN_SCORE and better:
            fv = collect_verses(fm.start_word_idx, fm.end_word_idx)[-1]
            if early_fatiha(state, chunk_index, fv[1]):
                fatiha_cand = PendingMatch(surah=1, ayah=fv[1], word_index=fm.end_word_idx, chunk_index=chunk_index)
                result["early_fatiha"] = True
            else:
                match, score, score_details = fm, fs, f_details
                fatiha_jump = True
                result["fatiha_jump"] = True

    # BEKLEME + aday: aday penceresinde tutmadiysa ayni chunk'ta tum Kuran'da ara. Eskiden yanlis
    # aday (orn. 113:1 / 114:1 ortak ifadesi) 2 chunk bayatlayana kadar dogru yeri aratmiyordu.
    if (not hold and state.state == NamazState.BEKLEME and state.pending_match is not None and preferred_range
            and word_count >= MIN_WORD_COUNT_FIRST_LOCK
            and (not match or score < MIN_CONFIDENCE_FIRST_LOCK)):
        g = align_transcription(text, CORPUS, preferred_range=None, preferred_bonus=PREFERRED_BONUS)
        gs, g_details = score_transcription(text, g)
        if g and gs >= MIN_CONFIDENCE_FIRST_LOCK:
            match, score, score_details = g, gs, g_details
            result["pending_window_missed"] = True
    # BEKLEME + aday, pencere tuttu ama tam degil: tum Kuran'da baska yer tek parcada kilit kuralini geciyorsa o
    # (belirsiz aday "قل أعوذ برب" 113:1 sonrasi "قل أعوذ برب الناس" adayi yanlis dogruluyordu; 114:1 100, "الناس")
    elif (not hold and state.state == NamazState.BEKLEME and state.pending_match is not None and preferred_range
            and word_count >= MIN_WORD_COUNT_FIRST_LOCK and match and score < 100):
        g = align_transcription(text, CORPUS, preferred_range=None, preferred_bonus=PREFERRED_BONUS)
        gs, g_details = score_transcription(text, g)
        outside = bool(g) and not preferred_range[0] <= g.start_word_idx <= preferred_range[1]
        if outside and gs > score and is_unique_match(text, g, gs, word_count):
            match, score, score_details = g, gs, g_details
            result["pending_window_overridden"] = True
        # Aday penceresindeki eslesme tum Kuran'daki en iyi yerden cok zayifsa dogrulama sayilmaz (asr 21.10: belirsiz
        # 6:73 adayini "هو الرحمن الرحيم" pencerede 71.3 ile dogruluyordu, tum Kuran'da 100)
        elif outside and gs >= score + VERIFY_GLOBAL_MARGIN:
            match, score, score_details = g, gs, g_details
            result["pending_window_overridden"] = True

    # Kilitliyken (FATIHA/ZAMM/ARA) pencere emin degilse tum Kuran'da da ara: sure gecisi. Eskiden
    # ABANDON_LOCK_AFTER_LOST (6 chunk, ~30 sn) dolmadan baska yere gecilemiyordu; ustelik Fatiha
    # penceresi zamm suresinin besmelesine / kisa ifadelerine 50-80 skorla "eslesip" kilidi tutuyordu.
    # Taze gecisin yeniden kontrolu (bkz. FRESH_JUMP_CHUNKS): gecis parcasi da yeni surenin acilisina oturmali
    fresh_fix = False
    fj = state.fresh_jump
    if (not hold and state.state == NamazState.ZAMM and fj is not None and 0 < chunk_index - fj[0] <= FRESH_JUMP_CHUNKS
            and not lock_abandoned and not fatiha_jump and fatiha_cand is None and (not match or score < MIN_CONFIDENCE)):
        g = align_transcription(text, CORPUS, preferred_range=None, preferred_bonus=PREFERRED_BONUS)
        gs, g_details = score_transcription(text, g)
        if g and gs >= FRESH_JUMP_MIN_SCORE and gs >= (score if match else 0.0) + JUMP_MARGIN:
            gfs, gfa = collect_verses(g.start_word_idx, g.end_word_idx)[0]
            if gfs != state.last_surah and gfa <= 2:
                ow = (AYAH_TO_CORPUS_RANGE[(gfs, 1)][0], AYAH_TO_CORPUS_RANGE[(gfs, min(2, SURAH_AYAH_COUNTS[gfs]))][1])
                pm = align_transcription(fj[1], CORPUS, preferred_range=ow, preferred_bonus=PREFERRED_BONUS)
                if (pm and is_opening_match(pm) and pm.start_word_idx <= g.start_word_idx
                        and score_transcription(fj[1], pm)[0] >= MIN_CONFIDENCE_FIRST_LOCK):
                    match, score, score_details = g, gs, g_details
                    fresh_fix = True
                    result["fresh_jump_fix"] = True

    jump = "natural" if fatiha_jump else None  # "natural" | "verified" (gecildi) | "candidate" (aday)
    if fresh_fix:
        jump = "verified"
        result["jump"] = jump
    opening = False   # sure basi gecisi (bkz. OPENING_MIN_FUZZY)
    fresh = False
    short_jump = word_count == JUMP_SHORT_WORDS and at_transition_point(state)
    if (not hold and state.state in (NamazState.FATIHA, NamazState.ZAMM, NamazState.ARA) and preferred_range
            and not lock_abandoned and (word_count >= MIN_WORD_COUNT_FIRST_LOCK or short_jump)
            and fatiha_cand is None and (not match or score < JUMP_SEARCH_BELOW)):
        g = align_transcription(text, CORPUS, preferred_range=None, preferred_bonus=PREFERRED_BONUS)
        gs, g_details = score_transcription(text, g)
        base = score if match else 0.0
        content_ok = bool(g) and content_word_count(g) >= 2
        ok = content_ok and gs >= MIN_CONFIDENCE_FIRST_LOCK and gs >= base + JUMP_MARGIN
        # Sure basi: gecis noktasinda surenin acilisina oturan eslesme ham hizalama skoruyla (bkz. OPENING_MIN_FUZZY)
        if content_ok and not ok and state.state in (NamazState.FATIHA, NamazState.ZAMM) \
                and at_transition_point(state) and g.score >= OPENING_MIN_FUZZY \
                and g.score >= base + JUMP_MARGIN and is_opening_match(g):
            gv = collect_verses(g.start_word_idx, g.end_word_idx)
            opening = ok = is_natural_transition(state, gv[0][0], gv[0][1])
        # Kalinan yerden devam da ham hizalama skoruyla (yatsi 22.10 sabit parca: "وعلمناه صنعة لوس لكل تعز" 21:80 ham 89.4,
        # sozluk cezali 69.2 — referans: build_state_machine_fixture)
        elif content_ok and not ok and state.state == NamazState.FATIHA and state.zamm_surah \
                and at_transition_point(state) and g.score >= OPENING_MIN_FUZZY and g.score >= base + JUMP_MARGIN:
            cw = _continue_window(state.zamm_surah, state.zamm_ayah)
            ok = bool(cw) and cw[0] <= g.start_word_idx <= cw[1]
            if ok:
                result["continue_raw"] = True
        if ok:
            gv = collect_verses(g.start_word_idx, g.end_word_idx)
            (gfs, gfa), (gls, gla) = gv[0], gv[-1]
        if ok and not opening and word_count < MIN_WORD_COUNT_FIRST_LOCK:
            # Kisa parca: sadece Kuran'da tek yerde gecen ifadeyle dogal gecis (aday da uretmez)
            ok = (gs >= JUMP_SHORT_MIN_SCORE and is_natural_transition(state, gfs, gfa)
                  and phrase_count([bare_token(t) for t in text.split()]) == 1)
        cont = False
        if ok and state.state == NamazState.FATIHA and state.zamm_surah and at_transition_point(state):
            # Hatim: onceki zamm'in kaldigi yerden devam (bkz. CONTINUE_*)
            cw = _continue_window(state.zamm_surah, state.zamm_ayah)
            if cw and cw[0] <= g.start_word_idx <= cw[1]:
                cont = True
            elif cw:
                cm = align_transcription(text, CORPUS, preferred_range=cw, preferred_bonus=PREFERRED_BONUS)
                cs, c_details = score_transcription(text, cm)
                prior = (cm and not opening and cs >= MIN_CONFIDENCE_FIRST_LOCK and cs >= gs - CONTINUE_PRIOR_MARGIN
                         and not is_opening_match(g))
                if cm and ((cs >= NATURAL_MIN_SCORE and cs >= gs - CONTINUE_MARGIN) or prior):
                    g, gs, g_details, cont, opening = cm, cs, c_details, True, False
                    gv = collect_verses(g.start_word_idx, g.end_word_idx)
                    (gfs, gfa), (gls, gla) = gv[0], gv[-1]
                    result["hatim_continue"] = True
        if ok:
            jc = state.jump_candidate
            if jc is not None and chunk_index - jc.chunk_index > 2:
                jc = None
            # Aday penceresi: tum Kuran eslesmesi adayin disindaysa adayin cevresinde de ara (CANDIDATE_WINDOW_MARGIN)
            if jc is not None and not cont and not (_verify_pending(jc, gfs, gfa) or _verify_pending(jc, gls, gla)):
                jw = _ayah_window(jc.surah, jc.ayah, PENDING_VERIFY_AYAH_WINDOW, PENDING_VERIFY_AYAH_WINDOW)
                jm = align_transcription(text, CORPUS, preferred_range=jw, preferred_bonus=PREFERRED_BONUS) if jw else None
                js, j_details = score_transcription(text, jm)
                if jm and js >= MIN_CONFIDENCE_FIRST_LOCK and js >= gs - CANDIDATE_WINDOW_MARGIN:
                    g, gs, g_details, opening = jm, js, j_details, False
                    gv = collect_verses(g.start_word_idx, g.end_word_idx)
                    (gfs, gfa), (gls, gla) = gv[0], gv[-1]
                    result["candidate_window"] = True
            if not opening and not cont and state.state == NamazState.FATIHA and gs >= NATURAL_MIN_SCORE \
                    and is_natural_transition(state, gfs, gfa) and not starts_ayah(g):
                # Zamm ayet basindan baslar: ayni ifade iki yerde → ayet basindaki ikinci yer (AYAH_START_TIE_MARGIN)
                ru = _runner_up_match(text, g)
                if ru is not None and ru.score >= g.score - AYAH_START_TIE_MARGIN and starts_ayah(ru):
                    rv = collect_verses(ru.start_word_idx, ru.end_word_idx)
                    rs, r_details = score_transcription(text, ru)
                    if rs >= NATURAL_MIN_SCORE and is_natural_transition(state, rv[0][0], rv[0][1]):
                        g, gs, g_details, gv = ru, rs, r_details, rv
                        (gfs, gfa), (gls, gla) = gv[0], gv[-1]
                        result["ayah_start_tie"] = True
            if (not opening and not cont and state.state == NamazState.FATIHA and gs >= MIN_CONFIDENCE_FIRST_LOCK
                    and at_transition_point(state) and not is_opening_match(g)):
                # Sure acilisi onceligi: bkz. OPENING_PREFER_MARGIN
                om, oms, om_details = opening_preference(text)
                if om is not None and oms >= gs - OPENING_PREFER_MARGIN:
                    g, gs, g_details, opening = om, oms, om_details, True
                    gv = collect_verses(g.start_word_idx, g.end_word_idx)
                    (gfs, gfa), (gls, gla) = gv[0], gv[-1]
                    result["opening_prefer"] = True
            in_candidate = jc is not None and (_verify_pending(jc, gfs, gfa) or _verify_pending(jc, gls, gla))
            natural = opening or cont or (is_natural_transition(state, gfs, gfa) and gs >= NATURAL_MIN_SCORE)
            tie = natural and not cont and is_opening_match(g) and opening_tie(text, g)
            if tie:
                natural = opening = False
                result["opening_tie"] = True
            # Zamm sonundan Fatiha'ya dogal gecis en az FATIHA_FAST_LOCK_MIN_WORDS kelimeyle (sabah 21.10: Adiyat sonu
            # "إن ربهم بهم" → ASR "إن رب العالمين" → Fatiha 1:2)
            early = gfs == 1 and early_fatiha(state, chunk_index, gla)
            if (natural and gfs == 1 and state.state == NamazState.ZAMM and not lock_abandoned
                    and word_count < FATIHA_FAST_LOCK_MIN_WORDS) or early:
                natural = opening = False
                result["fatiha_short_jump" if not early else "early_fatiha"] = True
            if natural:
                jump = "natural"
            elif in_candidate:
                jump = "verified"
            elif not tie and not early and is_unique_match(text, g, gs, word_count):
                jump = "verified"   # fark payi: baska yerde benzeri olmayan net eslesme ikinci parcayi beklemez
            elif (state.state == NamazState.ZAMM and score < MIN_CONFIDENCE_FIRST_LOCK and gfs == state.last_surah
                  and state.last_ayah is not None and state.last_ayah - RESUME_BACK <= gla < state.last_ayah):
                # Geri duzeltme: zayif pencere, ayni surede kalinan yerin 1-2 ayet gerisi cok daha iyi (yatsi 21.10: 21:24)
                jump = "verified"
                result["back_fix"] = True
            else:
                jump = "candidate"
                state.jump_candidate = PendingMatch(surah=gls, ayah=gla, word_index=g.end_word_idx,
                                                    chunk_index=chunk_index)
            if jump != "candidate":
                match, score, score_details = g, gs, g_details
            result["jump"] = jump
            fresh = jump == "natural" and state.state == NamazState.FATIHA and not opening and not cont
    if fatiha_cand is not None:
        jump = "candidate"
        state.jump_candidate = fatiha_cand
        result["jump"] = jump
    # BEKLEME'de belirsiz eslesme yerine Fatiha basi — bkz. FATIHA_ARA_MARGIN
    if (not hold and state.state == NamazState.BEKLEME and match is not None and jump is None
            and state.pending_match is None
            and word_count >= FATIHA_FAST_LOCK_MIN_WORDS and CORPUS.words[match.start_word_idx].surah != 1):
        fm = align_transcription(text, CORPUS, preferred_range=FATIHA_RANGE, preferred_bonus=PREFERRED_BONUS)
        fs, f_details = score_transcription(text, fm)
        if (fm and fs >= FATIHA_FAST_LOCK_MIN_SCORE and fs >= score - FATIHA_ARA_MARGIN
                and CORPUS.words[fm.start_word_idx].ayah <= 3 and is_ambiguous_candidate(text, match, score)):
            match, score, score_details = fm, fs, f_details
            result["fatiha_over_ambiguous"] = True
    timings["align"] = time.time() - t0

    result["confidence"] = score
    result["word_count"] = score_details["word_count"]

    in_preferred = False
    if match and preferred_range:
        ps, pe = preferred_range
        if ps <= match.start_word_idx <= pe:
            in_preferred = True
    result["in_preferred"] = in_preferred

    is_first_lock = (state.state == NamazState.BEKLEME)
    # Kilit kayboldu (6+ kayip chunk ya da ARA): yeniden kilit ilk kilit gibi (eskiden ARA'da 50 skorla
    # tek chunk kilit: gercek namazda selam → 6:54, "سمع الله حمدا" → 3:181)
    relock = lock_abandoned or state.state == NamazState.ARA

    if relock:
        effective_threshold = MIN_CONFIDENCE_FIRST_LOCK
        require_min_words = MIN_WORD_COUNT_FIRST_LOCK
    elif is_first_lock:
        effective_threshold = MIN_CONFIDENCE_FIRST_LOCK
        require_min_words = MIN_WORD_COUNT_FIRST_LOCK
    else:
        effective_threshold = MIN_CONFIDENCE
        require_min_words = 0

    insufficient_words = (require_min_words > 0 and word_count < require_min_words)
    # Okuma ara verdiyse kisa + zayif eslesme devam sayilmaz — bkz. PAUSE_LOST_CHUNKS
    paused_weak = (state.state == NamazState.ZAMM and not relock and not opening and state.lost_chunks >= PAUSE_LOST_CHUNKS
                   and word_count < MIN_WORD_COUNT_FIRST_LOCK and score < MIN_CONFIDENCE_FIRST_LOCK)
    # Kilitliyken tek basina "(و)الحمد لله" zayif eslesmesi okuma degil — bkz. STOCK_PHRASES
    tekbir_weak = (state.state == NamazState.ZAMM and not relock and not opening and jump not in ("natural", "verified")
                   and tekbir_after_reading(state) and word_count < MIN_WORD_COUNT_FIRST_LOCK and score < TEKBIR_SHORT_MIN_SCORE)
    stock_weak = (state.state in (NamazState.FATIHA, NamazState.ZAMM) and not relock and jump not in ("natural", "verified")
                  and score < MIN_CONFIDENCE_FIRST_LOCK
                  and tuple(t for t in (bare_token(w) for w in text.split()) if t) in STOCK_PHRASES)

    # Sure basi gecisi kendi esigiyle (ham hizalama) dogrulandi; sozluk cezali skor esige takilmasin
    if (score < effective_threshold and not opening) or not match or insufficient_words or paused_weak or stock_weak \
            or tekbir_weak:
        result["status"] = "low_confidence"
        if tekbir_weak and score >= effective_threshold and not stock_weak:
            result["reason"] = f"tekbirden sonra kisa eslesme ({word_count} kelime, skor {score:.1f} < {TEKBIR_SHORT_MIN_SCORE})"
        elif stock_weak and score >= effective_threshold:
            result["reason"] = f"kalip ifade '{text}' zayif eslesme (skor {score:.1f} < {MIN_CONFIDENCE_FIRST_LOCK})"
        elif insufficient_words:
            result["reason"] = f"yetersiz kelime ({word_count}<{require_min_words})"
        elif paused_weak and score >= effective_threshold:
            result["reason"] = (f"okuma ara verdi ({state.lost_chunks} kayip parca): kisa zayif eslesme "
                                f"({word_count} kelime, skor {score:.1f} < {MIN_CONFIDENCE_FIRST_LOCK})")
        else:
            tag = ""
            if relock:
                tag = f" (kilit terk, esik={effective_threshold})"
            elif is_first_lock:
                tag = f" (esik={effective_threshold})"
            result["reason"] = (score_details.get("reason") or f"skor {score}") + tag
        state.lost_chunks += 1
        _cleanup_stale_candidates(state, chunk_index)
        new_state = transition_state(state, False, None, None)
        if new_state != state.state:
            state.state_transitions.append(f"{state.state.value} → {new_state.value}")
            state.state = new_state
        if jump == "candidate":
            jc = state.jump_candidate
            result["status"] = "pending"
            result["reason"] = f"sure gecisi adayi {jc.surah}:{jc.ayah}, dogrulama bekleniyor"
            result["pending_surah"] = jc.surah
            result["pending_ayah"] = jc.ayah
        result["state"] = state.state.value
        timings["total"] = time.time() - t_start
        result["timings"] = timings
        return result

    verses = collect_verses(match.start_word_idx, match.end_word_idx)
    first_surah, first_ayah = verses[0] if verses else (None, None)
    last_surah, last_ayah = verses[-1] if verses else (None, None)

    # Pending (Fatiha basina guclu eslesme haric — namazda ilk okunan Fatiha)
    fatiha_fast = (state.state == NamazState.BEKLEME and first_surah == 1 and first_ayah is not None
                   and score >= FATIHA_FAST_LOCK_MIN_SCORE
                   and ((first_ayah <= 3 and word_count >= FATIHA_FAST_LOCK_MIN_WORDS)
                        or (hold and word_count >= MIN_WORD_COUNT_FIRST_LOCK)))
    if fatiha_fast:
        result["fatiha_fast_lock"] = True
    # Tek parcada kilit (fark payi): sadece ilk kilit (BEKLEME, bekleme yokken)
    unique = (state.state == NamazState.BEKLEME and not fatiha_fast and not hold
              and is_unique_match(text, match, score, word_count))
    if unique:
        result["unique_lock"] = True
    # Yeniden kilitte dogrulamasiz: rekat basi Fatiha (rukû/secde sonrasi beklenen), kalinan yerden devam ya da
    # 2 parcayla dogrulanmis gecis
    relock_fast = relock and (
        jump == "verified"
        or (first_surah == 1 and score >= FATIHA_FAST_LOCK_MIN_SCORE and word_count >= MIN_WORD_COUNT_FIRST_LOCK)
        or (first_surah == state.last_surah and state.last_ayah is not None and first_ayah is not None
            and state.last_ayah - RESUME_BACK <= first_ayah <= state.last_ayah + PREFERRED_AYAH_WINDOW_ARA))
    if ((state.state == NamazState.BEKLEME and not fatiha_fast) or (relock and not relock_fast)) and not unique:
        if state.pending_match is None:
            state.pending_match = PendingMatch(
                surah=last_surah, ayah=last_ayah,
                word_index=match.end_word_idx, chunk_index=chunk_index,
            )
            result["status"] = "pending"
            result["reason"] = (f"aday {get_surah_info(last_surah)['name_tr']} "
                                f"{last_surah}:{last_ayah} (skor {score}), dogrulama bekleniyor")
            result["pending_surah"] = last_surah
            result["pending_ayah"] = last_ayah
            result["state"] = state.state.value
            mark_ambiguous(result, text, match, score, state.pending_match)
            timings["total"] = time.time() - t_start
            result["timings"] = timings
            return result
        else:
            pm = state.pending_match
            verified = _verify_pending(pm, first_surah, first_ayah) or _verify_pending(pm, last_surah, last_ayah)
            # Belirsiz adayi geriye giden parca dogrulamaz (asr 21.10: 2:163 / 59:22 → "لا اله الا هو" adayin gerisinde)
            if verified and pm.alt_surah is not None and match.end_word_idx <= pm.word_index:
                verified = False
                result["ambiguous_backward"] = True
            if verified:
                pass  # dogrulandi, asagiya gec
            else:
                old_pending = state.pending_match
                state.pending_match = PendingMatch(
                    surah=last_surah, ayah=last_ayah,
                    word_index=match.end_word_idx, chunk_index=chunk_index,
                )
                result["status"] = "pending"
                result["reason"] = (f"onceki aday ({old_pending.surah}:{old_pending.ayah}) "
                                    f"reddedildi, yeni aday "
                                    f"{get_surah_info(last_surah)['name_tr']} "
                                    f"{last_surah}:{last_ayah} (skor {score})")
                result["pending_surah"] = last_surah
                result["pending_ayah"] = last_ayah
                result["state"] = state.state.value
                mark_ambiguous(result, text, match, score, state.pending_match)
                timings["total"] = time.time() - t_start
                result["timings"] = timings
                return result

    _commit_match(state, match, score, jump, result)
    if fresh:
        state.fresh_jump = (chunk_index, text)

    timings["total"] = time.time() - t_start
    timings["since_chunk_start"] = time.time() - chunk_start_time
    result["timings"] = timings
    return result


# ============================================================
# Routes
# ============================================================
@app.route("/")
def index():
    # Frontend'e secilen modeli aktar
    return render_template("index.html", asr_label=ASR_LABEL, asr_key=ARGS.asr)


@sock.route("/audio")
def audio_ws(ws):
    print(f"[WS] Baglanti: {request.remote_addr} | ASR: {ASR_LABEL}")

    session_id = str(int(time.time()))
    session_path = RECORDINGS_DIR / f"session_{ARGS.asr}_{session_id}.wav"
    state = SessionState()

    full_audio = []
    chunk_buffer = []
    chunk_buffer_samples = 0
    chunk_index = 0
    overlap_tail = np.array([], dtype=np.float32)
    chunk_start_time = None

    try:
        while True:
            msg = ws.receive()
            if msg is None:
                break
            if isinstance(msg, str):
                try:
                    data = json.loads(msg)
                    if data.get("type") == "stop":
                        break
                except json.JSONDecodeError:
                    pass
                continue
            if not isinstance(msg, bytes):
                continue

            audio_np = np.frombuffer(msg, dtype=np.float32)
            full_audio.append(audio_np)
            chunk_buffer.append(audio_np)
            chunk_buffer_samples += len(audio_np)

            if chunk_start_time is None:
                chunk_start_time = time.time()

            if chunk_buffer_samples >= CHUNK_SAMPLES:
                chunk_fill_duration = time.time() - chunk_start_time

                current = np.concatenate([overlap_tail] + chunk_buffer)
                to_process = current

                # Son 1sn → bir sonraki chunk'in basi (kesintisiz). Eski hali
                # current[CHUNK - OVERLAP:CHUNK] idi: 3. chunk'tan itibaren 1sn geriden yapistirma.
                overlap_tail = current[-OVERLAP_SAMPLES:]

                result = process_chunk(to_process, chunk_index, state, chunk_start_time)
                if "timings" in result:
                    result["timings"]["fill_wait"] = chunk_fill_duration

                t_send = time.time()
                try:
                    ws.send(json.dumps(result, ensure_ascii=False))
                except Exception:
                    break
                send_duration = time.time() - t_send
                total_latency = time.time() - chunk_start_time

                state_tag = f"[{state.state.value}]"
                t = result.get("timings", {})
                profile_str = (
                    f" | fill={t.get('fill_wait', 0):.2f}s "
                    f"asr={t.get('asr', 0):.2f}s "
                    f"align={t.get('align', 0):.3f}s "
                    f"send={send_duration:.3f}s "
                    f"TOTAL_LATENCY={total_latency:.2f}s"
                )

                if result["status"] == "matched":
                    v = result["verses"]
                    summary = ", ".join(f"{x['surah_name_tr']} {x['surah']}:{x['ayah']}" for x in v)
                    pref_tag = " [tercihli]" if result.get("in_preferred") else ""
                    gap_tag = f" [+{result['gap_filled']} ara]" if result.get("gap_filled") else ""
                    end_tag = " [sure-sonu]" if result.get("near_surah_end") else ""
                    abandon_tag = " [kilit-terk]" if result.get("lock_abandoned") else ""
                    transition_tag = ""
                    if state.state_transitions:
                        last = state.state_transitions[-1]
                        if f" → {state.state.value}" in last:
                            transition_tag = f" 🔄 {last}"
                    print(f"[chunk {chunk_index}] {state_tag} ✓ {summary} "
                          f"(guven {result['confidence']})"
                          f"{pref_tag}{gap_tag}{end_tag}{abandon_tag}{transition_tag}{profile_str}")
                elif result["status"] == "pending":
                    print(f"[chunk {chunk_index}] {state_tag} ⊙ pending "
                          f"[{result['reason']}]{profile_str}")
                else:
                    text_preview = result.get('text', '')[:30]
                    reason = result.get('reason', '')
                    reason_str = f" [{reason}]" if reason else ""
                    abandon_tag = " [kilit-terk]" if result.get("lock_abandoned") else ""
                    print(f"[chunk {chunk_index}] {state_tag} ⊘ {result['status']}"
                          f"{reason_str}{abandon_tag}"
                          f"{' | ' + text_preview if text_preview else ''}{profile_str}")

                chunk_index += 1
                chunk_buffer = []
                chunk_buffer_samples = 0
                chunk_start_time = None

    except Exception as e:
        import traceback
        print(f"[WS] Hata: {e}")
        traceback.print_exc()

    finally:
        if full_audio:
            full = np.concatenate(full_audio)
            sf.write(str(session_path), full, SAMPLE_RATE)
            duration = len(full) / SAMPLE_RATE
            print(f"[WS] Oturum: {session_path.name} ({duration:.1f}sn, "
                  f"{state.matched_chunks}/{state.total_chunks} chunk matched, "
                  f"{len(state.state_transitions)} state gecis) | ASR: {ASR_LABEL}")
            for t in state.state_transitions:
                print(f"    {t}")


if __name__ == "__main__":
    print(f"Kayit dizini: {RECORDINGS_DIR}")
    print(f"Port: {ARGS.port}")
    app.run(host="0.0.0.0", port=ARGS.port, debug=False)
