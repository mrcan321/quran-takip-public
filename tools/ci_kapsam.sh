#!/usr/bin/env bash
# CI kapsami: degisen dosyalara gore hangi testler kosar (kullanici: "goruntu / kullanim yeniligiyse ses tanima / kilit
# testlerini bosuna kosma; o konularda iyilestirme varsa CI'da kos").
#
#   recog=true  ses tanima, ayete kilitlenme, state machine, test verisi (scripts/, server/, tests/, uygulamanin
#               session / aligner / audio / asr kodu — JVM testlerinin derledigi kisim) → tum test kapisi
#   g2=true     G2 eklentisi / koprusu (assets/g2, glasses/, g2-plugin, tests/g2) ve secilebilir mealler (build_meals.py,
#               MealLoader / MealCatalog — telefon ve gozluk ekrani) → g2 + glasses kumeleri + simulator
#   ikisi de    false → test yok (arayuz degisikligi: APK derlemesi zaten Kotlin'i derler; APK sadece onayla — [apk])
#
# Kullanim: bash tools/ci_kapsam.sh <taban-commit> "<commit mesaji>" <varsayilan-dal> <olay>
#   taban bos / 000.. / bilinmiyorsa varsayilan dalla ortak ataya gore; o da yoksa hepsi. Mesajda [tam-test] ya da olay
#   workflow_dispatch → hepsi ([tam-test] sadece commit basliginda — govdede kurali anlatan yazi tetiklemesin).
#   GITHUB_OUTPUT varsa recog= g2= suites= oraya yazilir.
set -euo pipefail
BASE="${1:-}"
MSG="${2:-}"
DEFAULT="${3:-main}"
EVENT="${4:-push}"
HEAD_REF="${KAPSAM_HEAD:-HEAD}"   # denemek icin: KAPSAM_HEAD=<commit>

ALL_SUITES="replay,stress,compose,external,synth,signals,app,kotlin,g2"
G2_SUITES="g2,glasses"
G2_RE='^(tilavet-android/app/src/main/assets/g2/|tilavet-android/app/src/main/java/com/tilavet/takip/glasses/|tilavet-android/g2-plugin/|tests/g2/|tests/jvm/src/main/kotlin/(Glasses|Meal)Tests\.kt$|tests/lib/g2\.py$|scripts/build_meals\.py$|tilavet-android/app/src/main/java/com/tilavet/takip/data/Meal(Loader|Catalog)\.kt$)'
RECOG_RE='^(scripts/|server/|tests/|tilavet-android/app/src/main/java/com/tilavet/takip/(session|aligner|audio|asr)/|tools/kayitlari_cek\.sh$|\.github/workflows/tests\.yml$)'

out() {
  echo "recog=$1"; echo "g2=$2"; echo "suites=$3"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    { echo "recog=$1"; echo "g2=$2"; echo "suites=$3"; } >> "$GITHUB_OUTPUT"
  fi
}

SUBJECT="${MSG%%$'\n'*}"
if [ "$EVENT" = workflow_dispatch ] || [[ "$SUBJECT" == *"[tam-test]"* ]]; then
  echo "kapsam: hepsi ($EVENT${MSG:+, mesaj})"
  out true true "$ALL_SUITES"
  exit 0
fi
if [ -z "$BASE" ] || [ "$BASE" = 0000000000000000000000000000000000000000 ] || ! git cat-file -e "$BASE^{commit}" 2>/dev/null; then
  BASE="$(git merge-base "origin/$DEFAULT" "$HEAD_REF" 2>/dev/null || true)"
fi
if [ -z "$BASE" ]; then
  echo "kapsam: taban commit bulunamadi → hepsi"
  out true true "$ALL_SUITES"
  exit 0
fi
FILES="$(git diff --name-only "$BASE" "$HEAD_REF")"
echo "degisen dosyalar ($BASE..$HEAD_REF):"
echo "$FILES" | sed 's/^/  /'
G2=false
RECOG=false
if echo "$FILES" | grep -qE "$G2_RE"; then G2=true; fi
# tests/baseline.json notr: G2 degisikligi de sayaclari (g2_passed, glasses_passed) gunceller
if echo "$FILES" | grep -E "$RECOG_RE" | grep -vE "$G2_RE" | grep -qvxF "tests/baseline.json"; then RECOG=true; fi
if [ "$RECOG" = true ]; then
  out true "$G2" "$ALL_SUITES"
elif [ "$G2" = true ]; then
  out false true "$G2_SUITES"
else
  out false false ""
fi
