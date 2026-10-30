package com.tilavet.takip.util

import android.util.Log
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Pipeline'in duydugu sesi WAV olarak kaydeder (16 kHz, mono, 16-bit PCM).
 *
 * Amac: telefonda yapilan gercek okumalari (namaz, aile) eval test verisine cevirmek —
 * 📤 ile log + son WAV paylasilir, data/ klasorune konup scripts/eval_pipeline.py'de
 * EXPECTED'e beklenen sure yazilir. Log'daki [chunk N] satirlari WAV'da N*5. saniyeye denk gelir.
 *
 * - Dosyalar cacheDir/sessions/ altinda, sadece son [KEEP] oturumun WAV'i (simulasyon menusu), son [LOG_KEEP]
 *   oturumun log'u (namaz raporu) tutulur. Oturum bitince
 *   PublicRecordings ayni dosyayi + oturum log'unu (.txt) Download/Tilavet Takip'e kopyalar — orada silinmez.
 * - Her oturumun yaninda ayni adla .txt oturum log'u ([logFile], SessionLog yazar).
 * - Tek oturum en fazla [MAX_SECONDS] (sonrasi yazilmaz, pipeline etkilenmez).
 * - Header once bos yazilir, close()'da boyutlar doldurulur. Uygulama olurse header 0 kalir;
 *   eval tarafindaki soundfile yine de okuyabilsin diye periyodik olarak da guncellenir.
 * - Tek thread'den kullanilir (pipeline frame consumer'i).
 */
class SessionAudioWriter private constructor(val file: File) {

    companion object {
        private const val TAG = "SessionAudioWriter"
        const val DIR = "sessions"
        private const val KEEP = 3
        /**
         * Oturum log'lari (.txt, kucuk) WAV'lardan uzun tutulur: namaz raporu son 1-7 namaza bakar (ReportHtml.MAX_NAMAZ);
         * kisa / namazsiz oturumlar (deneme, ASR testi) da sayildigi icin pay birakildi.
         */
        const val LOG_KEEP = 20
        private const val SAMPLE_RATE = 16000
        private const val MAX_SECONDS = 60 * 60
        private const val HEADER_SIZE = 44
        private const val HEADER_REFRESH_BYTES = SAMPLE_RATE * 2 * 10   // ~10 sn'de bir header guncelle

        /** Su an yazilan oturum WAV'i (yayinlarken atlanir); kapaninca null. */
        @Volatile
        var openFile: File? = null
            private set

        /** Yeni oturum dosyasi ac; eski oturumlari temizle. Hata olursa null (kayit opsiyonel). */
        fun open(cacheDir: File): SessionAudioWriter? = try {
            val dir = File(cacheDir, DIR).apply { mkdirs() }
            val ts = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())
            val w = SessionAudioWriter(File(dir, "tilavet-$ts.wav"))
            openFile = w.file
            prune(dir, keep = KEEP)
            Log.d(TAG, "Oturum kaydi: ${w.file.name}")
            w
        } catch (e: Throwable) {
            Log.e(TAG, "Oturum kaydi acilamadi", e)
            null
        }

        /** En son oturum kaydi (paylasim icin), yoksa null. */
        fun latest(cacheDir: File): File? =
            File(cacheDir, DIR).listFiles { f -> f.name.endsWith(".wav") && f.length() > HEADER_SIZE }
                ?.maxByOrNull { it.lastModified() }

        /** Tutulan oturum kayitlari, en yenisi once (simulasyon menusu icin). */
        fun list(cacheDir: File): List<File> =
            File(cacheDir, DIR).listFiles { f -> f.name.endsWith(".wav") && f.length() > HEADER_SIZE }
                ?.sortedByDescending { it.lastModified() } ?: emptyList()

        /** Dosya boyutundan sure (sn) — 16 kHz mono 16 bit. */
        fun durationSec(file: File): Int = ((file.length() - HEADER_SIZE) / (SAMPLE_RATE * 2)).toInt()

        /** Oturumun log dosyasi: ayni ad, .txt (SessionLog yazar, PublicRecordings WAV'la birlikte kopyalar). */
        fun logFileOf(wav: File): File = File(wav.parentFile, wav.name.removeSuffix(".wav") + ".txt")

        /** Oturumun WAV'i (log'dan): ayni ad, .wav — WAV'lar [KEEP] ile sinirli, eski oturumda yoktur. */
        fun wavOf(log: File): File = File(log.parentFile, log.name.removeSuffix(".txt") + ".wav")

        /** Tutulan oturum log'lari, en yenisi once (adindaki baslangic zamanina gore; namaz raporu icin). */
        fun listLogs(cacheDir: File): List<File> =
            File(cacheDir, DIR).listFiles { f -> f.name.startsWith("tilavet-") && f.name.endsWith(".txt") }
                ?.sortedByDescending { it.name } ?: emptyList()

        private fun prune(dir: File, keep: Int) {
            val wavs = dir.listFiles { f -> f.name.endsWith(".wav") }?.sortedByDescending { it.lastModified() }
                ?: return
            // Yeni acilan dosya da listede — keep tane kalsin
            val kept = wavs.take(keep).map { it.name.removeSuffix(".wav") }.toSet()
            wavs.drop(keep).forEach { it.delete() }
            // Log'lar son LOG_KEEP oturumda kalir (namaz raporu); yayin isareti dosyasiyla birlikte gider
            val keptLogs = dir.listFiles { f -> f.name.endsWith(".txt") }?.sortedByDescending { it.name }
                ?.take(LOG_KEEP)?.map { it.name.removeSuffix(".txt") }?.toSet() ?: emptySet()
            dir.listFiles { f -> f.name.endsWith(".txt") || f.name.endsWith(".pub") }?.forEach { f ->
                val base = f.name.substringBeforeLast('.').removeSuffix(".wav").removeSuffix(".txt")
                if (base !in kept && base !in keptLogs) f.delete()
            }
        }
    }

    /** Bu oturumun log dosyasi (SessionLog.start ile acilir). */
    val logFile: File = logFileOf(file)

    private val out = BufferedOutputStream(FileOutputStream(file), 1 shl 16)
    private val frameBytes = ByteArray(3200)
    private var dataBytes = 0L
    private var bytesSinceHeader = 0L
    private var closed = false

    init {
        out.write(ByteArray(HEADER_SIZE))
        out.flush()
        writeHeader()
    }

    /** Float [-1, 1] frame'i 16-bit PCM olarak ekle. */
    fun write(frame: FloatArray) {
        if (closed) return
        if (dataBytes >= MAX_SECONDS.toLong() * SAMPLE_RATE * 2) return
        try {
            val need = frame.size * 2
            val buf = if (frameBytes.size >= need) frameBytes else ByteArray(need)
            for (i in frame.indices) {
                val v = (frame[i] * 32767f).toInt().coerceIn(-32768, 32767)
                buf[2 * i] = (v and 0xFF).toByte()
                buf[2 * i + 1] = ((v shr 8) and 0xFF).toByte()
            }
            out.write(buf, 0, need)
            dataBytes += need
            bytesSinceHeader += need
            if (bytesSinceHeader >= HEADER_REFRESH_BYTES) {
                out.flush()
                writeHeader()
                bytesSinceHeader = 0
            }
        } catch (e: Throwable) {
            Log.e(TAG, "Yazma hatasi, kayit durduruldu", e)
            close()
        }
    }

    fun close() {
        if (closed) return
        closed = true
        try {
            out.flush()
            out.close()
            writeHeader()
            Log.d(TAG, "Oturum kaydi kapandi: ${file.name} (${dataBytes / (SAMPLE_RATE * 2)} sn, ${file.length() / 1024} KB)")
        } catch (e: Throwable) {
            Log.e(TAG, "Kapatma hatasi", e)
        } finally {
            if (openFile == file) openFile = null
        }
    }

    /** RIFF/WAVE header'ini mevcut veri boyutuyla yaz (dosya basina). */
    private fun writeHeader() {
        val h = ByteArray(HEADER_SIZE)
        fun str(off: Int, s: String) { s.toByteArray(Charsets.US_ASCII).copyInto(h, off) }
        fun u32(off: Int, v: Long) { for (k in 0 until 4) h[off + k] = ((v shr (8 * k)) and 0xFF).toByte() }
        fun u16(off: Int, v: Int) { h[off] = (v and 0xFF).toByte(); h[off + 1] = ((v shr 8) and 0xFF).toByte() }
        str(0, "RIFF"); u32(4, 36 + dataBytes); str(8, "WAVE")
        str(12, "fmt "); u32(16, 16); u16(20, 1); u16(22, 1)
        u32(24, SAMPLE_RATE.toLong()); u32(28, SAMPLE_RATE * 2L); u16(32, 2); u16(34, 16)
        str(36, "data"); u32(40, dataBytes)
        RandomAccessFile(file, "rw").use { raf ->
            raf.seek(0)
            raf.write(h)
        }
    }
}
