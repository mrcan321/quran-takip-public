#!/usr/bin/env python3
"""Ses verisi kaynak taramasi (CI'da calisir — yerel oturumun ag erisimi kapali).

Hugging Face veri setleri (Kuran tilaveti / ASR) ve archive.org ses kayitlari (teravih, namaz, hatim) aranir; her biri
icin lisans, boyut, indirme sayisi, dosya / sure bilgisi yazilir. Hicbir sey indirilmez (sadece meta veri).

  python tests/scout_sources.py --summary "$GITHUB_STEP_SUMMARY"
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "tilavet-takip-scout/1.0"}
HF_QUERIES = ["quran", "quranic", "tilawa", "tilawah", "tarteel", "everyayah", "qiraat", "recitation", "taraweeh",
              "tarawih", "quran-asr", "quran audio"]
IA_QUERIES = [
    "teravih", "terawih", "tarawih", "taraweeh", "taraweh", "tarawee7", "\"salat al-tarawih\"", "\"salatul tarawih\"",
    "\"hatimle teravih\"", "\"teravih namazi\"", "\"teravih namazı\"", "\"cuma namazı\"", "\"yatsı namazı\"",
    "\"bayram namazı\"", "\"qiyam al-layl\"", "\"صلاة التراويح\"", "التراويح", "\"صلاة القيام\"",
]


def get_json(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                print(f"HATA {url}: {e}", flush=True)
                return None
            time.sleep(2 * (i + 1))


def hf_scan():
    seen = {}
    for q in HF_QUERIES:
        url = "https://huggingface.co/api/datasets?" + urllib.parse.urlencode(
            {"search": q, "limit": 60, "full": "true", "sort": "downloads", "direction": "-1"})
        for d in get_json(url) or []:
            seen.setdefault(d["id"], d)
    rows = []
    for did, d in seen.items():
        tags = d.get("tags") or []
        lic = [t.split(":", 1)[1] for t in tags if t.startswith("license:")]
        size = [t.split(":", 1)[1] for t in tags if t.startswith("size_categories:")]
        task = [t.split(":", 1)[1] for t in tags if t.startswith("task_categories:")]
        mod = [t.split(":", 1)[1] for t in tags if t.startswith("modality:")]
        audio = "audio" in mod or any("speech" in t or "audio" in t for t in task)
        rows.append({"id": did, "downloads": d.get("downloads", 0), "likes": d.get("likes", 0),
                     "license": ",".join(lic) or "?", "size": ",".join(size) or "?", "task": ",".join(task),
                     "audio": audio, "gated": d.get("gated", False), "modified": (d.get("lastModified") or "")[:10],
                     "desc": (d.get("description") or "").replace("\n", " ")[:160]})
    rows.sort(key=lambda r: (not r["audio"], -r["downloads"]))
    return rows


def ia_scan():
    seen = {}
    for q in IA_QUERIES:
        params = [("q", f"({q}) AND mediatype:(audio OR movies)"), ("rows", "100"), ("output", "json"),
                  ("sort[]", "downloads desc")]
        params += [("fl[]", f) for f in ("identifier", "title", "licenseurl", "downloads", "item_size", "date",
                                         "language", "mediatype")]
        res = get_json("https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(params))
        for doc in ((res or {}).get("response") or {}).get("docs", []):
            doc.setdefault("_q", q)
            seen.setdefault(doc["identifier"], doc)
    rows = sorted(seen.values(), key=lambda d: -(d.get("downloads") or 0))
    # En cok indirilen ilk 40 icin dosya listesi (ses dosyasi sayisi + toplam sure)
    for d in rows[:40]:
        meta = get_json(f"https://archive.org/metadata/{urllib.parse.quote(d['identifier'])}") or {}
        files = [f for f in meta.get("files", []) if str(f.get("name", "")).lower().endswith((".mp3", ".wav", ".ogg",
                                                                                             ".m4a", ".flac", ".opus"))]
        secs = 0.0
        for f in files:
            try:
                ln = f.get("length")
                if ln and ":" in str(ln):
                    parts = [float(x) for x in str(ln).split(":")]
                    secs += sum(p * 60 ** i for i, p in enumerate(reversed(parts)))
                elif ln:
                    secs += float(ln)
            except ValueError:
                pass
        d["_audio_files"] = len(files)
        d["_hours"] = round(secs / 3600, 1)
        d["_sample"] = [f["name"] for f in files[:3]]
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary")
    args = ap.parse_args()
    out = ["## Ses verisi kaynak taramasi", ""]

    hf = hf_scan()
    out += [f"### Hugging Face ({len(hf)} veri seti; ses / konusma olanlar once)", "",
            "| veri seti | ses | lisans | boyut | indirme | gated | guncelleme | aciklama |", "|---|---|---|---|---|---|---|---|"]
    for r in hf[:80]:
        out.append(f"| {r['id']} | {'✓' if r['audio'] else ''} | {r['license']} | {r['size']} | {r['downloads']} | "
                   f"{'evet' if r['gated'] else ''} | {r['modified']} | {r['desc'].replace('|', '/')} |")

    ia = ia_scan()
    out += ["", f"### archive.org ({len(ia)} kayit; en cok indirilen)", "",
            "| kayit | baslik | lisans | ses dosyasi | saat | indirme | tarih | arama |", "|---|---|---|---|---|---|---|---|"]
    for d in ia[:120]:
        title = str(d.get("title", ""))[:70].replace("|", "/")
        lic = str(d.get("licenseurl", "") or "-").replace("http://", "").replace("https://", "")
        out.append(f"| {d['identifier']} | {title} | {lic} | {d.get('_audio_files', '')} | {d.get('_hours', '')} | "
                   f"{d.get('downloads', '')} | {str(d.get('date', ''))[:10]} | {d.get('_q')} |")

    text = "\n".join(out) + "\n"
    print(text)
    print("SCOUTJSON " + json.dumps({"hf": hf[:150], "ia": ia[:200]}, ensure_ascii=False))
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(text)


if __name__ == "__main__":
    sys.exit(main())
