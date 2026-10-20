package com.tilavet.takip.audio

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import java.io.InputStream

/**
 * Simulasyon modu: kayitli WAV'i mikrofon gibi GERCEK ZAMANLI verir.
 *
 * Her 100 ms'lik cerceve, mikrofondaki gibi "duyulup bittigi" anda (baslangic + (k+1) × 100 ms) pipeline'a
 * gider → parca sinirlari, kuyruk, gecikme, hibrit duraklama kesimi canli dinlemedekiyle ayni calisir.
 * Ayni ses hoparlorden de calinir (kullanici imami duyar gibi takibi izler); cerceve once calinir, sonra
 * pipeline'a verilir. Hoparlor acilamazsa sessiz devam eder.
 *
 * @param open her baslatmada dosyayi yeniden acar (SAF Uri ya da uygulamanin kendi oturum kayitlari).
 */
class WavFileSource(
    val fileName: String,
    private val open: () -> InputStream,
    private val playback: Boolean = true,
) : FrameSource {

    companion object {
        private const val TAG = "WavFileSource"
        private const val FRAME = AudioRecorder.FRAME_SAMPLES     // 1600 = 100 ms
    }

    override val label: String get() = "SIM $fileName"
    override val isSimulation: Boolean get() = true

    @Volatile
    private var stopped = false

    override fun startFrames(): Flow<FloatArray> = flow {
        stopped = false
        val reader = WavReader(open())
        var track: AudioTrack? = null
        try {
            Log.d(TAG, "Simulasyon: $fileName (${reader.info})")
            if (playback) track = openTrack()
            val pcm = ShortArray(FRAME)
            val t0 = System.nanoTime()
            var samples = 0L
            while (!stopped) {
                val buf = FloatArray(FRAME)
                val n = reader.read(buf)
                if (n <= 0) break
                val frame = if (n == FRAME) buf else buf.copyOf(n)

                // Once hoparlore (bloklayan yazma; tampon kucuk, en fazla ~1 cerceve bekletir)
                track?.let { t ->
                    for (i in 0 until n) pcm[i] = (frame[i] * 32767f).toInt().coerceIn(-32768, 32767).toShort()
                    t.write(pcm, 0, n)
                }

                // Mikrofon gibi: cerceve "bittiginde" ver (mutlak zaman cizelgesi — kayma birikmez)
                samples += n
                val due = t0 + samples * 1_000_000_000L / WavReader.TARGET_RATE
                val wait = (due - System.nanoTime()) / 1_000_000L
                if (wait > 0) delay(wait)
                emit(frame)
                if (n < FRAME) break
            }
            Log.d(TAG, "Simulasyon dosyasi bitti: $fileName (${"%.1f".format(samples / WavReader.TARGET_RATE.toDouble())} sn)")
        } finally {
            try {
                track?.stop()
            } catch (_: IllegalStateException) {
            }
            track?.release()
            reader.close()
        }
    }.flowOn(Dispatchers.IO)

    private fun openTrack(): AudioTrack? = try {
        val rate = WavReader.TARGET_RATE
        val minBuf = AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
        // ~200 ms tampon: hoparlor pipeline'dan en fazla bu kadar geride kalir
        val bufBytes = maxOf(minBuf, FRAME * 2 * 2)
        AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setSampleRate(rate)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .build()
            )
            .setBufferSizeInBytes(bufBytes)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
            .also { it.play() }
    } catch (e: Throwable) {
        Log.w(TAG, "Hoparlor acilamadi, sessiz simulasyon", e)
        null
    }

    override fun stop() {
        stopped = true
    }
}
