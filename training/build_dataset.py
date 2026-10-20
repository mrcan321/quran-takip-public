#!/usr/bin/env python3
"""Ince ayar verisi — Asama A (model gerekmez; kiralik GPU makinesinde ya da herhangi bir Linux'ta).

Uretilenler (<out>/):
  audio/...                ses parcalari (16 kHz mono FLAC)
  stage_a.jsonl            hazir egitim satirlari (NeMo manifest: audio_filepath, duration, text + kind/source/... bilgi)
  val_a.jsonl              dogrulama (egitimde olmayan kari)
  to_align.jsonl           metni bilinen UZUN bolumler: 20 sn'den uzun ayetler, gercek kayitlarin okuma bolumleri, kamet —
                           Asama B (prepare_labels.py) temel modelin CTC'siyle zorla hizalayip 4-15 sn parcalara boler
  to_label.jsonl           genel Arapca (FLEURS ar): etiketi Asama B'de temel modelin kendi ciktisi (unutmayi onlemek)
  stats.json               saat / parca sayilari

Kaynaklar:
  - EveryAyah ayet ayet MP3 (https://everyayah.com/data/<kari>/<SSSAAA>.mp3) — TEST KARILERI HARIC (sentetik kume:
    Alafasy, Husary, Sureym; dis kume: Sudeys, Sureym, Maher el-Muaykili, Hani Rifai, Medine imamlari). Ayetler kisa
    "kosu"lara (1-6 ardisik ayet) bolunur, her kosu --coverage kariye dagitilir; ardisik ayetler 5-15 sn parcalarda
    birlestirilir (cami parcalari gibi icinde ayet siniri olsun). Etiket: Tanzil imla'i metni harekeli (rasm map) —
    aligner'in korpusuyla ayni yazim, tokenizer'in karakter kumesinde.
  - Cami akustigi (acoustics.mosque): parcalarin --clean-frac'i temiz, gerisi hoparlor + yanki + telefon + gurultu.
  - Olumsuz ornekler (etiket bos): gurultu (sentetik + egitim kayitlarinin sessiz bolumleri), Turkce konusma (FLEURS tr,
    hoparlor + yanki — vaaz gibi; ASR'nin Turkce konusmaya Arapca uydurmasi). Arapca zikir / dua ASLA bos etiketlenmez.
  - Gercek cami kayitlari (training/real_labels.json, sadece "split": "train"): okuma bolumleri, kamet, zikirler,
    olumsuz bolumler (vaaz).

Kullanim:
  python training/build_dataset.py --out /data/tt --workers 16
  python training/build_dataset.py --out /tmp/tt --smoke            # 2 kari, birkac yuz parca (boru hattini dene)
  python training/build_dataset.py --out /tmp/tt --smoke --fake     # indirmeden (okuma yerine kayitlarimiz; mekanik test)
"""
import argparse
import hashlib
import io
import json
import random
import sys
import tarfile
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "scripts"))
import acoustics as ac  # noqa: E402

SR = ac.SR
UA = {"User-Agent": "tilavet-takip-train/1.0"}
EVERYAYAH = "https://everyayah.com/data/{reciter}/{surah:03d}{ayah:03d}.mp3"
FLEURS = "https://huggingface.co/datasets/google/fleurs/resolve/main/data/{lang}/{what}"

# Murattal (tertil) kariler — imamlarin namazdaki okuyusuna yakin. Mucevved (makamli, cok yavas) ve Vers (Warsh) alinmaz.
# Klasor adlari EveryAyah'in; olmayan kari basta yoklanip atlanir.
TRAIN_RECITERS = [
    "Abdul_Basit_Murattal_192kbps", "Abdullah_Basfar_192kbps", "Abu_Bakr_Ash-Shaatree_128kbps",
    "Ahmed_ibn_Ali_al-Ajamy_128kbps_ketaballah.net", "Ghamadi_40kbps", "Ibrahim_Akhdar_32kbps",
    "Minshawy_Murattal_128kbps", "Mohammad_al_Tablaway_128kbps", "Muhammad_Ayyoub_128kbps", "Muhammad_Jibreel_128kbps",
    "Nasser_Alqatami_128kbps", "Yasser_Ad-Dussary_128kbps", "Fares_Abbad_64kbps", "Khaalid_Abdullaah_al-Qahtaanee_192kbps",
    "Ali_Jaber_64kbps", "Ayman_Sowaid_64kbps", "Akram_AlAlaqimy_128kbps", "Abdullaah_3awwaad_Al-Juhaynee_128kbps",
    "Abdullah_Matroud_128kbps", "Karim_Mansoori_40kbps", "Parhizgar_48kbps", "Mustafa_Ismail_48kbps",
    "Salaah_AbdulRahman_Bukhatir_128kbps", "Yaser_Salamah_128kbps", "aziz_alili_128kbps", "Sahl_Yassin_128kbps",
]
VAL_RECITERS = ["Ali_Hajjaj_AlSuesy_128kbps"]
# Test kumelerimizde olan kariler (sentetik + dis kaynak) — egitime girerse olcum sisirilir
TEST_RECITER_PATTERNS = ["alafasy", "husary", "shuraym", "sudais", "maher", "muaiqly", "hani_rifai", "hudhaify",
                         "budair", "muhsin_al_qasim"]
MAX_UTT_SEC = 20.0


# ---------------- Kuran metni (imla'i, harekeli) ----------------
def load_texts():
    """{(sure, ayet): imla'i metin}, {sure: besmele}, {sure: ayet sayisi} — aligner'in kullandigi rasm map'ten."""
    import aligner
    data = json.loads(aligner.ensure_rasm_map().read_text(encoding="utf-8"))["quran"]["sura"]
    texts, bism, counts = {}, {}, {}
    for s in data:
        si = int(s["@index"])
        counts[si] = len(s["aya"])
        for a in s["aya"]:
            texts[(si, int(a["@index"]))] = " ".join(a["@imlaey"].split())
            if "@bismillah_imlaey" in a:
                bism[si] = " ".join(a["@bismillah_imlaey"].split())
    return texts, bism, counts


# ---------------- indirme ----------------
def fetch(url, dst, tries=4):
    dst = Path(dst)
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            tmp = dst.with_suffix(dst.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.rename(dst)
            return dst
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 * (i + 1))
        except Exception:  # noqa: BLE001
            time.sleep(2 * (i + 1))
    return None


def probe_reciters(names, cache):
    ok = []
    for r in names:
        p = fetch(EVERYAYAH.format(reciter=r, surah=1, ayah=2), Path(cache) / r / "001002.mp3")
        print(f"  kari {r}: {'var' if p else 'YOK (atlandi)'}", flush=True)
        if p:
            ok.append(r)
    return ok


# ---------------- yardimcilar ----------------
def uid(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


def write_flac(path, audio):
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(audio, -1, 1), SR, format="FLAC", subtype="PCM_16")
    return round(len(audio) / SR, 3)


def silence(sec, rng):
    return (rng.standard_normal(int(sec * SR)) * 1e-4).astype(np.float32)


def augment(audio, rng, args, noise_pool, babble_pool, real_room=False):
    if not real_room and rng.random() < args.clean_frac:
        return audio, "temiz"
    return ac.mosque(audio, rng, noise_pool, babble_pool, real_room=real_room)


# ---------------- EveryAyah kosulari (isci surecte) ----------------
_W = {}


def _init_worker(state):
    _W.update(state)


def _fake_ayah(rng):
    src = _W["fake_pool"][rng.integers(len(_W["fake_pool"]))]
    n = int(rng.uniform(2, 8) * SR)
    st = rng.integers(max(1, len(src) - n))
    return src[st:st + n].copy()


def run_job(job):
    """Bir kari + bir kosu (ardisik ayetler) → hazir parcalar + hizalanacak uzun ayetler."""
    args, texts = _W["args"], _W["texts"]
    reciter, ayahs, split = job["reciter"], job["ayahs"], job["split"]
    rng = np.random.default_rng(int(uid(args.seed, reciter, ayahs[0]), 16) % (1 << 32))
    out_dir = Path(args.out) / "audio" / split / reciter
    items, aligns, cur, cur_dur = [], [], [], 0.0
    target = rng.uniform(5, 15)

    def emit():
        nonlocal cur, cur_dur, target
        if not cur:
            return
        pieces, labels, ids = [], [], []
        for k, (sa, a) in enumerate(cur):
            if k:
                pieces.append(silence(rng.uniform(0.3, 1.0), rng))
            pieces.append(a)
            labels.append(texts[sa])
            ids.append(f"{sa[0]}:{sa[1]}")
        audio = np.concatenate(pieces)
        aug, desc = augment(audio, rng, args, _W["noise_pool"], _W["babble_pool"])
        name = uid(reciter, *ids)
        dur = write_flac(out_dir / f"{name}.flac", aug)
        items.append({"audio_filepath": str(out_dir / f"{name}.flac"), "duration": dur, "text": " ".join(labels),
                      "kind": "quran", "source": "everyayah", "reciter": reciter, "ayahs": ids, "aug": desc,
                      "ayah1": any(sa[1] == 1 and sa[0] not in (1, 9) for sa, _ in cur)})
        cur, cur_dur, target = [], 0.0, rng.uniform(5, 15)

    for (s, a) in ayahs:
        if args.fake:
            audio = _fake_ayah(rng)
        else:
            p = fetch(EVERYAYAH.format(reciter=reciter, surah=s, ayah=a),
                      Path(args.cache) / reciter / f"{s:03d}{a:03d}.mp3")
            if p is None:
                emit()
                continue
            try:
                audio = ac.trim(ac.load_any(p))
            except Exception:  # noqa: BLE001
                emit()
                continue
        dur = len(audio) / SR
        if dur < 0.4:
            continue
        if dur > MAX_UTT_SEC:
            emit()
            clean = Path(args.out) / "align" / split / reciter / f"{uid(reciter, s, a)}.flac"
            d = write_flac(clean, audio)
            aligns.append({"audio_filepath": str(clean), "duration": d, "text": texts[(s, a)], "kind": "quran",
                           "source": "everyayah", "reciter": reciter, "ayahs": [f"{s}:{a}"], "split": split,
                           "augment": True, "ayah1": a == 1 and s not in (1, 9)})
            continue
        if cur and cur_dur + dur > target:
            emit()
        cur.append(((s, a), audio))
        cur_dur += dur
    emit()
    return items, aligns


# ---------------- planlama ----------------
def plan_runs(counts, reciters, coverage, rng, max_run=6):
    """Mushaf sirasinda 1-max_run ayetlik kosular; her kosu `coverage` farkli kariye (esit dagilim)."""
    all_ayahs = [(s, a) for s in range(1, 115) for a in range(1, counts[s] + 1)]
    runs, i = [], 0
    while i < len(all_ayahs):
        n = rng.randint(1, max_run)
        run = [x for x in all_ayahs[i:i + n] if x[0] == all_ayahs[i][0]]   # sure sinirini gecme
        runs.append(run)
        i += len(run)
    jobs = []
    k = max(1, min(len(reciters), int(round(coverage))))
    for run in runs:
        for r in rng.sample(reciters, k):
            jobs.append({"reciter": r, "ayahs": run, "split": "train"})
    rng.shuffle(jobs)
    return jobs


# ---------------- gercek kayitlar ----------------
def real_items(args, texts, rng_np):
    """real_labels.json (split=train) → hazir parcalar (zikir, olumsuz), hizalanacak bolumler, gurultu havuzu."""
    labels = json.loads(Path(args.real_labels).read_text(encoding="utf-8"))
    items, aligns, noise_pool = [], [], []
    out_dir = Path(args.out) / "audio" / "real"
    for fn, info in labels["files"].items():
        if info.get("split") != "train":
            continue
        p = REPO / "data" / fn
        if not p.exists():
            print(f"  UYARI: {fn} yok (data/'ya konmali)", flush=True)
            continue
        audio = ac.load_any(p)
        busy = []
        for seg in info.get("segments", []):
            s, (a0, a1) = seg["surah"], seg["ayahs"]
            text = " ".join(texts[(s, a)] for a in range(a0, a1 + 1))
            st, en = max(0.0, seg["start"] - 1.0), min(len(audio) / SR, seg["end"] + 1.0)
            clean = Path(args.out) / "align" / "real" / f"{uid(fn, st, en)}.flac"
            d = write_flac(clean, audio[int(st * SR):int(en * SR)])
            aligns.append({"audio_filepath": str(clean), "duration": d, "text": text, "kind": "real",
                           "source": fn, "ayahs": [f"{s}:{a}" for a in range(a0, a1 + 1)], "split": "train",
                           "augment": False, "trim_edges": True})
            busy.append((st, en))
        if info.get("kamet"):
            st, en = info["kamet"]
            clean = Path(args.out) / "align" / "real" / f"{uid(fn, 'kamet')}.flac"
            d = write_flac(clean, audio[int(st * SR):int(en * SR)])
            aligns.append({"audio_filepath": str(clean), "duration": d, "text": labels["kamet_text"], "kind": "kamet",
                           "source": fn, "split": "train", "augment": False, "trim_edges": False})
            busy.append((st, en))
        for st, en, kind in info.get("phrases", []):
            seg = audio[int(st * SR):int(en * SR)]
            text = labels["phrase_texts"].get(kind, kind)
            path = out_dir / f"{uid(fn, st, kind)}.flac"
            items.append({"audio_filepath": str(path), "duration": write_flac(path, seg), "text": text,
                          "kind": "phrase", "source": fn, "aug": "gercek"})
            busy.append((st, en))
        for st, en in info.get("negatives", []):
            t = st
            while t + 2 < en:
                d = min(en - t, rng_np.uniform(3, 10))
                seg = audio[int(t * SR):int((t + d) * SR)]
                path = out_dir / f"{uid(fn, 'neg', t)}.flac"
                items.append({"audio_filepath": str(path), "duration": write_flac(path, seg), "text": "",
                              "kind": "negative", "source": fn, "aug": "gercek"})
                t += d
            busy.append((st, en))
        # gurultu havuzu: etiketli bolumler disinda, dosyanin en sessiz %30'luk 5 sn pencereleri
        wins = [(t, ac.rms(audio[int(t * SR):int((t + 5) * SR)])) for t in np.arange(0, len(audio) / SR - 5, 5.0)
                if not any(a - 1 < t + 5 and t < b + 1 for a, b in busy)]
        if wins:
            thr = np.percentile([r for _, r in wins], 30)
            noise_pool += [audio[int(t * SR):int((t + 5) * SR)] for t, r in wins if r <= thr]
    return items, aligns, noise_pool


# ---------------- FLEURS (Turkce olumsuz, Arapca hatirlatma) ----------------
def fleurs(lang, split, cache):
    """FLEURS <lang>/<split> → [(ad, ses, metin)] (HF'den tar + tsv; ~200-500 MB, cache'lenir)."""
    tar_p = fetch(FLEURS.format(lang=lang, what=f"audio/{split}.tar.gz"), Path(cache) / "fleurs" / lang / f"{split}.tar.gz")
    tsv_p = fetch(FLEURS.format(lang=lang, what=f"{split}.tsv"), Path(cache) / "fleurs" / lang / f"{split}.tsv")
    if not tar_p or not tsv_p:
        print(f"  UYARI: FLEURS {lang}/{split} indirilemedi — atlandi", flush=True)
        return []
    trans = {}
    for line in tsv_p.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if len(cols) > 3:
            trans[cols[1]] = cols[2]   # ham metin (noktalama normalize_arabic ile gider)
    out = []
    with tarfile.open(tar_p) as tf:
        for m in tf:
            if not m.isfile() or not m.name.endswith(".wav"):
                continue
            name = Path(m.name).name
            a, sr = sf.read(io.BytesIO(tf.extractfile(m).read()), dtype="float32", always_2d=True)
            a = a.mean(axis=1)
            if sr != SR:
                import soxr
                a = soxr.resample(a, sr, SR, quality="HQ")
            out.append((name, a.astype(np.float32), trans.get(name, "")))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "everyayah")
    ap.add_argument("--reciters", default=",".join(TRAIN_RECITERS))
    ap.add_argument("--val-reciters", default=",".join(VAL_RECITERS))
    ap.add_argument("--coverage", type=float, default=4.0, help="her ayet kac farkli kariden (~25 sa / kapsam)")
    ap.add_argument("--max-hours", type=float, default=150.0, help="EveryAyah parcalari icin ust sinir (saat)")
    ap.add_argument("--val-ayahs", type=int, default=600)
    ap.add_argument("--clean-frac", type=float, default=0.25, help="bozulmadan kalan parca orani")
    ap.add_argument("--neg-frac", type=float, default=0.05, help="gurultu olumsuz orneklerinin orani")
    ap.add_argument("--fleurs-tr", type=int, default=600, help="Turkce konusma olumsuz ornek sayisi (0 = yok)")
    ap.add_argument("--fleurs-ar", type=int, default=1500, help="genel Arapca hatirlatma parcasi (0 = yok)")
    ap.add_argument("--real-labels", type=Path, default=HERE / "real_labels.json")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--smoke", action="store_true", help="kucuk deneme: 2 kari, ~60 kosu, az olumsuz")
    ap.add_argument("--fake", action="store_true", help="indirmeden: okuma yerine data/ kayitlari (sadece mekanik test)")
    args = ap.parse_args()
    args.out = args.out.resolve()
    args.cache = args.cache.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    rng_np = np.random.default_rng(args.seed)

    texts, bism, counts = load_texts()
    print(f"Kuran metni: {len(texts)} ayet", flush=True)

    reciters = [r for r in args.reciters.split(",") if r]
    bad = [r for r in reciters if any(p in r.lower() for p in TEST_RECITER_PATTERNS)]
    if bad:
        raise SystemExit(f"HATA: test karileri egitime konamaz: {bad}")
    val_reciters = [r for r in args.val_reciters.split(",") if r and r not in reciters]
    if args.smoke:
        reciters, args.fleurs_tr, args.fleurs_ar = reciters[:2], min(args.fleurs_tr, 20), min(args.fleurs_ar, 20)
        args.val_ayahs = min(args.val_ayahs, 30)
    if not args.fake:
        print("Kari yoklamasi:", flush=True)
        reciters = probe_reciters(reciters, args.cache)
        val_reciters = probe_reciters(val_reciters, args.cache)
        if not reciters:
            raise SystemExit("HATA: hic kari yok (everyayah.com erisilebilir mi?)")

    # gercek kayitlar (egitim bolumu) → gurultu havuzu da buradan
    r_items, r_aligns, noise_pool = real_items(args, texts, rng_np)
    print(f"Gercek kayitlar (train): {len(r_items)} parca, {len(r_aligns)} hizalanacak bolum, "
          f"gurultu havuzu {len(noise_pool)} × 5 sn", flush=True)
    if not noise_pool:
        print("  (egitim bolumunde gercek kayit yok — gurultu sentetik)", flush=True)

    fake_pool = None
    if args.fake:
        fake_pool = [ac.load_any(REPO / "data" / f) for f in ("test_fatiha.wav", "ihlas.wav", "Nas.wav", "felak.wav")]
    # uguldama havuzu: birkac temiz ayet (uzak cemaat sesi icin)
    babble_pool = []
    if args.fake:
        babble_pool = [x[:SR * 4] for x in fake_pool]
    else:
        for (s, a) in rng.sample(sorted(texts), 24):
            p = fetch(EVERYAYAH.format(reciter=reciters[0], surah=s, ayah=a), args.cache / reciters[0] / f"{s:03d}{a:03d}.mp3")
            if p:
                babble_pool.append(ac.trim(ac.load_any(p)))

    jobs = plan_runs(counts, reciters, args.coverage, rng)
    if args.smoke:
        jobs = jobs[:60]
    # dogrulama: egitimde olmayan kari(lar), rastgele ayetler
    val_jobs = []
    if val_reciters:
        picks = rng.sample(sorted(texts), args.val_ayahs)
        for i, sa in enumerate(sorted(picks)):
            val_jobs.append({"reciter": val_reciters[i % len(val_reciters)], "ayahs": [sa], "split": "val"})
    elif args.fake:
        val_jobs = [{"reciter": "fake_val", "ayahs": [sa], "split": "val"} for sa in rng.sample(sorted(texts), 10)]

    state = {"args": args, "texts": texts, "noise_pool": noise_pool, "babble_pool": babble_pool, "fake_pool": fake_pool}
    train, val, aligns = list(r_items), [], list(r_aligns)
    hours, t0 = 0.0, time.time()
    with ProcessPoolExecutor(args.workers, initializer=_init_worker, initargs=(state,)) as ex:
        futs = {ex.submit(run_job, j): j for j in val_jobs}
        for f in as_completed(futs):
            it, al = f.result()
            val += it
            aligns += [dict(x, split="val") for x in al]
        pending = list(jobs)
        futs = {}
        while pending or futs:
            while pending and len(futs) < args.workers * 4 and hours < args.max_hours:
                j = pending.pop()
                futs[ex.submit(run_job, j)] = j
            if not futs:
                break
            done = next(as_completed(futs))
            futs.pop(done)
            it, al = done.result()
            train += it
            aligns += al
            hours += (sum(x["duration"] for x in it) + sum(x["duration"] for x in al)) / 3600
            if len(train) % 500 < len(it):
                print(f"  {len(train)} parca, {hours:.1f} sa, {time.time() - t0:.0f} sn", flush=True)

    # olumsuz: gurultu
    n_neg = int(args.neg_frac * len(train))
    neg_dir = args.out / "audio" / "neg"
    for i in range(n_neg):
        a = ac.noise_only(int(rng_np.uniform(1.5, 8) * SR), rng_np, noise_pool, babble_pool)
        p = neg_dir / f"noise_{i:05d}.flac"
        train.append({"audio_filepath": str(p), "duration": write_flac(p, a), "text": "", "kind": "negative",
                      "source": "noise"})
    # olumsuz: Turkce konusma (hoparlor + yanki → vaaz gibi)
    if args.fleurs_tr:
        tr = fleurs("tr_tr", "dev", args.cache) + ([] if args.smoke else fleurs("tr_tr", "test", args.cache))
        for name, a, _ in rng.sample(tr, min(args.fleurs_tr, len(tr))):
            y, desc = ac.mosque(a, rng_np, noise_pool, babble_pool)
            p = neg_dir / f"tr_{Path(name).stem}.flac"
            train.append({"audio_filepath": str(p), "duration": write_flac(p, y), "text": "", "kind": "negative",
                          "source": "fleurs_tr", "aug": desc})
    # genel Arapca: etiket Asama B'de (temel modelin ciktisi; FLEURS metni kalite suzgeci)
    to_label = []
    if args.fleurs_ar:
        ar = fleurs("ar_eg", "dev" if args.smoke else "train", args.cache)
        rdir = args.out / "audio" / "replay"
        for name, a, ref in rng.sample(ar, min(args.fleurs_ar, len(ar))):
            y, desc = augment(a, rng_np, args, noise_pool, babble_pool)
            p = rdir / f"ar_{Path(name).stem}.flac"
            to_label.append({"audio_filepath": str(p), "duration": write_flac(p, y), "text": "", "ref": ref,
                             "kind": "replay", "source": "fleurs_ar", "aug": desc})

    def dump(name, rows):
        with open(args.out / name, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump("stage_a.jsonl", train)
    dump("val_a.jsonl", val)
    dump("to_align.jsonl", aligns)
    dump("to_label.jsonl", to_label)
    stats = {}
    for r in train + aligns + to_label:
        k = r["kind"]
        stats.setdefault(k, [0, 0.0])
        stats[k][0] += 1
        stats[k][1] += r["duration"] / 3600
    stats = {k: {"parca": n, "saat": round(h, 2)} for k, (n, h) in stats.items()}
    stats["val"] = {"parca": len(val), "saat": round(sum(x["duration"] for x in val) / 3600, 2)}
    stats["kariler"] = reciters
    stats["dogrulama_karileri"] = val_reciters
    (args.out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    print(f"bitti: {time.time() - t0:.0f} sn → {args.out}")


if __name__ == "__main__":
    main()
