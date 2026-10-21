#!/usr/bin/env python3
"""APK oncesi test kapisi — her kod degisikliginden sonra, APK derlenmeden once (android.yml) ve yerelde.

Gercek kayitlarin ASR transkriptleri (tests/trjson/*.trjson, CI eval'den) ASR'siz tekrar oynatilir; tum metrikler
tests/baseline.json ile karsilastirilir. Herhangi bir metrik kotulesirse ya da birebirlik kontrolu tutmazsa cikis 1.

Kumeler (--suites, virgulle; varsayilan hepsi):
  replay   35+ gercek kayit (iki zincir: rnnt sabit 5 sn, rnnt-hibrit): ilk kilit, takip gecikmesi, yanlis kilit / aday
  stress   S1-S5 zorlama: kamet + namaz, kamet + Fatiha'siz sure, hutbe + kamet + namaz, %15 gurultu, sahte tekbir
  compose  teravih 20 rekat (tesbih/salavat aralariyla), hatimle teravih, 4 rekatli namaz — takip + rekat sayaci
  external dis kaynak gercek kayitlar (tests/trjson/external: Harem teravihleri, Turk kari, ezan koleksiyonu; CI'da
           indirilip gercek ASR'den gecmis transkriptler): ilk kilit, takip, yanlis kilit / aday, ezan sinyali,
           EzanTracker penceresi (ezan kayitlarinda acilmali, Kuran kayitlarinda acilmamali)
  synth    sentetik namaz / teravih / hatim (tests/trjson/synth, EveryAyah + cami sesleri, gercek ASR transkripti):
           ayet takibi (ayet sinirlari kesin), ayet gecikmesi, yanlis gosterim, bolum kilidi; rekat / namaz sayisi kotlin'de
  signals  kamet / selam / semiallah kaliplari: Kuran okunan anlarda yanlis alarm 0, yakalanan sinyal sayisi
  app      server/app.py = referans state machine (parca parca)
  kotlin   uygulamanin Kotlin kodu (tests/jvm): Fuzzy/Aligner/StateMachine fixture'lari, Kotlin = Python karar izi
           (gercek kayitlar + bilesik senaryolar), RakatTracker/EzanTracker altin dosyalari, ChunkBuilder = vad_chunker,
           WavReader = soundfile, G2 gozluk koprusu (GlassesBridge: JSON, uzun yoklama, dosyalar, CORS)
  glasses  sadece G2 gozluk koprusu + secilebilir mealler (JvmTests glasses / meals; kotlin kumesinin parcasi) — tanima kodu
           degismeden G2 / meal degisince
           (tests.yml kapsam)
  g2       G2 gozluk eklentisinin ekran duzeni (assets/g2/layout.js, node --test): satir kirma, sayfalar, kutu boyutlari;
           <assets>/asr/meal.bin varsa tum mealler (satir / bayt siniri, fontta olmayan karakter sayisi). Simulator
           denemesi ayri: tests/g2/sim_check.py (tests.yml g2sim)

Kullanim:
  python tests/gate.py --assets android-assets-staged          # hepsi
  python tests/gate.py --suites replay,signals --seeds 2       # hizli
  python tests/gate.py --update-baseline                        # bilerek yapilan iyilestirmeden sonra
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import env  # noqa: E402
from lib import ayah, compose, metrics, signals  # noqa: E402

HIGHER_BETTER = ("first_ok", "sections_locked", "kamet_detected", "selam_detected", "ruku_detected", "passed",
                 "ayah_followed", "ezan_detected", "ezan_opened", "meal_editions")
LOWER_BETTER = ("first_wrong", "first_none", "wrong_chunks", "shown_wrong", "signal_false_alarms", "rakat_errors",
                "namaz_errors", "delay_median", "delay_mean", "first_median", "first_mean", "ayah_latency_median",
                "ayah_wrong_shown", "ezan_false_opened", "zikir_false_alarms", "dropped_chars", "hide_false",
                "hide_latency_median", "hide_latency_max", "hide_missing")
HARD_ZERO = ("app_diffs", "kotlin_trace_diffs", "chunk_diffs", "wav_diffs", "golden_diffs", "fixture_failures",
             "glasses_failures", "g2_failures", "meals_failures")


def direction(key):
    if key in HARD_ZERO:
        return "zero"
    if key.endswith(HIGHER_BETTER):
        return "up"
    if key.endswith(LOWER_BETTER):
        return "down"
    return "info"


def flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out[key] = v
    return out


def compare(results, baseline):
    """→ (satirlar, kotulesen, iyilesen)"""
    cur, base = flatten(results), flatten(baseline)
    rows, worse, better = [], [], []
    for key in sorted(cur):
        v, b, dr = cur[key], base.get(key), direction(key.rsplit(".", 1)[-1])
        if dr == "info":
            continue
        if dr == "zero":
            st = "✅" if v == 0 else "❌"
            if v != 0:
                worse.append(key)
        elif b is None:
            st = "yeni"
        elif (dr == "up" and v < b - 1e-9) or (dr == "down" and v > b + 1e-9):
            st = "❌ kotulesti"
            worse.append(key)
        elif (dr == "up" and v > b + 1e-9) or (dr == "down" and v < b - 1e-9):
            st = "⬆ iyilesti"
            better.append(key)
        else:
            st = "="
        rows.append((key, b, v, st))
    return rows, worse, better


def merge_into(base, results):
    for k, v in results.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merge_into(base[k], v)
        else:
            base[k] = v
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suites", default="replay,stress,compose,external,synth,signals,app,kotlin,g2")
    ap.add_argument("--seeds", type=int, default=5, help="S4/S5 gurultu tohum sayisi")
    ap.add_argument("--assets", default=str(env.REPO / "android-assets-staged"),
                    help="quran.bin + fixture'lar (asr/ altinda) — Kotlin kumesi icin")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--summary", help="Markdown rapor (GITHUB_STEP_SUMMARY)")
    ap.add_argument("--results", help="Sonuclari JSON olarak yaz")
    ap.add_argument("--offline", action="store_true", help="JVM derlemesi icin gradle --offline")
    args = ap.parse_args()
    suites = [s for s in args.suites.split(",") if s]

    t0 = time.time()
    T_all = env.load_trjson()
    T = {cfg: T_all.get(cfg, {}) for cfg in env.CONFIGS}
    print(f"TRJSON: " + ", ".join(f"{cfg} {len(T[cfg])} kayit" for cfg in env.CONFIGS), flush=True)
    results, notes, hard = {}, [], []
    compositions = {}

    if "replay" in suites:
        results["replay"] = {}
        for cfg in env.CONFIGS:
            per, summ = metrics.evaluate_set(T[cfg])
            results["replay"][cfg] = summ
            slow = sorted(((lk, fn, su) for fn, r in per.items() for _, su, lk, _ in r["segs"] if lk is not None),
                          reverse=True)[:5]
            notes.append(f"replay {cfg}: en yavas bolumler " + ", ".join(f"{fn} {su}: {lk:.0f} sn" for lk, fn, su in slow))
            print(f"[replay {cfg}] {summ}  ({time.time() - t0:.0f} sn)", flush=True)

    if "stress" in suites:
        results["stress"] = {}
        for cfg in env.CONFIGS:
            results["stress"][cfg] = {}
            for name, cases in compose.stress_scenarios(T[cfg], args.seeds):
                per = {cn: metrics.evaluate_recording(cn, ch, tl, "coklu") for cn, ch, tl in cases}
                s = metrics.summarize(per)
                key = name.split()[0]
                results["stress"][cfg][key] = {k: s[k] for k in ("sections", "sections_locked", "delay_median",
                                                                 "delay_mean", "wrong_chunks", "shown_wrong")}
                print(f"[stress {cfg}] {name}: {results['stress'][cfg][key]}  ({time.time() - t0:.0f} sn)", flush=True)

    if "compose" in suites or "kotlin" in suites:
        for cfg in env.CONFIGS:
            compositions[cfg] = compose.teravih_compositions(T[cfg])

    if "compose" in suites:
        results["compose"] = {}
        for cfg in env.CONFIGS:
            results["compose"][cfg] = {}
            for name, ch, tl, exp_rakat, exp_namaz in compositions[cfg]:
                r = metrics.evaluate_recording(name, ch, tl, "coklu")
                s = metrics.summarize({name: r})
                key = name.split()[0] + ("_" + name.split()[1] if name.split()[0].isdigit() else "")
                results["compose"][cfg][key] = {k: s[k] for k in ("sections", "sections_locked", "delay_median",
                                                                  "delay_mean", "wrong_chunks", "shown_wrong")}
                print(f"[compose {cfg}] {name}: {results['compose'][cfg][key]}", flush=True)

    E = env.load_external() if ("external" in suites or "kotlin" in suites or "app" in suites) else {}
    if "external" in suites and E:
        results["external"] = {}
        for cfg in env.CONFIGS:
            per, summ = metrics.evaluate_set(E.get(cfg, {}))
            results["external"][cfg] = summ
            bad = [f"{fn} {r['trace']}" for fn, r in per.items() if r["wrong"] or r["shown_wrong"]
                   or (r["expected"] is None and r["first"] is not None)]
            notes += [f"external {cfg} yanlis kilit / aday: {b[:300]}" for b in bad[:6]]
            print(f"[external {cfg}] {summ}  ({time.time() - t0:.0f} sn)", flush=True)
        es, edet = signals.scan(E)
        results["external"]["signals"] = es
        notes += [f"external: {d}" for d in edet[:5]]
        print(f"[external signals] {es}", flush=True)

    S = env.load_synth() if ("synth" in suites or "kotlin" in suites) else {}
    if "synth" in suites and S:
        results["synth"] = {}
        for cfg in env.CONFIGS:
            per_a, per_r = {}, {}
            for fn, ch in sorted(S.get(cfg, {}).items()):
                info = env.MANIFESTS.get(fn)
                if not info:
                    continue
                per_a[fn] = ayah.score_file(ch, info)
                per_r[fn] = metrics.evaluate_recording(fn, ch, env.ev.timeline_for(fn), "coklu")
            sa, sr = ayah.summarize(per_a), metrics.summarize(per_r)
            results["synth"][cfg] = {**{k: sa[k] for k in ("ayahs", "ayah_followed", "ayah_follow_pct",
                                                           "ayah_latency_median", "ayah_wrong_shown")},
                                     **{k: sr[k] for k in ("sections", "sections_locked", "delay_median", "wrong_chunks")}}
            print(f"[synth {cfg}] {results['synth'][cfg]}  ({time.time() - t0:.0f} sn)", flush=True)

    if "signals" in suites:
        summ, det = signals.scan(T_all)
        results["signals"] = summ
        notes += det[:10]
        print(f"[signals] {summ}", flush=True)

    if "app" in suites:
        from lib import app_parity
        diffs, n, ex = app_parity.compare([T[cfg] for cfg in env.CONFIGS] + [E.get(cfg, {}) for cfg in env.CONFIGS])
        results["app"] = {"app_diffs": diffs, "chunks": n}
        notes += [f"app.py fark: {e}" for e in ex]
        print(f"[app] {n} parca, fark {diffs}", flush=True)

    if "kotlin" in suites:
        from lib import kotlin
        kotlin.ensure_built(offline=args.offline)
        fx, _log = kotlin.fixtures(args.assets)
        results["kotlin"] = {
            "fuzzy_passed": fx["fuzzy"]["passed"], "fuzzy_total": fx["fuzzy"]["total"],
            "aligner_passed": fx["aligner"]["passed"], "aligner_total": fx["aligner"]["total"],
            "state_machine_passed": fx["state_machine"]["passed"], "state_machine_total": fx["state_machine"]["total"],
            "fixture_failures": (fx["fuzzy"]["total"] - fx["fuzzy"]["passed"])
                                + (fx["state_machine"]["total"] - fx["state_machine"]["passed"]),
        }
        notes += [f"StateMachine fixture: {f}" for f in fx["state_machine"]["failures"][:5]]
        # Kotlin = Python karar izi: gercek kayitlar + bilesik senaryolar (teravih, zorlama S1/S3)
        recs = {cfg: dict(T[cfg]) for cfg in env.CONFIGS}
        for cfg in env.CONFIGS:
            for fn, ch in S.get(cfg, {}).items():
                recs[cfg][f"sentetik: {fn}"] = ch
            for fn, ch in E.get(cfg, {}).items():
                recs[cfg][f"dis: {fn}"] = ch
        for cfg in env.CONFIGS:
            for name, ch, tl, *_ in compositions.get(cfg, []):
                recs[cfg][f"bilesik: {name}"] = ch
            for sname, cases in compose.stress_scenarios(T[cfg], 1):
                if sname.startswith(("S1", "S3")):
                    for cn, ch, tl in cases:
                        recs[cfg][f"{sname.split()[0]}: {cn}"] = ch
        d, n, ex = kotlin.trace_parity(args.assets, recs)
        results["kotlin"]["kotlin_trace_diffs"] = d
        results["kotlin"]["kotlin_trace_recordings"] = n
        notes += [f"Kotlin/Python iz farki: {e}" for e in ex]
        print(f"[kotlin] fixture {fx}  iz: {n} kayit, fark {d}", flush=True)
        # RakatTracker / EzanTracker: gercek kayitlarda altin dosya; bilesimlerde beklenen rekat / namaz sayisi
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "real.trjson"
            env.write_trjson(p, T)
            golden_diffs = 0
            for kind in ("rakat", "ezan", "zikir"):
                txt = kotlin.events_text(kotlin.events(kind, args.assets, p))
                gp = env.GOLDEN / f"{kind}.tsv"
                if args.update_baseline:
                    gp.parent.mkdir(parents=True, exist_ok=True)
                    gp.write_text(txt, encoding="utf-8")
                elif not gp.exists() or gp.read_text(encoding="utf-8") != txt:
                    golden_diffs += 1
                    old = gp.read_text(encoding="utf-8").splitlines() if gp.exists() else []
                    new = txt.splitlines()
                    import difflib
                    notes += [f"{kind} altin dosya farki: {l}" for l in
                              list(difflib.unified_diff(old, new, lineterm="", n=0))[2:12]]
            # EzanTracker dis kaynak kayitlarda: ezan kayitlarinda pencere acilmali, Kuran kayitlarinda acilmamali
            if E:
                pe = Path(td) / "ext.trjson"
                env.write_trjson(pe, {cfg: E.get(cfg, {}) for cfg in env.CONFIGS})
                ez = kotlin.events("ezan", args.assets, pe)
                opened = false_opened = 0
                for cfg in env.CONFIGS:
                    for fn in sorted(E.get(cfg, {})):
                        is_open = any(" OPEN " in line for line in ez.get((cfg, fn), []))
                        if env.MANIFESTS.get(fn, {}).get("kind") == "ezan":
                            opened += is_open
                            notes.append(f"ezan {cfg} {fn}: " + ("; ".join(ez.get((cfg, fn), [])[:4]) or "pencere acilmadi"))
                        elif is_open:
                            false_opened += 1
                            notes.append(f"ezan penceresi Kuran kaydinda acildi: {cfg} {fn}")
                results["kotlin"]["ext_ezan_opened"] = opened
                results["kotlin"]["ext_ezan_false_opened"] = false_opened
                # Teravih rekati kayitlari (manifest "rakat" / "namaz"): RakatTracker'in son durumu
                rk_e = kotlin.events("rakat", args.assets, pe)
                ext_rerr = 0
                for cfg in env.CONFIGS:
                    for fn in sorted(E.get(cfg, {})):
                        info = env.MANIFESTS.get(fn, {})
                        if "rakat" not in info:
                            continue
                        last = rk_e.get((cfg, fn), [""])[-1]
                        got = dict(x.split("=") for x in last.split()[1:]) if last.startswith("son") else {}
                        rk, nam = int(got.get("rekat", 0)), int(got.get("namaz", 0))
                        ext_rerr += abs(rk - info["rakat"]) + abs(nam - info["namaz"])
                        if rk != info["rakat"] or nam != info["namaz"]:
                            notes.append(f"rekat {cfg} {fn}: {rk}/{info['rakat']} rekat, {nam}/{info['namaz']} namaz — "
                                         + "; ".join(rk_e.get((cfg, fn), [])[:6]))
                results["kotlin"]["ext_rakat_errors"] = ext_rerr
            # Zikir karti (ZikirTracker): Kuran okunan anda ya da tek sureli / Kuran disi kayitta kart cikmamali
            pz = Path(td) / "zikir.trjson"
            zrecs = {cfg: {**T.get(cfg, {}), **E.get(cfg, {}), **S.get(cfg, {})} for cfg in env.CONFIGS}
            env.write_trjson(pz, zrecs)
            zk = kotlin.events("zikir", args.assets, pz)
            zfalse = zshown = 0
            for (cfg, fn), lines in sorted(zk.items()):
                tl = env.ev.timeline_for(fn) or []
                exp = env.ev.EXPECTED.get(fn)
                for line in lines:
                    if line.endswith(" ezan"):
                        continue                     # ezan/kamet penceresi acik: UI gostermez
                    t = float(line.split()[0])
                    zshown += 1
                    in_quran = any(su is not None and st <= t - 2.5 and t + 1 < (tl[i + 1][0] if i + 1 < len(tl) else 1e9)
                                   for i, (st, su) in enumerate(tl))
                    if in_quran or isinstance(exp, int):
                        zfalse += 1
                        notes.append(f"zikir karti Kuran okunurken: {cfg} {fn} {line}")
            results["kotlin"]["zikir_false_alarms"] = zfalse
            results["kotlin"]["zikir_shown"] = zshown
            # Ses kesilince metni kaldirma (VoiceActivity + TextHold, 3 sn): cok sureli gercek namaz / okuma kayitlarinda
            # (TIMELINE) okuma icinde silme olmamali; okuma bitince (rukû / secde) metin kac sn'de kalkiyor
            ph = Path(td) / "hide.trjson"
            env.write_trjson(ph, {"rnnt-hibrit": {fn: ch for fn, ch in T.get("rnnt-hibrit", {}).items()
                                                  if fn in env.ev.TIMELINE}})
            hd = kotlin.events_hide(args.assets, ph, env.REPO / "data")
            hfalse = hmiss = 0
            hlat = []
            for (cfg, fn), lines in sorted(hd.items()):
                tl = env.ev.TIMELINE[fn]
                hides = [float(x.split()[1]) for x in lines if x.startswith("HIDE")]
                shows = [(float(x.split()[1]), int(x.split()[2])) for x in lines if x.startswith("SHOW")]

                def shown_surah(h):
                    prev = [s for t, s in shows if t <= h]
                    return prev[-1] if prev else None
                for i, (t0, su) in enumerate(tl):
                    t1 = tl[i + 1][0] if i + 1 < len(tl) else 1e9
                    if su is not None:
                        # yanlis silme: o an okunan surenin metni kalkti (eski sureninki kalkarsa dogru)
                        bad = [h for h in hides if t0 + 3 < h < t1 - 1 and shown_surah(h) == su]
                        hfalse += len(bad)
                        notes += [f"metin okuma icinde kalkti: {fn} {su} @ {h:.1f}" for h in bad]
                    elif i > 0 and tl[i - 1][1] is not None:
                        after = [h for h in hides if t0 - 1 <= h < t1]
                        if after:
                            hlat.append(round(after[0] - t0, 1))
                        else:
                            hmiss += 1
                            notes.append(f"metin okuma bitince kalkmadi: {fn} @ {t0}")
            results["kotlin"]["hide_false"] = hfalse
            results["kotlin"]["hide_missing"] = hmiss
            results["kotlin"]["hide_latency_median"] = round(float(sorted(hlat)[len(hlat) // 2]), 1) if hlat else None
            results["kotlin"]["hide_latency_max"] = max(hlat) if hlat else None
            print(f"[kotlin] ses kesilince metin: okuma icinde {hfalse}, bitis → silme {hlat}, kalkmayan {hmiss}", flush=True)
            results["kotlin"]["golden_diffs"] = golden_diffs
            pc = Path(td) / "comp.trjson"
            env.write_trjson(pc, {cfg: {name: ch for name, ch, *_ in compositions.get(cfg, [])} for cfg in env.CONFIGS})
            rk = kotlin.events("rakat", args.assets, pc)
            rerr = nerr = 0
            for cfg in env.CONFIGS:
                for name, ch, tl, exp_rakat, exp_namaz in compositions.get(cfg, []):
                    last = rk.get((cfg, name), [""])[-1]
                    got = dict(x.split("=") for x in last.split()[1:]) if last.startswith("son") else {}
                    tot, nam = int(got.get("toplam", 0)), int(got.get("namaz", 0))
                    rerr += abs(tot - exp_rakat)
                    nerr += abs(nam - exp_namaz)
                    notes.append(f"rekat {cfg} {name}: sayilan {tot}/{exp_rakat} rekat, {nam}/{exp_namaz} namaz")
            results["kotlin"]["rakat_errors"] = rerr
            results["kotlin"]["namaz_errors"] = nerr
            # Sentetik namaz / teravih: manifest'teki beklenen rekat / namaz sayisi
            if S:
                ps = Path(td) / "synth.trjson"
                env.write_trjson(ps, {cfg: S.get(cfg, {}) for cfg in env.CONFIGS})
                rs = kotlin.events("rakat", args.assets, ps)
                srerr = snerr = 0
                for cfg in env.CONFIGS:
                    for fn in sorted(S.get(cfg, {})):
                        info = env.MANIFESTS.get(fn)
                        if not info:
                            continue
                        last = rs.get((cfg, fn), [""])[-1]
                        got = dict(x.split("=") for x in last.split()[1:]) if last.startswith("son") else {}
                        tot, nam = int(got.get("toplam", 0)), int(got.get("namaz", 0))
                        srerr += abs(tot - info["rakats"])
                        snerr += abs(nam - info["namaz"])
                        notes.append(f"rekat {cfg} {fn}: sayilan {tot}/{info['rakats']} rekat, {nam}/{info['namaz']} namaz")
                results["kotlin"]["synth_rakat_errors"] = srerr
                results["kotlin"]["synth_namaz_errors"] = snerr
        wavs = sorted(str(p) for p in (env.REPO / "data").glob("*.wav")) + \
            sorted(str(p) for p in (env.REPO / "server" / "recordings").glob("*.wav"))
        cp = kotlin.chunk_parity(wavs)
        results["kotlin"].update({k: v for k, v in cp.items() if not k.endswith("examples")})
        notes += [f"ChunkBuilder farki: {e}" for e in cp["chunk_examples"]] + [f"WavReader farki: {e}" for e in cp["wav_examples"]]
        print(f"[kotlin] golden fark {golden_diffs}, rekat hata {rerr}, namaz hata {nerr}, chunk {cp['chunk_diffs']}/{cp['chunk_cases']}, "
              f"wav {cp['wav_diffs']}/{cp['wav_cases']}", flush=True)
        gl, gfails = kotlin.glasses()
        results["kotlin"].update(gl)
        notes += [f"G2 koprusu: {f}" for f in gfails]
        print(f"[kotlin] G2 koprusu {gl['glasses_passed']}/{gl['glasses_total']}", flush=True)
        ml, mfails = kotlin.meals(Path(args.assets) / "asr")
        results["kotlin"].update(ml)
        notes += [f"mealler: {f}" for f in mfails]
        print(f"[kotlin] mealler {ml.get('meals_passed')}/{ml.get('meals_total')}", flush=True)

    if "glasses" in suites and "kotlin" not in suites:
        from lib import kotlin
        kotlin.ensure_built(offline=args.offline)
        gl, gfails = kotlin.glasses()
        results.setdefault("kotlin", {}).update(gl)
        notes += [f"G2 koprusu: {f}" for f in gfails]
        print(f"[glasses] G2 koprusu {gl['glasses_passed']}/{gl['glasses_total']}", flush=True)
        ml, mfails = kotlin.meals(Path(args.assets) / "asr")
        results["kotlin"].update(ml)
        notes += [f"mealler: {f}" for f in mfails]
        print(f"[glasses] mealler {ml.get('meals_passed')}/{ml.get('meals_total')}", flush=True)

    if "g2" in suites:
        from lib import g2
        r, gnotes = g2.layout_tests(Path(args.assets) / "asr" / "meal.bin")
        results["g2"] = r
        notes += gnotes
        print(f"[g2] {r}", flush=True)

    env.save_cache()
    baseline = json.loads(env.BASELINE.read_text(encoding="utf-8")) if env.BASELINE.exists() else {}
    rows, worse, better = compare(results, baseline)
    if args.update_baseline:
        env.BASELINE.write_text(json.dumps(merge_into(baseline, results), indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
        hard_fail = [k for k in worse if direction(k.rsplit(".", 1)[-1]) == "zero"]
        print(f"baseline guncellendi: {env.BASELINE}" + (f" (sifir olmasi gerekenler: {hard_fail})" if hard_fail else ""))
        worse = hard_fail

    lines = ["## Test kapisi", "", f"Sure: {time.time() - t0:.0f} sn · kumeler: {', '.join(suites)}", "",
             "| metrik | baseline | simdi | durum |", "|---|---|---|---|"]
    lines += [f"| {k} | {'-' if b is None else b} | {v} | {st} |" for k, b, v, st in rows]
    lines += ["", f"**{'GECTI' if not worse else 'KALDI'}** — kotulesen: {len(worse)}, iyilesen: {len(better)}"]
    if better and not args.update_baseline:
        lines.append("Iyilesme var: bilerek yapildiysa `python tests/gate.py --update-baseline` ile baseline'i guncelle.")
    if notes:
        lines += ["", "<details><summary>Notlar</summary>", "", *[f"- {n}" for n in notes], "", "</details>"]
    text = "\n".join(lines) + "\n"
    print(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(text)
    if args.results:
        Path(args.results).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if worse else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        env.save_cache()   # bir kume hata verse de hizalama onbellegi kaybolmasin (yerelde tekrar dakikalar suruyor)
