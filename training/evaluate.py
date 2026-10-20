#!/usr/bin/env python3
"""Ince ayar — Asama D: yeni modeli temel modelle AYNI kayitlar ve AYNI olcutlerle karsilastir (kiralik makinede,
CI dakikasi harcamadan; asr-compare.yml'in yerel karsiligi).

  1. Export: her iki model → ONNX (scripts/onnx_full_export.py; uygulamadaki dosyalarin aynisi).
  2. ASR: eval_pipeline (rnnt + rnnt-hibrit) — kumeler:
       data   data/*.wav + server/recordings, EGITIMDE KULLANILAN gercek kayitlar haric (real_labels.json split=train)
       ext-v1 / ext-v2   dis kaynak gercek kayitlar (archive.org'dan indirilir; tests/trjson/external manifest'leri)
       synth  sentetik namaz / teravih (EveryAyah: Alafasy + Sureym — egitimde YOK; tests/synth ile ayni tohum)
  3. Test kapisi (tests/gate.py, transkriptler TILAVET_TRJSON_DIR) + ses tanima olculeri (tests/asr_compare.py metrics).
  4. Ozet: temel modelin yaninda tablo + kabul sarti (asr_compare.py summary) → <work>/summary.md

Kullanim:
  python training/evaluate.py --model /data/run1/best.nemo --work /data/eval
  python training/evaluate.py --model /data/run1/best.nemo --work /data/eval --base-onnx /data/asr-model-v2
  python training/evaluate.py ... --smoke        # sadece data kumesinden 3 kayit, kapi: replay + signals
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

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PY = sys.executable
DEFAULT_MODEL = "nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0"
SYNTH_ARGS = ["--reciters", "Alafasy_128kbps,Saood_ash-Shuraym_128kbps", "--programs", "namaz2,teravih8,hatim4",
              "--seed", "1"]


def run(cmd, log, env=None, check=True):
    log.parent.mkdir(parents=True, exist_ok=True)
    print(f"$ {' '.join(map(str, cmd))}  (log: {log})", flush=True)
    with open(log, "w", encoding="utf-8") as f:
        p = subprocess.run([str(c) for c in cmd], stdout=f, stderr=subprocess.STDOUT, cwd=REPO,
                           env={**os.environ, **(env or {})})
    if check and p.returncode != 0:
        tail = log.read_text(encoding="utf-8", errors="replace")[-3000:]
        raise SystemExit(f"HATA ({p.returncode}): {' '.join(map(str, cmd))}\n{tail}")
    return p.returncode


def export(name, out_dir, log):
    if (out_dir / "meta.json").exists() and (out_dir / "rnnt_joint.onnx").exists():
        print(f"export var: {out_dir}", flush=True)
        return
    rc = run([PY, "scripts/onnx_full_export.py", "--out-dir", out_dir, "--model-name", name], log, check=False)
    if rc == 2 and (out_dir / "meta.json").exists():
        # export tamam ama ONNX ciktisi NeMo'dan farkli (raporda) — olcum yine yapilir, ozette export raporu var
        print(f"UYARI: {name} ONNX ciktisi NeMo'dan farkli — {out_dir}/export_report.txt incele", flush=True)
    elif rc != 0:
        raise SystemExit(f"HATA: export basarisiz ({rc}) — {log}")


def test_files(smoke):
    labels = json.loads((HERE / "real_labels.json").read_text(encoding="utf-8"))
    train = {fn for fn, v in labels["files"].items() if v.get("split") == "train"}
    files = sorted((REPO / "data").glob("*.wav")) + sorted((REPO / "server" / "recordings").glob("*.wav"))
    files = [f for f in files if f.name not in train]
    if smoke:
        keep = ("namaz_cuma3_kamet_fatiha_felak_fatiha_nas.wav", "Nas.wav", "test_turkce.wav")
        files = [f for f in files if f.name in keep]
    return files, sorted(train)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="yeni model (.nemo)")
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--base", default=DEFAULT_MODEL, help="temel model (NGC/HF adi ya da .nemo)")
    ap.add_argument("--base-onnx", type=Path, help="temel modelin hazir ONNX klasoru (asr-model-v2 release'i) — export atlanir")
    ap.add_argument("--sets", default="data,ext-v1,ext-v2,synth")
    ap.add_argument("--jobs", type=int, default=0, help="paralel eval sayisi (0: cekirdek / 4)")
    ap.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "everyayah", help="EveryAyah MP3 onbellegi")
    ap.add_argument("--no-kotlin", action="store_true", help="test kapisinin Kotlin kumesini atla (JDK / gradle yoksa)")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    W = args.work.resolve()
    W.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    sets = ["data"] if args.smoke else [s for s in args.sets.split(",") if s]
    ncpu = os.cpu_count() or 4
    jobs = args.jobs or max(1, ncpu // 4)
    threads = max(1, ncpu // jobs)

    # 1. export
    models = {"base": W / "base" / "model", "cand": W / "cand" / "model"}
    if args.base_onnx:
        models["base"] = args.base_onnx.resolve()
    else:
        export(args.base, models["base"], W / "logs" / "export-base.log")
    export(str(Path(args.model).resolve()), models["cand"], W / "logs" / "export-cand.log")
    for tag in models:
        rep = models[tag] / "export_report.txt"
        if rep.exists():
            (W / tag / "trj").mkdir(parents=True, exist_ok=True)
            shutil.copy(rep, W / tag / "trj" / "export_report.txt")

    # 2. ses kumeleri
    files, train_files = test_files(args.smoke)
    print(f"data: {len(files)} test kaydi (egitimde kullanilan {len(train_files)} kayit haric)", flush=True)
    ext_dirs = {}
    for s in sets:
        if s.startswith("ext-"):
            v = s[4:]
            d = W / "audio" / s
            if not (d / "manifest.json").exists():
                run([PY, "tests/external/fetch_external.py", "--out", d, "--max-minutes", "100", "--set", v],
                    W / "logs" / f"fetch-{s}.log")
            ext_dirs[s] = d
    if "synth" in sets and not (W / "audio" / "synth" / "manifest.json").exists():
        run([PY, "tests/synth/build_synth.py", "--out", W / "audio" / "synth", "--cache", args.cache, *SYNTH_ARGS],
            W / "logs" / "build-synth.log")

    tasks = []
    for tag, mdir in models.items():
        out = W / tag / "trj"
        (out / "external").mkdir(parents=True, exist_ok=True)
        (out / "synth").mkdir(parents=True, exist_ok=True)
        for s in sets:
            base_cmd = [PY, "scripts/eval_pipeline.py", "--model-dir", mdir, "--chains", "rnnt,rnnt-hibrit"]
            if s == "data":
                cmd = base_cmd + ["--audio", *files, "--trjson-out", out / "data.trjson", "--stats-out",
                                  out / "data.stats.json"]
            elif s.startswith("ext-"):
                v = s[4:]
                man = REPO / "tests" / "trjson" / "external" / f"external-{v}.manifest.json"
                shutil.copy(ext_dirs[s] / "manifest.json", out / "external" / f"a-fetch-{v}.manifest.json")
                shutil.copy(man, out / "external" / man.name)
                cmd = base_cmd + ["--audio", *sorted(ext_dirs[s].glob("*.wav")), "--manifest", man,
                                  "--trjson-out", out / "external" / f"{s}.trjson",
                                  "--stats-out", out / "external" / f"{s}.stats.json"]
            else:
                sd = W / "audio" / "synth"
                shutil.copy(sd / "manifest.json", out / "synth" / "synth.manifest.json")
                cmd = base_cmd + ["--audio", *sorted(sd.glob("*.wav")), "--manifest", sd / "manifest.json",
                                  "--trjson-out", out / "synth" / "synth.trjson",
                                  "--stats-out", out / "synth" / "synth.stats.json"]
            done = out / ("data.trjson" if s == "data" else
                          f"external/{s}.trjson" if s.startswith("ext-") else "synth/synth.trjson")
            if done.exists() and done.stat().st_size > 0:
                print(f"var: {done}", flush=True)
                continue
            tasks.append((cmd, W / "logs" / f"eval-{tag}-{s}.log"))
    print(f"{len(tasks)} eval, {jobs} paralel × {threads} cekirdek", flush=True)
    with ThreadPoolExecutor(jobs) as ex:
        list(ex.map(lambda t: run(t[0], t[1], env={"TILAVET_ORT_THREADS": str(threads)}), tasks))

    # 3. test kapisi + olculer (her iki model ayni kurallarla)
    assets = REPO / "android-assets-staged"
    if not (assets / "asr" / "quran.bin").exists():
        run([PY, "scripts/build_quran_assets.py"], W / "logs" / "assets.log")
        run([PY, "scripts/explore_rapidfuzz.py"], W / "logs" / "fixtures1.log")
        run([PY, "scripts/build_aligner_fixture.py"], W / "logs" / "fixtures2.log")
        run([PY, "scripts/build_state_machine_fixture.py"], W / "logs" / "fixtures3.log")
    suites = "replay,signals" if args.smoke else "replay,stress,compose,external,synth,signals"
    if not args.no_kotlin and not args.smoke and shutil.which("java") and shutil.which("gradle"):
        suites += ",kotlin"
    elif not args.smoke:
        print("UYARI: java / gradle yok — Kotlin kumesi (zikir karti yanlis alarmi, metin silme) atlandi", flush=True)
    scores = []
    for tag in models:
        trj = W / tag / "trj"
        envv = {"TILAVET_TRJSON_DIR": str(trj), "TILAVET_ALIGN_CACHE": str(W / "align-cache.pkl")}
        run([PY, "tests/gate.py", "--assets", assets, "--suites", suites, "--seeds", "2",
             "--results", W / tag / "gate.json"], W / "logs" / f"gate-{tag}.log", env=envv, check=False)
        run([PY, "tests/asr_compare.py", "metrics", "--tag", tag, "--gate", W / tag / "gate.json",
             "--out", W / f"score-{tag}.json"], W / "logs" / f"metrics-{tag}.log", env=envv)
        scores.append(W / f"score-{tag}.json")
    summary = W / "summary.md"
    summary.write_text("", encoding="utf-8")
    run([PY, "tests/asr_compare.py", "summary", "--base", "base", "--summary", summary, *scores],
        W / "logs" / "summary.log")
    print(summary.read_text(encoding="utf-8"))
    print(f"bitti: {(time.time() - t0) / 60:.0f} dk → {summary}", flush=True)


if __name__ == "__main__":
    main()
