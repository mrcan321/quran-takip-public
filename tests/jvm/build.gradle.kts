// Uygulamanin Android'siz Kotlin kaynaklarini (aligner, session, glasses, WavReader, ChunkBuilder, MealLoader / MealCatalog + uygulamadaki fixture
// runner'lari) KOPYALAMADAN derleyip JVM'de calistirir — APK oncesi test kapisi (tests/gate.py, android.yml).
// android.util.Log / android.content.Context / AssetManager icin kucuk stub'lar src/main/kotlin/android altinda.
plugins {
    kotlin("jvm") version "1.9.24"
    application
}

repositories { mavenCentral() }

dependencies {
    implementation("org.json:json:20240303")
}

val appSrc = "../../tilavet-android/app/src/main/java"

sourceSets {
    main {
        kotlin {
            srcDir(appSrc)
            include(
                "com/tilavet/takip/aligner/*.kt",
                "com/tilavet/takip/session/*.kt",
                "com/tilavet/takip/glasses/*.kt",
                "com/tilavet/takip/report/*.kt",
                "com/tilavet/takip/audio/WavReader.kt",
                "com/tilavet/takip/audio/ChunkBuilder.kt",
                "com/tilavet/takip/audio/VoiceActivity.kt",
                "com/tilavet/takip/data/MealLoader.kt",
                "com/tilavet/takip/data/MealCatalog.kt",
                "android/**",
                "*.kt",
            )
        }
    }
}

application {
    mainClass.set("JvmTestsKt")
    applicationDefaultJvmArgs = listOf("-Xss16m", "-Dfile.encoding=UTF-8")
}

tasks.named<JavaExec>("run") {
    // Kullanim: gradle run --args="fixtures <assets>" (bkz. JvmTests.kt)
    jvmArgs("-Xss16m", "-Dfile.encoding=UTF-8")
    standardOutput = System.out
}
