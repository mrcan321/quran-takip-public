# Tilavet Takip — Kuran Tilavet Tanıma Projesi

**Proje hedefi:** Namaz kılarken imamı sesli olarak takip eden Android uygulaması. **Tamamen offline** çalışır (namazda internet yok, cami koşulu). Kişisel proje. Play Store hedefi yok, manuel install. Hedef telefon: Samsung Galaxy A34 5G (MediaTek Dimensity 1080, 8GB RAM, arm64-v8a).

**Repo düzeni (20.10'dan beri):** kod **herkese açık** `mrcan321/quran-takip-public` (GitHub Actions dakikası ücretsiz; özel
repoda aylık 2.000 dk kotası doluyordu). **Ses kayıtları** (cami namazları, telefon okumaları, test konuşmaları: `data/*.wav`,
`server/recordings/*.wav`) **özel** `mrcan321/quran-takip` repoda, dal `claude/vigilant-davinci-emx2rt` (orada Actions kapalı;
kodun 20.10'a kadarki geçmişi de orada). Public repoda bu klasörlerin ses dosyaları `.gitignore`'da; CI her iş akışında
`tools/kayitlari_cek.sh` ile çeker (secret `KAYIT_TOKEN`: fine-grained, sadece özel repo, Contents read-only; model release'i
de bununla kopyalanır). Yerelde / kiralık makinede: `KAYIT_TOKEN=... bash tools/kayitlari_cek.sh`. **Yeni kayıt:** WAV özel
reponun `data/`'sına; transkript (`tests/trjson`), `EXPECTED` / `TIMELINE`, `training/real_labels.json` public repoya. İmza
anahtarı (`debug.keystore`) bilerek repoda (Play Store yok; gerekirse değiştirilir → telefonlarda bir kez kaldır-kur).

**Kullanıcı iletişim tercihleri:**
- Türkçe konuş
- Kod içi yorumlar Türkçe (mixed-latin OK — normalize edilmemiş)
- WSL/Ubuntu ortamı, sadece komut satırı (Android Studio yok)
- Hata mesajlarını sevmez — tam dosyalar ver, str_replace değil
- Fine-tune sever — build sayısını minimize etmek istiyor
- APK boyutu sorun değil, kalite öncelik

---

## Mimari — dosya organizasyonu

### Python tarafı (`scripts/`, `server/`)

`scripts/` — **referans implementasyon** ve asset builder script'ler:
- `aligner.py`: **ana** — QuranCorpus, trigram index, align_transcription (fuzzy match). Kotlin port'u için referans. `ZERO_WIDTH` normalize eklenmiş.
- `build_quran_assets.py`: `quran.bin` (3.5 MB) + `meal.bin` (~1 MB, Ali Bulaç meali) üretir. Android asset olarak kullanılır.
- `build_aligner_fixture.py`: 43 test case üretir, `aligner_test_fixture.json`
- `build_state_machine_fixture.py`: 26 senaryo × 558 chunk üretir, `state_machine_fixture.json` (+ referans state machine;
  fixture telefon varsayılanlarıyla: ilk kilit 70, pencere ±2)
- `onnx_full_export.py`: NeMo `nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0` → ONNX (opset 18, preprocessor+encoder+CTC birleşik)
- `sp_manual_decoder.py`: SentencePiece manuel decoder (Android'de Java SentencePiece yok, protobuf ile decode)
- `build_meals.py`: secilebilir mealler (Ayarlar → MEAL) → `asr/meals/<id>.bin` + `meals/index.tsv` (bkz. "Meal seçimi")
- `explore_rapidfuzz.py`: RapidFuzz partial_ratio algoritmasını debug için
- `../tools/kayitlari_cek.sh`: ses kayıtlarını özel repodan çeker (bkz. "Repo düzeni")
- `vad_chunker.py`: duraklamada kesen parçalayıcı — `AudioPipeline.kt` `ChunkBuilder`'ın referansı (birebir);
  hibrit: `chunks_pause(audio, pause_enabled=...)` — duraklama kesimi sadece kilitliyken
- `eval_pipeline.py` + `onnx_asr.py`: telefonsuz değerlendirme (bkz. "Offline değerlendirme")

`training/` — **ses tanıma modelinin ince ayarı** (kiralık GPU, bkz. açık sorun 19 ve `training/README.md`): `run_all.sh` (tek komut:
kurulum → A → B → C → D), `build_dataset.py` (A: EveryAyah test kârileri hariç + cami akustiği + olumsuz örnekler + gerçek kayıtların
eğitim bölümü), `acoustics.py` (hoparlör / yankı / telefon / gürültü), `prepare_labels.py` (B: temel modelle etiket doğrulama, CTC zorla
hizalama + bölme, genel Arapça kendi etiketi), `finetune.py` (C: NeMo hibrit), `evaluate.py` (D: iki model ONNX → aynı kayıtlar →
test kapısı → kabul tablosu), `publish.sh` (release), `real_labels.json` (gerçek cami kayıtlarının etiketleri + train/test bölümü).

`server/app.py` — **referans state machine** (Flask + WebSocket). Android state machine bunun birebir port'u. Namazda çalışmaz, sadece PC üzerinde test/kalibrasyon için.

`tests/` — **APK öncesi test kapısı** (bkz. "Test kapısı"): `gate.py` (kümeler + baseline karşılaştırması), `lib/`
(ortak ortam, metrikler, bileşik senaryolar, sinyal taraması, app.py birebirliği, Kotlin köprüsü, ayet ölçümü), `trjson/`
(gerçek kayıtların CI ASR transkriptleri; `synth/` sentetik, `external/` dış kaynak — Harem teravihi, Çollak, ezan), `synth/`
(sentetik ses üreticisi), `external/` (dış kaynak indirici), `baseline.json`, `golden/` (rekât/ezan olay dosyaları), `jvm/` (uygulamanın saf Kotlin
kaynaklarını kopyalamadan JVM'de derleyen Gradle projesi + `android.util.Log` / `Context` / `AssetManager` stub'ları).

### Android tarafı (`tilavet-android/`)

Build: GitHub Actions (`.github/workflows/android.yml`) → release APK. Kotlin/Compose, Min SDK 28, sadece arm64-v8a.

**Kaynak yapısı** (`app/src/main/java/com/tilavet/takip/`):
```
├── MainActivity.kt            — root composable, permission
├── MainViewModel.kt           — state, pipeline coordination, callbacks
├── audio/
│   ├── FrameSource.kt         — ses kaynağı arayüzü (mikrofon / WAV simülasyonu)
│   ├── AudioRecorder.kt       — 16kHz mono PCM frame emitter (100ms frame), FrameSource
│   ├── WavReader.kt           — akışlı WAV okuyucu → 16 kHz mono (Android'siz, JVM'de test edilir)
│   ├── WavFileSource.kt       — simülasyon: WAV'ı gerçek zamanlı ver + hoparlörden çal, FrameSource
│   ├── ChunkBuilder.kt        — duraklamada / 5 sn'de kesen parçalayıcı (Android'siz, JVM'de vad_chunker ile kıyaslanır)
│   └── AudioPipeline.kt       — kaynak → ChunkBuilder → ASR → state machine
├── asr/
│   ├── AsrTypes.kt            — AsrState, AsrResult
│   ├── SentencePieceDecoder.kt — Manuel protobuf decoder (~150 satır)
│   └── OnnxAsrEngine.kt       — ONNX Runtime inference
├── aligner/
│   ├── Normalizer.kt          — Arabic normalize (Python normalize_arabic port)
│   ├── QuranIndex.kt          — quran.bin mmap reader, trigram lookup
│   ├── Fuzzy.kt               — RapidFuzz partial_ratio + token_sort_ratio Kotlin port (bit-parallel LCS)
│   ├── Aligner.kt             — align_transcription port
│   ├── FuzzyTestRunner.kt     — 51 case test (bit-perfect)
│   └── AlignerTestRunner.kt   — 43 case test
├── session/
│   ├── SessionState.kt        — NamazState enum, PendingMatch, ChunkResult
│   ├── StateMachine.kt        — process_chunk port (app.py referans)
│   ├── EzanTracker.kt         — ezan/kamet penceresi icin cumle takibi (UI; state machine'i etkilemez)
│   ├── ZikirTracker.kt        — namaz zikirleri karti: tekbir, semiallah, rabbena, selam, namaz sonu duasi (UI, JVM'de test)
│   ├── RakatTracker.kt        — rekat sayaci + kaba durus (UI; state machine'i etkilemez, JVM'de test)
│   └── StateMachineTestRunner.kt — 558 chunk × 26 senaryo test (5-8. = gerçek namaz akışları; 558/558)
├── data/
│   ├── MushafData.kt          — tum Kuran listesi: ayet/sure tablolari, liste satirlari, besmele gizleme
│   ├── AppSettings.kt         — kullanıcı ayarları (SettingsRepository.kt içinde)
│   ├── SettingsRepository.kt  — DataStore Preferences wrapper (theme, sizes, motion, idleOpacity,
│   │                            skippedAyahTenths, mealId, G2 gözlük + yazı boyutu, tuner)
│   ├── MealCatalog.kt         — secilebilir mealler: asr/meals/index.tsv (Android'siz, JVM'de test)
│   └── MealLoader.kt          — meal.bin / meals/<id>.bin mmap reader (Türkçe meal + sure isimleri)
├── ui/
│   ├── AyahStepper.kt         — atlanan ayetleri sirayla gosterme (1:2 → 1:5 ise 1:3, 1:4 ayar kadar)
│   ├── theme/                 — Palette.kt (8 tema: Zümrüt varsayılan + 7 klasik, AppStyle), Typography, Theme
│   ├── components/            — MushafView (sure basligi + ayet satiri), Controls, SettingsSheet, EzanPopup, ZikirPopup,
│   │                            Ornaments (Zümrüt süsleri: kemer amblemi, cami silueti, yıldız deseni, altın ayraç,
│   │                            kemerli kart), BrandLogo (uygulama ikonu = logo madalyonu)
│   └── screens/MainScreen.kt  — ana ekran: Mushaf listesi + sese gore takip, top bar (6 ikon), footer
├── glasses/                   — Even Realities G2 gözlük (Android'siz, JVM'de test edilir)
│   ├── GlassesState.kt        — gözlüğe giden ekran durumu (sure/ayet, meal, Arapça, rekât, zikir/ezan) → JSON
│   └── GlassesBridge.kt       — 127.0.0.1:18765 yerel HTTP köprüsü: /state uzun yoklama + eklenti dosyaları + CORS
└── util/
    ├── AssetSync.kt           — APK assets → filesDir senkronu (model sadece meta.json degisince)
    ├── SessionAudioWriter.kt  — pipeline sesini WAV'a yazar (cacheDir/sessions, son 3 oturum) + yaninda .txt oturum log'u
    ├── SessionLog.kt          — pipeline / ViewModel log satirlari logcat'e + oturum .txt'sine (logcat tamponu silinmesin)
    ├── PublicRecordings.kt    — oturum bitince WAV + .txt → Download/Tilavet Takip (dosya yoneticisinden alinir, silinmez)
    ├── ListenService.kt       — dinlerken ön plan servisi (mikrofon): ekran kilitli / Even uygulamasına geçince de dinler
    └── LogExporter.kt         — logcat'i dosyaya yaz, log + son WAV share intent (FileProvider)
```
**G2 eklentisi** (Even Hub web uygulaması, `app/src/main/assets/g2/` — APK'dan da sunulur, `.ehpk` de aynı dosyalar):
`index.html` (telefondaki sayfa + önizleme), `boot.js` (yükleyici: kodu köprüden fetch + blob import, yoksa paketteki), `g2-kod.json`, `app.js` (köprüden okur, gözlüğe yazar, Arapça görüntü, kaydırma),
`layout.js` (saf ekran düzeni: satır kırma, sayfalar — node testli), `sdk.js` (`@evenrealities/even_hub_sdk` 0.0.16,
MIT, `sdk-LICENSE.txt`). Paket tanımı: `tilavet-android/g2-plugin/app.json`.

### Kritik: asset staging

Gradle (`app/build.gradle.kts`) asset'leri `TILAVET_ASSETS_DIR` env'inden okur; verilmemişse
repo kökündeki `android-assets-staged/` (gitignore'da). Python script'leri de aynı yola yazar.
APK içinde hepsi `assets/asr/` altında olur.

Bu klasör **git'te değil**. İçinde olması gerekenler (`asr/` altında):
- `fastconformer_full.onnx` (~3 MB) — encoder model (+ `enc_proj`, `enc_len` çıktıları, v2)
- `rnnt_decoder.onnx` (17 MB), `rnnt_joint.onnx` (2.5 MB) — RNNT (v2)
- `fastconformer_full.onnx.data` (443 MB) — model weights (**orijinal isim ZORUNLU**, ONNX external data loading için)
- `tokenizer.model` (249 KB) — SentencePiece
- `meta.json` — model meta (`blank_idx`, `sample_rate`)
- `quran.bin` (3.5 MB) — build_quran_assets.py üretir
- `meal.bin` (~1 MB) — build_quran_assets.py üretir (meal: `download_meal.py` `MEAL_EDITION`; varsayılan meal)
- `meals/` — build_meals.py üretir: `index.tsv` + seçilebilir mealler `<id>.bin` (~0.9-1.2 MB, meal.bin biçimi)
- `aligner_test_fixture.json` (~15 KB) — build_aligner_fixture.py
- `fuzzy_test_fixture.json` (~10 KB) — explore_rapidfuzz.py
- `state_machine_fixture.json` (~20 KB) — build_state_machine_fixture.py

**ONNX modeli git'te yok** — `model-export.yml` NeMo'dan export edip `asr-model-vN` release'ine
yükler, build'ler oradan indirir (APK ve eval şu an `asr-model-v2`). Export script'i değişirse
yeni tag aç (v3...), eski tag'ler eski APK'lar için kalır.

**Telefonda asset senkronu** (`util/AssetSync.kt`): APK sürümü değişince çalışır. Model dosyaları
sadece `meta.json` değiştiyse (yeni export) yeniden kopyalanır; `quran.bin`/`meal.bin` her yeni
APK'da kopyalanır. ESKİ HATA: "dosya varsa kopyalama" yüzünden yeni APK'daki model/quran.bin hiç
telefona geçmiyordu.

---

## Şu ana kadar yapılanlar (özet)

### Faz 1 — Mock UI ✅
7 tema (APK #30'dan beri + varsayılan Zümrüt), ayar paneli (Compose), mikrofon izni, scroll, top bar. Test verisi: Tevbe 9:1-7.

### Faz 2 — ASR + Aligner + State Machine port ✅

**Adım 1-3: ONNX ASR** (bit-perfect NeMo CTC + RNNT)
- opset 18, preprocessor+encoder+CTC tek graph; model v2: + `enc_proj`, `enc_len` çıktıları,
  `rnnt_decoder.onnx` (LSTM 1x640) + `rnnt_joint.onnx`. Greedy döngü: `scripts/onnx_asr.py` →
  `OnnxAsrEngine.kt` birebir port. Export sonunda ONNX CTC/RNNT çıktısı NeMo ile karşılaştırılır.
- onnxscript ile export
- Galaxy A34 5G: RTF 0.13-0.35, transkripsiyon kalitesi iyi
- APK 520 MB (model dahil)

**Adım 4a: Quran Asset Builder** (Python)
- `quran.bin`: Header + 77878 word entry + text pool + 7516 trigram entry
- `meal.bin`: 6236 meal + 114 surah info
- BOM/ZERO_WIDTH normalize düzeltmesi eklendi

**Adım 4b: QuranIndex Kotlin** ✅ bit-perfect
- mmap reader
- Trigram lookup Python ile birebir uyumlu

**Adım 4c: Fuzzy Kotlin** ✅ 51/51 bit-perfect
- RapidFuzz `fuzz_py.py` **birebir port** — 3-faz pencere taraması (Faz 1: longer[:i], Faz 2: longer[i:i+len_short], Faz 3: longer[i:])
- IntArray reuse (ThreadLocal), offset-based DP
- Kritik: `partial_ratio` LCS-based Indel distance kullanır, standart Levenshtein değil

**Adım 4d: Aligner Kotlin** — çalışıyor, hızı sınırlı
- `align_transcription` port
- Runtime slack: `defaultWindowSlack` var (default 2, production için — tuner ile ayarlanabilir)
- **Optimizasyonlar** — sıkı min_hits (aday sayısı >3000 ise arttır), score-based pruning, window cache
- Test: 43 case, saf Kotlin DP ~ RapidFuzz C++'a göre 100-500x yavaş, kabul edildi

**Adım 5: StateMachine Kotlin** ✅ 25/25 bit-perfect
- `SessionState`, `PendingMatch`, `ChunkResult`, `NamazState` enum
- `processChunk` port — sessizlik, kelime sayısı, preferred range, pending doğrulama, transition
- Runtime tuner: `minConfidence` (default 50), `minConfidenceFirstLock` (default 70) `@Volatile var`

**Adım 6: Pipeline entegrasyonu** ✅
- `AudioRecorder`: 100ms frame flow (16kHz mono)
- `AudioPipeline`: chunk buffer (5sn + 1sn overlap), mikrofon → ASR → state machine
- MainViewModel: `startPipeline()` — mock pipeline **kaldırıldı**
- MealLoader: gerçek Türkçe meal + sure isimleri UI'a bağlı

**Adım 6d: Meal/sure yükleyici** ✅
- `MealLoader.load()` — `meal.bin` mmap reader
- HashMap cache: surah:ayah → meal, surah → SurahInfo (Türkçe + Arapça isim + ayah count)
- UI'da placeholder yerine gerçek metin

### Runtime tuner (settings paneli TUNER (DEBUG) bölümü)
- `GUVEN ESIGI (KILITLI)` — normal match eşiği (default 50)
- `GUVEN ESIGI (ILK KILIT)` — ilk kilit eşiği (default 70, prod'da düşürmeye ihtiyaç var)
- `ALIGNER PENCERE GENISLIGI` — windowSlack (default ±2)
- DataStore ile persist, canlı reload (pipeline durmadan bir sonraki chunk'ta uygulanır)

### Log export + oturum ses kaydı ✅
- Top bar'da 📤 (IosShare) ikonu → log + **son oturumun WAV kaydı** birlikte paylaşılır (ACTION_SEND_MULTIPLE)
- `LogExporter`: kendi PID logcat'ini dosyaya yaz, FileProvider ile share intent
- `SessionAudioWriter`: mikrofon açıkken duyulan ses kesintisiz WAV (16 kHz mono 16-bit),
  `cacheDir/sessions/tilavet-YYYYMMDD-HHmmss.wav`, son 3 oturum, en fazla 60 dk; header ~10 sn'de bir
  güncellenir (uygulama ölse de dosya okunur). Log'daki `[chunk N] ... t=Xs` = WAV'da X. saniye (APK #21+).
- **Gerçek okuma → test verisi:** paylaşılan WAV'ı `data/`'ya koy, `eval_pipeline.py` `EXPECTED`'e
  beklenen sureyi yaz → eval.yml hem skor hem "ilk kilit" simülasyonunda kullanır.
- `AndroidManifest.xml`'de FileProvider tanımlı, `xml/file_paths.xml`: `logs/` + `sessions/`
- **Kayıtlar dosya yöneticisinden (APK #53+):** kullanıcı: "kayıtların hangi dizinde olduğunu söyle, file explorer ile alırım (paylaş
  boyut sınırına takılabilir)". `cacheDir/sessions` uygulamaya özel (dosya yöneticisi göremez) ve son 3'ü tutar → her mikrofon oturumu
  bitince (ses + parçalar işlenince ya da durdurunca) `util/PublicRecordings` WAV'ı ve **oturum log'unu** (`tilavet-…-….txt`)
  **Download/Tilavet Takip/**'e kopyalar (Android 10+ MediaStore Downloads, izin gerekmez; Android 9: `Android/data/com.tilavet.takip/
  files/Tilavet Takip/`). Kopyalananlar uygulama tarafından silinmez; cache'teki kopyaya `.pub` işareti (iki kez kopyalanmaz); 1 sn'den
  kısa kayıt kopyalanmaz; uygulama oturum ortasında kapanırsa bir sonraki açılışta kopyalanır. Durum satırı "Durduruldu · kayıt:
  Download/Tilavet Takip", log `[kayit] Download/Tilavet Takip/tilavet-….wav (… KB)`.
- **Oturum log'u** (`util/SessionLog`): AudioPipeline + MainViewModel satırları (`[chunk N]`, `[rekat]`, `[zikir]`, `[metin]`, `[g2]`,
  ara ayetler, hatalar) logcat'e ve oturumun `.txt`'sine — logcat tamponu tüm uygulamalara ortak, yatsı 19.10'da 20 dk'lık kaydın
  ilk 8 dk'sı log'da yoktu. Simülasyonda yazılmaz (WAV gibi).

### Simülasyon modu — kayıtlı sesi mikrofon gibi oynat (APK #21+)
- Alt barda mikrofonun solundaki dosya butonu → menü: uygulamanın tuttuğu son 3 oturum kaydı
  (`cacheDir/sessions`, dosya seçiciden görünmüyor) + "Telefondan dosya seç…" (SAF `OpenDocument`, `audio/*`).
- `WavFileSource` dosyayı **gerçek zamanlı** verir: her 100 ms'lik çerçeve mikrofondaki gibi "bittiği" anda
  (başlangıç + örnek sayısı / 16000, mutlak çizelge) pipeline'a gider → parça sınırları, hibrit duraklama
  kesimi, kuyruk ve gecikme canlıdakiyle aynı. Aynı ses hoparlörden de çalar (`AudioTrack`, ~200 ms tampon;
  açılamazsa sessiz devam). Pipeline kaynağın hangisi olduğunu bilmez (`FrameSource`).
- `WavReader`: PCM 8/16/24/32 bit, float32, EXTENSIBLE; kanallar ortalanır; 16 kHz dışı hızlar 16 kHz'e çevrilir
  (tam kat → ortalama, diğerleri doğrusal — eval soxr kullanıyor, o dosyalarda küçük fark olabilir). Telefon
  kayıtlarında (16 kHz mono 16 bit) çıktı eval'deki soundfile ile **bit bit aynı** (JVM testi: 6 biçim).
  data boyutu 0 ise dosya sonuna kadar okur; dosya belleğe alınmaz (akışlı).
- Simülasyonda oturum WAV'ı **yazılmaz** (son 3 gerçek kayıt silinmesin); log normal yazılır, 📤 ile paylaşılır.
- Dinlerken ve simülasyonda ekran kararmaz (`keepScreenOn`, MainActivity) — dokunmadan izleniyor.
- Ekran: durum satırında turuncu `SİM` + `dosyadaki konum/toplam süre`, dosya butonu vurgulu; durdurma büyük
  butondan (ya da dosya butonundan). Dosya bitince kalan parçalar işlenir, durum "Simülasyon bitti"
  (`PipelineEvent.Ended` — son parça sonucundan sonra gelir). Mikrofon kaynağı kapanırsa "Mikrofon kapandı".
- Log: başlangıçta `kaynak=SIM <dosya>` / `kaynak=MIC`; her `[chunk N]` satırında `t=57,2s` (parça sonunun
  oturum/dosya içindeki zamanı — eval TIMELINE ile doğrudan karşılaştırılır).

### Even Realities G2 gözlük — okunan ayet gözlükte (APK #43+, büyük yazı #44+, yazı boyutu #46+)
- Kullanıcı: "kilitlendiği ayeti aynı zamanda Even Realities G2 gözlüğe text olarak gönderebilir miyiz". G2'ye doğrudan
  BLE ile yazılamaz (protokol kapalı, bağlantı Even uygulamasında); gözlük uygulamaları **Even Hub eklentisi** = Even
  uygulamasının WebView'inde çalışan web sayfası (SDK `@evenrealities/even_hub_sdk`, MIT). Mimari:
  - **Köprü** (`glasses/GlassesBridge`): Ayarlar → **G2 GÖZLÜK: AÇIK** ise uygulama sadece `127.0.0.1:18765`'e bağlı küçük
    HTTP sunucusu açar (internete çıkmaz; soket için `INTERNET` izni). `GET /state?since=N&wait=20` → `GlassesState` JSON
    (durum değişince hemen, yoksa 20 sn bekler — uzun yoklama), `GET /` + eklenti dosyaları (assets/g2) + `kfgqpc.ttf`,
    CORS (`Access-Control-Allow-Origin: *`, `…-Private-Network: true`, OPTIONS). Durum `MainViewModel.glassesStateOf`:
    **ekrandaki** okunan ayet (AyahStepper'ın ara ayetleri dahil), `progress` = son vurgulu kelime / ayet kelime sayısı,
    meal, rekât etiketi, zikir kartı / ezan penceresi (başlık + okunuş + anlam — `EzanPhrase.reading` eklendi), aday/kilit.
  - **Eklenti** (`assets/g2`): köprüyü yoklar, SDK ile gözlüğe yazar. 576×288 ekran, firmware fontu tek boy (satır 27 px),
    **Arapça harf yok** (Latin/Kiril/Yunan/CJK; Türkçe harfler var).
    **Büyük yazı (varsayılan, Ayarlar → G2 YAZI: BÜYÜK)** — kullanıcı: "Arapça varsayılan kapalı, sadece meal, mümkün
    olduğunca büyük fontla, ekranda en yakın pozisyonda": firmware fontu büyütülemediği için meal eklentide canvas'ta
    **Manrope 700** (uygulamaya gömülü, köprüden `/manrope.ttf`) ile çizilip ekranın tamamını kaplayan 4 görüntü karosu
    (288×144 Gray8, görüntü kutusu sınırı; hepsi en fazla 4) olarak gider; arkada boş metin kutusu sadece dokunmatik olaylar
    için (zOrderIndex 0). Punto `fitBigText`: metni tek sayfaya sığdıran en büyüğü (120 px → **en küçük punto**), onda da
    sığmazsa sayfalar (satırlar sayfalara eşit dağılır, fark ≤ 1). En küçük punto = Ayarlar → **G2 YAZI BOYUTU** (30-80 px,
    varsayılan 48; `GlassesState.textPx` → `layout.bigOptions`, canlı — gözlükte hemen değişir). APK #45'e kadar sabit 34
    (kullanıcı: "yazılar istediğim büyüklükte değil" — tipik meal 34-40 px'e düşüyordu, firmware yazısının ~1.4 katı).
    Satır 1.16 em, kenar 6/4 px; tek sayfa aramasında kelime bölen punto atlanır, en küçük puntoda satıra sığmayan kelime
    tireyle bölünür. Blok dikeyde ortada, satırlar soldan; meal (üstte isteğe bağlı sure / ayet satırı — APK #50, aşağıda;
    kapalıyken başlık yok), aday ayet sönük gri, birden çok
    sayfada sağ kenarda ince dikey sayfa çubuğu (sayfa başına bir parça; eski köşedeki `2/3` dolu sayfada yazıya biniyordu);
    zikir / ezan kartında okunuş + anlam, boştayken kısa durum. Değişmeyen karo tekrar gönderilmez (özet). Font
    yüklenemezse normal düzen. Eklenti çizdiği düzeni köprüye bildirir (`/state?...&ekran=buyuk 48px`) → ayarlarda
    "BAĞLI · BÜYÜK YAZI 48 PX", log `[g2] eklenti ekrani: buyuk 48px` (düzen değişince).
    **Ekran alanı / derinlik (araştırıldı, kullanıcı: "ana ekran çok daha büyük, Even AI cevabı daha yakın popup'ta"):**
    eklentiye ekranın tamamı (576×288) veriliyor — 4 × 288×144 karo tam kaplıyor; SDK 0.0.16'da katman / derinlik /
    popup API'si yok (`zOrderIndex` sadece kutuların üst üste sırası, `shutDownPageContainer(1)` çıkış onayı). G2'nin
    katmanlı (stereoskopik) ekranında Even'ın kendi bildirimleri / Even AI ön katmanda — eklentiye açık değil. Görüntünün
    uzaklığı (Near / Mid / Far) ve yüksekliği Even uygulamasının "Display Adjustment" ayarı (her şeyi etkiler; eklenti
    değiştiremez). **NORMAL** (eski düzen): başlık `Kevser 108:2 · 2. REKÂT · KIYAM`
    (+ `· ADAY`, `1/3`) + 9 satır meal; **G2'DE ARAPÇA: AÇIK** ise ayet metni KFGQPC ile canvas'ta çizilip 2 × 288×112 Gray8
    görüntü (görüntü kutusu en fazla 288×144) + 5 satır meal. Uzun meal sayfalı: sayfa imamın ayetteki ilerlemesiyle
    (`progress`) seçilir; gözlükte dokunmatik kaydırma önceki/sonraki sayfa (ilerleme yeni sayfaya geçene ya da ayet
    değişene kadar). Aday ayet sönük (parlaklık 3). Satırlar eklentide kırılır (firmware genişlik tablosu
    `@evenrealities/pretext` 0.1.4 MIT ölçülerinden, kerningsiz → güvenli), kutu ≥ satır·27 + 2·padding (yoksa firmware
    kaydırma çubuğu çiziyor), metin kutusu ≤ 999 bayt. Fontta olmayan karakterler (`‘’“”`, NFD tabanı) değiştirilir.
  - **Ön plan servisi** (`util/ListenService`, mikrofon türü): Even uygulamasına geçince / ekran kilitlenince Android arka
    plandaki uygulamanın mikrofonunu susturuyor → dinlerken bildirimli servis. `startService` + `startForeground`
    (hata olursa yakalanır, dinleme eski davranışla sürer; `startForegroundService`'in "zamanında startForeground" çökmesi yok).
- **Kurulum** (iki yol, ikisi de aynı dosyalar): (1) **Geliştirici modu**: Even uygulamasında geliştirici QR'ını okut →
  `http://127.0.0.1:18765/` (sayfa doğrudan köprüden; release'te `tilavet-takip-g2-qr.png`). (2) **.ehpk**: release'teki
  `tilavet-takip-g2.ehpk` EvenHub sitesine (Even hesabıyla) yüklenir, Even uygulamasından açılır (whitelist
  `http://127.0.0.1:18765`). Sıra: eklentiyi aç → Tilavet Takip'e dön → mikrofon; telefon cebe girebilir.
- **Test** (fiziksel gözlük yok): JVM `glasses` (gerçek soket: JSON kaçışları, uzun yoklama, dosyalar, 404 / yol dışı, CORS,
  OPTIONS, port çakışması, kapatınca bekleyen yoklama, `textPx`, eklentinin ekran / sürüm / kod kaynağı / paket sürümü bildirimi,
  host ve geçiş logu, `bigHeader`, `fixedSize`, `blank`, `onePage`, `onePageMinPx`, `blankHeader`, `hideStatus`, `hideRakat`, `bigFont` / `bigWeight` (+ seçenekler = layout.js), aktarım logu — 67 kontrol);
  `tests/g2/layout.test.mjs` (node: satır/sayfa/kutu, büyük yazı puntosu / sayfaları, yazı boyutu ayarı 30-80 (sınırlar,
  dengeli sayfa, tireli bölme), tek ekrana sığdır, zikirde sadece anlam, boş ekran / durum gizli, tüm mealler — CI'da
  `big_px_median` / `big_pages_median` / `onepage_*`); `tests/g2/sim_check.py` —
  **Even Hub simülatörü** (`@evenrealities/evenhub-simulator` 0.9.5, Xvfb + WebKitGTK) uygulamanın kendi köprüsüyle
  52 adım (büyük yazı: boşta, dinleniyor, kısa meal, aday, aday → kilit (gözlüğe 0 karo gitmeli), Âyetü'l-Kürsî baş /
  kaydırma / son, uzun meal, tekbir, yazı boyutu 30 / 64 / 80, hızlı ardışık 3 ekran, başlıksız Kürsî / aday / tekbir,
  sabit yazı boyutu Kürsî / kısa meal / tekbir (2 satırlık metinde 2 karo), tek ekrana sığdır Bakara 2:282 (alt sınır 12:
  tek sayfa, 20: 2 sayfa) / başlıksız Kürsî, ses kesildi (boş ekran + rekât; üst bilgisiz bombos — `EXPECT_EMPTY`: çizili piksel olmamalı) → okuma, durum
  yazısı gizli (boşta / dinleniyor bombos, ayet gelince meal), rekât gizli;
  normal: boşta, dinleniyor, kamet,
  Fatiha, aday, uzun meal + kaydırma + ilerleme, tekbir, üst bilgisiz uzun meal, rekât gizli; Arapça Kevser / Âyetü'l-Kürsî
  baş-son, Arapça'da tekbir, üst bilgisiz Kürsî, Arapça kapat), gözlük ekran görüntüsü + konsol hatası; iki mod:
  geliştirici (aynı kaynak) ve `.ehpk` gibi başka kaynak (CORS, font köprüden). Simülatörün WebKitGTK'si Arapça harekeleri
  çizmiyor; telefondaki WebView (Chromium) çiziyor — 32 px + 0.8 kontur + gama 0.5 Chromium'da 4 bit gri tonda denendi.
- **Telefonda ilk deneme (APK #44, .ehpk EvenHub'a yüklendi):** eklenti "Tilavet Takip bekleniyor", uygulama "EKLENTİ
  BEKLENİYOR" — eklentiden köprüye hiç istek gelmedi. .ehpk Even Hub'ın kendi kaynağından çalışıyor (taraweeh-companion
  değişiklik notu da öyle diyor) → `http://127.0.0.1` köprüsüne cross-origin istek Even uygulamasının WebView'inde
  engelleniyor olmalı (simülatörde yok). Düzeltme (APK #45+, yeni .ehpk): eklenti `127.0.0.1` / `localhost` dener, olmazsa
  `/ping.png` görüntü yoklamasıyla köprüyü bulup sayfayı **doğrudan köprüden açar** (`http://127.0.0.1:18765/?kaynak=ehpk`,
  geliştirici modundaki aynı kaynak; Even köprüsü yeni sayfada da var, ikinci `createStartUpPageContainer` "invalid" →
  `rebuildPageContainer`). Yoklama da olmazsa 3 hatadan sonra bir kez yine dener (2 dk koruma), geçiş sayfa başına bir
  kez otomatik (dış tarayıcıya yönlenirse tekrarlamasın), telefondaki sayfada "Köprüye doğrudan bağlan" düğmesi.
  Tanı: telefondaki sayfa sayfa kaynağı + denenen adres + son hata; gözlükte son hata; ayarlarda "istek yok" / "son istek
  N sn önce"; log `[g2] istek: GET /state kaynak=<origin> ua=...` (her yöntem + kaynak bir kez). Simülatör `--mode engel`
  (fetch engeli taklidi `?test-fetch-engel`) → geçiş + bağlantı.
- Log: `[g2] kopru acildi: http://127.0.0.1:18765/`, `[g2] eklenti baglandi` / `baglantisi yok`; eklenti konsolu `[tt-g2]`.
- **Telefonda (APK #45 + yeni .ehpk):** gözlükte yazı görünüyor (doğrudan köprü geçişi çalışıyor). Sayfa doğrudan köprüden
  açıldığı için eklentinin çizim kodu (app.js / layout.js) **APK'dan** gelir. APK #46+ .ehpk'si köprüye fetch tutsa bile
  sayfayı bir kez köprüden açar (`hopChecked`; geçiş 8 sn'de olmazsa eski sayfa devam eder, yoklama döngüsü `pollGen` ile
  tek) → eklenti değişiklikleri için .ehpk'yi yeniden yüklemek gerekmez (sadece .ehpk'deki geçiş kodu değişirse).
  Ayarlarda "BAĞLI · BÜYÜK YAZI NN PX" görünüyorsa gözlükteki kod APK'nınki.
- **APK #46 telefonda: "Web sayfası mevcut değil — http://127.0.0.1:18765/?kaynak=ehpk net::ERR_CONNECTION_REFUSED".**
  Ekran görüntüsünden: .ehpk sayfası Even uygulamasının **kendi yerel sunucusundan** açılıyor (`http://127.0.0.1:45605`,
  port rastgele olabilir) ve oradan köprüye fetch "Failed to fetch". Köprü kapalıydı (APK güncellenince Android uygulamayı
  kapatır, köprü uygulama açılınca başlar); eski kod 3 hatadan sonra **yoklamasız** köprüye geçiyordu (ya da düğme) →
  WebView hata sayfası, oradan geri dönüş yok (eklenti kapatılıp açılmalı). Düzeltme (APK #47 + yeni .ehpk): köprüye geçiş
  sadece `/ping.png` görüntü yoklaması tutunca (her hatada yeniden yoklanır → uygulama açılınca kendiliğinden geçer); düğme
  önce yoklar, köprü yanıt vermezse uyarır ("yine de bağlan", 30 sn içinde ikinci basış yoklamasız geçer). Telefondaki
  sayfa / gözlükte "telefonda uygulamayı açın (güncellemeden sonra bir kez açmak gerekir)". Eklenti `/state`'e
  `surum=2` ekler → köprü eski .ehpk kodunu ayırt eder, ayarlarda "BAĞLI · ESKİ EKLENTİ (.EHPK'Yİ GÜNCELLEYİN)"; düzen
  değişince hemen bildirilir (uzun yoklamayı beklemez). Geçiş adresinde `yol=goruntu|fetch|dugme|dugme-kor` → log
  `[g2] eklenti sayfasi kopruden acildi: /?kaynak=ehpk&yol=goruntu` (telefonda hangi yolun çalıştığı buradan görülür).
  Simülatör `--mode gec`: fetch engelli + köprü 15 sn geç açılır → eski kod hata sayfasında kalıyordu, yeni kod bekleyip
  köprü gelince bağlanıyor.
- **APK #47 telefon log'u — asıl sebep: Even WebView'inde `127.0.0.1:18765` köprüye ulaşmıyor, `localhost:18765` ulaşıyor.**
  Log'da eklentinin her açılışında `[g2] istek: GET /state kaynak=http://127.0.0.1:<port>` (fetch köprüye geldi, `kaynak` portu
  her açılışta farklı), hemen ardından #46-47'nin "fetch tuttu → sayfayı köprüden aç" geçişi `http://127.0.0.1:18765/?...&yol=fetch`
  → **ERR_CONNECTION_REFUSED** (bu istek köprüye hiç gelmedi), görüntü yoklaması da "yok". Git geçmişi: sadece 127.0.0.1 kullanan
  #43-44 hiç bağlanmadı ("istek yok"), `localhost` eklenen #45 bağlandı (fetch'in 1. denemesi 127.0.0.1'de düşüp 2. deneme
  localhost'ta tutuyordu). Neden 127.0.0.1'in engellendiği bilinmiyor (Even uygulaması kendi sunucusunun adresini — 127.0.0.1 —
  yakalıyor olabilir). Düzeltme (APK #48 + yeni .ehpk):
  - Her yerde önce `localhost` (fetch adresleri, görüntü yoklaması, son çare geçiş adresi, geliştirici QR'ı `http://localhost:18765/`).
  - Fetch tutunca sayfa geçişi **yok** (geçiş sadece fetch iki adreste de düşüp `localhost/ping.png` yoklaması tutarsa).
  - **`boot.js` yükleyici** (index.html'in tek betiği): köprüden `g2-kod.json` (`{"boot": 1, "surum": 3}`) + `layout.js`, `sdk.js`,
    `app.js` fetch ile alınıp blob adresinden `import` edilir (`./layout.js` / `./sdk.js` importları blob adresine çevrilir) →
    eklenti kodu APK'dan gelir, sayfa geçişi olmadan; köprü yoksa / eski APK'da `g2-kod.json` yoksa / blob import çalışmazsa
    paketteki kopya (`./app.js`). `boot` alanı yükleyiciyle köprüdeki kodun sözleşmesi (import satırları değişirse artır).
  - Fontlar fetch → `ArrayBuffer` → `FontFace` (CSS `url()` değil); yüklenemezse 5 sn sonra yeniden denenir (eskiden ilk hata sayfa
    boyunca kalıyordu → köprü geç açılınca büyük yazı hiç gelmiyor, normal yazıya düşüyordu); köprü bağlanmadan font istenmez.
  - `/state` `surum=3&kod=kopru-3|paket|dogrudan`; köprü `surum < 3` → ayarlarda "BAĞLI · ESKİ EKLENTİ (.EHPK'Yİ GÜNCELLEYİN)"
    (`GlassesBridge.PLUGIN_VERSION`), `[g2] eklenti kodu: kopru-3`, istek logunda `host=localhost:18765` (hangi adresin tuttuğu).
  - Simülatör: `cross` modunda kod köprüden + geçiş yok şartı; yeni `gec-fetch` modu (telefondaki durum: başka kaynak, fetch tutuyor,
    köprü 15 sn geç) → geçişsiz bağlanır, font yüklenip büyük yazıya geçer.
- **.ehpk sürümü (APK #49+):** kullanıcı "ehpk aynı versiyon kalmış, Even yeni build'i algılamıyor". Paketleyici sürümü pakete
  yazıyordu (`0.1.47` / `0.1.48` paketleri farklı) ama sadece son hane değişiyordu → sürüm artık `0.<build>.0`; release'te
  `tilavet-takip-g2-0.<build>.0.ehpk` kopyası da var. CI paketlerken `g2-paket.json` (`{"surum": "0.<build>.0"}`) yazar →
  `boot.js` okur, eklenti `/state`'e `paket=` ekler: telefondaki eklenti sayfasında "eklenti 0.49.0", ayarlarda
  "BAĞLI · BÜYÜK YAZI 48 PX · EKLENTİ 0.49.0", log `[g2] eklenti paketi: 0.49.0` (Even'ın hangi paketi açtığı görülür).
- **Büyük yazıda geçiş hızı + sure / ayet satırı (APK #50+):** kullanıcı (#49, gözlükte bağlandı): "geçişler yavaş, yenileme
  efekti var gibi"; "bu modda ayet adı ve numarası yazmıyor". Görüntü yolu doğası gereği karo karo (4 × `updateImageRawData`,
  sırayla; en fazla 4 görüntü kutusu → çift tampon yok), ekran çeyrek çeyrek değişiyor. Yapılanlar:
  - **Eski ekran yarıda bırakılır:** karolar gönderilirken yeni durum gelirse (ara ayetler, AyahStepper, hızlı kilit) eskinin
    kalan karoları gönderilmez, doğrudan yenisine geçilir (log `eski ekran yarida birakildi`). Değişmeyen karo zaten gitmiyordu.
  - ~~İki tonlu karolar~~ (APK #50, #51'de geri alındı): LZ4'lü veri ~%20 azalıyordu ama gönderim süresinin çoğu çağrı başına
    sabit (aşağıda) → hız farkı ihmal edilebilir; kenar yumuşatma (gama 0.7, aday × 0.6) geri geldi.
  - **Sure / ayet satırı** (Ayarlar → **G2'DE SURE / AYET ADI**, varsayılan AÇIK; `GlassesState.bigHeader`): `bigh` düzeni —
    üstte gözlüğün kendi yazısıyla `Bakara 2:255 · 1. REKÂT · KIYAM  1/6` (sayfa etiketi; aday `· ADAY` + sönük başlık), altında
    576×256 büyük yazı (4 × 288×128 karo; `bigAreaHeight`, `bigOptions(px, 256)`). Başlık metin kutusu → anında değişir,
    görüntü göndermez; **ADAY → kilit** sadece başlığı değiştirir, büyük yazı parlak kalır → karolar yeniden gitmez (eskiden
    sönük → parlak 4 karo). KAPALI: eski tam ekran (`big`; aday sönük yazı, sağda sayfa çubuğu).
  - Tanı: eklenti her ekran aktarımını köprüye bildirir (`/state?...&aktarim=4x820`) → log `[g2] eklenti aktarim: 4 karo 820 ms`,
    telefondaki eklenti sayfasında "son aktarım" (gerçek gözlükte süre buradan ölçülür).
  - Cevaplar: ayet bölme punto ile (tek sayfaya sığan en büyük punto 120 → ayardaki en küçük; onda da sığmazsa satırlar
    sayfalara eşit dağılır, sayfa imamın ilerlemesiyle), anlama göre değil. Ekranın tamamı (576×288) zaten eklentide; ana
    menü / Even AI daha büyük görünüyorsa Even'ın kendi katmanı / büyük arayüz öğeleri — SDK'da yok (bkz. "Ekran alanı / derinlik").
- **"Hâlâ 4 parça hâlinde yükleniyor, hepsi aynı anda görünemez mi?" (APK #51 araştırması):** hayır. SDK 0.0.16 (npm'deki son
  sürüm) görüntüyü kutu kutu `updateImageRawData` ile alıyor; toplu / gizli / çift tampon API'si yok, sayfada en fazla 4 görüntü
  kutusu (her biri ≤ 288×144) → 576×256'lık büyük yazı 4 gönderim. Topluluk ölçümü (`nickustinov/even-g2-notes`
  docs/performance.md, page-lifecycle.md; G2 firmware 2.2.7, SDK 0.0.13): gönderim ~104 ms sabit + ~4 ms/KB gray4 (288×144 ≈
  20 KB → ~185 ms), gönderimler **sıralı olmak zorunda** (eşzamanlı yasak), her kutu kendi gönderimi bitince görünür →
  4 karo ≈ 0.7 sn, çeyrek çeyrek. `rebuildPageContainer` görüntüleri siler ve titretir; metin kutusunun arka plan dolgusu yok
  (görüntüyü örtüp birden açmak olmaz). Anında değişen tek yol gözlüğün kendi yazısı (`textContainerUpgrade`, ~83 ms, titremesiz)
  — o da büyütülemiyor (NORMAL düzen). Yapılabilen: daha az karo göndermek (değişmeyen karo zaten gitmiyor, ADAY → kilit 0 karo,
  sabit boyutta kısa metin 2 karo).
- **Sabit yazı boyutu (APK #51+, Ayarlar → G2 SABİT YAZI BOYUTU, varsayılan KAPALI; `GlassesState.fixedSize`):** kullanıcı "kısa
  metinlerde büyük, uzun metinlerde küçük font olmasın, hepsinde aynı olsun; pasifken şu anki gibi". Açıkken `bigOptions(px, h,
  true)` → `maxPx = minPx = G2 YAZI BOYUTU`: her metin bu puntoda, sığmayan meal sayfalara (eşit dağılır). Blok dikeyde ortada
  değil **üstten** (satırlar her ekranda aynı yerde; ≤ 2 satırlık metin sadece üst iki karoda → alt karolar boş kalır,
  gönderilmez: 4 yerine 2 karo). Köprüye `ekran=buyuk 48px sabit` → ayarlarda "BÜYÜK YAZI 48 PX SABİT".
- **Gözlük ekranı ayarları (APK #103+):** kullanıcı (APK #102): "ayet 2-3 sayfada gösterilince tüm ayeti okumak zor, gerekirse
  fontu küçültsün"; "ekran boş kaldığında üst bilgi durmasın, ayara bağla"; "rükün seslerinde Allahu ekber Allah en büyüktür
  olmasın, direkt Allah en büyüktür yazsın"; "hide status: Dinleme kapalı yazısı çıkmasın, ekran bomboş olsun"; "ayetler akarken
  de üst bilgiyi kapatan ayar olsun".
  - **G2 AYETİ TEK EKRANA SIĞDIR** (varsayılan KAPALI, `GlassesState.onePage`, büyük yazıda): `bigOptions(px, h, fixed, true,
    onePageMinPx)` → `minPx` = alt sınır, `fewestPages`: sığan en büyük punto aranır (sabit boyut açıksa en büyüğü ayardaki punto —
    kısa metin büyütülmez). **Alt sınır** Ayarlar → **G2 TEK EKRAN EN KÜÇÜK YAZI** (12-40 px, 2 px adım, varsayılan 20, ayardaki
    G2 YAZI BOYUTU'ndan büyük olamaz; `onePageMinPx`, `layout.ONE_PAGE_PX`; APK #104+ — kullanıcı: "alt sınır punto ayarını
    kullanıcıya bırak, altında kalacaksa yine sayfalama yaptır"; APK #103'te sabit 12): alt sınırda da sığmazsa sayfalar — alt
    sınırdaki sayfa sayısı (en az sayfa) ve o sayfa sayısına sığan en büyük punto. Tüm Bulaç meallerinde (APK'daki meal.bin,
    yaklaşık ölçü, başlıklı düzen): alt sınır 12'de hiçbiri sayfalanmıyor (ortanca 36 px, en küçük 12 px: Bakara 2:282, 1129
    karakter; 2:102 / 4:12 ~14 px); 20'de 99 meal sayfalı, en çok 3 sayfa (Bakara 2:282 iki sayfa ~20 px). Köprüye
    `ekran=buyuk 36px tek` → ayarlarda "… TEK SAYFA".
  - **G2 BOŞ EKRANDA ÜST BİLGİYİ GİZLE** (varsayılan AÇIK = gizli, `AppSettings.glassesHideBlankHeader`, `GlassesState.blankHeader`
    = tersi): ses kesilince (TextHold) gözlük bombos; kapalıyken eski davranış (üstte `1. REKÂT · RÜKÛ / SECDE`, APK #52-102).
  - **G2 DURUM YAZISINI GİZLE** (varsayılan KAPALI, `hideStatus`): dinleme kapalıyken ve ayet bulunana kadar ("Dinleme kapalı",
    "Dinleniyor", "Kamet · Fatiha bekleniyor") gözlük bombos; zikir / ezan kartı ve ayet gelir; bağlantı yoksa tanı ekranı (ayar
    bilinmiyor).
  - **Zikir / ezan kartı gözlükte sadece Türkçe anlamı** (ayarsız; `layout.noteText`: anlam, yoksa okunuş, yoksa başlık): tekbir,
    semiallah, rabbena, selam, namaz sonu duası, ezan / kamet cümleleri. Başlık (TEKBİR / KAMET + rekât) üst bilgide kalır
    (G2 ÜST BİLGİ kapalıysa yok). Telefondaki kart değişmedi (Arapça + okunuş + anlam).
  - Eski **G2'DE SURE / AYET ADI** ayarının adı **G2 ÜST BİLGİ (AYET OKUNURKEN)** oldu (davranış aynı: KAPALI → üst bilgi hiç
    çıkmaz, ekranın tamamı meal; `bigHeader`).
- **Büyük yazı fontu + kalınlığı (APK #110+, sadece gözlük):** kullanıcı: "G2 fontunu seçmezsem senin resim üreterek
  oluşturduğun fontun birkaç seçeneği olsun; bilimsel olarak rahat okunabilirliğini araştırdığın 3 font daha, kalın ince
  seçenekleri mutlaka; ayarlardan seçilsin, seçtiği anda gözlükte değişsin; telefona değil". Ayarlar → **G2 YAZI TİPİ**
  (Manrope varsayılan / Atkinson Hyperlegible / Lexend / Inter) ve **G2 YAZI KALINLIĞI** (İNCE 300 / NORMAL 500 / KALIN 700
  varsayılan / ÇOK KALIN 800), büyük yazıda (Arapça kapalıyken) görünür; `GlassesState.bigFont` / `bigWeight`
  (`FONTS` / `WEIGHTS` = layout.js `BIG_FONTS` / `BIG_WEIGHTS`, JVM testi karşılaştırır).
  - Seçim (21.10): **Atkinson Hyperlegible Next** (Braille Institute, 2025; az görenlerle test edilerek tasarlandı, benzer harfler
    ayrık — I l 1, O 0), **Lexend** (Shaver-Troup'un okuma akıcılığı araştırması: genişletilmiş harf aralığı; kanıt sınırlı —
    çoğunlukla bir sınıf çalışması), **Inter** (ekran için, yüksek x-yüksekliği). Wallace ve ark. 2022 (ACM TOCHI, 16 font): herkes
    için en iyi font yok, en hızlı font kişiye göre değişiyor (en hızlı / en yavaş arası %35) → seçenek sunmanın gerekçesi.
    Elenenler: **B612** (Airbus + ENAC kokpit ekranı fontu — gözlüğe en uygun fikir ama ğ ı İ ş yok), **Andika** (SIL, okuma
    öğrenenler; ince kalınlığı yok), Noto Sans (2 MB, araştırma gerekçesi zayıf).
  - Fontlar `assets/g2fonts/<id>.ttf` (google/fonts reposundaki değişken OFL dosyaları **aynen**, lisanslar `OFL-<id>.txt`;
    .ehpk paketine girmez), köprü `/g2font-<id>.ttf` (`MainViewModel.glassesFile`). Hepsinde 7 mealin tüm karakterleri +
    Türkçe harfler var (node testi TTF cmap'ini okur: `g2_fonts_dropped_chars` 0). Satır 1.16 em hepsine yetiyor (şapkalı büyük
    harf + kuyruk: Manrope 1.24 em, diğerleri 1.04-1.19).
  - Eklenti (`app.js` `wantBigFont`): `FontFace(aile, veri, {weight: '100 900'})` (aralık verilmezse tarayıcı kalını sahte
    kalınlaştırır); kalınlık değişimi anında, font değişiminde yeni font yüklenene kadar eskisi (ekran boş kalmaz / titremez);
    yüklenemezse Manrope, o da yoksa eski köprünün `manrope.ttf`'i (700). Yerleşim önbelleği ve karo anahtarı fonta göre →
    değişince karolar yeniden gider. Köprüye `ekran=buyuk 48px lexend 300` → ayarlarda "BÜYÜK YAZI 48 PX · LEXEND İNCE".
  - Simülatör: Atkinson ince / çok kalın, Lexend kalın, Inter normal + kısa meal, Manrope'a dönüş — her değişimde gözlüğe karo
    gitmeli (`MIN_TILES`), konsolda "font yuklenemedi" olmamalı.
- **Rekât bilgisini gizle + her düzende üst bilgi gizleme (APK #105 sonrası):** kullanıcı (APK #104): "üst bilgi aktifse rekât
  belirtecini gizleme parametresi belirsin, hide yaparsa sadece sure adı: ayet no çıksın"; "G2'nin kendi fontunu seçince (büyük
  punto yerine) üst bilgiyi gizleme ayarı kayboluyor, o zaman da gizleyebilmek istiyorum".
  - **G2 REKÂT BİLGİSİNİ GİZLE** (varsayılan KAPALI, `AppSettings.glassesHideRakat`, `GlassesState.hideRakat`; ayarlarda sadece
    G2 ÜST BİLGİ açıkken): üst bilgide `Bakara: 255 1/6` (rekât / duruş yok); boş ekranda üst bilgi açıksa da rekât yazılmaz
    (bombos); zikir / ezan kartının başlığı (TEKBİR, KAMET) kalır.
  - **G2 ÜST BİLGİ (AYET OKUNURKEN)** artık her düzende (ayarlarda büyük yazıdan bağımsız): gözlüğün kendi yazısında (NORMAL)
    KAPALI → `textn` düzeni (başlık kutusu yok, 10 satır meal, ekranın tamamı), Arapçada → `arabicn` (2 Arapça karo en üstte,
    altında 6 satır meal). Sayfa etiketi başlıkla birlikte gider; sayfa yine imamın ilerlemesiyle / kaydırmayla.
- Kalan: gerçek gözlükte deneme (parlaklık, görüntü hızı, Arapça okunurluğu, kaydırma yönü); Even uygulamasının geliştirici
  modunda `http://` localhost'a izin verdiği varsayıldı (CLI'ın varsayılan şeması http).

### Zümrüt teması — varsayılan (APK #30+)
- Kullanıcı "Namazda Anla" tanıtım görsellerini verdi: "yepyeni tema, varsayılan olsun, eski temalar dursun, görsellerdeki
  kaliteyi yakala". Krem kâğıt zemin (`#F8F2E6` → `#F1E8D7` gradyan + sağ üstte gün batımı ışıltısı), koyu zümrüt
  (`#0E2A1F`/`#1A4433`/`#1D5A3D`), altın (`#C6A15B`, metin `#9C7838`), nane (`#E0ECE2`).
- `ui/theme/Palette.kt` (Android'siz — masaüstü düzeneğinde de derlenir): `AppTheme` (ZUMRUT ilk, `DEFAULT`),
  `AppPalette`, **`AppStyle`** (yazı tipleri + `ornate` + süs renkleri), `Styles.CLASSIC` (Cormorant/JetBrains — eski 7 tema
  **piksel piksel aynı**, masaüstü düzeneğinde 3 tema × 4 durum diff = 0) / `Styles.ZUMRUT`. `LocalAppStyle`; Material
  tipografi `typographyFor(style)`.
- Yazı tipleri APK'ya gömülü (`res/font`, SIL OFL 1.1, dosyalar değiştirilmedi, telif + lisans `res/raw/ofl_fonts.txt`):
  **Playfair Display** 500/600/700 (başlık), **Lora** 400/500 (meal, `bodyScale` 0.9), **Manrope** 500/600/700 (büyük harf
  etiketler, geniş aralık). Google Fonts sağlayıcısı telefonda yüklenmiyor — o yüzden gömülü.
- `ornate` çizim (klasikte kod yolu aynen):
  - **Üst bant** (`MainScreen.OrnateHeader`): TopBar + durum satırı tek koyu zümrüt bantta, altı 26dp yuvarlak + yeşil gölge;
    sağ altta soluk cami silueti, sağ üstte altın ışıltı (`Ornaments.headerBackground`); solda altın kemer+hilal amblemi,
    durum (canlı nokta altın), sure adı Playfair (sığmazsa 22 → 16 sp küçülür) + numara altın; ikonlar cam daire
    (beyaz %9 + altın hat); altın ince çizgi; durum satırı nane rengi. Sistem çubuğu: üst koyu zümrüt, alt beyaz.
  - **Sure başlığı**: üstü kemerli beyaz kart (`ArchTopShape`, altın hat, gölge) — amblem, `1. SURE · 7 AYET`, Playfair 30sp
    sure adı, Arapça ad altın, `—✦—` ayraç; besmele kartın altında.
  - **Ayet**: okunan ayet gölgeli beyaz kart (22dp köşe, altın hat; animasyonlu, metin yerinden oynamaz), etiket hapı
    (okunan: dolu zümrüt, diğer: nane), ayet sonu işareti altın, diğer ayetler arasında iki yana solan altın çizgi.
  - **Alt bar**: gölgeli beyaz, üstü yuvarlak; altın büyük harf etiketler; mikrofon her zaman zümrüt gradyan + altın halka
    (dinlerken altın dalga), simülasyon butonu nane daire; ses çubuğu zümrüt → altın.
  - Ayarlar (Playfair başlık, altın ayraçlar, Zümrüt örneği koyu bant + cami silueti), ezan penceresi (amblem + Manrope),
    boş ekran (büyük amblem).
- Tema anahtarı `theme_v2` (DataStore): eski kurulumlarda da Zümrüt bir kez gelsin diye; eski temalar ayarlardan seçilir.
- **Marka metniyle inceltme (APK #31+):** kullanıcı "Namazda Anla" marka metnini verdi (sakin, manevi, modern
  Islamic-tech; krem/parşömen, derin orman yeşili, **zeytin yeşili**, hafif altın, yumuşak yeşil glow / yarı saydam
  HUD; başlıkta serif, **gövdede okunaklı sans-serif**; Arapça geniş satır aralıklı; aktif ayet belirgin, diğerleri
  silik; hafif İslami geometrik desen, mihrap/kemer). Uygulananlar:
  - Meal **Manrope 400** (Lora kaldırıldı), `bodyScale` 0.86, satır 1.55; Arapça satır aralığı 2.0 (zümrütte).
  - Okunan ayet **HUD kartı**: fildişi → çok açık yeşil (`hudTint`) zemin, yeşil ışıltı gölgesi (`hudGlow`), ince orman
    yeşili çerçeve; diğer ayetlerin etiketi nane hap + zeytin yazı. Ezan penceresi de aynı yeşil ışıltıda.
  - Üst bantta soluk altın **8 köşeli yıldız + haç deseni** (`starPatternPath`, soldan sağa belirginleşir), sure başlığı
    kartının kemer altında da soluk desen; krem zeminin altında çok soluk **mihrap kemeri dizisi**.
  - **Logo:** üst bantta logo madalyonu (`BrandLogo` = uygulama ikonu), boş ekranda büyük logo + "Duyduğun ayeti
    anlamaya bir adım daha yaklaş."; amblem (ayarlar, ezan, sure kartı) logodaki sivri kemer + 4 köşeli yıldız + kitap.
  - Alt bar boştayken tireler yerine "**Dinle ve anla** / İmam okur, sen anlamını takip et." (dinlerken SURE/GÜVEN/SES).
  - Klasik 7 tema yine piksel piksel aynı (3 tema × 4 durum diff = 0).

### Uygulama ikonu = Namazda Anla logosu (APK #31+)
- Kullanıcının verdiği logo (krem daire, yeşil halka, sivri kemer içinde 4 köşeli yıldız + "N", kalın çerçeveli gözlük,
  iki katlı açık kitap) piksel ölçümüyle **vektör** olarak yeniden çizildi: `tilavet-android/tools/gen_launcher_icon.py`
  → `res/drawable/ic_launcher_foreground.xml` (gradyanlı), `ic_launcher_background.xml` (krem radyal),
  `ic_launcher_monochrome.xml` (Android 13 tema ikonu). Adaptive icon (108 viewport, halka r=30, güvenli alan içinde).
  Değiştirmek için betiği düzenleyip çalıştır (XML'leri elle değiştirme). Masaüstü düzeneğinde logo ile yan yana,
  daire / yuvarlak kare maskede ve 48-192 px boyutlarda kontrol edildi. Uygulama adı hâlâ "Tilavet Takip".
- Masaüstü Compose düzeneğinde 10 durum (boşta, Fatiha, kilit, aday, uzun ayet, simülasyon, ASR test, kamet, ayarlar, boş)
  görsel kontrol edildi.

### Kuran fontu = KFGQPC HAFS Uthmanic Script, APK'ya gömülü (APK #23+)
- Eskiden Arapça (Amiri Quran) + Latin fontlar Google Fonts'tan **indiriliyordu** — telefonda hiç yüklenmedi
  (ekranda sistem fontu; namazda internet de yok). Kullanıcı: "Tarteel'deki gibi olsun".
- `res/font/kfgqpc_hafs.ttf` = quran.com / Tarteel'in fontu (KFGQPC v0.18, `UthmanicHafs1Ver18.ttf`, quran.com-frontend-next
  reposundan). Lisans (font içinde): ücretsiz kullanım/kopya/dağıtım, satılamaz/değiştirilemez → dosya **aynen**.
- Ayet sonu: sadece Arapça rakam (`٢`) — font onu süslü çerçeveli ayet işareti olarak çiziyor (﴿﴾ kaldırıldı).
- `MushafData.displayText`: Tanzil Uthmani → KFGQPC yazımı (sadece ekran, pozisyonlar aynı): 0652→06E1 (sükûn ۡ),
  06DF→0652 (yuvarlak sıfır; KFGQPC'de 06DF noktalı daire), tatweel+0670→0670, 06EB→06EC, 06E3 çizilmez.
  HarfBuzz ile 6236 ayet: dönüşümden sonra noktalı daire/eksik glif yok.
- Boyut: KFGQPC aynı sp'de sistem Naskh'tan ~%16 dar (ölçüm: 14:2 ilk 8 kelime, Noto Naskh 832 px / KFGQPC 717 px)
  → `QURAN_FONT_SCALE = 1.15` ile çizilir; ayardaki Arapça boyut aynı görünür.
- Vurgulu kelimeler tek bant (aradaki boşluk da vurgulu). Ayet etiketi `İbrâhîm: 2` (`MushafData.ayahTag`; APK #52'ye kadar
  `14-İbrâhîm:2` — kullanıcı: "7:55 gibi göstermesin, önce sure adı sonra ayet"; log'larda `label()` = `İbrâhîm 14:2`).
- Latin fontlar (Cormorant, JetBrains Mono) hâlâ Google Fonts (telefonda sistem fontu çıkıyor) — sadece klasik temalarda;
  Zümrüt temasının fontları gömülü (aşağıda).

### Mushaf görünümü (Tarteel benzeri) ✅
- Ekranda tüm Kuran tek `LazyColumn`: 114 sure başlığı (Türkçe + Arapça isim, ayet sayısı, besmele) +
  6236 ayet (etiket `55:5`, Uthmani metin + `﴿٥﴾`, meal). Açılışta yüklenir, dinlemeden de okunur.
- `MushafData`: QuranIndex'ten string üretmeden ayet sınırları (`getSurahAyah`), `ayahOfWord` (ikili
  arama), besmele 1. ayetten gizlenip başlıkta gösterilir (kelime pozisyonları değişmez).
- Sese göre takip: okunan ayet = eşleşmenin son kelimesinin ayeti; ekranın üstünden 90dp aşağıya
  kayar (önceki ayetin sonu görünür), eşleşen kelimeler vurgulu. PENDING aday da gösterilir ("ADAY",
  soluk vurgu) — kilit doğrulanmadan kullanıcı nerede olduğunu görür.
- **Elle kaydırma (APK #25+):** kullanıcı listeyi parmakla sürükleyince (`listState.interactionSource`
  `collectIsDraggedAsState`) takip **durur ve kendiliğinden geri dönmez** (eskiden 1.5 sn sonra okunan ayete
  dönüyordu — kullanıcı önceki/sonraki ayetlere bakarken ekran elinden kaçıyordu). Sağ altta (mikrofonun
  üstünde) yuvarlak **ok butonu** belirir (ok okunan ayetin yönünde); basınca takip devam eder ve okunan ayete
  gidilir. Kaydırmadan dokunmak takibi bozmaz; yeni dinleme/simülasyon takip açık başlar. Okunan ayet ekrandaki
  satırdan **8 satırdan uzaksa** (`FAR_JUMP_ITEMS`, ayet/sure başlığı) animasyonsuz atlanır (başka sureye geçişte
  yüzlerce ayetlik kaydırma animasyonu ayetin gelmesini geciktiriyordu), yakınsa yumuşak kayar.
  Desktop Compose harness'te test edildi (sürükle → buton, 4 sn bekle → dönmüyor, buton → 55:9, yakın animasyonlu,
  2:255'e 80 ms'de atlıyor).
- **Atlanan ayetler sırayla (APK #27+):** kullanıcı (cuma, Fatiha): "2. ayetten 5'e atlıyor". Kilitli eşleşme aynı
  surede birden fazla ayet ileri giderse ekran aradaki ayetlerde sırayla durur (tamamı vurgulu), sonra okunan ayete geçer
  (`ui/AyahStepper.kt`, `MushafData.skippedAyahs`). Süre ayarda: **ATLANAN AYET SÜRESİ** 0-2 sn, 0.1 sn adım (varsayılan
  0.5; 0 = kapalı, `AppSettings.skippedAyahTenths`). Sadece kilitli eşleşme (aday değil), aynı sure, en fazla 7 ara ayet
  (`AyahStepper.MAX_SKIPPED`); sure geçişi / geri gidiş / uzak atlama doğrudan. Adımlarken yeni konum gelirse ekrandaki
  ara ayetten yeni hedefe devam eder (ekrandaki ara ayet süresini doldurur); geri gidiş hemen, kamet keser.
  Log: `ara ayetler: Fâtiha 1:3 .. Fâtiha 1:4 → Fâtiha 1:5 (500ms/ayet)`.
  **Sure başı (APK #28+):** başka sureye geçiş (Fatiha → zamm, zamm → 2. rekât Fatiha'sı, sure → sure) hedef surenin
  ilk 5 ayetine düştüyse surenin başından adımlanır (`AyahStepper.MAX_OPENING` = 4; Fatiha'da 1:2'den, besmele sessiz):
  cuma #2'de Asr'a 103:3'te kilitlenip 103:1-2 hiç görünmemişti. Sure ortasına geçiş (21:104) doğrudan.
  Ölçüm (34 kayıt, replay): ardışık kilitlerin ~%8'i aynı surede 2-3 ayet ileri (rnnt 27/227, hibrit 17/245; ör. 1:2→1:4,
  94:5→94:7, 107:1→107:3); cuma hibrit 1:2 → 1:5 (88 sn'deki "الرحمن الرحيم" parçası ASR'de boş döndü). Sebep: boş/kısa
  parça ya da tek parçaya iki kısa ayet sığması. Masaüstü Compose düzeneğinde 12 zamanlama senaryosu + ekran testi.
- **Ezan / kamet penceresi (APK #26+):** kamet/ezan sinyaliyle (`ChunkResult.kamet`, açık sorun 10'daki Kuran'da
  geçmeyen kalıplar) liste üstünde kart açılır: tüm cümleler Arapça + Türkçe anlamı (Diyanet), okunan cümle vurgulu
  (okunmuşlar normal, sonrakiler soluk); sabah ("الصلاة خير من النوم") ve kamet ("قد قامت الصلاة") satırları duyulunca
  eklenir, başlık EZAN / KAMET / "EZAN · KAMET" (belli değilken). `session/EzanTracker.kt`: ASR'ye dayanıklı anahtar
  kelime kuralları ("بل قام بالصلاة" = kad kâmeti's-salâh, "الصلاة حي الصلاة" = hayye ale's-salâh), sıra hep ileri.
  **Kapanış yeni ses beklemeden:** son "لا إله إلا الله" → 2.5 sn gösterip kapanır; son tekbirden 12 sn içinde tevhid
  yoksa ya da 40 sn hiç cümle yoksa kapanır (APK #41'e kadar 25 sn — bkz. açık sorun 16); Kuran'a kilit (FATIHA/ZAMM) → hemen. Kullanıcı sağ üstteki kırmızı
  çarpıyla ya da kartı sağa/sola sürükleyip bırakarak (kart dönerek uçar; az sürüklenirse yerine yaylanır) kapatır →
  o ezan/kamet bitene kadar tekrar açılmaz. Cuma kaydı (JVM): rnnt 20 sn'de açılır → 60 sn'de son tevhidle kapanır;
  hibritte son tevhid ASR'de yok → 69 sn'de (iftitah tekbirinden önce) kapanır; diğer 33 kayıtta hiç açılmaz.
  Ezan (müezzin uzun makamla okuyor) ASR'de kötü tanınabilir (namaz #2 log'undaki ezan: "المصدر كتاب", "المحمد" →
  işaret yok → pencere açılmaz). KFGQPC fontu Arapça virgülü (،) dolu daire çiziyor → metinlerde virgül yok.
- **Ekran düzeni (APK #17+):** tek sütun — TopBar → **durum satırı** (tek satır, sabit, alt çizgiyle ayrık)
  → Mushaf listesi (kendi alanında kayar, üst alanların altına girmez) → Footer. Durum satırı: model
  durumu (beklemede / kopyalanıyor / yükleniyor / hazır / hata), dinlerken `güven %X · gecikme Y sn`
  (parça sonu → ekran), ASR testinde `ASR TEST <arapça metin> RNNT 612ms`; en sağda `#<CI run> · <commit>`
  (`BuildConfig.CI_BUILD` / `GIT_SHA`, CI'da `GITHUB_RUN_NUMBER` / `GITHUB_SHA`, yerelde "yerel").
  Eskiden ASR TEST kutusu listenin üstüne biniyordu ve model "Hazır" olunca hiç kapanmıyordu.
  Σ # ▶ test sonuç panelleri dokununca kapanır.

---

## Şu an nerede kaldık — AÇIK SORUNLAR

### 1. Skor problemi — iki kök neden bulundu ve düzeltildi (APK build #3+)
**a) Uthmani korpus vs imla'i ASR:** korpus Uthmani, FastConformer imla'i yazıyor. Normalize
Uthmani'deki küçük elifi siliyor → kelimelerin ~%10'u hiç eşleşmiyordu (العلمين/العالمين,
ملك/مالك, الصرط/الصراط, الكتب/الكتاب, الصلوه/الصلاه) → vocab_coverage ve fuzzy düşük.
Çözüm: `aligner.py` `QuranCorpus.load()` her kelimenin `normalized` alanını Tanzil rasm_map'teki
**imla'i karşılıktan** üretir (bkz. "Bilinen kritik detaylar"). Ekranda Uthmani `text` aynen kalır.

**b) ChunkBuilder overlap hatası (app.py'den birebir port edilmişti):**
`overlap_tail = current[CHUNK-OVERLAP:CHUNK]` 2. chunk'tan sonra sondan 2. saniyeyi alıyordu →
3. chunk'tan itibaren her chunk'ta 1sn geriden yapıştırma + 1sn atlama. ASR ek yerinde kelimeyi
ortasından kesik duyuyor, **çift karakterlerin asıl kaynağı buydu** (eval'de `من وسوواس الخناس` →
düzeltmeyle `من شر الوسواس الخناس`, skor 69.7 → 100). Kotlin + app.py'de düzeltildi: tail = son 1sn.

**Ölçüm** (eval.yml, CTC ONNX, 27 kayıt, 144 skorlanan chunk, BEKLEME modu):

| | medyan | ≥70 | ≥90 |
|---|---|---|---|
| eski (overlap hatası + Uthmani) | 72.8 | 72 | 18 |
| yeni (düzeltilmiş chunk + imla'i) | 79.2 | 99 | 39 |

Kuran dışı konuşma (test_arapca_sohbet) en fazla 45.7, Türkçe/sessizlik too_short/empty.
Yanlış sure eşleşmeleri (≥70) kısa ve Kuran'da birden çok yerde geçen ifadeler
(`قل أعوذ برب` 113:1/114:1, `الذين آمنوا وعملوا`, `له ما في السماوات`) → eşik değil, pending
doğrulaması (2 ardışık tutarlı chunk) koruyor. **Öneri: ilk kilit eşiği 70 kalsın** (90 ile
chunk'ların sadece ~%27'si geçer, kilit çok gecikir).

### 2. Aligner hızı — bit-parallel LCS ile ~10x (APK build #7+)
- Eskiden case başına 5-15sn (saf Kotlin DP) → BEKLEME'de chunk'lar birikiyordu (ilk kilit gecikmesi).
- `Fuzzy.kt`: Hyyrö/Allison-Dix bit-parallel LCS (Indel = |a|+|b|-2·LCS, sonuç DP ile birebir).
  partial_ratio'da tüm pencereler shorter'ın tek pattern'iyle ölçülür (LCS simetrik), longer'ın
  karakter→maske satırı bir kere hesaplanır, ≤64 karakterde tek Long hızlı yol.
- JVM ölçümü: 43 aligner case 22.6 sn → 2.6 sn (~10x); 51 fixture + 20000 rastgele çift + 43 aligner
  sonucu eski DP ile **birebir**. Kalan maliyet Aligner'ın kendi string/HashMap işleri.

### 3. ASR kalitesi — RNNT decoder'a geçildi (APK build #6+)
- Çift karakterlerin çoğu chunk overlap hatasından geliyordu (yukarıda, düzeltildi).
- CTC head temiz kayıtta bile kelime birleştiriyordu (`الرَّحْمَنَِّحِيمِ`, `كفواحد`). Android artık
  varsayılan olarak **RNNT greedy** kullanıyor (server/benchmark ile aynı decoder). Tuner'da
  `ASR DECODER: RNNT / CTC` seçimi var (A/B için; model RNNT içermiyorsa otomatik CTC).
- eval.yml (27 kayıt, BEKLEME modu): medyan skor CTC 79.2 → RNNT **91.5**, ≥70: 99 → 108,
  ≥90: 39 → 65; Kuran dışı max ~45 (değişmedi); ASR süresi +%9. Örnek: `فَانقَضَ هْرَك وَرَرفَعْنا`
  (19.0) → `قض ظهرك ورفعنا لك ذكرك` (86.8), `والحجر يسجدان والسم` (49.5) → `والشجر يسجدان والسماء` (100).
- Besmele filtresi düzeltildi: `بسم الله الرحمن الرحيم قل هو الله` (sure başı) eskiden "sadece
  besmele" sayılıp reddediliyordu (الله de besmele kelimesi → 5/7 oran). Artık başta tam besmele
  varsa karar, kalan kelime sayısına göre (2+ kelime → hizala). aligner.py + Aligner.kt birebir.

### 4. İlk kilit gecikmesi (kullanıcı: "surenin ortasında buluyor") — düzeltildi (APK build #8+)
- Hesaplama kaynaklı birikme: aligner ~10x hızlandı (yukarıda).
- eval simülasyonunun chunk izleri iki algoritmik kök neden gösterdi:
  **a) `MIN_WORD_COUNT_FIRST_LOCK = 4`:** tertil/yavaş okumada 5 sn'lik chunk'a 3 kelime sığıyor
  (`الشمس والقمر بحسبان`, `إنا أعطيناك الكوثر`, `اهدنا الصراط المستقيم` → skor 100 ama reddediliyordu).
  Rahman oturumunda 4 chunk (skor 100/98/100/81) boşa gitti, kilit 45 sn. → **3'e indirildi**
  (2 denendi: Asr → 12:96, Rahman → 4:25 yanlış kilit — reddedildi).
  **b) Yanlış aday 2 chunk boyunca doğru yeri aratmıyordu:** BEKLEME'de aday varken arama adayın
  ±4 ayet penceresiyle sınırlı (`compute_preferred_range`); ortak ifadeden gelen yanlış aday
  (`إن شاء الله` → 12:99, `قل أعوذ برب` → 113:1) bayatlayana kadar kilit imkânsızdı. → Aday
  penceresinde eşik tutmazsa aynı chunk **tüm Kuran'da da aranır**, başka yerde ≥eşik varsa aday değişir.
- Sonuç (27 kayıt, RNNT transkriptleri, eşik 70; 19 etiketli Kuran + 8 negatif):
  doğru ilk kilit 13 → **17**, yanlış kilit 0 → **0**, kilit yok 6 → 2, doğru kilit medyanı 15 → **10 sn**.
  Negatifler (ilahi `session_1777027721`, Arapça sohbet, Türkçe, sessizlik) kilitlenmiyor.
  Önceki chunk metnini bağlam olarak eklemek denendi → 1 yanlış kilit (Asr → 12:99), alınmadı.
- Python referansı (`build_state_machine_fixture.py`, `server/app.py`) + Kotlin birebir: JVM'de
  Kotlin StateMachine eval transkriptlerinde Python ile 27/27 aynı iz.
- Kalan: `session_1777005126/6567` (2 chunk okuyup susmuş) kilit yok — beklenen.
- CI eval (gerçek korpus) teyidi: RNNT 17 doğru / 0 yanlış / 2 kilitsiz, medyan 10 sn. CTC zincirinde
  1 yanlış kilit (asr.wav → 10:89) — varsayılan decoder RNNT kalmalı.

### 5. Sure geçişi (Fatiha → zamm, sure → sure) — düzeltildi (APK build #9+)
- Telefon testi (APK #8, `data/telefon_rahman_maun_kevser_felak.wav`): 107 doğru takip edildi ama
  **Kevser (108) hiç bulunamadı** — kilitliyken arama mevcut surenin penceresiyle sınırlı (HARD),
  pencere sure sonunda bitiyor; ancak `ABANDON_LOCK_AFTER_LOST` (6 chunk, ~30 sn) sonra global arandı.
- Sentetik namaz (`data/sentetik_namaz_fatiha_*.wav`) daha kötüsünü gösterdi: **Fatiha penceresi
  yapışkan** — zamm suresinin besmelesi Fatiha 1:1'e (79), "الله أحد الله الصمد" 1:2'ye (55) "eşleşiyor"
  (kilitliyken eşik 50), lost sayacı sıfırlanıyor, zamm rükûya kadar bulunamayabiliyordu.
- Çözüm (Python ref + app.py + Kotlin birebir):
  - Kilitliyken pencere skoru `JUMP_SEARCH_BELOW` (80) altındaysa tüm Kuran'da da ara; bulunan yer
    ≥ ilk kilit eşiği, pencereden ≥ `JUMP_MARGIN` (15) iyi ve besmele dışı ≥2 kelime içermeli.
  - **Doğal geçiş → hemen:** Fatiha'da en ileri ayet ≥6 iken başka yer (zamm her yerden başlayabilir);
    sure sonu (son 2 ayet) → bir surenin 1-2. ayeti. Değilse **aday** (UI "ADAY"), sonraki chunk
    ±4 ayet içinde doğrularsa geçilir.
  - `max_ayah`: kilitli suredeki en ileri ayet — geriye çöp eşleşmeler doğal geçiş kararını bozmasın.
  - Besmele içerik şartı: korpusta her 1. ayet besmeleyle başlıyor; "...بسم الله الرحمن الرحيم" parçası
    sure sonundan rastgele surenin başına (68:1) atlıyordu.
  - **İstiaze filtresi** (`strip_istiaze`): "الشيطان" içeren ≥3 kelimelik istiaze parçası çıkarılır
    (16:98'e "ADAY" sıçraması bitti).
- Sonuç (takip simülasyonu, 30 kayıt, 27 sure bölümü): Kevser kaçtı → 9 sn (ilk parçada), Fatiha →
  İhlas kaçtı → 5 sn, Fatiha → Ayetel Kürsi kaçtı → 5 sn (önce 2:163, sonra 2:255), yanlış kilitli
  chunk 0. Eşik taraması (70-101 / 10-20) geniş güvenli bölge; "her zaman ara + 10 fark" 1 yanlış.
- JVM: Kotlin = Python tüm kayıtlarda aynı kararlar (3 kayıtta bilinen aligner ayet sınırı ±1);
  state machine fixture 21/25 → 24/25 (Fatiha + İhlas geçiş senaryosu artık birebir).
- **Fatiha hızlı kilit** (build #10+): namazda sesli okunan ilk şey Fatiha → BEKLEME'de Fatiha başına
  (1:1-3) skor ≥90 ve ≥4 kelime doğrulama beklemeden kilit. Fatiha ile başlayan kayıtlarda ilk kilit
  10 → 5 sn, yanlış 0. 3 kelimeye inince ilahi ("يا رب العالمين") yanlış kilitliyor — 4 şart.

### 6. Takip hızı: duraklamada kes + sonraki ayete ön-kaydırma (APK build #11+, hibrit #14+)
- Kullanıcı önerisi: imam ayeti bitirip beklerken ekran sonraki ayete kaysın, okununca kelimeler
  vurgulansın; imam geçmezse sonraki sonuç doğru ayete geri getirsin.
- **Duraklamada kesen parçalayıcı** (`scripts/vad_chunker.py` ↔ `AudioPipeline.kt ChunkBuilder`,
  JVM'de 30/30 kayıtta parça sınırları birebir): 100 ms çerçeve RMS, uyarlamalı eşik (son 5 sn p20/p90,
  eşik = gürültü + 0.3·(konuşma − gürültü)); parçada ≥1.5 sn yeni ses + ≥1 sn konuşma varken 0.5 sn
  sessizlik → kes (bindirme yok); duraklama gelmezse 5 sn'de kes (1 sn bindirme, eski davranış).
  Düşük SNR'de (konuşma < 2·gürültü + 0.002) duraklama algılanmaz → sabit 5 sn. MIN 2.5 sn denendi:
  zorunlu kesimden hemen sonraki duraklamalar kaçıyordu (parçalar 5 sn ızgarasında kalıyordu).
  ASR'siz ölçüm (30 kayıt, ~1 sn işlem dahil): kelime → ekran ort. 3.4 → 3.0 sn, ayet sonu
  duraklaması → ekran medyan 3.4 → 2.1 sn.
- **CI eval (gerçek RNNT, APK #11-13, her yerde duraklama kesimi) — DOĞRULUK GERİLEDİ:** ilk kilit
  17/0/2 → 14/**2**/3 (Nas → 113:2, ilahi → 2:258 Kuran değil, session_1777005364 → 14:31), takipte
  yanlış kilitli chunk 0 → **7**, asr.wav hiç kilitlenmedi (hep too_short). Kazanç küçüktü: son kelime →
  ekran 1.8 → 1.7 sn, ayet sonu → sonraki ayet 2.3 → 2.0 sn. Kök neden: 1-3 kelimelik duraklama
  parçaları BEKLEME'de belirsiz aday üretiyor, sonraki kısa parça onu "doğruluyor"
  (Nas: `0:P113:1(100) 1:S 2:S 3:M113:2(80)`, ilahi: `3:P2:260(78) 4:L 5:M2:258(78)`). 7 yanlışın
  **hepsi BEKLEME'de**; kilitliyken kısa parça hiç yanlış kilit üretmedi (pencere belirsizliği çözer).
  Parça başına en az konuşmayı 2-3 sn'ye çıkarmak kazancı tamamen siliyor (ayet sonu → ekran 2.1 → 3.5 sn).
- **Hibrit (APK #14+):** `ChunkBuilder.pauseCutEnabled` sadece kilitliyken (FATIHA/ZAMM) true —
  BEKLEME/ARA'da sabit 5 sn (APK #10 davranışı, ilk kilit 17/0). Chunk consumer anahtarı her parçanın
  state machine sonucundan sonra günceller; 1.5 sn'den önce kesim olmadığı için işleme 1.5 sn'den kısa
  sürdükçe sınırlar eval'dekiyle aynı. JVM: Kotlin = Python parça sınırları (30 kayıt, açık/kapalı
  değişen anahtarla da birebir). Eval `rnnt-hibrit` zinciri state machine'i ASR ile aynı döngüde
  çalıştırır (`HybridChunker.feed`).
- **CI eval teyidi (hibrit, 30 kayıt, gerçek RNNT):** doğruluk sabit parçayla **aynı** — ilk kilit
  17/0/2 (medyan 10 sn), takipte 27 bölümün 24'ü kilitli, **yanlış kilitli chunk 0**. Hız kazancı
  korundu: son kelime → ekran 1.8/2.1 → **1.7/1.9 sn** (medyan/ort), parçaların %29'u duraklamada
  kesildi, ön-kaydırma 56 → **76** (isabet 48/52 → 62/68, %91), ayet sonu → sonraki ayet medyan
  2.3 → **2.1 sn**. Sure geçişleri: Fatiha → İhlas 15 → 11 sn, Fatiha → Ayetel Kürsi 5 → 6 sn,
  107 → Kevser 9 → 12 sn (tek kayıt; kısa parça geçişte bir chunk geç doğrulanıyor).
- **Ön-kaydırma — APK #25'te KALDIRILDI** (kullanıcı: "önceki ayet okunmadan sonrakine geçiyor"; ekran artık hep
  okunan ayette, sonraki ayet okununca kilitlenir; eval'deki ön-kaydırma sütunları sadece tanı). Eski hâli
  (`MainViewModel.handleChunkResult`, UI katmanı — state machine değişmedi): kilitli
  (FATIHA/ZAMM) eşleşmenin son kelimesi ayetin son kelimesiyse ekran aynı suredeki sonraki ayete geçer
  (`UiState.advanced`); parça duraklamada kesildiyse ve ayet ≥3 kelimeyse sondan bir önceki kelime de
  yeter (son kelime uzatılıp tanınmayabiliyor). Sabit parçalı eski transkriptlerde bile 54 geçişin
  50'si isabetli (sonraki eşleşme o ayette), 4'ünde geri döndü.
- `PipelineResult` (sonuç + parça bitiş zamanı + duraklama kesimi); log satırında `parca=dur 3.2s`
  / `5sn 6.0s` ve `gecikme=Xms` (parça bitişinden sonuca, kuyruk dahil).
- `server/app.py` hâlâ sabit 5 sn parça kullanıyor (state machine referansı değişmedi).

### 7. Gerçek namaz kaydı — zikir filtresi + doğrulamalı yeniden kilit (APK build #15+)
- `data/namaz_aksam_fatiha_zilzal_fatiha_kafirun.wav` (27.09 akşam, camide cemaat arasından telefon,
  6 dk 19 sn, 48 kHz AAC → 16 kHz): tekbir → Fatiha (18 sn) → Zilzal (56) → rükû/secde (101) → Fatiha (138)
  → Kâfirûn (175) → rükû/secde/tahiyyat, 3. rekât sessiz → selam (~356). TIMELINE RNNT transkriptinden.
- Takip iyiydi (Fatiha 7 sn, Zilzal 5-9 sn, 2. Fatiha 7-11 sn, Kâfirûn 5-6 sn, ön-kaydırma 12-13/13) ama
  **namazın kendisi yanlış kilit üretiyordu:**
  - Selam "السلام عليكم ورحمة الله" → **6:54** (84), "سمع الله لمن حمده" (ASR: "سمع الله حمدا") → **3:181** (74).
    Kök neden: ARA'da (12+ kayıp chunk — rükû/secde, sessiz rekât) `compute_preferred_range` None → tüm
    Kuran'da **50 skorla tek chunk doğrulamasız kilit**.
  - ASR sessizlik/tekbirde eğitim verisindeki video girişlerini uyduruyor: "شركة الهدى للخدمات التقنية" (7 kez),
    "موسوعة النابلسي للإعجاب", "لا تنسوا مشاركة العمل" → bir kez 53:24 "ADAY".
- Çözüm (Python ref + app.py + Kotlin birebir):
  - **Namaz zikir filtresi** (`strip_namaz_phrases`): selam ("السلام عليكم/عليك" + ورحمة الله…), semiallah
    ("سمع الله (لمن) حمد…"), "ربنا (و)لك الحمد" çıkarılır; "الله اكبر" sadece parça tamamen tekbirse. Korpusla
    doğrulandı: "السلام عليكم/عليك" ve "ربنا لك الحمد" Kuran'da yok, "سمع الله" hep "قول" ile devam ediyor,
    "الله أكبر" 3 ayette var (9:72, 29:45, 40:10 — bu yüzden tek başına değilse dokunulmaz).
  - **ASR uydurma filtresi** (`is_asr_hallucination`): Kuran vocab'ında olmayan video girişi kelimeleri
    (شركه، للخدمات، التقنيه، موسوعه، النابلسي، مشاركه…) içeren parça boş sayılır (kayıp chunk).
  - **Doğrulamalı yeniden kilit:** kilit kaybolunca (`lock_abandoned` ya da ARA) eşik/kelime ilk kilit gibi
    ve **aday doğrulaması** (2 tutarlı chunk). İstisnalar: rekât başı Fatiha (herhangi bir ayet, skor ≥90,
    ≥3 kelime) ve kalınan yerden devam (aynı sure, son ayetin −2..+3). Aday bayatlaması artık her durumda.
  - `transition_state`: Fatiha'nın herhangi bir ayeti → FATIHA (eskiden 1:1-3; 2. rekât Fatiha'sı 1:4'ten
    yakalanınca ZAMM kalıyordu, Fatiha → zamm geçişi "aday"a düşüyordu).
- Sonuç (TRJSON replay, 30 kayıt + namaz, rnnt + rnnt-hibrit): namazda yanlış kilitli chunk 2/1 → **0**,
  rükû/secde boyunca aday/kilit yok; diğer 30 kayıtta ilk kilit (17/0/2), takip (28/31) ve ön-kaydırma
  **birebir aynı**. State machine fixture'a 5. senaryo (gerçek namaz akışı, 30 chunk) eklendi.
- **CI eval teyidi (31 kayıt, gerçek RNNT):** namaz kaydında her iki zincir **0 yanlış kilitli chunk**
  (rnnt: Fatiha 7 / Zilzal 9 / Fatiha 7 / Kâfirûn 5 sn; hibrit: 7 / 5 / 11 / 6 sn — hibritte 2. Fatiha
  "الرحمن الرحيم" 2 kelimelik parçayla başlıyor, bir parça geç). Genel: ilk kilit 17/0/2 (medyan 10 sn),
  takip 31 bölümün 28'i, yanlış kilitli chunk 0; hibrit ön-kaydırma 89 (isabet 74/80, %93), son kelime →
  ekran 1.7/2.0 sn, ayet sonu → sonraki ayet 2.1 sn. (CTC zinciri namazda 1 yanlış — varsayılan RNNT kalmalı.)
- `eval.yml` elle çalıştırmada `audio` girdisi: sadece verilen kayıtlar (yeni kaydın transkripti ~4 dk).

### 8. Telefon testi (APK #15): Fatiha'da geri zıplama + geçiş adayı gösterimi (APK build #16+)
- `data/telefon_fatiha_maun_kureys.wav` (132 sn): Fatiha → Mâûn (107) → Kureyş (106). Kullanıcı: "bazen
  yanlış kilitlendi gibi". Log'da tüm kilitler doğru surede; yanlış görünen iki şey:
  - **Fatiha'da geri zıplama:** "الرحمن الرحيم" hem 1:1'de (besmele) hem 1:3'te; FATIHA penceresi tüm
    Fatiha (0-30) olduğu için aligner ilkini (1:1) seçiyordu → 1:2'den sonra ekran bir ayet geri. İmam
    "رب العالمين"den sonra durunca (duraklama kesimi) **her Fatiha'da** oluyor (namaz kaydında da vardı).
    Çözüm: FATIHA penceresi son eşleşmenin `FATIHA_BACK_WORDS` (3) kelime gerisinden başlar ve Fatiha'nın
    son kelimesinde (1:7) biter — `FATIHA_WORD_RANGE` (0-30) Bakara 2:1-2'yi de kapsıyordu; daralan pencerede
    çöp eşleşme 2:1'e kilitlendi (fixture senaryo 4), pencere sonu düzeltilince fixture **55/55** (bilinen
    aligner sınır farkı da kalktı).
  - **Geçiş adayı ekranı kaydırıyordu:** kilitliyken bozuk parça ("شعور وما لا") → tüm Kuran'da 22:12
    (sure geçişi adayı) → UI "ADAY" ile oraya kaydırıyordu; doğrulanmasa da kullanıcı yanlış kilit görüyor.
    Çözüm: `ChunkResult.jumpCandidate` → MainViewModel geçiş adayında ekranı **kaydırmaz** (sadece durum
    satırı); gerçek geçiş sonraki parçada doğrulanınca kayar. BEKLEME ve kilit kaybı adayları gösterilir.
    eval "aday medyan" ölçümü de artık geçiş adaylarını saymıyor.
- Telefon log'unun parçaları (rms + metin) Python referansından geçince telefonun kararları birebir
  çıktı (referans = telefon); yeni pencereyle 2. parça 1:1 → **1:3**.
- Kalan: Kureyş başı "لإيلاف قريش" / "قريش إيلافهم" 2'şer kelime → sure atlaması ≥3 kelime istiyor,
  geçiş ~9 sn gecikti (106:2'de doğal geçiş). 2 kelimeyle atlama yanlış geçiş riski — bilerek bırakıldı.
- **CI eval teyidi (32 kayıt, APK #16):** ilk kilit 17/0/2 (medyan 10 sn), takip 34 bölümün 31'i,
  **yanlış kilitli chunk 0** (rnnt + hibrit); hibrit ön-kaydırma 99, isabet **88/95** (%93), son kelime →
  ekran 1.8/2.0 sn, ayet sonu → sonraki ayet 2.1 sn. Telefon kaydı (hibrit): Fatiha 10 / Mâûn 10 /
  Kureyş 13 sn (sabit parçada Kureyş 6 sn — hibritte kısa parçalar 2 kelimeye düşüyor).


### 9. Gerçek namaz #2 (01.10 akşam, APK #19): titreşim, "المصدر", namaz sonu duası, kısa sure geçişi (APK build #20+)
- `data/namaz_aksam2_fatiha_rad_fatiha_ibrahim.wav` (8 dk 5 sn, camide, telefon): tekbir → Fatiha (11 sn) → Ra'd
  13:38-43 (54-151) → rükû/secde → Fatiha (199) → İbrahim 14:1-3 (238-295) → 3. rekât sessiz → selam (446) →
  "اللهم انت السلام ومنك السلام..." duası. TIMELINE enerji zarfı + telefon log'undan.
- **Çağrı titreşimi** (kullanıcı: "telefon titreşimde çağrı aldı"): 151-163 sn, 4 darbe × 1.5 sn, 200 Hz, 3.5 sn
  periyot, rms ~0.16 (okumanın ~2.5 katı, enerjinin %95'i 60-300 Hz'de). Ra'd biter bitmez rükû tekbirine denk geldi —
  okuma kaybı yok (en fazla 13:43'ün son 2 kelimesi). ASR titreşimde "شركة الهدى..." / "المصدر كتاب" uydurdu.
- Telefon log'u (104 parça) Python referansından geçince kararlar **birebir** aynı. Takip iyi: Fatiha 4-5 sn, Ra'd
  13 sn, 2. Fatiha 5 sn, İbrahim 7 sn, yanlış kilit 0, ön-kaydırma 13/14. Ra'd gecikmesi: 13:38 başındaki 5 sn'lik
  parçada (57-62 sn) RNNT **ve CTC** boş döndü; sabit ızgarada (55-60) aynı ses tam tanındı → pencere şansı.
- Sorunlar → düzeltmeler (Python ref + app.py + Kotlin birebir):
  - **"المصدر" ASR uydurması** (tekbir/gürültü/titreşim/ezan: "المصدر كتاب", "المصدر صور من"; namazda 8 kez, CTC'de
    "المصدرة"): ZAMM'da "كتاب" 13:43'e (54) çöp eşleşme veriyordu. "المصدر" Kuran'da yok → kelime çıkarılır.
  - **Namaz sonu duası**: "السلام منك السلام" → 59:23 ADAY, "تباركت يا ذا الجلال والاكرام" → 55:27 ADAY (ekranda).
    Kuran'da "انت السلام", "(و)منك السلام", "تباركت", "ذا الجلال" yok → çıkarılır (dua başı geriye doğru da).
  - **Kısa doğal geçiş**: yavaş okumada sure başı parçaya 2 kelime sığıyor ("لإيلاف قريش", "أعطيناك الكوثر"),
    atlama 3 kelime istediği için hibritte geçiş bir parça gecikiyordu. Doğal geçiş noktasında (Fatiha sonu ≥1:6 /
    sure son 2 ayeti) 2 kelime de atlar: ifade Kuran'da **tek yerde** geçmeli (`phrase_count`, normalize birebir),
    skor ≥ 90, hedef doğal geçiş. "ولقد ارسلنا", "الرحمن الرحيم" gibi çok yerde geçenler 3 kelimeyi bekler.
- **CTC yedeği denendi (tanı), eklenmedi:** eval RNNT zincirlerinde aynı encoder çıktısının CTC metni de yazılıyor;
  RNNT boşken CTC çoğunlukla kırıntı/çöp ("الله و", "ال ال", "المصدرة") → fayda yok.
- Sonuç (TRJSON replay, 33 kayıt): rnnt yanlış kilitli chunk 1 → **0** (namaz #2'de "المصدر كتاب" → 13:43);
  hibrit Kureyş 12.8 → **5.5 sn**, Kevser 12.5 → **7.8 sn**, ön-kaydırma 113 → 115 (isabet 101/108 → 103/110);
  ilk kilit 17/0/2, takip 35/38 ve diğer tüm kayıtlar aynı. JVM: Kotlin = Python 33/33 kayıt; fixture'a senaryo 6
  (Maun → Kureyş 2 kelime, "المصدر", selam + dua) → 6 senaryo × 78 chunk, 78/78.
- Log'daki ilk oturum (18:58, 67 sn) ezan: "المصدر كتاب", "المحمد" — kilit/aday yok.
- **CI eval teyidi (33 kayıt, gerçek korpus, APK #20 kodu):** replay ile aynı — ilk kilit 17/0/2 (medyan 10 sn),
  takip 38 bölümün 35'i, yanlış kilitli chunk rnnt 1 → **0**, hibrit **0**; hibrit Kureyş 13 → 6 sn, Kevser 12 → 8 sn,
  ön-kaydırma 115 (isabet 103/110), son kelime → ekran 1.8/2.0 sn, ayet sonu → sonraki ayet 2.1 sn.

### 10. Cuma namazı (02.10, APK #23): kamet Kuran'a eşleşiyordu → yanlış kilit zinciri (APK build #24+)
- `data/namaz_cuma_kamet_fatiha_enbiya_fatiha_insirah.wav` (camide telefon, 8 dk 50 sn): kamet 6-56 → tekbir ~70 →
  Fatiha 82-115 → Enbiyâ 21:102-104 (117-166) → rükû/secde → Fatiha 215-248 → İnşirah (249-284) → secde/oturuş →
  selam 366-378 → dua. Eval hibrit zinciri telefon log'uyla (120 parça) birebir aynı kararlar.
- Telefonda olan: kamet "الصلاة حي الصلاة" → 4:103 aday, "بل قام بالصلاة" (قد قامت الصلاة) → 4:101 **kilit** (2 tutarlı
  parça). Kilit yanlış yerde olunca zincirleme: Fatiha 4:102 penceresine eşleşti (Fatiha kilidi 14 sn geç), zamm başı
  "لا يسمعون عصيس" (21:102, ASR bozuk) → 7:100 (74.5) **doğal geçiş** sayıldı ve pencere 30 sn yapıştı (21:104'e ancak
  148. sn'de), semiallah sonrası "لمن عمل" → 21:106, 2. rekât Fatiha'sı 21:107'ye. Hibritte 13 yanlış kilitli parça.
- Düzeltmeler (Python ref + app.py + Kotlin birebir):
  - **Kamet/ezan algılama** (`namaz_signal`): Kuran'da HİÇ geçmeyen kelime/ikililer (korpusla doğrulandı): الفلاح, قامت,
    محمدا, اشهد+ان/انه/لا, ان/الله+محمد, قد قام, قام+(ب)الصلاه, حي+على/الصلاه/الفلاح, الصلاه+حي/خير, من النوم. 33 kaydın
    RNNT + CTC transkriptlerinde **0** yanlış alarm; cuma kametinin 5 parçasını yakaladı. "لا اله الا الله", "محمد رسول الله",
    "حي" (21:30) Kuran'da var → işaret değil. Kamet parçası boş sayılır, kilit/adaylar silinir (BEKLEME) ve
    **12 parça "sadece Fatiha" beklemesi** (`hold_until`): hizalama Fatiha'ya yapılır, ≥90 + 3 kelime → hemen FATIHA
    (herhangi ayet), 70-90 → aday (doğrulamalı); tüm Kuran aranmaz.
  - **Semiallah** → ARA + 24 parça bekleme (sadece Fatiha ya da kalınan yerden devam, pencere skoru ≥80).
    **Selam** (kilit yokken) → sıfırla + 24 parça bekleme (dua cümleleri kilitlemesin).
  - Tek başına **tekbir sinyal değil**, sadece atılır ("الله اغبر" de tekbir sayılır): zorlama testinde okuma ortasına sahte
    tekbir konunca ARA'ya geçmek / beklemek yeni sureyi kilitletmiyordu; gerçek kayıtlarda semiallah aynı işi güvenilir yapıyor.
  - **Doğal geçiş ≥ 77** (`NATURAL_MIN_SCORE`), altı sadece (görünmez) geçiş adayı: eval'deki 28 doğal geçişin hepsi doğru,
    en düşüğü 79.3 (Kevser sonu → "قل أعوذ برب الفحص"); cuma yanlışı 74.5. (21:102'ye sure ortası doğru geçiş 82 → sure
    ortası için ayrıca sıkılaştırılmadı.)
  - **Fatiha yoklaması** (ZAMM'da pencere <80 ve ≥4 kelime, ARA'da ≥3 kelime): Fatiha'ya ayrıca hizala; ≥90 ve pencereden
    ≥15 iyi (ARA'da eşitlik yeter, kalınan yerin penceresi hariç) → hemen FATIHA. Tüm Kuran araması "الحمد لله رب العالمين"i
    6:45/10:10/37:182'ye de oturtabiliyor. ZAMM'da 4 kelime şartı: "وإلى رب العالمين" (94:8 bozuk) Fatiha'ya 92.6 alıyor.
    (Gerçek veride hiç tetiklenmedi — kamet/semiallah kaçarsa güvenlik ağı.)
  - ARA'da 2 parçayla **doğrulanmış sure geçişi** yeniden kilit sayılır (eskiden üstüne bir aday doğrulaması daha bekliyordu).
  - UI: kamet → durum satırı "kamet: Fatiha bekleniyor", önceki kilidin vurgusu silinir (`ChunkResult.kamet`).
- Fixture artık telefon varsayılanlarıyla üretiliyor (ilk kilit 70, pencere ±2; eskiden 90 / ±5 — senaryolar farka duyarsız
  olduğu için fark edilmemişti). Senaryo 7: cuma akışı (kamet → Fatiha → Enbiyâ (7:100 adayı) → semiallah → Fatiha →
  İnşirah + okuma ortasında tekbir → semiallah beklemesinde 16:97 benzeri cümle → selam) → 7 senaryo × 123 chunk, 123/123.
- Sonuç (TRJSON replay, 34 kayıt): cuma yanlış kilitli parça rnnt 5 → **0**, hibrit 13 → **0**, ekranda yanlış aday 3 → 0;
  hibrit Fatiha 13.6 → **3.3 sn**, Enbiyâ 30.9 → **16.6 sn** (yanlış 7:100 yok), 2. Fatiha 9.9 → **4.9 sn**; sabit parçada
  Fatiha 8 → 3 sn. Diğer 33 kayıt birebir aynı (ilk kilit 17/0/2, takip 39/42).
- **Zorlama testleri** (gerçek transkriptlerden bileşik/bozulmuş kayıtlar, ESKI → YENI, rnnt / hibrit):
  - kamet + Fatiha ile başlayan kayıtlar (18 bölüm): yanlış kilitli 40/36 → **0/0**, yanlış aday 24 → 0, kilit medyanı 9.5 → 6 sn
  - hutbe (önce Rahman kilidi) + kamet + namaz: yanlış 3/14 → **0/0**
  - parçaların %15'i gürültü (uydurma / rastgele Kuran kelimeleri / boş), 5 tohum: yanlış 40/86 → 4/22 (cuma dahil),
    yanlış aday 75/86 → 52/59, takip aynı; vaka bazında hiçbir kayıt kötüleşmedi
  - okuma ortasına 2 sahte tekbir: takip aynı (193/210), yanlış 33/68 → 8/3
  - bedel: kametten hemen sonra Fatiha'sız bir sure okunursa (namazda olmaz) ilk kilit ~1 dk bekler.
- JVM: Kotlin = Python 34/34 kayıt (rnnt + hibrit); app.py = referans (Flask taklitli düzenek) 68 kayıt-zincir / 1329 parça.
- eval takip tablosuna **"ekranda yanlış aday"** sütunu eklendi (BEKLEME / kilit kaybı adayları; geçiş adayları görünmez).
- **CI eval teyidi (34 kayıt, gerçek RNNT, APK #24 kodu):** replay ile birebir — ilk kilit 17/0/2 (medyan 10 sn), takip
  42 bölümün 39'u (cuma'nın 4 bölümü dahil, kaçan 3 bölüm eskiden de kaçıyordu), **yanlış kilitli chunk rnnt 0 / hibrit 0**,
  ekranda yanlış aday 7 (hepsi namaz dışı kayıtlarda BEKLEME belirsizliği: ilahi 4, nas3 113:1, asr.wav 12:99, 16:4).
  Cuma: rnnt Fatiha 3 / Enbiyâ 8 / Fatiha 5 / İnşirah 6 sn; hibrit 3 / 17 / 4 / 3 sn, ikisinde de 0 yanlış. Hibrit
  son kelime → ekran 1.7/2.0 sn, duraklama kesimi %37, ön-kaydırma 129 (isabet 116/123), ayet sonu → sonraki ayet 1.9 sn.

### 11. Cuma #2 (09.10, APK #27): kamet "Nisa" adayı + zamm başı geç kilit (APK build #28+)
- `data/namaz_cuma2_kamet_fatiha_tekasur_fatiha_asr.wav` (camide telefon, 8 dk 18 sn): kamet 0-35 → iftitah 48.4 → Fatiha
  60.3-88 (1:1 sessiz) → Tekâsür 102 (96.1 "الهاكم", 99.2 102:2, 103.2 102:3 … 138) → rükû 141.4 → Fatiha 189.5-216 → Asr 103
  (223.8 "والعصر", 226.1 103:2, 231.4 103:3 … 242.6) → rükû 245.4 → secde/oturuş → selam 335.2. Zamanlar CI kelime zamanlı
  transkriptinden (`--words`) + enerji zarfı; telefon log'u 107 parça (eval hibrit = telefon kararları).
- Kullanıcı: "kamet yerine Nisa suresini algıladı sonra tekrar kameti buldu", "her iki rekâtta Fatiha'dan sonraki sureye geç
  kilitlendi, 2. veya 3. ayette; surenin başını kaçırdım". Log'da (ekrana göre):
  - 10 sn: "خير الصلاة على الصلاة" (hayye ale's-salâh) hiçbir kamet kalıbına uymadı → **4:142 ADAY** 11-21 sn ekranda; kamet
    ancak 20 sn'de "قد قام بالصلاة" ile.
  - Tekâsür: 99.2 sn'de "ألهاكم التجاد" (102:1) reddedildi → ilk görünen **102:2**, 103.1 sn (imam 96.1'de başladı: 7 sn,
    102:1 hiç görünmedi). Asr: 229 sn'de "والعص إن الإنسان لعام" reddedildi → ilk **103:3**, 235.2 sn (imam 223.7: 11.5 sn).
  - Kök neden: tüm Kuran araması doğru yeri buluyordu (hizalama 85.4 / 91.9) ama `score_transcription` Kuran sözlüğünde
    olmayan bozuk kelimeler ("التجاد", "والعص", "لعام") için √kapsam cezası kesiyor (60 / 65) → geçiş eşikleri (70, doğal 77)
    tutmadı; 2 kelimelik parça ayrıca "tek yerde geçen ifade + ≥90" istiyordu.
- Düzeltmeler (Python ref + app.py + Kotlin birebir):
  - **Sure başı geçişi** (`OPENING_MIN_FUZZY` 75): geçiş noktasında (Fatiha sonu / sure son 2 ayeti) hizalama bir surenin
    açılışından başlıyorsa (1. ayetin besmele dışı ilk 2 kelimesi ya da besmele) ham hizalama skoru yeter → doğal geçiş
    (2 kelimelik parça dahil). Aday kümesi 114 sure açılışı — ceza olmadan da seçici. Eşik taraması 65-85: hepsi aynı
    sonuç; zorlama testlerinde (5 senaryo × 2 zincir, %15 gürültü dahil) yanlış kilit / aday artmadı.
  - **Kamet ikilileri**: "على الصلاة", "خير الصلاة", "مضت الصلاة" (Kuran'da yok; 34 kaydın 2405 transkriptinde 0). EzanTracker
    de tanır (hayye ale's-salâh / kad kâmeti's-salâh) → pencere 10 sn'de açılıp 35 sn'de son tevhidle kapanır.
  - **UI:** geç kalan sure başı için atlanan ilk ayetler sırayla gösterilir (bkz. Mushaf "Sure başı").
- Sonuç (telefon parçaları replay, ekran zaman çizelgesi, ara ayet 1 sn): Nisa adayı yok; Tekâsür **102:1** 100.2 sn'de
  (imam başladıktan 4.1 sn, ayet bittikten 1.5 sn sonra), Asr **103:1** 229.9 → 103:2 230.9 → 103:3 235.2 sn (6.2 sn; "والعصر"
  223.7-224.6 sabit parça sınırına (224.0) denk geldi, tek kelimesi tek başına kilitleyemez). Diğer 34 kayıt: geçen cuma
  rnnt İnşirah 6 → 1 sn, başka fark yok (ilk kilit 17/0/2, takip 39/42, yanlış kilitli 0).
- **CI eval teyidi (35 kayıt, gerçek RNNT, APK #28 kodu):** cuma #2 hibrit Fatiha 6 / **Tekâsür 3** / Fatiha 5 / **Asr 6 sn**,
  yanlış kilitli 0, ekranda yanlış aday 0 (sabit parça: 6 / 4 / 6 / 7 sn); genel ilk kilit 17/0/2 (medyan 10 sn), takip 46
  bölümün 43'ü, yanlış kilitli rnnt 0 / hibrit 0, son kelime → ekran 1.7/2.1 sn. Sabit parçada 1 yeni yanlış aday: ikinci
  selam parça sınırında bölündü ("السلام" | "عليكم ورحمة الله") → hold'da Fatiha 1:1'e 76 → **bölünmüş selam filtresi**
  (`strip_namaz_phrases`: "عليكم/عليك + (و)رحمه" baştaysa, Kuran'da yok; 35 kaydın transkriptlerinde sadece selamda) →
  yanlış aday 8 → 7 (kalanlar eskiden beri namaz dışı BEKLEME belirsizliği). JVM: Kotlin = Python 70 kayıt-zincir,
  app.py = referans 1531 parça; fixture senaryo 8 → 8 senaryo × 173 chunk, 173/173.

### 12. taraweeh-companion-g2'den fikirler: fark payıyla kilit, gerekçeli log, rekât sayacı (APK build #32+)
- Kullanıcı Even Realities G2 için yazılmış `wasimlhr/taraweeh-companion-g2` projesini kıyaslattı; **lisansı yok** ("kişisel ve
  eğitim amaçlı") → kodu alınmadı, sadece fikirler bizim verimizle ölçülüp yeniden yazıldı.
- **Fark payıyla tek parçada kilit** (onların "yüksek fark payı" kilidi): en iyi eşleşmenin aralığına değmeyen en iyi ikinci yer
  (`align_transcription(exclude_range=...)` / Kotlin `Aligner.align(excludeRange=...)` — o aralıkla kesişen pencere ve başlangıç
  atlanır) ölçülür. BEKLEME'de (Fatiha hızlı kilidi / bekleme dışı) skor ≥ 90, ≥ 3 kelime ve ikinciden ≥ 12 fark → aday
  doğrulaması beklemeden kilit. Kilitliyken tüm Kuran araması da (sure geçişi) aynı şartla doğrulanmış sayılır.
  Veri (35 kayıt, BEKLEME adayları): yanlışların farkı 0-1.6 (nas3 "قل أعوذ برب" 113:1/114:1 0, ilahi "يا رب العالمين"
  1:2/5:28 0, asr.wav 12:99/2:70 1.6); doğrularınki 0-33 (Ayetel Kürsi 2:255/3:2 aynı cümle → 0, İhlas 6.8, Felak/Nas 8.6,
  ≥ 12 sadece doğrularda: 13-33). Fark 15 de denendi (zorlama 218/230) — 12 seçildi.
  - Sonuç (TRJSON replay, 35 kayıt, rnnt / hibrit): ilk kilit 17/0/2 → **19/0/0** (medyan 10 sn), takip 43/46 → **46/46**,
    takip gecikmesi medyanı rnnt 8.0 → **7.0**, hibrit 9.7 → **7.6 sn**, yanlış kilitli 0 / 0, ekranda yanlış aday 7 → 6.
    Telefon kaydı Rahman → Mâûn geçişi 12 → 7 sn (`gecis fark payi ile`). Zorlama (S1-S5): kilitli bölüm 213 → 228/230,
    yanlış kilit 3 (aynı), yanlış aday 10 (aynı; gürültü testinde 2 yer değişti — eski kod gürültüde 14:16'ya kaymıştı).
  - Python ref + app.py + Kotlin birebir (Kotlin = Python 35/35 kayıt iki zincirde, app.py fark 0 / 1531 parça); fixture
    173/173 (5 chunk'ın beklenen sonucu değişti: Fatiha → İhlas 112:3 ve iki senaryoda ilk parçada kilit).
  - **CI eval teyidi (35 kayıt, gerçek RNNT, APK #32 kodu):** replay ile birebir — ilk kilit rnnt / hibrit **19/0/0** (medyan
    10 sn; asr.wav 30 sn'de, session_1777009737 20 sn), takip **46/46** (kilit medyanı 7 / 8 sn), yanlış kilitli chunk 0 / 0,
    ekranda yanlış aday 6; hibrit son kelime → ekran 1.7/2.1 sn, ön-kaydırma 148 (isabet 130/139). Rahman → Mâûn 7 sn (eskiden 12).
- **Gerekçeli log** (onların "neden" satırları): `ChunkResult.reason` her parçada kabul/red nedenini + bağlamı yazar, log'da
  `[chunk N] ... | 107:1 [kilitli takip; pencere 55:2-55:5; gecis aramasi: 107:1 100.0 (pencere 47.9); gecis fark payi ile;
  gecis dogrulandi]`. Örnekler (gerçek kayıtlardan): `tek parcada kilit (ikinci yer 20:5 83.5, fark 16.5 >= 12.0); tum Kuran`,
  `aday 12:99 (skor 91.9), dogrulama bekleniyor; tum Kuran; ikinci yer 2:70 90.3, fark 1.6 < 12.0`,
  `skor 63.5 @ 1:1 < ilk kilit esigi 70; bekleme (parca 15'e kadar): sadece Fatiha / kalinan yer`, `1 kelime (min 2)`,
  `ASR bos`, `ASR uydurmasi (Kuran disi)`, `0 kelime (min 3); selam: namaz bitti, 24 parca sadece Fatiha; namaz zikri
  cikarildi (4 kelime)`, `Fatiha hizli kilit`, `yeniden kilit: rekat basi Fatiha`, `aday dogrulandi (114:1 → 114:1)`.
- **Rekât sayacı + kaba duruş** (`session/RakatTracker.kt`, UI): durum satırının başında altın/vurgu renkte
  `2. REKÂT · KIYAM` / `· RÜKÛ / SECDE` / `2. REKÂT SONRASI · SESSİZ` / `SELAM` (oturumda ≥2 namaz bitince `TOPLAM N`).
  Gerçek cami kayıtlarında tekbirler ASR'de neredeyse hiç yok (akşam 0, akşam #2'de 1) → tekbir saymak yerine güvenilir
  sinyaller: sesli rekâtın Fatiha'sına giriş (ya da Fatiha içinde başa dönüş) = yeni rekât (aynı rekâtta 25 sn içinde tekrar
  sayılmaz), selam = namaz bitti, semiallah = rükû; okuma bittikten 40 sn sonra gelen semiallah = **sessiz rekât** (3./4.).
  Okuma 25 sn susunca RÜKÛ / SECDE, son olaydan 70 sn sonra "N. REKÂT SONRASI · SESSİZ" (oturuş mu sessiz rekât mı
  bilinmiyor — semiallah duyulmazsa sessiz rekâtlar sayılamaz). Kamet → sıfırla; kayıt namaz ortasında başladıysa (Fatiha'sız
  ilk kilit) sayı ilk Fatiha'ya kadar gösterilmez. Log: `[rekat] t=203.6s 2. rekat (Fatiha)`.
  4 gerçek namaz (hibrit): akşam #2 R1 15 sn / R2 204 / rükû-secde 321 / sessiz 367 / selam 452; akşam R1 25 / R2 149 / sessiz 284 /
  selam 364 (sabit parçada 300 sn'de sessiz 3. rekât semiallahtan sayıldı); cuma #2 R1 65 / R2 194 / selam 337; cuma R1 85 /
  R2 219 / selam 369 — hepsi doğru. Klasik 7 tema piksel piksel aynı (etiket sadece dinlerken).
- Denenmeyen: onların mikrofon filtresi (80 Hz yüksek geçiren × 2 + 6 kHz alçak geçiren) — CI'da ayrı eval zinciriyle
  ölçülmeli (gerçek ASR sadece CI'da); tekbir için enerji patlaması dedektörü 4 kayıtla çok kırılgan bulundu.

### 13. taraweeh-companion-g2 derin inceleme: ayırt edici kelime, birikmiş metin, bozuk semiallah (APK build #33+)
- Kullanıcı repoyu kendi hesabına fork'ladı (`mrcan321/taraweeh-companion-g2`; fork lisans vermez, repo hâlâ lisanssız →
  kod alınmadı, fikirler bizim verimizle ölçülüp yeniden yazıldı). Satır satır okunanlar: `audioPipelineV4.js` (3373 satır),
  `anchorStateMachine.js`, `keywordMatcher.js`, `prayerKeywords.js`, `rakatCounter.js`, `whisperClean.js`, sürüm notları,
  bench betikleri. Bulut Whisper (Groq/OpenAI) + kelime torbası (F1 + IDF) + zamanlayıcıyla ekran ilerletme mimarisi.
- Onların vardığı, bizim kararları doğrulayan sonuçlar: v3.4.16 "ekran sadece gerçek okuma doğrulanınca ilerler" (bizde
  ön-kaydırma APK #25'te kalktı); rekât sayacı artık sadece kilitli Fatiha başlarını sayıyor, tekbir/semiallahtan duruş
  çıkarmayı bırakmışlar (`_feedPrayerCue() → false`; bizde de tekbir camide ASR'de neredeyse yok, bkz. açık sorun 12).
- Uygulananlar (Python ref + app.py + Kotlin birebir):
  - **Ayırt edici kelime** (onların "prefix-ambiguity guard"ının tersi; `is_unique_match` / Kotlin `uniqueCheck`): harf
    benzerliği ikinci yeri yaklaştırıyor — "قل أعوذ برب الفلق" 113:1'e 100, 114:1 "...الناس"e 91.4 (fark 8.6 < 12). Fark ≥
    `EXCLUSIVE_LOCK_MARGIN` (5) ve parçada en iyi yerin ayetlerinde birebir geçip ikinci yerin ayetlerinde geçmeyen, besmele
    dışı, ≥ 3 harfli kelime varsa da tek parçada kilit (ilk kilit + sure geçişi). Veri (35 kayıt, BEKLEME adayları, skor ≥ 90):
    yanlışların farkı 0-1.6 ve hiçbirinde ayırt edici kelime yok ("قل أعوذ برب", ilahi "يا رب العالمين", "والعصر إن شاء الله"
    → 12:99); doğrular 6.7-10.6, hepsinde var ("الفلق", "الناس", "اهدنا", "والعصر", "الفيل"). Besmele kelimeleri sayılmaz
    (korpusta her 1. ayet besmeleyle başlıyor; İhlas'ta "بسم الرحمن الرحيم" ayırt edici görünüyordu). Log:
    `tek parcada kilit (ikinci yer 114:1 91.4, fark 8.6, ayirt edici kelime 'الفلق')`.
  - **Aday penceresi yerine tüm Kuran**: BEKLEME'de aday varken pencere eşleşmesi 70-100 arasıysa tüm Kuran'a da bakılır;
    pencere dışındaki yer tek parçada kilit kuralını geçiyorsa o alınır. Belirsiz aday "قل أعوذ برب" (113:1) sonrası
    "قل أعوذ برب الناس" aday penceresinde 113:1'e ~91 alıp adayı YANLIŞ doğruluyordu, kilit Felak'ta kalıyordu (sentetik dizi;
    gerçek kayıtlarda tesadüfen olmamış). Şimdi 114:1.
  - **Birikmiş metin** (onların arama penceresi merdiveni + son 3 metnin birleştirilmesi; `SEARCH_CONCAT_CHUNKS` 2): yavaş
    okumada 5 sn'lik parçaya 1-2 kelime sığıyor ("خلق الإنسان" | "علمه البيان" tek tek too_short → Rahman ilk kilidi 20 sn).
    BEKLEME'de (bekleme yokken) kilit vermeyen son 2 parçanın temiz metni saklanır; yeni parça da kilit vermezse birleşik metin
    tüm Kuran'da hizalanır, sadece tek parçada kilit kuralını geçerse kilit (aday/doğrulama üretmez — aynı ses iki kez kanıt
    sayılmasın). Sessizlik, namaz sinyali, bekleme, kilit birikimi siler; boş ASR silmez; sınırdaki bindirme kelimeleri bir
    kez. Log: `birikmis metinle tek parcada kilit (...); birlesik metin '...'`.
  - **Bozuk semiallah** (onların `TASMEE_RE`'si "سمع"siz hâli de tanıyor): cuma #2'de "يدع الله لمن حمده" (260 sn) ve
    "سمع القول لمن حمد" (156 sn) "سمع الله" kalıbına uymuyordu → rükû sinyali, bekleme ve rekât sayacı kaçıyordu; CTC
    zincirinde 26:227'ye yanlış kilit, durum selama kadar ZAMM. "لمن حمد…" ve "حمده" Kuran'da yok (korpus), 2782 RNNT + CTC
    transkriptinde sadece semiallahta. Önündeki en fazla 2 kısa kelime (≤ 5 harf) de atılır. Rekât sayacı cuma #2'de iki
    rükûyu da görüyor (hibrit 156 / 257 sn).
- Sonuç (TRJSON replay, 35 kayıt, rnnt / hibrit): ilk kilit 19/0/0 (aynı); ilk parçada (5 sn) kilitlenen tek sureli kayıt
  3 → **9** (Nas, Felak, Fil, test_fatiha, Asr ×2 10 → 5 sn), Rahman 20 → 10 sn; takip 46/46, gecikme medyanı 7.0 → **6.0** /
  7.6 → **5.9 sn** (ort 8.6 → 7.8 / 8.9 → 8.0); yanlış kilitli 0, ekranda yanlış aday 6 (aynı). Zorlama (10 tohum): S4 gürültü
  yanlış kilitli 22 → **13** / 40 → **36**, kilitlenen 445 → 452 / 430 → 436 (460 bölüm), medyan 9-10 → 7 sn; S5 sahte tekbir
  yanlış aynı, medyan 7.0 → 6.0 / 7.8 → 5.9; S1-S3 gerileme yok (S3 ort 9.6 → 7.2).
- Kotlin = Python 35/35 (iki zincir), app.py = referans 1531 parça. Fixture: 9-11. senaryolar (Rahman yavaş okuma + bozuk
  semiallah, belirsiz aday → Nas, ilahi + Felak) → 11 senaryo × 187 chunk, 187/187.
- Ölçülüp alınmayanlar: birikmiş metin eşiğini gevşetmek (nas3 "محب الناس" 80, İnşirah "مزهرك" 58-61 — skor ASR bozukluğundan
  düşük, gevşetmek riskli); kilitliyken tek kelimelik parça (35 kayıtta 4 fırsat, 1'i tutarsız); "آمين" Fatiha sonu işareti
  (35 kayıtta 1 kez; cemaatin amini ASR'de çıkmıyor); IDF ağırlıklı kelime puanı (harf tabanlı hizalama + fark payı + ayırt edici
  kelime aynı işi görüyor); kelime kelime tahmini "karaoke" saati ve zamanlayıcıyla ilerleme (tahmin — kullanıcı istemedi).
- **Sonraki adım fikri (CI eval):** onların `fetch-recitation.sh`'ı gibi EveryAyah'tan ayet ayet MP3 indirip birleştir → her ayet
  sınırı kesin bilinen kayıt (manifest). Ayet düzeyinde doğruluk (ekrandaki ayet = okunan ayet, % zaman) ve ayet başına
  gecikme ölçülür — şu an sadece sure düzeyi ve kilit gecikmesi var. Cami akustiği için seviye düşürme + yankı + gürültü.
  → yapıldı: açık sorun 14, `tests/synth`.

### 14. Cuma #3 (16.10, APK #33) + APK öncesi test kapısı + sentetik teravih (APK build #34+)
- `data/namaz_cuma3_kamet_fatiha_felak_fatiha_nas.wav` (camide telefon, 6 dk): salavat/kamet 0-45 → iftitah ~72 → Fatiha 83-110 →
  Felak (118-141) → rükû/secde (semiallah ~154) → Fatiha 193-219 → Nas (~226-249) → semiallah ~263 → oturuş → selam 345-356.
  TIMELINE CI kelime zamanlı transkriptinden. Eski kodla (replay): **kamette "محمد رسول الله" → 48:29 tek parçada kilit** (fark payı;
  kamet kalıpları ASR'de bozuk: "المصدر كتاب", "نور العصا", "شركة الهدى…" — kamet sinyali hiç tetiklenmedi), Fatiha ZAMM'daki Fatiha
  yoklamasıyla yakalandı; 2. rekâtta Nas'ın ilk parçası "قُلْ أَعُوذُ بِرَبِّ" Fatiha sonunda **Felak'a doğal geçiş** (113:1 / 114:1 aynı,
  ilki seçiliyordu). rnnt 1 / hibrit 4 yanlış kilitli parça.
- Düzeltmeler (Python ref + app.py + Kotlin birebir):
  - **Zikir ifadesi** (`DHIKR_PHRASES`, `dhikr_only`): zamm kilitli değilken (BEKLEME / ARA / FATIHA) parça sadece "محمد(ا) رسول الله",
    "لا اله الا الله" ya da "ان شاء الله" (+ en fazla 1 kelime) ise boş sayılır. Kelime-i şehadet BEKLEME'de **kamet** (sıfırla +
    12 parça Fatiha beklemesi + ezan penceresi); bekleme sürerken gelen zikir beklemeyi uzatır (cuma #3: kamet sonrası "لا إله إلا الله"
    44 sn, "إن شاء الله" 58 sn; uzatmasız bekleme 13. parçada bitip "والحمد لله رب العالمين" 6:45 adayı oluyordu, Fatiha 7 sn gecikti).
    Tarama: 36 kaydın RNNT + CTC metinlerinde bu ifadeler (+ ≤ 2 kelime) Kuran okunan anda sadece asr.wav "والعصر إن شاء الله" (ASR
    hatası; teravih bileşiminde Fatiha sonunda 12:99'a doğal geçiş olup 6 parça yanlış kilitti).
  - **İki surenin açılışı aynı** (`OPENING_TIE_MARGIN` 2): doğal geçişte eşleşme bir sure açılışı ve başka suredeki ikinci yer de bir
    sure açılışıysa (ham hizalama farkı < 2) geçiş tahmin edilmez, (görünmez) geçiş adayı olur. Her yakın ikinci yere genellemek
    denendi (97 doğal geçişin 3 yanlışını yakalıyordu) ama aynı metnin iki yerde geçtiği doğru geçişleri bekletti (2:255 / 3:2,
    14:1 / 38:29); hibritte Ayetel Kürsi doğrulanamadı, "لا تدري" 65:1'e kilitlendi → sadece açılış-açılış. Bedel: Kevser → "قل أعوذ برب
    الفحص" (Felak, fark 0.1) 5 → 10 sn.
  - **Geçiş adayı penceresi** (`CANDIDATE_WINDOW_MARGIN` 2): geçiş adayı varken yeni parça adayın ±4 ayetinde tüm Kuran eşleşmesinden
    ≤ 2 kötü (ve ≥ 70) eşleşiyorsa aday doğrulanır. Fatiha → bozuk Asr "الإنسان لفيه السوء" (103:2 adayı) → "الذين آمنوا وعملوا" 2:25'e
    doğal geçiş oluyordu (103:3 aynı skor).
  - **Hatimle teravih** (`CONTINUE_AHEAD` 6 / `CONTINUE_MARGIN` 2, `SessionState.zamm_surah/ayah`): son zamm konumu (selam / kamette
    silinmez) tutulur; Fatiha sonundaki geçiş aramasında devam penceresi (son zamm ayeti .. +6) tüm Kuran'dan ≤ 2 kötü ve ≥ 77 ise devam.
    Bileşik hatimde 2. rekât "رب المشرقين والمغرب" 73:9 (91.5) yerine 55:17 (91.0).
  - Kotlin `Aligner` küçük sonuç önbelleği (`cacheSize` 32; aynı metin + pencere + ayar → aynı sonuç): bir parçada aynı metin birden
    çok kez hizalanabiliyor; JVM test kapısında 500 000.
- Sonuç (TRJSON replay, 36 kayıt, eski → yeni): cuma #3 yanlış kilitli rnnt 1 → **0**, hibrit 4 → **0**, ekranda yanlış aday 2 → 0;
  Fatiha 85 / 86.6 sn (doğru), Felak ve Nas doğru; asr.wav'da 12:99 adayı kalktı. Bileşik teravih 20 rekât: yanlış kilitli 6 → **0**
  (iki zincir), kilitsiz bölüm (asr.wav'lı rekât) → 30 sn'de kilit; hatimli teravih yanlış 2 → 0, Rahman devamı 25 → 15 sn. Diğer
  kayıtlar birebir aynı; tek gecikme Kevser → Felak 5 → 10 sn (telefon_rahman_maun_kevser_felak). Fixture: 12-14. senaryolar (kamet
  şehadeti + uzayan bekleme, 113/114 açılış adayı, hatim devamı) → 14 senaryo × 237 chunk, 237/237.
- Zorlama (5 tohum, eski → yeni, rnnt / hibrit): S4 gürültü yanlış kilitli 18 → **10** / 43 → **19**, ekranda yanlış aday
  49 → 39 / 56 → 51, kilitlenen bölüm aynı; S5 sahte tekbir 9 → **4** / 23 → **3**; S1 / S3 ekranda yanlış aday 3-4 → **0**.
  Bedel: S2 (kametten hemen sonra Fatiha'sız sure — namazda olmaz) kilit medyanı 45 → 55 / 36 → 54 sn (bekleme zikirle uzuyor;
  hibritte 4 → 3 bölüm). Bileşiklerde rekât sayacı 20/20, 2/2, 4/4 (bileşik düzeltmesi: tek sureli kayıtların sondaki sessizliği
  kırpıldı, 1-2 parça okuyup susan kayıtlar alınmadı; 4 rekâtlıda fazladan semiallah vardı).
- **CI eval teyidi (36 kayıt, gerçek RNNT):** replay ile birebir — ilk kilit 19/0/0 (medyan 10 sn), takip 50 bölümün 50'si,
  **yanlış kilitli chunk rnnt 0 / hibrit 0**, ekranda yanlış aday 5 (namaz dışı kayıtlarda BEKLEME belirsizliği). Cuma #3: rnnt Fatiha 3
  / Felak 7 / Fatiha 3 / Nas 4 sn; hibrit 3 / 4 / 3 / 12 sn. Hibrit son kelime → ekran 1.7/2.1 sn, duraklama kesimi %41. Eval
  hizalama önbelleğiyle 23 dk (eskiden 45 dk sınırında iptal).
- **APK öncesi test kapısı** (kullanıcı: "her kod değişikliğinden sonra APK çıkmadan önce çok daha kapsamlı testler") → bkz.
  "Nasıl test edilir / Test kapısı". `android.yml`: `apk` job'u `test`'i bekler. `ChunkBuilder` `AudioPipeline.kt`'den ayrı dosyaya
  alındı (JVM'de derlensin diye, kod aynı).
- **Ses verisi** (kullanıcı: "mümkün oldukça ses datası bulalım, teravih de dahil"):
  - `tests/synth/build_synth.py` + `synth.yml` (CI; `tests/synth/**` değişince ya da elle): EveryAyah ayet ayet MP3 (kâri listesi
    girdi) + gerçek cami kayıtlarımızdan kesilen namaz sesleri (kamet 3, tekbir 17, semiallah 6, selam 11 klip; TRJSON metnine göre) +
    sentetik oda yankısı (RT60 1.0-2.4 sn) + telefon mikrofonu bandı + cami arka plan gürültüsü. Programlar: `namaz2` (kamet + 2 rekât),
    `teravih8` (4 × 2 rekât, Fil → Nas, tesbih araları), `hatim4` (rekâtlar kalınan ayetten devam), `uzun2` (cuma: sure ortasından
    10-16 ayet), `dort4` (3-4. rekât sessiz). Hanefi: besmele sessiz. Manifest: sure zaman çizelgesi + **her ayetin başlangıç/bitişi** +
    beklenen rekât / namaz.
  - Gerçek ASR (eval_pipeline `--manifest`, `--chains rnnt,rnnt-hibrit`, `--trjson-out`) + `tests/synth/score_synth.py`: **ayet
    takibi** (ayet okunurken / bitişinden 4 sn sonrasına kadar ekranda ya da adımlanarak gösterildi mi), ayet gecikmesi, yanlış
    gösterim, bölüm kilidi, Kotlin RakatTracker rekât / namaz sayısı. TRJSON + manifest artifact; `tests/trjson/*.trjson` +
    `*.manifest.json` olarak eklenince test kapısı bu kayıtları da gerçek kayıt gibi ölçer (`env.load_manifests`).
  - Yerelde `--fake` (indirmeden, okuma yerine kayıtlarımızdan parça) ile mekanik test; "ideal ASR" (manifest'teki ayet metinleri)
    ile ayet takibi %84, yanlış gösterim 0.
  - **İlk CI koşusu** (Alafasy + Saood eş-Şureym × namaz2 / teravih8 / hatim4, ~1 saat ses, gerçek RNNT): ayet takibi **%89.4 / %89.7**
    (rnnt / hibrit, 341 ayetin 305 / 306'sı), ayet gecikmesi medyanı 5.5 / 5.1 sn, 56/56 sure bölümü kilitli (medyan 5 sn), yanlış
    kilitli parça 1 / 6. **Rekât sayacı sentetik teravihte kötü** (teravih8 Saood 2/8 rekât · 1/4 namaz): (1) selam klibi bazen ASR'de
    boş; (2) semiallah "سمع الله لنا محمدا" → içindeki "محمدا" kamet kelimesi → **kamet** sayılıp namaz sıfırlandı; (3) bazı tekbir
    klipleri cuma kayıtlarının kamet bölümünden kesilmişti (üretici düzeltildi: kamet bölümünden klip alınmaz).
  - **Semiallah önce** (`namaz_signal`, Python + app.py + Kotlin): Kuran'da "سمع الله" hep "قول" ile devam ediyor (3:181, 58:1) →
    "سمع الله" + "قول" dışı kelime = rükû, kametten önce bakılır (parça sonundaki "سمع الله" sinyal değil). Gerçek akşam kaydındaki
    "سمع الله من حمداً" de artık rükû (eskiden hiçbir kalıba uymuyordu). Fixture senaryo 15 → 15 × 249.
  - **İkinci CI koşusu** (düzeltilmiş üretici + semiallah kuralı, aynı program): ayet takibi rnnt **%89.6** / hibrit **%93.5**
    (337 ayet), ayet gecikmesi medyanı 5.5 / 5.0 sn, 56/56 bölüm kilitli (medyan 5 / 4 sn), yanlış kilitli parça 2 / 7 (5'i hibrit
    hatim Alafasy). **Rekât sayacı teravihte 8/8** (önce 2/8); namaz sayısı 2-3/4 — selam klibi bazı yerlerde ASR'de boş dönüyor
    (açık iş). Transkriptler + manifest `tests/trjson/synth/` → test kapısında **synth** kümesi (ayet takibi, ayet gecikmesi,
    yanlış gösterim, bölüm kilidi; Kotlin'de `synth_rakat_errors` / `synth_namaz_errors`).
  - Bu koşunun bulguları → düzeltmeler: (1) **hatimde sure sınırı**: 2. rekât Ahkâf sonunda bitti, 3. rekât Muhammed 47:1 ile
    devam etti; "الذين كفروا وصدوا عن سبيل الله" 4:167 / 16:88 / 47:1'de aynı → 4:167'ye kilit, 47 bölümü 29 sn gecikti (5 yanlış
    parça). Devam penceresi (`continue_window`) sure biterse **sonraki surenin başına taşar** → 47:1, 6.4 sn, 0 yanlış. Normal
    namazda da işe yarıyor (2. rekâtta mushaf sırasıyla sonraki sure): cuma #3 hibrit Nas 12.3 → **3.2 sn** ("قل أعوذ برب"
    113:1/114:1 eşitliği, 1. rekât Felak'tı). Fixture senaryo 16 → 16 × 265. "Eşitlikte sure açılışını seç" denendi: tek ikinci yer
    yetmiyor (ifade 3+ yerde), alınmadı. (2) Üretici: Kuran bölümüne değen parçalardan namaz sesi klibi alınmaz (iftitah tekbiri
    parçası Fatiha başını içeriyordu → sentetikte rükû arasında "الحمد لله رب العالمين" kilidi). (3) **Açık:** selam ASR'de
    kaçınca rekât sayacı yeni namazı başlatamıyor (teravih 8/8 rekât ama 2-3/4 namaz); selamsız "2. rekât + oturuş + sesli
    Fatiha = yeni namaz" kuralı vitirde (3. rekât sesli) yanlış böler — gerçek teravih / vitir kaydıyla ölçülmeli.
  - Düzeltilmiş üreticiyle üçüncü koşu → `tests/trjson/synth/synth-s1.*` yenilendi: ayet takibi %87.2 / %91.1, yanlış gösterim
    0 / 1, yanlış kilitli parça 0 / 1, 56/56 bölüm; teravih namaz sayısı 3-4/4.
- **Ses verisi kaynak taraması** (`tests/scout_sources.py`, tests.yml `scout` job'u — commit mesajında `[scout]`; yerel oturumun
  ağ erişimi kapalı, CI'da sadece meta veri): Hugging Face'te 150 Kuran veri seti (ör. QUD-Technologies/quran-alignment-benchmark
  CC-BY-4.0 kelime zamanlı; tarteel-ai/tlog CC-BY-4.0 gated, sıradan kişilerin telefon okumaları; RetaSy/quranic_audio_dataset
  Arap olmayanların okuması; dev-ahmedhany/everyayah-wav CC0), archive.org'da 200 kayıt: **gerçek teravihler** (Makkah_Tarawih_1430
  43 saat, taraweeh-khalid-jaleel-1435 52 saat, Medine teravihleri, Hani_Rifai "Tarawih Recitation"), Fatih Çollak (Türk kâri),
  90 ezan koleksiyonu, teravih / hatim duaları. archive.org kayıtlarının çoğunda **lisans belirtilmemiş** → sadece test için CI'da
  indirilir, ses saklanmaz (transkript TRJSON tutulur).
- **Dış kaynak kayıtları** (`tests/external/fetch_external.py`, tests.yml `external` job'u — commit mesajında `[external]`):
  Mekke 1430 + Celil 1435 teravihlerinden kısa sureler (Harem yankısı, canlı okuma), Fatih Çollak, 4 ezan (negatif) → 16 kHz WAV →
  gerçek ASR (eval_pipeline `--manifest`, beklenen sure dosya adındaki numaradan) → TRJSON + MANIFEST log'da / artifact →
  test kapısında **external** kümesi (bkz. açık sorun 15). Yerel oturumda huggingface.co / archive.org / everyayah.com proxy'de
  kapalı (403); indirme CI'da.

### 15. Dış kaynak gerçek kayıtlar (Harem teravihi, Çollak, ezan): zikir, ders girişi uydurması, belirsiz aday (APK build #38+)
- `tests/trjson/external/external-v1.*` (CI koşusu, 44 kayıt, 37 dk ses, gerçek RNNT + hibrit): Mekke 1430 teravihi 16 sure (93-114),
  Halid el-Celil 1435 teravihi 14 sure (87-114), Fatih Çollak 10 sure (105-114), 4 ezan (Kuran değil). Felak kaydının sonunda Nas
  başlıyor (25 sn) → manifest `timeline`. Lisans belirtilmemiş → ses saklanmaz, sadece transkript.
- İlk sonuç (eski kod): ilk kilit **39 doğru / 1 yanlış / 1 yok**, 41 bölümün 40'ı kilitli (medyan 10 sn), Harem yankısında ASR iyi
  (medyan skor 93). Sorunlar:
  - ezan_004 sonu "اللَّهُ أَكْبَرُ النَّاسِ" → 9:72 adayı, "الله أكبر لا" → **9:72 kilit** (2 parça), kesik tevhid "إله إلا الله"
    (kamet beklemesinde) → 1:1 ADAY.
  - Çollak kayıtlarında ASR'nin uydurduğu **ders girişi** "تفسير سورة الأعراف الدرس" (Nablusî tefsir dersinin açılışı; eğitim verisi).
    Tüm transkriptlerde 97 kez (sentetik teravihte 78), çoğu zaman gerçek okumayla aynı parçada: "تفسير سورة الأعراف الدرس اهدنا
    الصراط المستقيم", "نهاية الدرس الحمد لله رب العالمين" → hizalamayı bozuyordu.
  - Ekranda yanlış aday: belirsiz ifadeler ("ألم تر كيف" 14:24 / 89:6 / 105:1, "قل أعوذ ب" 113:1 / 114:1).
  - Kalan (bilerek): Çollak Kevser (24 sn) kilitsiz — "وأعطيناك الكوثر" 2 kelime, sonra dosya bitiyor; ezan_002'de ASR çöp
    ("الذي كذب الرسول" → 92:16 belirsiz aday, artık gösterilmiyor). EzanTracker 3/4 ezanda açılıyor, uzun makamda 25 sn cümle
    gelmeyince kapanıyor (UI).
- Düzeltmeler (Python ref + app.py + Kotlin birebir):
  - **Zikir**: `DHIKR_PHRASES` + "اله الا الله", "الله اكبر" (+1 kelime, zamm kilitli değilken). "الله اكبر" 3 ayette (9:72, 29:45,
    40:10), "اله الا الله" 4 ayette (3:62, 37:35, 38:65, 47:19), hepsi ayet ortasında. Tamamen tekbir olan parça eskisi gibi
    (strip → too_short) — zikir sayılmaz, bekleme uzamaz.
  - **Ders girişi süzgeci** (`strip_namaz_phrases`): "تفسير" (+ "سورة" + sure adı), "(سورة X) الدرس" (+ sıralama kelimesi:
    `LECTURE_ORDINAL_PREFIXES`), "نهاية الدرس" çıkarılır; kalan okuma hizalanır. "تفسير", "الدرس", "نهاية" Kuran'da yok; "سورة" ve
    sure adı sadece bu kalıpta silinir. ("النابلسي" içeren parça eskisi gibi tamamen boş.)
  - **Belirsiz aday** (`AMBIGUOUS_MARGIN` 3, `ChunkResult.ambiguous`, UI): BEKLEME / kilit kaybı adayında ikinci yer (aralığa
    değmeyen, `runner_up_match`) 3 puandan yakınsa aday **ekranda gösterilmez** (MainViewModel kaydırmaz, durum satırı "belirsiz
    aday", log gerekçesinde ikinci yer + fark); state machine kararı aynı, doğrulanınca kayar. Veri (gerçek + sentetik + dış, 2
    zincir, 51 görünür aday): yanlışların farkı 0-2.7 (22/22), doğruların 9'u < 3 (Ayetel Kürsî 2:255 / 3:2 aynı metin, Felak /
    Nas, Fatiha "الحمد لله"), 20'si ≥ 4.1.
- Sonuç (yerel replay, eski → yeni, rnnt / hibrit): dış kayıtlar ilk kilit 39/1/1 → **39/0/1**, yanlış kilitli parça 2 → **0**, ekranda
  yanlış aday 5 → **0**; gerçek 36 kayıt ekranda yanlış aday 5 → **0** (kilitler aynı); zorlama S4 gürültü 31 / 30 → **5 / 3**, S5 7 / 5
  → **0**, S2 4 / 5 → 0 ve kilit ort. 56.7 → 51.7 / 51.7 → 50.8 sn; sentetik ayet takibi 294 → **298** / 307 → **309** (337 ayet; rnnt
  ayet gecikmesi medyanı 5.14 → 5.17 sn — yeni takip edilen ayetler). Kotlin = Python 214 kayıt (fark 0), app.py = referans 2577 parça
  (dış kayıtlar dahil), fixture senaryo 17 (ezan sonu zikri, ders girişi, belirsiz aday) → **17 × 272**, 272/272.
- **CI eval teyidi (36 kayıt, gerçek korpus + RNNT, APK #38 kodu):** replay ile birebir — ilk kilit 19/0/0 (medyan 10 sn), takip
  **50/50** (kilit medyanı rnnt 6 / hibrit 5 sn), yanlış kilitli parça 0 / 0, **ekranda yanlış aday 5 → 0**; hibrit son kelime → ekran
  1.7/2.1 sn, duraklama kesimi %41.
- **CI'da APK yükleme (build #38):** "apk-latest" silinip aynı adla yeniden oluşturulurken iki denemede de 403 → link APK'sız kaldı.
  Artık her build kendi tag'iyle (`apk-ci<N>-<deneme>`) release açar, eski `apk-*` release'leri yenisi oluştuktan sonra silinir
  (build #39 sorunsuz; sebep büyük olasılıkla silinen tag adının yeniden kullanılamaması).
- **external-v2** (`fetch_external.py --set v2`, 23 kayıt, 99 dk): Mâhir el-Muaykılî teravihi 1427 (ayet aralıklı parçalar,
  ör. 51:24-60 — sure ortasından), Medine (Mescid-i Nebevî) teravihi 1436 (67-75, ilk 4 dk), **Hani Rifai teravih rekâtları**
  (gerçek rekât: "استووا واستقيموا" saf düzeltme → tekbir → Fatiha → âmin → zamm; A'râf 7:127, Tevbe 9:91, Yûsuf 12:1,
  İbrâhîm 14:42, Hicr 15:1, Enbiyâ 21:1 — `016_alanbeia2` dosya numarasına rağmen Enbiyâ; ilk 7 dk). Rifai zaman çizelgeleri
  transkriptten (manifest `timeline`, `rakat: 1`, `namaz: 0`). Sonuç: 23 kaydın 29 bölümünün **hepsi kilitli**, yanlış kilitli
  parça 0, ekranda yanlış aday 0; sure ortasından ilk kilit 5 sn (51:24), Hâkka 15-25 sn ("الحاقة ما الحاقة" tekrarı), Rifai zamm
  kilidi Fatiha sonrası ~9-20 sn. Dış kümede toplam 70 bölümün 69'u (kaçan: Çollak Kevser).
- **Uydurma selam okuma arasında:** Rifai Hicr 15:4'te imamın kısa duraklamasında ASR "السلام عليكم" yazdı (hibrit). State machine
  kilitliyken selamı zaten yok sayıyor; ama `RakatTracker` "namaz bitti" deyip sayacı sıfırlıyordu → son okumadan 20 sn içinde
  gelen selam yok sayılır (`SELAM_MIN_AFTER_RECITATION_SEC`; gerçek selam son okumadan 80-150 sn sonra: akşam, cuma ×3). Sentetik
  hatim4 Alafasy'de de 1. rekât rükûsunda uydurma selam vardı (293 sn) → eski sayım 2/2 namaz iki hatanın birbirini götürmesiydi
  (gerçek selam 695 sn'de ASR'de boş); şimdi 1/2 (`synth_namaz_errors` 3 → 4, bilerek). Dış kayıtlarda `signal_false_alarms` 1
  (bu uydurma; kalıp doğru).

### 16. Cuma #3 kameti takip edilmiyordu + namaz zikirleri kartı (APK build #41+)
- Kullanıcı (cuma #3 kaydı, `data/namaz_cuma3_*.wav`): "kametin çoğunu algılamıyor, kilitlenmiyor"; "rükünler arasındaki Allahu
  ekber, semiallahu limen hamideh gibi sözleri de yakala, Türkçe anlamlarını ezan/kametteki gibi popup olarak göster; esselamu
  aleyküm de".
- **Kamet ASR'de:** müezzin telefona yakın (rms 0.18-0.21, Fatiha'nın ~3 katı; kırpılma %0.015, spektrum normal) ve ASR kametin
  ortasını çözemiyor: 5 sn parçalarda "شركة الهدى للخدمات التقنية", "المصدر كتاب", "نور العصا", "عن عيبنا وتضا"; 12 sn pencereli
  kelime transkriptinde bile sadece kırıntı ("أيها الصلاة للصلاة" = hayye ale's-salâh, "وتخاف من الظلام" ≈ kad kâmet). Tanınan:
  10 sn "محمد رسول الله", 40 sn "الله اغبر/اغفر", 44-45 sn "لا إله إلا الله".
- **EzanTracker kaybı:** (1) 25 sn cümle gelmeyince 35 sn'de kapanıyordu (kamet 45 sn'ye kadar); (2) son tekbir / tevhid "hayya'ya
  ulaşıldıysa son" kuralıyla ayırt ediliyordu → hayya'lar duyulmayınca baştaki tekbir / şehadet sayılıp (sıra geri gitmez) atlanıyordu;
  (3) kad kâmet duyulmayınca başlık "EZAN" oluyordu. Düzeltmeler (UI, state machine aynı): Resul şehadetinden sonra gelen tekbir =
  son tekbir ("الله اغفر" de, pencere açıkken), Resul'den sonra (اشهد'siz) tevhid = son tevhid (ilk şehadet değil: sabit parçanın
  1 sn bindirmesinde baştaki tekbir kırıntısı kalabilir); `PHRASE_TIMEOUT_SEC` 25 → 40; kamet duyulmadan son tekbire gelindiyse
  açılıştan ≤ 60 sn (`KAMET_MAX_SEC`) → KAMET, uzunsa EZAN.
  Sonuç (Python kopyasıyla ölçüldü, Kotlin JVM'de birebir): cuma #3 rnnt / hibrit 10 sn açılış → 40 sn son tekbir → 45 / 44 sn son
  tevhid, pencere kametin sonuna kadar "KAMET"; sentetik namaz2 Alafasy (aynı kamet klibi) aynı; dış ezan_003 sonuna kadar (135 son
  tekbir → 140 tevhid, eskiden 90'da kapanıp 105'te yeniden açılıyordu); cuma / cuma #2 değişmedi. Kametin ortası (hayya'lar, kad
  kâmet) bu kayıtta tanınmıyor — tahminle doldurulmadı. CTC metnini ikinci kaynak yapmak denendi: sadece ezan_001'de bir satır
  ekledi, alınmadı.
- **Namaz zikirleri kartı** (`session/ZikirTracker.kt` + `ui/components/ZikirPopup.kt`, UI): her parçanın ASR metninde tekbir
  (parça ağırlıkla "الله أكبر": tekbir çiftleri ve diğer zikirler çıkınca ≤ 1 kelime, Kuran'a eşleşmeyen parça), semiallah
  ("سمع الله" + "قول" dışı kelime ya da "لمن حمد…"; `namazSignal`'in tek başına "حمده" kuralı kart için yok — sentetik teravihte
  Kureyş 106:4 "أطعمهم" → ASR "الذي حمده منه" okuma ortasında kart açtı; aynı metin state machine'de rükû sinyali veriyor, açık),
  "ربنا لك الحمد", selam ("السلام عليكم", bölünmüş "عليكم ورحمة") ve namaz sonu duası ("أنت السلام",
  "منك السلام", "تباركت", "ذا الجلال"; selam ve dua son Kuran okumasından ≥ 20 sn sonra — okuma arası uydurma selam). Kart: başlık
  (TEKBİR / RÜKÛDAN KALKIŞ / SELAM / NAMAZ SONU DUASI), Arapça (KFGQPC), okunuş, Türkçe anlam (Diyanet): "Allah en büyüktür",
  "Allah, kendisine hamd edeni işitti", "Rabbimiz! Hamd sana mahsustur", "Allah'ın selamı ve rahmeti üzerinize olsun", "Allah'ım!
  Sen selamsın, esenlik ancak sendendir. Ey celal ve ikram sahibi! Sen ne yücesin". Ezan penceresiyle aynı yerde ve görünümde; 6 sn
  görünür (aynı parçada birden fazla zikir: 2.5 sn arayla sırayla), dokununca / Kuran okuması kilitlenince kapanır, ezan/kamet
  penceresi açıkken gösterilmez. Log: `[zikir] t=160.0s SEMIALLAH`.
  Ölçüm (36 gerçek + 67 dış + 6 sentetik kayıt, iki zincir): Kuran okunan anda ya da tek sureli kayıtta **0** kart. Cuma #3 rnnt:
  iftitah tekbiri 75 sn, semiallah 160, secde tekbirleri 165-180, 2. rekât semiallah + tekbir 270, selam 350; akşam #2: tekbir 300,
  selam 450, dua 470-480 sn. Camide tekbirlerin çoğu ASR'de yine kayıp (açık sorun 12) — kart sadece duyulanlarda çıkar.
- Test kapısı: `tests/golden/zikir.tsv` (JvmTests `zikir`), `zikir_false_alarms` (0 olmalı), `ezan.tsv` cuma #3 satırları yenilendi.

### 17. Yatsı (19.10, APK #51): kamet geç, Felak "kamet", dua kartı yok, rükûda asılı ayet (APK build #52+)
- `data/namaz_yatsi_kamet_fatiha_araf_fatiha_araf.wav` (camide telefon, 20.8 dk; telefon log'u 105. parçadan, t=488.8 — logcat
  tamponu ilk 8 dk'yı tutmamış): 0-685 Türkçe vaaz (içinde Fatiha 9-34, Felak 333-350, Fatiha 423-451 okunuyor) → kamet 685-735 →
  iftitah → Fatiha 744 → A'râf 7:51-53 (776-851) → rükû / secde → Fatiha 892 → A'râf 7:54-55 (930-980) → 3-4. rekât sessiz
  (semiallah ~1075, ~1135) → selam 1217 / 1224 → dua 1237. TIMELINE CI kelime zamanlı transkriptinden (`words`) + enerji zarfı.
  Telefon kararları = eval hibrit zinciri. Yanlış kilit 0; Fatiha 1:2 748.8 (hızlı kilit), A'râf 7:51 781.0 (doğal geçiş), 2. rekât
  Fatiha 901.7, selam 1221 (rekât sayacı "4 rekât").
- Kullanıcı: "ayete / kamete / namaz komutlarına geç kilitlenme, yanlış kilitlenme sorunlarını düzelt"; "sondaki Allahümme ente's-selam
  duasını algılamadı"; "Araf 7:55 gibi göstermesin, Araf: 55"; "zammdan sonra rükûya gidilince ayet ekranda asılı kalmasın, ekran boş
  kalsın; ne kadar kalacağı ayardan 0-10 sn, 0.1; ekran boşken üst bilgi (rekât, secde) dursun".
- Düzeltmeler (state machine: Python ref + app.py + Kotlin birebir):
  - **Kamet başı tekbir + tevhid** (`TEKBIR_TEVHID_CHUNKS` 2, `SessionState.last_tekbir_chunk`): 688.8 / 693.8 "الله اغبر" (tekbir
    kartı), 698.8 "لا اله الا الله" zikir sayılıyordu (tek başına tevhid Kuran'da 4 yerde + ezan / kamet sonunda), kamet ancak 708.8
    "أشهد أن سيدنا محمد" ile (kamet başından 24 sn). Kilit yokken (BEKLEME / ARA, bekleme dışında) tamamen tekbir parçasından ≤ 2 parça
    sonra gelen tevhid = kamet / ezan → 698.8 (10 sn erken). Tüm veride (gerçek + dış + sentetik + bileşik, iki zincir) sadece bu parça
    değişiyor; 3 parça arayla tevhid kamet değil (fixture).
  - **Felak "برب الفلاح" kamet değil** (`FALAQ_PREV`): sabit parçada vaazdaki Felak "أعوذ برب الفلاح" ("الفلاح" kamet kelimesi) →
    sıfırla + 12 parça Fatiha beklemesi → Felak hiç kilitlenmedi; namazda zamm Felak olsa zamm kaybolurdu. Tüm transkriptlerde "الفلاح"
    4 kez: 3 "ايها الفلاح" (hayya), 1 bu. → Felak 12 sn'de kilit (aday 2 sn).
  - **Fatiha sonunda ayet başı tercihi** (`AYAH_START_TIE_MARGIN` 2, `MUQATTAAT`, `starts_ayah`): sabit parçada "الذين اتخذوا دينهم لهوا
    ولعبا" 7:51'in başı + 6:70'in ortası ("وذر الذين اتخذوا دينهم لعبا ولهوا") → 6:70'e doğal geçiş. Fatiha sonundaki doğal geçiş
    (açılış / devam penceresi değil) ayet ortasına oturduysa ve ikinci yer (≤ 2 kötü, ≥ 77, doğal geçiş) bir ayetin başındaysa o alınır;
    1. ayette besmele, ayet başındaki mukattaa harfleri atlanır (ASR "الر"yi düşürüyor: istisnasız Rifai Yûsuf 12:1 → 26:2'ye kayıyordu).
    Tüm veride sadece hedeflenen 2 parça değişti.
- **Namaz sonu duası** (`ZikirTracker`, `DUA_AFTER_SELAM_SEC` 90): dua ASR'de "اللهم كسر" (5 sn parça), "يا ذا العلي" (12 sn pencere) —
  "أنت السلام" / "تباركت" / "ذا الجلال" hiç yok. Selam kartından sonra 90 sn içinde "اللهم" ile başlayan ya da "يا ذا" içeren ilk
  (kilitli eşleşme olmayan) parça = NAMAZ SONU DUASI, selam başına bir kez ("اللهم" Kuran'da 5, "يا ذا" 2 yerde → sadece selamdan sonra).
  Yatsıda 1236 sn'de kart; altın dosya `zikir.tsv`.
- **Ayet etiketi "Sure: ayet"**: telefon (ayet satırı, alt bar) `MushafData.ayahTag` = `A'râf: 55`; G2 başlığı `layout.ayahLabel` =
  `A'râf: 55 · 1. REKÂT · KIYAM`. Log'larda `label()` (`A'râf 7:55`) aynen.
- **Ses kesilince metin kalkar** (`audio/VoiceActivity.kt`: `VoiceActivity` + `TextHold`, UI — state machine aynı; Ayarlar → **SES
  KESİLİNCE METİN** 0-10 sn, 0.1 adım, varsayılan 3.0, `AppSettings.textHoldTenths`): yatsıda 7:53 rükû / secde boyunca 50 sn
  (852 → 901.7), vaazdaki Fatiha dakikalarca ekrandaydı.
  - Konuşma eşiği okunan sesin kendisinden: son 5 gösterilen okuma parçasının (kilit / görünen aday) RMS medyanının 0.3'ü, 100 ms
    çerçeve RMS'i 5 çerçeve medyanla. Sabit eşik (0.006) gürültülü camide rükû / secdede hiç 3 sn sessizlik bulmuyordu; son 30 sn'nin
    p10 / p90'ından uyarlamalı eşik telefon titreşimi / âmin korosundan sonra alçak sesli okumayı "sessiz" sayıyordu (akşam #2 Ra'd,
    15 sn).
  - Karar: son konuşmadan ≥ max(ayar, 0.5) sn **ve** ayetin son güncellenmesinden ≥ ayar sn geçtiyse ya da ses sürse de ≥ max(ayar,
    20) sn yeni eşleşme yoksa (`NO_MATCH_SEC`: vaazda Türkçe konuşma okuma kadar yüksek, Fatiha 157 sn ekrandaydı; okuma içinde iki
    eşleşme arası en fazla 12.1 sn). Yeni okuma eşleşince metin geri gelir.
  - Telefon: okunan ayetin vurgusu / kartı ve alt bardaki etiket kalkar, liste yerinde durur. G2 (`GlassesState.blank`): ayet yok,
    üst satırda rekât / duruş (`2. REKÂT · RÜKÛ / SECDE`) — zikir / ezan kartı varsa o; simülatörde boş ekran 0 karo, geri dönüş 4 karo.
    Log `[metin] t=…s ses kesildi (son ses …s), metin kalkti (bekleme 3,0 sn)`.
  - Ölçüm (JVM `hide`: Kotlin StateMachine + VoiceActivity gerçek WAV çerçeveleriyle, hibrit, TIMELINE'lı 10 kayıt, 3 sn): okuma
    içinde yanlış silme **0** (2 sn'de 1), kalkmayan 0; okuma bitişinden silmeye medyan 7.0 sn (namazlarda 2.5-8 sn; 20 sn kuralıyla
    akşam #2 Ra'd sonrası telefon titreşimi 21 sn, yatsı vaazındaki Felak / Fatiha sonrası 19-20 sn). Test kapısı: `hide_false` (0),
    `hide_latency_median` / `_max`, `hide_missing`.
- Sonuç (TRJSON replay, 37 kayıt): takip rnnt **57/57** bölüm (Felak), hibrit 57/57, yanlış kilitli parça 0 / 0, ekranda yanlış aday 0;
  yatsı hibrit Fatiha 6 / Felak 8.3 / Fatiha 2.6 / Fatiha 4.8 / A'râf 5 / Fatiha 9.7 / A'râf 4 sn; diğer kayıtlar aynı. Fixture'a 2 senaryo
  (kamet tekbir + tevhid / 3 parça arayla tevhid, Felak "برب الفلاح") → 19 × 289.
- Açık: duraklama kesimi sadece kilitliyken (ARA'da sabit 5 sn) → rükû / secde zikir kartları parça sonunu bekliyor; ARA'da duraklama
  kesimi gerçek ASR'yle CI'da ölçülmeli. 2. rekât Fatiha'sı 9.7 sn ("المصدر كتاب" + kısa parçalar).

### 18. Ses tanıma modeli: aday modelleri yarıştırma düzeneği (ASR model yarışı)
- Neden: gerçek namaz / telefon kayıtlarında (hibrit) okuma sırasındaki sesli parçaların ~%9'unda ASR boş, ~%11'inde kilit için
  yetersiz metin; okuma dışında 46 uydurma ("شركة الهدى", "المصدر كتاب", "تفسير سورة…"). Eski karşılaştırma
  (`benchmark/full_results.json`, 20 klip): FastConformer kelime hatası %31; Tarteel'in Kur'an Whisper'ları daha kötü (%41-67).
- Bulunan adaylar (2026, arama özetleri; HF bu oturumdan kapalı): aynı temel modelin Kur'an ince ayarları —
  `msyukriafifi/fastconformer-quran-ar` (hibrit RNNT + CTC, tarteel-ai/everyayah), `muhdur/tilawi-fastconformer-quran` (sadece
  CTC, hazır ONNX, CC-BY-4.0); Quran-Lab held-out benchmark (stüdyo + telefon, 600 klip): NVIDIA temel %7.44, Kur'an
  FastConformer %5.41 kelime hatası. Riskler: temiz stüdyo verisi (cami / cep yok), Kur'an dışı Arapçayı (kamet, semiallah, selam,
  dua) unutma, gürültüden Kur'an uydurma, Uthmani yazım; EveryAyah ile eğitilenler sentetik kümemizin kârilerini görmüş (sızıntı).
- **Düzenek** (uygulamaya dokunmaz):
  - `scripts/onnx_full_export.py --model-name` NGC/HF adı (başka HF deposunda .nemo bulunup indirilir), .nemo yolu / URL'si;
    `--quantize int8`: ana graph'in MatMul/Gemm ağırlıkları dinamik INT8 (`MatMulConstBOnly`; Conv'a dokunulmaz — bazı
    onnxruntime-android derlemelerinde ConvInteger yok; ilk Log düğümünün atası olan ön işleyici (log-mel) fp32 kalır), fp32
    NeMo ile doğrulandıktan sonra; rapora INT8 çıktısı + hızı ve çıktı yazımı (`UTHMANI?` / `imla'i`). `meta.json`'da
    `source_model`, `quantize`. `model-export.yml` girdileri `model_name`, `quantize`.
  - `tests/asr_candidates.json` (tag, model, quantize, kümeler) değişince `.github/workflows/asr-compare.yml`: plan → export
    (`asr-cand-*` release) → evaluate (aday × küme: `data` = data/*.wav + server/recordings, `ext-v1` / `ext-v2` = dış kaynak,
    istenirse `synth`; eval_pipeline rnnt + rnnt-hibrit, `--stats-out` ASR süresi) → score (aday transkriptleriyle test kapısı:
    `TILAVET_TRJSON_DIR=<aday> tests/gate.py --suites replay,stress,compose,external,synth,signals,kotlin` + `tests/asr_compare.py
    metrics`) → summary (temelin yanında tablo + kabul şartı; log'da `SCORE {...}` satırları).
  - `tests/lib/env.py`: `TILAVET_TRJSON_DIR` (varsayılan tests/trjson; `<dir>/*.trjson`, `<dir>/external/`, `<dir>/synth/`).
  - Ses tanıma ölçüleri (`asr_compare.py metrics`, TIMELINE ile): okuma sırasındaki sesli parçalarda boş / yetersiz / kilitli %,
    skor medyanı; okuma dışında metinli parça ve uydurma sayısı; Uthmani yazımlı parça %; ASR ms / parça (CI).
  - **Kabul şartı:** güvenlik ölçüleri temelden kötü olamaz (yanlış kilitli parça, ekranda yanlış aday, yanlış ilk kilit — gerçek,
    dış, zorlama; sinyal / zikir yanlış alarmı, okuma içinde metin silme; kamet / selam / semiallah / ezan yakalama düşmez);
    iyileşme: okumada boş + yetersiz % ya da takip gecikmesi medyanı. Kazanan: android.yml / eval.yml `MODEL_TAG` → `asr-model-v3`,
    yeni transkriptler tests/trjson'a, `--update-baseline`.
- **İlk koşu (20.10, asr-compare run 39361314480; export + evaluate bitti, puan / özet işleri GitHub faturalama limiti yüzünden
  başlamadı — artifact'ler 14 gün duruyor, "Re-run failed jobs" ile puanlanır; değerler eval'in kendi takip simülasyonundan):**

  | | data: kilitli bölüm (rnnt / hibrit) | yanlış kilitli parça | ekranda yanlış aday | ilk kilit d/y/yok | skorlanan parça · medyan (hibrit) | ext-v1 kilitli | ext-v2 yanlış kilitli | ASR ms/parça (CI x86) |
  |---|---|---|---|---|---|---|---|---|
  | temel (asr-model-v2) | 57 / 57 | 0 / 0 | 0 / 0 | 19/0/0 | 428 · 92.6 | ? / 40 (41) | 0 / 0 | 110 / 106 |
  | INT8 (asr-cand-int8) | 57 / 57 | **1** / 0 | 0 / 0 | 19/0/0 | 423 · 91.7 | 41 / 41 | 0 / 0 | **256 / 216** |
  | Kur'an ince ayarı (msyukriafifi) | **52 / 51** | **5 / 4** | 1 / 2 | **16/1/2** | **313 · 85.1** | 40 / 40 | **4 / 3** | 112 / 109 |

  - **Kur'an ince ayarı reddedildi:** temiz kayıtlarda iyi (Nas hibrit medyan 77 → 100) ama cami / telefonda çok parça boş ya da
    bozuk: Zilzal, Mâûn, Ra'd (hibrit), asr.wav kaçtı; telefon_fatiha_maun_kureys 3, cuma 2, yatsı 1, session_1777005364 2 yanlış
    kilitli parça (75:14'e yanlış ilk kilit); Rifai teravihinde 4 / 3. Çıktı harekeli imla'i (aligner'la uyumlu), tokenizer aynı.
  - **INT8 alınmadı (kalite öncelik):** ağırlık 438 → 165 MB, doğruluk neredeyse aynı ama sabit parçada akşam kaydında 1 yanlış
    kilitli parça, hibrit kilit medyanı 5 → 6 sn, skor medyanı 92.6 → 91.7; CI'ın x86 makinesinde parça başına **2 kat yavaş**
    (MatMulInteger; export makinesinde 5 sn RNNT 158 → 81 ms hızlıydı — telefon ARM'ında ölçülmedi). APK boyutu derdi olursa
    yeniden bakılır.
- Sonraki aşama: kendi ince ayarımız (açık sorun 19).

### 19. Kendi ince ayarımız: cami verisi toplama + eğitim betikleri (kiralık GPU)
- Kullanıcı (20.10): "cami verisi kaç tane var? daha çok cami verisi ilave edip öyle GPU testlerine geçsek daha verimli olmaz mı?"
  — elde 6 cami namazı (aynı imam): akşam 27.09 / 01.10, cuma 02.10 / 09.10 / 16.10, yatsı 19.10 = 58.9 dk kayıt, **17.8 dk Kur'an
  okuma** (14 Fatiha, 11 zamm bölümü), ~41 dk okuma dışı (kamet, rükû / secde, cemaat, vaaz, titreşim). Karar: önce veri — hedef
  20-30 sesli namaz (sabah / akşam / yatsı / cuma), mümkünse farklı cami / imam; kullanıcı kayıtları `Download/Tilavet Takip`'ten
  alıp gönderir; betikler şimdiden hazır, veri birikince kiralık GPU'da tek komut.
- **Bölüm kuralı** (`training/real_labels.json`): ilk 6 kayıt + `server/recordings` + `telefon_*` hep **test** (bileşik testler de
  onları kullanıyor); yeni kayıtlar varsayılan train, her 4. yeni kayıt test. Etiket: `segments` (sure + ayet aralığı + zaman; Hanefi:
  Fatiha 1:2'den), `kamet`, `phrases` (tekbir / semiallah / selam / dua kanonik metin), `negatives` (Türkçe vaaz — içinde Arapça zikir
  olmamalı). Yeni kayıt gelince: eval (kelime zamanlı) → TIMELINE + real_labels girdisi.
- **Etiket yazımı:** Tanzil imla'i metni **harekeli** (rasm map `@imlaey`; aligner korpusuyla aynı yazım). Temel modelin tokenizer'ı
  (1024 parça, 52 karakter: 0621-0652 + U+0670) bu metni birebir token'lıyor (`حْمَٰ` parçası var); harekeli etiket harekesizle aynı
  uzunlukta (besmele 17 / 16 token). `asr_compare.py`'nin Uthmani ölçüsünden U+0670 çıkarıldı (imla'i Tanzil'de de var).
- **Aşamalar** (`training/README.md`): A `build_dataset.py` — EveryAyah ~26 murattal kâri (test kârileri yasak: Alafasy, Husary,
  Şureym, Sudeys, Maher, Hani Rifai, Medine imamları; doğrulama: Ali Hajjaj), 1-6 ayetlik koşular her ayet 4 kâriden (~100 sa),
  5-15 sn parçalar (içinde ayet sınırı), %75 cami akustiği (`acoustics.mosque`: hoparlör EQ / kırpma, RT60 0.6-3 sn yankı, telefon
  bandı, gerçek (sadece train kayıtlarından) ya da sentetik gürültü — pembe / kahverengi / şebeke uğultusu / cemaat uğultusu / titreşim,
  SNR 0-25 dB), %5 gürültü + FLEURS Türkçe (vaaz gibi) **boş etiket**; 20 sn'den uzun ayetler ve gerçek kayıt bölümleri hizalamaya.
  B `prepare_labels.py` — temel modelle temiz MP3 doğrulaması (normalize kelime hatası > %50 → at; 1. ayette okunan besmele etikete),
  CTC Viterbi zorla hizalama → kelime zamanı → 4-15 sn parçalar (kelime güveni = yol − karenin en iyisi log olasılığı; gerçek
  kayıtlarda ilk / son kelime atılır; 20 sn'den uzun / kelimesi 4 sn'den uzun parça atılır), gerçek parçalar 1 asıl + 1 gürültülü
  kopya, FLEURS ar (genel Arapça) etiketi = temel modelin kendi çıktısı (unutmayı önler; uydurma / FLEURS metninden uzak olan atılır).
  C `finetune.py` — NeMo 2.7.3, temel modelden, AdamW 1e-4 kosinüs (ısınma 500), bf16, lhotse dinamik paket (GPU belleğine göre
  250-900 sn ses; epoch → adım çevrimi), doğrulama WER'ine göre en iyi `.nemo`, isteğe bağlı kodlayıcı dondurma. D `evaluate.py` —
  temel + yeni model ONNX (`onnx_full_export.py`), aynı kayıtlar (eğitimdeki gerçek kayıtlar hariç data, ext-v1 / v2, sentetik —
  Alafasy + Şureym eğitimde yok), paralel eval (`TILAVET_ORT_THREADS`), test kapısı + `asr_compare.py` → `summary.md` (RED / ADAY /
  KAZANÇ YOK). Kabul → `publish.sh v3` (`asr-model-v3` + `asr-train-v3` release) → MODEL_TAG değişir, yeni APK.
- Yerel deneme (GPU'suz): NeMo 2.7.3 + torch (PyPI) scratch venv'de; temel modelle aynı mimari ve tokenizer'da küçük rastgele model
  (427 bin parametre) ile `--smoke --fake` veri → A → B (gerçek cami kaydı geçici train: segment / kamet / zikir / olumsuz) → C (sabit
  paket + lhotse, doğrulama + en iyi model) → D (export, eval, kapı, özet) uçtan uca çalıştı; Viterbi birim testi. Bulunan / düzeltilen:
  torch ≥ 2.6 `weights_only` NeMo'nun en iyi model adımını kırıyor (`TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1`), NumPy 2 int8 taşması
  (Viterbi geri izleme), NeMo kurulurken pip torch'u CUDA 13'e yükseltiyor (requirements'ta torch sabit, cu126 index).
- Kalan: gerçek modelle ilk çalıştırma kiralık makinedeki duman testi (`run_all.sh --smoke`, ~30-45 dk); EveryAyah klasör adları
  yoklanıyor (olmayan kâri atlanır); GitHub Actions faturalama limiti (20.10) çözülmeden CI / APK yok.

### 20. Yatsı #2 (20.10, APK #102): kayıp kilitte kamet, rükûda kısa zayıf eşleşme, rekât sayısı, dua kartı (APK #105+)
- `data/namaz_yatsi2_kamet_fatiha_taha_fatiha_taha.wav` (özel repoda; camide telefon, 15 dk 15 sn; telefon log'u logcat'ten — ilk
  90 sn tamponda yok): 0-120 namazdan önce biri İhlas'ı 3 kez + Sâffât 37:180-182 okuyor → kamet 165-247 → iftitah ~262 → Fatiha
  274-311 → Tâhâ 20:100-111 (321-436) → semiallah ~451 → Fatiha 487-518 → Tâhâ 20:112-115 (527-586) → 3-4. rekât sessiz → selam
  820-830 → dua. TIMELINE kelime zamanlı transkriptten (yerelde: model public release'ten indirilip `eval_pipeline --words`;
  sabit parça transkripti CI'dakiyle birebir — cuma #3'te 76/76 parça). Yerel hibrit tekrar = telefon kararları (parça parça).
- Kilit gecikmeleri iyi (Fatiha 5 sn, Tâhâ 20:100 ~5 sn, 2. Fatiha ~6 sn, 20:112 hatim devamı ~5 sn), yanlış sure kilidi yok. Sorunlar:
  - **Kamet geç (194 sn, kamet 165'te başladı):** namaz öncesi okuma 37:182'de ZAMM kilidi bıraktı, 50 sn sessizlikten sonra kamet
    tekbirleri ("الله اغبر" ×2, 175-180) ve "شهود لا اله الا الله" (189) ZAMM'da zikir sayılmadı (37:35 belirsiz adayı). Düzeltme:
    kilit kaybolmuşsa (`ABANDON_LOCK_AFTER_LOST`+ kayıp parça) zikir ifadesi ve tekbir + tevhid kuralı ZAMM / FATIHA'da da →
    kamet 189 sn.
  - **Rükûda okunmamış ayet:** 20:111 bitti (436), 3 boş parça, semiallah ASR'de "لم يعد" → 20:112'ye 62.9 → ekranda 20:112
    (2. rekâtta okundu). Düzeltme (`PAUSE_LOST_CHUNKS` 2): ZAMM'da ≥ 2 ardışık kayıp parçadan sonra < 3 kelime ve < ilk kilit
    eşiği eşleşme devam sayılmaz. FATIHA'da denendi, alınmadı: Fatiha → zamm arasındaki âminden sonra zammın kısa ilk parçası
    ("إن الإنسان") Fatiha'ya zayıf eşleşip kayıp sayacını sıfırlıyor; reddedilince bileşik teravihte Asr bölümü hiç kilitlenmedi.
  - **Rekât sayacı "2 rekât"** (semiallah hiç tanınmadı): `RakatTracker` selamda son okumadan geçen süreden sessiz rekât tahmini
    (`SILENT_ONE_RAKAT_SEC` 132 / `SILENT_TWO_RAKAT_SEC` 195; son okuma → selam: 2 rekâtlı gerçek cumalar 90-100 sn, sentetik
    95-125, bileşik teravih 85-95; akşamlar 140 / 150; yatsılar 240 / 250 — 125 denendi, sentetik teravihte 2 rekât 3 sayıldı).
    Yatsı #2 → 4, akşam #2 (eskiden 2) → 3.
  - **Duada 3. selam kartı:** duadaki "ومنك السلام" ASR'de "السلام عليكم" → `ZikirTracker`: dua kartından sonra
    (`DUA_AFTER_SELAM_SEC` içinde) selam kartı açılmaz. Dua kartının dua sürerken tekrarı kalır ("selam başına bir kez" denendi:
    akşam #2'de 475 / 480 sn kartları kalkıp kart dua ortasında kapanıyordu — alınmadı).
  - Kalan: 20:100 başı parça sınırına düştü (âmin + "شركة الهدى" uydurması) → kilit ~5 sn; semiallah bu imamda ASR'de tanınmıyor.
- **Değişiklik denetimi (kullanıcı: "ayet algılamadaki hiçbir değişiklik bizi kötüye götürmemeli; her değişikliği en eski
  kayıttan başlayarak test et"):** eski / yeni / sadece kamet / sadece rükû kuralı her kayıtta ayrı ayrı (2026-04-24 server
  oturumlarından 20.10'a, 38 kayıt × 2 zincir): 37 eski kayıtta karar izi birebir aynı, yatsı #2'de sadece hedeflenen 2 parça;
  test kapısının Python kümelerinde (aynı veri / zaman çizelgesi / tohum) 170 metrikten tek fark S4 gürültü hibrit yanlış kilitli
  parça 10 → 9; Kotlin = Python 272 kayıt, app.py = referans, fixture 312/312 (senaryo 20).
- **CI / APK düzeni (kullanıcı: "görüntü / kullanım yeniliğiyse ses tanıma testlerini boşuna koşma"; 21.10: "apk üretmen için artık
  benim onayımı beklemene gerek yok"):** APK yalnız commit mesajı `[apk]` ile başlıyorsa (ya da elle) — bkz. "Nasıl build edilir";
  test kapsamı değişen dosyalara göre (`tools/ci_kapsam.sh`).

### 21. Sabah namazı + namaz sonu aşr (21.10): uydurmalı Fatiha, belirsiz aday doğrulaması, kayıp kilitte devam, "صدق الله العظيم"
- `data/namaz_sabah_kamet_fatiha_isra_fatiha_adiyat.wav` (özel repoda; camide telefon, 9 dk 27 sn): kamet 0-50 → iftitah ~52 →
  Fatiha 63.7 → İsrâ 17:8-15 (101-263) → rükû / secde (semiallah ASR'de yok) → Fatiha 320 → Âdiyât 100 (355-412) → semiallah ~426 →
  selam 516-530 → istiğfar / dua. `data/tilavet_hasr_22_24_namaz_sonu.wav` (namazdan sonra okunan aşr, 2 dk 16 sn): istiaze × 2 +
  besmele → Haşr 59:22-24 (31-106) → "صدق الله العظيم" → Sâffât 37:180-182 (114-130). TIMELINE kelime zamanlı transkriptten (yerel
  `eval_pipeline --words`); yerel hibrit tekrar = telefon kararları (parça parça).
- Telefonda (eski kod): sabah kamet 5 sn, Fatiha 6 sn, İsrâ 17:8 3 sn, Âdiyât 3 sn — ama **2. rekât Fatiha'sı 15 sn**: semiallah
  duyulmadığı için ZAMM'da kalan kilit 13 parça kayıptı; "والحمد لله رب العالمين شركة الهدى للخدمات التقنية" uydurma kelimesi yüzünden
  parçanın tamamı boş sayıldı, sonraki "مالك يوم الدين إياك نعين" ancak aday. Aşr: "عالم الغيب والشهادة" belirsiz **6:73** adayı (9:94
  ile eşit) "هو الرحمن الرحيم" ile doğrulandı (pencerede 71.3; tüm Kuran'da 2:163 / 59:22 100) → 50-70 sn ekranda 6:73; 59:23 70 sn;
  59:24 hiç kilitlenmedi (4 boş parçadan sonra kilit kayıp, "الا وهو العزيز" tüm Kuran'da 3:6 / 3:18 93.9, 59:24 93.3 → belirsiz aday);
  "صدق الله العظيم" 69:33 adayı, Sâffât sadece aday (ekranda 59:24 asılı).
- Düzeltmeler (Python ref + app.py + Kotlin birebir):
  - **Uydurma ifadesi parçadan çıkarılır** (`strip_asr_hallucination`, `HALLUCINATION_HEADS` / `_CONT`): "شركة" / "موسوعة" + marka
    kelimesi (الهدى / النابلسي / النحل / التابعين …) + devam kelimeleri (للخدمات, التقنية, للعلوم الإسلامية …) silinir; kalan (istiaze /
    zikir hariç) ≥ 3 kelimeyse parça o metinle işlenir, değilse eskisi gibi boş; başka uydurma kelimesi kalırsa ("لفضيلة … النابلسي",
    "لا تنسوا مشاركة") yine boş.
  - **Kilidi kaybolmuş ZAMM = ARA gibi** (Fatiha yoklaması): `ABANDON_LOCK_AFTER_LOST` dolmuşsa 3 kelimeyle yoklanır ve pencere
    dışındaki en iyi yerden `FATIHA_ARA_MARGIN` (8) düşük olsa da Fatiha kazanır (ASR başa "و" ekliyor: "والحمد لله رب العالمين" 6:45'te
    100, 1:2 92.4). ARA'da da aynı pay.
  - **Aday doğrulaması tüm Kuran'la kıyaslanır** (`VERIFY_GLOBAL_MARGIN` 15): BEKLEME adayının penceresindeki eşleşme tüm Kuran'daki en
    iyi yerden ≥ 15 kötüyse aday doğrulanmaz, en iyi yer yeni aday olur.
  - **Kilit kaybında kalınan yerden devam**: kalınan yerin penceresi (aynı sure, son ayetin −`RESUME_BACK`..+3) tüm Kuran'dan ≤
    `CONTINUE_MARGIN` (2) kötü ve ≥ `HOLD_RESUME_MIN_SCORE` (80) ise o (Fatiha yoklamasında pencere içi sayılır).
  - **Tilavet sonu** (`TILAVET_END`, "صدق الله العظيم" Kuran'da yok): ifade çıkarılır, kilit / adaylar biter (BEKLEME, beklemesiz) →
    sonraki okuma (Sâffât) ilk kilit gibi aranır. Çollak kayıtlarında da sonda 69:33 adayı vardı.
  - **Zamm sonundan Fatiha'ya doğal geçiş ≥ 4 kelime** (`FATIHA_FAST_LOCK_MIN_WORDS`, Fatiha yoklamasındaki gibi; kilidi kaybolmuş
    zamm / ARA hariç): sabit parçada Âdiyât sonu "إن ربهم بهم" ASR'de "إن رب العالمين" → Fatiha 1:2'ye doğal geçiş, rekât sayacı "3.
    rekât" saydı (yeni rekât rükû / secdeden sonra gelir). Ölçüdeki "önceki bölüm" toleransı yüzünden yanlış kilit sayılmıyordu.
  - **Belirsiz aday geriye giden parçayla doğrulanmaz** (`PendingMatch.alt_surah/alt_ayah` = ikinci yerin son ayeti): doğrulayan
    parçanın eşleşmesi adayın bittiği kelimeden ileride bitmeli. Aşr: "هو الرحمن الرحيم" 2:163 sonu / 59:22 sonu eşit → belirsiz 2:163
    adayı; 59:23 başı "لا اله الا هو" 2:163'te adayın gerisine oturup doğruluyordu → 60-70 sn 2:163'e yanlış kilit. Bu, ilk sürümün CI
    eval'inde (gerçek hibrit döngü) çıktı: yeni kod 6:73 kilidini engelleyince aşr başında kilit yok → hibrit parçalar sabit 5 sn
    kesiliyor (duraklama kesimi sadece kilitliyken) → sabit parçadaki 2:163 durumu telefonda da olacaktı. Yerel tekrar oynatma eski
    kodun parça sınırlarıyla yapıldığı için görmemişti → yeni kayıtların hibrit transkripti son kodla yeniden üretildi.
  - Denendi, alınmadı: "belirsiz aday belirsiz parçayla doğrulanmaz" ve "aday ile ikinci yeri ayırt etmeyen parça doğrulamaz" —
    ikisi de Âyetü'l-Kürsî (2:255 / 3:2 aynı metin, "الله لا ال" → "لا اله الا هو") ilk kilidini 10 → 20 / 23.5 sn geciktirdi. Birikmiş metin eşiğini gevşetmek (59:22 birleşik metinle 88.6) — riskli.
- Sonuç (denetim: eski kod → son kod; tüm kayıtlar en eskiden — 2026-04 server oturumları → 21.10 — + dış + sentetik + bileşik,
  232 kayıt-zincir): 219'u karar izi birebir aynı, 13'ü değişti, hepsi iyileşme:
  - sabah hibrit 2. Fatiha 12.5 → **5.3 sn** (telefonda 15 sn); sabit parçada Âdiyât sonu 1:2 kilidi yok (rekât sayacı 2 rekât).
  - aşr (iki zincir): yanlış kilitli parça 5 → **0**, ilk kilit 6:73 (yanlış) → 59:23 (70 sn), 59:24 kalınan yerden devam, "صدق الله
    العظيم" kilidi bitirir, Sâffât 37:180 kilitsiz → 6-9 sn. Son kodun gerçek hibrit döngüsünde (yerel eval_pipeline) de yanlış kilit 0.
  - sentetik hatim Fatiha 17.4 → 7.4 / 16.5 → 6.5 / 21.7 → 4.5 sn ("والحمد لله رب العالمين" 6:45 adayı yerine Fatiha), namaz2 /
    teravih8 "موسوعة النابلسي … مالك يوم الدين" → 1:4 kilit; Çollak Nas sonu 69:33 adayı yok; yatsı #2 sabit parçada "بسم الله الرحمن
    الرحيم موسوعة النابلسي…" boş → düşük skor (etkisiz).
  - zorlama (aynı veri + tohum, eski kod → son kod; yeni kayıtlar listeye girince S4 / S5'in rastgele parçaları değiştiği için
    baseline'la değil A/B ile ölçüldü): S1-S3 aynı ya da ortalama gecikme biraz düşük; S4 gürültü yanlış kilitli parça rnnt 36 →
    **14**, hibrit 43 → **18** (kilitli bölüm 337 → 338, ekranda yanlış aday 9 → 8); S5 sahte tekbir rnnt 36 → **12**, hibrit 28 →
    **8** (rnnt kilitli 346 → 347). Kayıt kayıt hiçbiri kötüleşmedi (farkın çoğu yeni aşr kaydında). Baseline'da hibrit S4 / S5
    kilitli bölüm 340 → 338 / 349 → 347 görünmesi aşrın son kodla üretilen hibrit transkriptinden (veri değişti, kod değil).
  - Sentetik ayet takibi rnnt %88.4 → **%90.2**, hibrit %91.7 → **%93.8** (ayet gecikmesi medyanı 5.17 → 5.14 / 5.03 → 4.84 sn).
  - UI: tilavet sonu `ChunkResult.tilavetEnd` → okunan ayetin vurgusu silinir (kamet gibi; ezan / rekât sayacı etkilenmez).
  - Kotlin = Python, app.py = referans, fixture 430/430 (senaryo 21: sabah İsrâ kilidi kayıp + uydurmalı Fatiha, senaryo 22: aşr
    (eski kodun parça sınırları), 23: Âdiyât sonu kısa "Fatiha" ifadesi, 24: aşr son kodun hibrit parçaları — geriye doğrulama).
  - Ses kesilince metin (JVM `hide`): tilavet sonu da metni kaldırır (UI gibi); aşr'da 59:24 okunurken ASR 20 sn boş → 20 sn kuralı
    metni kaldırdı (`hide_false` 0 → 1, eski kodla da aynı — ASR kaybı); kayıt son ayetten 5 sn sonra bitiyorsa silme ölçülmez
    (ortam sesi sürerken en geç 20 sn).

### 22. Yatsı #3 (21.10, APK #113): 2. rekât Enbiyâ devamı Yûnus'a gitti, sonra ekran ileri gidip geldi
- `data/namaz_yatsi3_kamet_fatiha_enbiya_fatiha_enbiya.wav` (özel repoda; camide telefon, 14.7 dk; telefon log'u logcat): kamet sonu
  0-10 → iftitah ~23 → Fatiha 36.6 → Enbiyâ 21:11-23 (81-211) → rükû / secde (semiallah 224) → Fatiha 263 → Enbiyâ 21:24-29 (303.6-388,
  1. rekâtın kaldığı yerden) → 3-4. rekât sessiz → selam 627.6 / 637 → dua. TIMELINE kelime zamanlı transkriptten. Telefonda (APK #113):
  Fatiha 3 sn, Enbiyâ 21:11 3 sn, 2. Fatiha 5 sn, rekât sayacı 4 rekât, selam / dua kartı doğru. Kullanıcı: "ikinci rekâtta sanki
  baya bir yanlış yaptı veya çok ileri gitti geldi". İki hata:
  - **307-316 sn Yûnus 10:38:** "أَمِ اتَّخَذُوا مِن دُونِهِ" ASR'de "أم اتطعتم من دونه" → 10:38 ("استطعتم من دون الله") 77.3 doğal geçiş.
    Devam penceresi (21:23..21:29) 21:24'e 72.2 (sözlük cezası; ham hizalama 83.3 / 89.3) → `CONTINUE_MARGIN` (≥ 77 ve ≤ 2 kötü)
    tutmadı. Düzeltme **devam önceliği** (`CONTINUE_PRIOR_MARGIN` 6): devam penceresi ≥ ilk kilit eşiği ve tüm Kuran'dan ≤ 6 kötüyse,
    en iyi yer bir sure açılışı değilse devam; devam her zaman doğal geçiş.
  - **321-339 sn ileri gidip gelme:** 21:24 okunurken bozuk "بدأ يدع لنا" 21:25'e 65 → ZAMM penceresi son ayetten başladığı için
    (geri pay 0) "يلمون الحق فهم معرضون" (21:24 sonu) 21:26-27'ye 50, "وما حسدنا" 21:28'e 57 (tüm Kuran'da 21:24 84.5 — geçiş adayı,
    görünmez) → sonra 21:25'e geri. Düzeltme **geri düzeltme**: ZAMM'da pencere < ilk kilit eşiği ve aynı surede son ayetin 1-2
    (`RESUME_BACK`) ayet gerisi tüm Kuran'da ≥ `JUMP_MARGIN` iyiyse oraya (okuma geri gitmez — önceki zayıf eşleşme ileri taşımış).
    Denendi, alınmadı: "zayıf pencere + daha iyi geçiş adayı varsa ekran ilerlemesin" — sentetik teravihte doğru (zayıf) bir ayet
    güncellemesini de engelledi (ayet takibi 316 → 315).
- Sonuç (telefon parçaları, eski → yeni): 307 sn 10:38 → **21:24**, 312 sn 10:38 → 21:24, 325 sn 21:27 → **21:24**, 330 sn 21:28 →
  21:25. Denetim (en eski kayıttan, 232 kayıt-zincir, eski → yeni): 6'sı değişti, hepsi iyileşme — bileşik teravih Asr 30 → 20 sn
  (rnnt + hibrit; "الإنسان لفيه السوء" Fatiha sonunda devam), hatimli teravih Rahman 15 → 10 sn, sentetik hatim Saood Tâhâ 6.5 → 1.5
  sn, sentetik teravih Saood Nasr 17.7 → 7.7 / 8.8 → 3.8 sn; sentetik ayet takibi rnnt 304 → 305, hibrit 316 → 317 (ayet ayet:
  önceden takip edilenlerin hiçbirinin gecikmesi artmadı; hibrit medyan 4.84 → 4.85 sadece yeni takip edilen ayetten).
  Yatsı #3 son kodun gerçek hibrit döngüsünde (yerel eval_pipeline): Fatiha 4 / Enbiyâ 3 / Fatiha 5 / Enbiyâ (2. rekât) 4 sn, yanlış
  kilitli parça 0 (eski kodda 2. rekâtta 2 parça 10:38).
- **Baştaki tekbir zikir sayılmaz** (`_drop_leading_tekbir` / Kotlin `dropLeadingTekbir`): kayıt kametin sonunda başlıyor, "الله اغبر لا
  اله الا الله" (tekbir + tevhid tek parçada) zikir sayılmıyordu → belirsiz aday; üstelik Kotlin aligner'ı (aday budaması) 28:88, Python
  37:35 buluyordu → Kotlin = Python izi 2 kayıtta bozuldu. Zikir kontrolü önce eskisi gibi, tutmazsa baştaki tekbir ("الله اكبر" /
  "اكبر") atılıp yeniden (Kuran'da tekbirden hemen sonra tevhid yok) → tekbir + tevhid kuralıyla kamet. Tüm kayıtlarda sadece bu parça
  ve dış kaynak ezan_003 kapanışı ("الله أكبر لا إله إلا الله", eskiden düşük skor) değişti.
- Kalan (bilerek): 21:24 içindeki bozuk "بدأ يدع لنا" 21:25'i bir parça erken gösteriyor (sonraki parça geri düzeltiyor).

### 23. Akşam 22.10 (APK #114): Kâfirûn yerine 7:158, secdede "yeni rekât", Nasr yerine Hicr, tesbihatta 18:39 (APK #115+)
- `data/namaz_aksam3_kamet_fatiha_kafirun_fatiha_nasr.wav` (özel repoda; camide telefon, 11.2 dk; telefon log'u uygulamanın oturum
  .txt'si): kamet 0-45 → Fatiha 56.4 → Kâfirûn 88.2-122 → semiallah ~138 → secdeler → Fatiha 171.3 → Nasr 203.1-226.7 → semiallah
  ("استمع الله") 240 → 3. rekât sessiz → selam → tesbihat. TIMELINE kelime zamanlı transkriptten; yerel gerçek ASR telefonla 137/139
  parça aynı. Kullanıcı: "bugün çok kötüydü kilitlenmeler, hem yanlış hem geç buldu". Hepsi telefonun hibrit zincirinde (sabit 5 sn
  zincir doğruydu):
  - **92.7 sn 7:158:** "قل يا أيها الرحم" 7:158 / 62:6 / 109:1 eşit 78.6, ilki seçildi; Kâfirûn 97.7'de. Düzeltme **sure açılışı
    önceliği** (`OPENING_PREFER_MARGIN` 1): Fatiha sonunda doğal geçiş açılış olmayan yere oturduysa, ilk kelimesi parçanın ilk 2
    kelimesinden biri olan surelerin açılışı (1-2. ayet) ayrıca hizalanır; tüm Kuran'dan ≤ 1 kötüyse açılış.
  - **143.8 sn "yeni rekât":** Kâfirûn bitiminden 21 sn sonra semiallah kuyruğu + 3 sn sessizlik + secde tekbiri başı ASR'de
    "الحمد لله رب العالمين" → kilit düşmeden (4 kayıp parça) ZAMM Fatiha yoklaması → FATIHA; 2. rekât 171.3'te. Düzeltme **erken
    Fatiha** (`FATIHA_MIN_GAP_CHUNKS` 6, `FATIHA_EARLY_MAX_AYAH` 2): ZAMM'da son sağlam eşleşmeden (≥ 3 kelime, ≥ ilk kilit eşiği)
    6 parça geçmeden gelen ve Fatiha'nın 1-2. ayetinde biten eşleşme (yoklama ya da geçiş araması) geçiş adayı olur (görünmez),
    sonraki parça Fatiha'da doğrularsa geçilir. Önce sadece "son sağlam eşleşme ≥ 3 kelime" denendi: gürültü testinde (S4) rükû
    arasındaki 50-60 skorlu çöp eşleşmeler ve 1:5'ten yakalanan gerçek 2. Fatiha 5-10 sn gecikti → skor şartı + 1-2. ayet.
    Veri: tüm kayıtlarda 75 ZAMM/ARA → Fatiha geçişinin hepsi doğru, kilit düşmeden olan 2'si (cuma #2, yatsı #2) değişmedi.
  - **206.4 sn Hicr 15:61, 20 sn:** Nasr "إذا جاء نصر الله" ASR'de "فما جاء النصر" → 15:61 ("فلما جاء آل لوط") 90.5, 110:1 75.0
    doğal geçiş; "والله والفتح" (2 kelime) geçiş araması yapılmadan 15:61 penceresinde 48.4, "يدخلون في" 15:62-63'e 61.3; 110:3
    227'de. Düzeltme **taze geçişin yeniden kontrolü** (`FRESH_JUMP_CHUNKS` 2, `FRESH_JUMP_MIN_SCORE` 80): Fatiha sonunda açılış /
    devam olmayan yere doğal geçişten sonraki 2 parçada pencere < MIN_CONFIDENCE ise parça (2 kelime de) tüm Kuran'da aranır; en
    iyi yer başka surenin 1-2. ayeti, ≥ 80, pencereden ≥ JUMP_MARGIN iyi ve geçiş parçasının metni o açılışa ≥ ilk kilit eşiği
    oturuyorsa (sıralı) geçilir → 210.6'da 110:1. İlk parçanın kendisi (90.5 / 75) düzeltilemedi: 1 parça (4 sn) 15:61 kalıyor.
  - **240 sn "استمع الله":** semiallah tanınmadı ("استمع" Kuran'da sadece 72:1 "استمع نفر") → 72:1'e 86.7 geçiş araması. Artık
    rükû sinyali (`namaz_signal` + zikir kartı).
  - **640 sn 18:39 (hibrit, yeni kod):** namaz sonu tesbihatı "ولا قوة إلا بالله" 18:39'a tek parçada kilit (telefonda parça sınırı
    farklıydı). `DHIKR_PHRASES` + "قوة إلا بالله", "حول ولا قوة إلا بالله" (Kuran'da sadece 18:39, önünde "ما شاء الله"); tesbihattaki
    "الحمد لله ولا إله إلا الله" Kotlin'de 2:255, Python'da 37:35 belirsiz aday (aligner aday budaması) → + "ولا إله إلا الله",
    "لله ولا إله إلا الله" ("ولا اله الا الله" Kuran'da hiç yok; tüm transkriptlerde sadece bu kayıtta).
- Sonuç (telefon parçaları, eski → yeni): 92.7 sn 7:158 → **109:1**, 143.8 sn Fatiha → görünmez aday, 210.6 sn — → **110:1**,
  213.2 sn 15:63 → 110:2, 222.2 sn aday → 110:3, 240.3 sn 110:3 → rükû. Son kodun gerçek hibrit döngüsünde: Fatiha 4 / Kâfirûn
  9.7 → **4.7** / Fatiha 4 / Nasr 24.3 → **7.7 sn**, yanlış kilitli parça 5 → 1. Denetim (en eski kayıttan, 236 kayıt-zincir):
  sadece bu kayıt değişti. Zorlama (aynı veri, 5 tohum, eski → yeni): sabit parça S1-S5 birebir aynı; hibrit S1 / S3 yanlış kilitli 5 → 1, S4 46 → 28 (kilitlenen 376 → 377), S5 25 → 5. Fixture senaryo 26 (telefon parçaları) → 26 × 558.

---

## Bilinen kritik detaylar (kolay unutulan)

### Score formülü (Python `score_transcription`)
```python
score = fuzzy * pow(vocab_coverage, 0.5) * pow(unique_ratio, 0.3)
if max_consec >= 3: score *= 0.3       # aynı kelime 3+ tekrar cezası
if vocab_coverage < 0.3: score *= 0.5  # dusuk vocab cezası
```

### app.py state machine parametreleri
```
SAMPLE_RATE=16000, CHUNK_DURATION=5.0, OVERLAP=1.0
MIN_RMS_ENERGY=0.005
MIN_WORD_COUNT_COLD/HOT/FIRST_LOCK = 3/2/3   ← FIRST_LOCK 4'tu (eval ile 3'e indi)
MIN_CONFIDENCE/FIRST_LOCK = 50/90  ← Kotlin'de FIRST_LOCK 70'e düşürüldü, tuner ile değişir
PREFERRED_AYAH_WINDOW_BASE/MAX/ARA = 2/6/3
ABANDON_LOCK_AFTER_LOST=6, PENDING_VERIFY_AYAH_WINDOW=4
ARA_AFTER_LOST_CHUNKS=12, MAX_GAP_FILL=3, PREFERRED_BONUS=30
FATIHA_WORD_RANGE=(0,30), SURAH_END_THRESHOLD=2
FATIHA_END_AYAH=6, JUMP_SEARCH_BELOW=80, JUMP_MARGIN=15   ← sure geçişi (bkz. açık sorun 5)
FATIHA_FAST_LOCK_MIN_SCORE/WORDS = 90/4                  ← BEKLEME'de Fatiha başı doğrulamasız kilit; zamm sonundan Fatiha'ya doğal
  geçiş de ≥4 kelime (bkz. 21)
RESUME_BACK=2   ← yeniden kilit: aynı surede son ayetin -2..+3'ü doğrulamasız (bkz. açık sorun 7)
FATIHA_BACK_WORDS=3   ← FATIHA penceresi son eşleşmenin 3 kelime gerisinden başlar (bkz. açık sorun 8)
JUMP_SHORT_WORDS/MIN_SCORE = 2/90   ← doğal geçiş noktasında 2 kelimeyle atlama (tek yerde geçen ifade, bkz. 9)
NATURAL_MIN_SCORE=77   ← doğal geçiş bunun altında sadece aday (bkz. açık sorun 10)
OPENING_MIN_FUZZY=75, OPENING_START_SLACK=1   ← geçiş noktasında sure açılışına oturan eşleşme ham hizalama skoruyla
  (sözlük cezasız) doğal geçiş (bkz. açık sorun 11)
KAMET_HOLD_CHUNKS/RUKU_HOLD_CHUNKS = 12/24, HOLD_RESUME_MIN_SCORE=80   ← kamet/semiallah/selam sonrası "sadece Fatiha"
UNIQUE_LOCK_MIN_SCORE/MIN_WORDS/MARGIN = 90/3/12   ← en iyi ile ikinci yer (aralığa değmeyen) arası ≥12 → BEKLEME'de tek
  parçada kilit, kilitliyken sure geçişi doğrulanmış (bkz. açık sorun 12)
EXCLUSIVE_LOCK_MARGIN/MIN_LETTERS = 5/3   ← fark ≥5 + ikinci yerde olmayan besmele dışı birebir kelime de tek parçada kilit
SEARCH_CONCAT_CHUNKS/MAX_OVERLAP = 2/4    ← BEKLEME'de son 2 parçanın metni birleştirilip tek parçada kilit denenir (bkz. 13)
OPENING_TIE_MARGIN=2   ← doğal geçişte eşleşme bir sure açılışı ve başka suredeki ikinci yer de açılışsa (ham hizalama farkı
  < 2: 113:1 / 114:1) geçiş adayı; her yakın ikinci yere genellemek doğru geçişleri bekletti (bkz. 14)
CONTINUE_AHEAD/MARGIN = 6/2   ← hatim / 2. rekâtta sonraki sure: Fatiha sonunda son zamm konumu..+6 ayet (sonraki sureye taşar)
  penceresi tüm Kuran'dan ≤2 kötüyse devam (bkz. 14)
CONTINUE_PRIOR_MARGIN=6   ← devam penceresi ≥ ilk kilit eşiği ve tüm Kuran'dan ≤6 kötü ise (en iyi yer sure açılışı değilse)
  devam; devam her zaman doğal geçiş (bkz. 22)
Geri düzeltme   ← ZAMM'da pencere < ilk kilit eşiği ve aynı surede son ayetin 1-2 (RESUME_BACK) gerisi tüm Kuran'da ≥ JUMP_MARGIN
  iyi → oraya (bkz. 22)
OPENING_PREFER_MARGIN=1   ← Fatiha sonunda doğal geçiş açılış olmayan yere oturduysa, ilk kelimesi parçanın ilk 2 kelimesinden
  biri olan surelerin açılışı (1-2. ayet) tüm Kuran'dan ≤1 kötüyse açılış (7:158 → 109:1, bkz. 23)
FRESH_JUMP_CHUNKS/MIN_SCORE = 2/80   ← Fatiha sonunda açılış / devam olmayan yere geçişten sonraki 2 parçada pencere < MIN_CONFIDENCE
  ise (2 kelime de) tüm Kuran; başka surenin 1-2. ayeti ≥80, pencereden ≥ JUMP_MARGIN iyi ve geçiş parçası o açılışa ≥ ilk kilit
  eşiği oturuyorsa geçilir (15:61 → 110:1, bkz. 23)
FATIHA_MIN_GAP_CHUNKS/EARLY_MAX_AYAH = 6/2   ← ZAMM'da son sağlam eşleşmeden (≥3 kelime, ≥ ilk kilit eşiği) 6 parça geçmeden
  Fatiha'nın 1-2. ayetinde biten eşleşme (yoklama / geçiş araması) geçiş adayı olur, sonraki parça doğrular (bkz. 23)
CANDIDATE_WINDOW_MARGIN=2   ← geçiş adayı ±4 ayetinde tüm Kuran kadar iyi eşleşme adayı doğrular (bkz. 14)
DHIKR_PHRASES / DHIKR_EXTRA_MAX=1   ← kilit yokken sadece "محمد رسول الله" / "لا اله الا الله" / "ان شاء الله" / "اله الا الله" /
  "الله اكبر" / "(لا حول) ولا قوة إلا بالله" / "(لله) ولا اله الا الله" (+1 kelime; tamamen tekbir hariç) → boş; şehadet BEKLEME'de kamet, bekleme sürerken
  zikir beklemeyi uzatır (bkz. 14, 15, 23)
AMBIGUOUS_MARGIN=3   ← BEKLEME / kilit kaybı adayında ikinci yer bu kadar yakınsa `ambiguous` (UI ekranı kaydırmaz; bkz. 15);
  belirsiz adayı geriye giden parça doğrulamaz (eşleşme sonu ≤ adayın sonu, bkz. 21)
TEKBIR_TEVHID_CHUNKS=2   ← kilit yokken (BEKLEME / ARA, kayıp kilit — bkz. 20 — bekleme dışı) tamamen tekbir parçasından ≤2
  parça sonra tevhid → kamet (bkz. 17)
PAUSE_LOST_CHUNKS=2   ← ZAMM'da ≥2 ardışık kayıp parçadan sonra <3 kelime ve <ilk kilit eşiği eşleşme devam sayılmaz (bkz. 20)
FALAQ_PREV={برب, رب}   ← "(ب)رب الفلاح" (Felak "برب الفلق" ASR'de) kamet kelimesi sayılmaz (bkz. 17)
AYAH_START_TIE_MARGIN=2, MUQATTAAT   ← Fatiha sonunda doğal geçiş ayet ortasına oturduysa ≤2 kötü ikinci yer ayet başıysa o
  (besmele / mukattaa atlanır; 6:70 → 7:51, bkz. 17)
HALLUCINATION_HEADS/CONT   ← "شركة / موسوعة" + marka kelimesi + devam kelimeleri parçadan çıkarılır, kalan (zikir hariç) ≥3
  kelimeyse hizalanır (strip_asr_hallucination; eskiden parça tamamen boş, bkz. 21)
TILAVET_END = صدق الله العظيم   ← ifade çıkarılır, kilit / adaylar biter (BEKLEME, beklemesiz; bkz. 21)
VERIFY_GLOBAL_MARGIN=15   ← BEKLEME adayının penceresindeki eşleşme tüm Kuran'dan ≥15 kötüyse aday doğrulanmaz (bkz. 21)
FATIHA_ARA_MARGIN=8   ← ARA'da / kilidi kaybolmuş ZAMM'da Fatiha yoklaması pencere dışı en iyi yerden 8 düşük olsa da kazanır;
  kilit kaybında kalınan yerin penceresi (-RESUME_BACK..+ARA) tüm Kuran'dan ≤ CONTINUE_MARGIN kötü ve ≥80 ise devam (bkz. 21)
Filtreler: strip_istiaze, strip_namaz_phrases (selam (bölünmüş "عليكم ورحمة" dahil)/semiallah (bozuk "لمن حمد…", "حمده"
  dahil)/rabbena/tekbir(اكبر/اغبر/اكبار)
  + namaz sonu duası + "المصدر" + ders girişi "تفسير سورة X الدرس (ORD)" / "نهاية الدرس"), is_asr_hallucination; sinyaller:
  namaz_signal (kamet / selam / ruku — "استمع الله" de rukû, bkz. 23); strip_asr_hallucination (uydurma ifadesi, bkz. 21), strip_tilavet_end ("صدق الله العظيم")
States: BEKLEME, FATIHA, ZAMM, ARA
```

### `preferred_bonus` NEDEN ETKİSİZ
`aligner.py`'de parametre var ama fonksiyon gövdesinde **kullanılmıyor** (yorum: "geriye uyumluluk"). Bu yüzden Kotlin'de eklenmedi — doğru port.

### Aligner test fixture'da hoşgörü
- 43 case, ~11 tanesi Python'dan sayısal fark (start/end_idx). Sebep: Kotlin'de agresif min_hits sıkıştırma (aday >3000 ise min_hits artar) ve score-based pruning. Expansion ikisinde de ±2.
- Bu KABUL EDİLDİ. Fixture doğrulama optimizasyon açıkken yapılıyor.

### Korpus normalized = imla'i (rasm_map)
- Kaynak: `quran-transcript` 0.6.4 wheel'i (MIT, Tanzil Uthmani 1.1 + imla'i karşılıklar), PyPI'dan
  sha256 sabit indirilir → `~/.cache/quran-align/quran-uthmani-imlaey-map.json` (`aligner.ensure_rasm_map`).
- Eşleme ayet ayet `difflib.SequenceMatcher` ile; alquran.cloud metninde 1. ayetlerin başındaki besmele
  atlanır. Gerçek veride: 77596/77878 kelime eşlendi, 5960 ayet tam, 276 kısmi (eşlenemeyen kelime
  Uthmani normalize hâliyle kalır).
- 366 Uthmani kelime imla'ide iki kelime (`يا ايها`): `normalized` boşluk içerir. Vocab
  (`corpus.vocab`, Kotlin `corpusVocab`) ve trigram (`normalized_to_trigrams`) boşluktan bölünür.
- `build_quran_assets.py`, fixture'lar ve server kelimeleri **hep** `QuranCorpus.load()`'dan alır
  (tek kaynak). `QuranCorpus.load(imlaei=False)` eski davranış (karşılaştırma için).

### QuranIndex.getWord vs getNormalized
- `getWord(i)` → `WordRecord(pos, surah, ayah, wordIdxInAyah, text, normalized)`
- `getNormalized(i)` → String — hızlı, normalize edilmiş kelime
- `WordEntry` diye bir class **YOK** — dokümantasyonda karışıklık olmasın

### meal.bin format
```
Header (16B): "MEAL" + version u32 + meal_count u32 + surah_count u32
Meal entries: surah u16, ayah u16, len u16, utf8 bytes
Surah entries: surah_no u16, tr_len u8, tr, ar_len u8, ar, ayah_count u16
```

### Meal baskısı = Ali Bulaç (`tr.bulac`), ayet ayet ayrık (APK #19+)
- Eskiden `tr.diyanet`: ardışık ayetleri tek cümlede birleştirip aynı metni her ayete koyuyor —
  **841 ayette** meal önceki ayetle birebir aynı (kullanıcı: Nasr 110:2-3 aynı, Tarteel'de ayrık).
- `scripts/compare_meals.py` (eval.yml `meal_compare` ✓, sadece CI — alquran.cloud yerelden kapalı):
  ardışık tekrar diyanet 841, yildirim 606, yazir 57, vakfi 10; **ates / bulac / golpinarli / ozturk /
  yuksel 0**. Bulaç Nasr metni Tarteel'e en yakın.
- Baskı tek yerde: `download_meal.py` `MEAL_EDITION` (cache `meal-tr-bulac.json`; build_quran_assets +
  server'lar oradan alır). `build_quran_assets.py` ardışık tekrar > 20 ise build'i durdurur.

### Meal seçimi — Ayarlar → MEAL (APK #105 sonrası)
- Kullanıcı (21.10): "başka meal seçeneklerini de seçtirmek istiyorum ayarlar kısmından" (Diyanet çeşitleri, Erhan Aktaş, 8-10
  meal daha). Telefonda (Mushaf listesi, okunan ayet) ve G2 gözlükte seçili meal; hepsi APK'da (namazda internet yok).
- 7 meal (sıra = Ayarlar'daki sıra; birleşik = ardışık ayette birebir aynı meal):
  | id | meal | kaynak | birleşik |
  |---|---|---|---|
  | `bulac` | Ali Bulaç (varsayılan, `meal.bin`, değişmedi) | alquran.cloud `tr.bulac` | 0 |
  | `diyanetvakfi` | Diyanet Vakfı | fawazahmed0 `tur-diyanetvakfi` (Tanzil) | 10 |
  | `elmalilisade` | Elmalılı Hamdi Yazır (sadeleştirilmiş) | fawazahmed0 `tur-elmallsadelesti` | 25 |
  | `ates` | Süleyman Ateş | fawazahmed0 `tur-suleymanates` | 0 |
  | `esed` | Muhammed Esed — Kur'an Mesajı | fawazahmed0 `tur-muhammedesed` | 0 |
  | `ozturk` | Yaşar Nuri Öztürk | fawazahmed0 `tur-yasarnuriozturk` | 0 |
  | `golpinarli` | Abdulbaki Gölpınarlı | fawazahmed0 `tur-abdulbakigolpin` | 0 |
- **Erhan Aktaş, Mustafa İslamoğlu, Mehmet Okuyan** da istendi; sadece Açık Kuran API'sinde vardı (yazar 105 / 38 / 107) ve
  `api.acikkuran.com` kapanmış (21.10 CI: GitHub sunucularında da "Name or service not known"). Kullanıcı: "şimdilik 7 meal
  yeter". Kaynak geri gelirse `build_meals.py` `MEALS`'e `("acikkuran", id)` satırı (indirme kodu duruyor); başka yol: başka
  sitelerden sure sayfası çekmek (ikrakuran.com, ayetbul.net, mealler.org — kırılgan) ya da kullanıcının vereceği dosya.
- Kaynak araştırması (21.10): fawazahmed0/quran-api 29 Türkçe baskı (raw.githubusercontent.com — yerelden de erişiliyor; Tanzil +
  qurandatabase.org + QuranEnc), Açık Kuran 22 Türkçe yazar (`acik-kuran/acikkuran-frontend` `data/authors.js`; API yerelden
  kapalı; kod lisansı CC BY-NC-SA 4.0). Diyanet'in güncel resmi meali "Kur'an Yolu" ve Ömer Nasuhi Bilmen hiçbir açık veri
  setinde yok (en yakını Diyanet Vakfı: büyük ölçüde aynı ekip). Kullanıcı kuralı **"birleşik baskıları alma"**: birleşik > 100
  olan baskı alınmaz (`MAX_MERGED`) — Hasan Basri Çantay (159) seçilmişti ama bu yüzden yok, eski Diyanet İşleri 843, Suat
  Yıldırım 607. Elenenler: `tur-diyanetisleri1` aslında Elmalılı, `tur-ademugur` = Diyanet Vakfı, `tur-ynozturk` = Öztürk,
  `tur-muhammetabay` okunuş. Meal metinlerinin hakkı yazarlarında (kişisel, ticari olmayan kullanım).
- `scripts/build_meals.py`: `MEALS` listesi (id, ad, açıklama, kaynak) → indir (önbellek `~/.cache/tilavet-meals/<id>.json`,
  CI'da actions/cache `meals-v1-<betik hash>`), temizle (`´` `’` → `'`, Açık Kuran dipnot işareti `[n]` silinir, dipnot
  alınmaz), doğrula (meal.bin'le aynı 6236 ayet, boş yok, birleşik ≤ 100) → `asr/meals/<id>.bin` (meal.bin v1 biçimi, sure
  tablosu meal.bin'den byte byte) + `meals/index.tsv` (`id \t dosya \t birleşik \t ad \t açıklama`, ilki `bulac` → `meal.bin`).
  İndirilemeyen / kurala takılan baskı atlanır (uyarı + run özetinde tablo: ayet, birleşik, kalan işaret, uzunluk, örnekler);
  Bulaç yoksa durur. android.yml (apk) ve tests.yml (gate) `build_quran_assets.py`'den sonra çalıştırır.
- Uygulama: `AssetSync` `assets/asr/meals/*` → `filesDir/asr/meals/` (her yeni APK, APK'da olmayan silinir); `MealCatalog`
  index.tsv'yi okur (bilinmeyen id / dosyası yok → varsayılan); `AppSettings.mealId` (`meal_id`); `MainViewModel.openMealLocked`
  seçili dosyayı açar (açılamazsa varsayılan), ayar değişince `MushafData.withMeals` (diziler paylaşılır, kaydırma yeri korunur),
  G2 `meal` aynı kaynaktan; log `[meal] Diyanet Vakfı (diyanetvakfi)`. Ayarlar: "TÜRKÇE MEAL BOYUTU"nun üstünde **MEAL** —
  seçili meal (ad + açıklama, DEĞİŞTİR), dokununca liste açılır.
- Test: JVM `meals` (MealCatalog + MealLoader: her dosya 6236 meal / 114 sure / sure tablosu = meal.bin / boş yok / birleşik =
  index ≤ 100, ayrıştırma ve varsayılana düşme; `meals_failures` 0), node `tests/g2/layout.test.mjs` "seçilebilir mealler"
  (`TILAVET_MEALS_DIR`: gözlük fontu, normal / Arapçalı başlıksız düzende satır / bayt / genişlik, büyük yazı sayfası →
  `g2_meal_editions` ↑, `g2_meals_dropped_chars` ↓). 7 meal (yerel + CI): hepsi geçiyor, en uzun meal Esed
  (normal düzende 5 sayfa, büyük yazıda 19). `tools/ci_kapsam.sh`: `build_meals.py`, `MealLoader` / `MealCatalog`, `MealTests.kt`
  → G2 kapsamı.

### AndroidManifest.xml FileProvider
Log export için gerekli. `xml/file_paths.xml` içinde `cache-path name="logs"` tanımlı.

---

## Nasıl build edilir

**Build GitHub Actions'ta yapılır** (`.github/workflows/android.yml`) — yerel build yok.
Her push'ta (tüm branch'ler; sadece `**.md` değişince değil), PR'da ve elle (`workflow_dispatch`) çalışır. `model` + `apk` işleri
commit mesajı **`[apk]` ile başlıyorsa** ya da elle; diğer push'larda sadece test kapısı. **Onay gerekmez** (21.10, kullanıcı: "bundan
sonra apk üretmen için artık benim onayımı beklemene gerek yok"; 20.10-21.10 arası "biriktir, sonra sor, onay verirsem üret"):
bir değişiklik seti bitip test kapısı yeşil olunca APK doğrudan üretilir (`[apk]` başlıklı commit ya da elle), ama build sayısı yine
az tutulur (her küçük adımda değil). Aynı dalda yeni push süren koşuyu iptal eder (`concurrency: cancel-in-progress`) — APK derlenirken
`.md` dışı push yapma. DİKKAT: işaretleri commit gövdesinde de yazma (ilk sürümde "içinde geçiyor mu" bakılıyordu,
kuralı anlatan commit'in gövdesi APK #105'i onaysız derletti; `[tam-test]` de sadece başlıkta).

1. **`model` job** (`model-export.yml`, tekrar kullanılabilir) — `asr-model-v2` release'inde model
   var mı bakar. Yoksa önce özel repodaki aynı tag'in release'inden **aynen kopyalar** (KAYIT_TOKEN; aynı dosyalar → aynı
   meta.json, telefon modeli yeniden kopyalamaz), orada da yoksa (ya da `force_model_export` input'u ile) NeMo'yu kurup
   `scripts/onnx_full_export.py` çalıştırır (~5 dk) ve model dosyalarını + `export_report.txt`'yi
   release'e yükler.
   Bağımlılıklar: `scripts/requirements-export.txt` (torch 2.11 CPU + NeMo 2.7.3, dynamo exporter
   opset 18, IR 10 → onnxruntime-android 1.18 uyumlu; export sonrası IR >10 ise 10'a çekilir).
2. **`test` job** (`tests.yml`, tekrar kullanılabilir, `secrets: inherit` — gerçek WAV'lar özel repodan) — APK öncesi test kapısı (`tests/gate.py`, bkz. "Test kapısı"); kırmızıysa
   `apk` çalışmaz.
3. **`apk` job** — Kuran verisini api.alquran.cloud'dan indirir (`~/.cache/quran-align`, actions/cache),
   `quran.bin` + `meal.bin` + 3 fixture'ı üretir, modeli release'ten indirir,
   Gradle 8.7 + JDK 17 ile `assembleRelease` (debuggable değil, minify kapalı, repodaki keystore ile imzalı).
4. Push build'lerinde APK **`apk-ci<N>-<deneme>`** release'ine yüklenir ("Latest" işaretli; eski `apk-*` release'leri yenisi
   oluştuktan **sonra** silinir — build #38'de "sil + aynı adla yeniden oluştur" 403 aldı ve link APK'sız kaldı; hedef commit'te
   tag açılamazsa tag varsayılan dala açılır). Link her zaman aynı. Telefondan direkt link:
   `https://github.com/mrcan321/quran-takip-public/releases/latest/download/tilavet-takip.apk` (20.10'a kadar `quran-takip`)
   Kurulum kablosuz: telefonda linki aç → indir → dokun → kur (güncellemeler de üstüne kurulur).

Notlar:
- APK ~500 MB → workflow artifact olarak **yüklenmiyor**; release asset'i olarak.
- Build numarası `N` = GitHub run numarası + 100 (`BUILD_OFFSET`, `TILAVET_BUILD`): repo taşınınca run numarası 1'den başladı
  (eski repoda son build #53) — versionCode geri giderse Android üstüne kurmaz. `versionCode` = N, `versionName` = `0.2.0-ci<N>`,
  durum satırında `#N`, release `apk-ci<N>-<deneme>`; public repodaki ilk build #101.
- Aynı release'te **G2 eklentisi** `tilavet-takip-g2.ehpk` (`evenhub-cli` 0.1.14 `pack`, sürüm `0.<N>.0` — #48'e kadar `0.1.<N>`;
  kullanıcı: Even yeni build'i algılamadı, son hane yetmiyor olabilir; aynı dosya `tilavet-takip-g2-0.<N>.0.ehpk` adıyla da) ve geliştirici modu
  QR'ı `tilavet-takip-g2-qr.png` (`http://127.0.0.1:18765/`); bu adım başarısız olursa APK yine yüklenir.
- İmza: repodaki sabit `tilavet-android/app/debug.keystore` (şifre `android`) → her CI APK'sı
  eskisinin üstüne kurulur, uninstall gerekmez (ilk geçişte yerel build'li APK bir kez silinmeli).
- Modeli yeniden export etmek için: Actions → Android CI → Run workflow → `force_model_export` ✓.
- Aday ASR modelleri (başka hibrit NeMo modeli / INT8) `tests/asr_candidates.json` + `asr-compare.yml` ile yarıştırılır (bkz. açık sorun 18).

Yerelde asset üretmek (opsiyonel, test/kalibrasyon için):
```bash
pip install rapidfuzz numpy
python scripts/build_quran_assets.py      # → android-assets-staged/asr/
python scripts/explore_rapidfuzz.py
python scripts/build_aligner_fixture.py
python scripts/build_state_machine_fixture.py
```

## Nasıl test edilir

Top bar'daki 6 ikon:
- **Σ** Fuzzy Test — 51 case, ~10-35ms (bit-perfect)
- **#** Aligner Test — 43 case, 2-5 dakika (yavaş!)
- **▶** State Machine Test — 558 chunk × 26 senaryo, ~2-3 dakika (558/558 bit-perfect)
- **🔬** ASR Test — 5sn mikrofon kaydı → transkripsiyon (sonuç durum satırında)
- **📤** Log Export — logcat share intent
- **⚙️** Settings — tema + tuner

Mikrofon butonu (alttaki yuvarlak) → gerçek pipeline başlat. Solundaki dosya butonu → **simülasyon**
(kayıtlı WAV'ı mikrofon gibi gerçek zamanlı oynat; bkz. "Simülasyon modu").

### Test kapısı — her kod değişikliğinden sonra, APK'dan önce (`tests/gate.py`, CI: `tests.yml`)
- `android.yml`'de `apk` job'u `test` job'unu bekler (`needs: [model, test]`): kapı kırmızıysa **APK derlenmez**.
  `tests.yml` her push'ta android.yml'den çağrılır (elle de; `seeds` girdisi). **Kapsam** (`tools/ci_kapsam.sh`, `scope` işi):
  ses tanıma / kilit / state machine / test verisi (`scripts/`, `server/`, `tests/`, uygulamanın session / aligner / audio / asr
  kodu) değiştiyse tüm kümeler; sadece G2 eklentisi / köprüsü değiştiyse `g2,glasses` + simülatör; ikisi de değilse (arayüz) test
  yok; `tests/baseline.json` nötr; commit başlığında `[tam-test]` → hepsi. `eval.yml` push'ta sadece ASR / parçalayıcı / eval
  dosyaları değişince (state machine'i kapı kayıtlı transkriptlerle ölçer).
- **Algılama değişikliği denetimi:** değişiklik hiçbir kayıtta kötüleştirmemeli — eski / yeni kodu kayıt kayıt (en eski tarihliden)
  karşılaştır (karar izi, ilk kilit, bölüm kilitleri, yanlış kilit / aday) + test kapısının tüm kümeleri aynı veri ve tohumla; kötüleştiren
  kural alınmaz (bkz. açık sorun 20).
- Kümeler (`--suites`, varsayılan hepsi):
  - **replay** — gerçek kayıtların CI ASR transkriptleri (`tests/trjson/*.trjson`, 36 kayıt × rnnt + rnnt-hibrit) ASR'siz
    tekrar oynatılır: ilk kilit (doğru / yanlış / yok, süre), sure bölümü başına kilit gecikmesi, yanlış kilitli parça,
    ekranda yanlış aday.
  - **stress** — S1-S5 zorlama (kamet + Fatiha'lı kayıt, kamet + Fatiha'sız sure, hutbe + kamet + namaz, %15 gürültü ×
    `--seeds`, okuma ortasında sahte tekbir).
  - **compose** — gerçek cami parçalarından bileşik namazlar: **teravih 20 rekât** (10 × 2 rekât, her 4 rekâtta tesbih +
    salavat, her set selamla biter), **hatimle teravih** (Rahman iki rekâta bölünmüş, 2. rekât kalınan ayetten), **4 rekâtlı**
    (3-4. rekât sessiz). Takip metrikleri + Kotlin `RakatTracker` ile beklenen rekât / namaz sayısı.
  - **external** — dış kaynak gerçek kayıtlar (`tests/trjson/external/*.trjson` + `*.manifest.json`, tests.yml `external`
    job'unun gerçek ASR çıktısı; ses repoda yok): Harem teravihleri (Mekke 1430, Celil 1435), Fatih Çollak, 4 ezan. replay
    metrikleri + ezan sinyali (`ezan_detected`) + Kotlin EzanTracker (`ext_ezan_opened` ↑, Kuran kaydında açılırsa
    `ext_ezan_false_opened` ↓), teravih rekâtı kayıtlarında RakatTracker son durumu (`ext_rakat_errors`). Manifest'te `expected`
    (sure / `null` = Kuran değil / `"coklu"`), istenirse `timeline`, `kind: "ezan"`, `rakat` / `namaz`. Yeni koşu: commit
    mesajında `[external]` (tests.yml `fetch_external.py --set v2`), log'daki `TRJSON` + `MANIFEST` satırları →
    `tests/trjson/external/external-vN.*`, gerekirse zaman çizelgesini transkriptten düzelt.
  - **synth** — sentetik namaz / teravih / hatim (`tests/trjson/synth/*.trjson` + `*.manifest.json`, synth.yml'nin gerçek ASR
    çıktısı): ayet takibi (ayet okunurken / bitişinden 4 sn sonrasına kadar ekranda), ayet gecikmesi, yanlış gösterim, bölüm
    kilidi; rekât / namaz sayısı kotlin kümesinde (`synth_rakat_errors`, `synth_namaz_errors`). Yeni sentetik koşu: log'daki
    `TRJSON` satırları + `MANIFEST` satırı (json) → `tests/trjson/synth/<ad>.trjson` / `<ad>.manifest.json`.
  - **signals** — kamet / selam / semiallah kalıpları tüm RNNT + CTC metinlerinde: Kuran okunan anda (TIMELINE) ya da namaz
    dışı kayıtta yanlış alarm 0 olmalı; yakalanan sinyal sayısı düşerse kaçırma.
  - **app** — `server/app.py` = referans state machine (Flask taklitli, parça parça, gerçek + dış kayıtlar; fark 0 olmalı).
  - **kotlin** — `tests/jvm` uygulamanın kendi kaynaklarını derler: Fuzzy / Aligner / StateMachine fixture'ları, Kotlin = Python
    karar izi (gerçek + sentetik + dış kayıtlar + bileşikler + S1/S3; belirsiz aday `?` ile), `RakatTracker` / `EzanTracker` /
    `ZikirTracker` altın dosyaları (`tests/golden`), zikir kartı Kuran okunurken / tek sureli kayıtta (`zikir_false_alarms` 0),
    `ChunkBuilder` = `vad_chunker` (tüm WAV'lar, sabit + değişen anahtar), `WavReader` = soundfile (16 kHz mono kayıtlar),
    G2 köprüsü (`glasses`: `glasses_failures` 0), seçilebilir mealler (`meals`: `meals_failures` 0), ses kesilince metin (`hide`: Kotlin StateMachine + VoiceActivity gerçek WAV'la,
    TIMELINE'lı kayıtlarda okuma içinde silme `hide_false` 0, okuma bitince kalkmayan `hide_missing` 0, gecikme medyanı / en çok).
  - **g2** — G2 eklentisinin ekran düzeni (`tests/g2/layout.test.mjs`, node): satır kırma, sayfalar, kutu boyutları; CI'da
    gerçek `meal.bin` ile tüm mealler (her satır kutuya sığmalı, sayfa ≤ 999 bayt; fontta olmayan karakter sayısı
    `dropped_chars` ↓); `asr/meals/index.tsv` varsa seçilebilir mealler de (`g2_meal_editions` ↑). `g2_failures` 0 olmalı.
  - Ayrı job **g2sim** (tests.yml): `tests/g2/sim_check.py` Even Hub simülatöründe (Xvfb) uygulamanın köprüsüyle 52 adım,
    geliştirici + `.ehpk` (CORS, kod köprüden `boot.js`) + engellenmiş fetch (doğrudan geçiş) + geç açılan köprü (`gec`, `gec-fetch`) modu; ekran görüntüleri artifact `g2-simulator`. Yerelde: simülatör ikilisi
    `npm pack @evenrealities/sim-linux-x64@0.9.5`, `apt install libwebkit2gtk-4.1-0 xvfb`, `tests/jvm` installDist.
- Her metrik `tests/baseline.json` ile karşılaştırılır (yön: kilit ↑, gecikme / yanlış ↓; birebirlik / fixture / altın dosya
  farkı **0** olmalı). Kötüleşen varsa çıkış 1, rapor run özetinde. Bilerek yapılan iyileştirmeden sonra
  `python tests/gate.py --update-baseline` (altın dosyaları da yazar) ve commit.
- Yerelde: `TILAVET_ALIGN_CACHE=/tmp/align.pkl python tests/gate.py --assets android-assets-staged` (hizalama önbelleği
  tekrarları dakikalardan saniyelere indirir; CI'da `actions/cache`, anahtar `aligner.py`). JVM için `gradle` 8.7 + JDK 17
  (`--offline` yerelde). Hızlı tur: `--suites replay,signals,app --seeds 2`.
- Yeni gerçek kayıt: eval'in log'undaki `TRJSON` satırlarını `tests/trjson/<model>.trjson`'a ekle (+ `EXPECTED` / `TIMELINE`),
  `--update-baseline`.
- Dikkat: yereldeki Kuran korpusu kopyası (`~/.cache/quran-align`, alquran.cloud yerelden kapalı → tanzil haritasından kurulmuş,
  77881 kelime) CI'dakinden (alquran.cloud, 77878 kelime) birkaç kelime farklı. Gerçek transkriptlerde sonuçlar aynı çıkıyor;
  S4 gürültüsünün kelime listesi bu yüzden korpustan değil transkriptlerden (ilk CI koşusunda S4 ±1-3 farklıydı). Baseline'da
  fark çıkarsa CI sonucuna (`--results` / run özeti) göre güncelle. `rapidfuzz` sürümü sabit (3.14.6).

### Offline değerlendirme (telefonsuz kalibrasyon)
`.github/workflows/eval.yml` → `scripts/eval_pipeline.py`: repodaki kayıtları (`data/*.wav`,
`server/recordings/*.wav`, ~24 dk) telefondaki zincirle işler: 5sn+1sn chunk → APK'daki CTC ONNX →
`align_transcription` (preferred yok, windowSlack=2) → `score_transcription`. Eski/yeni chunk ×
Uthmani/imla'i tablosu + dosya bazında eşleşen sureler run özetinde. `scripts/**` değişince veya elle çalışır (~10 dk;
kayıtlar özel repodan `tools/kayitlari_cek.sh`). Yeni kayıt eklemek = WAV'ı özel reponun `data/`'sına koyup (public repoda
`EXPECTED`'e beklenen sureyi yazıp) eval'i elle (`audio` girdisiyle) çalıştırmak.

**Namaz simülasyonu:** her kayıt referans state machine'den (`build_state_machine_fixture.process_chunk_simulated`,
ilk kilit eşiği 70) chunk chunk geçer → "ilk kilit" tablosu (kaçıncı sn, doğru sure mi). Log'da
`[sim <config>] <dosya>: 0:P1:2(95) 1:M1:3(100)` izi (P aday, M kilit, L düşük, S kısa, - sessiz/boş).
Log sonunda `TRJSON {...}` satırları: her config/dosya için `(rms, metin)` — state machine
deneyleri ASR'siz, yerelde tekrar oynatılabilir.

**Zincirler:** `guncel` (CTC, sabit 5 sn), `rnnt` (RNNT, sabit 5 sn — APK #6-10), `rnnt-hibrit` (RNNT,
kilitliyken duraklamada kes — APK #14+; parça sınırları state'e bağlı olduğu için state machine ASR
döngüsünde çalışır). `rnnt-vad` (her yerde duraklama kesimi, APK #11-13) artık ölçülmüyor. TRJSON: `[rms, metin, bitiş_sn, duraklama_kesimi, son_kelime_sn, ctc_metni]`
(ctc_metni: RNNT zincirlerinde aynı encoder çıktısının CTC çözümü — tanı için)
(son kelime = son RNNT/CTC token'ının frame'i × 80 ms); simülasyonlar parça bitiş zamanlarını kullanır.
**Hız ve ön-kaydırma tablosu:** son kelime → ekran (bitiş + 1 sn işlem − son token), duraklama kesimi
oranı, ön-kaydırma sayısı / isabet (sonraki eşleşme o ayette) / geri dönen, ayet sonu → sonraki ayet.

**Kelime zamanlı transkript** (`--words`, eval.yml elle çalıştırmada `words` ✓, `audio` ile): 12 sn pencere / 6 sn
kaydırma RNNT, her kelimenin zamanı (ilk token'ı, 80 ms) → `[kelime] 96.32 الهاكم` satırları + `WORDS {...}` json.
Yeni kaydın TIMELINE'ı ve imamın ayete başladığı an (gecikme ölçümü) buradan. Yereldeki model kopyaları deneme
export'ları (80 MB, çıktı boş) — gerçek ASR sadece CI'da (repo özel, release asset'i yerelden inmiyor).

**Takip simülasyonu:** kayıt baştan sona state machine'den geçer; `TIMELINE` (çok sureli kayıtlar:
`[(başlangıç_sn, sure|None), ...]`, tek sureliler otomatik) ile her sure bölümü için kilit/aday
gecikmesi, kaçan bölüm ve **yanlış kilitli chunk** sayılır. Gerçek namaz / ardışık sure kaydı eklemek:
WAV'ı `data/`'ya koy, `EXPECTED`'e `"coklu"`, `TIMELINE`'a zaman çizelgesini yaz.

## Debug ipuçları

```bash
adb logcat -c
adb logcat -s AudioPipeline:* Aligner:* QuranIndex:* MainViewModel:* AndroidRuntime:E *:F
```

Log'da kritik satırlar:
- `AudioPipeline: Pipeline basliyor — tuner: minConf=X.X minConfFirstLock=X.X windowSlack=X`
- `[chunk N] STATE_BEFORE→STATE_AFTER status score=X.X dec=RNNT | verses [gerekçe] (parca=dur 3.2s rms=X asr=Xms sm=Xms
  gecikme=Xms t=Xs) txt='...'` — gerekçe: kabul/red nedeni + pencere, geçiş araması, ikinci yer farkı (bkz. açık sorun 12)
- `MainViewModel: [rekat] t=203.6s 2. rekat (Fatiha)` — rekât sayacı olayları
- `MainViewModel: [g2] eklenti baglandi` — G2 gözlük köprüsü (bkz. "Even Realities G2 gözlük")
- `Aligner:   candidate=X, min_hits=X`
- `Aligner: align: n=X, candidates=X, windows=X, max_combos=X`
- `Aligner: align bitti Xms, best=X.X @ Y-Z`

Ya da uygulama içinden 📤 (Log Export) ile logcat dosyaya yazılıp Drive/mail ile paylaşılabilir (kablosuz debug).

---

## Sonraki adımlar (roadmap)

1. **Canlı test (Mushaf APK)** — ilk kilit süresi, `align bitti Xms`, `asr=`/`sm=` süreleri;
   📤 ile log + WAV → özel reponun `data/`'sına eklenip eval'e girsin (farklı okuyucular).
2. **Daha çok gerçek namaz kaydı** (iki akşam + bir cuma eklendi: açık sorun 7, 9, 10) — farklı imam/cami akustiği,
   4 rekâtlı (yatsı: 3-4. rekât sessiz), cuma/bayram (uzun zamm), teravih (ardışık sureler). WAV'ı
   özel reponun `data/`'sına koy, `EXPECTED`'e `"coklu"`, TIMELINE'ı ilk eval transkriptinden (`audio` girdisiyle hızlı).
3. **Daha da hızlı** (opsiyonel, eval ile): duraklama eşiklerini gerçek cami kaydıyla ayarla (yankı
   duraklamayı maskeleyebilir; BEKLEME'de duraklama kesimi yanlış kilit üretti — bkz. açık sorun 6); kilitliyken 2.5 sn'de bir kısa "takip yoklaması" (sadece mevcut ayet
   penceresinde hizalama) → uzun ayetlerde de vurgu akıcı. Kayan pencere (üst üste binen parçalar)
   pending doğrulamasını zayıflatır — dikkat. Mikrofon filtresi (80 Hz yüksek geçiren + 6 kHz alçak geçiren, bkz. açık
   sorun 12) ayrı eval zinciriyle denenebilir. Ayet düzeyinde doğruluk için EveryAyah'tan birleştirilmiş, ayet sınırları
   bilinen kayıtlar (bkz. açık sorun 13).
4. **UI polish**: sure sonu animasyonu, ayet menüsü (⋮), sayfa/cüz bilgisi (Zümrüt teması APK #30'da geldi)
5. **APK boyutunu düşür** — mümkünse INT8 quantization ONNX modeli (opsiyonel)

---

## Yerel kopya konumları (WSL)

- `~/projects/quran-asr/` — proje kökü (ses kayıtları: `bash tools/kayitlari_cek.sh`)
- `~/projects/quran-asr/venv/` — Python venv (ignore)
- `~/projects/quran-asr/onnx/` — ONNX export çıktıları (ignore, ~400MB)
- `<repo>/android-assets-staged/asr/` — Gradle'ın okuduğu asset staging (ignore, `TILAVET_ASSETS_DIR` ile değişir)
- `~/.cache/quran-align/` — Kuran text + meal + surah names JSON'ları (indirilir)

## User workflow tercihi

- **Yeni kod verirken tam dosya ver**, patch değil
- **Küçük iteratif değişiklikler tercih et**, tek büyük refactor değil
- **Build sayısını azalt** — canlı reload'a yatırım yapıldı (tuner slider'ları)
- Kod içi yorumları **Türkçe** yaz (mixed-latin OK, normalize etmeye gerek yok)
- Türkçe konuş, teknik terimleri İngilizce bırak
- **Log export**'a öncelik ver — kullanıcı kablo bağlamak istemiyor
