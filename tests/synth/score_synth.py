#!/usr/bin/env python3
"""Sentetik kayitlarin (build_synth.py) eval transkriptlerini ayet duzeyinde ve sure bolumu duzeyinde olc.

  python tests/synth/score_synth.py --trjson synth.trjson --manifest synth/manifest.json [--summary $GITHUB_STEP_SUMMARY]

Kotlin RakatTracker ile rekat / namaz sayisi da (tests/jvm derliyse) manifest'teki beklenenle karsilastirilir.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import ayah, env, metrics  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trjson", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--summary", type=Path)
    ap.add_argument("--assets", help="quran.bin (asr/ altinda) — verilirse Kotlin RakatTracker ile rekat sayilir")
    args = ap.parse_args()
    man = json.loads(args.manifest.read_text(encoding="utf-8"))["files"]
    for fn, m in man.items():
        env.ev.EXPECTED[fn] = "coklu"
        env.ev.TIMELINE[fn] = [(float(t), su) for t, su in m["timeline"]]
    T = env.load_trjson([args.trjson])
    rk = {}
    if args.assets:
        from lib import kotlin
        kotlin.ensure_built()
        rk = kotlin.events("rakat", args.assets, args.trjson)
    lines = ["## Sentetik namaz / teravih (EveryAyah + cami sesleri)", "",
             "| zincir | kayit | ayet takip | ayet gecikme (medyan) | yanlis gosterim | bolum kilit | bolum gecikme (medyan) "
             "| yanlis kilitli parca | rekat / namaz |", "|---|---|---|---|---|---|---|---|---|"]
    totals = {}
    for cfg in sorted(T):
        per = {}
        for fn, chunks in sorted(T[cfg].items()):
            if fn not in man:
                continue
            a = ayah.score_file(chunks, man[fn])
            r = metrics.evaluate_recording(fn, chunks, env.ev.TIMELINE[fn], "coklu")
            s = metrics.summarize({fn: r})
            per[fn] = a
            last = rk.get((cfg, fn), [""])[-1]
            got = dict(x.split("=") for x in last.split()[1:]) if last.startswith("son") else {}
            rek = f"{got.get('toplam', '?')}/{man[fn]['rakats']} · {got.get('namaz', '?')}/{man[fn]['namaz']}" if got else "-"
            lines.append(f"| {cfg} | {fn} | {a['followed']}/{a['ayahs']} | {a['latency_median']} | {a['wrong_shown']} | "
                         f"{s['sections_locked']}/{s['sections']} | {s['delay_median']} | {s['wrong_chunks']} | {rek} |")
        totals[cfg] = ayah.summarize(per)
    lines += ["", "| zincir | ayet takip % | ayet gecikme medyani | yanlis gosterim |", "|---|---|---|---|"]
    for cfg, t in totals.items():
        lines.append(f"| {cfg} | {t['ayah_follow_pct']} ({t['ayah_followed']}/{t['ayahs']}) | {t['ayah_latency_median']} | "
                     f"{t['ayah_wrong_shown']} |")
    text = "\n".join(lines) + "\n"
    print(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(text)
    env.save_cache()


if __name__ == "__main__":
    main()
