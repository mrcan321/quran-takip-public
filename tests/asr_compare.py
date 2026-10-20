#!/usr/bin/env python3
"""ASR model yarisi — aday ses tanima modellerini kendi kayitlarimizla yan yana olcer (.github/workflows/asr-compare.yml).

Adaylar tests/asr_candidates.json'da (release tag + NeMo modeli + INT8). Her aday CI'da export edilir (model-export.yml),
ayni kayitlar (data/*.wav, dis kaynak v1 / v2, istege bagli sentetik) gercek ASR ile transkribe edilir (eval_pipeline,
rnnt + rnnt-hibrit), transkriptler test kapisindan gecer (TILAVET_TRJSON_DIR=<aday> python tests/gate.py ...) ve:

  plan     tests/asr_candidates.json → GITHUB_OUTPUT (export / degerlendirme / puanlama matrisleri)
  metrics  bir adayin transkriptleri → ses tanima olculeri (okumada bos / yetersiz parca, okuma disi metin ve uydurma,
           ASR suresi, Uthmani yazim orani) + test kapisi sonuclari → score-<tag>.json
  summary  score-*.json → temel modelin yaninda karsilastirma tablosu (markdown) + kabul sarti

Kabul sarti (CLAUDE.md "Ses tanima modelini iyilestirme"): guvenlik olculeri temel modelden kotu olmamali (yanlis
kilitli parca, ekranda yanlis aday, yanlis ilk kilit, sinyal / zikir yanlis alarmi, okuma icinde metin silme), kamet /
selam / semiallah yakalama dusmemeli; iyilesme: okumada bos + yetersiz parca orani ve takip gecikmesi medyani.
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANDIDATES = REPO / "tests" / "asr_candidates.json"

# ASR'nin sessizlik / gurultude uydurdugu egitim verisi kaliplari (bkz. CLAUDE.md acik sorun 7, 9, 15), normalize hali
HALLUCINATION_WORDS = ["شركة", "للخدمات", "التقنية", "المصدر", "تفسير", "الدرس", "موسوعة", "النابلسي", "مشاركة"]
# U+0670 (ust elif) imla'i Tanzil metninde de var (هَٰذَا) ve temel modelin tokenizer'inda — Uthmani sayilmaz
UTHMANI_CHARS = {"ٱ"} | {chr(c) for c in range(0x06D6, 0x06EE)}


# ---------------- plan ----------------
def cmd_plan(args):
    cfg = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    sets = cfg.get("sets", ["data"])
    cands = [{"tag": c["tag"], "model": c.get("model", ""), "quantize": c.get("quantize", "none")}
             for c in cfg["candidates"]]
    evals = [{"tag": c["tag"], "set": s} for c in cfg["candidates"] for s in c.get("sets", sets)]
    lines = [f"cands={json.dumps(cands)}", f"evals={json.dumps(evals)}",
             f"tags={json.dumps([c['tag'] for c in cfg['candidates']])}", f"base={cfg.get('base', 'asr-model-v2')}"]
    print("\n".join(lines))


# ---------------- metrics ----------------
def recitation_stats(recs, env, metrics, hallu):
    """{dosya: parcalar} (tek zincir) → okuma sirasinda / disinda parca istatistikleri (TIMELINE / EXPECTED ile)."""
    from aligner import normalize_arabic

    c = dict(rec=0, rec_empty=0, rec_weak=0, rec_matched=0, out=0, out_text=0, out_hallu=0, chunks=0, uthmani=0)
    scores = []
    for fn, ch in sorted(recs.items()):
        tl = env.ev.timeline_for(fn)
        if not tl:
            continue
        res = env.run_sm(ch)
        for k, (x, r) in enumerate(zip(ch, res)):
            text = (x[1] or "").strip()
            c["chunks"] += 1
            if text and any(t in UTHMANI_CHARS for t in text):
                c["uthmani"] += 1
            cur, _ = metrics.segment_at(tl, env.chunk_time(x, k) - 1.0)
            if cur is not None:
                if r["status"] == "silent":
                    continue   # ses yok (imam duraklamasi / kayit sonu) — modelin hatasi degil
                c["rec"] += 1
                if not text:
                    c["rec_empty"] += 1
                elif r["status"] == "matched":
                    c["rec_matched"] += 1
                elif r["status"] in ("low_confidence", "too_short"):
                    c["rec_weak"] += 1
                if r.get("score") is not None:
                    scores.append(r["score"])
            else:
                c["out"] += 1
                if text and r["status"] != "silent":
                    c["out_text"] += 1
                    toks = set(normalize_arabic(text).split())
                    if toks & hallu:
                        c["out_hallu"] += 1
    pct = lambda a, b: round(100.0 * a / b, 1) if b else None   # noqa: E731
    scores.sort()
    return {
        "rec_chunks": c["rec"], "rec_empty_pct": pct(c["rec_empty"], c["rec"]),
        "rec_weak_pct": pct(c["rec_weak"], c["rec"]), "rec_matched_pct": pct(c["rec_matched"], c["rec"]),
        "rec_empty_weak_pct": pct(c["rec_empty"] + c["rec_weak"], c["rec"]),
        "rec_score_median": scores[len(scores) // 2] if scores else None,
        "out_chunks": c["out"], "out_text": c["out_text"], "out_hallu": c["out_hallu"],
        "uthmani_pct": pct(c["uthmani"], c["chunks"]),
    }


def cmd_metrics(args):
    sys.path.insert(0, str(REPO / "tests"))
    sys.path.insert(0, str(REPO / "scripts"))
    from lib import env, metrics   # TILAVET_TRJSON_DIR=<aday> ile cagrilir
    from aligner import normalize_arabic

    hallu = {normalize_arabic(w) for w in HALLUCINATION_WORDS}
    sets = {"data": env.load_trjson(), "external": env.load_external(), "synth": env.load_synth()}
    out = {"tag": args.tag, "asr": {}}
    for name, T in sets.items():
        if not T:
            continue
        out["asr"][name] = {cfg: recitation_stats(T.get(cfg, {}), env, metrics, hallu) for cfg in env.CONFIGS}
        print(f"[{name}] {json.dumps(out['asr'][name], ensure_ascii=False)}", flush=True)
    d = Path(env.TRJSON_DIR)
    stats = {}
    for p in sorted(d.rglob("*.stats.json")):
        stats[p.name.replace(".stats.json", "")] = json.loads(p.read_text(encoding="utf-8"))
    out["asr_ms"] = stats
    if args.gate and Path(args.gate).exists():
        out["gate"] = json.loads(Path(args.gate).read_text(encoding="utf-8"))
    for p in sorted(d.glob("export_report*.txt")):
        out["export_report"] = p.read_text(encoding="utf-8")[-3000:]
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")


# ---------------- summary ----------------
def get(d, path):
    for k in path.split("/"):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


H = "rnnt-hibrit"
# (etiket, yol, yon): yon "low" = dusuk iyi, "high" = yuksek iyi; "safe" = guvenlik (temelden kotu olamaz)
ROWS = [
    ("Ses tanima (telefon zinciri: hibrit)", None, None, None),
    ("Okumada bos parca %", f"asr/data/{H}/rec_empty_pct", "low", False),
    ("Okumada yetersiz parca %", f"asr/data/{H}/rec_weak_pct", "low", False),
    ("Okumada bos + yetersiz %", f"asr/data/{H}/rec_empty_weak_pct", "low", False),
    ("Okumada kilitli parca %", f"asr/data/{H}/rec_matched_pct", "high", False),
    ("Okuma skor medyani", f"asr/data/{H}/rec_score_median", "high", False),
    ("Okuma disi metinli parca", f"asr/data/{H}/out_text", "low", False),
    ("Okuma disi uydurma", f"asr/data/{H}/out_hallu", "low", False),
    ("Dis kaynak: bos + yetersiz %", f"asr/external/{H}/rec_empty_weak_pct", "low", False),
    ("Dis kaynak: okuma disi metin", f"asr/external/{H}/out_text", "low", False),
    ("Uthmani yazimli parca %", f"asr/data/{H}/uthmani_pct", None, False),
    ("ASR ms / parca (CI, medyan)", f"asr_ms/data/asr_ms/{H}/median", "low", False),
    ("Guvenlik (temelden kotu olamaz)", None, None, None),
    ("Yanlis kilitli parca (rnnt)", "gate/replay/rnnt/wrong_chunks", "low", True),
    ("Yanlis kilitli parca (hibrit)", f"gate/replay/{H}/wrong_chunks", "low", True),
    ("Ekranda yanlis aday (hibrit)", f"gate/replay/{H}/shown_wrong", "low", True),
    ("Yanlis ilk kilit (hibrit)", f"gate/replay/{H}/first_wrong", "low", True),
    ("Dis: yanlis kilitli parca (hibrit)", f"gate/external/{H}/wrong_chunks", "low", True),
    ("Dis: ekranda yanlis aday (hibrit)", f"gate/external/{H}/shown_wrong", "low", True),
    ("Dis: yanlis ilk kilit (hibrit)", f"gate/external/{H}/first_wrong", "low", True),
    ("Zorlama S1 yanlis kilitli (hibrit)", f"gate/stress/{H}/S1/wrong_chunks", "low", True),
    ("Zorlama S3 yanlis kilitli (hibrit)", f"gate/stress/{H}/S3/wrong_chunks", "low", True),
    ("Zorlama S5 yanlis kilitli (hibrit)", f"gate/stress/{H}/S5/wrong_chunks", "low", True),
    ("Sinyal yanlis alarmi", "gate/signals/signal_false_alarms", "low", True),
    ("Dis: sinyal yanlis alarmi", "gate/external/signals/signal_false_alarms", "low", True),
    ("Kamet yakalanan", "gate/signals/kamet_detected", "high", True),
    ("Selam yakalanan", "gate/signals/selam_detected", "high", True),
    ("Semiallah yakalanan", "gate/signals/ruku_detected", "high", True),
    ("Dis: ezan yakalanan", "gate/external/signals/ezan_detected", "high", True),
    ("Zikir karti yanlis alarmi", "gate/kotlin/zikir_false_alarms", "low", True),
    ("Okuma icinde metin silme", "gate/kotlin/hide_false", "low", True),
    ("Takip", None, None, None),
    ("Ilk kilit dogru (hibrit)", f"gate/replay/{H}/first_ok", "high", False),
    ("Kilitlenen bolum (hibrit)", f"gate/replay/{H}/sections_locked", "high", False),
    ("Takip gecikmesi medyani sn (hibrit)", f"gate/replay/{H}/delay_median", "low", False),
    ("Takip gecikmesi ort. sn (hibrit)", f"gate/replay/{H}/delay_mean", "low", False),
    ("Takip gecikmesi medyani sn (rnnt)", "gate/replay/rnnt/delay_median", "low", False),
    ("Dis: kilitlenen bolum (hibrit)", f"gate/external/{H}/sections_locked", "high", False),
    ("Dis: takip gecikmesi medyani (hibrit)", f"gate/external/{H}/delay_median", "low", False),
    ("Teravih 20 rekat kilitli bolum", f"gate/compose/{H}/teravih/sections_locked", "high", False),
    ("Sentetik ayet takibi % (hibrit)", f"gate/synth/{H}/ayah_follow_pct", "high", False),
]


def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)


def cmd_summary(args):
    scores = {}
    for p in args.files:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        scores[d["tag"]] = d
    base = args.base if args.base in scores else next(iter(scores), None)
    if base is None:
        print("Hic sonuc yok")
        return
    tags = [base] + [t for t in sorted(scores) if t != base]
    md = ["## ASR model yarisi", "", f"Temel: `{base}`. Hucrelerde deger (temele gore fark).", "",
          "| olcu | " + " | ".join(f"`{t}`" for t in tags) + " |", "|---|" + "---|" * len(tags)]
    verdict = {t: {"safe": [], "better": [], "worse": []} for t in tags[1:]}
    for label, path, direction, safe in ROWS:
        if path is None:
            md.append(f"| **{label}** |" + " |" * len(tags))
            continue
        bv = get(scores[base], path)
        cells = [fmt(bv)]
        for t in tags[1:]:
            v = get(scores[t], path)
            cell = fmt(v)
            if isinstance(v, (int, float)) and isinstance(bv, (int, float)) and direction:
                diff = v - bv
                if abs(diff) > 1e-9:
                    good = diff < 0 if direction == "low" else diff > 0
                    cell += f" ({diff:+.1f} {'✓' if good else '✗'})"
                    if safe and not good:
                        verdict[t]["safe"].append(label)
                    elif good:
                        verdict[t]["better"].append(label)
                    else:
                        verdict[t]["worse"].append(label)
            cells.append(cell)
        md.append(f"| {label} | " + " | ".join(cells) + " |")
    md += ["", "### Kabul sarti", ""]
    for t, v in verdict.items():
        key = ["Okumada bos + yetersiz %", "Takip gecikmesi medyani sn (hibrit)"]
        improves = any(k in v["better"] for k in key)
        if v["safe"]:
            md.append(f"- `{t}`: **RED** — guvenlik olcusu kotulesti: {', '.join(v['safe'])}")
        elif improves:
            md.append(f"- `{t}`: **ADAY** — guvenlik ayni, iyilesen: {', '.join(v['better'])}"
                      + (f"; kotulesen: {', '.join(v['worse'])}" if v["worse"] else ""))
        else:
            md.append(f"- `{t}`: **KAZANC YOK** — guvenlik ayni ama okuma / gecikme iyilesmedi"
                      + (f"; kotulesen: {', '.join(v['worse'])}" if v["worse"] else ""))
    for t in tags:
        rep = scores[t].get("export_report")
        if rep:
            md += ["", f"<details><summary>Export raporu `{t}`</summary>", "", "```", rep.strip(), "```", "", "</details>"]
    text = "\n".join(md) + "\n"
    print(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("candidates", nargs="?", default=str(CANDIDATES))
    p = sub.add_parser("metrics")
    p.add_argument("--tag", required=True)
    p.add_argument("--gate", help="tests/gate.py --results json")
    p.add_argument("--out", required=True)
    p = sub.add_parser("summary")
    p.add_argument("--base", default="asr-model-v2")
    p.add_argument("--summary", help="GITHUB_STEP_SUMMARY")
    p.add_argument("files", nargs="+")
    args = ap.parse_args()
    {"plan": cmd_plan, "metrics": cmd_metrics, "summary": cmd_summary}[args.cmd](args)


if __name__ == "__main__":
    main()
