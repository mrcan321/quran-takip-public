#!/usr/bin/env python3
"""Parametre ayari denemesi: her senaryo tek bir parametreyi degistirir, test kapisinin Python kumeleri (gercek kayitlar,
zorlama, bilesik, dis kaynak, sentetik) sifirdan kosar; sonuclar bugunku ayarla (grubun temel senaryosu) kiyaslanir.

  python tests/tune.py list --group A,B                          # senaryolar (CI matrisi icin json)
  python tests/tune.py asr --group B --only B1-6 --out OUT --model-dir model   # ses senaryosu: kayitlari yeniden tani
  python tests/tune.py run --group A --only A1-45 --out OUT       # senaryo(lar)i kos (biteni atlar)
  python tests/tune.py report --out OUT > rapor.md                # kiyas tablosu + kayit kayit kotulesen / iyilesen

A (kilit kararlari): TILAVET_SM_PARAMS (tests/lib/env.py) — kayitli transkriptler tekrar oynatilir.
B (ses / ASR): TILAVET_ASR_PARAMS (scripts/eval_pipeline.py) — kendi kayitlarimiz (data/ + server/recordings) gercek modelle
yeniden taninir (hibrit zincir), sonra ayni kumeler TILAVET_TRJSON_DIR ile. Temeli "B-base" (bugunku ayarlarla yeniden tanima).
Guvenlik olculeri (yanlis kilitli parca, ekranda yanlis aday, yanlis ilk kilit, sentetikte yanlis ayet) kotulesen senaryo
elenir; kalanlar kilit gecikmesi / kilitlenen bolum / ayet takibine gore.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUITES = "replay,stress,compose,external,synth"

# (kimlik, aciklama, TILAVET_SM_PARAMS[, TILAVET_ASR_PARAMS])
SCENARIOS = {
    "A": [
        ("base", "bugunku ayarlar", {}),
        # 27.10 duzeltmelerinin yeni veride etkisi (kullanici: "hicbir degisiklik kotuye gotururmemeli"): eski kural
        ("A0-eski-selam", "eski kural: bolunmus selam sinyal degil", {"SELAM_SPLIT_SIGNAL": False}),
        ("A0-eski-muhammed", "eski kural: tek basina \"محمدا\" kamet", {"MUHAMMAD_CONTEXT": False}),
        ("A1-40", "guven esigi (kilitli) 40", {"MIN_CONFIDENCE": 40}),
        ("A1-45", "guven esigi (kilitli) 45", {"MIN_CONFIDENCE": 45}),
        ("A1-55", "guven esigi (kilitli) 55", {"MIN_CONFIDENCE": 55}),
        ("A1-60", "guven esigi (kilitli) 60", {"MIN_CONFIDENCE": 60}),
        ("A2-60", "guven esigi (ilk kilit) 60", {"FIRST_LOCK_THRESHOLD": 60}),
        ("A2-65", "guven esigi (ilk kilit) 65", {"FIRST_LOCK_THRESHOLD": 65}),
        ("A2-75", "guven esigi (ilk kilit) 75", {"FIRST_LOCK_THRESHOLD": 75}),
        ("A2-80", "guven esigi (ilk kilit) 80", {"FIRST_LOCK_THRESHOLD": 80}),
        ("A3-1", "aligner pencere genisligi 1", {"WINDOW_SLACK": 1}),
        ("A3-3", "aligner pencere genisligi 3", {"WINDOW_SLACK": 3}),
        ("A3-4", "aligner pencere genisligi 4", {"WINDOW_SLACK": 4}),
        ("A4-8", "tek parcada kilit farki 8", {"UNIQUE_LOCK_MARGIN": 8}),
        ("A4-10", "tek parcada kilit farki 10", {"UNIQUE_LOCK_MARGIN": 10}),
        ("A4-15", "tek parcada kilit farki 15", {"UNIQUE_LOCK_MARGIN": 15}),
        ("A5-85", "Fatiha hizli kilit skoru 85", {"FATIHA_FAST_LOCK_MIN_SCORE": 85}),
        ("A5-95", "Fatiha hizli kilit skoru 95", {"FATIHA_FAST_LOCK_MIN_SCORE": 95}),
        ("A6-70", "dogal gecis en az skor 70", {"NATURAL_MIN_SCORE": 70}),
        ("A6-75", "dogal gecis en az skor 75", {"NATURAL_MIN_SCORE": 75}),
        ("A6-80", "dogal gecis en az skor 80", {"NATURAL_MIN_SCORE": 80}),
        ("A7-75", "sure gecisi arama esigi 75", {"JUMP_SEARCH_BELOW": 75}),
        ("A7-85", "sure gecisi arama esigi 85", {"JUMP_SEARCH_BELOW": 85}),
        ("A7m-10", "sure gecisi farki 10", {"JUMP_MARGIN": 10}),
        ("A7m-20", "sure gecisi farki 20", {"JUMP_MARGIN": 20}),
        ("A8-4", "kilit kaybi 4 parca", {"ABANDON_LOCK_AFTER_LOST": 4}),
        ("A8-8", "kilit kaybi 8 parca", {"ABANDON_LOCK_AFTER_LOST": 8}),
        ("A9-2", "belirsiz aday farki 2", {"AMBIGUOUS_MARGIN": 2.0}),
        ("A9-5", "belirsiz aday farki 5", {"AMBIGUOUS_MARGIN": 5.0}),
        ("A10-2", "ilk kilitte en az kelime 2", {"MIN_WORD_COUNT_FIRST_LOCK": 2}),
        ("A10-4", "ilk kilitte en az kelime 4", {"MIN_WORD_COUNT_FIRST_LOCK": 4}),
    ],
    "B": [
        ("B-base", "ses: bugunku ayarlar", {}, {}),
        ("B1-4", "parca suresi 4 sn", {}, {"chunk_sec": 4}),
        ("B1-6", "parca suresi 6 sn", {}, {"chunk_sec": 6}),
        ("B1-7", "parca suresi 7 sn", {}, {"chunk_sec": 7}),
        ("B2-0.5", "bindirme 0.5 sn", {}, {"overlap_sec": 0.5}),
        ("B2-1.5", "bindirme 1.5 sn", {}, {"overlap_sec": 1.5}),
        ("B3-0.3", "duraklama 0.3 sn", {}, {"pause_sec": 0.3}),
        ("B3-0.7", "duraklama 0.7 sn", {}, {"pause_sec": 0.7}),
        ("B4-1.0", "duraklamada en kisa parca 1.0 sn", {}, {"min_chunk_sec": 1.0}),
        ("B4-2.0", "duraklamada en kisa parca 2.0 sn", {}, {"min_chunk_sec": 2.0}),
        ("B5-0.9", "ses hizi 0.9x", {}, {"tempo": 0.9}),
        ("B5-1.1", "ses hizi 1.1x", {}, {"tempo": 1.1}),
        ("B5-1.2", "ses hizi 1.2x", {}, {"tempo": 1.2}),
        ("B6-filtre", "mikrofon filtresi 80 Hz - 6 kHz", {}, {"filter": True}),
    ],
}
BASE_OF = {"A": "base", "B": "B-base"}

# Guvenlik olculeri (artarsa senaryo elenir)
SAFETY = ("wrong_chunks", "shown_wrong", "first_wrong", "ayah_wrong_shown")


def group_of(sid):
    return next(g for g, scs in SCENARIOS.items() if any(s[0] == sid for s in scs))


def scenario_list(group, only=None):
    out = []
    for g in group.split(","):
        sc = SCENARIOS.get(g, [])
        if only:
            keep = set(only.split(","))
            sc = [s for s in sc if s[0] in keep]
        out += sc
    return out


def asr_params(sc):
    return sc[3] if len(sc) > 3 else None


def trjson_dir_of(sc, out_dir):
    return out_dir / "trjson" / sc[0] if asr_params(sc) is not None else None


def run_asr(sc, out_dir, model_dir, threads):
    """B senaryosu: kendi kayitlarimizi bu ses ayarlariyla gercek modelle yeniden tani → <out>/trjson/<id>/."""
    d = trjson_dir_of(sc, out_dir)
    f = d / "asr-model-v2.trjson"
    if f.exists():
        return sc[0], "var", 0.0
    d.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TILAVET_ASR_PARAMS": json.dumps(asr_params(sc)), "TILAVET_ORT_THREADS": str(threads)}
    t0 = time.time()
    with open(d / "eval.log", "w", encoding="utf-8") as log:
        subprocess.run([sys.executable, str(REPO / "scripts" / "eval_pipeline.py"), "--model-dir", str(model_dir),
                        "--chains", "rnnt-hibrit", "--trjson-out", str(d / "tmp.trjson"),
                        "--stats-out", str(d / "stats.json")],
                       cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    if (d / "tmp.trjson").exists():
        (d / "tmp.trjson").rename(f)
    return sc[0], "bitti" if f.exists() else "HATA", time.time() - t0


def run_one(sc, out_dir, seeds, cache_seed):
    sid, desc, params = sc[:3]
    trjson_dir = trjson_dir_of(sc, out_dir)
    if trjson_dir is not None and not (trjson_dir / "asr-model-v2.trjson").exists():
        return sid, "transkript yok (once: tune.py asr)", 0.0
    d = out_dir / sid
    if (d / "results.json").exists():
        return sid, "var", 0.0
    d.mkdir(parents=True, exist_ok=True)
    cache = d / "align.pkl"
    if cache_seed and Path(cache_seed).exists() and not cache.exists():
        shutil.copy(cache_seed, cache)
    env = {**os.environ, "TILAVET_SM_PARAMS": json.dumps(params), "TILAVET_ALIGN_CACHE": str(cache)}
    if trjson_dir is not None:
        env["TILAVET_TRJSON_DIR"] = str(trjson_dir)
    (d / "scenario.json").write_text(json.dumps({"id": sid, "group": group_of(sid), "desc": desc, "params": params,
                                                 "asr": asr_params(sc)}, ensure_ascii=False))
    t0 = time.time()
    with open(d / "gate.log", "w", encoding="utf-8") as log:
        subprocess.run([sys.executable, str(REPO / "tests" / "gate.py"), "--suites", SUITES, "--seeds", str(seeds),
                        "--results", str(d / "results.json"), "--details", str(d / "details.json")],
                       cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    if trjson_dir is not None and (trjson_dir / "stats.json").exists():
        shutil.copy(trjson_dir / "stats.json", d / "asr_stats.json")
    try:
        cache.unlink()   # her senaryonun onbellegi buyuk; sonuc dosyalari yeter
    except OSError:
        pass
    return sid, "bitti" if (d / "results.json").exists() else "HATA", time.time() - t0


def cmd_merge(a):
    """Yeni transkriptleri (TRJSON satirlari) dosyaya ekle; ayni zincir + kayit varsa yenisiyle degistir."""
    def key(line):
        d = json.loads(line[line.find("TRJSON ") + 7:])
        return d["config"], d["file"]
    new = [ln for ln in Path(a.src).read_text(encoding="utf-8").splitlines() if "TRJSON " in ln]
    keys = {key(ln) for ln in new}
    old = [ln for ln in Path(a.dst).read_text(encoding="utf-8").splitlines() if ln.strip()]
    kept = [ln for ln in old if "TRJSON " not in ln or key(ln) not in keys]
    Path(a.dst).write_text("\n".join(kept + new) + "\n", encoding="utf-8")
    print(f"{len(new)} satir eklendi ({len(old) - len(kept)} eskisi degisti) → {a.dst}")


def cmd_list(a):
    print(json.dumps([{"id": s[0], "group": group_of(s[0]), "asr": asr_params(s) is not None}
                      for s in scenario_list(a.group, a.only)]))


def cmd_asr(a):
    out = Path(a.out)
    scs = [s for s in scenario_list(a.group, a.only) if asr_params(s) is not None]
    print(f"{len(scs)} ses senaryosu → {out}/trjson", flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        for sid, st, dt in ex.map(lambda s: run_asr(s, out, a.model_dir, a.threads), scs):
            print(f"{sid}: {st} ({dt / 60:.1f} dk)", flush=True)


def cmd_run(a):
    out = Path(a.out)
    scs = scenario_list(a.group, a.only)
    print(f"{len(scs)} senaryo → {out}", flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        for sid, st, dt in ex.map(lambda s: run_one(s, out, a.seeds, a.cache), scs):
            print(f"{sid}: {st} ({dt / 60:.1f} dk)", flush=True)


# ---------------------------------------------------------------- rapor

def flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(flatten(v, f"{prefix}{k}."))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out[f"{prefix}{k}"] = v
    return out


def total(flat, suffix):
    return sum(v for k, v in flat.items() if k.endswith("." + suffix))


def per_recording(base, cur):
    """Kayit kayit → (kotulesen, iyilesen). "YANLIS" iceren kotulesme guvenlik (senaryo elenir): yanlis kilitli parca /
    ekranda yanlis aday artti, yanlis ilk kilit, Kuran disi kayit kilitlendi, sentetikte yanlis ayet. Digerleri: ilk kilit
    kayboldu / >1 sn degisti, bolum kilidi kayboldu / >1 sn degisti, sentetikte takip edilen ayet."""
    worse, better = [], []
    for suite, chains in base.items():
        for cfg, files in chains.items():
            for fn, b in files.items():
                c = cur.get(suite, {}).get(cfg, {}).get(fn)
                if c is None:
                    continue
                w, g = [], []
                if c["wrong"] > b["wrong"]:
                    w.append(f"YANLIS kilitli parca {b['wrong']}→{c['wrong']}")
                elif c["wrong"] < b["wrong"]:
                    g.append(f"yanlis kilitli parca {b['wrong']}→{c['wrong']}")
                if c["shown_wrong"] > b["shown_wrong"]:
                    w.append(f"YANLIS ekranda aday {b['shown_wrong']}→{c['shown_wrong']}")
                elif c["shown_wrong"] < b["shown_wrong"]:
                    g.append(f"ekranda yanlis aday {b['shown_wrong']}→{c['shown_wrong']}")
                bf, cf, exp = b["first"], c["first"], b.get("expected")
                if isinstance(exp, int):
                    bok, cok = bool(bf and bf[0] == exp), bool(cf and cf[0] == exp)
                    if cf and cf[0] != exp and not (bf and bf[0] != exp):
                        w.append(f"YANLIS ilk kilit {bf}→{cf}")
                    elif bok and not cok:
                        w.append(f"ilk kilit {bf}→{cf}")
                    elif cok and not bok:
                        g.append(f"ilk kilit {bf}→{cf}")
                    elif bok and cok and abs(cf[1] - bf[1]) > 1.0:
                        (w if cf[1] > bf[1] else g).append(f"ilk kilit {bf[1]}→{cf[1]} sn")
                elif exp is None and (cf is not None) != (bf is not None):
                    (w if cf is not None else g).append(f"{'YANLIS ' if cf else ''}Kuran disi kilit {bf}→{cf}")
                for (su, lb), (_su2, lc) in zip(b["segs"], c["segs"]):
                    if su is None:
                        continue
                    if lb is not None and lc is None:
                        w.append(f"{su}. sure kilitlenmedi (once {lb} sn)")
                    elif lb is None and lc is not None:
                        g.append(f"{su}. sure kilitlendi ({lc} sn)")
                    elif lb is not None and lc is not None and abs(lc - lb) > 1.0:
                        (w if lc > lb else g).append(f"{su}: {lb}→{lc} sn")
                if b.get("ayah") and c.get("ayah"):
                    if c["ayah"][0] < b["ayah"][0]:
                        w.append(f"ayet {b['ayah'][0]}→{c['ayah'][0]}/{b['ayah'][1]}")
                    elif c["ayah"][0] > b["ayah"][0]:
                        g.append(f"ayet {b['ayah'][0]}→{c['ayah'][0]}/{b['ayah'][1]}")
                    if c["ayah"][3] > b["ayah"][3]:
                        w.append(f"YANLIS ayet gosterimi {b['ayah'][3]}→{c['ayah'][3]}")
                tag = f"{suite}/{cfg}/{fn}"
                if w:
                    worse.append(f"{tag}: " + ", ".join(w))
                if g:
                    better.append(f"{tag}: " + ", ".join(g))
    return worse, better


def summary_metrics(res, asr_stats=None):
    f = flatten(res)
    h = "rnnt-hibrit"
    g = f.get
    stress_locked = sum(v for k, v in f.items() if k.startswith(f"stress.{h}.") and k.endswith(".sections_locked"))
    stress_delay = [v for k, v in f.items() if k.startswith(f"stress.{h}.") and k.endswith(".delay_mean")]
    return {
        "safety": sum(total(f, s) for s in SAFETY),
        "real_locked": g(f"replay.{h}.sections_locked"), "real_med": g(f"replay.{h}.delay_median"),
        "real_mean": g(f"replay.{h}.delay_mean"), "first_med": g(f"replay.{h}.first_median"),
        "ext_locked": g(f"external.{h}.sections_locked"), "ext_mean": g(f"external.{h}.delay_mean"),
        "syn_pct": g(f"synth.{h}.ayah_follow_pct"), "syn_lat": g(f"synth.{h}.ayah_latency_median"),
        "str_locked": stress_locked, "str_mean": round(sum(stress_delay) / len(stress_delay), 2) if stress_delay else None,
        "asr_ms": ((asr_stats or {}).get("asr_ms", {}).get(h) or {}).get("median"),
    }


def fmt(v, base, nd=1, up=False):
    if v is None:
        return "-"
    s = f"{v:.{nd}f}" if isinstance(v, float) else f"{v}"
    if base is None:
        return s
    d = v - base
    if abs(d) < 1e-9:
        return s
    good = d > 0 if up else d < 0
    return f"{s} ({'+' if d > 0 else ''}{d:.{nd}f}{' ✓' if good else ' ✗'})"


def load_rows(out):
    rows = []
    for d in sorted(Path(out).rglob("scenario.json")):
        d = d.parent
        if not (d / "results.json").exists():
            continue
        sc = json.loads((d / "scenario.json").read_text())
        det = json.loads((d / "details.json").read_text()) if (d / "details.json").exists() else {}
        st = json.loads((d / "asr_stats.json").read_text()) if (d / "asr_stats.json").exists() else None
        rows.append((sc, json.loads((d / "results.json").read_text()), det, st))
    return rows


def verdict_of(sc, m, bm, worse, better):
    safety_worse = m["safety"] > bm["safety"] or any("YANLIS" in w for w in worse)
    gain = any((m[k] or 0) > (bm[k] or 0) for k in ("real_locked", "ext_locked", "str_locked", "syn_pct")) or any(
        (m[k] or 0) < (bm[k] or 0) - 0.05 for k in ("real_mean", "ext_mean", "str_mean"))
    if sc["id"] == BASE_OF[sc["group"]]:
        return "temel"
    if safety_worse:
        return "ELENDI (guvenlik)"
    if worse and better:
        return "KARISIK"
    if gain and not worse:
        return "IYI"
    if worse:
        return "KOTU"
    return "FARK YOK"


def cmd_report(a):
    rows = load_rows(a.out)
    out_lines, verdicts = [], []
    for grp in ("A", "B"):
        grows = [r for r in rows if r[0]["group"] == grp]
        base = next((r for r in grows if r[0]["id"] == BASE_OF[grp]), None)
        if not base:
            continue
        bm = summary_metrics(base[1], base[3])
        out_lines += [f"### Grup {grp} (temel: {BASE_OF[grp]})", "",
                      "| senaryo | guvenlik (yanlis toplam) | gercek: kilitli bolum | gercek: gecikme medyan / ort "
                      "| ilk kilit medyan | dis: kilitli / ort | sentetik: ayet % / gecikme | zorlama: kilitli / ort "
                      "| ASR ms/parca | kayit: kotu / iyi | karar |",
                      "|---|---|---|---|---|---|---|---|---|---|---|"]
        order = [s[0] for s in SCENARIOS[grp]]
        for sc, res, det, st in sorted(grows, key=lambda r: order.index(r[0]["id"]) if r[0]["id"] in order else 999):
            m = summary_metrics(res, st)
            worse, better = per_recording(base[2], det) if det and base[2] else ([], [])
            v = verdict_of(sc, m, bm, worse, better)
            verdicts.append((sc["id"], v, worse, better))
            out_lines.append(
                f"| {sc['id']} {sc['desc']} | {fmt(m['safety'], bm['safety'], 0)} "
                f"| {fmt(m['real_locked'], bm['real_locked'], 0, True)} "
                f"| {fmt(m['real_med'], bm['real_med'], 2)} / {fmt(m['real_mean'], bm['real_mean'], 2)} "
                f"| {fmt(m['first_med'], bm['first_med'])} "
                f"| {fmt(m['ext_locked'], bm['ext_locked'], 0, True)} / {fmt(m['ext_mean'], bm['ext_mean'], 2)} "
                f"| {fmt(m['syn_pct'], bm['syn_pct'], 1, True)} / {fmt(m['syn_lat'], bm['syn_lat'], 2)} "
                f"| {fmt(m['str_locked'], bm['str_locked'], 0, True)} / {fmt(m['str_mean'], bm['str_mean'], 2)} "
                f"| {fmt(m['asr_ms'], bm['asr_ms'], 0)} | {len(worse)} / {len(better)} | {v} |")
        out_lines.append("")
    out_lines.append("Karar: ELENDI = guvenlik olcusu (yanlis kilit / ekranda yanlis aday / yanlis ilk kilit / yanlis ayet) "
                     "kotulesti; KARISIK = bazi kayitlar iyilesti, bazilari kotulesti; IYI = kotulesen kayit yok, en az bir "
                     "olcu iyilesti; KOTU = sadece kotulesme; FARK YOK.")
    out_lines.append("")
    for sid, v, worse, better in verdicts:
        if v == "temel" or (not worse and not better):
            continue
        out_lines.append(f"<details><summary>{sid}: {v} — kotulesen {len(worse)}, iyilesen {len(better)}</summary>\n")
        out_lines += [f"- ✗ {w}" for w in worse[:a.max_lines]]
        out_lines += [f"- ✓ {g}" for g in better[:a.max_lines]]
        out_lines.append("\n</details>\n")
    text = "\n".join(out_lines)
    print(text)
    if a.summary:
        with open(a.summary, "a", encoding="utf-8") as f:
            f.write("## Ayar denemesi\n\n" + text + "\n")
    if a.json:
        Path(a.json).write_text(json.dumps([{"id": s, "verdict": v, "worse": w, "better": g} for s, v, w, g in verdicts],
                                           ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "asr", "run"):
        p = sub.add_parser(name)
        p.add_argument("--group", default="A")
        p.add_argument("--only", help="sadece bu senaryolar (virgulle)")
        if name != "list":
            p.add_argument("--out", required=True)
            p.add_argument("--workers", type=int, default=1)
        if name == "asr":
            p.add_argument("--model-dir", required=True)
            p.add_argument("--threads", type=int, default=4)
        if name == "run":
            p.add_argument("--seeds", type=int, default=5)
            p.add_argument("--cache", help="baslangic hizalama onbellegi (her senaryoya kopyalanir)")
    p = sub.add_parser("merge")
    p.add_argument("--src", required=True)
    p.add_argument("--dst", required=True)
    p = sub.add_parser("report")
    p.add_argument("--out", required=True)
    p.add_argument("--max-lines", type=int, default=15)
    p.add_argument("--summary", help="Markdown rapor (GITHUB_STEP_SUMMARY)")
    p.add_argument("--json", help="kararlar + kayit kayit liste (json)")
    a = ap.parse_args()
    {"list": cmd_list, "asr": cmd_asr, "run": cmd_run, "merge": cmd_merge, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
