### Grup A (temel: base)

| senaryo | guvenlik (yanlis toplam) | gercek: kilitli bolum | gercek: gecikme medyan / ort | gercek: ekranda ort | ilk kilit medyan | dis: kilitli / ort | sentetik: ayet % / gecikme | zorlama: kilitli / ort | ASR ms/parca | kayit: kotu / iyi | karar |
|---|---|---|---|---|---|---|---|---|---|---|---|
| base bugunku ayarlar | 106 | 97 | 5.20 / 7.04 | - | 10.0 | 69 / 10.07 | 94.1 / 4.85 | 1116 / 15.91 | - | 0 / 0 | temel |
| A2-60 guven esigi (ilk kilit) 60 | 169 (+63 ✗) | 97 | 5.30 (+0.10 ✗) / 7.11 (+0.07 ✗) | - | 10.0 | 69 / 9.92 (-0.15 ✓) | 94.1 / 4.85 | 1116 / 15.99 (+0.08 ✗) | - | 7 / 5 | ELENDI (guvenlik) |
| A3-4 aligner pencere genisligi 4 | 121 (+15 ✗) | 97 | 5.20 / 7.04 | - | 10.0 | 69 / 10.00 (-0.07 ✓) | 94.1 / 4.85 | 1116 / 15.92 (+0.01 ✗) | - | 1 / 2 | ELENDI (guvenlik) |

Karar: ELENDI = guvenlik olcusu (yanlis kilit / ekranda yanlis aday / yanlis ilk kilit / yanlis ayet) kotulesti; KARISIK = bazi kayitlar iyilesti, bazilari kotulesti; IYI = kotulesen kayit yok, en az bir olcu iyilesti; KOTU = sadece kotulesme; FARK YOK.

<details><summary>A2-60: ELENDI (guvenlik) — kotulesen 7, iyilesen 5</summary>

- ✗ replay/rnnt/namaz_aksam4_kamet_fatiha_felak_fatiha_nas.wav: YANLIS ekranda aday 0→1
- ✗ replay/rnnt/session_1777027721.wav: YANLIS kilitli parca 0→4, YANLIS Kuran disi kilit None→[7, 20.0]
- ✗ replay/rnnt-hibrit/namaz_aksam4_kamet_fatiha_felak_fatiha_nas.wav: YANLIS ekranda aday 0→1
- ✗ replay/rnnt-hibrit/namaz_cuma2_kamet_fatiha_tekasur_fatiha_asr.wav: 102: 3.2→6.5 sn
- ✗ replay/rnnt-hibrit/namaz_sabah_kamet_fatiha_isra_fatiha_adiyat.wav: 100: 3.5→7.1 sn
- ✗ replay/rnnt-hibrit/session_1777027721.wav: YANLIS kilitli parca 0→4, YANLIS Kuran disi kilit None→[7, 20.0]
- ✗ synth/rnnt/synth_teravih8_alafasy_s1.wav: 108: 4.7→9.7 sn, 113: 1.7→6.7 sn, ayet 77→75/85
- ✓ replay/rnnt/namaz_yatsi_kamet_fatiha_araf_fatiha_araf.wav: 113: 12.0→7.0 sn
- ✓ external/rnnt/ext_celil1435_106.wav: ilk kilit 20.0→15.0 sn, 106: 20.0→15.0 sn
- ✓ external/rnnt/ext_maher1427_069-Al-haaqqa.wav: ilk kilit 25.0→20.0 sn, 69: 25.0→20.0 sn
- ✓ external/rnnt-hibrit/ext_celil1435_106.wav: ilk kilit 20.0→15.0 sn, 106: 20.0→15.0 sn
- ✓ external/rnnt-hibrit/ext_maher1427_069-Al-haaqqa.wav: ilk kilit 25.0→20.0 sn, 69: 25.0→20.0 sn

</details>

<details><summary>A3-4: ELENDI (guvenlik) — kotulesen 1, iyilesen 2</summary>

- ✗ synth/rnnt/synth_teravih8_saood_s1.wav: ayet 78→77/85
- ✓ external/rnnt/ext_maher1427_069-Al-haaqqa.wav: ilk kilit 25.0→20.0 sn, 69: 25.0→20.0 sn
- ✓ external/rnnt-hibrit/ext_maher1427_069-Al-haaqqa.wav: ilk kilit 25.0→20.0 sn, 69: 25.0→20.0 sn

</details>

