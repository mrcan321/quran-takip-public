"""
Türkçe meal verisini indirir ve cache'ler (api.alquran.cloud).

Baskı: Ali Bulaç (tr.bulac) — her ayetin kendi meali var (Tarteel gibi).
Eskiden tr.diyanet (Diyanet İşleri) kullanılıyordu: ardışık ayetleri tek cümlede birleştirip AYNI metni
her ayete tekrar koyuyor — 841 ayette önceki ayetin mealiyle birebir aynı (örn. Nasr 110:1-3 üç ayette
tek meal). scripts/compare_meals.py ile ölçüldü (CI, eval.yml meal_compare): ardışık tekrar
diyanet 841, yildirim 606, yazir 57, vakfi 10; ates / bulac / golpinarli / ozturk / yuksel 0.

Baskıyı değiştirmek için sadece MEAL_EDITION — cache dosya adı ondan türer; build_quran_assets.py ve
server'lar MEAL_CACHE'i buradan alır. Bu dosya değişince CI'daki Kuran verisi cache anahtarı da değişir.
"""
import json
import sys
import urllib.request
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "quran-align"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MEAL_EDITION = "tr.bulac"
MEAL_URL = f"https://api.alquran.cloud/v1/quran/{MEAL_EDITION}"
MEAL_CACHE = CACHE_DIR / f"meal-{MEAL_EDITION.replace('.', '-')}.json"


def consecutive_duplicates(meals: dict) -> list:
    """Aynı suredeki bir önceki ayetle birebir aynı (boş olmayan) meal — birleştirilmiş ayet işareti."""
    dups = []
    for key, text in meals.items():
        s, a = (int(x) for x in key.split(":"))
        if a > 1 and text and meals.get(f"{s}:{a - 1}") == text:
            dups.append(key)
    return sorted(dups, key=lambda k: tuple(int(x) for x in k.split(":")))


def download_meal():
    if MEAL_CACHE.exists():
        print(f"Meal zaten cache'de: {MEAL_CACHE}")
        return load_meal()

    print(f"Meal indiriliyor: {MEAL_URL}")
    with urllib.request.urlopen(MEAL_URL) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    # Basitleştirilmiş format: {"1:1": "meal...", "1:2": "...", ...}
    meals = {}
    for surah in data["data"]["surahs"]:
        s_num = surah["number"]
        for ayah in surah["ayahs"]:
            a_num = ayah["numberInSurah"]
            meals[f"{s_num}:{a_num}"] = (ayah["text"] or "").strip()

    with open(MEAL_CACHE, "w", encoding="utf-8") as f:
        json.dump(meals, f, ensure_ascii=False, indent=2)

    print(f"✓ {len(meals)} ayet mealli kaydedildi: {MEAL_CACHE}")
    return meals


def load_meal() -> dict:
    with open(MEAL_CACHE, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    meals = download_meal()
    empty = sum(1 for t in meals.values() if not t)
    dups = consecutive_duplicates(meals)
    print(f"\n{MEAL_EDITION}: {len(meals)} ayet, bos {empty}, ardisik tekrar {len(dups)} {dups[:6]}")
    # Hızlı doğrulama — birkaç ayet göster
    print("\n--- Örnek mealler ---")
    for key in ["1:1", "1:7", "110:1", "110:2", "110:3", "112:1", "2:255"]:
        if key in meals:
            print(f"\n{key}: {meals[key]}")
    sys.exit(0)
