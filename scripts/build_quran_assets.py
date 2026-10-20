#!/usr/bin/env python3
"""
Quran Asset Builder — Android packed binary format

Hedef: aligner.py'nin tum verilerini onceden hesaplayip Android'in mmap
edebilecegi tek dosyalik binary'lere paketle.

Cikti: <repo>/android-assets-staged/asr/  (TILAVET_ASSETS_DIR ile degistirilebilir)
  - quran.bin       (kelimeler + trigram indeksi, ~6 MB)
  - meal.bin        (meal + sure isimleri, ~1.5 MB)

Format:
==========================================================
quran.bin (little-endian, all multi-byte ints):

[Header — 32 bytes]
  magic: "QRAN"        (4 bytes)
  version: u32         (4 bytes) = 1
  word_count: u32      (4 bytes) = 77878
  trigram_count: u32   (4 bytes) = 7519
  text_section_offset: u64
  trigram_section_offset: u64

[Words section — fixed 16 bytes per word]
  Per word:
    surah: u16
    ayah: u16
    word_idx: u16 (kelime ayet icindeki indeks)
    text_offset: u32 (text section icinde offset)
    text_len: u8
    normalized_offset: u32 (text section icinde offset)
    normalized_len: u8
  Total: 16 bytes * 77878 = ~1.2 MB

[Text section — variable length]
  Tum stringler UTF-8 packed (text + normalized birarada)
  ~1.5 MB tahmini

[Trigram section]
  Per trigram entry:
    trigram_utf8_len: u8
    trigram_utf8: bytes (3 chars Arabic = ~6 bytes)
    word_idx_count: u32
    word_indices: u32[count] (sirali, ascending)
  ~3 MB tahmini

==========================================================
meal.bin:

[Header — 16 bytes]
  magic: "MEAL"
  version: u32 = 1
  meal_count: u32
  surah_count: u32

[Meal entries — variable]
  Per entry:
    surah: u16
    ayah: u16
    meal_utf8_len: u16
    meal_utf8: bytes
  ~6236 entries

[Surah entries]
  Per surah (1-114):
    surah_no: u16
    name_tr_len: u8, name_tr: bytes
    name_ar_len: u8, name_ar: bytes
    ayah_count: u16
==========================================================
"""

import json
import os
import struct
import sys
from collections import defaultdict
from pathlib import Path

# ============================================================
# Paths
# ============================================================
HOME = Path.home()
CACHE_DIR = HOME / ".cache" / "quran-align"
QURAN_JSON = CACHE_DIR / "quran-uthmani.json"
SURAH_JSON = CACHE_DIR / "surah-names.json"

# Asset staging: TILAVET_ASSETS_DIR verilmisse orasi, yoksa repo kokundeki
# android-assets-staged/ (gitignore'da). Gradle de ayni yolu okur.
REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_ROOT = Path(os.environ.get("TILAVET_ASSETS_DIR", REPO_ROOT / "android-assets-staged"))
OUTPUT_DIR = ASSETS_ROOT / "asr"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
QURAN_BIN = OUTPUT_DIR / "quran.bin"
MEAL_BIN = OUTPUT_DIR / "meal.bin"

# ============================================================
# Kelimeler + normalizasyon aligner.py'dan (tek kaynak)
# ============================================================
# QuranCorpus.load(): Uthmani metin (text) + imla'i karsiligin normalize hali (normalized).
# Fixture'lar, server ve quran.bin ayni kelime listesini kullanir → Kotlin ile Python birebir.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from aligner import QuranCorpus, normalized_to_trigrams  # noqa: E402
# Meal baskisi (ayet ayet ayrik) + cache yolu download_meal.py'da (tek kaynak)
from download_meal import MEAL_CACHE as MEAL_JSON, MEAL_EDITION, consecutive_duplicates  # noqa: E402

# Ardisik ayette birebir ayni meal = baski ayetleri birlestirmis (tr.diyanet: 841, Nasr 110:1-3 tek meal).
# Ekranda her ayetin kendi meali olmali → bu sayidan fazlaysa build durur.
MAX_MEAL_DUPLICATES = 20

# ============================================================
# Build quran.bin
# ============================================================
def build_quran_bin():
    # 1. Tum kelimeler (normalize + imla'i eslemesi aligner.py'da)
    corpus = QuranCorpus.load()
    words = [(w.surah, w.ayah, w.word_index, w.text, w.normalized) for w in corpus.words]
    print(f"  Toplam kelime: {len(words)}")

    # 2. Text section — tum benzersiz stringleri tek bir blob'a koy
    # (Aynı string'i birden fazla kelimede gorebiliriz, dedupe)
    string_blob = bytearray()
    string_offsets = {}  # str -> (offset, length)

    def add_string(s: str) -> tuple:
        if s in string_offsets:
            return string_offsets[s]
        encoded = s.encode("utf-8")
        if len(encoded) > 255:
            raise ValueError(f"String cok uzun: {s} ({len(encoded)} bytes)")
        offset = len(string_blob)
        string_blob.extend(encoded)
        result = (offset, len(encoded))
        string_offsets[s] = result
        return result

    # 3. Word records
    word_records = []  # List of (surah, ayah, word_idx, text_off, text_len, norm_off, norm_len)
    for s, a, w_idx, text, norm in words:
        text_off, text_len = add_string(text)
        norm_off, norm_len = add_string(norm)
        word_records.append((s, a, w_idx, text_off, text_len, norm_off, norm_len))

    print(f"  Text section: {len(string_blob)} bytes ({len(string_offsets)} unique string)")

    # 4. Trigram indeks — aligner.py ile birebir ayni hesaplama (cok kelimeli imla'i: parca parca)
    trigram_index = defaultdict(set)
    for word_pos, (_, _, _, _, _, _, _) in enumerate(word_records):
        norm = words[word_pos][4]  # normalized text
        for tri in normalized_to_trigrams(norm):
            trigram_index[tri].add(word_pos)

    # Sirayi belirle (her trigram icin word indices ascending)
    trigram_entries = []
    for tri in sorted(trigram_index.keys()):
        indices = sorted(trigram_index[tri])
        tri_utf8 = tri.encode("utf-8")
        trigram_entries.append((tri_utf8, indices))

    print(f"  Trigram count: {len(trigram_entries)}")
    total_trigram_indices = sum(len(idx) for _, idx in trigram_entries)
    print(f"  Total trigram->word mapping: {total_trigram_indices}")

    # ============================================================
    # Yaz
    # ============================================================
    out = bytearray()

    # Header — once boyutlari hesapla
    word_section_size = len(word_records) * 16  # 16 bytes per word
    trigram_section_size = sum(
        1 + len(tri) + 4 + 4 * len(idx)  # len byte + utf8 + count u32 + indices u32[]
        for tri, idx in trigram_entries
    )

    HEADER_SIZE = 32
    text_section_offset = HEADER_SIZE + word_section_size
    trigram_section_offset = text_section_offset + len(string_blob)

    # Header
    out.extend(b"QRAN")                                      # magic (4)
    out.extend(struct.pack("<I", 1))                         # version (4)
    out.extend(struct.pack("<I", len(word_records)))         # word_count (4)
    out.extend(struct.pack("<I", len(trigram_entries)))      # trigram_count (4)
    out.extend(struct.pack("<Q", text_section_offset))       # text section offset (8)
    out.extend(struct.pack("<Q", trigram_section_offset))    # trigram section offset (8)
    assert len(out) == HEADER_SIZE

    # Words section
    for s, a, w_idx, t_off, t_len, n_off, n_len in word_records:
        out.extend(struct.pack("<HHH", s, a, w_idx))         # 6 bytes
        out.extend(struct.pack("<IB", t_off, t_len))         # 5 bytes
        out.extend(struct.pack("<IB", n_off, n_len))         # 5 bytes
        # Total: 16 bytes per word
    assert len(out) == HEADER_SIZE + word_section_size

    # Text section
    out.extend(string_blob)
    assert len(out) == text_section_offset + len(string_blob)

    # Trigram section
    for tri_utf8, indices in trigram_entries:
        out.append(len(tri_utf8))                            # u8 length
        out.extend(tri_utf8)                                 # utf8 bytes
        out.extend(struct.pack("<I", len(indices)))          # u32 count
        for idx in indices:
            out.extend(struct.pack("<I", idx))               # u32 index

    # Yaz
    QURAN_BIN.write_bytes(out)
    print(f"  Yazildi: {QURAN_BIN} ({len(out) / 1024 / 1024:.2f} MB)")

    # Stats
    print(f"  Header:   {HEADER_SIZE} bytes")
    print(f"  Words:    {word_section_size} bytes ({word_section_size / 1024 / 1024:.2f} MB)")
    print(f"  Text:     {len(string_blob)} bytes ({len(string_blob) / 1024 / 1024:.2f} MB)")
    print(f"  Trigrams: {trigram_section_size} bytes ({trigram_section_size / 1024 / 1024:.2f} MB)")

    return word_records, words, trigram_entries

# ============================================================
# Build meal.bin
# ============================================================
def build_meal_bin():
    print(f"\nYukleniyor: {MEAL_JSON}")
    with open(MEAL_JSON, "r", encoding="utf-8") as f:
        meals = json.load(f)
    dups = consecutive_duplicates(meals)
    print(f"  Meal count: {len(meals)} ({MEAL_EDITION}), ardisik tekrar: {len(dups)} {dups[:6]}")
    if len(dups) > MAX_MEAL_DUPLICATES:
        raise ValueError(f"{MEAL_EDITION}: {len(dups)} ayette meal onceki ayetle ayni (birlestirilmis ayetler) "
                         f"— ayet ayet ayrik bir baski sec (scripts/compare_meals.py)")

    print(f"Yukleniyor: {SURAH_JSON}")
    with open(SURAH_JSON, "r", encoding="utf-8") as f:
        surahs = json.load(f)
    print(f"  Surah count: {len(surahs)}")

    # Ayah counts (her surenin kac ayeti var)
    ayah_counts = defaultdict(int)
    for key in meals.keys():
        s, a = key.split(":")
        s, a = int(s), int(a)
        if a > ayah_counts[s]:
            ayah_counts[s] = a

    out = bytearray()

    # Header
    out.extend(b"MEAL")
    out.extend(struct.pack("<I", 1))                          # version
    out.extend(struct.pack("<I", len(meals)))                 # meal_count
    out.extend(struct.pack("<I", len(surahs)))                # surah_count

    # Meal entries — sirali (surah, ayah)
    sorted_meals = sorted(
        meals.items(),
        key=lambda kv: tuple(int(x) for x in kv[0].split(":"))
    )
    for key, text in sorted_meals:
        s, a = (int(x) for x in key.split(":"))
        text_utf8 = text.encode("utf-8")
        if len(text_utf8) > 65535:
            raise ValueError(f"Meal cok uzun: {key} ({len(text_utf8)} bytes)")
        out.extend(struct.pack("<HHH", s, a, len(text_utf8)))
        out.extend(text_utf8)

    # Surah entries
    for s_str in sorted(surahs.keys(), key=lambda x: int(x)):
        s_num = int(s_str)
        info = surahs[s_str]
        name_tr = info.get("turkish", f"Sure {s_num}").encode("utf-8")
        name_ar = info.get("arabic", "").encode("utf-8")
        if len(name_tr) > 255 or len(name_ar) > 255:
            raise ValueError(f"Sure ismi cok uzun: {s_num}")
        out.extend(struct.pack("<H", s_num))
        out.append(len(name_tr))
        out.extend(name_tr)
        out.append(len(name_ar))
        out.extend(name_ar)
        out.extend(struct.pack("<H", ayah_counts.get(s_num, 0)))

    MEAL_BIN.write_bytes(out)
    print(f"  Yazildi: {MEAL_BIN} ({len(out) / 1024:.1f} KB)")

# ============================================================
# Verification — yazılanı geri okuyup test et
# ============================================================
def verify_quran_bin():
    print(f"\n--- Verification: {QURAN_BIN} ---")
    data = QURAN_BIN.read_bytes()

    # Header
    magic = data[0:4]
    assert magic == b"QRAN", f"Magic yanlis: {magic}"
    version, word_count, trigram_count = struct.unpack("<III", data[4:16])
    text_offset, trigram_offset = struct.unpack("<QQ", data[16:32])
    print(f"  Magic: {magic.decode()}, version: {version}")
    print(f"  Word count: {word_count}, Trigram count: {trigram_count}")
    print(f"  Text offset: {text_offset}, Trigram offset: {trigram_offset}")

    # Ilk 5 kelimeyi oku
    print("\n  Ilk 5 kelime:")
    for i in range(5):
        word_offset = 32 + i * 16
        s, a, w_idx = struct.unpack("<HHH", data[word_offset:word_offset+6])
        t_off, t_len = struct.unpack("<IB", data[word_offset+6:word_offset+11])
        n_off, n_len = struct.unpack("<IB", data[word_offset+11:word_offset+16])
        text = data[text_offset+t_off:text_offset+t_off+t_len].decode("utf-8")
        norm = data[text_offset+n_off:text_offset+n_off+n_len].decode("utf-8")
        print(f"    [{i}] {s}:{a}.{w_idx} '{text}' -> '{norm}'")

    # Ilk birkac trigram
    print(f"\n  Ilk 5 trigram:")
    pos = trigram_offset
    for i in range(5):
        tri_len = data[pos]
        pos += 1
        tri = data[pos:pos+tri_len].decode("utf-8")
        pos += tri_len
        count = struct.unpack("<I", data[pos:pos+4])[0]
        pos += 4
        first_indices = struct.unpack(f"<{min(count, 5)}I", data[pos:pos+min(count, 5)*4])
        pos += count * 4  # tum index'leri atla, sonraki trigram'a gec
        print(f"    [{i}] '{tri}' -> {count} kelime, ilk birkac: {first_indices}")

def verify_meal_bin():
    print(f"\n--- Verification: {MEAL_BIN} ---")
    data = MEAL_BIN.read_bytes()
    magic = data[0:4]
    assert magic == b"MEAL", f"Magic yanlis: {magic}"
    version, meal_count, surah_count = struct.unpack("<III", data[4:16])
    print(f"  Magic: {magic.decode()}, version: {version}")
    print(f"  Meal count: {meal_count}, Surah count: {surah_count}")

    # Ilk 3 meal
    pos = 16
    print("\n  Ilk 3 meal:")
    for i in range(3):
        s, a, m_len = struct.unpack("<HHH", data[pos:pos+6])
        pos += 6
        meal_text = data[pos:pos+m_len].decode("utf-8")
        pos += m_len
        print(f"    {s}:{a} -> {meal_text[:80]}...")

    # Tum meal'leri atla, surah'lara gec
    # Bu basit verification icin yeterli — tam parser Kotlin tarafinda yazilacak

# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Quran Asset Builder — Android packed binary")
    print("=" * 60)

    build_quran_bin()
    build_meal_bin()
    verify_quran_bin()
    verify_meal_bin()

    print("\n" + "=" * 60)
    print("BASARILI")
    print("=" * 60)
    print(f"  Quran bin: {QURAN_BIN}")
    print(f"  Meal bin:  {MEAL_BIN}")
    print(f"\nBu dosyalar APK build sirasinda otomatik kullanilacak")
    print(f"(android-assets-staged/asr/ klasorunde duruyor)")
