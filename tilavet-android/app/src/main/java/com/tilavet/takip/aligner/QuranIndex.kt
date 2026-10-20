package com.tilavet.takip.aligner

import android.util.Log
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.MappedByteBuffer
import java.nio.channels.FileChannel

/**
 * Kuran kelime indeksi — quran.bin reader.
 *
 * Sorumluluklari:
 *   1. quran.bin dosyasını mmap ile aç (RAM'e yükleme yok)
 *   2. Header parse, word records, text section, trigram index
 *   3. Hızlı kelime sorgulama API'si
 *   4. Trigram tabanlı aday pozisyon arama (Python find_candidate_positions ile aynı)
 *
 * Python karşılığı: aligner.py içindeki QuranCorpus sınıfı.
 */
class QuranIndex private constructor(
    private val raf: RandomAccessFile,
    private val mmap: MappedByteBuffer,
    val wordCount: Int,
    val trigramCount: Int,
    private val textOffset: Long,
    private val trigramOffset: Long,
) {

    companion object {
        private const val TAG = "QuranIndex"
        private const val MAGIC = "QRAN"
        private const val HEADER_SIZE = 32
        private const val WORD_RECORD_SIZE = 16

        /** quran.bin dosyasını yükle ve indeks oluştur. */
        fun load(quranBinPath: String): QuranIndex {
            val t0 = System.nanoTime()

            val raf = RandomAccessFile(quranBinPath, "r")
            val channel = raf.channel
            val mmap = channel.map(FileChannel.MapMode.READ_ONLY, 0L, channel.size())
            mmap.order(ByteOrder.LITTLE_ENDIAN)

            // Magic
            val magicBytes = ByteArray(4)
            mmap.get(magicBytes)
            val magic = String(magicBytes)
            require(magic == MAGIC) { "Yanlış magic: '$magic' (beklenen '$MAGIC')" }

            // Header
            val version = mmap.int
            val wordCount = mmap.int
            val trigramCount = mmap.int
            val textOffset = mmap.long
            val trigramOffset = mmap.long

            require(version == 1) { "Desteklenmeyen quran.bin versiyonu: $version" }

            val loadMs = (System.nanoTime() - t0) / 1_000_000L
            Log.d(TAG, "Yüklendi: $wordCount kelime, $trigramCount trigram (${loadMs}ms mmap)")
            Log.d(TAG, "  Text offset: $textOffset, Trigram offset: $trigramOffset")
            Log.d(TAG, "  Dosya boyutu: ${channel.size() / 1024} KB")

            return QuranIndex(raf, mmap, wordCount, trigramCount, textOffset, trigramOffset)
        }
    }

    /** Bir kelime kaydı — quran.bin'deki struct ile birebir. */
    data class WordRecord(
        val pos: Int,            // global word index (0..wordCount-1)
        val surah: Int,          // sure numarası (1..114)
        val ayah: Int,           // ayet numarası
        val wordIdxInAyah: Int,  // ayet içinde kaçıncı kelime (0 tabanlı)
        val text: String,        // orijinal Arapça metin
        val normalized: String,  // normalize edilmiş hâli
    )

    // ============================================================
    // Lazy trigram index — ilk lookup'ta build, sonra HashMap'te tut.
    // ============================================================
    @Volatile
    private var trigramMap: HashMap<String, IntArray>? = null

    private fun ensureTrigramMap(): HashMap<String, IntArray> {
        trigramMap?.let { return it }
        synchronized(this) {
            trigramMap?.let { return it }

            val t0 = System.nanoTime()
            val map = HashMap<String, IntArray>(trigramCount * 2)

            // Trigram section'ı baştan tara
            // Format: [u8 tri_len][bytes tri_utf8][u32 count][u32 indices...]
            var pos = trigramOffset.toInt()
            for (i in 0 until trigramCount) {
                val triLen = mmap.get(pos).toInt() and 0xFF
                pos++

                val triBytes = ByteArray(triLen)
                for (j in 0 until triLen) {
                    triBytes[j] = mmap.get(pos + j)
                }
                val tri = String(triBytes, Charsets.UTF_8)
                pos += triLen

                val count = mmap.getInt(pos)
                pos += 4

                val indices = IntArray(count)
                for (j in 0 until count) {
                    indices[j] = mmap.getInt(pos + j * 4)
                }
                pos += count * 4

                map[tri] = indices
            }

            val ms = (System.nanoTime() - t0) / 1_000_000L
            Log.d(TAG, "Trigram map hazır: ${map.size} entry (${ms}ms)")

            trigramMap = map
            return map
        }
    }

    // ============================================================
    // Word record okuma
    // ============================================================
    /**
     * Verilen pozisyondaki kelime kaydını oku.
     * Pozisyon: global word index, [0, wordCount)
     */
    fun getWord(pos: Int): WordRecord {
        require(pos in 0 until wordCount) { "Pozisyon dışı: $pos" }

        val recordOffset = HEADER_SIZE + pos * WORD_RECORD_SIZE

        val surah = mmap.getShort(recordOffset).toInt() and 0xFFFF
        val ayah = mmap.getShort(recordOffset + 2).toInt() and 0xFFFF
        val wordIdx = mmap.getShort(recordOffset + 4).toInt() and 0xFFFF
        val textOff = mmap.getInt(recordOffset + 6)
        val textLen = mmap.get(recordOffset + 10).toInt() and 0xFF
        val normOff = mmap.getInt(recordOffset + 11)
        val normLen = mmap.get(recordOffset + 15).toInt() and 0xFF

        val text = readString(textOffset.toInt() + textOff, textLen)
        val norm = readString(textOffset.toInt() + normOff, normLen)

        return WordRecord(pos, surah, ayah, wordIdx, text, norm)
    }

    /** Sadece normalized kelimeyi getir (lookup hızlı, full record gerekmiyorsa). */
    fun getNormalized(pos: Int): String {
        require(pos in 0 until wordCount)
        val recordOffset = HEADER_SIZE + pos * WORD_RECORD_SIZE
        val normOff = mmap.getInt(recordOffset + 11)
        val normLen = mmap.get(recordOffset + 15).toInt() and 0xFF
        return readString(textOffset.toInt() + normOff, normLen)
    }

    /** Sadece orijinal (Uthmani) metin — Mushaf gorunumu icin. */
    fun getText(pos: Int): String {
        require(pos in 0 until wordCount)
        val recordOffset = HEADER_SIZE + pos * WORD_RECORD_SIZE
        val textOff = mmap.getInt(recordOffset + 6)
        val textLen = mmap.get(recordOffset + 10).toInt() and 0xFF
        return readString(textOffset.toInt() + textOff, textLen)
    }

    /** (surah shl 16) or ayah — string uretmeden, tum korpusu taramak icin (MushafData). */
    fun getSurahAyah(pos: Int): Int {
        val recordOffset = HEADER_SIZE + pos * WORD_RECORD_SIZE
        val surah = mmap.getShort(recordOffset).toInt() and 0xFFFF
        val ayah = mmap.getShort(recordOffset + 2).toInt() and 0xFFFF
        return (surah shl 16) or ayah
    }

    private fun readString(offset: Int, length: Int): String {
        val bytes = ByteArray(length)
        for (i in 0 until length) {
            bytes[i] = mmap.get(offset + i)
        }
        return String(bytes, Charsets.UTF_8)
    }

    // ============================================================
    // Trigram lookup — Python find_candidate_positions ile birebir
    // ============================================================
    /**
     * Verilen sorgu tokenları için aday pozisyonları bulur.
     *
     * @param queryTokens Normalize edilmiş sorgu kelimeleri
     * @param minHits Bir pozisyonun aday sayılması için en az kaç farklı trigram eşleşmesi olmalı
     * @param positionFilter Eğer null değilse, sadece [start, end] aralığındaki pozisyonlar (inclusive)
     * @return Aday pozisyon set'i (sıralanmamış, IntArray hız için)
     *
     * Python: QuranCorpus.find_candidate_positions(query_tokens, min_hits, position_filter)
     */
    fun findCandidatePositions(
        queryTokens: List<String>,
        minHits: Int = 1,
        positionFilter: IntRange? = null,
    ): IntArray {
        val map = ensureTrigramMap()

        // 1. Tüm sorgu trigramlarını birleştir (set — Python'da da set)
        val allTrigrams = HashSet<String>()
        for (token in queryTokens) {
            allTrigrams.addAll(Normalizer.wordToTrigrams(token))
        }

        // 2. Her trigram için pozisyon listesini al, hit count'ları topla
        // Position → kaç farklı trigram'da bu pozisyon vurulmuş?
        val positionHits = HashMap<Int, Int>()
        for (tri in allTrigrams) {
            val positions = map[tri] ?: continue
            for (pos in positions) {
                if (positionFilter != null && pos !in positionFilter) continue
                positionHits[pos] = (positionHits[pos] ?: 0) + 1
            }
        }

        // 3. minHits'i geçenleri çıkar
        val result = ArrayList<Int>(positionHits.size / 4)
        for ((pos, count) in positionHits) {
            if (count >= minHits) result.add(pos)
        }

        return result.toIntArray()
    }

    // ============================================================
    // Yardımcı: bir aralığa karşılık gelen normalized token listesi
    // ============================================================
    /** [startPos, endPos] aralığındaki normalize tokenları " " ile birleştirir. */
    fun joinNormalized(startPos: Int, endPos: Int): String {
        require(startPos in 0 until wordCount)
        require(endPos in 0 until wordCount)
        require(startPos <= endPos)

        val sb = StringBuilder(64)
        for (i in startPos..endPos) {
            if (i > startPos) sb.append(' ')
            sb.append(getNormalized(i))
        }
        return sb.toString()
    }

    // ============================================================
    // Yaşam döngüsü
    // ============================================================
    fun close() {
        try {
            raf.close()
        } catch (e: Throwable) {
            Log.e(TAG, "close hatası", e)
        }
        trigramMap = null
    }
}
