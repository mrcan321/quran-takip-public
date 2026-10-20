package com.tilavet.takip.audio

import kotlinx.coroutines.flow.Flow

/**
 * Pipeline'in ses kaynagi: 16 kHz mono float (-1..1) cerceveler ureten bir akis.
 *
 *   - [AudioRecorder]  — mikrofon (gercek namaz)
 *   - [WavFileSource]  — kayitli WAV dosyasi, gercek zamanli (simulasyon modu)
 *
 * AudioPipeline kaynagin hangisi oldugunu bilmez: ChunkBuilder → ASR → StateMachine ayni yol.
 * Akis biterse (dosya sonu, mikrofon hatasi) pipeline kalan parcalari isleyip kendini bitirir.
 */
interface FrameSource {
    /** Log ve ekran etiketi: "MIC" ya da "SIM <dosya adi>". */
    val label: String

    /** true: simulasyon (dosyadan) — oturum sesi WAV'a yazilmaz, ekranda "SİMÜLASYON" gorunur. */
    val isSimulation: Boolean

    /** Cerceve akisini baslat (her cerceve ~100 ms = 1600 ornek; son cerceve daha kisa olabilir). */
    fun startFrames(): Flow<FloatArray>

    fun stop()
}
