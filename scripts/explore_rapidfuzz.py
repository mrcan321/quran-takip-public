#!/usr/bin/env python3
"""
RapidFuzz davranis kesfi — Kotlin port icin referans verisi olustur.

Hedef: partial_ratio ve token_sort_ratio fonksiyonlarinin tam algoritmalarini
cikarmak. Yuzlerce farkli input/output ciftleri olustur, Kotlin tarafinda
ayni sonuclari uretmesi icin test fixture olarak kullan.

Calistirma:
  python scripts/explore_rapidfuzz.py
"""

import json
import os
from pathlib import Path
from rapidfuzz import fuzz

# FuzzyTestRunner.kt bu dosyayi APK icinde asr/fuzzy_test_fixture.json olarak okur
REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_ROOT = Path(os.environ.get("TILAVET_ASSETS_DIR", REPO_ROOT / "android-assets-staged"))
OUTPUT = ASSETS_ROOT / "asr" / "fuzzy_test_fixture.json"
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

# ============================================================
# Test cases — basitten karmasiga
# ============================================================
test_cases = [
    # ============ Trivial cases ============
    ("", ""),
    ("a", "a"),
    ("a", "b"),
    ("hello", "hello"),
    ("hello", "world"),

    # ============ Substring tests (partial_ratio'nun ana ozelligi) ============
    ("abc", "xabcx"),               # tam icerme
    ("abc", "axbxcx"),              # bozuk
    ("abc", "xxxxxx"),              # hicbir benzerlik
    ("abcd", "xxxabcdxxx"),
    ("abcd", "xxxabxdxxx"),
    ("the quick", "the quick brown fox"),
    ("brown fox", "the quick brown fox"),
    ("fox", "the quick brown fox"),
    ("the brown", "the quick brown fox"),

    # ============ Token order (token_sort_ratio'nun ana ozelligi) ============
    ("abc def", "def abc"),          # ayni token, farkli sira
    ("the quick brown fox", "fox brown quick the"),
    ("a b c d", "d c b a"),
    ("a b c", "c a b"),

    # ============ Repetition ============
    ("abc abc abc", "abc"),
    ("abc", "abc abc abc"),
    ("the the the", "the"),

    # ============ Length asymmetry ============
    ("hi", "hi there friend how are you"),
    ("hi there friend how are you", "hi"),

    # ============ Edit distance edge cases ============
    ("abc", "ab"),                   # silme
    ("abc", "abcd"),                 # ekleme
    ("abc", "abd"),                  # degistirme
    ("abc", "axc"),                  # ortadan degistirme

    # ============ Arabic — bizim icin asil onemli olan ============
    ("بسم", "بسم الله"),
    ("بسم الله", "بسم"),
    ("بسم الله", "الله بسم"),
    ("الله", "بسم الله الرحمن الرحيم"),
    ("الحمد لله", "الحمد لله رب العالمين"),
    ("الحمد لله رب العالمين", "الحمد"),
    ("بسم الله الرحمن الرحيم", "الرحمن الرحيم بسم الله"),

    # ============ Quran ayet parcalarindan ornekler ============
    ("الحمد لله رب العالمين الرحمن الرحيم",
     "الحمد لله رب العالمين"),
    ("قل هو الله احد",
     "قل هو الله احد الله الصمد"),
    ("اقرا باسم ربك",
     "اقرا باسم ربك الذي خلق"),
    ("الرحمن علم القران",
     "الرحمن علم القران خلق الانسان"),

    # ============ ASR hatasi tipi (extra/missing words) ============
    ("الحمد لله", "الحمد له"),       # cift karakter dusurme
    ("الرحمن", "الرحمان"),           # ekstra karakter
    ("بسم الله الرحمن الرحيم الحمد",
     "الحمد لله رب العالمين"),

    # ============ Bos string'ler ============
    ("", "abc"),
    ("abc", ""),
    (" ", "abc"),
    ("abc", " "),
    ("   ", "   "),

    # ============ Tek karakter ============
    ("a", "abc"),
    ("a", "xax"),
    ("z", "abc"),

    # ============ Sayilar (genelde olmaz ama testleyelim) ============
    ("123", "12345"),
    ("123 456", "456 123"),
]

results = []
for s1, s2 in test_cases:
    partial = fuzz.partial_ratio(s1, s2)
    sorted_ = fuzz.token_sort_ratio(s1, s2)
    raw_score = 0.6 * partial + 0.4 * sorted_

    results.append({
        "s1": s1,
        "s2": s2,
        "partial_ratio": round(partial, 4),
        "token_sort_ratio": round(sorted_, 4),
        "combined_score": round(raw_score, 4),
    })

# Yazdir
print(f"=" * 60)
print(f"RapidFuzz fixture — {len(results)} test case")
print(f"=" * 60)

# Tabular output
print(f"\n{'partial':>8} {'sorted':>8} {'combined':>9}  s1 / s2")
print("-" * 60)
for r in results:
    print(f"{r['partial_ratio']:>8.2f} {r['token_sort_ratio']:>8.2f} "
          f"{r['combined_score']:>9.2f}  '{r['s1'][:30]}' / '{r['s2'][:30]}'")

# JSON kaydet
with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump({
        "version": 1,
        "description": "RapidFuzz partial_ratio + token_sort_ratio test fixture",
        "cases": results,
    }, f, ensure_ascii=False, indent=2)

print(f"\nKaydedildi: {OUTPUT} ({OUTPUT.stat().st_size} bytes)")
print(f"\nKotlin port'u bu fixture'a karsi test edilecek.")
print(f"Her test case icin partial_ratio ve token_sort_ratio degerlerinin")
print(f"birebir ayni cikmasi gerekiyor.")
