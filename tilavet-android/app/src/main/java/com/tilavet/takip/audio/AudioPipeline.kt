package com.tilavet.takip.audio

import com.tilavet.takip.aligner.Aligner
import com.tilavet.takip.aligner.QuranIndex
import com.tilavet.takip.asr.OnnxAsrEngine
import com.tilavet.takip.session.ChunkResult
import com.tilavet.takip.session.ChunkStatus
import com.tilavet.takip.session.NamazState
import com.tilavet.takip.session.SessionState
import com.tilavet.takip.session.StateMachine
import com.tilavet.takip.util.SessionAudioWriter
import com.tilavet.takip.util.SessionLog
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.consumeEach
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.File
import kotlin.math.sqrt

/**
 * Pipeline'in UI'a verdigi sonuc: state machine sonucu + parcanin zamanlamasi.
 */
data class PipelineResult(
    val result: ChunkResult,
    /** Parcanin son ornegi alindigi an (System.nanoTime). */
    val audioEndNanos: Long,
    /** Parca imamin duraklamasinda mi kesildi (true) yoksa 5 sn sinirinda mi (false). Sadece kilitliyken true olabilir. */
    val pauseCut: Boolean,
    /** Parcanin bittigi an, oturum basindan itibaren ses saniyesi (simulasyonda dosyadaki konum). */
    val audioEndSec: Double = 0.0,
)

/** Pipeline'dan UI'a giden olaylar — sirali (son parca sonucu "bitti"den once gelir). */
sealed interface PipelineEvent {
    data class Chunk(val pr: PipelineResult) : PipelineEvent
    /** Kaynak bitti (simulasyonda dosya sonu, mikrofonda kayit hatasi) ve kalan parcalar islendi. */
    data class Ended(val chunks: Int) : PipelineEvent
}

/** Ses etkinligi (VoiceActivity) — her cercevede: oturumdaki zaman + son konusma zamani (sn). */
data class VoiceTick(val nowSec: Double, val lastVoiceSec: Double)

/** ChunkBuilder'in urettigi parca. */
private class AudioChunk(val audio: FloatArray, val pauseCut: Boolean, val endNanos: Long, val endSec: Double)

/**
 * Tilavet pipeline koordinatoru.
 *
 * Akış:
 *   FrameSource (100ms frame'ler) — mikrofon (AudioRecorder) ya da simulasyonda WAV (WavFileSource)
 *     ↓
 *   levelFlow: Flow<Float>          ← UI mic bar
 *   ChunkBuilder (kilitliyken imam duraklayinca ya da en gec 5 sn'de parca; kilit yokken sabit 5 sn)
 *     ↓
 *   ASR.transcribe → StateMachine.processChunk
 *     ↓
 *   events: Flow<PipelineEvent>     ← UI Mushaf konumu + state; kaynak bitince Ended
 *
 * Yasam dongu:
 *   start() — kayit ve isleme baslar
 *   stop() — kapat, scope cancel
 *
 * State (sessionState) ve durum dahili olarak tutulur.
 * Gercek namaz akisi simulasyonu icin app.py ile birebir parametreler.
 *
 * sessionDir verilirse duyulan ses WAV olarak oraya da yazilir (SessionAudioWriter) —
 * gercek okumalari eval test verisine cevirmek icin; oturumun log satirlari da yanindaki .txt'ye (SessionLog).
 * Ses ve parcalar bitince (ya da stop()) [onSessionEnd] cagrilir (PublicRecordings disari kopyalar). Simulasyonda yazilmaz.
 */
class AudioPipeline(
    private val source: FrameSource,
    private val asrEngine: OnnxAsrEngine,
    private val index: QuranIndex,
    private val aligner: Aligner,
    private val sessionDir: File? = null,
    private val onSessionEnd: (() -> Unit)? = null,
) {

    companion object {
        private const val TAG = "AudioPipeline"
        const val SAMPLE_RATE = 16000
    }

    private val stateMachine = StateMachine(index, aligner)
    private val sessionState = SessionState()

    private val _levelFlow = MutableStateFlow(0f)
    val levelFlow: StateFlow<Float> = _levelFlow.asStateFlow()

    private val _events = MutableSharedFlow<PipelineEvent>(replay = 0, extraBufferCapacity = 16)
    val events: Flow<PipelineEvent> = _events.asSharedFlow()

    /** "Ses kesildi mi" (okunan ayet metnini ses kesilince kaldirmak icin — bkz. VoiceActivity, TextHold). */
    private val voice = VoiceActivity()
    private val _voiceTicks = MutableStateFlow(VoiceTick(0.0, Double.NEGATIVE_INFINITY))
    val voiceTicks: StateFlow<VoiceTick> = _voiceTicks.asStateFlow()

    /** Islenen ses (tam saniye) — simulasyonda dosyadaki konum (ekranda ilerleme). */
    private val _audioSeconds = MutableStateFlow(0)
    val audioSeconds: StateFlow<Int> = _audioSeconds.asStateFlow()

    private val _isRunning = MutableStateFlow(false)
    val isRunning: StateFlow<Boolean> = _isRunning.asStateFlow()

    private var pipelineScope: CoroutineScope? = null

    /**
     * Pipeline'i baslat. Mikrofonda izin hasPermission() ile kontrol edilmeli (izin yoksa kaynak
     * hemen kapanir → Ended). Simulasyonda kaynak dosya bitince kalan parcalar islenip Ended gelir.
     */
    fun start() {
        if (_isRunning.value) return
        // Simulasyonda oturum kaydi yok: dosya zaten var, son 3 kayit (gercek namazlar) silinmesin
        val sessionWriter = if (source.isSimulation) null else sessionDir?.let { SessionAudioWriter.open(it) }
        sessionWriter?.let { SessionLog.start(it.logFile) }
        SessionLog.d(TAG, "Pipeline basliyor — kaynak=${source.label} tuner: minConf=${"%.1f".format(stateMachine.minConfidence)} " +
                "minConfFirstLock=${"%.1f".format(stateMachine.minConfidenceFirstLock)} " +
                "windowSlack=${aligner.defaultWindowSlack} decoder=${asrEngine.activeDecoder} parca=hibrit(kilitli: duraklama, degil: 5sn)")

        sessionState.reset()
        voice.reset()
        _isRunning.value = true
        _audioSeconds.value = 0

        val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
        pipelineScope = scope

        // Audio frame'lerini al, hem level hem chunk'a yonlendir
        val frameFlow = source.startFrames()
        val chunkChannel = Channel<AudioChunk>(capacity = 6)  // ~20-30 sn tampon
        sessionWriter?.let { SessionLog.d(TAG, "Oturum sesi kaydediliyor: ${it.file.name} (+ log ${it.logFile.name})") }
        // Iki coroutine ortak: frame consumer keser, chunk consumer state'e gore duraklama kesimini acar/kapatir
        val chunkBuilder = ChunkBuilder()

        // 1. Frame consumer: level guncelle + (kayit) + chunk'a sok
        val frameJob = scope.launch {
            var totalSamples = 0L
            try {
                frameFlow.collect { frame ->
                    // Level guncellemesi + ses etkinligi
                    val frameRms = computeRms(frame)
                    _levelFlow.value = (frameRms / 0.3f).toFloat().coerceIn(0f, 1f)
                    totalSamples += frame.size
                    _audioSeconds.value = (totalSamples / SAMPLE_RATE).toInt()
                    val nowSec = totalSamples / SAMPLE_RATE.toDouble()
                    voice.onFrame(nowSec, frameRms)
                    _voiceTicks.value = VoiceTick(nowSec, voice.lastVoiceSec)

                    // Oturum kaydi (chunk'lardan bagimsiz, kesintisiz ham ses)
                    sessionWriter?.write(frame)

                    // Chunk'a ekle — (kilitliyken) imam durakladiysa ya da 5 sn dolduysa parca hazir
                    val chunk = chunkBuilder.addSamples(frame)
                    if (chunk != null) {
                        val endSec = totalSamples / SAMPLE_RATE.toDouble()
                        val sent = chunkChannel.trySend(AudioChunk(chunk.first, chunk.second, System.nanoTime(), endSec)).isSuccess
                        if (!sent) {
                            SessionLog.w(TAG, "Chunk drop — pipeline yetisemedi")
                        }
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                SessionLog.e(TAG, "Frame consumer hata", e)
            } finally {
                chunkChannel.close()
                sessionWriter?.close()
            }
        }

        // 2. Chunk consumer: ASR + StateMachine
        val chunkJob = scope.launch {
            var chunkIndex = 0
            try {
                chunkChannel.consumeEach { chunk ->
                    val audio = chunk.audio

                    // RMS hesapla (sessizlik kontrolu icin)
                    val rms = stateMachine.computeRms(audio)
                    val tRms = System.nanoTime()

                    // ASR
                    val asrResult = try {
                        asrEngine.transcribe(audio)
                    } catch (e: Throwable) {
                        SessionLog.e(TAG, "ASR hatasi (chunk $chunkIndex)", e)
                        null
                    }
                    val tAsr = System.nanoTime()
                    val text = asrResult?.text ?: ""

                    // StateMachine
                    val result = try {
                        stateMachine.processChunk(rms, text, chunkIndex, sessionState)
                    } catch (e: Throwable) {
                        SessionLog.e(TAG, "StateMachine hatasi (chunk $chunkIndex)", e)
                        null
                    }
                    val tSm = System.nanoTime()

                    // Ekranda gosterilen okuma (kilit / gorunen aday): ses esigi bu seviyeden — bkz. VoiceActivity
                    if (result != null && (result.status == ChunkStatus.MATCHED ||
                            (result.status == ChunkStatus.PENDING && !result.jumpCandidate && !result.ambiguous))) {
                        voice.addRecitationLevel(rms)
                    }

                    // Hibrit parca: duraklama kesimi sadece kilitliyken. Kilit yokken kisa parcalar (1-3 kelime)
                    // belirsiz aday uretip birbirini dogruluyordu (eval: yanlis ilk kilit 0 → 2).
                    chunkBuilder.pauseCutEnabled =
                        sessionState.state == NamazState.FATIHA || sessionState.state == NamazState.ZAMM

                    if (result != null) {
                        val asrMs = (tAsr - tRms) / 1_000_000L
                        val smMs = (tSm - tAsr) / 1_000_000L
                        // Parca bitisinden sonuca (kuyrukta bekleme dahil) — kullanicinin hissettigi gecikme
                        val lagMs = (tSm - chunk.endNanos) / 1_000_000L
                        // Kalibrasyon icin tek satir: skor, decoder, eslesen ayetler, sebep, parca, sureler, metin
                        val scoreStr = result.confidence?.let { "%.1f".format(it) } ?: "-"
                        val versesStr = result.verses?.joinToString(",") { "${it.surah}:${it.ayah}" }
                            ?: result.pendingSurah?.let { "aday ${it}:${result.pendingAyah}" } ?: "-"
                        val cutStr = "${if (chunk.pauseCut) "dur" else "5sn"} ${"%.1f".format(audio.size / SAMPLE_RATE.toDouble())}s"
                        SessionLog.d(TAG, "[chunk $chunkIndex] ${result.stateBefore.name}→${result.state.name} " +
                                "${result.status.name.lowercase()} score=$scoreStr " +
                                "dec=${asrResult?.decoder ?: "-"} | $versesStr" +
                                (result.reason?.let { " [$it]" } ?: "") +
                                " (parca=$cutStr rms=${"%.4f".format(rms)} asr=${asrMs}ms sm=${smMs}ms gecikme=${lagMs}ms " +
                                "t=${"%.1f".format(chunk.endSec)}s) txt='${text.take(60)}'")

                        _events.emit(PipelineEvent.Chunk(PipelineResult(result, chunk.endNanos, chunk.pauseCut, chunk.endSec)))
                    }

                    chunkIndex++
                }
                // Kaynak bitti (stop() degil — o scope'u iptal eder): kalan parcalar islendi
                SessionLog.d(TAG, "Kaynak bitti (${source.label}): $chunkIndex parca islendi")
                _isRunning.value = false
                _levelFlow.value = 0f
                _events.emit(PipelineEvent.Ended(chunkIndex))
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                SessionLog.e(TAG, "Chunk consumer hata", e)
            }
        }

        // 3. Oturum sonu: ses (WAV kapandi) ve parcalar bitince ya da stop() ile iptal olunca log'u kapat ve kayitlari
        // disari kopyala. Ayri scope — stop() pipelineScope'u iptal etse de calisir.
        if (sessionWriter != null) {
            val logFile = sessionWriter.logFile
            CoroutineScope(Dispatchers.IO).launch {
                try {
                    frameJob.join()
                    chunkJob.join()
                } finally {
                    withContext(NonCancellable) {
                        SessionLog.stop(logFile)
                        try {
                            onSessionEnd?.invoke()
                        } catch (e: Throwable) {
                            SessionLog.e(TAG, "Oturum sonu hatasi", e)
                        }
                    }
                }
            }
        }
    }

    fun stop() {
        SessionLog.d(TAG, "Pipeline duruyor")
        source.stop()
        pipelineScope?.cancel()
        pipelineScope = null
        _isRunning.value = false
        _levelFlow.value = 0f
    }

    /**
     * Tuner ayarlarini calisirken degistir. Pipeline aktifken cagrildiginda
     * bir sonraki chunk yeni degerleri kullanir.
     */
    fun updateTunerConfig(minConfidence: Double, minConfidenceFirstLock: Double) {
        stateMachine.minConfidence = minConfidence
        stateMachine.minConfidenceFirstLock = minConfidenceFirstLock
    }

    private fun computeRms(frame: FloatArray): Double {
        if (frame.isEmpty()) return 0.0
        var sumSq = 0.0
        for (v in frame) sumSq += v * v
        return sqrt(sumSq / frame.size)
    }

    private fun SessionState.reset() {
        state = NamazState.BEKLEME
        lastWordIndex = null
        lastSurah = null
        lastAyah = null
        lostChunks = 0
        totalChunks = 0
        matchedChunks = 0
        stateTransitions.clear()
        pendingMatch = null
        jumpCandidate = null
        maxAyah = null
        lastTekbirChunk = null
    }
}
