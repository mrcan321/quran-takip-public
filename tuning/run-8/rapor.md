### Grup A (temel: base)

| senaryo | guvenlik (yanlis toplam) | gercek: kilitli bolum | gercek: gecikme medyan / ort | ilk kilit medyan | dis: kilitli / ort | sentetik: ayet % / gecikme | zorlama: kilitli / ort | ASR ms/parca | kayit: kotu / iyi | karar |
|---|---|---|---|---|---|---|---|---|---|---|
| base bugunku ayarlar | 106 | 97 | 5.20 / 7.04 | 10.0 | 69 / 10.07 | 94.1 / 4.85 | 1116 / 15.91 | - | 0 / 0 | temel |
| A1-57 guven esigi (kilitli) 57 | 92 (-14 ✓) | 97 | 5.20 / 7.04 | 10.0 | 69 / 10.07 | 94.1 / 4.85 | 1117 (+1 ✓) / 15.92 (+0.01 ✗) | - | 0 / 0 | IYI |
| A4-6 tek parcada kilit farki 6 | 107 (+1 ✗) | 97 | 5.20 / 6.99 (-0.05 ✓) | 10.0 | 69 / 9.92 (-0.15 ✓) | 94.1 / 4.85 | 1120 (+4 ✓) / 16.12 (+0.21 ✗) | - | 0 / 6 | ELENDI (guvenlik) |
| A5-80 Fatiha hizli kilit skoru 80 | 169 (+63 ✗) | 97 | 5.00 (-0.20 ✓) / 6.99 (-0.05 ✓) | 10.0 | 69 / 10.00 (-0.07 ✓) | 94.1 / 4.85 | 1116 / 15.86 (-0.05 ✓) | - | 2 / 4 | ELENDI (guvenlik) |
| A7-70 sure gecisi arama esigi 70 | 120 (+14 ✗) | 97 | 5.20 / 7.04 | 10.0 | 69 / 10.07 | 94.1 / 4.85 | 1116 / 15.94 (+0.03 ✗) | - | 1 / 0 | ELENDI (guvenlik) |
| A9-7 belirsiz aday farki 7 | 96 (-10 ✓) | 97 | 5.20 / 7.04 | 10.0 | 69 / 10.07 | 94.1 / 4.85 | 1116 / 15.92 (+0.01 ✗) | - | 0 / 0 | FARK YOK |
| K1 kombinasyon: kilit farki 10 + Fatiha 85 + gecis aramasi 75 (kotulestirmeyenler) | 105 (-1 ✓) | 97 | 5.20 / 7.04 | 10.0 | 69 / 9.85 (-0.22 ✓) | 94.1 / 4.85 | 1116 / 15.91 | - | 0 / 7 | IYI |
| K2 kombinasyon: K1 + guven esigi 55 + belirsiz aday 5 (zorlamada yanlis azalan) | 87 (-19 ✓) | 97 | 5.20 / 7.04 | 10.0 | 69 / 9.85 (-0.22 ✓) | 94.1 / 4.85 | 1116 / 15.92 (+0.01 ✗) | - | 0 / 7 | IYI |
| K3 kombinasyon: K2, kilit farki 8 | 86 (-20 ✓) | 97 | 5.20 / 7.04 | 10.0 | 69 / 9.85 (-0.22 ✓) | 94.1 / 4.85 | 1116 / 15.92 (+0.01 ✗) | - | 0 / 7 | IYI |

Karar: ELENDI = guvenlik olcusu (yanlis kilit / ekranda yanlis aday / yanlis ilk kilit / yanlis ayet) kotulesti; KARISIK = bazi kayitlar iyilesti, bazilari kotulesti; IYI = kotulesen kayit yok, en az bir olcu iyilesti; KOTU = sadece kotulesme; FARK YOK.

<details><summary>A4-6: ELENDI (guvenlik) — kotulesen 0, iyilesen 6</summary>

- ✓ replay/rnnt/ihlas.wav: ilk kilit 15.0→10.0 sn, 112: 15.0→10.0 sn
- ✓ replay/rnnt-hibrit/ihlas.wav: ilk kilit 15.0→10.0 sn, 112: 15.0→10.0 sn
- ✓ external/rnnt/ext_celil1435_112.wav: ilk kilit 10.0→5.0 sn, 112: 10.0→5.0 sn
- ✓ external/rnnt/ext_collak_112.wav: ilk kilit 15.0→10.0 sn, 112: 15.0→10.0 sn
- ✓ external/rnnt-hibrit/ext_celil1435_112.wav: ilk kilit 10.0→5.0 sn, 112: 10.0→5.0 sn
- ✓ external/rnnt-hibrit/ext_collak_112.wav: ilk kilit 15.0→10.0 sn, 112: 15.0→10.0 sn

</details>

<details><summary>A5-80: ELENDI (guvenlik) — kotulesen 2, iyilesen 4</summary>

- ✗ replay/rnnt/namaz_aksam4_kamet_fatiha_felak_fatiha_nas.wav: YANLIS kilitli parca 0→2
- ✗ replay/rnnt/namaz_sabah2_fatiha_hac_fatiha_hac.wav: YANLIS kilitli parca 0→2
- ✓ replay/rnnt-hibrit/namaz_yatsi5_bakara_fatiha_insan.wav: 1: 6.9→1.9 sn
- ✓ external/rnnt/ext_rifai_009_altawbah.wav: 1: 10.0→5.0 sn
- ✓ external/rnnt-hibrit/ext_rifai_009_altawbah.wav: 1: 10.0→5.0 sn
- ✓ synth/rnnt/synth_hatim4_saood_s1.wav: 1: 6.1→1.1 sn

</details>

<details><summary>A7-70: ELENDI (guvenlik) — kotulesen 1, iyilesen 0</summary>

- ✗ external/rnnt/ext_rifai_014_ebrahim.wav: 14: 7.0→12.0 sn

</details>

<details><summary>K1: IYI — kotulesen 0, iyilesen 7</summary>

- ✓ external/rnnt/ext_celil1435_112.wav: ilk kilit 10.0→5.0 sn, 112: 10.0→5.0 sn
- ✓ external/rnnt/ext_collak_112.wav: ilk kilit 15.0→10.0 sn, 112: 15.0→10.0 sn
- ✓ external/rnnt/ext_rifai_009_altawbah.wav: 1: 10.0→5.0 sn
- ✓ external/rnnt-hibrit/ext_celil1435_112.wav: ilk kilit 10.0→5.0 sn, 112: 10.0→5.0 sn
- ✓ external/rnnt-hibrit/ext_collak_112.wav: ilk kilit 15.0→10.0 sn, 112: 15.0→10.0 sn
- ✓ external/rnnt-hibrit/ext_rifai_009_altawbah.wav: 1: 10.0→5.0 sn
- ✓ synth/rnnt/synth_hatim4_saood_s1.wav: 1: 6.1→1.1 sn

</details>

<details><summary>K2: IYI — kotulesen 0, iyilesen 7</summary>

- ✓ external/rnnt/ext_celil1435_112.wav: ilk kilit 10.0→5.0 sn, 112: 10.0→5.0 sn
- ✓ external/rnnt/ext_collak_112.wav: ilk kilit 15.0→10.0 sn, 112: 15.0→10.0 sn
- ✓ external/rnnt/ext_rifai_009_altawbah.wav: 1: 10.0→5.0 sn
- ✓ external/rnnt-hibrit/ext_celil1435_112.wav: ilk kilit 10.0→5.0 sn, 112: 10.0→5.0 sn
- ✓ external/rnnt-hibrit/ext_collak_112.wav: ilk kilit 15.0→10.0 sn, 112: 15.0→10.0 sn
- ✓ external/rnnt-hibrit/ext_rifai_009_altawbah.wav: 1: 10.0→5.0 sn
- ✓ synth/rnnt/synth_hatim4_saood_s1.wav: 1: 6.1→1.1 sn

</details>

<details><summary>K3: IYI — kotulesen 0, iyilesen 7</summary>

- ✓ external/rnnt/ext_celil1435_112.wav: ilk kilit 10.0→5.0 sn, 112: 10.0→5.0 sn
- ✓ external/rnnt/ext_collak_112.wav: ilk kilit 15.0→10.0 sn, 112: 15.0→10.0 sn
- ✓ external/rnnt/ext_rifai_009_altawbah.wav: 1: 10.0→5.0 sn
- ✓ external/rnnt-hibrit/ext_celil1435_112.wav: ilk kilit 10.0→5.0 sn, 112: 10.0→5.0 sn
- ✓ external/rnnt-hibrit/ext_collak_112.wav: ilk kilit 15.0→10.0 sn, 112: 15.0→10.0 sn
- ✓ external/rnnt-hibrit/ext_rifai_009_altawbah.wav: 1: 10.0→5.0 sn
- ✓ synth/rnnt/synth_hatim4_saood_s1.wav: 1: 6.1→1.1 sn

</details>

