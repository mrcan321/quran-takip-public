package com.tilavet.takip.audio

import java.io.BufferedInputStream
import java.io.Closeable
import java.io.EOFException
import java.io.IOException
import java.io.InputStream

/**
 * WAV okuyucu (akisli) → 16 kHz mono float (-1..1). Simulasyon modunun dosya tarafi.
 *
 * Android bagimliligi yok (JVM'de test edilir). Desteklenen: PCM 8/16/24/32 bit tamsayi, 32 bit float,
 * WAVE_FORMAT_EXTENSIBLE; her ornekleme hizi ve kanal sayisi.
 *   - Kanallar ortalanir (mono).
 *   - 16 kHz: dogrudan (telefonun kendi kayitlari — SessionAudioWriter 16 kHz mono 16 bit yazar; deger
 *     ornek/32768, eval'deki soundfile ile birebir).
 *   - 16 kHz'in tam kati (32/48 kHz): ardisik ornek ortalamasi (basit alcak geciren + seyreltme).
 *   - Diger hizlar (44.1/22.05/8 kHz): dogrusal ara degerleme. Eval soxr (HQ) kullaniyor → bu
 *     dosyalarda ASR sonucu eval'den biraz farkli olabilir; telefon kayitlarinda fark yok.
 *
 * data parcasinin boyutu 0 ya da 0xFFFFFFFF ise dosya sonuna kadar okunur (yarida kalmis kayit).
 * Dosya tamamen bellege alinmaz: 60 dk'lik kayit da okunabilir.
 */
class WavReader(input: InputStream) : Closeable {

    companion object {
        const val TARGET_RATE = 16000
        private const val FMT_PCM = 1
        private const val FMT_FLOAT = 3
        private const val FMT_EXTENSIBLE = 0xFFFE
    }

    /** Baslik bilgisi. durationSec: data parcasinin suresi (boyut bilinmiyorsa 0). */
    data class Info(
        val sampleRate: Int,
        val channels: Int,
        val bitsPerSample: Int,
        val isFloat: Boolean,
        val dataBytes: Long,
        val durationSec: Double,
    ) {
        override fun toString(): String =
            "$sampleRate Hz, $channels kanal, $bitsPerSample bit${if (isFloat) " float" else ""}, " +
                    "${"%.1f".format(durationSec)} sn"
    }

    private val inp = BufferedInputStream(input, 1 shl 16)
    val info: Info
    private val blockAlign: Int
    private val bytesPerSample: Int
    /** Okunacak kalan data baytı; -1 = dosya sonuna kadar. */
    private var remaining: Long

    init {
        if (readTag() != "RIFF") throw IOException("WAV degil (RIFF basligi yok)")
        readU32()
        if (readTag() != "WAVE") throw IOException("WAV degil (WAVE yok)")
        var fmtFound = false
        var format = 0
        var channels = 0
        var rate = 0
        var bits = 0
        var align = 0
        var dataSize: Long
        while (true) {
            val tag = try { readTag() } catch (e: EOFException) { throw IOException("WAV'da data parcasi yok") }
            val size = readU32()
            if (tag == "fmt ") {
                format = readU16()
                channels = readU16()
                rate = readU32().toInt()
                readU32()               // byte rate
                align = readU16()
                bits = readU16()
                var used = 16L
                if (format == FMT_EXTENSIBLE && size >= 40) {
                    readU16()           // cbSize
                    readU16()           // valid bits
                    readU32()           // kanal maskesi
                    format = readU16()  // alt format GUID'inin ilk 2 bayti = format kodu
                    used = 26L
                }
                skipFully(size - used + (size and 1))
                fmtFound = true
            } else if (tag == "data") {
                dataSize = size
                break
            } else {
                skipFully(size + (size and 1))   // LIST, fact vb. (cift bayta hizali)
            }
        }
        if (!fmtFound) throw IOException("WAV'da fmt parcasi yok")
        val isFloat = format == FMT_FLOAT
        if (format != FMT_PCM && !isFloat) throw IOException("Desteklenmeyen WAV kodlamasi ($format) — PCM/float olmali")
        if (isFloat && bits != 32) throw IOException("Desteklenmeyen float WAV ($bits bit)")
        if (!isFloat && bits !in setOf(8, 16, 24, 32)) throw IOException("Desteklenmeyen PCM ($bits bit)")
        if (channels <= 0 || rate <= 0) throw IOException("Gecersiz WAV basligi ($channels kanal, $rate Hz)")
        bytesPerSample = bits / 8
        blockAlign = if (align > 0) align else channels * bytesPerSample
        val unknownSize = dataSize == 0L || dataSize == 0xFFFFFFFFL
        remaining = if (unknownSize) -1L else dataSize - dataSize % blockAlign
        info = Info(
            sampleRate = rate,
            channels = channels,
            bitsPerSample = bits,
            isFloat = isFloat,
            dataBytes = if (unknownSize) 0L else remaining,
            durationSec = if (unknownSize) 0.0 else remaining.toDouble() / blockAlign / rate,
        )
    }

    // ---------- 16 kHz mono cikis (akisli donusturucu) ----------
    private val inBlock = ByteArray(blockAlign * 2048)
    private var outBuf = FloatArray(4096)
    private var outStart = 0
    private var outEnd = 0
    private var eof = false

    // Seyreltme (tam kat): ardisik `decim` ornegin ortalamasi
    private val decim = if (info.sampleRate % TARGET_RATE == 0) info.sampleRate / TARGET_RATE else 0
    private var decimSum = 0.0
    private var decimN = 0

    // Dogrusal ara degerleme: cikis ornegi j ↔ giris konumu j * step
    private val step = info.sampleRate.toDouble() / TARGET_RATE
    private var lerpT = 0.0
    private var lerpIdx = -1L
    private var lerpPrev = 0f

    /**
     * En fazla out.size kadar 16 kHz mono ornek doldur. Donen sayi < out.size ise dosya bitti
     * (0 = hic kalmadi).
     */
    fun read(out: FloatArray): Int {
        var n = 0
        while (n < out.size) {
            if (outStart == outEnd) {
                if (eof || !fill()) break
                continue
            }
            val k = minOf(out.size - n, outEnd - outStart)
            System.arraycopy(outBuf, outStart, out, n, k)
            outStart += k
            n += k
        }
        return n
    }

    /** Bir blok oku, donustur, outBuf'a ekle. false = veri kalmadi. */
    private fun fill(): Boolean {
        var want = inBlock.size
        if (remaining in 0 until want) want = remaining.toInt()
        if (want <= 0) { eof = true; return false }
        var got = 0
        while (got < want) {
            val r = inp.read(inBlock, got, want - got)
            if (r < 0) break
            got += r
        }
        got -= got % blockAlign
        if (got <= 0) { eof = true; return false }
        if (remaining >= 0) remaining -= got
        outStart = 0
        outEnd = 0
        val frames = got / blockAlign
        for (f in 0 until frames) {
            val base = f * blockAlign
            var sum = 0.0
            for (c in 0 until info.channels) sum += sampleAt(base + c * bytesPerSample)
            push((sum / info.channels).toFloat())
        }
        return true
    }

    private fun sampleAt(off: Int): Double {
        val b = inBlock
        return when {
            info.isFloat -> {
                val bitsInt = (b[off].toInt() and 0xFF) or ((b[off + 1].toInt() and 0xFF) shl 8) or
                        ((b[off + 2].toInt() and 0xFF) shl 16) or ((b[off + 3].toInt() and 0xFF) shl 24)
                java.lang.Float.intBitsToFloat(bitsInt).toDouble()
            }
            bytesPerSample == 1 -> ((b[off].toInt() and 0xFF) - 128) / 128.0
            bytesPerSample == 2 -> ((b[off].toInt() and 0xFF) or (b[off + 1].toInt() shl 8)).toShort() / 32768.0
            bytesPerSample == 3 -> {
                val v = (b[off].toInt() and 0xFF) or ((b[off + 1].toInt() and 0xFF) shl 8) or (b[off + 2].toInt() shl 16)
                v / 8388608.0
            }
            else -> {
                val v = (b[off].toInt() and 0xFF) or ((b[off + 1].toInt() and 0xFF) shl 8) or
                        ((b[off + 2].toInt() and 0xFF) shl 16) or (b[off + 3].toInt() shl 24)
                v / 2147483648.0
            }
        }
    }

    /** Bir mono giris ornegini 16 kHz'e cevirip outBuf'a ekle. */
    private fun push(x: Float) {
        when {
            info.sampleRate == TARGET_RATE -> emit(x)
            decim > 0 -> {
                decimSum += x
                decimN++
                if (decimN == decim) {
                    emit((decimSum / decim).toFloat())
                    decimSum = 0.0
                    decimN = 0
                }
            }
            else -> {
                lerpIdx++
                if (lerpIdx == 0L) {
                    while (lerpT <= 0.0) { emit(x); lerpT += step }
                } else {
                    while (lerpT <= lerpIdx) {
                        val frac = (lerpT - (lerpIdx - 1)).toFloat()
                        emit(lerpPrev + (x - lerpPrev) * frac)
                        lerpT += step
                    }
                }
                lerpPrev = x
            }
        }
    }

    private fun emit(v: Float) {
        if (outEnd == outBuf.size) outBuf = outBuf.copyOf(outBuf.size * 2)
        outBuf[outEnd++] = v
    }

    // ---------- baslik yardimcilari ----------
    private fun readByte(): Int {
        val v = inp.read()
        if (v < 0) throw EOFException()
        return v
    }

    private fun readTag(): String {
        val b = ByteArray(4) { readByte().toByte() }
        return String(b, Charsets.US_ASCII)
    }

    private fun readU16(): Int = readByte() or (readByte() shl 8)

    private fun readU32(): Long =
        (readByte().toLong()) or (readByte().toLong() shl 8) or (readByte().toLong() shl 16) or (readByte().toLong() shl 24)

    private fun skipFully(n: Long) {
        var left = n
        while (left > 0) {
            val s = inp.skip(left)
            if (s <= 0) {
                if (inp.read() < 0) throw EOFException()
                left--
            } else {
                left -= s
            }
        }
    }

    override fun close() = inp.close()
}
