#!/usr/bin/env bash
# Ses kayitlarini (data/*.wav, server/recordings/*.wav) ozel repodan bu klasore ceker.
#
# Kod herkese acik repoda (mrcan321/quran-takip-public — Actions dakikasi ucretsiz), cami / telefon kayitlari ozel
# repoda (mrcan321/quran-takip): imamin, cemaatin ve ailenin sesi herkese acilmasin. Public repoda .gitignore bu
# klasorlerdeki ses dosyalarini disarida tutar.
#
#   CI:        her is akisinda checkout'tan sonra (env KAYIT_TOKEN: secrets.KAYIT_TOKEN)
#   yerelde /  KAYIT_TOKEN=<fine-grained token: sadece ozel repo, Contents read-only> bash tools/kayitlari_cek.sh
#   kiralik makine
#
# KAYIT_REPO / KAYIT_REF ile kaynak degisir (varsayilan: ozel repodaki gelistirme dali — yeni kayitlar oraya eklenir).
# Var olan ayni adli dosyalarin ustune yazar, baska dosyalara dokunmaz. Token diske yazilmaz (gecici klonun
# ayari, cikista silinir).
set -euo pipefail
cd "$(dirname "$0")/.."

TOKEN="${KAYIT_TOKEN:-}"
REPO="${KAYIT_REPO:-mrcan321/quran-takip}"
REF="${KAYIT_REF:-claude/vigilant-davinci-emx2rt}"
DIRS=(data server/recordings)

hata() {
  if [ "${GITHUB_ACTIONS:-}" = true ]; then echo "::error::$*"; else echo "HATA: $*" >&2; fi
  exit 1
}
[ -n "$TOKEN" ] || hata "KAYIT_TOKEN yok — ses kayitlari ozel repoda ($REPO). CI: repo Settings → Secrets and variables → Actions → KAYIT_TOKEN (fine-grained token, sadece $REPO, Contents: Read-only). Fork'tan gelen PR'larda secret verilmez."

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
AUTH="Authorization: Basic $(printf 'x-access-token:%s' "$TOKEN" | base64 | tr -d '\n')"

# Sadece ses klasorleri: sig klon + blob'suz + seyrek → sadece data/ ve server/recordings/ dosyalari iner
for i in 1 2 3; do
  if git -c http.extraHeader="$AUTH" clone -q --depth 1 --branch "$REF" --filter=blob:none --sparse \
       "https://github.com/$REPO.git" "$TMP/r"; then
    break
  fi
  [ "$i" = 3 ] && hata "$REPO ($REF) klonlanamadi — token suresi dolmus ya da izni eksik olabilir"
  rm -rf "$TMP/r"
  sleep $((i * 5))
done
git -C "$TMP/r" config http.extraHeader "$AUTH"   # seyrek checkout'un sonradan indirdigi blob'lar icin (gecici klon)
git -C "$TMP/r" sparse-checkout set "${DIRS[@]}"

for d in "${DIRS[@]}"; do
  mkdir -p "$d"
  [ -d "$TMP/r/$d" ] || continue
  find "$TMP/r/$d" -maxdepth 1 -type f -name '*.wav' -exec cp -f {} "$d/" \;
done
SHA="$(git -C "$TMP/r" rev-parse --short HEAD)"
N1=$(find data -maxdepth 1 -name '*.wav' | wc -l)
N2=$(find server/recordings -maxdepth 1 -name '*.wav' | wc -l)
echo "kayitlar: data/ $N1 · server/recordings/ $N2 WAV ($REPO@$REF $SHA, $(du -shc data/*.wav server/recordings/*.wav 2>/dev/null | tail -1 | cut -f1))"
