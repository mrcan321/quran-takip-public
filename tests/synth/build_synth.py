#!/usr/bin/env python3
"""Sentetik namaz / teravih kayitlari: EveryAyah ayet ayet kayitlari + gercek cami kayitlarimizdan namaz sesleri.

Telefonsuz, gercek ASR ile (eval_pipeline) olculecek uzun namaz akislari uretir — elimizde gercek teravih kaydi yok.
Her ayet ayri dosya oldugu icin ayet sinirlari kesin: manifest'te sure zaman cizelgesi (eval TIMELINE) + ayet ayet
dogruluk (tests/synth/score_synth.py) + beklenen rekat / namaz sayisi.

Parcalar:
- Okuma: https://everyayah.com/data/<kari>/<SSSAAA>.mp3 (CI'da indirilir, --cache'te tutulur; repoya konmaz).
  Hanefi: besmele sessiz (Fatiha 1:2'den, zamm 1. ayetin besmelesi atlanir).
- Namaz sesleri (kamet, tekbir, semiallah, selam) ve cami arka plan gurultusu: data/namaz_*.wav gercek cami kayitlarindan,
  tests/trjson'daki sabit 5 sn RNNT parcalarinin metnine gore kesilir (namaz_signal / tekbir) — gercek cami akustigi.
- Cami akustigi okumaya eklenir: sentetik oda yankisi (RT60 1.0-2.4 sn, ustel sonumlu gurultu + hava sogurmasi),
  telefon mikrofonu (100 Hz yuksek geciren, 5-7 kHz alcak geciren), seviye, arka plan gurultusu.

Programlar (--programs):
  namaz2    kamet + 2 rekat (Fatiha + kisa sure, 2. rekatta sonraki sure) + oturus + selam
  teravih8  4 x 2 rekat, zamm Fil → Nas sirasiyla (Turkiye'de teravihte okunan sureler), her 4 rekatta tesbih arasi
  hatim4    2 x 2 rekat, hatimle teravih: her rekat onceki rekatin kaldigi ayetten devam (cuz basindan)
  uzun2     2 rekat, uzun zamm (cuma/bayram: bir surenin ortasindan 10-16 ayet)
  dort4     4 rekatli (yatsi/ikindi gibi): 1-2. rekat sesli, 3-4. rekat sessiz (sadece tekbir/semiallah)

Kullanim:
  python tests/synth/build_synth.py --out synth --cache ~/.cache/everyayah --reciters Alafasy_128kbps,Husary_128kbps
  python tests/synth/build_synth.py --out synth --fake      # indirmeden (okuma yerine kayitlarimizdan parca; mekanik test)
"""
import argparse
import json
import random
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
SR = 16000
EVERYAYAH = "https://everyayah.com/data/{reciter}/{surah:03d}{ayah:03d}.mp3"
DEFAULT_RECITERS = "Alafasy_128kbps,Husary_128kbps,Saood_ash-Shuraym_128kbps"
NAMAZ_WAVS = ["namaz_aksam_fatiha_zilzal_fatiha_kafirun.wav", "namaz_aksam2_fatiha_rad_fatiha_ibrahim.wav",
              "namaz_cuma_kamet_fatiha_enbiya_fatiha_insirah.wav", "namaz_cuma2_kamet_fatiha_tekasur_fatiha_asr.wav",
              "namaz_cuma3_kamet_fatiha_felak_fatiha_nas.wav"]
SURAH_AYAHS = {}   # sure → ayet sayisi (korpustan)


# ---------------- ses yardimcilari ----------------
def load_any(path):
    """MP3 / WAV → 16 kHz mono float32 (soundfile; olmazsa ffmpeg)."""
    try:
        a, sr = sf.read(str(path), dtype="float32", always_2d=True)
        a = a.mean(axis=1)
    except Exception:
        raw = subprocess.run(["ffmpeg", "-v", "quiet", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                             capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype="<f4").copy()
    if sr != SR:
        import soxr
        a = soxr.resample(a, sr, SR, quality="HQ")
    return a.astype(np.float32)


def trim(a, thr_db=-38.0, pad=0.06):
    """Bastaki / sondaki sessizligi kirp (20 ms cerceve, tepe seviyesine gore esik)."""
    if len(a) == 0:
        return a
    f = 320
    n = len(a) // f
    if n == 0:
        return a
    rms = np.sqrt(np.mean(a[:n * f].reshape(n, f) ** 2, axis=1) + 1e-12)
    thr = rms.max() * 10 ** (thr_db / 20)
    on = np.nonzero(rms > thr)[0]
    if len(on) == 0:
        return a[:0]
    s = max(0, on[0] * f - int(pad * SR))
    e = min(len(a), (on[-1] + 1) * f + int(pad * SR))
    return a[s:e]


def fft_filter(a, lo=None, hi=None):
    """Frekans alaninda yumusak bant gecirme (cosinus gecis) — tek kutuplu donguden hizli."""
    n = len(a)
    if n == 0:
        return a
    m = 1 << (n - 1).bit_length()
    A = np.fft.rfft(a, m)
    f = np.fft.rfftfreq(m, 1 / SR)
    g = np.ones_like(f)
    if hi:
        w = hi * 0.25
        g *= np.clip(0.5 * (1 + np.cos(np.pi * np.clip((f - hi) / w, 0, 1))), 0, 1)
    if lo:
        w = lo * 0.5
        g *= np.clip(0.5 * (1 - np.cos(np.pi * np.clip((f - (lo - w)) / w, 0, 1))), 0, 1)
    return np.fft.irfft(A * g, m)[:n].astype(np.float32)


def room_ir(rng, rt60):
    """Sentetik oda yankisi: dogrudan ses + erken yansimalar + ustel sonumlu gurultu kuyrugu (hava sogurmasi)."""
    n = int(SR * min(rt60 * 1.1, 3.0))
    t = np.arange(n) / SR
    tail = rng.standard_normal(n) * np.exp(-6.91 * t / rt60)
    tail = fft_filter(tail, hi=rng.uniform(2500, 4500))
    ir = np.zeros(n, dtype=np.float32)
    pre = int(SR * rng.uniform(0.008, 0.03))
    ir[0] = 1.0
    for _ in range(6):
        k = pre + int(SR * rng.uniform(0.0, 0.05))
        if k < n:
            ir[k] += rng.uniform(0.2, 0.6) * rng.choice([-1, 1])
    drr = 10 ** (rng.uniform(-4, 4) / 20)   # dogrudan / yanki orani
    tail[:pre] = 0
    tail *= 1.0 / (np.sqrt(np.sum(tail ** 2)) + 1e-9) / drr
    return (ir + tail).astype(np.float32)


def convolve(a, ir):
    n = len(a) + len(ir) - 1
    m = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(a, m) * np.fft.rfft(ir, m), m)[:n].astype(np.float32)


def rms(a):
    return float(np.sqrt(np.mean(a ** 2))) if len(a) else 0.0


# ---------------- gercek kayitlardan namaz sesleri ----------------
def load_cues(rng):
    """data/namaz_*.wav + tests/trjson (rnnt, sabit 5 sn) → {tekbir, semiallah, selam, kamet: [klip]}, gurultu yatagi."""
    sys.path.insert(0, str(REPO / "tests"))
    from lib import env  # noqa: E402
    sm = env.sm
    T = env.load_trjson().get("rnnt", {})
    cues = {"tekbir": [], "semiallah": [], "selam": [], "kamet": []}
    noise = []
    for fn in NAMAZ_WAVS:
        p = REPO / "data" / fn
        if not p.exists() or fn not in T:
            continue
        audio = load_any(p)
        tl = env.ev.timeline_for(fn) or []
        first_quran = next((st for st, su in tl if su is not None), None)
        # Kuran okunan araliklar: bunlara degen 5 sn'lik parca namaz sesi klibi olamaz (iftitah tekbiri parcasi Fatiha'nin
        # basini, rukû tekbiri zamm'in sonunu iceriyordu → sentetikte rukû arasinda "الحمد لله رب العالمين" kilidi)
        quran = [(st, tl[i + 1][0] if i + 1 < len(tl) else 1e9) for i, (st, su) in enumerate(tl) if su is not None]
        for k, c in enumerate(T[fn]):
            end = env.chunk_time(c, k)
            if first_quran is not None and end - 5 < first_quran and "kamet" in fn:
                continue        # kamet bolumundeki "tekbir"ler kamet parcasi icerir (ilk CI kosusunda kamet sayildi)
            if any(a - 1.0 < end and end - 5 < b + 1.0 for a, b in quran):
                continue
            seg = audio[int((end - 5) * SR):int(end * SR)]
            text = c[1] or ""
            if (c[0] or 0) < 0.004 and len(seg) == 5 * SR:
                noise.append(seg)
                continue
            sig = sm.namaz_signal(text)
            toks = [t for t in (sm.bare_token(w) for w in text.split()) if t]
            if sig == "ruku":
                cues["semiallah"].append(trim(seg, -30))
            elif sig == "selam":
                cues["selam"].append(trim(seg, -30))
            elif toks and all(t in ("الله", "اكبر", "اغبر", "اكبار") for t in toks) and "الله" in toks:
                cues["tekbir"].append(trim(seg, -30))
        if "kamet" in fn and first_quran:
            # kamet: kaydin basindan iftitah tekbirine kadar (ilk Fatiha'dan ~12 sn once)
            ks = audio[:int(max(0, first_quran - 12) * SR)]
            if len(ks) > 20 * SR:
                cues["kamet"].append(trim(ks, -35))
    bed = np.concatenate(noise) if noise else np.zeros(SR * 10, dtype=np.float32)
    return {k: [x for x in v if len(x) > SR // 4] for k, v in cues.items()}, bed


# ---------------- okuma ----------------
class Recitation:
    def __init__(self, reciter, cache, fake=False, fake_pool=None, rng=None):
        self.reciter, self.cache, self.fake, self.pool, self.rng = reciter, Path(cache), fake, fake_pool, rng

    def ayah(self, s, a):
        if self.fake:
            # Mekanik test: kayitlarimizdan rastgele 2-6 sn konusma (icerik dogru degil)
            src = self.pool[self.rng.randrange(len(self.pool))]
            n = int(self.rng.uniform(2, 6) * SR)
            st = self.rng.randrange(max(1, len(src) - n))
            return src[st:st + n].copy()
        p = self.cache / self.reciter / f"{s:03d}{a:03d}.mp3"
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            url = EVERYAYAH.format(reciter=self.reciter, surah=s, ayah=a)
            req = urllib.request.Request(url, headers={"User-Agent": "tilavet-takip-test/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r, open(p.with_suffix(".tmp"), "wb") as f:
                f.write(r.read())
            p.with_suffix(".tmp").rename(p)
        return trim(load_any(p))


class Program:
    """Zaman cizelgesi kurucu: okuma (yankili), namaz sesleri (gercek), sessizlik; manifest bilgisi."""

    def __init__(self, rng, rec, cues, room):
        self.rng, self.rec, self.cues, self.ir = rng, rec, cues, room
        self.parts = []          # (baslangic_sn, ses)
        self.t = 0.0
        self.timeline = []       # (sn, sure | None)
        self.ayahs = []          # (bas, son, sure, ayet)
        self.events = []         # (sn, olay)
        self.level = rng.uniform(0.04, 0.075)    # cami kayitlarinda okuma rms ~0.05-0.07

    def _put(self, a):
        self.parts.append((self.t, a))

    def gap(self, lo, hi=None):
        self.t += self.rng.uniform(lo, hi) if hi is not None else lo

    def section(self, surah):
        if not self.timeline or self.timeline[-1][1] != surah:
            self.timeline.append((round(self.t, 2), surah))

    def cue(self, kind):
        lst = self.cues.get(kind) or []
        self.events.append((round(self.t, 2), kind))
        if not lst:
            self.gap(1.5)
            return
        c = lst[self.rng.randrange(len(lst))]
        self._put(c * self.rng.uniform(0.7, 1.2))
        self.t += len(c) / SR

    def recite(self, s, a):
        dry = self.rec.ayah(s, a)
        if len(dry) == 0:
            return
        wet = convolve(dry, self.ir)
        wet = fft_filter(wet, lo=100, hi=self.rng.uniform(5000, 7000))
        wet *= self.level / (rms(wet[:len(dry)]) + 1e-9) * self.rng.uniform(0.85, 1.15)
        self._put(wet)
        self.ayahs.append((round(self.t, 2), round(self.t + len(dry) / SR, 2), s, a))
        self.t += len(dry) / SR

    def recite_range(self, s, a0, a1, gap=(0.4, 1.4)):
        self.section(s)
        for a in range(a0, a1 + 1):
            self.recite(s, a)
            self.gap(*gap)

    # ---- namaz parcalari ----
    def fatiha(self):
        self.recite_range(1, 2, 7, gap=(0.5, 1.6))     # Hanefi: besmele sessiz
        self.gap(1.5, 4.0)                             # "amin" sessiz

    def zamm(self, s, a0=1, a1=None):
        a1 = a1 or SURAH_AYAHS[s]
        if a0 == 1 and s not in (1, 9):
            self.gap(0.3, 0.8)                         # besmele sessiz
        self.recite_range(s, a0, a1)

    def ruku_sujud(self):
        self.section(None)
        self.cue("tekbir"); self.gap(6, 10)            # ruku
        self.cue("semiallah"); self.gap(2, 4)
        self.cue("tekbir"); self.gap(5, 8)             # secde
        self.cue("tekbir"); self.gap(2, 3)             # celse
        self.cue("tekbir"); self.gap(5, 8)             # secde
        self.cue("tekbir"); self.gap(1, 2)             # kalkis / oturus

    def rakat(self, zamm_spec):
        """Kiyam (iftitah / kalkis tekbiri onceki parcada) → Fatiha → zamm → rukû + secdeler."""
        self.gap(1, 3)
        self.section(1)
        self.fatiha()
        if zamm_spec:
            self.zamm(*zamm_spec)
        self.gap(0.8, 1.5)
        self.ruku_sujud()

    def silent_rakat(self):
        self.section(None)
        self.gap(25, 35)                               # sessiz Fatiha
        self.ruku_sujud()

    def selam(self):
        self.section(None)
        self.gap(30, 60)                               # tahiyyat / salavat / dualar (sessiz)
        self.cue("selam"); self.gap(1, 2); self.cue("selam")
        self.gap(3, 6)

    def kamet(self):
        self.section(None)
        if self.cues.get("kamet"):
            self.cue("kamet")
        self.gap(6, 12)
        self.cue("tekbir")                             # iftitah

    def render(self, bed):
        n = int((self.t + 3.5) * SR)
        out = np.zeros(n, dtype=np.float32)
        for st, a in self.parts:
            i = int(st * SR)
            j = min(n, i + len(a))
            out[i:j] += a[:j - i]
        if len(bed):
            reps = int(np.ceil(n / len(bed)))
            off = self.rng.randrange(len(bed))
            nb = np.tile(bed, reps + 1)[off:off + n]
            out += nb * self.rng.uniform(0.7, 1.4)
        peak = np.max(np.abs(out)) if len(out) else 1.0
        if peak > 0.98:
            out *= 0.98 / peak
        return out


def build(name, rng, rec, cues, bed):
    room = room_ir(np.random.default_rng(rng.randrange(1 << 30)), rng.uniform(1.0, 2.4))
    P = Program(rng, rec, cues, room)
    rakats, namaz = 0, 0
    if name == "namaz2":
        s = rng.choice([93, 95, 97, 99, 100, 101, 102, 103, 104, 105, 107, 108, 109, 110, 112])
        P.kamet()
        P.rakat((s,)); P.rakat((s + 1 if s + 1 <= 114 else 112,)); P.selam()
        rakats, namaz = 2, 1
    elif name == "teravih8":
        seq = [105, 106, 107, 108, 109, 110, 111, 112, 113, 114]
        k = rng.randrange(3)
        P.section(None); P.gap(4, 8); P.cue("tekbir")
        for st in range(4):
            for _ in range(2):
                P.rakat((seq[k % len(seq)],)); k += 1
            P.selam()
            if st % 2 == 1 and st < 3:
                P.gap(20, 35)                          # tesbih / salavat arasi
            P.cue("tekbir")
        rakats, namaz = 8, 4
    elif name == "hatim4":
        # cuz baslari (sure, ayet) — kisa ayetli bolumler secilir ki rekat ~1.5-2 dk olsun
        s, a = rng.choice([(78, 1), (67, 1), (51, 31), (46, 21), (36, 13), (26, 1), (20, 1), (19, 1)])
        P.section(None); P.gap(4, 8); P.cue("tekbir")
        for st in range(2):
            for _ in range(2):
                n = rng.randint(6, 10)
                a1 = min(SURAH_AYAHS[s], a + n - 1)
                P.rakat((s, a, a1))
                a = a1 + 1
                if a > SURAH_AYAHS[s]:
                    s, a = s + 1, 1
            P.selam(); P.cue("tekbir")
        rakats, namaz = 4, 2
    elif name == "uzun2":
        s = rng.choice([18, 19, 20, 21, 23, 25, 36, 55, 56, 67])
        a = rng.randint(1, max(1, SURAH_AYAHS[s] - 30))
        P.kamet()
        n1, n2 = rng.randint(10, 16), rng.randint(8, 12)
        P.rakat((s, a, min(SURAH_AYAHS[s], a + n1 - 1)))
        a2 = min(SURAH_AYAHS[s], a + n1)
        P.rakat((s, a2, min(SURAH_AYAHS[s], a2 + n2 - 1)))
        P.selam()
        rakats, namaz = 2, 1
    elif name == "dort4":
        s = rng.choice([97, 99, 103, 105, 106, 107, 108, 110, 112])
        P.kamet()
        P.rakat((s,)); P.rakat((s + 1,))
        P.section(None); P.gap(15, 25); P.cue("tekbir")   # ilk oturus (tahiyyat) + kalkis
        P.silent_rakat(); P.silent_rakat(); P.selam()
        rakats, namaz = 4, 1
    else:
        raise SystemExit(f"bilinmeyen program: {name}")
    audio = P.render(bed)
    return audio, {"expected": "coklu", "timeline": P.timeline, "ayahs": P.ayahs, "events": P.events,
                   "rakats": rakats, "namaz": namaz, "duration": round(len(audio) / SR, 2)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "everyayah")
    ap.add_argument("--reciters", default=DEFAULT_RECITERS)
    ap.add_argument("--programs", default="namaz2,teravih8,hatim4")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--fake", action="store_true", help="indirmeden: okuma yerine kayitlarimizdan rastgele parca")
    args = ap.parse_args()

    import aligner
    corpus = aligner.QuranCorpus.load()
    for w in corpus.words:
        SURAH_AYAHS[w.surah] = max(SURAH_AYAHS.get(w.surah, 0), w.ayah)

    rng0 = random.Random(args.seed)
    cues, bed = load_cues(rng0)
    print("namaz sesleri: " + ", ".join(f"{k} {len(v)}" for k, v in cues.items()) + f"; gurultu {len(bed) / SR:.0f} sn",
          flush=True)
    pool = None
    if args.fake:
        pool = [load_any(REPO / "data" / fn) for fn in ("test_fatiha.wav", "ihlas.wav", "Nas.wav")]
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = {"files": {}}
    for reciter in [r for r in args.reciters.split(",") if r]:
        for prog in [p for p in args.programs.split(",") if p]:
            rng = random.Random(f"{args.seed}-{reciter}-{prog}")
            rec = Recitation(reciter, args.cache, args.fake, pool, rng)
            fn = f"synth_{prog}_{reciter.split('_')[0].lower()}_s{args.seed}.wav"
            try:
                audio, info = build(prog, rng, rec, cues, bed)
            except Exception as e:     # kari klasoru yoksa / indirme hatasi: digerleriyle devam
                print(f"ATLANDI {fn}: {e}", flush=True)
                continue
            sf.write(str(args.out / fn), audio, SR, subtype="PCM_16")
            info["reciter"], info["program"] = reciter, prog
            manifest["files"][fn] = info
            secs = [su for _, su in info["timeline"] if su]
            print(f"{fn}: {info['duration']:.0f} sn, {len(info['ayahs'])} ayet, sureler {secs}", flush=True)
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(manifest['files'])} kayit → {args.out}")


if __name__ == "__main__":
    main()
