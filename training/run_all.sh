#!/usr/bin/env bash
# Kiralik GPU makinesinde tek komut: kurulum → veri (A) → etiket dogrulama / hizalama (B) → ince ayar (C) →
# temel modelle karsilastirma (D). Ayrinti: training/README.md
#
#   bash training/run_all.sh --smoke                  # once bu (~30-45 dk): tum boru hatti kucuk veriyle
#   bash training/run_all.sh                          # tam kosu (~4-8 sa, A100 / H100)
#   bash training/run_all.sh --stages train,eval      # kaldigi yerden (asamalar: setup,data,labels,train,eval)
#   WORK=/mnt/disk/tt bash training/run_all.sh        # calisma klasoru (varsayilan ~/tilavet-train, >= 80 GB bos yer)
#
# Sonuc: $WORK/eval/summary.md (kabul sarti tablosu) — bu dosyayi gonder. Kabul edilirse: bash training/publish.sh
set -euo pipefail
cd "$(dirname "$0")/.."

WORK="${WORK:-$HOME/tilavet-train}"
SMOKE=0
STAGES="setup,data,labels,train,eval"
TRAIN_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --smoke) SMOKE=1 ;;
    --work) WORK="$2"; shift ;;
    --stages) STAGES="$2"; shift ;;
    --epochs) TRAIN_ARGS+=(--epochs "$2"); shift ;;
    --lr) TRAIN_ARGS+=(--lr "$2"); shift ;;
    --freeze) TRAIN_ARGS+=(--freeze-encoder-layers "$2"); shift ;;
    *) echo "bilinmeyen secenek: $1"; exit 1 ;;
  esac
  shift
done
[ "$SMOKE" = 1 ] && WORK="${WORK%/}-smoke"
mkdir -p "$WORK/logs"
VENV="$WORK/venv"
PY="$VENV/bin/python"
has() { [[ ",$STAGES," == *",$1,"* ]]; }
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$WORK/logs/run_all.log"; }
step() { local name="$1"; shift; log "$name basliyor"; "$@" 2>&1 | tee "$WORK/logs/$name.log"; log "$name bitti"; }
SM=()
[ "$SMOKE" = 1 ] && SM=(--smoke)

if has setup; then
  log "kurulum → $WORK"
  nvidia-smi || log "UYARI: nvidia-smi yok — GPU gorunmuyor (egitim CPU'da cok yavas olur)"
  if command -v apt-get >/dev/null && [ "$(id -u)" = 0 ]; then
    apt-get update -qq && apt-get install -y -qq ffmpeg libsndfile1 openjdk-17-jdk-headless unzip curl >/dev/null || \
      log "UYARI: apt paketleri kurulamadi (ffmpeg / java olmadan da calisir)"
  fi
  if [ ! -x "$PY" ]; then
    python3 -m venv "$VENV" || { log "HATA: python3 -m venv (apt install python3-venv)"; exit 1; }
  fi
  "$VENV/bin/pip" install -q --upgrade pip
  # CUDA 12.6 tekerlekleri: surucu >= 525 yeter. Yeni surucu ve H100 icin TORCH_INDEX=.../whl/cu128 de olur.
  "$VENV/bin/pip" install -q torch==2.11.0 --index-url "${TORCH_INDEX:-https://download.pytorch.org/whl/cu126}"
  "$VENV/bin/pip" install -q -r training/requirements.txt
  if ! command -v gradle >/dev/null && [ ! -x "$WORK/gradle-8.7/bin/gradle" ]; then
    curl -sSL -o "$WORK/gradle.zip" https://services.gradle.org/distributions/gradle-8.7-bin.zip && \
      unzip -q -o "$WORK/gradle.zip" -d "$WORK" || log "UYARI: gradle indirilemedi (Kotlin test kumesi atlanir)"
  fi
  "$PY" - <<'EOF'
import torch, nemo
print("torch", torch.__version__, "| CUDA", torch.cuda.is_available(),
      "|", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "-", "| NeMo", nemo.__version__)
EOF
fi
export PATH="$WORK/gradle-8.7/bin:$PATH"

# Ses kayitlari ozel repoda (kod herkese acik): gercek namazlar egitimin train bolumu + degerlendirmenin data kumesi
if ! ls data/*.wav >/dev/null 2>&1; then
  if [ -n "${KAYIT_TOKEN:-}" ]; then
    log "ses kayitlari ozel repodan cekiliyor"
    bash tools/kayitlari_cek.sh
  else
    log "UYARI: data/*.wav yok ve KAYIT_TOKEN verilmedi — gercek kayitlar olmadan (degerlendirmenin data kumesi bos)"
  fi
fi

# GPU bellegine gore dinamik paket (toplam ses saniyesi / paket)
MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -dc 0-9 || true)
MEM=${MEM:-0}
if [ "$MEM" -ge 70000 ]; then LB=900; elif [ "$MEM" -ge 38000 ]; then LB=500; elif [ "$MEM" -ge 22000 ]; then LB=250
else LB=120; fi
NPROC=$(nproc)

if has data; then
  step data "$PY" training/build_dataset.py --out "$WORK/data" --cache "$WORK/cache" --workers "$NPROC" "${SM[@]}"
fi
if has labels; then
  step labels "$PY" training/prepare_labels.py --data "$WORK/data" --cache "$WORK/cache"
fi
if has train; then
  log "GPU bellegi ${MEM} MB → paket ${LB} sn ses"
  step train "$PY" training/finetune.py --data "$WORK/data" --out "$WORK/run" --lhotse-batch-duration "$LB" \
    --workers 8 "${TRAIN_ARGS[@]}" "${SM[@]}"
fi
if has eval; then
  MODEL="$WORK/run/best.nemo"
  [ -f "$MODEL" ] || MODEL="$WORK/run/final.nemo"
  step eval "$PY" training/evaluate.py --model "$MODEL" --work "$WORK/eval" --cache "$WORK/cache" "${SM[@]}"
fi
log "TAMAM. Ozet: $WORK/eval/summary.md · egitim raporu: $WORK/run/train_report.json · veri: $WORK/data/stats_b.json"
