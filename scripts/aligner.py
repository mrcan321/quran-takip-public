"""
Kuran metni hizalama modülü (trigram indeksli + hard preferred_range + besmele filtreleme)

Eşleştirme imla'i yazımla yapılır:
  Korpus metni Uthmani (Tanzil, api.alquran.cloud) — ekranda bu gösterilir.
  ASR ise standart imla'i yazımla çıktı verir (الكتاب, الصلاة, العالمين ...).
  Uthmani normalize edilince küçük elif (U+0670) silinir ve kelime değişir
  (الكتب, الصلوه, العلمين) → Kuran kelimelerinin ~%10'u ASR çıktısıyla hiç eşleşmez,
  vocab_coverage ve fuzzy skor düşer.
  Çözüm: her Uthmani kelimenin `normalized` alanı, imla'i karşılığının normalize hâli
  (Tanzil rasm_map, quran-transcript paketi). `text` alanı Uthmani kalır.
  Bazı Uthmani kelimeler imla'ide iki kelime olur (يَٰٓأَيُّهَا → يا ايها): normalized'da boşluk olur,
  vocab ve trigram tarafında boşluktan bölünür.
"""
import difflib
import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from rapidfuzz import fuzz

QURAN_JSON_URL = "https://api.alquran.cloud/v1/quran/quran-uthmani"
CACHE_DIR = Path.home() / ".cache" / "quran-align"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
QURAN_CACHE = CACHE_DIR / "quran-uthmani.json"

# Uthmani → imla'i kelime haritası (Tanzil Uthmani 1.1 + imla'i karşılıkları).
# quran-transcript (MIT) wheel'inin içinden alınır — sürüm ve sha256 sabit.
RASM_MAP_CACHE = CACHE_DIR / "quran-uthmani-imlaey-map.json"
RASM_WHEEL_URL = (
    "https://files.pythonhosted.org/packages/88/9f/"
    "355569ee077aeebcba700d8b010be2a3d11a9fe97d0b053a9b7aa1747245/"
    "quran_transcript-0.6.4-py3-none-any.whl"
)
RASM_WHEEL_SHA256 = "8db46fa8217514d44b81abfe548b92f7eb6d23988195ad2c193c7d69c13c50a9"
RASM_WHEEL_MEMBER = "quran_transcript/quran-script/quran-uthmani-imlaey-map.json"


# ---------------------------------------------------------------------------
# Arapça metin normalizasyonu
# ---------------------------------------------------------------------------

ARABIC_DIACRITICS = re.compile(
    r"[ؐ-ًؚ-ٰٟۖ-ۭـ]"
)
NORMALIZATION_MAP = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ئ": "ي",
    "ؤ": "و",
    "ة": "ه",
})
ZERO_WIDTH = re.compile(r"[﻿​‌‍‪-‮]")

def normalize_arabic(text: str) -> str:
    text = ZERO_WIDTH.sub("", text)         # BU SATIRI EKLE
    text = ARABIC_DIACRITICS.sub("", text)
    text = text.translate(NORMALIZATION_MAP)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Besmele algılama
# ---------------------------------------------------------------------------

# Normalize edilmiş besmele kelimeleri
BISMILLAH_NORMALIZED_TOKENS = {
    "بسم",      # bismi
    "الله",     # allâh
    "الرحمن",   # rahmân
    "الرحيم",   # rahîm
}


def is_bismillah_only(normalized_tokens: List[str]) -> bool:
    """
    Verilen tokenlar SADECE besmeleden ibaret mi?
    Tolerans: 1-2 ekstra kelime olabilir (ASR hatası), ama besmele kelimeleri çoğunlukta olmalı.

    Başta tam besmele varsa karar, besmeleden sonra kalan kelime sayısına göre verilir:
    "بسم الله الرحمن الرحيم قل هو الله" eskiden besmele sayılıyordu (الله de besmele kelimesi
    → 5/7 ≥ 0.6) ve her sure başı reddediliyordu. Artık kalan 2+ kelime varsa hizalanır.
    """
    if not normalized_tokens:
        return False
    rest = strip_bismillah_prefix(normalized_tokens)
    if len(rest) < len(normalized_tokens):
        return len(rest) < 2
    # Başta tam besmele yok (eksik/bozuk okunmuş olabilir) → oran kuralı
    bismillah_count = sum(1 for t in normalized_tokens if t in BISMILLAH_NORMALIZED_TOKENS)
    # En az 3 besmele kelimesi var ve token'ların çoğu besmele
    return bismillah_count >= 3 and bismillah_count / len(normalized_tokens) >= 0.6


def strip_bismillah_prefix(normalized_tokens: List[str]) -> List[str]:
    """
    Tokenların başındaki besmele kısmını çıkar.
    "bismi allâh rahmân rahîm <başka kelimeler>" → "<başka kelimeler>"
    Eğer başında besmele yoksa, listeyi olduğu gibi döner.
    """
    # İlk 4 token'a bak — besmele kelimeleri var mı?
    if len(normalized_tokens) < 4:
        return normalized_tokens

    first_four = normalized_tokens[:4]
    bismillah_in_first_four = sum(1 for t in first_four if t in BISMILLAH_NORMALIZED_TOKENS)

    if bismillah_in_first_four >= 3:
        # Başlangıçta besmele var, ilk 4 token'ı atla
        return normalized_tokens[4:]

    return normalized_tokens


# ---------------------------------------------------------------------------
# Uthmani → imla'i haritası
# ---------------------------------------------------------------------------

def ensure_rasm_map() -> Path:
    """Harita cache'de yoksa quran-transcript wheel'ini indir, JSON'u çıkar."""
    if RASM_MAP_CACHE.exists():
        return RASM_MAP_CACHE
    print(f"Uthmani→imla'i haritası indiriliyor: {RASM_WHEEL_URL}", file=sys.stderr)
    with urllib.request.urlopen(RASM_WHEEL_URL) as resp:
        wheel = resp.read()
    digest = hashlib.sha256(wheel).hexdigest()
    if digest != RASM_WHEEL_SHA256:
        raise RuntimeError(f"quran-transcript wheel sha256 uyuşmuyor: {digest}")
    with zipfile.ZipFile(io.BytesIO(wheel)) as zf:
        RASM_MAP_CACHE.write_bytes(zf.read(RASM_WHEEL_MEMBER))
    return RASM_MAP_CACHE


def load_rasm_map() -> Dict[Tuple[int, int], List[Tuple[str, str]]]:
    """(sure, ayet) → [(uthmani_kelime, imlai_karsilik), ...]"""
    with open(ensure_rasm_map(), "r", encoding="utf-8") as f:
        data = json.load(f)
    result: Dict[Tuple[int, int], List[Tuple[str, str]]] = {}
    for sura in data["quran"]["sura"]:
        s = int(sura["@index"])
        ayas = sura["aya"] if isinstance(sura["aya"], list) else [sura["aya"]]
        for aya in ayas:
            a = int(aya["@index"])
            rm = aya["rasm_map"]
            rm = rm if isinstance(rm, list) else [rm]
            result[(s, a)] = [(w["@uthmani"], w["@imlaey"]) for w in rm]
    return result


def map_ayah_to_imlaei(uthmani_norms: List[str],
                       rasm_pairs: List[Tuple[str, str]]) -> Tuple[List[str], int]:
    """
    Bir ayetin (normalize) Uthmani kelimelerini imla'i karşılıklarına çevir.

    Korpus metni ile haritanın Uthmani'si birebir aynı olmayabilir (besmele öneki,
    Tanzil sürüm farkları) → SequenceMatcher ile sadece normalize hâli aynı olan
    kelimeler eşlenir, geri kalanı Uthmani normalize hâliyle kalır.

    Dönüş: (normalized listesi, eşlenen kelime sayısı)
    """
    rasm_u = [normalize_arabic(u) for u, _ in rasm_pairs]
    rasm_i = [normalize_arabic(i) for _, i in rasm_pairs]
    out = list(uthmani_norms)
    matched = 0
    sm = difflib.SequenceMatcher(a=uthmani_norms, b=rasm_u, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            continue
        for k in range(i2 - i1):
            if rasm_i[j1 + k]:
                out[i1 + k] = rasm_i[j1 + k]
            matched += 1
    return out, matched


# ---------------------------------------------------------------------------
# Kuran korpusu
# ---------------------------------------------------------------------------

@dataclass
class QuranWord:
    surah: int
    ayah: int
    word_index: int
    text: str
    normalized: str


def _word_to_trigrams(word: str) -> Set[str]:
    if len(word) < 3:
        return {word}
    padded = f"  {word}  "
    return {padded[i:i+3] for i in range(len(padded) - 2)}


def normalized_to_trigrams(normalized: str) -> Set[str]:
    """Korpus kelimesinin trigramları — imla'i karşılığı çok kelimeliyse her parça ayrı."""
    result: Set[str] = set()
    for part in normalized.split(" "):
        if part:
            result |= _word_to_trigrams(part)
    return result


class QuranCorpus:
    def __init__(self, words: List[QuranWord]):
        self.words = words
        self.normalized_tokens = [w.normalized for w in words]
        # score_transcription icin: ASR token'lari tek kelime, korpus kelimesi "يا ايها" olabilir
        self.vocab: Set[str] = {part for n in self.normalized_tokens for part in n.split(" ") if part}

        print(f"Trigram indeks oluşturuluyor...", file=sys.stderr)
        import time
        _t0 = time.time()
        self._word_trigram_index: Dict[str, Set[int]] = self._build_trigram_index()
        print(f"Trigram indeks: {len(self._word_trigram_index)} 3-gram "
              f"({time.time() - _t0:.2f}sn)", file=sys.stderr)

    def _build_trigram_index(self) -> Dict[str, Set[int]]:
        index: Dict[str, Set[int]] = defaultdict(set)
        for pos, word in enumerate(self.normalized_tokens):
            for tri in normalized_to_trigrams(word):
                index[tri].add(pos)
        return index

    def find_candidate_positions(
        self, query_tokens: List[str], min_hits: int = 1,
        position_filter: Optional[Tuple[int, int]] = None,
    ) -> Set[int]:
        position_hits: Dict[int, int] = defaultdict(int)

        all_trigrams: Set[str] = set()
        for token in query_tokens:
            all_trigrams.update(_word_to_trigrams(token))

        for tri in all_trigrams:
            if tri in self._word_trigram_index:
                for pos in self._word_trigram_index[tri]:
                    if position_filter is not None:
                        ps, pe = position_filter
                        if not (ps <= pos <= pe):
                            continue
                    position_hits[pos] += 1

        return {pos for pos, count in position_hits.items() if count >= min_hits}

    @classmethod
    def load(cls, imlaei: bool = True) -> "QuranCorpus":
        """
        imlaei=True (varsayılan): normalized = imla'i karşılık (ASR ile eşleşme için).
        imlaei=False: eski davranış, normalized = Uthmani'nin normalize hâli (karşılaştırma için).
        """
        if not QURAN_CACHE.exists():
            print(f"Kuran metni indiriliyor: {QURAN_JSON_URL}", file=sys.stderr)
            urllib.request.urlretrieve(QURAN_JSON_URL, QURAN_CACHE)

        with open(QURAN_CACHE, "r", encoding="utf-8") as f:
            data = json.load(f)

        rasm_map = load_rasm_map() if imlaei else {}
        stats = {"ayah": 0, "full": 0, "partial": 0, "missing": 0, "words": 0, "mapped": 0, "changed": 0}

        words: List[QuranWord] = []
        for surah in data["data"]["surahs"]:
            s_num = surah["number"]
            for ayah in surah["ayahs"]:
                a_num = ayah["numberInSurah"]
                text = ayah["text"]
                tokens = text.split()
                ayah_words: List[QuranWord] = []
                for idx, tok in enumerate(tokens):
                    norm = normalize_arabic(tok)
                    if not norm:
                        continue
                    ayah_words.append(QuranWord(
                        surah=s_num, ayah=a_num,
                        word_index=idx, text=tok, normalized=norm,
                    ))

                if imlaei:
                    stats["ayah"] += 1
                    stats["words"] += len(ayah_words)
                    pairs = rasm_map.get((s_num, a_num))
                    if pairs is None:
                        stats["missing"] += 1
                    else:
                        # alquran.cloud 1. ayetlerin başına besmele ekliyor (Fatiha ve Tevbe hariç);
                        # haritada yok, besmele imla'ide de aynı → atla
                        skip = 0
                        if a_num == 1 and s_num not in (1, 9) and len(ayah_words) >= 4 and \
                                all(w.normalized in BISMILLAH_NORMALIZED_TOKENS for w in ayah_words[:4]):
                            skip = 4
                        rest = ayah_words[skip:]
                        new_norms, matched = map_ayah_to_imlaei([w.normalized for w in rest], pairs)
                        for w, n in zip(rest, new_norms):
                            if n != w.normalized:
                                stats["changed"] += 1
                            w.normalized = n
                        stats["mapped"] += matched + skip
                        if matched == len(rest) == len(pairs):
                            stats["full"] += 1
                        else:
                            stats["partial"] += 1
                words.extend(ayah_words)

        print(f"Kuran yüklendi: {len(words)} kelime", file=sys.stderr)
        if imlaei:
            print(f"  imla'i eşleme: {stats['mapped']}/{stats['words']} kelime eşlendi, "
                  f"{stats['changed']} kelimenin normalize hâli değişti; "
                  f"ayet: {stats['full']} tam, {stats['partial']} kısmi, {stats['missing']} haritada yok",
                  file=sys.stderr)
        return cls(words)

    def filter_surah(self, surah: int) -> "QuranCorpus":
        filtered = [w for w in self.words if w.surah == surah]
        return QuranCorpus(filtered)


# ---------------------------------------------------------------------------
# Hizalama
# ---------------------------------------------------------------------------

@dataclass
class AlignmentMatch:
    start_word_idx: int
    end_word_idx: int
    score: float
    recited_text: str


def align_transcription(
    transcription: str,
    corpus: QuranCorpus,
    window_slack: int = 5,
    preferred_range: Optional[Tuple[int, int]] = None,
    preferred_bonus: float = 8.0,  # geriye uyumluluk
    min_score_threshold: float = 40.0,
    exclude_range: Optional[Tuple[int, int]] = None,
) -> Optional[AlignmentMatch]:
    """
    Trigram indeks + HARD preferred_range + besmele filtreleme.

    exclude_range: bu kelime araligina degen pencereler atlanir — "en iyi eslesmenin disindaki en iyi ikinci yer"
    (fark payi / tek parcada kilit icin, bkz. build_state_machine_fixture.UNIQUE_LOCK_*).

    Besmele kuralları:
    - Eğer transkript SADECE besmeleden ibaretse → eşleşme yok (None)
    - Eğer transkript besmele + başka kelimelerle başlıyorsa → besmele atlanır,
      sadece sonraki kelimeler hizalanır
    """
    recited_tokens = [normalize_arabic(t) for t in transcription.split()]
    recited_tokens = [t for t in recited_tokens if t]
    if not recited_tokens:
        return None

    # YENİ: Sadece besmele ise eşleşme yok
    if is_bismillah_only(recited_tokens):
        return None

    # YENİ: Başlangıçta besmele varsa atla
    recited_tokens = strip_bismillah_prefix(recited_tokens)
    if not recited_tokens:
        return None

    recited_joined = " ".join(recited_tokens)
    n = len(recited_tokens)
    corpus_size = len(corpus.normalized_tokens)

    # --- Adım 1: Aday pozisyonları bul ---
    desired_hits = max(2, n // 2)
    candidate_positions = corpus.find_candidate_positions(
        recited_tokens, min_hits=desired_hits,
        position_filter=preferred_range,
    )
    if not candidate_positions:
        candidate_positions = corpus.find_candidate_positions(
            recited_tokens, min_hits=1,
            position_filter=preferred_range,
        )

    if not candidate_positions:
        return None

    # --- Adım 2: Aday pozisyonlar etrafında küçük genişleme ---
    expanded_starts: Set[int] = set()
    for pos in candidate_positions:
        for offset in (-2, -1, 0, 1, 2):
            s = pos + offset
            if 0 <= s < corpus_size:
                if preferred_range is not None:
                    ps, pe = preferred_range
                    if not (ps <= s <= pe):
                        continue
                if exclude_range is not None and exclude_range[0] <= s <= exclude_range[1]:
                    continue
                expanded_starts.add(s)

    if not expanded_starts:
        return None

    sorted_starts = sorted(expanded_starts)

    # --- Adım 3: Sadece adaylarda fuzzy matching ---
    best_score = -1.0
    best_span: Tuple[int, int] = (0, 0)

    for window_size in range(max(1, n - window_slack), n + window_slack + 1):
        if window_size > corpus_size:
            continue
        max_start = corpus_size - window_size
        for i in sorted_starts:
            if i > max_start:
                continue
            if preferred_range is not None:
                ps, pe = preferred_range
                if i + window_size - 1 > pe:
                    continue
            if exclude_range is not None and i <= exclude_range[1] and i + window_size - 1 >= exclude_range[0]:
                continue
            candidate = " ".join(corpus.normalized_tokens[i : i + window_size])
            partial = fuzz.partial_ratio(recited_joined, candidate)
            sorted_ = fuzz.token_sort_ratio(recited_joined, candidate)
            raw_score = 0.6 * partial + 0.4 * sorted_

            if raw_score > best_score:
                best_score = raw_score
                best_span = (i, i + window_size - 1)
                if raw_score >= 98:
                    return AlignmentMatch(
                        start_word_idx=best_span[0],
                        end_word_idx=best_span[1],
                        score=raw_score,
                        recited_text=transcription,
                    )

    if best_score < min_score_threshold:
        return None

    return AlignmentMatch(
        start_word_idx=best_span[0],
        end_word_idx=best_span[1],
        score=best_score,
        recited_text=transcription,
    )


# ---------------------------------------------------------------------------
# Yardımcı
# ---------------------------------------------------------------------------

def format_match(match: AlignmentMatch, corpus: QuranCorpus) -> str:
    if not match:
        return "(eşleşme yok)"
    words = corpus.words[match.start_word_idx : match.end_word_idx + 1]
    start = words[0]
    end = words[-1]
    if start.surah == end.surah and start.ayah == end.ayah:
        loc = f"Sure {start.surah}:{start.ayah} (kelime {start.word_index+1}-{end.word_index+1})"
    else:
        loc = f"Sure {start.surah}:{start.ayah} → {end.surah}:{end.ayah}"
    matched_text = " ".join(w.text for w in words)
    return f"{loc}\n  {matched_text}\n  (skor: {match.score:.1f}/100)"
