package com.tilavet.takip.data

import android.util.Log
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.MappedByteBuffer
import java.nio.channels.FileChannel

/**
 * meal.bin reader — Türkçe meal + Arapça/Türkçe sure isimleri.
 *
 * Format (build_quran_assets.py):
 *   Header (16 byte): "MEAL" + version u32 + meal_count u32 + surah_count u32
 *   Meal entries (sirali, surah:ayah artiyor):
 *     surah u16, ayah u16, text_len u16, text_utf8 bytes
 *   Surah entries (surah_no artiyor):
 *     surah_no u16, name_tr_len u8, name_tr bytes,
 *     name_ar_len u8, name_ar bytes, ayah_count u16
 *
 * Hizli erisim: ilk yuklemede (surah, ayah) -> meal_text tum mealleri,
 * surah_no -> SurahInfo tum sureleri parse edip HashMap'e koyar.
 * Bellek tuketimi: ~1 MB (meal stringleri zaten utf-8'le compact).
 */
class MealLoader private constructor(
    private val raf: RandomAccessFile,
    private val mmap: MappedByteBuffer,
    val mealCount: Int,
    val surahCount: Int,
    private val mealMap: HashMap<Long, String>,    // (surah shl 16 | ayah) -> meal
    private val surahMap: HashMap<Int, SurahInfo>, // surah -> info
) {
    companion object {
        private const val TAG = "MealLoader"
        private const val MAGIC = "MEAL"

        fun load(mealBinPath: String): MealLoader {
            val t0 = System.nanoTime()

            val raf = RandomAccessFile(mealBinPath, "r")
            val channel = raf.channel
            val mmap = channel.map(FileChannel.MapMode.READ_ONLY, 0L, channel.size())
            mmap.order(ByteOrder.LITTLE_ENDIAN)

            // Header
            val magicBytes = ByteArray(4)
            mmap.get(magicBytes)
            val magic = String(magicBytes)
            require(magic == MAGIC) { "Yanlis magic: '$magic' (beklenen '$MAGIC')" }

            val version = mmap.int
            val mealCount = mmap.int
            val surahCount = mmap.int
            require(version == 1) { "Desteklenmeyen meal.bin versiyonu: $version" }

            // Meal entries
            val mealMap = HashMap<Long, String>(mealCount + 100)
            for (i in 0 until mealCount) {
                val surah = mmap.short.toInt() and 0xFFFF
                val ayah = mmap.short.toInt() and 0xFFFF
                val len = mmap.short.toInt() and 0xFFFF
                val bytes = ByteArray(len)
                mmap.get(bytes)
                val text = String(bytes, Charsets.UTF_8)
                val key = (surah.toLong() shl 16) or ayah.toLong()
                mealMap[key] = text
            }

            // Surah entries
            val surahMap = HashMap<Int, SurahInfo>(surahCount + 10)
            for (i in 0 until surahCount) {
                val surahNo = mmap.short.toInt() and 0xFFFF
                val trLen = mmap.get().toInt() and 0xFF
                val trBytes = ByteArray(trLen)
                mmap.get(trBytes)
                val nameTr = String(trBytes, Charsets.UTF_8)

                val arLen = mmap.get().toInt() and 0xFF
                val arBytes = ByteArray(arLen)
                mmap.get(arBytes)
                val nameAr = String(arBytes, Charsets.UTF_8)

                val ayahCount = mmap.short.toInt() and 0xFFFF

                surahMap[surahNo] = SurahInfo(
                    surah = surahNo, nameTr = nameTr, nameAr = nameAr, ayahCount = ayahCount,
                )
            }

            val ms = (System.nanoTime() - t0) / 1_000_000L
            Log.d(TAG, "Yuklendi: $mealCount meal, $surahCount sure (${ms}ms)")

            return MealLoader(raf, mmap, mealCount, surahCount, mealMap, surahMap)
        }
    }

    /** Bir ayetin Türkçe mealini getir. Bulunamazsa null. */
    fun getMeal(surah: Int, ayah: Int): String? {
        val key = (surah.toLong() shl 16) or ayah.toLong()
        return mealMap[key]
    }

    /** Bir surenin bilgisini getir. Bulunamazsa null. */
    fun getSurahInfo(surah: Int): SurahInfo? = surahMap[surah]

    fun close() {
        try {
            raf.close()
        } catch (e: Throwable) {
            Log.e(TAG, "close hatasi", e)
        }
    }

    data class SurahInfo(
        val surah: Int,
        val nameTr: String,
        val nameAr: String,
        val ayahCount: Int,
    )
}
