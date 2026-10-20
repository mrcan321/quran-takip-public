#!/usr/bin/env python3
"""
ONNX Export — FastConformer Hybrid (Preprocessor + Encoder + CTC head + RNNT parcalari)

NeMo `nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0` → ONNX. Android (OnnxAsrEngine.kt)
bu dosyalari assets/asr/ altinda bekler:

  fastconformer_full.onnx        graph (~3 MB): audio → logprobs (CTC) + enc_proj (RNNT joint'in
                                 encoder projeksiyonu, (B, T, J))
  fastconformer_full.onnx.data   weights (~440 MB) — isim ZORUNLU, graph icinde yazili
  rnnt_decoder.onnx              RNNT prediction network (LSTM) tek adim: token + (h, c) → g + (h, c)
  rnnt_joint.onnx                RNNT joint tek adim: enc_proj[t] + g → logits (V+1)
  tokenizer.model                SentencePiece (SentencePieceDecoder.kt okur)
  meta.json                      blank_idx, sample_rate, rnnt {pred_layers, pred_hidden, max_symbols}
  export_report.txt              NeMo (CTC + RNNT) vs ONNX karsilastirma raporu

RNNT greedy dongusu: scripts/onnx_asr.py (Kotlin port'u icin referans).
Neden RNNT: server/benchmark RNNT kullaniyor; CTC head ayni encoder'la bile kelime birlestirme
yapiyor (ihlas.wav: "الرحمن الرحيم" → "الرَّحْمَنَِّحِيمِ").

Calistirma:
  python scripts/onnx_full_export.py                          # cikti: <repo>/android-assets-staged/asr/
  python scripts/onnx_full_export.py --out-dir model-out      # CI
  python scripts/onnx_full_export.py --model-name org/model   # baska hibrit model (HF), ya da .nemo yolu / URL'si
  python scripts/onnx_full_export.py --quantize int8          # ana graph'in MatMul/Gemm agirliklari INT8 (dinamik)

ASR model yarisi (tests/asr_candidates.json, .github/workflows/asr-compare.yml) aday modelleri bu betikle export eder.

Android tarafi onnxruntime-android 1.18 kullaniyor → IR version en fazla 10.
Yeni onnx/torch surumleri daha yuksek IR yazabiliyor, export sonrasi 10'a cekiliyor.
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ============================================================
# Konfig
# ============================================================
REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_ROOT = Path(os.environ.get("TILAVET_ASSETS_DIR", REPO_ROOT / "android-assets-staged"))

DEFAULT_MODEL_NAME = "nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0"
DEFAULT_TEST_WAV = REPO_ROOT / "data" / "ihlas.wav"

ONNX_NAME = "fastconformer_full.onnx"
ONNX_DATA_NAME = "fastconformer_full.onnx.data"  # OnnxAsrEngine.kt ile ayni olmali
RNNT_DECODER_NAME = "rnnt_decoder.onnx"
RNNT_JOINT_NAME = "rnnt_joint.onnx"
SAMPLE_RATE = 16000

# onnxruntime-android 1.18 → ONNX 1.16 → IR version 10
MAX_IR_VERSION = 10


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ============================================================
# Wrapper module'ler
# ============================================================
class FullPipeline(nn.Module):
    """
    Input:  audio_signal (B, T_audio) float32 16kHz, length (B,) int64
    Output: logprobs (B, T, V+1)  — CTC
            enc_proj (B, T, J)    — RNNT joint'in encoder projeksiyonu (joint.project_encoder)
            enc_len  (B,)         — gecerli frame sayisi. T'den kucuk olabilir (son frame padding);
                                    NeMo decode'u sadece ilk enc_len frame'de yapar, biz de oyle.
    """
    def __init__(self, preprocessor, encoder, decoder_ctc, joint):
        super().__init__()
        self.preprocessor = preprocessor
        self.encoder = encoder
        self.decoder_ctc = decoder_ctc
        self.joint = joint

    def forward(self, audio_signal, length):
        # 1. Mel-spec: (B, T_audio) → (B, n_mels, T_frames)
        mel, mel_len = self.preprocessor(input_signal=audio_signal, length=length)
        # 2. Encoder: → (B, D, T_enc)
        enc_out, enc_len = self.encoder(audio_signal=mel, length=mel_len)
        # 3. CTC head (linear + log_softmax): → (B, T_enc, V+1)
        logprobs = self.decoder_ctc(encoder_output=enc_out)
        # 4. RNNT joint encoder projeksiyonu: (B, T_enc, D) → (B, T_enc, J)
        enc_proj = self.joint.project_encoder(enc_out.transpose(1, 2))
        return logprobs, enc_proj, enc_len


class RnntDecoderStep(nn.Module):
    """token (1,1) int64, h_in/c_in (L,1,H) → g (1,1,J), h_out, c_out"""
    def __init__(self, decoder, joint):
        super().__init__()
        self.decoder = decoder
        self.joint = joint

    def forward(self, token, h_in, c_in):
        g, hid = self.decoder.predict(token, [h_in, c_in], add_sos=False, batch_size=None)
        return self.joint.project_prednet(g), hid[0], hid[1]


class RnntJointStep(nn.Module):
    """f (1,1,J) = enc_proj[t], g (1,1,J) → logits (1,1,1,V+1)"""
    def __init__(self, joint):
        super().__init__()
        self.joint = joint

    def forward(self, f, g):
        return self.joint.joint_after_projection(f, g)


# ============================================================
# Yardimcilar
# ============================================================
def load_audio_16k(path: Path) -> np.ndarray:
    """WAV'i mono float32 16kHz olarak yukle (data/*.wav 48kHz, resample gerekir)."""
    import librosa
    audio, _ = librosa.load(str(path), sr=SAMPLE_RATE, mono=True)
    return audio.astype(np.float32)


def hyp_to_text(result) -> str:
    """NeMo transcribe() ciktisi surume gore degisiyor — hepsini metne cevir."""
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, list):
        if not result:
            return ""
        first = result[0]
        if isinstance(first, list):
            first = first[0] if first else ""
        if hasattr(first, "text"):
            return first.text
        return str(first)
    if hasattr(result, "text"):
        return result.text
    return str(result)


def nemo_transcribe(model, audio: np.ndarray, decoder_type: str) -> str:
    import soundfile as sf
    model.change_decoding_strategy(decoder_type=decoder_type)
    with tempfile.TemporaryDirectory() as tmp:
        wav16 = Path(tmp) / "test16k.wav"
        sf.write(str(wav16), audio, SAMPLE_RATE)
        with torch.no_grad():
            return hyp_to_text(model.transcribe([str(wav16)], verbose=False)).strip()


def rnnt_max_symbols(model) -> int:
    """RNNT greedy'nin frame basina en fazla token sayisi (NeMo decoding config'inden)."""
    model.change_decoding_strategy(decoder_type="rnnt")
    inner = getattr(getattr(model, "decoding", None), "decoding", None)
    for attr in ("max_symbols", "max_symbols_per_step"):
        v = getattr(inner, attr, None)
        if v is not None:
            return int(v)
    try:
        return int(model.cfg.decoding.greedy.max_symbols)
    except Exception:  # noqa: BLE001
        return 10


def export_module(module, args, raw_path: Path, input_names, output_names, dynamic_axes, attempts):
    """attempts: [(etiket, torch.onnx.export kwargs), ...] — ilk basarili olan kullanilir."""
    errors = []
    for label, kwargs in attempts:
        log(f"  Deneme: {label}")
        t0 = time.time()
        try:
            with torch.no_grad():
                torch.onnx.export(module, args, str(raw_path), input_names=input_names,
                                  output_names=output_names, dynamic_axes=dynamic_axes, **kwargs)
            log(f"  OK — {label} ({time.time() - t0:.0f}s)")
            return label
        except Exception as e:  # noqa: BLE001 — bir sonraki yolu dene
            log(f"  HATA ({label}): {type(e).__name__}: {str(e)[:2000]}")
            errors.append(f"{label}: {type(e).__name__}: {e}")
    raise RuntimeError("ONNX export basarisiz:\n" + "\n".join(errors))


DYNAMO_18 = ("dynamo opset 18", dict(opset_version=18, dynamo=True, external_data=True))
LEGACY_17 = ("legacy opset 17", dict(opset_version=17, dynamo=False, do_constant_folding=True))


def load_nemo_model(name: str):
    """NGC / HF model adi, .nemo dosya yolu ya da .nemo URL'si → NeMo modeli (CPU).

    Varsayilan NVIDIA modeli eskisi gibi from_pretrained ile (asr-model-v2 export'u degismesin). Baska bir HF deposu
    (org/ad) icin depodaki .nemo dosyasi bulunup indirilir: NeMo'nun from_pretrained'i dosya adinin depo adiyla ayni
    olmasini bekliyor, ince ayarli modellerde cogu zaman degil.
    """
    import nemo.collections.asr as nemo_asr

    cpu = torch.device("cpu")
    if name.startswith(("http://", "https://")):
        import urllib.request
        local = Path(tempfile.gettempdir()) / Path(name.split("?")[0]).name
        if not local.exists():
            log(f"  indiriliyor: {name}")
            urllib.request.urlretrieve(name, local)
        return nemo_asr.models.ASRModel.restore_from(str(local), map_location=cpu)
    if name.endswith(".nemo") and Path(name).exists():
        return nemo_asr.models.ASRModel.restore_from(name, map_location=cpu)
    if "/" in name and not name.startswith("nvidia/"):
        from huggingface_hub import hf_hub_download, list_repo_files
        nemo_files = sorted(f for f in list_repo_files(name) if f.endswith(".nemo"))
        if not nemo_files:
            log(f"HATA: {name} deposunda .nemo dosyasi yok")
            sys.exit(3)
        log(f"  HF: {name}/{nemo_files[0]}")
        local = hf_hub_download(repo_id=name, filename=nemo_files[0])
        return nemo_asr.models.ASRModel.restore_from(local, map_location=cpu)
    return nemo_asr.models.EncDecHybridRNNTCTCBPEModel.from_pretrained(model_name=name, map_location=cpu)


# Uthmani yazima ozgu isaretler: ust elif (U+0670), vasla elifi (U+0671), Uthmani sukun / kucuk harfler (U+06D6-U+06ED).
# Aligner'in korpusu imla'i (bkz. CLAUDE.md "Korpus normalized = imla'i"); Uthmani yazan bir modelde normalize_arabic
# ust elifi siler → "العلمين" / "العالمين" eslesmez.
UTHMANI_MARKS = {"\u0670": "ust elif", "\u0671": "vasla elifi"}


def script_marks(text: str) -> str:
    """Cikti yaziminin ozeti: Uthmani isaretlerinin sayisi + hareke var mi."""
    counts = {label: text.count(ch) for ch, label in UTHMANI_MARKS.items()}
    small = sum(1 for ch in text if "\u06d6" <= ch <= "\u06ed")
    harakat = sum(1 for ch in text if "\u064b" <= ch <= "\u0652")
    parts = [f"{k} {v}" for k, v in counts.items()] + [f"Uthmani kucuk isaret {small}", f"hareke {harakat}"]
    uthmani = counts["ust elif"] + counts["vasla elifi"] + small
    return ("UTHMANI? " if uthmani else "imla'i ") + ", ".join(parts)


def quantize_main_graph(out_dir: Path):
    """Ana graph'in (fastconformer_full.onnx + .data) MatMul / Gemm agirliklarini dinamik INT8'e cevirir, ayni dosya
    adlariyla yazar (Android ayni isimleri bekliyor). MatMulConstBOnly: sadece agirlikli MatMul'lar (dikkat skorlari
    gibi iki girdisi de dinamik olanlar fp32 kalir). Conv'lara dokunulmaz: bazi onnxruntime-android derlemelerinde
    ConvInteger yok.

    On isleyici (log-mel) fp32 kalir: graph'taki ilk Log dugumunun atalari haric tutulur. Mel filtre bankasinin MatMul'u
    INT8 olursa girdisi (guc spektrumu, cok genis dinamik aralik) tensor basina 8 bite sikisir, sessiz bantlar kaybolur."""
    import onnx
    from onnxruntime.quantization import QuantType, quantize_dynamic

    model = onnx.load(str(out_dir / ONNX_NAME), load_external_data=True)
    for i, n in enumerate(model.graph.node):
        if not n.name:
            n.name = f"n{i}_{n.op_type}"
    producer = {o: n for n in model.graph.node for o in n.output}
    first_log = next((n for n in model.graph.node if n.op_type == "Log"), None)
    ancestors, stack = set(), list(first_log.input) if first_log else []
    while stack:
        n = producer.get(stack.pop())
        if n is not None and n.name not in ancestors:
            ancestors.add(n.name)
            stack.extend(n.input)
    matmuls = [n.name for n in model.graph.node if n.op_type in ("MatMul", "Gemm")]
    exclude = sorted(nm for nm in matmuls if nm in ancestors)
    log(f"  MatMul/Gemm {len(matmuls)}, on isleyicide (fp32 kalir) {len(exclude)}")

    with tempfile.TemporaryDirectory() as tmp:
        named = Path(tmp) / "named.onnx"
        onnx.save_model(model, str(named), save_as_external_data=True, all_tensors_to_one_file=True,
                        location="named.onnx.data", size_threshold=1024)
        del model
        q_path = Path(tmp) / "q.onnx"
        quantize_dynamic(
            model_input=str(named),
            model_output=str(q_path),
            op_types_to_quantize=["MatMul", "Gemm"],
            nodes_to_exclude=exclude,
            weight_type=QuantType.QInt8,
            per_channel=False,
            use_external_data_format=True,
            extra_options={"MatMulConstBOnly": True},
        )
        finalize_onnx(q_path, out_dir / ONNX_NAME, ONNX_DATA_NAME)
    q = onnx.load(str(out_dir / ONNX_NAME), load_external_data=False)
    log(f"  INT8 MatMulInteger: {sum(1 for n in q.graph.node if n.op_type == 'MatMulInteger')}")


def finalize_onnx(raw_path: Path, final_path: Path, external_data_name=None):
    """
    Export ciktisini Android'in bekledigi formata getir:
      - IR version <= MAX_IR_VERSION
      - external_data_name verilmisse weights tek dosyada o isimle, yoksa tek dosya
    """
    import onnx

    model = onnx.load(str(raw_path), load_external_data=True)
    opsets = {o.domain or "ai.onnx": o.version for o in model.opset_import}
    log(f"  {final_path.name}: IR {model.ir_version}, opset {opsets}")
    if model.ir_version > MAX_IR_VERSION:
        log(f"  IR version {model.ir_version} → {MAX_IR_VERSION} (onnxruntime-android 1.18 uyumu)")
        model.ir_version = MAX_IR_VERSION

    targets = [final_path] + ([final_path.parent / external_data_name] if external_data_name else [])
    for p in targets:
        if p.exists():
            p.unlink()

    if external_data_name:
        onnx.save_model(model, str(final_path), save_as_external_data=True,
                        all_tensors_to_one_file=True, location=external_data_name, size_threshold=1024)
    else:
        onnx.save_model(model, str(final_path), save_as_external_data=False)
    # Buyuk model icin checker'a path ver (proto 2 GB sinirina takilmasin)
    onnx.checker.check_model(str(final_path))
    for p in targets:
        log(f"  {p.name}: {p.stat().st_size / 1024 / 1024:.1f} MB")
    return model.ir_version, opsets


# ============================================================
# Ana
# ============================================================
def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, default=ASSETS_ROOT / "asr",
                        help="Cikti klasoru (default: <repo>/android-assets-staged/asr)")
    parser.add_argument("--test-wav", type=Path, default=DEFAULT_TEST_WAV,
                        help="NeMo vs ONNX karsilastirma icin ses dosyasi")
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME,
                        help="NGC/HF model adi (org/ad), .nemo dosya yolu ya da .nemo URL'si")
    parser.add_argument("--quantize", default="none", choices=["none", "int8"],
                        help="int8: ana graph'in MatMul/Gemm agirliklari dinamik INT8 (Conv'a dokunulmaz)")
    args = parser.parse_args()

    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    report = []
    report.append("=" * 60)
    report.append("ONNX Export — Preprocessor + Encoder + CTC + RNNT (decoder, joint)")
    report.append("=" * 60)
    report.append(f"Tarih: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"Model: {args.model_name}")
    report.append(f"Quantize: {args.quantize}")
    report.append(f"torch {torch.__version__}")

    # 1. Test wav
    if not args.test_wav.exists():
        log(f"HATA: Test wav bulunamadi: {args.test_wav}")
        sys.exit(1)
    log(f"Test wav: {args.test_wav}")
    report.append(f"Test wav: {args.test_wav.name}")
    audio = load_audio_16k(args.test_wav)
    log(f"  {audio.shape[0] / SAMPLE_RATE:.1f}s @ {SAMPLE_RATE}Hz")

    # 2. NeMo modelini yukle
    log("NeMo modeli yukleniyor...")
    import nemo
    import nemo.collections.asr as nemo_asr
    report.append(f"nemo {nemo.__version__}")

    model = load_nemo_model(args.model_name)
    model.eval()
    if not (hasattr(model, "ctc_decoder") and hasattr(model, "joint") and hasattr(model, "decoder")):
        log(f"HATA: {type(model).__name__} hibrit (RNNT + CTC) model degil — Android zinciri ikisini de bekliyor")
        sys.exit(3)
    report.append(f"Model sinifi: {type(model).__name__}")

    # 3. NeMo referans transkripsiyonlari (ayni 16kHz audio ile)
    log("NeMo CTC referans...")
    ref_ctc = nemo_transcribe(model, audio, "ctc")
    log(f"  {ref_ctc[:120]}")
    log("NeMo RNNT referans...")
    ref_rnnt = nemo_transcribe(model, audio, "rnnt")
    log(f"  {ref_rnnt[:120]}")
    max_symbols = rnnt_max_symbols(model)
    report.append(f"NeMo CTC:  {ref_ctc}")
    report.append(f"NeMo RNNT: {ref_rnnt}")
    report.append(f"Cikti yazimi: {script_marks(ref_rnnt)}")

    # 4. RNNT boyutlari. SOS = blank token id: blank_as_pad embedding satiri sifir olmali
    #    (NeMo SOS icin sifir vektor kullaniyor) — garanti icin sifirla, blank asla decoder'a
    #    token olarak verilmedigi icin baska hicbir sey degismez.
    decoder, joint = model.decoder, model.joint
    blank = int(decoder.blank_idx)
    with torch.no_grad():
        decoder.prediction["embed"].weight[blank].zero_()
    pred_layers = int(decoder.pred_rnn_layers)
    pred_hidden = int(decoder.pred_hidden)
    joint_hidden = int(joint.joint_hidden)
    log(f"RNNT: blank={blank}, LSTM {pred_layers}x{pred_hidden}, joint {joint_hidden}, max_symbols={max_symbols}")

    # 5. Wrapper'lar
    full = FullPipeline(model.preprocessor, model.encoder, model.ctc_decoder, joint).eval()
    dec_step = RnntDecoderStep(decoder, joint).eval()
    joint_step = RnntJointStep(joint).eval()

    audio_tensor = torch.from_numpy(audio).unsqueeze(0)
    length_tensor = torch.tensor([audio.shape[0]], dtype=torch.long)
    with torch.no_grad():
        py_logprobs, py_enc_proj, py_enc_len = full(audio_tensor, length_tensor)
    log(f"PyTorch: logprobs {tuple(py_logprobs.shape)}, enc_proj {tuple(py_enc_proj.shape)}, "
        f"enc_len {int(py_enc_len[0])}")

    # 6. ONNX export (gecici klasore), sonra Android formatina getir
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        log("Ana graph export (birkac dakika surebilir)...")
        label = export_module(
            full, (audio_tensor, length_tensor), tmp / "full.onnx",
            ["audio_signal", "length"], ["logprobs", "enc_proj", "enc_len"],
            {"audio_signal": {0: "batch", 1: "audio_length"}, "length": {0: "batch"},
             "logprobs": {0: "batch", 1: "frames"}, "enc_proj": {0: "batch", 1: "frames"},
             "enc_len": {0: "batch"}},
            [DYNAMO_18, LEGACY_17])
        report.append(f"Ana graph export: {label}")
        ir, opsets = finalize_onnx(tmp / "full.onnx", out_dir / ONNX_NAME, ONNX_DATA_NAME)
        report.append(f"Ana graph: IR {ir}, opset {opsets}")

        log("RNNT decoder export...")
        tok = torch.tensor([[blank]], dtype=torch.long)
        h0 = torch.zeros(pred_layers, 1, pred_hidden)
        label = export_module(
            dec_step, (tok, h0, h0.clone()), tmp / "dec.onnx",
            ["token", "h_in", "c_in"], ["g", "h_out", "c_out"], None,
            [LEGACY_17, ("dynamo opset 18", dict(opset_version=18, dynamo=True, external_data=False))])
        report.append(f"RNNT decoder export: {label}")
        finalize_onnx(tmp / "dec.onnx", out_dir / RNNT_DECODER_NAME)

        log("RNNT joint export...")
        f0 = py_enc_proj[:, :1, :].contiguous()
        with torch.no_grad():
            g0, _, _ = dec_step(tok, h0, h0.clone())
        label = export_module(
            joint_step, (f0, g0), tmp / "joint.onnx",
            ["f", "g"], ["logits"], None,
            [LEGACY_17, ("dynamo opset 18", dict(opset_version=18, dynamo=True, external_data=False))])
        report.append(f"RNNT joint export: {label}")
        finalize_onnx(tmp / "joint.onnx", out_dir / RNNT_JOINT_NAME)

    # 7. Tokenizer + meta
    log("Tokenizer ve meta kaydediliyor...")
    sp = model.tokenizer.tokenizer if hasattr(model.tokenizer, "tokenizer") else model.tokenizer
    (out_dir / "tokenizer.model").write_bytes(sp.serialized_model_proto())
    vocab_size = sp.get_piece_size()
    if vocab_size != blank:
        log(f"UYARI: vocab_size {vocab_size} != RNNT blank {blank}")
    meta = {
        "model_name": "fastconformer_full",
        "vocab_size": vocab_size,
        "blank_idx": vocab_size,  # CTC ve RNNT blank = son indeks
        "sample_rate": SAMPLE_RATE,
        "export_id": time.strftime("%Y%m%d-%H%M%S"),
        "source_model": args.model_name,
        "quantize": args.quantize,
        "rnnt": {
            "pred_layers": pred_layers,
            "pred_hidden": pred_hidden,
            "joint_hidden": joint_hidden,
            "max_symbols": max_symbols,
        },
    }
    with open(out_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    report.append(f"Vocab: {vocab_size}, blank: {blank}, RNNT: LSTM {pred_layers}x{pred_hidden}, "
                  f"joint {joint_hidden}, max_symbols {max_symbols}")

    # 8. Dogrulama — Android'in yukleyecegi dosyalarla (scripts/onnx_asr.py = OnnxAsrEngine referansi)
    log("ONNX dogrulama...")
    from onnx_asr import OnnxAsr
    asr = OnnxAsr(out_dir)
    logprobs, enc_proj, enc_len = asr.encode(audio, ["logprobs", "enc_proj", "enc_len"])
    n = int(enc_len[0])
    log(f"  enc_len ONNX {n}, PyTorch {int(py_enc_len[0])}, frame {logprobs.shape[1]}")
    d1 = float(np.max(np.abs(logprobs - py_logprobs.numpy())))
    d2 = float(np.max(np.abs(enc_proj - py_enc_proj.numpy())))
    log(f"  PyTorch vs ONNX max fark: logprobs {d1:.2e}, enc_proj {d2:.2e}")
    report.append(f"PyTorch vs ONNX max fark: logprobs {d1:.2e}, enc_proj {d2:.2e}")

    onnx_ctc = asr.decode(asr.ctc_ids(logprobs[0][:n]))
    onnx_rnnt = asr.decode(asr.rnnt_ids(enc_proj[0][:n]))
    ctc_ok = onnx_ctc == ref_ctc
    rnnt_ok = onnx_rnnt == ref_rnnt
    log(f"  ONNX CTC:  {onnx_ctc[:120]}  → NeMo ile {'✓ AYNI' if ctc_ok else '✗ FARKLI'}")
    log(f"  ONNX RNNT: {onnx_rnnt[:120]}  → NeMo ile {'✓ AYNI' if rnnt_ok else '✗ FARKLI'}")
    report.append(f"ONNX CTC:  {onnx_ctc}")
    report.append(f"ONNX RNNT: {onnx_rnnt}")
    report.append(f"NeMo ile ayni mi: CTC {'EVET' if ctc_ok else 'HAYIR'}, RNNT {'EVET' if rnnt_ok else 'HAYIR'}")

    # 9. 5sn chunk hizi (streaming senaryosu)
    chunk = audio[:SAMPLE_RATE * 5]
    for dec_name in ("ctc", "rnnt"):
        times = []
        for _ in range(4):
            t0 = time.time()
            asr.transcribe(chunk, dec_name)
            times.append(time.time() - t0)
        med = float(np.median(times[1:]))
        log(f"  5sn {dec_name}: {med * 1000:.0f}ms (RTF {med / 5:.4f})")
        report.append(f"5sn chunk {dec_name}: {med * 1000:.0f}ms (RTF {med / 5:.4f})")

    # 10. INT8 (istege bagli): fp32 graph NeMo ile dogrulandiktan sonra ana graph'in agirliklari INT8'e. Cikti NeMo'dan
    #     biraz farkli olabilir — burada sadece raporlanir; karar ASR model yarisinda (gercek kayitlarla) verilir.
    if args.quantize == "int8":
        log("INT8 (dinamik, MatMul/Gemm)...")
        quantize_main_graph(out_dir)
        asr = OnnxAsr(out_dir)
        q_logprobs, q_enc_proj, q_enc_len = asr.encode(audio, ["logprobs", "enc_proj", "enc_len"])
        qn = int(q_enc_len[0])
        q_ctc = asr.decode(asr.ctc_ids(q_logprobs[0][:qn]))
        q_rnnt = asr.decode(asr.rnnt_ids(q_enc_proj[0][:qn]))
        log(f"  INT8 CTC:  {q_ctc[:120]}  → fp32 ile {'✓ AYNI' if q_ctc == onnx_ctc else '✗ FARKLI'}")
        log(f"  INT8 RNNT: {q_rnnt[:120]}  → fp32 ile {'✓ AYNI' if q_rnnt == onnx_rnnt else '✗ FARKLI'}")
        report.append(f"INT8 CTC:  {q_ctc}")
        report.append(f"INT8 RNNT: {q_rnnt}")
        report.append(f"INT8 fp32 ile ayni mi: CTC {'EVET' if q_ctc == onnx_ctc else 'HAYIR'}, "
                      f"RNNT {'EVET' if q_rnnt == onnx_rnnt else 'HAYIR'}")
        for dec_name in ("ctc", "rnnt"):
            times = []
            for _ in range(4):
                t0 = time.time()
                asr.transcribe(chunk, dec_name)
                times.append(time.time() - t0)
            med = float(np.median(times[1:]))
            log(f"  INT8 5sn {dec_name}: {med * 1000:.0f}ms (RTF {med / 5:.4f})")
            report.append(f"INT8 5sn chunk {dec_name}: {med * 1000:.0f}ms (RTF {med / 5:.4f})")

    report.append("")
    report.append("SONUC: " + ("✓ Export basarili, CTC ve RNNT NeMo ile ayni"
                              if ctc_ok and rnnt_ok else "Export OK ama cikti NeMo'dan farkli — incele"))
    (out_dir / "export_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    for f in sorted(out_dir.iterdir()):
        log(f"  {f.name}: {f.stat().st_size / 1024 / 1024:.2f} MB")
    if not (ctc_ok and rnnt_ok):
        sys.exit(2)


if __name__ == "__main__":
    main()
