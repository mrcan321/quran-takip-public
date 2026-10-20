# Tilavet Takip — Android (Faz 1: Mock APK)

Namaz sırasında imamı takip edip okunan ayetin Türkçe mealini anında ekrana getiren Android uygulaması.

**Bu sürüm Faz 1: Mock APK.** Gerçek ASR (FastConformer) henüz entegre değil — UI mock data ile çalışıyor (Tevbe Suresi 9:1-7 sırayla otomatik gelir). Mikrofon izni ve gerçek ses kaydı çalışıyor (sadece görsel level bar için kullanılıyor şu an).

## Hızlı başlangıç (Ubuntu)

```bash
# 1. Sistem paketleri (yoksa)
sudo apt update
sudo apt install -y openjdk-17-jdk-headless unzip wget

# 2. Android SDK (~3-4 GB indirir, tek seferlik)
./setup_android_sdk.sh

# 3. APK derle (Gradle yoksa otomatik indirir, ~127 MB tek seferlik)
./build_apk.sh
```

Sonraki seferler sadece:

```bash
./build_apk.sh
```

Çıktı: `output/tilavet-takip-debug.apk`

## Nasıl çalışıyor?

Wrapper script (`gradlew`) **kullanılmıyor**. `build_apk.sh` ilk çalıştırıldığında:

1. Gradle 8.7 dağıtımını `$HOME/.gradle-tilavet/` klasörüne indirir (tek seferlik, ~127 MB)
2. Sonraki build'lerde direkt o gradle binary'sini kullanır (indirme yok)

İlk build 5-10 dakika sürer (Compose dependencies de indirilir). Sonraki build'ler 30-60 saniye.

## Telefona yükleme

```bash
# USB ile (USB debugging açık olmalı)
adb install -r output/tilavet-takip-debug.apk

# Veya APK'yi telefona kopyalayıp dokunarak kurun
# (Ayarlar → "Bilinmeyen kaynaklar" izinli olmalı)
```

## Proje yapısı

```
tilavet-android/
├── app/                          # Asıl uygulama modülü
│   ├── build.gradle.kts          # App-level Gradle config
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── java/com/tilavet/takip/
│       │   ├── MainActivity.kt           # Entry point
│       │   ├── MainViewModel.kt          # UI state + mock pipeline
│       │   ├── audio/
│       │   │   └── AudioRecorder.kt      # 16kHz PCM kayıt
│       │   ├── data/
│       │   │   ├── Verse.kt              # Ayet data class
│       │   │   ├── MockVerses.kt         # Tevbe 9:1-7 test data
│       │   │   └── SettingsRepository.kt # DataStore tabanlı ayarlar
│       │   └── ui/
│       │       ├── theme/                # 7 tema, fonts
│       │       ├── components/           # VerseCard, MicButton, vb.
│       │       └── screens/MainScreen.kt
│       └── res/                          # Resources
├── build.gradle.kts              # Root Gradle config
├── settings.gradle.kts
├── gradle.properties
├── build_apk.sh                  # Tek komut APK build
├── setup_android_sdk.sh          # SDK otomatik kurulum
└── README.md
```

## Özellikler (Faz 1)

- ✅ Tasarım: liste/scroll, ortalanmış aktif ayet, üstte/altta context
- ✅ 7 tema: Karanlık, Gece, Mürekkep, Gündüz, Sefa, Yeşim, Bordo
- ✅ Ayar paneli (alttan kayan bottom sheet)
  - Tema seçici (4 sütunlu grid)
  - Arapça yazı boyutu slider (18-44 px)
  - Türkçe meal boyutu slider (14-32 px)
  - Animasyon yoğunluğu (Yok / Az / Tam)
  - Eski ayet solukluğu (0-80%)
- ✅ Ayarlar kalıcı (DataStore preferences)
- ✅ Mikrofon izni + gerçek ses level animasyonu
- ✅ Mock pipeline: Tevbe 9:1-7 sırayla 5sn aralıkla
- ✅ Edge-to-edge ekran (status bar transparent)
- ✅ Türkçe lokalize UI

## Bilinen kısıtlar (Faz 1)

- ❌ Gerçek ASR yok — mock data sabit. Mikrofon tuşuna basınca Tevbe 9:1-7 otomatik gelir, ne okunduğu önemli değil.
- ❌ Sadece Tevbe 9:1-7 örneği var (test için yeterli).
- ❌ Ayet birleştirme yok (ardışık aynı meal'li ayetler ayrı kartlarda).

Bunlar Faz 2-3'te eklenecek.

## Sonraki adımlar (Faz 2)

- `aligner.py` → Kotlin'e port (~300 satır)
- NeMo FastConformer encoder → ONNX export (PoC)
- ONNX Runtime Mobile entegrasyonu
- Streaming pipeline + ardışık iki match state machine
- Gerçek mikrofon → ASR pipeline bağlantısı

## Sorun giderme

### "Java 17 gerekli" hatası
```bash
sudo apt install openjdk-17-jdk-headless
sudo update-alternatives --config java   # 17'yi varsayilan yap
```

### "ANDROID_HOME tanımlı değil" hatası
```bash
./setup_android_sdk.sh
echo 'export ANDROID_HOME=$HOME/Android/Sdk' >> ~/.bashrc
echo 'export PATH=$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH' >> ~/.bashrc
source ~/.bashrc
```

### Gradle indirme yarıda kesildi
```bash
# Yarıda kalmış zip'i sil ve tekrar dene
rm -f $HOME/.gradle-tilavet/gradle-8.7-bin.zip
./build_apk.sh
```

### "Out of memory" hatası
`gradle.properties` içindeki `org.gradle.jvmargs=-Xmx2048m` değerini `-Xmx4096m` yapın.

### Build çok yavaş
İlk build'de Compose bağımlılıkları (~150 MB) indirilir, normalde 5-10 dakika. Sonraki build'ler için Gradle daemon arka planda kalır, ikinci build çok hızlıdır.

### Telefonda "uygulama yüklenemedi"
- Geliştirici seçenekleri açık olmalı
- USB debugging veya "Bilinmeyen kaynaklar" izinli olmalı
- Eski sürüm yüklüyse: `adb uninstall com.tilavet.takip`

### Tamamen sıfırdan başlamak
```bash
rm -rf ~/.gradle-tilavet ~/.gradle
rm -rf app/build
./build_apk.sh
```

## Gereksinimler

- **OS:** Linux (Ubuntu/Debian/WSL2 test edildi)
- **Java:** OpenJDK 17 (sadece bu sürüm; 11 veya 21 ile çalışmaz)
- **Disk:** ~5 GB (SDK + Gradle + bağımlılıklar)
- **RAM:** En az 4 GB (ilk build için 8 GB önerilir)
- **İnternet:** İlk seferde gerekli

## Hedef cihaz

- **Min Android:** 9 (Pie / API 28)
- **Hedef Android:** 14 (API 34)
- **Mimari:** ARM64 + ARMv7 + x86_64

## Lisans

Kişisel/aile kullanımı için.
