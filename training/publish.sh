#!/usr/bin/env bash
# Kabul edilen modeli GitHub release'ine yukle (kiralik makineden; gh CLI + repoya yazma izni gerekir):
#   gh auth login            # ya da: export GH_TOKEN=<repo yetkili token>
#   bash training/publish.sh v3
#
#   asr-model-<v>  : uygulamanin dosyalari (ONNX + tokenizer + meta) — android.yml / eval.yml MODEL_TAG bu olur
#   asr-train-<v>  : .nemo + egitim / degerlendirme raporlari (yeniden egitim, inceleme)
set -euo pipefail
cd "$(dirname "$0")/.."
V="${1:?surum ver: v3}"
WORK="${WORK:-$HOME/tilavet-train}"
REPO="${REPO:-mrcan321/quran-takip-public}"   # CI modeli bu repodaki release'ten indirir
M="$WORK/eval/cand/model"
for f in fastconformer_full.onnx fastconformer_full.onnx.data rnnt_decoder.onnx rnnt_joint.onnx tokenizer.model meta.json; do
  [ -f "$M/$f" ] || { echo "HATA: $M/$f yok (once run_all.sh eval)"; exit 1; }
done
gh release create "asr-model-$V" -R "$REPO" --title "ASR model $V (ince ayar)" --notes-file "$WORK/eval/summary.md" \
  "$M"/fastconformer_full.onnx "$M"/fastconformer_full.onnx.data "$M"/rnnt_decoder.onnx "$M"/rnnt_joint.onnx \
  "$M"/tokenizer.model "$M"/meta.json "$M"/export_report.txt
NEMO="$WORK/run/best.nemo"
[ -f "$NEMO" ] || NEMO="$WORK/run/final.nemo"
gh release create "asr-train-$V" -R "$REPO" --title "Ince ayar $V: .nemo + raporlar" --notes-file "$WORK/eval/summary.md" \
  "$NEMO" "$WORK/run/train_report.json" "$WORK/data/stats.json" "$WORK/data/stats_b.json" "$WORK/eval/summary.md"
echo "Yuklendi: asr-model-$V, asr-train-$V — Claude'a haber ver (MODEL_TAG degisecek, yeni APK)"
