"""Kayit kumesi metrikleri (eval_pipeline ile ayni tanimlar): ilk kilit, sure bolumu basina kilit gecikmesi,
yanlis kilitli parca, ekranda gorunen yanlis aday."""
import statistics

from . import env

ev = env.ev


def segment_at(timeline, t):
    cur = prev = None
    for st, su in timeline:
        if t >= st:
            prev, cur = cur, su
    return cur, prev


def shown_wrong_candidates(results, chunks, timeline):
    """Ekranda gorunen yanlis aday: BEKLEME / kilit kaybi adayi (kilitliyken gecis adayi ve belirsiz aday gosterilmez)."""
    n = 0
    for k, r in enumerate(results):
        if r["status"] == "pending" and not r.get("jump") and not r.get("ambiguous"):
            if r.get("pending_surah") not in segment_at(timeline, env.chunk_time(chunks[k], k) - 1.0):
                n += 1
    return n


def evaluate_recording(fn, chunks, timeline, expected=None, mod=None):
    """Tek kayit → {first: (sure, sn) | None, segs: [(bas, sure, kilit, aday)], wrong, shown_wrong}"""
    mod = mod or env.sm
    results = env.run_sm(chunks, mod, fn)
    first = None
    for k, r in enumerate(results):
        if r["status"] == "matched":
            first = (r["first_surah"], round(env.chunk_time(chunks[k], k), 1))
            break
    out = {"first": first, "expected": expected, "segs": [], "wrong": 0, "shown_wrong": 0,
           "trace": " ".join(env.decision_cell(k, r) for k, r in enumerate(results))}
    if timeline:
        segs, wrong, _trace, _adv = ev.track_file(mod, chunks, env.corpus(), env.aux(), timeline, fn=fn)
        out["segs"] = [(st, su, None if lk is None else round(lk, 1), None if cd is None else round(cd, 1))
                       for st, su, lk, cd in segs]
        out["wrong"] = wrong
        out["shown_wrong"] = shown_wrong_candidates(results, chunks, timeline)
    return out


def summarize(per_file):
    """Kayit sonuclari → toplam metrikler (baseline ile karsilastirilan)."""
    ok = wrong1 = none = 0
    t1, delays, shows = [], [], []
    segs_n = locked = wrong = shown = 0
    for fn, r in per_file.items():
        exp = r["expected"]
        if isinstance(exp, int):
            if r["first"] is None:
                none += 1
            elif r["first"][0] == exp:
                ok += 1
                t1.append(r["first"][1])
            else:
                wrong1 += 1
        elif exp is None and r["first"] is not None:
            wrong1 += 1      # Kuran disi kayit kilitlendi
        for st, su, lk, cd in r["segs"]:
            segs_n += 1
            if lk is not None:
                locked += 1
                delays.append(lk)
            if cd is not None:
                shows.append(cd)
        wrong += r["wrong"]
        shown += r["shown_wrong"]
    return {
        "first_ok": ok, "first_wrong": wrong1, "first_none": none,
        "first_median": round(statistics.median(t1), 1) if t1 else 0.0,
        "first_mean": round(statistics.mean(t1), 2) if t1 else 0.0,
        "sections": segs_n, "sections_locked": locked,
        "delay_median": round(statistics.median(delays), 2) if delays else 0.0,
        "delay_mean": round(statistics.mean(delays), 2) if delays else 0.0,
        "wrong_chunks": wrong, "shown_wrong": shown,
        # Dogru surenin ekranda ilk gorunmesi (kilit ya da gorunen aday; belirsiz / gecis adayi gorunmez)
        "show_delay_median": round(statistics.median(shows), 2) if shows else 0.0,
        "show_delay_mean": round(statistics.mean(shows), 2) if shows else 0.0,
    }


def evaluate_set(recs, timeline_of=None, expected_of=None, mod=None):
    """recs: {dosya: chunks} → ({dosya: sonuc}, toplam)"""
    timeline_of = timeline_of or ev.timeline_for
    expected_of = expected_of or (lambda fn: ev.EXPECTED.get(fn, "?"))
    per = {fn: evaluate_recording(fn, ch, timeline_of(fn), expected_of(fn), mod) for fn, ch in sorted(recs.items())}
    return per, summarize(per)
