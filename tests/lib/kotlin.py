"""Kotlin tarafi (tests/jvm): uygulamanin kendi kaynaklari JVM'de calisir, ciktilar Python referansiyla ya da altin
dosyalarla karsilastirilir."""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import env

JVM_DIR = env.TESTS / "jvm"
JVM_BIN = JVM_DIR / "build" / "install" / "tilavet-jvm-tests" / "bin" / "tilavet-jvm-tests"


def ensure_built(offline=False):
    if JVM_BIN.exists() and os.environ.get("TILAVET_JVM_REBUILD") != "1":
        return
    cmd = ["gradle", "-q", "installDist"] + (["--offline"] if offline else [])
    subprocess.run(cmd, cwd=JVM_DIR, check=True)


def run(*args):
    p = subprocess.run([str(JVM_BIN), *map(str, args)], capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError(f"JvmTests {args[0]} hata ({p.returncode}):\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}")
    return p.stdout


def fixtures(assets):
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "fx.json"
        log = run("fixtures", assets, out)
        return json.loads(out.read_text(encoding="utf-8")), log


def _tsv(path):
    rows = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        a, b, c = line.split("\t", 2)
        rows.setdefault((a, b), []).append(c)
    return rows


def trace(assets, trjson_path):
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "trace.tsv"
        run("trace", assets, trjson_path, out)
        return {k: v[0] for k, v in _tsv(out).items()}


def events(kind, assets, trjson_path):
    """kind: rakat | ezan → {(zincir, dosya): [satirlar]}"""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / f"{kind}.tsv"
        run(kind, assets, trjson_path, out)
        return _tsv(out) if out.stat().st_size else {}


def events_hide(assets, trjson_path, wav_dir):
    """Ses kesilince metni kaldirma (JvmTests hide) → {(zincir, dosya): ["SHOW t" / "HIDE t", ...]}"""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "hide.tsv"
        run("hide", assets, trjson_path, wav_dir, out)
        return _tsv(out) if out.stat().st_size else {}


def events_text(ev_map):
    return "".join(f"{a}\t{b}\t{line}\n" for (a, b), lines in sorted(ev_map.items()) for line in lines)


def trace_parity(assets, recs_by_cfg):
    """Kotlin karar izi = Python referansi mi? recs_by_cfg: {zincir: {dosya: parcalar}} → (fark, kayit, ornekler)"""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "in.trjson"
        env.write_trjson(p, recs_by_cfg)
        kt = trace(assets, p)
    diffs, n, ex = 0, 0, []
    for cfg, recs in recs_by_cfg.items():
        for fn, chunks in recs.items():
            n += 1
            py = " ".join(env.decision_cell(k, r) for k, r in enumerate(env.run_sm(chunks)))
            if kt.get((cfg, fn)) != py:
                diffs += 1
                if len(ex) < 5:
                    a, b = (kt.get((cfg, fn)) or "").split(), py.split()
                    first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
                    ex.append(f"{cfg} {fn}: ilk fark #{first}: kotlin={a[first:first + 3]} python={b[first:first + 3]}")
    return diffs, n, ex


def chunk_parity(wav_paths):
    """ChunkBuilder (Kotlin) = vad_chunker (Python)? always + toggle modlari; WavReader = soundfile (16 kHz mono)."""
    import vad_chunker as vc
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        py = {}
        for wp in wav_paths:
            audio = env.ev.load_audio(Path(wp))
            name = Path(wp).name
            audio.astype("<f4").tofile(d / f"{name}.f32")
            for mode in ("always", "toggle"):
                cuts, flag = [], [mode == "always"]
                for c, t, p in vc.chunks_pause(audio, pause_enabled=lambda: flag[0]):
                    cuts.append(f"{t:.1f}{'p' if p else ''}:{len(c)}")
                    if mode == "toggle":
                        flag[0] = len(cuts) % 3 != 0
                py[(mode, name)] = " ".join(cuts)
            os.symlink(os.path.abspath(wp), d / name)
        out = d / "chunks.tsv"
        run("chunks", d, out)
        kt = {k: v[0] for k, v in _tsv(out).items()}
        cdiff = sum(1 for k, v in py.items() if kt.get(k) != v)
        cex = [f"{m} {n}" for (m, n), v in py.items() if kt.get((m, n)) != v][:5]
        # WavReader: 16 kHz mono 16 bit kayitlarda soundfile ile bit bit ayni olmali
        wout = d / "wav.tsv"
        run("wav", d, wout)
        wdiff, wn, wex = 0, 0, []
        import soundfile as sf
        for wp in wav_paths:
            name = Path(wp).name
            info = sf.info(str(wp))
            if info.samplerate != 16000 or info.channels != 1 or info.subtype != "PCM_16":
                continue
            wn += 1
            ref = np.fromfile(d / f"{name}.f32", dtype="<f4")
            got = np.fromfile(d / f"{Path(name).stem}.wavreader.f32", dtype="<f4")
            if len(ref) != len(got) or (len(ref) and float(np.max(np.abs(ref - got))) != 0.0):
                wdiff += 1
                wex.append(f"{name}: uzunluk {len(got)}/{len(ref)}")
    return {"chunk_diffs": cdiff, "chunk_cases": len(py), "chunk_examples": cex,
            "wav_diffs": wdiff, "wav_cases": wn, "wav_examples": wex}


def meals(asr_dir):
    """Secilebilir mealler (JvmTests meals: MealCatalog + MealLoader, <asr>/meals/index.tsv) → ({meals_passed, meals_total,
    meals_failures}, hatalar). index.tsv yoksa (scripts/build_meals.py calismadi) bos sonuc + not."""
    if not (asr_dir / "meals" / "index.tsv").exists():
        return {}, [f"meals: {asr_dir}/meals/index.tsv yok — scripts/build_meals.py calismamis, mealler denenmedi"]
    p = subprocess.run([str(JVM_BIN), "meals", str(asr_dir)], capture_output=True, text=True, encoding="utf-8")
    m = re.search(r"meals: (\d+)/(\d+)", p.stdout)
    fails = [ln.strip() for ln in p.stdout.splitlines() if "HATA" in ln]
    if not m:
        return {"meals_passed": 0, "meals_total": 0, "meals_failures": 1}, \
            fails + [f"cikti yok ({p.returncode}): {p.stderr[-500:]}"]
    ok, total = int(m.group(1)), int(m.group(2))
    return {"meals_passed": ok, "meals_total": total, "meals_failures": total - ok}, fails


def glasses():
    """G2 gozluk koprusu kontrolleri (JvmTests glasses) → ({glasses_passed, glasses_total, glasses_failures}, hatalar)."""
    p = subprocess.run([str(JVM_BIN), "glasses"], capture_output=True, text=True, encoding="utf-8")
    m = re.search(r"glasses: (\d+)/(\d+)", p.stdout)
    fails = [ln.strip() for ln in p.stdout.splitlines() if "HATA" in ln]
    if not m:
        return {"glasses_passed": 0, "glasses_total": 0, "glasses_failures": 1}, \
            fails + [f"cikti yok ({p.returncode}): {p.stderr[-500:]}"]
    ok, total = int(m.group(1)), int(m.group(2))
    return {"glasses_passed": ok, "glasses_total": total, "glasses_failures": total - ok}, fails
