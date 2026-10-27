"""Test kapisi ortak ortami: yollar, referans state machine (scripts/build_state_machine_fixture.py), eval yardimcilari,
korpus, TRJSON okuma ve align_transcription onbellegi (ayni parca metni tum testlerde bir kez hizalanir)."""
import json
import os
import pickle
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
TESTS = REPO / "tests"
# TILAVET_TRJSON_DIR: baska bir transkript kumesi (ASR model yarisinda aday modelin transkriptleri: <dir>/*.trjson,
# <dir>/external/, <dir>/synth/ — tests/asr_compare.py); varsayilan repodaki tests/trjson
TRJSON_DIR = Path(os.environ.get("TILAVET_TRJSON_DIR") or TESTS / "trjson")
BASELINE = TESTS / "baseline.json"
GOLDEN = TESTS / "golden"

sys.path.insert(0, str(SCRIPTS))
# eval_pipeline ONNX modelini ancak ASR'de kullanir; replay icin onnxruntime gerekmez
sys.modules.setdefault("onnx_asr", types.SimpleNamespace(OnnxAsr=None))

import aligner  # noqa: E402
import build_state_machine_fixture as sm  # noqa: E402
import eval_pipeline as ev  # noqa: E402
from aligner import QuranCorpus  # noqa: E402

CONFIGS = ("rnnt", "rnnt-hibrit")

# ---------------- align_transcription onbellegi ----------------
_orig_align = aligner.align_transcription
_cache = {}
_cache_path = os.environ.get("TILAVET_ALIGN_CACHE")   # verilirse diske de yazilir (yerelde tekrarlar hizlansin)
if _cache_path and os.path.exists(_cache_path):
    try:
        with open(_cache_path, "rb") as f:
            _cache = pickle.load(f)
    except Exception:
        _cache = {}
_cache_n0 = len(_cache)


def cached_align(transcription, corpus, window_slack=5, preferred_range=None, preferred_bonus=8.0,
                 min_score_threshold=40.0, exclude_range=None):
    key = (transcription, window_slack, tuple(preferred_range) if preferred_range else None, min_score_threshold,
           tuple(exclude_range) if exclude_range is not None else None)
    if key not in _cache:
        _cache[key] = _orig_align(transcription, corpus, window_slack=window_slack, preferred_range=preferred_range,
                                  preferred_bonus=preferred_bonus, min_score_threshold=min_score_threshold,
                                  exclude_range=exclude_range)
    return _cache[key]


def phone_align(*a, **k):
    """Telefon varsayilani: pencere genisligi +-2 (Aligner.defaultWindowSlack)."""
    return cached_align(*a, **{**k, "window_slack": ev.WINDOW_SLACK})


def save_cache():
    if _cache_path and len(_cache) != _cache_n0:
        tmp = _cache_path + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump(_cache, f)
        os.replace(tmp, _cache_path)


# Ayar denemesi (tests/tune.py): TILAVET_SM_PARAMS='{"MIN_CONFIDENCE": 45, "WINDOW_SLACK": 3}' — referans state machine'in
# modul sabitleri ve telefon varsayilanlari (eval_pipeline WINDOW_SLACK / FIRST_LOCK_THRESHOLD) bu degerlerle. Sadece Python
# kumeleri icin (app / kotlin birebirligi bilerek bozulur).
SM_PARAMS = json.loads(os.environ.get("TILAVET_SM_PARAMS") or "{}")
EV_PARAMS = ("WINDOW_SLACK", "FIRST_LOCK_THRESHOLD")
for _k in EV_PARAMS:
    if _k in SM_PARAMS:
        setattr(ev, _k, SM_PARAMS[_k])


def configure_sm(mod):
    """Referans state machine'i telefon varsayilanlarina ayarla (ilk kilit 70, pencere +-2) + onbellek."""
    mod.MIN_CONFIDENCE_FIRST_LOCK = ev.FIRST_LOCK_THRESHOLD
    for k, v in SM_PARAMS.items():
        if k in EV_PARAMS:
            continue
        if not hasattr(mod, k):
            raise KeyError(f"TILAVET_SM_PARAMS: state machine'de {k} yok")
        setattr(mod, k, v)
    mod.align_transcription = phone_align
    return mod


aligner.align_transcription = cached_align
configure_sm(sm)


SYNTH_DIR = TRJSON_DIR / "synth"
EXTERNAL_DIR = TRJSON_DIR / "external"


def load_manifests():
    """tests/trjson/synth/*.manifest.json (sentetik kayitlar, tests/synth/build_synth.py: beklenen sure + zaman cizelgesi
    + ayet sinirlari + beklenen rekat / namaz) ve tests/trjson/external/*.manifest.json (dis kaynak gercek kayitlar,
    tests/external/fetch_external.py: beklenen sure ya da None, "kind": "ezan"). EXPECTED / TIMELINE'a eklenir."""
    out = {}
    for p in sorted(SYNTH_DIR.glob("*.manifest.json")) + sorted(EXTERNAL_DIR.glob("*.manifest.json")):
        for fn, m in json.loads(p.read_text(encoding="utf-8")).get("files", {}).items():
            out[fn] = m
            ev.EXPECTED[fn] = m.get("expected", "coklu")
            if m.get("timeline"):
                ev.TIMELINE[fn] = [(float(t), su) for t, su in m["timeline"]]
    return out


MANIFESTS = load_manifests()

_corpus = None
_aux = None


def corpus():
    global _corpus
    if _corpus is None:
        _corpus = QuranCorpus.load(imlaei=True)
    return _corpus


def aux():
    global _aux
    if _aux is None:
        _aux = sm.build_aux_maps(corpus())
    return _aux


# ---------------- TRJSON ----------------
def load_trjson(paths=None):
    """{config: {dosya: [[rms, metin, bitis_sn, duraklama_kesimi, son_kelime_sn, ctc_metni], ...]}}"""
    paths = paths or sorted(TRJSON_DIR.glob("*.trjson"))
    out = {}
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            i = line.find("TRJSON ")
            if i < 0:
                continue
            d = json.loads(line[i + 7:])
            chunks = [list(c) + [None] * (6 - len(c)) for c in d["chunks"]]
            out.setdefault(d["config"], {})[d["file"]] = chunks
    return out


def load_synth():
    """Sentetik kayitlarin transkriptleri (tests/trjson/synth/*.trjson) — gercek kayitlardan ayri olculur."""
    paths = sorted(SYNTH_DIR.glob("*.trjson"))
    return load_trjson(paths) if paths else {}


def load_external():
    """Dis kaynak kayitlarin transkriptleri (tests/trjson/external/*.trjson: Harem teravihleri, Turk kari, ezan)."""
    paths = sorted(EXTERNAL_DIR.glob("*.trjson"))
    return load_trjson(paths) if paths else {}


def write_trjson(path, recs):
    """recs: {config: {dosya: chunks}} → TRJSON satirlari (Kotlin JvmTests ayni bicimi okur)."""
    with open(path, "w", encoding="utf-8") as f:
        for cfg in sorted(recs):
            for fn in sorted(recs[cfg]):
                f.write("TRJSON " + json.dumps({"config": cfg, "file": fn, "chunks": recs[cfg][fn]},
                                                ensure_ascii=False) + "\n")


def chunk_time(c, k):
    return ev.chunk_time(c, k)


def run_sm(chunks, mod=None):
    """Parcalari state machine'den gecir → sonuc listesi."""
    mod = mod or sm
    st = mod.SessionState()
    a = aux()
    return [mod.process_chunk_simulated(c[0], c[1] or "", k, st, corpus(), *a) for k, c in enumerate(chunks)]


def decision_cell(k, r):
    """Kotlin JvmTests trace ile ayni (skorsuz) karar hucresi."""
    s = r["status"]
    if s == "matched":
        return f"{k}:M{r.get('first_surah')}:{r.get('first_ayah')}"
    if s == "pending":
        return (f"{k}:P{r.get('pending_surah', r.get('first_surah'))}:{r.get('pending_ayah', r.get('first_ayah'))}"
                + ("?" if r.get("ambiguous") else ""))
    return f"{k}:" + {"low_confidence": "L", "too_short": "S"}.get(s, "-")
