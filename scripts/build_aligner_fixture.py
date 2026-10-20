#!/usr/bin/env python3
"""
Aligner test fixture uretici — Kotlin port'u dogrulamak icin.

Hedef: 30-50 farkli transkripsiyon icin Python aligner'in dondurdugu
tam sonucu (start_word_idx, end_word_idx, score) JSON'a kaydet.
Kotlin port'u bu fixture'a karsi her case'de aynı sonucu vermeli.

Calistirma:
  python scripts/build_aligner_fixture.py
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aligner import QuranCorpus, align_transcription, normalize_arabic

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_ROOT = Path(os.environ.get("TILAVET_ASSETS_DIR", REPO_ROOT / "android-assets-staged"))
OUTPUT = ASSETS_ROOT / "asr" / "aligner_test_fixture.json"

# ============================================================
# Test cases — gercek Kuran metinlerinden cesitli durumlar
# ============================================================
test_cases = [
    # ============ Basit test ler ============
    # Format: (transcription, [optional preferred_range], description)

    # Bos / gecersiz girdiler
    {
        "transcription": "",
        "description": "bos transkripsiyon",
    },
    {
        "transcription": "   ",
        "description": "bosluk",
    },

    # Sadece besmele -> None
    {
        "transcription": "بسم الله الرحمن الرحيم",
        "description": "sadece besmele - eslesme yok beklenir",
    },
    {
        "transcription": "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ",
        "description": "sadece besmele (harekeli)",
    },

    # Besmele + diger
    {
        "transcription": "بسم الله الرحمن الرحيم الحمد لله رب العالمين",
        "description": "besmele + Fatiha 1:2 - besmele atlanmali",
    },

    # ============ Fatiha (sure 1) ============
    {
        "transcription": "الحمد لله رب العالمين",
        "description": "Fatiha 1:2 tam",
    },
    {
        "transcription": "الرحمن الرحيم",
        "description": "Fatiha 1:3 tam (kisa)",
    },
    {
        "transcription": "مالك يوم الدين",
        "description": "Fatiha 1:4",
    },
    {
        "transcription": "اياك نعبد واياك نستعين",
        "description": "Fatiha 1:5",
    },
    {
        "transcription": "اهدنا الصراط المستقيم",
        "description": "Fatiha 1:6",
    },
    {
        "transcription": "الحمد لله رب العالمين الرحمن الرحيم مالك يوم الدين",
        "description": "Fatiha 1:2-4 (uzun, multi-ayah)",
    },

    # Fatiha preferred_range testi
    {
        "transcription": "الحمد لله رب العالمين",
        "preferred_range": [0, 30],
        "description": "Fatiha 1:2 + preferred_range Fatiha (0-30)",
    },

    # ============ Kısa sureler ============
    # 112 - İhlas
    {
        "transcription": "قل هو الله احد",
        "description": "Ihlas 112:1",
    },
    {
        "transcription": "قل هو الله احد الله الصمد",
        "description": "Ihlas 112:1-2",
    },
    {
        "transcription": "لم يلد ولم يولد",
        "description": "Ihlas 112:3",
    },
    {
        "transcription": "ولم يكن له كفوا احد",
        "description": "Ihlas 112:4",
    },
    {
        "transcription": "قل هو الله احد الله الصمد لم يلد ولم يولد ولم يكن له كفوا احد",
        "description": "Ihlas tam (112:1-4)",
    },

    # 113 - Felak
    {
        "transcription": "قل اعوذ برب الفلق",
        "description": "Felak 113:1",
    },
    {
        "transcription": "من شر ما خلق",
        "description": "Felak 113:2",
    },

    # 114 - Nas
    {
        "transcription": "قل اعوذ برب الناس",
        "description": "Nas 114:1",
    },
    {
        "transcription": "ملك الناس",
        "description": "Nas 114:2",
    },
    {
        "transcription": "اله الناس",
        "description": "Nas 114:3",
    },
    {
        "transcription": "من شر الوسواس الخناس",
        "description": "Nas 114:4",
    },

    # ============ Alak (96) ============
    {
        "transcription": "اقرا باسم ربك الذي خلق",
        "description": "Alak 96:1",
    },
    {
        "transcription": "اقرا باسم ربك الذي خلق خلق الانسان من علق",
        "description": "Alak 96:1-2",
    },

    # ============ Rahman (55) ============
    {
        "transcription": "الرحمن علم القران",
        "description": "Rahman 55:1-2",
    },
    {
        "transcription": "خلق الانسان علمه البيان",
        "description": "Rahman 55:3-4",
    },

    # ============ Yasin (36) ============
    {
        "transcription": "يس والقران الحكيم",
        "description": "Yasin 36:1-2",
    },

    # ============ Bakara baslangici ============
    {
        "transcription": "الم ذلك الكتاب لا ريب فيه",
        "description": "Bakara 2:1-2",
    },

    # ============ Tevbe (mock data icin) ============
    {
        "transcription": "براءة من الله ورسوله الى الذين عاهدتم من المشركين",
        "description": "Tevbe 9:1",
    },

    # ============ Bozulmus / kismen yanlis transkripsiyonlar ============
    {
        "transcription": "الحمد لله",
        "description": "Fatiha 1:2 KISA - kelime sayisi 2 (cold min 3?)",
    },
    {
        "transcription": "احمد لله رب عالمين",
        "description": "Fatiha 1:2 BOZUK - eksik karakterler",
    },
    {
        "transcription": "قل هو الله",
        "description": "Ihlas eksik - 3 kelime",
    },

    # ============ Cok kisa (1 kelime) ============
    {
        "transcription": "الله",
        "description": "tek kelime - aday cok ama secim guc",
    },
    {
        "transcription": "محمد",
        "description": "tek kelime nadir",
    },

    # ============ Olmayan/uydurma metin ============
    {
        "transcription": "تست تست تست",
        "description": "uydurma - eslesme dusuk olmali",
    },
    {
        "transcription": "abcdefg xyz",
        "description": "yabanci karakter - eslesme yok beklenir",
    },

    # ============ Preferred range testleri ============
    {
        "transcription": "قل هو الله احد",
        "preferred_range": [0, 30],
        "description": "Ihlas Fatiha range icinde aranıyor - eslesme yok/dusuk",
    },
    {
        "transcription": "اقرا باسم ربك",
        "preferred_range": [77000, 77878],
        "description": "Alak son range'da - bulunmali",
    },

    # ============ Tekrar eden kelimeler ============
    {
        "transcription": "الله الله الله الله",
        "description": "tekrar - dusuk skor beklenir (tekrar penalty olmasa da fuzzy dusuk)",
    },

    # ============ Uzun/orta transkripsiyon ============
    {
        "transcription": "الحمد لله رب العالمين الرحمن الرحيم مالك يوم الدين اياك نعبد واياك نستعين اهدنا الصراط المستقيم",
        "description": "Fatiha tam (1:2-6)",
    },

    # ============ Surah end testleri ============
    {
        "transcription": "ولم يكن له كفوا احد",
        "description": "Ihlas son ayet (112:4)",
    },

    # ============ Hatirlanmasi gereken: Fatiha BIRINCI ayet (besmele) ============
    {
        "transcription": "بسم الله الرحمن الرحيم الحمد",
        "description": "besmele + tek kelime - besmele atlanip 'الحمد' kalir",
    },
]

def main():
    print("Kuran corpus yukleniyor...")
    corpus = QuranCorpus.load()
    print(f"  {len(corpus.words)} kelime\n")

    fixtures = []

    print(f"{'#':>3} {'score':>6} {'span':>15}  case")
    print("-" * 80)

    for idx, case in enumerate(test_cases):
        transcription = case["transcription"]
        preferred_range = case.get("preferred_range")
        pref_tuple = tuple(preferred_range) if preferred_range else None

        match = align_transcription(
            transcription, corpus,
            preferred_range=pref_tuple,
        )

        if match:
            # Eslesen kelime listesi (debug)
            words_in_match = []
            for i in range(match.start_word_idx, match.end_word_idx + 1):
                w = corpus.words[i]
                words_in_match.append(f"{w.surah}:{w.ayah}.{w.word_index}")
            first_w = corpus.words[match.start_word_idx]
            last_w = corpus.words[match.end_word_idx]

            fixtures.append({
                "transcription": transcription,
                "preferred_range": preferred_range,
                "expected_match": {
                    "start_word_idx": match.start_word_idx,
                    "end_word_idx": match.end_word_idx,
                    "score": round(match.score, 4),
                    "first_surah": first_w.surah,
                    "first_ayah": first_w.ayah,
                    "last_surah": last_w.surah,
                    "last_ayah": last_w.ayah,
                },
                "description": case["description"],
            })

            score_str = f"{match.score:.1f}"
            span_str = f"{match.start_word_idx}-{match.end_word_idx}"
            preview = transcription[:40] + ("..." if len(transcription) > 40 else "")
            print(f"{idx:>3} {score_str:>6} {span_str:>15}  {preview}")
        else:
            fixtures.append({
                "transcription": transcription,
                "preferred_range": preferred_range,
                "expected_match": None,
                "description": case["description"],
            })
            preview = transcription[:40] + ("..." if len(transcription) > 40 else "")
            print(f"{idx:>3} {'NONE':>6} {'-':>15}  {preview}")

    # JSON'a yaz
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump({
            "version": 1,
            "description": "Aligner test fixture — Python aligner.py reference outputs",
            "cases": fixtures,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*80}")
    print(f"Toplam: {len(fixtures)} case")
    print(f"Eslesen: {sum(1 for f in fixtures if f['expected_match'])}")
    print(f"Eslesmeyen: {sum(1 for f in fixtures if not f['expected_match'])}")
    print(f"\nKaydedildi: {OUTPUT}")
    print(f"Boyut: {OUTPUT.stat().st_size / 1024:.1f} KB")
    print(f"\nKotlin port'u bu dosyaya karsi test edilecek.")
    print(f"Asset olarak APK'ya gomulecek (android-assets-staged/asr/).")

if __name__ == "__main__":
    main()
