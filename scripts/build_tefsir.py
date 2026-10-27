#!/usr/bin/env python3
"""
Turkce kisa tefsir → <assets>/asr/tefsir.bin (namaz raporunun sonunda "isteyenler icin tefsir").

Kullanici (27.10): "anaekranda bir buton ile son 3 kayda ait namazda okunan ayetleri guzel bir rapor html sunsun; ayetin
arapcasi, turkce meali olsun; rapor bitiminde ise isteyenler icin tefsir de olsun". Namazda internet yok → APK'da.

Kaynak: El-Muhtasar fi Tefsiri'l-Kur'ani'l-Kerim (Tefsir Arastirmalari Merkezi; QuranEnc "Turkish Mokhtasar") —
spa5k/tafsir_api (GitHub) tafsir/turkish-mokhtasar/<sure>.json ([{surah, ayah, text}]). Ayet basina kisa aciklama (cogu
150-250 karakter). Metnin hakki yayincisinda; kisisel, ticari olmayan kullanim, kaynak raporda belirtilir.

Bin bicimi meal.bin ile ayni (v1, MealLoader degismeden okur; sure tablosu meal.bin'den). Ayet kumesi meal.bin'le birebir
(6236), bos ayet yok — yoksa durur. Onbellek: ~/.cache/tilavet-meals/tefsir-<id>.json (CI: meal onbellegiyle ayni).

Kullanim: python scripts/build_tefsir.py [--summary <md>]
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_meals import ASR_DIR, CACHE_DIR, MEAL_BIN, clean, get_json, read_meal_bin, write_meal_bin  # noqa: E402

TEFSIR_ID = "turkish-mokhtasar"
TEFSIR_NAME = "El-Muhtasar fi Tefsîri'l-Kur'ân (Tefsir Araştırmaları Merkezi)"
URL = "https://raw.githubusercontent.com/spa5k/tafsir_api/main/tafsir/{id}/{surah}.json"
OUT = ASR_DIR / "tefsir.bin"
TAG_RE = re.compile(r"<[^>]+>")


def fetch(keys_by_surah):
    cache = CACHE_DIR / f"tefsir-{TEFSIR_ID}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8")), "onbellek"
    out = {}
    for surah in sorted(keys_by_surah):
        for v in get_json(URL.format(id=TEFSIR_ID, surah=surah)):
            out[f"{int(v['surah'])}:{int(v['ayah'])}"] = v.get("text") or ""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out, "indirildi"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY"), help="Markdown ozet (CI: run ozeti)")
    args = ap.parse_args()
    if not MEAL_BIN.exists():
        print(f"HATA: {MEAL_BIN} yok — once scripts/build_quran_assets.py", file=sys.stderr)
        return 1
    base, surah_bytes, surah_count = read_meal_bin(MEAL_BIN)
    keys = sorted(base, key=lambda k: tuple(int(x) for x in k.split(":")))
    keys_by_surah = {}
    for k in keys:
        keys_by_surah.setdefault(int(k.split(":")[0]), []).append(k)
    raw, source = fetch(keys_by_surah)
    tefsir = {k: clean(TAG_RE.sub(" ", v)) for k, v in raw.items()}
    missing = [k for k in keys if not tefsir.get(k)]
    if missing:
        print(f"HATA: tefsir {len(missing)} ayette eksik / bos: {missing[:8]}", file=sys.stderr)
        return 1
    size = write_meal_bin(OUT, tefsir, keys, surah_bytes, surah_count)
    lens = sorted(len(tefsir[k]) for k in keys)
    line = (f"tefsir: {TEFSIR_NAME} ({source}) → {OUT} ({size / 1024:.0f} KB), {len(keys)} ayet, uzunluk medyan "
            f"{lens[len(lens) // 2]} / en cok {lens[-1]}")
    print(line, flush=True)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(f"## Tefsir (namaz raporu)\n\n{line}\n\n- **1:2** {tefsir['1:2']}\n- **108:2** {tefsir['108:2']}\n\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
