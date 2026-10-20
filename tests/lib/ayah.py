"""Ayet duzeyinde takip olcumu (sentetik kayitlar: ayet sinirlari kesin, tests/synth/build_synth.py manifest'i).

Ekrandaki ayet: her parcanin sonucu parca bitisinden PROC_SEC sonra gelir; kilitli eslesme (matched) ekrani eslesmenin
son ayetine tasir. AyahStepper gibi: ayni surede en fazla 7 ayetlik ileri atlamada aradaki ayetler de gosterilmis sayilir.

Ayet "takip edildi": okunmaya basladigi andan bitisinin TAIL_SEC sonrasina kadar ekranda (ya da adimlanarak) gosterildi.
Gecikme: ayetin baslangicindan ekrana gelisine. Yanlis gosterim: ekranda o an okunan / az once okunan sure disinda bir
sure (kilitli) varken gecen parca sayisi.
"""
import statistics

from . import env

TAIL_SEC = 4.0
MAX_STEP = 7


def displayed_timeline(chunks, results):
    """→ [(sn, sure, ayet_bas, ayet_son)] ekranda gosterilen (kilitli) konum degisimleri; ayet araligi adimlanan ayetler."""
    out = []
    last = None
    for k, r in enumerate(results):
        if r["status"] != "matched":
            continue
        t = env.chunk_time(chunks[k], k) + env.ev.PROC_SEC
        s, a = r["last_surah"], r["last_ayah"]
        fs, fa = r["first_surah"], r["first_ayah"]
        lo = fa if fs == s else 1
        if last and last[0] == s and 0 < lo - last[1] <= MAX_STEP + 1:
            lo = last[1] + 1           # aradaki ayetler sirayla gosterilir (AyahStepper)
        out.append((t, s, min(lo, a), a))
        last = (s, a)
    return out


def score_file(chunks, info, mod=None):
    """info: manifest girdisi (ayahs, timeline) → {ayahs, followed, latency_median, wrong_shown}"""
    results = env.run_sm(chunks, mod)
    disp = displayed_timeline(chunks, results)
    lat, followed = [], 0
    for t0, t1, s, a in info["ayahs"]:
        hit = next((t for t, ds, lo, hi in disp if ds == s and lo <= a <= hi and t0 <= t <= t1 + TAIL_SEC), None)
        if hit is not None:
            followed += 1
            lat.append(hit - t0)
    # yanlis gosterim: kilitli konumun suresi o an okunan / onceki bolumde degil
    tl = info.get("timeline") or []
    wrong = 0
    for t, ds, lo, hi in disp:
        cur = prev = None
        for st, su in tl:
            if t - env.ev.PROC_SEC >= st:
                prev, cur = cur, su
        if ds not in (cur, prev):
            wrong += 1
    return {"ayahs": len(info["ayahs"]), "followed": followed,
            "latency_median": round(statistics.median(lat), 2) if lat else None,
            "latency_mean": round(statistics.mean(lat), 2) if lat else None, "wrong_shown": wrong}


def summarize(per):
    n = sum(r["ayahs"] for r in per.values())
    f = sum(r["followed"] for r in per.values())
    lats = [r["latency_median"] for r in per.values() if r["latency_median"] is not None]
    return {"ayahs": n, "ayah_followed": f, "ayah_follow_pct": round(100.0 * f / n, 1) if n else 0.0,
            "ayah_latency_median": round(statistics.median(lats), 2) if lats else 0.0,
            "ayah_wrong_shown": sum(r["wrong_shown"] for r in per.values())}
