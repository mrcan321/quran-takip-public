package com.tilavet.takip.util

import android.content.Context
import android.util.Log
import java.io.File
import java.io.FileNotFoundException
import java.io.FileOutputStream
import java.io.IOException

/**
 * APK assets/asr/ → filesDir/asr/ senkronu.
 *
 * ONNX Runtime modeli ve QuranIndex/MealLoader dosyalari dosya yolundan (mmap) okur, bu yuzden
 * asset'ler internal storage'a kopyalanir. ESKI HATA: "dosya varsa kopyalama" mantigi yeni APK'daki
 * degisiklikleri hic almiyordu (yeni model, imla'i quran.bin ...).
 *
 * Kural:
 *   - APK surumu (versionCode + lastUpdateTime) degismediyse hicbir sey yapma (hizli yol).
 *   - Model dosyalari (~440 MB): sadece meta.json degistiyse (yeni export) yeniden kopyala.
 *     APK'da olmayan model dosyasi (orn. eski surumde rnnt_*.onnx yok) silinir.
 *   - Kucuk veri dosyalari (quran.bin, meal.bin): her yeni APK surumunde yeniden kopyala.
 *   - Secilebilir mealler (assets/asr/meals/: index.tsv + <id>.bin, scripts/build_meals.py): her yeni APK surumunde
 *     yeniden kopyala; APK'da olmayan eski meal dosyasi silinir.
 *   - meta.json ve surum damgasi EN SON yazilir: kopya yarida kalirsa sonraki acilista tekrarlanir.
 *   - Her kopya once .tmp'ye yazilip rename edilir (yarim dosya kalmaz).
 */
object AssetSync {

    private const val TAG = "AssetSync"
    private const val DIR = "asr"
    private const val META = "meta.json"
    private const val MEALS = "meals"
    private const val STAMP = ".asset_version"

    private val MODEL_FILES = listOf(
        "fastconformer_full.onnx",
        "fastconformer_full.onnx.data",   // ONNX graph icinde bu isimle yazili — degistirme
        "tokenizer.model",
        "rnnt_decoder.onnx",
        "rnnt_joint.onnx",
    )
    private val DATA_FILES = listOf("quran.bin", "meal.bin")

    /** Senkronu yap (gerekiyorsa) ve filesDir/asr klasorunu don. Thread-safe, idempotent. */
    @Synchronized
    fun sync(context: Context): File {
        val dir = File(context.filesDir, DIR).apply { mkdirs() }
        val version = appVersion(context)
        val stamp = File(dir, STAMP)
        val oldVersion = if (stamp.exists()) stamp.readText().trim() else null
        if (oldVersion == version) return dir

        Log.i(TAG, "Asset senkronu: APK $version (onceki: ${oldVersion ?: "-"})")
        val t0 = System.nanoTime()

        val newMeta = context.assets.open("$DIR/$META").use { it.readBytes() }
        val metaFile = File(dir, META)
        val modelChanged = !metaFile.exists() || !metaFile.readBytes().contentEquals(newMeta)
        if (modelChanged) Log.i(TAG, "  meta.json degismis → model dosyalari yeniden kopyalanacak")

        for (name in MODEL_FILES) {
            val dst = File(dir, name)
            if (!assetExists(context, name)) {
                if (dst.exists()) {
                    dst.delete()
                    Log.i(TAG, "  $name APK'da yok, eski kopya silindi")
                }
                continue
            }
            if (modelChanged || !dst.exists() || dst.length() == 0L) copy(context, name, dst)
        }
        metaFile.writeBytes(newMeta)

        for (name in DATA_FILES) {
            if (assetExists(context, name)) copy(context, name, File(dir, name))
        }
        syncMeals(context, dir)

        stamp.writeText(version)
        Log.i(TAG, "Asset senkronu bitti (${(System.nanoTime() - t0) / 1_000_000L}ms)")
        return dir
    }

    /** assets/asr/meals/ → filesDir/asr/meals/ (Ayarlar → MEAL). APK'da olmayan dosyalar silinir. */
    private fun syncMeals(context: Context, dir: File) {
        val names = try {
            context.assets.list("$DIR/$MEALS")?.toList().orEmpty()
        } catch (_: IOException) {
            emptyList()
        }
        val dst = File(dir, MEALS).apply { mkdirs() }
        for (name in names) copy(context, "$MEALS/$name", File(dst, name))
        dst.listFiles()?.forEach { f ->
            if (f.name !in names) {
                f.delete()
                Log.i(TAG, "  $MEALS/${f.name} APK'da yok, silindi")
            }
        }
    }

    @Suppress("DEPRECATION")
    private fun appVersion(context: Context): String {
        val pi = context.packageManager.getPackageInfo(context.packageName, 0)
        return "${pi.longVersionCode}-${pi.lastUpdateTime}"
    }

    private fun assetExists(context: Context, name: String): Boolean = try {
        context.assets.open("$DIR/$name").close()
        true
    } catch (_: FileNotFoundException) {
        false
    }

    private fun copy(context: Context, name: String, dst: File) {
        val t0 = System.nanoTime()
        val tmp = File(dst.parentFile, "${dst.name}.tmp")
        context.assets.open("$DIR/$name").use { input ->
            FileOutputStream(tmp).use { output -> input.copyTo(output, 1 shl 16) }
        }
        if (!tmp.renameTo(dst)) {
            dst.delete()
            if (!tmp.renameTo(dst)) throw IOException("$name kopyalanamadi (rename)")
        }
        Log.d(TAG, "  $name kopyalandi: ${dst.length() / 1024} KB (${(System.nanoTime() - t0) / 1_000_000L}ms)")
    }
}
