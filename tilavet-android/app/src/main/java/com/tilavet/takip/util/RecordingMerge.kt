package com.tilavet.takip.util

import java.text.SimpleDateFormat
import java.util.Locale

/**
 * Paylas penceresi (📤) icin oturum kayitlari: her oturum = ses (tilavet-YYYYMMDD-HHmmss.wav) + oturum log'u (.txt).
 * Kaynaklar (util/RecordingCatalog): Download/Tilavet Takip (PublicRecordings'in kopyalari, silinmez) ve cacheDir/sessions
 * (son 3 WAV, son 20 log; henuz kopyalanmamis oturum). Ayni dosya iki kaynakta varsa onceki kaynak alinir. Kullanici
 * (30.10): "paylas butonuna basinca yalnizca son kaydin logu ve ses kaydi paylasiliyor; popupta en yeniden en eskiye 30
 * kayit gorunsun, multiple secebilsin".
 *
 * Android'e bagli degil (tests/jvm `recordings`); [ref] kaynagin kendi dosya tanimi (uygulamada Uri).
 */
object RecordingMerge {
    const val MAX = 30
    /** 1 sn'den kisa ses (yanlislikla basma) listelenmez — PublicRecordings ile ayni sinir. */
    const val MIN_WAV_BYTES = 44L + 16000 * 2
    /** Sesi olmayan (WAV'i silinmis) oturumun log'u bundan kucukse (bos / cok kisa oturum) listelenmez. */
    const val MIN_LOG_ONLY_BYTES = 2048L
    private const val WAV_HEADER = 44L
    private const val BYTES_PER_SEC = 16000L * 2
    private val NAME = Regex("""^tilavet-(\d{8}-\d{6})\.(wav|txt)$""")

    /** Bir dosya: ad, boyut (bayt) ve kaynaktaki tanimi. */
    class Entry<R>(val name: String, val bytes: Long, val ref: R)

    /** Bir oturum: [stamp] "YYYYMMDD-HHmmss" (dosya adindan), ses ve log (ikisinden biri olmayabilir). */
    class Recording<R>(val stamp: String, val wav: Entry<R>?, val log: Entry<R>?) {
        /** WAV boyutundan sure (16 kHz mono 16 bit); ses yoksa null. */
        val durationSec: Int? get() = wav?.let { ((it.bytes - WAV_HEADER).coerceAtLeast(0) / BYTES_PER_SEC).toInt() }
        val startMs: Long? get() = startMs(stamp)
        val files: List<Entry<R>> get() = listOfNotNull(wav, log)
    }

    /** "20261030-071523" → epoch ms (yerel saat), olmazsa null. */
    fun startMs(stamp: String): Long? = try {
        SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).apply { isLenient = false }.parse(stamp)?.time
    } catch (e: Exception) {
        null
    }

    /**
     * Kaynaklari birlestir: oncelik sirasiyla ([sources] basi once), adi tilavet-...wav/.txt olmayanlar ve [exclude]
     * (su an yazilan oturum) atlanir; ayni oturumun sesi ve log'u tek kayit; en yeniden eskiye, en fazla [max].
     */
    fun <R> merge(sources: List<List<Entry<R>>>, exclude: Set<String> = emptySet(), max: Int = MAX): List<Recording<R>> {
        val wavs = HashMap<String, Entry<R>>()
        val logs = HashMap<String, Entry<R>>()
        for (src in sources) for (e in src) {
            if (e.name in exclude) continue
            val m = NAME.matchEntire(e.name) ?: continue
            val stamp = m.groupValues[1]
            val target = if (m.groupValues[2] == "wav") wavs else logs
            if (stamp !in target) target[stamp] = e
        }
        return (wavs.keys + logs.keys).asSequence()
            .map { Recording(it, wavs[it]?.takeIf { w -> w.bytes >= MIN_WAV_BYTES }, logs[it]) }
            .filter { r ->
                r.wav != null || (wavs[r.stamp] == null && r.log != null && r.log.bytes >= MIN_LOG_ONLY_BYTES)
            }
            .sortedByDescending { it.stamp }
            .take(max)
            .toList()
    }
}
