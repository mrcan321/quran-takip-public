#!/usr/bin/env python3
"""
Secilebilir Turkce mealler → <assets>/asr/meals/<id>.bin + meals/index.tsv (Ayarlar → MEAL).

Kullanici (21.10): "baska meal seceneklerini de sectirmek istiyorum ayarlar kismindan" — Diyanet cesitleri, Erhan Aktas ve
8-10 meal daha. Namazda internet yok → hepsi APK'da. Varsayilan Ali Bulac: build_quran_assets.py'nin meal.bin'i (download_meal.py,
alquran.cloud tr.bulac) — bu betik ona dokunmaz, index.tsv'de "meal.bin" dosyasiyla gecer.

Kaynaklar:
  fawaz      fawazahmed0/quran-api (GitHub; Tanzil + qurandatabase.org) — editions/<ad>.min.json
  acikkuran  Acik Kuran API (api.acikkuran.com, acik-kuran/acikkuran-api; kod CC BY-NC-SA 4.0) — /surah/{n}?author={id}
Meal metinlerinin hakki yazarlarinda / yayincilarinda; kisisel, ticari olmayan kullanim.

Kurallar:
  - ayet kumesi meal.bin'le (Bulac) birebir ayni (6236), bos meal yok
  - birlesik ayet (ayni suredeki onceki ayetle birebir ayni meal — ayetler tek cumlede cevrilmis) <= MAX_MERGED; kullanici:
    "birlesik baskilari alma" (Hasan Basri Cantay 159, Diyanet Isleri eski 843 → alinmadi)
  - indirilemeyen ya da kurala takilan baski atlanir (uyari), Bulac yoksa durur
Bin bicimi meal.bin ile ayni (v1, MealLoader degismeden okur); sure tablosu meal.bin'den byte byte kopyalanir.

Onbellek: ~/.cache/tilavet-meals/<id>.json (CI: actions/cache, anahtar bu dosyanin hash'i). Yerelde fawaz kaynagi erisilebilir,
alquran / acikkuran kapali → o baskilar atlanir.

Kullanim: python scripts/build_meals.py [--summary <md>] [--only id,id]
"""
import argparse
import json
import os
import re
import struct
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_ROOT = Path(os.environ.get("TILAVET_ASSETS_DIR", REPO_ROOT / "android-assets-staged"))
ASR_DIR = ASSETS_ROOT / "asr"
MEAL_BIN = ASR_DIR / "meal.bin"          # build_quran_assets.py (varsayilan meal + sure adlari)
OUT_DIR = ASR_DIR / "meals"
CACHE_DIR = Path(os.environ.get("TILAVET_MEALS_CACHE", Path.home() / ".cache" / "tilavet-meals"))

# Kullanicinin listesi (21.10); sira = Ayarlar'daki sira. Ilki varsayilan (meal.bin).
# Erhan Aktas (Acik Kuran yazar 105), Mustafa Islamoglu (38), Mehmet Okuyan (107) da istendi ama sadece Acik Kuran'da var ve
# api.acikkuran.com kapanmis (21.10, GitHub sunucularinda da "Name or service not known"); kullanici: "simdilik 7 meal yeter".
# Kaynak geri gelirse: dict(id="erhanaktas", name="Erhan Aktaş", desc="Kerim Kur'an", src=("acikkuran", 105)) gibi satirlar.
MEALS = [
    dict(id="bulac", name="Ali Bulaç", desc="Kur'an-ı Kerim ve Türkçe Anlamı", src="meal.bin"),
    dict(id="diyanetvakfi", name="Diyanet Vakfı", desc="Türkiye Diyanet Vakfı meali", src=("fawaz", "tur-diyanetvakfi")),
    dict(id="elmalilisade", name="Elmalılı Hamdi Yazır", desc="Sadeleştirilmiş meal", src=("fawaz", "tur-elmallsadelesti")),
    dict(id="ates", name="Süleyman Ateş", desc="Kur'an-ı Kerim ve Yüce Meali", src=("fawaz", "tur-suleymanates")),
    dict(id="esed", name="Muhammed Esed", desc="Kur'an Mesajı", src=("fawaz", "tur-muhammedesed")),
    dict(id="ozturk", name="Yaşar Nuri Öztürk", desc="Kur'an-ı Kerim Meali", src=("fawaz", "tur-yasarnuriozturk")),
    dict(id="golpinarli", name="Abdulbaki Gölpınarlı", desc="Kur'an-ı Kerim ve Meali", src=("fawaz", "tur-abdulbakigolpin")),
]
DEFAULT_ID = "bulac"
MAX_MERGED = 100

FAWAZ_URL = "https://raw.githubusercontent.com/fawazahmed0/quran-api/1/editions/{name}.min.json"
ACIKKURAN_URL = "https://api.acikkuran.com/surah/{surah}?author={author}"
# Dipnot isareti: "[1]", "[12]" (Acik Kuran dipnotlari ayri alanda; metindeki isaret silinir, dipnot alinmaz)
FOOTNOTE_RE = re.compile(r"\s*\[\d{1,3}\]")
# Rapor: temizlikten sonra kalan isaret benzeri karakterler (desen eksikse buradan gorulur)
MARK_RE = re.compile(r"\[\d|\*|\{|<[a-z/]")
SAMPLES = ["1:2", "108:1", "110:1", "110:2", "110:3", "2:255"]


def get_json(url, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tilavet-takip/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)


def read_meal_bin(path):
    """meal.bin → ({"s:a": metin}, sure tablosu bayt dizisi, sure sayisi)."""
    b = path.read_bytes()
    assert b[:4] == b"MEAL", f"{path}: MEAL degil"
    version, count, surah_count = struct.unpack("<III", b[4:16])
    assert version == 1, f"{path}: surum {version}"
    off, meals = 16, {}
    for _ in range(count):
        s, a, n = struct.unpack("<HHH", b[off:off + 6])
        off += 6
        meals[f"{s}:{a}"] = b[off:off + n].decode("utf-8")
        off += n
    return meals, b[off:], surah_count


def write_meal_bin(path, meals, keys, surah_bytes, surah_count):
    out = bytearray(b"MEAL")
    out += struct.pack("<III", 1, len(keys), surah_count)
    for k in keys:
        s, a = (int(x) for x in k.split(":"))
        t = meals[k].encode("utf-8")
        if len(t) > 65535:
            raise ValueError(f"meal cok uzun: {k} ({len(t)} bayt)")
        out += struct.pack("<HHH", s, a, len(t)) + t
    out += surah_bytes
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(out)
    tmp.replace(path)
    return len(out)


def clean(text):
    t = (text or "").replace("´", "'").replace("’", "'").replace(" ", " ")
    t = FOOTNOTE_RE.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


def fetch_fawaz(name):
    d = get_json(FAWAZ_URL.format(name=name))
    return {f"{v['chapter']}:{v['verse']}": v.get("text") or "" for v in d["quran"]}


def fetch_acikkuran(author, keys_by_surah):
    meals = {}
    for s in sorted(keys_by_surah):
        d = get_json(ACIKKURAN_URL.format(surah=s, author=author))
        data = d.get("data", d)
        for v in data.get("verses") or []:
            no = v.get("verse_number", v.get("verse_no"))
            tr = v.get("translation") or {}
            if isinstance(tr, list):   # bazi uclarda liste
                tr = tr[0] if tr else {}
            if no is None or int(no) < 1:
                continue   # besmele / 0. ayet
            meals[f"{s}:{int(no)}"] = tr.get("text") or ""
        time.sleep(0.15)
    return meals


def fetch(entry, keys_by_surah):
    cache = CACHE_DIR / f"{entry['id']}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8")), "onbellek"
    kind, ref = entry["src"]
    if kind == "fawaz":
        raw = fetch_fawaz(ref)
    elif kind == "acikkuran":
        raw = fetch_acikkuran(ref, keys_by_surah)
    else:
        raise ValueError(f"bilinmeyen kaynak {kind}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return raw, kind


def merged(meals, keys):
    """Ayni suredeki onceki ayetle birebir ayni (bos olmayan) meal sayisi + ilk ornekler."""
    out = []
    for k in keys:
        s, a = (int(x) for x in k.split(":"))
        if a > 1 and meals[k] and meals.get(f"{s}:{a - 1}") == meals[k]:
            out.append(k)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY"), help="Markdown ozet (CI: run ozeti)")
    ap.add_argument("--only", help="sadece bu id'ler (virgullu, deneme icin; index.tsv yazilmaz)")
    args = ap.parse_args()

    if not MEAL_BIN.exists():
        print(f"HATA: {MEAL_BIN} yok — once scripts/build_quran_assets.py", file=sys.stderr)
        return 1
    base, surah_bytes, surah_count = read_meal_bin(MEAL_BIN)
    keys = sorted(base, key=lambda k: tuple(int(x) for x in k.split(":")))
    keys_by_surah = {}
    for k in keys:
        keys_by_surah.setdefault(int(k.split(":")[0]), []).append(k)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    only = set(args.only.split(",")) if args.only else None

    index, rows, samples, warnings = [], [], {}, []
    for e in MEALS:
        if only and e["id"] not in only and e["id"] != DEFAULT_ID:
            continue
        if e["src"] == "meal.bin":
            meals, source = base, "meal.bin"
        else:
            try:
                raw, source = fetch(e, keys_by_surah)
            except Exception as ex:
                warnings.append(f"{e['id']} ({e['name']}): indirilemedi — {type(ex).__name__}: {ex}")
                rows.append(f"| {e['id']} | {e['name']} | {e['src'][0]} | - | - | - | - | **atlandi: indirilemedi** |")
                continue
            meals = {k: clean(v) for k, v in raw.items()}
        missing = [k for k in keys if not meals.get(k)]
        extra = sorted(set(meals) - set(base))
        mg = merged(meals, keys)
        marks = sum(1 for k in keys if MARK_RE.search(meals.get(k, "")))
        lens = sorted(len(meals.get(k, "")) for k in keys)
        status = "tamam"
        if e["id"] != DEFAULT_ID:
            if missing or extra:
                status = f"atlandi: {len(missing)} eksik/bos, {len(extra)} fazla ayet ({(missing + extra)[:4]})"
            elif len(mg) > MAX_MERGED:
                status = f"atlandi: {len(mg)} birlesik ayet > {MAX_MERGED}"
        rows.append(f"| {e['id']} | {e['name']} | {source} | {len(keys) - len(missing)} | {len(mg)} {mg[:3]} | {marks} | "
                    f"{lens[len(lens) // 2]} / {lens[-1]} | {status} |")
        print(f"{e['id']:13s} {e['name']:22s} kaynak={source:9s} ayet={len(keys) - len(missing)} birlesik={len(mg)} "
              f"isaret={marks} uzunluk={lens[len(lens) // 2]}/{lens[-1]} → {status}", flush=True)
        if status != "tamam":
            warnings.append(f"{e['id']} ({e['name']}): {status}")
            continue
        if e["id"] == DEFAULT_ID:
            fname = "meal.bin"
        else:
            fname = f"meals/{e['id']}.bin"
            size = write_meal_bin(ASR_DIR / fname, meals, keys, surah_bytes, surah_count)
            print(f"  yazildi: {ASR_DIR / fname} ({size / 1024:.0f} KB)", flush=True)
        index.append(dict(id=e["id"], name=e["name"], desc=e["desc"], file=fname, merged=len(mg)))
        samples[e["id"]] = {k: meals.get(k, "") for k in SAMPLES}

    if not any(x["id"] == DEFAULT_ID for x in index):
        print("HATA: varsayilan meal (meal.bin) yok", file=sys.stderr)
        return 1
    if not only:
        # eski calismalardan kalan, listede olmayan dosyalar APK'ya girmesin
        keep = {x["file"] for x in index}
        for p in OUT_DIR.glob("*.bin"):
            if f"meals/{p.name}" not in keep:
                p.unlink()
        # index.tsv (data/MealCatalog.kt, tests/g2): id, dosya (asr/'a gore), birlesik ayet, ad, aciklama; sira = Ayarlar'daki sira
        rows_tsv = ["# id\tfile\tmerged\tname\tdesc"] + [
            "\t".join([x["id"], x["file"], str(x["merged"]), x["name"], x["desc"]]) for x in index]
        (OUT_DIR / "index.tsv").write_text("\n".join(rows_tsv) + "\n", encoding="utf-8")
        print(f"index: {OUT_DIR / 'index.tsv'} ({len(index)} meal)", flush=True)

    md = ["## Mealler (Ayarlar → MEAL)", "",
          f"{len(index)} / {len(MEALS)} meal APK'ya giriyor. Birlesik = ayni suredeki onceki ayetle birebir ayni meal "
          f"(en fazla {MAX_MERGED}); isaret = temizlikten sonra kalan dipnot / isaret benzeri karakterli ayet.", "",
          "| id | meal | kaynak | ayet | birlesik | isaret | uzunluk medyan / en cok | durum |",
          "|---|---|---|---|---|---|---|---|"] + rows
    if warnings:
        md += ["", "**Uyarilar:**", ""] + [f"- {w}" for w in warnings]
    for mid, smp in samples.items():
        md += ["", f"<details><summary>{mid}</summary>", ""] + [f"- **{k}** {t}" for k, t in smp.items()] + ["", "</details>"]
    text = "\n".join(md) + "\n"
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    for w in warnings:
        print(f"::warning::meal {w}" if os.environ.get("GITHUB_ACTIONS") else f"UYARI: {w}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
