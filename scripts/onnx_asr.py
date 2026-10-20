#!/usr/bin/env python3
"""
ONNX ASR — Android OnnxAsrEngine.kt'nin Python referansi (CTC + RNNT greedy).

Model klasoru (onnx_full_export.py ciktisi / APK assets/asr):
  fastconformer_full.onnx (+ .data)  audio → logprobs (CTC) [+ enc_proj, enc_len (model v2+)]
  rnnt_decoder.onnx                  token + LSTM state → g (joint'e projekte) + yeni state
  rnnt_joint.onnx                    enc_proj[t] + g → logits (V+1)
  tokenizer.model, meta.json

RNNT greedy (NeMo GreedyRNNTInfer ile ayni sonuc):
  g, state = decoder(SOS=blank, sifir state)
  her t icin en fazla max_symbols kez:
      k = argmax joint(enc_proj[t], g)
      blank → sonraki frame (state DEGISMEZ)
      degilse → k'yi ekle, g, state = decoder(k, state)
"""

import json
import os
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

FRAME_SEC = 0.08   # encoder cikis frame'i: 10 ms hop x 8 alt ornekleme


class OnnxAsr:
    def __init__(self, model_dir: Path):
        import onnxruntime as ort
        import sentencepiece as spm

        model_dir = Path(model_dir)
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        # Ayni makinede birden cok eval paralel kosarken (training/evaluate.py) cekirdekleri paylastir
        threads = int(os.environ.get("TILAVET_ORT_THREADS", "0") or 0)
        if threads > 0:
            opts.intra_op_num_threads = threads
            opts.inter_op_num_threads = 1
        providers = ["CPUExecutionProvider"]
        self.sess = ort.InferenceSession(str(model_dir / "fastconformer_full.onnx"), opts, providers=providers)
        self.sp = spm.SentencePieceProcessor(model_file=str(model_dir / "tokenizer.model"))
        self.meta = json.loads((model_dir / "meta.json").read_text())
        self.blank = int(self.meta["blank_idx"])
        self.output_names = [o.name for o in self.sess.get_outputs()]

        rnnt = self.meta.get("rnnt")
        self.has_rnnt = (rnnt is not None and "enc_proj" in self.output_names
                         and (model_dir / "rnnt_decoder.onnx").exists()
                         and (model_dir / "rnnt_joint.onnx").exists())
        if self.has_rnnt:
            self.dec = ort.InferenceSession(str(model_dir / "rnnt_decoder.onnx"), opts, providers=providers)
            self.joint = ort.InferenceSession(str(model_dir / "rnnt_joint.onnx"), opts, providers=providers)
            self.pred_layers = int(rnnt["pred_layers"])
            self.pred_hidden = int(rnnt["pred_hidden"])
            self.max_symbols = int(rnnt["max_symbols"])

    # ------------------------------------------------------------
    def encode(self, audio: np.ndarray, outputs: List[str]):
        return self.sess.run(outputs, {
            "audio_signal": audio[np.newaxis, :].astype(np.float32),
            "length": np.array([len(audio)], dtype=np.int64),
        })

    def ctc_ids(self, logprobs: np.ndarray) -> List[int]:
        """logprobs (T, V+1) → argmax + CTC collapse (blank ve tekrar at)."""
        ids, prev = [], -1
        for t in logprobs.argmax(axis=-1):
            t = int(t)
            if t != self.blank and t != prev:
                ids.append(t)
            prev = t
        return ids

    def _pred(self, token: int, h: np.ndarray, c: np.ndarray):
        g, h2, c2 = self.dec.run(None, {
            "token": np.array([[token]], dtype=np.int64), "h_in": h, "c_in": c,
        })
        return g, h2, c2

    def rnnt_ids(self, enc_proj: np.ndarray, frames: Optional[List[int]] = None) -> List[int]:
        """enc_proj (T, J) → greedy RNNT token id'leri (frames verilirse her token'in frame'i eklenir)."""
        h = np.zeros((self.pred_layers, 1, self.pred_hidden), dtype=np.float32)
        c = np.zeros_like(h)
        g, h, c = self._pred(self.blank, h, c)      # SOS
        ids: List[int] = []
        for t in range(enc_proj.shape[0]):
            f = enc_proj[t][np.newaxis, np.newaxis, :]
            for _ in range(self.max_symbols):
                logits = self.joint.run(None, {"f": f, "g": g})[0]
                k = int(np.argmax(logits.reshape(-1)))
                if k == self.blank:
                    break
                ids.append(k)
                if frames is not None:
                    frames.append(t)
                g, h, c = self._pred(k, h, c)
        return ids

    def decode(self, ids: List[int]) -> str:
        return self.sp.decode_ids(ids).strip()

    def transcribe_timed(self, audio: np.ndarray, decoder: str = "ctc") -> Tuple[str, Optional[float]]:
        """transcribe + son token'in parca icindeki zamani (sn; token yoksa None).
        Encoder 8x alt ornekleme, 10 ms hop → frame = 80 ms. Eval'de "son kelime → ekran" gecikmesi icin."""
        has_len = "enc_len" in self.output_names
        frames: List[int] = []
        if decoder == "rnnt":
            if not self.has_rnnt:
                raise RuntimeError("Model RNNT parcalarini icermiyor (asr-model-v2+ gerekli)")
            out = self.encode(audio, ["enc_proj", "enc_len"] if has_len else ["enc_proj"])
            enc_proj = out[0][0]
            if has_len:
                enc_proj = enc_proj[:int(out[1][0])]
            ids = self.rnnt_ids(enc_proj, frames)
        else:
            out = self.encode(audio, ["logprobs", "enc_len"] if has_len else ["logprobs"])
            logprobs = out[0][0]
            if has_len:
                logprobs = logprobs[:int(out[1][0])]
            ids, prev = [], -1
            for t, k in enumerate(logprobs.argmax(axis=-1)):
                k = int(k)
                if k != self.blank and k != prev:
                    ids.append(k)
                    frames.append(t)
                prev = k
        text = self.decode(ids)
        return text, ((frames[-1] + 1) * FRAME_SEC if frames and text else None)

    def transcribe(self, audio: np.ndarray, decoder: str = "ctc") -> str:
        """
        Sadece gecerli frame'ler (enc_len) decode edilir — son frame padding olabilir,
        NeMo da oyle yapiyor. v1 modelde enc_len yok → tum frame'ler (eski davranis).
        """
        has_len = "enc_len" in self.output_names
        if decoder == "rnnt":
            if not self.has_rnnt:
                raise RuntimeError("Model RNNT parcalarini icermiyor (asr-model-v2+ gerekli)")
            out = self.encode(audio, ["enc_proj", "enc_len"] if has_len else ["enc_proj"])
            enc_proj = out[0][0]
            if has_len:
                enc_proj = enc_proj[:int(out[1][0])]
            return self.decode(self.rnnt_ids(enc_proj))
        out = self.encode(audio, ["logprobs", "enc_len"] if has_len else ["logprobs"])
        logprobs = out[0][0]
        if has_len:
            logprobs = logprobs[:int(out[1][0])]
        return self.decode(self.ctc_ids(logprobs))
