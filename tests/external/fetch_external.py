#!/usr/bin/env python3
"""Dis kaynaklardan gercek kayitlar (CI'da indirilir, repoya konmaz): Harem teravihleri (cami akustigi, canli okuma),
Turk kari, ezan koleksiyonu (negatif / ezan-kamet sinyali). archive.org kayitlarinin cogunda lisans belirtilmemis →
sadece test icin, ses dosyasi saklanmaz; transkript (TRJSON) + manifest tests/trjson/external/ altina eklenir.

Dosya adindaki 3 haneli sure numarasi beklenen sure olur (001.mp3 → 1). Ezan kayitlari beklenen None (Kuran degil).
Kume (--set): v1 = Harem teravihi kisa sureler + Collak + ezan (tests/trjson/external/external-v1.*), v2 = sure ortasindan
baslayan teravih parcalari (Maher el-Muaykili 1427, ayet aralikli), uzun teravih okumalari (Hani Rifai), Medine 1436 orta
uzunlukta sureler — uzun dosyalar max_sec ile kirpilir.

  python tests/external/fetch_external.py --out ext --max-minutes 70 --set v2
"""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import soundfile as sf

UA = {"User-Agent": "tilavet-takip-test/1.0"}
SR = 16000
SOURCES_V1 = [
    # Mekke Harem teravihi 1430 (Sudeys / Sureym), sure sure ayrilmis — Harem yankisi, canli okuma
    {"item": "Makkah_Tarawih_1430", "tag": "mekke1430", "surahs": list(range(105, 115)) + [93, 94, 97, 99, 101, 103]},
    # Halid el-Celil teravihi 1435
    {"item": "taraweeh-khalid-jaleel-1435", "tag": "celil1435", "surahs": list(range(105, 115)) + [87, 91, 95, 100]},
    # Fatih Collak (Turk kari)
    {"item": "rabieaaa2015_yahoo_002132432", "tag": "collak", "surahs": list(range(105, 115))},
    # Ezan koleksiyonu: Kuran degil → kilit olmamali, ezan/kamet sinyali beklenir
    {"item": "90---azan---90---azan--many----sound----mp3---alazan", "tag": "ezan", "first_n": 4, "expected": None},
]
SOURCES_V2 = [
    # Maher el-Muaykili teravih 1427: ayet aralikli parcalar ("051-Adh-dhariyat24-60") — sure ortasindan ilk kilit
    {"item": "Maher1427_3", "tag": "maher1427", "first_n": 12, "max_sec": 300},
    # Hani Rifai "Tarawih Recitation": uzun teravih okumalari ("007_ala3raf") — ilk 7 dk
    {"item": "Hani_Rifai", "tag": "rifai", "first_n": 6, "max_sec": 420},
    # Medine (Mescid-i Nebevi) teravihi 1436: orta uzunlukta sureler — ilk 4 dk
    {"item": "5680680804060", "tag": "medine1436", "surahs": list(range(67, 79)), "max_sec": 240},
]
SOURCE_SETS = {"v1": SOURCES_V1, "v2": SOURCES_V2}


def get(url, tries=3, binary=False):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
                return data if binary else json.loads(data.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                print(f"HATA {url}: {e}", flush=True)
                return None
            time.sleep(3 * (i + 1))


def to_wav(src, dst, max_sec=None):
    """MP3 → 16 kHz mono PCM16 (max_sec verilirse bastan o kadar). soundfile (libsndfile >= 1.1 MP3 okur) + soxr;
    runner'da ffmpeg olmayabilir."""
    try:
        a, sr = sf.read(str(src), dtype="float32", always_2d=True,
                        frames=int(max_sec * sf.info(str(src)).samplerate) if max_sec else -1)
        a = a.mean(axis=1)
        if sr != SR:
            import soxr
            a = soxr.resample(a, sr, SR, quality="HQ")
    except Exception:  # noqa: BLE001 — son care ffmpeg
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", str(SR), "-sample_fmt", "s16",
                        *(["-t", str(max_sec)] if max_sec else []), str(dst)], check=True)
        return
    sf.write(str(dst), a, SR, subtype="PCM_16")


def length_sec(f):
    ln = f.get("length")
    try:
        if ln and ":" in str(ln):
            return sum(float(p) * 60 ** i for i, p in enumerate(reversed(str(ln).split(":"))))
        return float(ln) if ln else None
    except ValueError:
        return None


def pick_files(src, meta):
    files = [f for f in meta.get("files", []) if str(f.get("name", "")).lower().endswith(".mp3")
             and "_64kb" not in f["name"] and "/" not in f["name"]]
    files.sort(key=lambda f: f["name"])
    def surah_of(f):
        m = re.match(r"^\D*(\d{3})", f["name"])
        return int(m.group(1)) if m and 1 <= int(m.group(1)) <= 114 else None

    if "first_n" in src:
        # beklenen: kaynakta verildiyse o (ezan: None), yoksa dosya adindaki sure numarasi
        picks = [(f, src["expected"] if "expected" in src else surah_of(f)) for f in files]
        return [(f, e) for f, e in picks if "expected" in src or e is not None][:src["first_n"]]
    return [(f, surah_of(f)) for f in files if surah_of(f) in src["surahs"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-minutes", type=float, default=70.0, help="toplam ses siniri (ASR suresi)")
    ap.add_argument("--set", default="v2", choices=sorted(SOURCE_SETS), help="kaynak kumesi")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    tmp = args.out / "_mp3"
    tmp.mkdir(exist_ok=True)
    manifest = {"set": args.set, "files": {}}
    total = 0.0
    budget = args.max_minutes * 60
    plan = []
    for src in SOURCE_SETS[args.set]:
        meta = get(f"https://archive.org/metadata/{urllib.parse.quote(src['item'])}")
        if not meta:
            continue
        picks = pick_files(src, meta)
        print(f"{src['item']}: {len(picks)} dosya secildi", flush=True)
        plan.append((src, picks))
    # Kaynaklar arasinda sirayla (round-robin) — butce bitince her kaynaktan ornek kalsin
    queue = []
    longest = max((len(p) for _, p in plan), default=0)
    for i in range(longest):
        for src, picks in plan:
            if i < len(picks):
                queue.append((src, *picks[i]))
    for src, f, expected in queue:
        dur = length_sec(f) or 0.0
        if src.get("max_sec"):
            dur = min(dur, src["max_sec"]) if dur else src["max_sec"]
        if total + dur > budget:
            continue
        name = f"ext_{src['tag']}_{Path(f['name']).stem}"
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", name) + ".wav"
        url = f"https://archive.org/download/{urllib.parse.quote(src['item'])}/{urllib.parse.quote(f['name'])}"
        data = get(url, binary=True)
        if not data:
            continue
        mp3 = tmp / (name + ".mp3")
        mp3.write_bytes(data)
        try:
            to_wav(mp3, args.out / name, src.get("max_sec"))
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"ATLANDI {name}: {e}", flush=True)
            continue
        mp3.unlink()
        info = sf.info(str(args.out / name))
        total += info.duration
        manifest["files"][name] = {"expected": expected, "source": f"archive.org/{src['item']}/{f['name']}",
                                   "license": "belirtilmemis (sadece test)", "duration": round(info.duration, 1)}
        if expected is None:
            manifest["files"][name]["kind"] = src["tag"]
        if src.get("max_sec") and (length_sec(f) or 0) > src["max_sec"]:
            manifest["files"][name]["trimmed_from"] = round(length_sec(f), 1)
        print(f"{name}: {info.duration:.0f} sn, beklenen {expected}", flush=True)
    if not any(tmp.iterdir()):
        tmp.rmdir()
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(manifest['files'])} kayit, {total / 60:.0f} dk → {args.out}")
    print("MANIFEST " + json.dumps(manifest, ensure_ascii=False))
    return 0 if manifest["files"] else 1


if __name__ == "__main__":
    sys.exit(main())
