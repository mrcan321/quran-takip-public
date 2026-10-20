plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// ASR modeli + quran.bin/meal.bin + test fixture'lari git'te degil, build oncesi uretilir
// (CI: .github/workflows/android.yml, elle: scripts/*.py). Hepsi <assetsDir>/asr/ altinda olmali.
// TILAVET_ASSETS_DIR verilmisse orasi, yoksa repo kokundeki android-assets-staged/ (gitignore'da).
val tilavetAssetsDir: String = System.getenv("TILAVET_ASSETS_DIR")
    ?: rootProject.file("../android-assets-staged").absolutePath

// CI'da her build'in versionCode'u artar (GitHub Actions run numarasi) — ustune kurulum sorunsuz olsun.
val ciBuildNumber: Int? = System.getenv("GITHUB_RUN_NUMBER")?.toIntOrNull()
// Ekranin durum satirinda gosterilen commit (hangi kod test ediliyor): CI'da GITHUB_SHA, yerelde "yerel"
val gitShortSha: String = System.getenv("GITHUB_SHA")?.take(7) ?: "yerel"

android {
    namespace = "com.tilavet.takip"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.tilavet.takip"
        minSdk = 28
        targetSdk = 34
        versionCode = ciBuildNumber ?: 2
        versionName = if (ciBuildNumber != null) "0.2.0-ci$ciBuildNumber" else "0.2.0"
        buildConfigField("String", "GIT_SHA", "\"$gitShortSha\"")
        buildConfigField("int", "CI_BUILD", "${ciBuildNumber ?: 0}")

        // Sadece arm64-v8a — modern telefonlar (Galaxy A34 5G dahil).
        // Bu APK boyutunu ~%50 dusurur (x86_64 ve armv7 atlanir).
        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }

    signingConfigs {
        // Repodaki sabit debug keystore: her makinede/CI calismasinda ayni imza,
        // boylece yeni APK eskisinin ustune kurulur (uninstall + 445 MB model kopyasi gerekmez).
        getByName("debug") {
            storeFile = file("debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    sourceSets {
        getByName("main") {
            // ASR asset'leri proje disindaki bir klasorden geliyor (bkz. tilavetAssetsDir).
            // Bu sayede repo agirligi artmiyor (~450 MB model).
            //
            // Hem proje icindeki assets/ hem de bu external dizin kullanilir.
            assets.srcDirs(
                "src/main/assets",
                tilavetAssetsDir,
            )
        }
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfig = signingConfigs.getByName("debug")
        }
        getByName("debug") {
            isDebuggable = true
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.14"
    }

    androidResources {
        // ONNX dosyalarini sikistirma — APK icinden direkt mmap edilebilsin
        noCompress += listOf("onnx", "data", "model")
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
        // ONNX runtime native lib'leri sikistirma — extractNativeLibs=false ile uyumlu
        jniLibs {
            useLegacyPackaging = false
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.09.02")
    implementation(composeBom)

    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.4")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.4")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.4")
    implementation("androidx.activity:activity-compose:1.9.1")

    // Compose
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.ui:ui-text-google-fonts")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.foundation:foundation")

    // DataStore for settings
    implementation("androidx.datastore:datastore-preferences:1.1.1")

    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    // ONNX Runtime — full Android paketi (mobile degil; bizim modelimiz STFT vs.icerir)
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.18.0")

    // Debug
    debugImplementation("androidx.compose.ui:ui-tooling")
}
