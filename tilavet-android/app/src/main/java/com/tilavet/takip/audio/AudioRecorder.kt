package com.tilavet.takip.audio

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
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

        recorder?.startRecording()

        recordingJob = scope.launch {
            val shortBuf = ShortArray(FRAME_SAMPLES)
            while (isActive) {
                val read = recorder?.read(shortBuf, 0, FRAME_SAMPLES) ?: 0
                if (read <= 0) continue
                // Float'a cevir (-1..1), exact uzunluk kadar
                val frame = FloatArray(read)
                for (i in 0 until read) {
                    frame[i] = shortBuf[i] / 32768f
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
        try {
            recorder?.stop()
        } catch (_: IllegalStateException) {}
        recorder?.release()
        recorder = null
    }
}
