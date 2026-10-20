#!/usr/bin/env python3
"""
Turkce meal baskilarini karsilastirir (CI'da calisir — api.alquran.cloud yerel ortamdan erisilemiyor).

Sorun: tr.diyanet (Diyanet Isleri) bazi ardisik ayetleri tek cumlede birlestirip AYNI metni her ayete
tekrar koyuyor (orn. Nasr 110:1-3 uc ayette birebir ayni meal). Tarteel gibi her ayetin kendi meali
olsun diye hangi baskinin ayet ayet ayrik oldugunu olcer:
  - ayet sayisi / bos meal
  - ardisik tekrar: ayni suredeki bir onceki ayetle birebir ayni meal
  - ornek ayetler (Nasr 110:1-3, Kevser 108:1-3, Fatiha 1:1-3)

Cikti: log + (varsa) --summary markdown dosyasi (GITHUB_STEP_SUMMARY).
"""
import argparse
import json
import sys
import time
import urllib.request

EDITIONS = [
    "tr.diyanet", "tr.vakfi", "tr.yazir", "tr.ates", "tr.bulac",
    "tr.golpinarli", "tr.ozturk", "tr.yildirim", "tr.yuksel",
]
SAMPLES = ["110:1", "110:2", "110:3", "108:1", "108:2", "108:3", "1:1", "1:2", "1:3"]


def fetch(edition):
    url = f"https://api.alquran.cloud/v1/quran/{edition}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as e:  # ag hatasi → tekrar dene
            if attempt == 3:
                raise
            print(f"  {edition}: {e}, tekrar...", flush=True)
            time.sleep(2 ** attempt)
    meals = {}
    name = data["data"].get("name") or data["data"].get("edition", {}).get("name", edition)
    for surah in data["data"]["surahs"]:
        for ayah in surah["ayahs"]:
            meals[(surah["number"], ayah["numberInSurah"])] = (ayah["text"] or "").strip()
    return name, meals


def analyze(meals):
    empty = sum(1 for t in meals.values() if not t)
    dup = 0
    dup_examples = []
    for (s, a), t in sorted(meals.items()):
        prev = meals.get((s, a - 1))
        if a > 1 and t and prev == t:
            dup += 1
            if len(dup_examples) < 6:
                dup_examples.append(f"{s}:{a}")
    return empty, dup, dup_examples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", help="Markdown ozet dosyasi")
    args = ap.parse_args()

    rows, samples = [], {}
    for ed in EDITIONS:
        try:
            name, meals = fetch(ed)
        except Exception as e:
            print(f"{ed}: indirilemedi: {e}", flush=True)
            rows.append(f"| {ed} | - | indirilemedi | | | |")
            continue
        empty, dup, ex = analyze(meals)
        rows.append(f"| {ed} | {name} | {len(meals)} | {empty} | **{dup}** | {', '.join(ex)} |")
        samples[ed] = {k: meals.get(tuple(int(x) for x in k.split(":")), "") for k in SAMPLES}
        print(f"{ed:14s} {name:30s} ayet={len(meals)} bos={empty} ardisik_tekrar={dup} ornek={ex}", flush=True)

    md = ["## Turkce meal karsilastirmasi (api.alquran.cloud)", "",
          "Ardisik tekrar = ayni suredeki bir onceki ayetle birebir ayni meal (birlestirilmis ayetler).", "",
          "| baski | ad | ayet | bos | ardisik tekrar | ornek tekrarlar |", "|---|---|---|---|---|---|"] + rows
    for ed, smp in samples.items():
        md += ["", f"### {ed}", ""]
        for k, t in smp.items():
            md.append(f"- **{k}** {t}")
    text = "\n".join(md) + "\n"
    print("\n" + text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
