#!/usr/bin/env bash
set -e

# ============================================================
# Tilavet Takip — APK Build Script
# Tek komutla derler ve APK'yi cikti olarak verir.
#
# Kullanim:
#   ./build_apk.sh              # Debug APK
#   ./build_apk.sh release      # Unsigned release APK
#
# Ilk calistirmada otomatik:
#  - Gradle 8.7 indirir (~127 MB) → $HOME/.gradle-tilavet/
#  - Sonraki build'lerde indirme yok, hizli
# ============================================================

cd "$(dirname "$0")"
ROOT="$(pwd)"

BUILD_TYPE="${1:-debug}"

GRADLE_VERSION="8.7"
GRADLE_HOME="$HOME/.gradle-tilavet/gradle-${GRADLE_VERSION}"
GRADLE_BIN="$GRADLE_HOME/bin/gradle"
DIST_URL="https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip"
EXPECTED_DIST_SHA256="544c35d6bd849ae8a5ed0bcea39ba677dc40f49df7d1835561582da2009b961d"

echo "=================================================="
echo "  Tilavet Takip APK Build"
echo "  Type: $BUILD_TYPE"
echo "=================================================="
echo ""

# ============================================================
# Java kontrol
# ============================================================
if ! command -v java >/dev/null 2>&1; then
    echo "HATA: Java bulunamadi."
    echo "Kurmak icin: sudo apt install openjdk-17-jdk-headless"
    exit 1
fi

JAVA_VERSION=$(java -version 2>&1 | head -n1 | awk -F '"' '{print $2}' | cut -d. -f1)
if [ "$JAVA_VERSION" -lt 17 ]; then
    echo "HATA: Java 17 gerekli (mevcut: $JAVA_VERSION)"
    echo "Kurmak icin: sudo apt install openjdk-17-jdk-headless"
    echo "Sonra varsayilan yapmak icin: sudo update-alternatives --config java"
    exit 1
fi
echo "[OK] Java $JAVA_VERSION mevcut"

# ============================================================
# Android SDK kontrol
# ============================================================
if [ -z "${ANDROID_HOME:-}" ] && [ -z "${ANDROID_SDK_ROOT:-}" ]; then
    DEFAULT_SDK="$HOME/Android/Sdk"
    if [ -d "$DEFAULT_SDK" ]; then
        export ANDROID_HOME="$DEFAULT_SDK"
        echo "[OK] Android SDK bulundu: $DEFAULT_SDK"
    else
        echo ""
        echo "Android SDK bulunamadi."
        echo "Kurmak icin: ./setup_android_sdk.sh"
        exit 1
    fi
else
    [ -n "${ANDROID_HOME:-}" ] || export ANDROID_HOME="$ANDROID_SDK_ROOT"
    echo "[OK] ANDROID_HOME: $ANDROID_HOME"
fi

if [ ! -d "$ANDROID_HOME/platforms/android-34" ] || [ ! -d "$ANDROID_HOME/build-tools" ]; then
    echo "HATA: SDK bilesenleri eksik (platforms;android-34 ve/veya build-tools)"
    echo "Kurmak icin: ./setup_android_sdk.sh"
    exit 1
fi

# ============================================================
# Gradle kurulu mu? Yoksa indir
# ============================================================
if [ ! -x "$GRADLE_BIN" ]; then
    echo ""
    echo "[INFO] Gradle ${GRADLE_VERSION} kurulu degil — indiriliyor..."
    echo "       Hedef: $GRADLE_HOME"
    echo ""

    if ! command -v unzip >/dev/null 2>&1; then
        echo "HATA: unzip yuklu degil. Kurmak icin: sudo apt install unzip"
        exit 1
    fi
    if ! command -v wget >/dev/null 2>&1 && ! command -v curl >/dev/null 2>&1; then
        echo "HATA: wget veya curl yuklu degil. Kurmak icin: sudo apt install wget"
        exit 1
    fi

    mkdir -p "$HOME/.gradle-tilavet"
    DIST_ZIP="$HOME/.gradle-tilavet/gradle-${GRADLE_VERSION}-bin.zip"

    if [ ! -f "$DIST_ZIP" ]; then
        echo "Gradle ${GRADLE_VERSION} distribution indiriliyor (~127 MB)..."
        if command -v wget >/dev/null 2>&1; then
            wget -q --show-progress -O "$DIST_ZIP" "$DIST_URL"
        else
            curl -fL -# -o "$DIST_ZIP" "$DIST_URL"
        fi
    else
        echo "[OK] Distro zip zaten indirilmis: $DIST_ZIP"
    fi

    # Checksum dogrula
    if command -v sha256sum >/dev/null 2>&1; then
        ACTUAL=$(sha256sum "$DIST_ZIP" | awk '{print $1}')
        if [ "$ACTUAL" != "$EXPECTED_DIST_SHA256" ]; then
            echo "UYARI: SHA256 dogrulamasi basarisiz, devam ediliyor."
            echo "  Beklenen: $EXPECTED_DIST_SHA256"
            echo "  Gelen:    $ACTUAL"
        else
            echo "[OK] SHA256 dogrulandi"
        fi
    fi

    echo "Cikartiliyor..."
    unzip -q -o "$DIST_ZIP" -d "$HOME/.gradle-tilavet"

    if [ ! -x "$GRADLE_BIN" ]; then
        echo "HATA: Gradle binary bulunamadi: $GRADLE_BIN"
        exit 1
    fi

    rm -f "$DIST_ZIP"  # zip artik gerek yok, distro cikartildi
    echo "[OK] Gradle ${GRADLE_VERSION} kuruldu: $GRADLE_HOME"
fi

echo "[OK] Gradle: $GRADLE_BIN"

# ============================================================
# Build
# ============================================================
echo ""
echo "=================================================="
echo "  Gradle build basliyor..."
echo "=================================================="

if [ "$BUILD_TYPE" = "release" ]; then
    "$GRADLE_BIN" assembleRelease
    APK_PATH="$ROOT/app/build/outputs/apk/release/app-release.apk"
    if [ ! -f "$APK_PATH" ]; then
        APK_PATH="$ROOT/app/build/outputs/apk/release/app-release-unsigned.apk"
    fi
else
    "$GRADLE_BIN" assembleDebug
    APK_PATH="$ROOT/app/build/outputs/apk/debug/app-debug.apk"
fi

# ============================================================
# Output
# ============================================================
if [ -f "$APK_PATH" ]; then
    OUT_DIR="$ROOT/output"
    mkdir -p "$OUT_DIR"
    OUT_FILE="$OUT_DIR/tilavet-takip-$BUILD_TYPE.apk"
    cp "$APK_PATH" "$OUT_FILE"

    echo ""
    echo "=================================================="
    echo "  BAŞARILI"
    echo "=================================================="
    echo "  APK: $OUT_FILE"
    echo "  Boyut: $(du -h "$OUT_FILE" | cut -f1)"
    echo ""
    echo "Telefona yuklemek icin:"
    echo "  adb install -r '$OUT_FILE'"
    echo "  veya APK'yi telefona kopyalayip dokunarak kurun."
    echo "=================================================="
else
    echo ""
    echo "HATA: APK uretilemedi"
    exit 1
fi
