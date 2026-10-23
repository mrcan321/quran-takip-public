package com.tilavet.takip.audio

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioRecordingConfiguration
import android.media.MediaRecorder
import android.os.Build
import android.util.Log
import androidx.core.content.ContextCompat
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.consumeAsFlow

/**
 * 16kHz mono PCM kayıt — raw FloatArray frame'ler emit eder.
 *
 * Her frame ~100ms'lik audio (1600 sample) iceren bir FloatArray.
 * Tum dinleme + chunk biriktirme + level hesaplama AudioPipeline'da yapilir.
 *
 * Bu sınıf ASR pipeline'i icin _ana audio kaynagi_ olarak kullanilir.
 * Eski "level only" davranisi AudioPipeline tarafindan saglanir.
 */
class AudioRecorder(private val context: Context) : FrameSource {

    companion object {
        const val SAMPLE_RATE = 16000
        const val CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO
        const val ENCODING = AudioFormat.ENCODING_PCM_16BIT
        const val FRAME_SAMPLES = 1600  // 100ms @ 16kHz
        private const val TAG = "AudioRecorder"
        /**
         * Bu kadar art arda tamamen sifir cerceve (2 sn) = Android mikrofonu susturdu. Gercek mikrofon sessiz ortamda bile
         * gurultu verir; tam sifir sadece susturmada geliyor (yatsi 23.10: 2.0-16.1 sn ve 32.5-523.1 sn hep sifir).
         */
        const val SILENCED_ZERO_FRAMES = 20
    }

    /**
     * Mikrofon susturuldu / tekrar acildi (true / false) + sebep. Android uygulama ekranda degilken on plan servisi yoksa
     * ya da baska uygulama mikrofonu aldiysa kayda sifir verir — AudioRecordingConfiguration.isClientSilenced (API 29+)
     * ve [SILENCED_ZERO_FRAMES] sifir cerceve. Kayit thread'inden / ana thread'den cagrilir.
     */
    @Volatile
    var onSilenced: ((Boolean, String) -> Unit)? = null
    @Volatile
    private var silenced = false
    private var recordingCallback: Any? = null

    private fun reportSilenced(value: Boolean, why: String) {
        if (value == silenced) return
        silenced = value
        onSilenced?.invoke(value, why)
    }

    override val label: String get() = "MIC"
    override val isSimulation: Boolean get() = false

    private var recorder: AudioRecord? = null
    private var recordingJob: Job? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    fun hasPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            context, Manifest.permission.RECORD_AUDIO
        ) == PackageManager.PERMISSION_GRANTED
    }

    /**
     * Audio kaydi baslat ve raw float frame'ler ureten bir Flow don.
     * Her frame FRAME_SAMPLES uzunlugunda (100ms @ 16kHz).
     * Sample'lar -1..1 araliginda normalize edilmis.
     *
     * Eger izin yoksa veya AudioRecord init edemezse, Flow hemen kapanir.
     */
    @SuppressLint("MissingPermission")
    override fun startFrames(): Flow<FloatArray> {
        val channel = Channel<FloatArray>(capacity = 32)  // 3.2 saniyelik buffer

        if (!hasPermission()) {
            Log.w(TAG, "İzin yok")
            channel.close()
            return channel.consumeAsFlow()
        }

        val minBufferSize = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL_CONFIG, ENCODING)
        // En az 200ms'lik buffer
        val internalBufferBytes = maxOf(minBufferSize, FRAME_SAMPLES * 2 * 4)

        try {
            recorder = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE, CHANNEL_CONFIG, ENCODING,
                internalBufferBytes,
            )
        } catch (e: SecurityException) {
            Log.e(TAG, "AudioRecord init: SecurityException", e)
            channel.close(e)
            return channel.consumeAsFlow()
        }

        if (recorder?.state != AudioRecord.STATE_INITIALIZED) {
            Log.e(TAG, "AudioRecord init failed (state != INITIALIZED)")
            recorder?.release()
            recorder = null
            channel.close(IllegalStateException("AudioRecord init failed"))
            return channel.consumeAsFlow()
        }

        silenced = false
        // Susturma bildirimi: startRecording'den ONCE kaydedilmeli (Android dokumani)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            try {
                val rec = recorder!!
                val cb = object : AudioManager.AudioRecordingCallback() {
                    override fun onRecordingConfigChanged(configs: List<AudioRecordingConfiguration>) {
                        val mine = try { rec.activeRecordingConfiguration } catch (_: Throwable) { null } ?: return
                        reportSilenced(mine.isClientSilenced, "Android (isClientSilenced)")
                    }
                }
                rec.registerAudioRecordingCallback(ContextCompat.getMainExecutor(context), cb)
                recordingCallback = cb
            } catch (e: Throwable) {
                Log.w(TAG, "AudioRecordingCallback kaydedilemedi: ${e.message}")
            }
        }

        recorder?.startRecording()

        recordingJob = scope.launch {
            val shortBuf = ShortArray(FRAME_SAMPLES)
            var zeroFrames = 0
            var soundFrames = 0
            while (isActive) {
                val read = recorder?.read(shortBuf, 0, FRAME_SAMPLES) ?: 0
                if (read <= 0) continue
                // Float'a cevir (-1..1), exact uzunluk kadar
                val frame = FloatArray(read)
                var allZero = true
                for (i in 0 until read) {
                    if (shortBuf[i].toInt() != 0) allZero = false
                    frame[i] = shortBuf[i] / 32768f
                }
                if (allZero) {
                    zeroFrames++
                    soundFrames = 0
                    if (zeroFrames == SILENCED_ZERO_FRAMES) reportSilenced(true, "${SILENCED_ZERO_FRAMES / 10} sn tam sifir ses")
                } else {
                    zeroFrames = 0
                    soundFrames++
                    // 0.5 sn gercek ses: susturma bitti (tampondaki birkac eski cerceve yuzunden gidip gelmesin)
                    if (silenced && soundFrames >= 5) reportSilenced(false, "ses geldi")
                }
                if (!channel.trySend(frame).isSuccess) {
                    // Buffer dolmus — ASR isleme yetisemiyor. Drop.
                    Log.w(TAG, "Frame drop (buffer full)")
                }
            }
            channel.close()
        }

        return channel.consumeAsFlow()
    }

    override fun stop() {
        recordingJob?.cancel()
        recordingJob = null
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            (recordingCallback as? AudioManager.AudioRecordingCallback)?.let { cb ->
                try { recorder?.unregisterAudioRecordingCallback(cb) } catch (_: Throwable) {}
            }
        }
        recordingCallback = null
        silenced = false
        try {
            recorder?.stop()
        } catch (_: IllegalStateException) {}
        recorder?.release()
        recorder = null
    }
}
