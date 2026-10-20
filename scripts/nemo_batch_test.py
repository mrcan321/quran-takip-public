#!/usr/bin/env python3
"""
NeMo FastConformer Arabic — Batch test
---------------------------------------
Birden fazla ses dosyasını hem RNNT hem CTC decoder ile test eder.
"""
import argparse
import sys
import time
from pathlib import Path

import nemo.collections.asr as nemo_asr

MODEL_NAME = "nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0"


def transcribe_with_decoder(model, audio_files, decoder_type):
    """Belirli bir decoder ile transkripsiyon yap."""
    model.change_decoding_strategy(decoder_type=decoder_type)

    results = []
    for path in audio_files:
        t0 = time.time()
        output = model.transcribe([str(path)], verbose=False)
        elapsed = time.time() - t0

        if output and hasattr(output[0], "text"):
            text = output[0].text
        elif output and isinstance(output[0], str):
            text = output[0]
        elif output and isinstance(output[0], list):
            first = output[0][0] if output[0] else ""
            text = first.text if hasattr(first, "text") else str(first)
        else:
            text = str(output)

        results.append({
            "file": Path(path).name,
            "text": text.strip() if text else "(boş)",
            "time": elapsed,
        })
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_files", nargs="+")
    args = parser.parse_args()

    # Dosyaları kontrol et
    audio_paths = []
    for f in args.audio_files:
        p = Path(f)
        if not p.exists():
            print(f"✗ Bulunamadı: {f}", file=sys.stderr)
        else:
            audio_paths.append(p)

    if not audio_paths:
        sys.exit(1)

    # Modeli yükle
    print(f"Model yükleniyor: {MODEL_NAME}", file=sys.stderr)
    t0 = time.time()
    model = nemo_asr.models.EncDecHybridRNNTCTCBPEModel.from_pretrained(
        model_name=MODEL_NAME,
    )
    model = model.to("cpu")
    model.eval()
    print(f"Model hazır ({time.time() - t0:.1f} sn).\n", file=sys.stderr)

    # İki decoder ile sırayla test et
    for decoder in ["rnnt", "ctc"]:
        print(f"\n{'═' * 70}")
        print(f"  DECODER: {decoder.upper()}")
        print(f"{'═' * 70}")

        results = transcribe_with_decoder(model, audio_paths, decoder)

        for r in results:
            print(f"\n  📄 {r['file']}  ({r['time']:.2f} sn)")
            print(f"     {r['text']}")


if __name__ == "__main__":
    main()
