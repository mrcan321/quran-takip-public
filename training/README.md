# Ses tanıma modelinin ince ayarı (kiralık GPU)

Uygulamadaki ses tanıma modelini (NVIDIA FastConformer Hybrid, Arapça) **cami + telefon koşullarına** göre yeniden eğitir:
EveryAyah okumaları (test kârileri hariç) + yapay cami akustiği + gerçek cami kayıtlarımız + "boş" örnekler (gürültü,
Türkçe vaaz) + genel Arapça hatırlatma. Mimari, tokenizer ve çıktı yazımı aynı kalır → uygulamada kod değişmez, sadece
model dosyaları (`asr-model-v3`) değişir.

**Ne zaman:** yeterli cami kaydı birikince (hedef 20-30 sesli namaz; telefonda `Download/Tilavet Takip/`). Kayıtlar repoya
girip `training/real_labels.json`'da etiketlenir (bunu Claude yapar); ilk 6 kayıt ve `server/recordings` hep **test**.

## Makine

| | öneri |
|---|---|
| GPU | 1× A100 40/80 GB ya da H100 (L40S / RTX 4090 24 GB da olur, ~2 kat yavaş) |
| Disk | ≥ 80 GB boş (EveryAyah önbelleği ~10 GB, ses parçaları ~10-15 GB, venv ~8 GB) |
| Sistem | Ubuntu 22.04 / 24.04, NVIDIA sürücüsü CUDA 12.x (`nvidia-smi`), Python 3.10-3.12, internet |
| Süre / ücret | duman testi ~30-45 dk; tam koşu ~4-8 sa (veri ~1-2 sa CPU + eğitim 1-3 sa + değerlendirme ~1 sa) ≈ 10-30 $ |

RunPod / Vast.ai / Lambda gibi bir yerde "PyTorch" ya da düz Ubuntu imajı yeter (betik kendi ortamını kurar).

## Çalıştırma

```bash
# 1. Kod (özel repo: GitHub token ya da `gh auth login`)
git clone https://<TOKEN>@github.com/mrcan321/quran-takip.git && cd quran-takip

# 2. tmux içinde (bağlantı koparsa iş sürsün)
tmux new -s tt

# 3. Önce duman testi: tüm boru hattı küçük veriyle (2 kâri, 20 eğitim adımı) — hata varsa burada çıkar
bash training/run_all.sh --smoke

# 4. Tam koşu
bash training/run_all.sh

# 5. Sonuç tablosu → Claude'a gönder (kopyala-yapıştır yeter)
cat ~/tilavet-train/eval/summary.md

# 6. "ADAY" çıktıysa ve Claude onaylarsa: modeli GitHub release'ine yükle
gh auth login        # ya da export GH_TOKEN=...
bash training/publish.sh v3
```

Yarıda kalırsa kaldığı aşamadan: `bash training/run_all.sh --stages train,eval` (aşamalar: `setup,data,labels,train,eval`).
Seçenekler: `--epochs 4`, `--lr 5e-5`, `--freeze 6` (kodlayıcının ilk 6 katmanını dondur), `WORK=/mnt/disk/tt`.

## Aşamalar

| aşama | betik | ne yapar | çıktı |
|---|---|---|---|
| setup | `run_all.sh` | venv, torch 2.11 (CUDA 12.6), NeMo 2.7.3, ffmpeg, JDK + gradle (test kapısı) | `$WORK/venv` |
| A data | `build_dataset.py` | EveryAyah (~26 kâri, her ayet 4 farklı kâriden), 5-15 sn parçalar, %75'i cami akustiğiyle bozulur; gürültü ve Türkçe konuşma (FLEURS tr) boş etiketle; gerçek kayıtların eğitim bölümü | `data/stage_a.jsonl`, `to_align.jsonl`, `to_label.jsonl` |
| B labels | `prepare_labels.py` | temel modelle etiket doğrulama (kelime hatası > %50 olan ayet atılır, besmele düzeltmesi); uzun ayetler ve gerçek kayıtlar CTC ile zorla hizalanıp 4-15 sn'ye bölünür; FLEURS ar etiketi = temel modelin kendi çıktısı | `data/train.jsonl`, `val.jsonl`, `stats_b.json`, `rejected.jsonl` |
| C train | `finetune.py` | düşük öğrenme hızı (1e-4 kosinüs), bf16, lhotse dinamik paket, doğrulama WER'ine göre en iyi model | `run/best.nemo`, `train_report.json` |
| D eval | `evaluate.py` | iki modeli ONNX'e çevirir, aynı kayıtlarla (gerçek test kayıtları, Harem / Rifai / Çollak / ezan, sentetik teravih) uygulamanın zinciriyle ölçer, test kapısından geçirir | `eval/summary.md` |

## Kabul şartı (summary.md'nin sonu)

- **RED**: güvenlik ölçülerinden biri temel modelden kötü (yanlış kilitli parça, ekranda yanlış aday, yanlış ilk kilit,
  sinyal / zikir kartı yanlış alarmı, okuma içinde metin silme; kamet / selam / semiallah / ezan yakalama düşmesi).
- **ADAY**: güvenlik aynı + okumada boş / yetersiz parça oranı ya da takip gecikmesi iyileşti → yükle, APK'da dene.
- **KAZANÇ YOK**: güvenlik aynı ama iyileşme yok.

## Notlar

- Test kârileri eğitime giremez (`build_dataset.py` durdurur): Alafasy, Husary, Şureym (sentetik küme), Sudeys, Maher
  el-Muaykılî, Hani Rifai, Medine imamları (dış küme). Doğrulama kârisi: Ali Hajjaj es-Süveysi.
- Gerçek kayıt gürültüsü yalnız `split: train` kayıtlardan alınır (test kayıtlarının cami sesi eğitime sızmasın).
- Lisanslar: NVIDIA modeli CC-BY-4.0; FLEURS CC-BY-4.0; EveryAyah kayıtlarının lisansı belirsiz — kişisel proje.
- Betikler GPU'suz ortamda küçük rastgele bir modelle (aynı mimari ve tokenizer) ve `--smoke --fake` verisiyle A → B → C → D
  uçtan uca denendi; gerçek modelle ilk çalıştırma kiralık makinedeki duman testi.
