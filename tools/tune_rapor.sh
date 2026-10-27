#!/bin/bash
# Ayar denemesi (tune.yml) sonuclari → tuning/<ad>/: senaryo json'lari + rapor.md + kararlar.json
# Kullanim: tools/tune_rapor.sh INDIRILEN_ARTIFACT_KLASORU HEDEF [OZET_DOSYASI]
# Artifact'in koku senaryoya gore degisiyor (yukleme yollarinin ortak atasi: A → out/<id>/, B → out/) → scenario.json
# nerede olursa bulunur (run 1-3'te "$a"/*.json hic dosya bulmadi, rapor bos cikti).
set -e
src=$1
D=$2
sum=${3:-/dev/null}
mkdir -p "$D"
find "$src" -name scenario.json | while read -r f; do
  s=$(dirname "$f")
  id=$(basename "$s")
  mkdir -p "$D/$id"
  cp "$s"/*.json "$D/$id/"
done
echo "senaryo: $(find "$D" -name scenario.json | wc -l)" >&2
python tests/tune.py report --out "$D" --summary "$sum" --json "$D/kararlar.json" > "$D/rapor.md"
cat "$D/rapor.md"
rm -f "$D"/*/details.json   # kayit kayit ayrinti rapor.md / kararlar.json'da; dosyalar buyuk
