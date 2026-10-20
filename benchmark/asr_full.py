"""
Tam ASR benchmark - 20 klip x 3 model.
Ground truth ile karsilastirma + WER hesaplama.
"""
import json
import sys
import time
import warnings
import re
import unicodedata
from pathlib import Path
import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore")

SAMPLE_RATE = 16000
MANIFEST = Path.home() / "projects/benchmark/benchmark_workspace/dataset/manifest.jsonl"
OUTPUT_DIR = Path.home() / "projects/quran-asr/benchmark"
OUTPUT_DIR.mkdir(exist_ok=True)


def now():
    return time.strftime("%H:%M:%S")


def log(msg):
    print(f"[{now()}] {msg}", flush=True)


# ============================================================
# Arapca normalizasyon (WER hesaplama icin)
# ============================================================
ARABIC_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u06D6-\u06ED]")
TATWEEL = "\u0640"


def normalize_arabic(text):
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = ARABIC_DIACRITICS.sub("", text)
    text = text.replace(TATWEEL, "")
    text = re.sub(r"[إأآا]", "ا", text)
    text = re.sub(r"ى", "ي", text)
    text = re.sub(r"ة", "ه", text)
    text = re.sub(r"ؤ", "و", text)
    text = re.sub(r"ئ", "ي", text)
    text = text.replace("ء", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def wer(reference, hypothesis):
    ref_words = normalize_arabic(reference).split()
    hyp_words = normalize_arabic(hypothesis).split()
    if not ref_words:
        return 1.0 if hyp_words else 0.0
    n, m = len(ref_words), len(hyp_words)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                d[i][j] = 1 + min(d[i - 1][j], d[i][j - 1], d[i - 1][j - 1])
    return d[n][m] / n


# ============================================================
# Manifest yukle
# ============================================================
log("Manifest yukleniyor...")
clips = []
with open(MANIFEST) as f:
    for line in f:
        if line.strip():
            clips.append(json.loads(line))
log(f"{len(clips)} klip yuklendi")


def load_audio(wav_path):
    audio, sr = sf.read(wav_path)
    if sr != SAMPLE_RATE:
        log(f"  UYARI: SR={sr}, beklenen {SAMPLE_RATE}")
    if len(audio.shape) > 1:
        audio = audio.mean(axis=1)
    return audio.astype(np.float32)


all_results = {}


def benchmark_model(model_name, transcribe_fn):
    log(f"\n{'='*70}")
    log(f"  {model_name}")
    log('='*70)

    results = {}
    for clip in clips:
        clip_id = clip["clip_id"]
        audio = load_audio(clip["audio_path"])
        duration = len(audio) / SAMPLE_RATE

        log(f"  {clip_id} ({clip['condition']}, {duration:.1f}s) transkribe...")
        t0 = time.time()
        try:
            text = transcribe_fn(audio)
        except Exception as e:
            text = f"[HATA: {e}]"
        elapsed = time.time() - t0

        w = wer(clip["ground_truth_text"], text)
        rtf = elapsed / duration if duration > 0 else 0

        results[clip_id] = {
            "text": text,
            "wer": w,
            "time": elapsed,
            "duration": duration,
            "rtf": rtf,
            "condition": clip["condition"],
            "reciter": clip["reciter_key"],
        }
        log(f"    {elapsed:.1f}s | WER={w:.2%} | RTF={rtf:.3f}")

    return results


# ============================================================
# Model 1: FastConformer
# ============================================================
log("\n>>> Model 1: FastConformer Large yukleniyor...")
t0 = time.time()
import nemo.collections.asr as nemo_asr
import logging
logging.getLogger("nemo_logger").setLevel(logging.ERROR)
fc_model = nemo_asr.models.EncDecHybridRNNTCTCBPEModel.from_pretrained(
    "nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0"
).to("cpu")
fc_model.eval()
fc_model.change_decoding_strategy(decoder_type="rnnt")
log(f"Yuklendi: {time.time() - t0:.1f}s")

import tempfile


def transcribe_fc(audio):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, audio, SAMPLE_RATE)
        tmp_path = tmp.name
    try:
        out = fc_model.transcribe([tmp_path], verbose=False)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    if out and hasattr(out[0], "text"):
        return out[0].text.strip()
    return str(out[0]).strip() if out else ""


all_results["FastConformer"] = benchmark_model("FastConformer Large", transcribe_fc)
del fc_model
import gc
gc.collect()


# ============================================================
# Model 2: Tarteel Whisper-tiny
# (Eski generation_config icin: forced_decoder_ids generate'e gecirilmiyor,
#  modelin config dictionarysine direkt set ediliyor)
# ============================================================
log("\n>>> Model 2: Tarteel Whisper-tiny yukleniyor...")
t0 = time.time()
from transformers import WhisperProcessor, WhisperForConditionalGeneration
import torch

W_TINY_ID = "tarteel-ai/whisper-tiny-ar-quran"
w_proc = WhisperProcessor.from_pretrained(W_TINY_ID)
w_model = WhisperForConditionalGeneration.from_pretrained(W_TINY_ID)
w_model.eval()

# Eski generation config'e dogrudan forced_decoder_ids set et
# Bu transformers 4.57 ile uyumlu (lang_to_id mapping'i gerektirmiyor)
forced_ids = w_proc.get_decoder_prompt_ids(language="arabic", task="transcribe")
w_model.config.forced_decoder_ids = forced_ids
w_model.generation_config.forced_decoder_ids = forced_ids
# Dil ve task config'inden sil ki "outdated" kontrolune takilmasin
if hasattr(w_model.generation_config, "language"):
    w_model.generation_config.language = None
if hasattr(w_model.generation_config, "task"):
    w_model.generation_config.task = None

log(f"Yuklendi: {time.time() - t0:.1f}s")


def transcribe_w_tiny(audio):
    inputs = w_proc(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt")
    with torch.no_grad():
        pred_ids = w_model.generate(inputs.input_features)
    return w_proc.batch_decode(pred_ids, skip_special_tokens=True)[0].strip()


all_results["Whisper-tiny-Tarteel"] = benchmark_model("Whisper-tiny (Tarteel)", transcribe_w_tiny)
del w_model, w_proc
gc.collect()


# ============================================================
# Model 3: faster-whisper Tarteel base
# ============================================================
log("\n>>> Model 3: faster-whisper Tarteel base yukleniyor...")
t0 = time.time()
from faster_whisper import WhisperModel
fw_model = WhisperModel("OdyAsh/faster-whisper-base-ar-quran", device="cpu", compute_type="int8")
log(f"Yuklendi: {time.time() - t0:.1f}s")


def transcribe_fw(audio):
    segments, _ = fw_model.transcribe(audio, language="ar", beam_size=1)
    return " ".join(s.text for s in segments).strip()


all_results["faster-whisper-base-Tarteel"] = benchmark_model("faster-whisper-base (Tarteel)", transcribe_fw)
del fw_model
gc.collect()


# ============================================================
# Model 4: Tadabur Whisper-Small
# ============================================================
log("\n>>> Model 4: Tadabur Whisper-Small yukleniyor (970MB)...")
t0 = time.time()
TADABUR_ID = "FaisaI/Tadabur-Whisper-Small"
try:
    td_proc = WhisperProcessor.from_pretrained(TADABUR_ID)
    td_model = WhisperForConditionalGeneration.from_pretrained(TADABUR_ID)
    td_model.eval()
    # Yeni model olabilir, generation_config moderni anlayabilir
    try:
        td_model.generation_config.language = "arabic"
        td_model.generation_config.task = "transcribe"
        if hasattr(td_model.generation_config, "forced_decoder_ids"):
            td_model.generation_config.forced_decoder_ids = None
        TD_USE_NEW_API = True
    except Exception:
        TD_USE_NEW_API = False
        td_forced = td_proc.get_decoder_prompt_ids(language="arabic", task="transcribe")
        td_model.config.forced_decoder_ids = td_forced
        td_model.generation_config.forced_decoder_ids = td_forced
    log(f"Yuklendi: {time.time() - t0:.1f}s")

    def transcribe_td(audio):
        inputs = td_proc(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt")
        with torch.no_grad():
            pred_ids = td_model.generate(inputs.input_features)
        return td_proc.batch_decode(pred_ids, skip_special_tokens=True)[0].strip()

    all_results["Tadabur-Whisper-Small"] = benchmark_model("Tadabur Whisper-Small", transcribe_td)
    del td_model, td_proc
    gc.collect()
except Exception as e:
    log(f"Tadabur yuklenemedi: {e}")
    all_results["Tadabur-Whisper-Small"] = {}


# ============================================================
# Sonuclari kaydet
# ============================================================
log("\nSonuclar kaydediliyor...")
out_json = OUTPUT_DIR / "full_results.json"
with open(out_json, "w") as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2)
log(f"  JSON: {out_json}")


# ============================================================
# Ozet raporlar
# ============================================================
print("\n\n" + "=" * 90, flush=True)
print("  GENEL OZET", flush=True)
print("=" * 90, flush=True)
print(f"{'Model':<35} {'Avg WER':>10} {'Avg RTF':>10} {'Median WER':>12}", flush=True)
print("-" * 90, flush=True)
for model_name, results in all_results.items():
    if not results:
        print(f"{model_name:<35} (sonuc yok)", flush=True)
        continue
    wers = [r["wer"] for r in results.values()]
    rtfs = [r["rtf"] for r in results.values()]
    print(f"{model_name:<35} {np.mean(wers):>9.2%} {np.mean(rtfs):>9.3f} {np.median(wers):>11.2%}", flush=True)


# Kosul ve hafiz bazinda ozet
def report_by_key(key_name, key_func):
    print(f"\n" + "=" * 90, flush=True)
    print(f"  {key_name.upper()} BAZINDA WER", flush=True)
    print("=" * 90, flush=True)
    first_model_results = next((r for r in all_results.values() if r), {})
    keys = sorted(set(key_func(r) for r in first_model_results.values()))
    print(f"{'Model':<35} " + "".join(f"{k[:10]:>12}" for k in keys), flush=True)
    print("-" * 90, flush=True)
    for model_name, results in all_results.items():
        if not results:
            continue
        row = f"{model_name:<35} "
        for k in keys:
            kw = [r["wer"] for r in results.values() if key_func(r) == k]
            row += f"{np.mean(kw):>11.2%} " if kw else f"{'-':>11} "
        print(row, flush=True)

report_by_key("kosul", lambda r: r["condition"])
report_by_key("hafiz", lambda r: r["reciter"])


# Klip detayi
print("\n" + "=" * 90, flush=True)
print("  KLIP BAZINDA DETAY", flush=True)
print("=" * 90, flush=True)
for clip in clips:
    cid = clip["clip_id"]
    print(f"\n  {cid} ({clip['condition']}, {clip['reciter_key']}, {clip['duration_sec']:.1f}s)", flush=True)
    print(f"    GT: {clip['ground_truth_text'][:80]}...", flush=True)
    for model_name, results in all_results.items():
        if cid in results:
            r = results[cid]
            print(f"    [{model_name[:25]:<25}] WER={r['wer']:.2%} | {r['text'][:80]}", flush=True)


print("\nTamamlandi.", flush=True)
