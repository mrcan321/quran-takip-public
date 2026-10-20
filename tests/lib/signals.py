"""Namaz sinyali (kamet / selam / rukû) taramasi: tum transkriptlerde (RNNT + CTC metni) namaz_signal.

Yanlis alarm = Kuran okunan bir bolumde (TIMELINE'da sure olan an) ya da namaz disi kayitta sinyal. Kamet / selam /
semiallah kaliplari "Kuran'da yok" diye secildi; bu tarama yeni bir kalip eklenince Kuran okumasina carpmadigini
her kayitta kontrol eder. Namaz kayitlarinda Kuran disi anlarda yakalanan sinyaller de sayilir (azalirsa kacirma).
"""
from . import env

ev = env.ev


def scan(T_all):
    """T_all: {config: {dosya: parcalar}} → (ozet, ayrintilar)"""
    false_alarm, detected = 0, {"kamet": 0, "selam": 0, "ruku": 0}
    ezan = 0
    details = []
    texts = 0
    for cfg, recs in sorted(T_all.items()):
        for fn, chunks in sorted(recs.items()):
            tl = ev.timeline_for(fn)
            exp = ev.EXPECTED.get(fn, "?")
            for k, c in enumerate(chunks):
                t = env.chunk_time(c, k)
                for src, text in (("rnnt", c[1]), ("ctc", c[5])):
                    if not text:
                        continue
                    texts += 1
                    sig = env.sm.namaz_signal(text)
                    if not sig:
                        continue
                    if env.MANIFESTS.get(fn, {}).get("kind") == "ezan":
                        # ezan kaydi (dis kaynak): ezan cumlesi kamet sinyali olarak beklenir, selam / rukû olmamali
                        if sig == "kamet":
                            ezan += 1
                            continue
                        bad = True
                    elif exp != "coklu":
                        # tek sureli / Kuran disi kayitta namaz sinyali olmamali
                        bad = True
                    elif tl:
                        cur = None
                        for st, su in tl:
                            if t - 2.5 >= st:   # parcanin ortasi
                                cur = su
                        bad = cur is not None
                    else:
                        bad = False
                    if bad:
                        false_alarm += 1
                        details.append(f"YANLIS ALARM {cfg} {fn} #{k} t={t:.1f} {src} {sig}: {text}")
                    else:
                        detected[sig] += 1
    return {"signal_false_alarms": false_alarm, "kamet_detected": detected["kamet"],
            "selam_detected": detected["selam"], "ruku_detected": detected["ruku"], "ezan_detected": ezan,
            "texts_scanned": texts}, details
