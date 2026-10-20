#!/usr/bin/env bash
set -e

# ============================================================
# Android SDK Otomatik Kurulum (Ubuntu)
# ============================================================
# Indirir: command-line tools, SDK platform 34, build-tools 34
# Konum: ~/Android/Sdk
# Lisans: -y ile otomatik kabul
# ============================================================

SDK_ROOT="${ANDROID_HOME:-$HOME/Android/Sdk}"
CMDLINE_TOOLS_VERSION="11076708"  # latest stable as of 2024
CMDLINE_TOOLS_URL="https://dl.google.com/android/repository/commandlinetools-linux-${CMDLINE_TOOLS_VERSION}_latest.zip"

echo "=================================================="
echo "  Android SDK Kurulumu"
echo "=================================================="
echo "Hedef: $SDK_ROOT"
echo ""

mkdir -p "$SDK_ROOT/cmdline-tools"

# Java kontrol
if ! command -v java >/dev/null 2>&1; then
    echo "HATA: Java yuklu degil."
    echo "Once kurun: sudo apt install openjdk-17-jdk-headless"
    exit 1
fi

# wget veya curl gerekli
if ! command -v wget >/dev/null 2>&1 && ! command -v curl >/dev/null 2>&1; then
    echo "HATA: wget veya curl yuklu degil."
    echo "Kurmak icin: sudo apt install wget"
    exit 1
fi

# Cmdline tools indir
TMP_ZIP="/tmp/android-cmdline-tools.zip"
echo "[1/4] Cmdline tools indiriliyor..."
if command -v wget >/dev/null 2>&1; then
    wget -q --show-progress -O "$TMP_ZIP" "$CMDLINE_TOOLS_URL"
else
    curl -L -o "$TMP_ZIP" "$CMDLINE_TOOLS_URL"
fi

# unzip kontrol
if ! command -v unzip >/dev/null 2>&1; then
    echo "HATA: unzip yuklu degil."
    echo "Kurmak icin: sudo apt install unzip"
    exit 1
fi

echo "[2/4] Cmdline tools cikartiliyor..."
unzip -q -o "$TMP_ZIP" -d "/tmp/android-cmdline-tools-extracted"
mkdir -p "$SDK_ROOT/cmdline-tools/latest"
# Klasor yapisi: cmdline-tools/latest/bin/...
cp -r /tmp/android-cmdline-tools-extracted/cmdline-tools/* "$SDK_ROOT/cmdline-tools/latest/"
rm -rf /tmp/android-cmdline-tools-extracted "$TMP_ZIP"

# Path
export ANDROID_HOME="$SDK_ROOT"
export PATH="$SDK_ROOT/cmdline-tools/latest/bin:$SDK_ROOT/platform-tools:$PATH"

# Lisanslari kabul et
echo "[3/4] SDK lisanslari kabul ediliyor..."
yes | "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" --licenses >/dev/null 2>&1 || true

# Bilesenleri kur
echo "[4/4] SDK bilesenleri kuruluyor (platform 34 + build-tools 34 + platform-tools)..."
"$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" \
    "platforms;android-34" \
    "build-tools;34.0.0" \
    "platform-tools" \
    >/dev/null

echo ""
echo "=================================================="
echo "  KURULUM TAMAMLANDI"
echo "=================================================="
echo "Konum: $SDK_ROOT"
echo ""
echo "Kalici tanim icin ~/.bashrc'ye ekleyin:"
echo "  export ANDROID_HOME=$SDK_ROOT"
echo "  export PATH=\$ANDROID_HOME/cmdline-tools/latest/bin:\$ANDROID_HOME/platform-tools:\$PATH"
echo ""
echo "Sonra ./build_apk.sh ile APK uretebilirsiniz."
