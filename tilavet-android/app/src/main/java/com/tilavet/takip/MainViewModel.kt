package com.tilavet.takip

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.annotation.RequiresPermission
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.tilavet.takip.aligner.Aligner
import com.tilavet.takip.aligner.AlignerTestRunner
import com.tilavet.takip.aligner.FuzzyTestRunner
import com.tilavet.takip.aligner.QuranIndex
import com.tilavet.takip.asr.AsrDecoder
import com.tilavet.takip.asr.AsrState
import com.tilavet.takip.asr.OnnxAsrEngine
import com.tilavet.takip.audio.AudioPipeline
import com.tilavet.takip.audio.FrameSource
import com.tilavet.takip.audio.PipelineEvent
import com.tilavet.takip.audio.PipelineResult
import com.tilavet.takip.audio.TextHold
import com.tilavet.takip.audio.VoiceTick
import com.tilavet.takip.audio.AudioRecorder
import com.tilavet.takip.audio.WavFileSource
import com.tilavet.takip.audio.WavReader
import com.tilavet.takip.data.AppSettings
import com.tilavet.takip.data.MealLoader
import com.tilavet.takip.data.MushafData
import com.tilavet.takip.data.SettingsRepository
import com.tilavet.takip.glasses.GlassesBridge
import com.tilavet.takip.glasses.GlassesState
import com.tilavet.takip.session.ChunkResult
import com.tilavet.takip.session.ChunkStatus
import com.tilavet.takip.session.EzanEvent
import com.tilavet.takip.session.EzanTracker
import com.tilavet.takip.session.EzanView
import com.tilavet.takip.session.NamazState
import com.tilavet.takip.session.NamazZikri
import com.tilavet.takip.session.RakatTracker
import com.tilavet.takip.session.StateMachineTestRunner
import com.tilavet.takip.session.ZikirTracker
import com.tilavet.takip.ui.AyahStepper
import com.tilavet.takip.ui.theme.AppTheme
import com.tilavet.takip.util.AssetSync
import com.tilavet.takip.util.ListenService
import com.tilavet.takip.util.LogExporter
import com.tilavet.takip.util.PublicRecordings
import com.tilavet.takip.util.SessionAudioWriter
import com.tilavet.takip.util.SessionLog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.File
import java.io.InputStream

/** Simulasyon menusundeki uygulama ici oturum kaydi (cacheDir/sessions). */
data class SimRecording(val file: File, val durationSec: Int)

data class UiState(
    /** Pipeline calisiyor (mikrofon ya da simulasyon). */
    val isListening: Boolean = false,
    /** Simulasyon modu: calan dosyanin adi (null = mikrofon / bos). */
    val simFile: String? = null,
    /** Simulasyonda dosyadaki konum ve toplam sure (sn). */
    val simPositionSec: Int = 0,
    val simDurationSec: Int = 0,
    /** Simulasyon menusu: uygulamanin tuttugu son oturum kayitlari (en yeni once). */
    val simRecordings: List<SimRecording> = emptyList(),
    val statusText: String = "Hazır",
    // === Mushaf (tum Kuran listesi) ===
    val mushaf: MushafData? = null,
    /** Okunan ayet (global indeks) — kilitli eslesme veya aday; null = henuz yok. */
    val currentAyah: Int? = null,
    /** true: state machine henuz dogrulamadi (PENDING aday), false: kilitli eslesme. */
    val tentative: Boolean = false,
    /** Vurgulanan global kelime araligi [hlStart, hlEnd], yoksa -1. */
    val hlStart: Int = -1,
    val hlEnd: Int = -1,
    val currentLabel: String = "",     // "Rahman: 5" (MushafData.ayahTag)
    val confidence: Int? = null,
    /** Son parcanin sonundan ekrana gelene kadar gecen sure (ms) — durum satirinda gosterilir. */
    val lastLatencyMs: Long? = null,
    val audioLevel: Float = 0f,
    /** Ses kesildi: okunan ayetin metni ekrandan kalkti (vurgu yok, G2 bos + rekat) — bkz. TextHold. */
    val textHidden: Boolean = false,
    val settings: AppSettings = AppSettings(),
    val showSettingsSheet: Boolean = false,
    val surahEnded: Boolean = false,
    val asrState: String = "",
    val asrLastResult: String = "",
    val asrTimingInfo: String = "",
    val asrInProgress: Boolean = false,
    val alignerState: String = "",
    val alignerResult: String = "",
    val fuzzyState: String = "",
    val fuzzyResult: String = "",
    val stateMachineState: String = "",
    val stateMachineResult: String = "",
    val pipelineStatus: String = "",  // "[FATIHA] (3/5 chunk match)"
    /** Ezan / kamet penceresi (null = kapali). Bkz. EzanTracker. */
    val ezan: EzanView? = null,
    /** Namaz zikri karti (tekbir, semiallah, selam...; null = kapali). Bkz. ZikirTracker. */
    val zikir: NamazZikri? = null,
    /** Rekat + kaba durus ("2. REKÂT · KIYAM"); null = gosterme. Bkz. RakatTracker. */
    val rakatLabel: String? = null,
    /** G2 gozluk koprusu durumu (ayarlarda): null = kapali, "bağlı", "eklenti bekleniyor · istek yok / son istek N sn önce",
     *  "açılamadı". */
    val glassesLink: String? = null,
)

class MainViewModel(application: Application) : AndroidViewModel(application) {

    companion object {
        private const val TAG = "MainViewModel"
        private const val QURAN_BIN = "quran.bin"
        private const val MEAL_BIN = "meal.bin"
        /** Ezan/kamet son cumlesi ("لا إله إلا الله") taninca pencere bu kadar gorunup kapanir. */
        private const val EZAN_FINAL_SHOW_MS = 2500L
        /** Zikir karti (son zikir) bu kadar gorunur; ayni parcada birden fazla zikir varsa aradakiler ZIKIR_STEP_MS. */
        private const val ZIKIR_SHOW_MS = 6000L
        private const val ZIKIR_STEP_MS = 2500L
        /** G2 eklentisinin bagli olup olmadigina bu aralikla bakilir (ayarlardaki durum + log). */
        private const val GLASSES_LINK_POLL_MS = 3000L

        /** Ayet sonu numarasi: KFGQPC fontu Arapca rakami susle cerceveli ayet isareti olarak ciziyor. */
        private fun arabicDigits(n: Int): String = n.toString().map { '٠' + (it - '0') }.joinToString("")
    }

    private val settingsRepo = SettingsRepository(application)
    private val recorder = AudioRecorder(application)

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    private var pipelineJob: Job? = null
    private var asrJob: Job? = null
    private var alignerJob: Job? = null
    private var fuzzyJob: Job? = null
    private var stateMachineJob: Job? = null

    // Ezan / kamet penceresi: takip her parcada, pencere kullanici kapattiysa o ezan/kamet bitene kadar acilmaz
    private val ezanTracker = EzanTracker()
    // Rekat sayaci + kaba durus (UI): Fatiha / semiallah / selam sinyallerinden
    private val rakatTracker = RakatTracker()
    private var ezanCloseJob: Job? = null
    private var ezanDismissed = false
    // Namaz zikirleri karti (tekbir, semiallah, rabbena, selam, dua): birkac saniye gorunur
    private val zikirTracker = ZikirTracker()
    private var zikirJob: Job? = null

    // Atlanan ara ayetler (ör. 1:2 → 1:5): ekran aradaki ayetlerde sirayla durur, sonra okunan ayete gecer
    private val ayahStepper = AyahStepper(viewModelScope)

    private val asrEngine: OnnxAsrEngine by lazy { OnnxAsrEngine(application) }

    // Even Realities G2 gozluk koprusu (ayarlardan acilir): ekrandaki okunan ayet + meal 127.0.0.1'den eklentiye
    @Volatile
    private var glasses: GlassesBridge? = null
    private var glassesLinkJob: Job? = null
    private val glassesFileCache = HashMap<String, ByteArray>()
    private val glassesMutex = Mutex()

    @Volatile
    private var quranIndex: QuranIndex? = null

    @Volatile
    private var aligner: Aligner? = null

    @Volatile
    private var pipeline: AudioPipeline? = null

    @Volatile
    private var mealLoader: MealLoader? = null

    // QuranIndex/MealLoader hem acilista (Mushaf) hem pipeline'da yuklenir — iki kere acilmasin
    private val loadMutex = Mutex()

    init {
        // Onceki oturumlardan disari kopyalanmamis kayit kaldiysa (uygulama oturum ortasinda kapandi) simdi kopyala
        viewModelScope.launch(Dispatchers.IO) { PublicRecordings.publishPending(getApplication()) }

        viewModelScope.launch {
            settingsRepo.settings.collect { s ->
                _state.update { it.copy(settings = s) }
                // Tuner ayarlari Aligner, StateMachine ve ASR decoder'i etkiler.
                // Pipeline calisiyorsa, bir sonraki chunk yeni degerleri kullanir.
                aligner?.defaultWindowSlack = s.windowSlack
                asrEngine.preferredDecoder = AsrDecoder.fromKey(s.asrDecoder)
                pipeline?.updateTunerConfig(
                    minConfidence = s.minConfidence.toDouble(),
                    minConfidenceFirstLock = s.minConfidenceFirstLock.toDouble(),
                )
                applyGlasses(s.glassesEnabled)
            }
        }

        // Gozluk: ekran durumu → GlassesState (ses seviyesi gibi alakasiz degisiklikler ayni durumu uretir, gitmez)
        viewModelScope.launch {
            _state.map { if (it.settings.glassesEnabled) glassesStateOf(it) else GlassesState() }
                .distinctUntilChanged()
                .flowOn(Dispatchers.Default)
                .collect { glasses?.update(it) }
        }

        viewModelScope.launch {
            asrEngine.state.collect { asrState ->
                val text = when (asrState) {
                    AsrState.Idle -> ""
                    AsrState.LoadingAssets -> "Modeli kopyalıyorum (~445 MB)..."
                    AsrState.InitializingModel -> "Modeli yüklüyorum..."
                    AsrState.Ready -> "Hazır"
                    is AsrState.Error -> "Hata: ${asrState.message}"
                }
                _state.update { it.copy(asrState = text) }
            }
        }

        // Mushaf'i acilista yukle — dinlemeye baslamadan once de Kuran okunabilsin/kaydirilabilsin.
        // Ilk kurulumda AssetSync modeli de kopyalar (~445 MB), o yuzden biraz surebilir.
        viewModelScope.launch {
            try {
                _state.update { it.copy(statusText = "Kuran yükleniyor...") }
                ensureMushaf()
                _state.update { if (it.statusText == "Kuran yükleniyor...") it.copy(statusText = "Hazır") else it }
            } catch (e: Throwable) {
                SessionLog.e(TAG, "Mushaf yuklenemedi", e)
                _state.update { it.copy(statusText = "Kuran yüklenemedi: ${e.message}") }
            }
        }
    }

    // ============================================================
    // GERCEK PIPELINE — mock kaldirildi
    // ============================================================
    fun toggleListening() {
        if (_state.value.isListening) stopPipeline() else startPipeline(recorder)
    }

    // ============================================================
    // SIMULASYON — kayitli WAV'i mikrofon gibi gercek zamanli oynat
    // ============================================================

    /** Simulasyon menusu acilirken uygulama ici oturum kayitlarini tazele. */
    fun refreshSimRecordings() {
        viewModelScope.launch(Dispatchers.IO) {
            val dir = getApplication<Application>().cacheDir
            val list = SessionAudioWriter.list(dir).map { SimRecording(it, SessionAudioWriter.durationSec(it)) }
            _state.update { it.copy(simRecordings = list) }
        }
    }

    /** Uygulamanin kendi oturum kaydini simule et (cacheDir/sessions — dosya seciciden gorunmuyor). */
    fun startSimulation(file: File) {
        startSimulation(file.name) { file.inputStream() }
    }

    /** Telefondan secilen dosyayi (SAF Uri) simule et. */
    fun startSimulation(uri: Uri) {
        val cr = getApplication<Application>().contentResolver
        val name = try {
            cr.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) c.getString(0) else null
            }
        } catch (e: Throwable) {
            null
        } ?: uri.lastPathSegment ?: "dosya"
        startSimulation(name) {
            cr.openInputStream(uri) ?: throw java.io.IOException("Dosya acilamadi")
        }
    }

    private fun startSimulation(name: String, open: () -> InputStream) {
        if (_state.value.isListening) stopPipeline()
        viewModelScope.launch {
            // Baslik once okunur: WAV degilse / bozuksa pipeline hic baslamaz, hata ekranda
            val info = try {
                withContext(Dispatchers.IO) { WavReader(open()).use { it.info } }
            } catch (e: Throwable) {
                SessionLog.e(TAG, "Simulasyon dosyasi okunamadi: $name", e)
                _state.update { it.copy(statusText = "Simülasyon: ${e.message ?: "dosya okunamadı"}") }
                return@launch
            }
            SessionLog.d(TAG, "Simulasyon basliyor: $name ($info)")
            startPipeline(WavFileSource(name, open), simFile = name, simDurationSec = info.durationSec.toInt())
        }
    }

    private fun startPipeline(source: FrameSource, simFile: String? = null, simDurationSec: Int = 0) {
        if (_state.value.isListening) return
        resetEzan()
        rakatTracker.reset()
        ayahStepper.cancel()   // onceki oturumun ara ayet adimlamasi yeni oturumun ekranini bozmasin

        _state.update { it.copy(
            isListening = true,
            simFile = simFile,
            simPositionSec = 0,
            simDurationSec = simDurationSec,
            statusText = "Hazırlanıyor...",
            currentAyah = null,
            tentative = false,
            hlStart = -1,
            hlEnd = -1,
            currentLabel = "",
            confidence = null,
            lastLatencyMs = null,
            surahEnded = false,
            pipelineStatus = "",
            ezan = null,
            zikir = null,
            rakatLabel = null,
            // Durum satiri dinleme bilgisini gostersin (onceki ASR testi sonucu kalmasin)
            asrLastResult = "",
            asrTimingInfo = "",
        ) }

        pipelineJob = viewModelScope.launch {
            try {
                // 1. ASR yukle
                if (asrEngine.state.value !is AsrState.Ready) {
                    _state.update { it.copy(statusText = "ASR yükleniyor...") }
                    asrEngine.initialize()
                }
                if (asrEngine.state.value !is AsrState.Ready) {
                    _state.update { it.copy(
                        isListening = false,
                        statusText = "ASR yüklenemedi",
                    ) }
                    return@launch
                }

                // 2. Aligner + Index + Meal yukle
                _state.update { it.copy(statusText = "Index yükleniyor...") }
                ensureAligner()
                ensureMushaf()

                // 3. Pipeline olustur (duyulan ses cacheDir/sessions/ altina WAV + oturum log'u olarak da kaydedilir;
                //    oturum bitince Download/Tilavet Takip'e kopyalanir — bkz. PublicRecordings)
                val app = getApplication<Application>()
                val p = AudioPipeline(source, asrEngine, quranIndex!!, aligner!!, sessionDir = app.cacheDir,
                    onSessionEnd = { onSessionEnd(app) })
                pipeline = p

                // Tuner ayarlarini settings'ten yukle
                val s = _state.value.settings
                aligner?.defaultWindowSlack = s.windowSlack
                p.updateTunerConfig(
                    minConfidence = s.minConfidence.toDouble(),
                    minConfidenceFirstLock = s.minConfidenceFirstLock.toDouble(),
                )

                // 4. Akislari bagla
                launch {
                    p.levelFlow.collect { level ->
                        _state.update { it.copy(audioLevel = level) }
                    }
                }
                launch { p.voiceTicks.collect { checkTextHold(it) } }
                if (simFile != null) {
                    launch {
                        p.audioSeconds.collect { sec -> _state.update { it.copy(simPositionSec = sec) } }
                    }
                }
                launch {
                    // Sirali olaylar: son parcanin sonucu "bitti"den once islenir
                    p.events.collect { ev ->
                        when (ev) {
                            is PipelineEvent.Chunk -> handleChunkResult(ev.pr)
                            is PipelineEvent.Ended -> onSourceEnded(ev.chunks)
                        }
                    }
                }

                // 5. Baslat
                p.start()
                _state.update { it.copy(statusText = if (simFile != null) "Simülasyon" else "Dinleniyor") }
                // Ekran kilitlenince / baska uygulamaya (G2 icin Even) gecince de dinleme sursun
                ListenService.start(app, if (simFile != null) "Simülasyon: $simFile" else "Dinleniyor")

            } catch (e: Throwable) {
                SessionLog.e(TAG, "Pipeline baslat hatasi", e)
                ListenService.stop(getApplication())
                _state.update { it.copy(
                    isListening = false,
                    statusText = "Hata: ${e.message}",
                ) }
            }
        }
    }

    private fun stopPipeline() {
        SessionLog.d(TAG, "Pipeline durduruluyor")
        pipelineJob?.cancel()
        pipeline?.stop()
        pipeline = null
        ListenService.stop(getApplication())
        resetEzan()
        _state.update { it.copy(
            isListening = false,
            simFile = null,
            statusText = "Durduruldu",
            audioLevel = 0f,
            textHidden = false,
            ezan = null,
            zikir = null,
            rakatLabel = null,
        ) }
    }

    /**
     * Mikrofon oturumu bitti (ses ve parcalar islendi, oturum log'u kapandi): kaydi + log'u dosya yoneticisinden
     * alinabilen klasore kopyala; durum satirinda nerede oldugu gorunsun. IO thread'inde cagrilir.
     */
    private fun onSessionEnd(app: Application) {
        val n = PublicRecordings.publishPending(app)
        if (n > 0) {
            val where = PublicRecordings.describe(app)
            _state.update { if (it.isListening) it else it.copy(statusText = "${it.statusText} · kayıt: $where") }
        }
    }

    /** Kaynak kendiliginden bitti: simulasyonda dosya sonu, mikrofonda kayit acilamadi/koptu. */
    private fun onSourceEnded(chunks: Int) {
        val sim = _state.value.simFile != null
        SessionLog.d(TAG, if (sim) "Simulasyon bitti ($chunks parca)" else "Mikrofon kaynagi kapandi ($chunks parca)")
        pipeline?.stop()
        pipeline = null
        ListenService.stop(getApplication())
        resetEzan()
        _state.update { it.copy(
            isListening = false,
            simFile = null,
            statusText = if (sim) "Simülasyon bitti" else "Mikrofon kapandı",
            audioLevel = 0f,
            textHidden = false,
            ezan = null,
            zikir = null,
            rakatLabel = null,
        ) }
        pipelineJob?.cancel()   // olay toplayicilari (bu coroutine dahil) biter
    }

    /**
     * Ezan / kamet penceresi (EzanTracker): kamet/ezan sinyaliyle acilir, okunan cumleyi gosterir; son cumle
     * taninca EZAN_FINAL_SHOW_MS sonra, zaman asiminda ya da Kuran'a kilitlenince hemen kapanir.
     */
    private fun handleEzan(pr: PipelineResult): EzanEvent {
        val r = pr.result
        val quranLocked = r.status == ChunkStatus.MATCHED && (r.state == NamazState.FATIHA || r.state == NamazState.ZAMM)
        val event = ezanTracker.onChunk(r.text, r.kamet, quranLocked, pr.audioEndSec)
        when (event) {
            EzanEvent.NONE -> Unit
            EzanEvent.OPEN -> {
                ezanCloseJob?.cancel()
                ezanDismissed = false
                showEzan(ezanTracker.view)
            }
            EzanEvent.CHANGED -> showEzan(ezanTracker.view)
            EzanEvent.END_FINAL -> {
                showEzan(ezanTracker.view)
                ezanCloseJob?.cancel()
                ezanCloseJob = viewModelScope.launch {
                    delay(EZAN_FINAL_SHOW_MS)
                    _state.update { it.copy(ezan = null) }
                }
            }
            EzanEvent.END_TIMEOUT, EzanEvent.END_QURAN -> {
                ezanCloseJob?.cancel()
                _state.update { it.copy(ezan = null) }
            }
        }
        return event
    }

    /**
     * Namaz zikri karti (ZikirTracker): tekbir / semiallah / rabbena / selam / namaz sonu duasi duyulunca Arapca + okunus
     * + Turkce anlami birkac saniye gosterilir. Ezan/kamet penceresi acikken (ya da bu parcada ezan olayi varken)
     * gosterilmez — kametteki tekbirler ezan penceresinde. Kuran okumasi kilitlenince kart hemen kapanir.
     */
    private fun handleZikir(pr: PipelineResult, ezanEvent: EzanEvent) {
        val r = pr.result
        val zs = zikirTracker.onChunk(r, pr.audioEndSec)
        val quranLocked = r.status == ChunkStatus.MATCHED && (r.state == NamazState.FATIHA || r.state == NamazState.ZAMM)
        if (quranLocked && _state.value.zikir != null) dismissZikir()
        if (zs.isEmpty() || ezanEvent != EzanEvent.NONE || _state.value.ezan != null) return
        SessionLog.d(TAG, "[zikir] t=${"%.1f".format(pr.audioEndSec)}s ${zs.joinToString(",")}")
        zikirJob?.cancel()
        zikirJob = viewModelScope.launch {
            for ((i, z) in zs.withIndex()) {
                _state.update { it.copy(zikir = z) }
                delay(if (i < zs.lastIndex) ZIKIR_STEP_MS else ZIKIR_SHOW_MS)
            }
            _state.update { it.copy(zikir = null) }
        }
    }

    /** Zikir karti kapat (dokunma / carpi ya da Kuran okumasi basladi). */
    fun dismissZikir() {
        zikirJob?.cancel()
        _state.update { it.copy(zikir = null) }
    }

    private fun showEzan(v: EzanView?) {
        if (!ezanDismissed) _state.update { it.copy(ezan = v) }
    }

    /** Kullanici pencereyi kapatti (carpi / yana surukleme): bu ezan/kamet bitene kadar tekrar acilmaz. */
    fun dismissEzan() {
        ezanDismissed = true
        ezanCloseJob?.cancel()
        _state.update { it.copy(ezan = null) }
    }

    private fun resetEzan() {
        ezanTracker.reset()
        ezanCloseJob?.cancel()
        ezanDismissed = false
        zikirTracker.reset()
        zikirJob?.cancel()
    }

    /**
     * StateMachine'den gelen sonucu UI'a yansit.
     *
     * Mushaf'ta konum: MATCHED → kilitli ayet; PENDING → aday ayet (tentative, dogrulama bekleniyor —
     * kullanici ilk chunk'tan itibaren nerede oldugunu gorur, yanlis adayda bir sonraki chunk duzeltir).
     * Okunan ayet = eslesmenin son kelimesinin ayeti (imam o an orada).
     *
     * Sonraki ayete on-kaydirma (APK #11-24: son kelime duyulunca ekran sonraki ayete gecerdi) KALDIRILDI:
     * kullanici "onceki ayet okunmadan sonrakine geciyor" dedi; ekran hep okunan ayette kalir, sonraki ayet
     * okununca (hizli algilama ile) kilitlenir. eval'deki "on-kaydirma" sutunlari sadece tani amacli.
     *
     * Kilitliyken gelen sure gecisi adayi (jumpCandidate) ekrani KAYDIRMAZ: dogrulanmamis aday bozuk bir
     * parcadan da gelebiliyor (telefon testi: "شعور وما لا" → ekran Kureys'ten 22:12'ye zipliyordu) ve
     * kullanici bunu yanlis kilit olarak goruyor. Gercek gecis bir sonraki parcada dogrulanip kayar.
     * Kilit oncesi (BEKLEME) ve kilit kaybi sonrasi adaylar gosterilmeye devam eder; ama belirsiz aday
     * (`ambiguous`: ikinci yer neredeyse ayni iyi, "قل أعوذ برب" 113:1 / 114:1) gosterilmez — yazi tura atmak olur,
     * ekran yanlis sureye kayiyordu. Dogrulaninca (sonraki parca) kayar.
     *
     * Atlanan ayetler (AyahStepper): kilitli eslesme ayni surede birden fazla ayet ileri giderse (ör. 1:2 → 1:5)
     * ya da yeni sureye basindan birkac ayet sonra kilitlendiyse (ör. Fatiha → 103:3) atlanan ayetler sirayla ayar
     * kadar (`skippedAyahTenths`, 0-2 sn) gosterilir, sonra okunan ayete gecilir.
     */
    /** Ekrandaki ayetin son guncellenme ani (oturumdaki sn) — bkz. TextHold. */
    private var shownAtSec = 0.0

    private fun markShown() {
        shownAtSec = pipeline?.voiceTicks?.value?.nowSec ?: 0.0
    }

    /**
     * Ses kesilince okunan ayetin metnini kaldir (telefonda vurgu + alt bar etiketi, G2'de bos ekran + ust satirda rekat).
     * Hem son konusmadan hem ayetin son guncellenmesinden Ayarlar → SES KESİLİNCE METİN suresi gecince; yeni okuma
     * eslesince metin geri gelir. Bkz. VoiceActivity / TextHold.
     */
    private fun checkTextHold(tick: VoiceTick) {
        val s = _state.value
        if (s.textHidden || s.currentAyah == null || !s.isListening) return
        val holdSec = s.settings.textHoldTenths.coerceIn(0, TextHold.MAX_TENTHS) / 10.0
        if (!TextHold.shouldHide(tick.nowSec, tick.lastVoiceSec, shownAtSec, holdSec)) return
        SessionLog.d(TAG, "[metin] t=${"%.1f".format(tick.nowSec)}s ses kesildi (son ses " +
            (if (tick.lastVoiceSec.isFinite()) "%.1f".format(tick.lastVoiceSec) else "-") +
            "s), metin kalkti (bekleme ${"%.1f".format(holdSec)} sn)")
        _state.update { it.copy(textHidden = true) }
    }

    private fun handleChunkResult(pr: PipelineResult) {
        val result = pr.result
        handleZikir(pr, handleEzan(pr))
        rakatTracker.onChunk(result, pr.audioEndSec)?.let { SessionLog.d(TAG, "[rekat] t=${"%.1f".format(pr.audioEndSec)}s $it") }
        val rakatLabel = rakatTracker.label(pr.audioEndSec)
        if (rakatLabel != _state.value.rakatLabel) _state.update { it.copy(rakatLabel = rakatLabel) }
        val latencyMs = (System.nanoTime() - pr.audioEndNanos) / 1_000_000L
        val candidateKind = when {
            result.jumpCandidate -> "gecis adayi"
            result.ambiguous -> "belirsiz aday"
            else -> "aday"
        }
        val statusText = when (result.status) {
            ChunkStatus.MATCHED -> "[${result.state.name}]"
            ChunkStatus.PENDING -> "[${result.state.name}] $candidateKind: ${result.pendingSurah}:${result.pendingAyah}"
            ChunkStatus.LOW_CONFIDENCE -> "[${result.state.name}] dusuk guven"
            ChunkStatus.SILENT -> "[${result.state.name}] sessiz"
            ChunkStatus.EMPTY -> "[${result.state.name}] " + if (result.kamet) "kamet: Fatiha bekleniyor" else "bos"
            ChunkStatus.TOO_SHORT -> "[${result.state.name}] kisa"
        }

        val mushaf = _state.value.mushaf
        val start = result.matchStartWordIdx
        val end = result.matchEndWordIdx
        val positioned = mushaf != null && start != null && end != null &&
                (result.status == ChunkStatus.MATCHED ||
                    (result.status == ChunkStatus.PENDING && !result.jumpCandidate && !result.ambiguous))

        if (result.kamet) {
            // Kamet: onceki (kametten once olusmus, muhtemelen yanlis) kilidin vurgusu silinir; liste yerinde kalir
            ayahStepper.cancel()
            _state.update { cur ->
                cur.copy(
                    statusText = statusText,
                    pipelineStatus = result.status.name,
                    currentAyah = null,
                    tentative = false,
                    hlStart = -1,
                    hlEnd = -1,
                    currentLabel = "",
                    confidence = null,
                    lastLatencyMs = latencyMs,
                )
            }
            return
        }
        if (!positioned) {
            // Konum yok (bos / kisa / dusuk guven / gecis adayi / belirsiz aday): ekran ve suren adimlama oldugu gibi kalir
            _state.update { it.copy(statusText = statusText, pipelineStatus = result.status.name, lastLatencyMs = latencyMs) }
            return
        }

        val m = mushaf!!
        val ayah = m.ayahOfWord(end!!)
        val tentative = result.status == ChunkStatus.PENDING
        val atTarget: (UiState) -> UiState = { cur ->
            markShown()
            cur.copy(
                currentAyah = ayah,
                tentative = tentative,
                hlStart = start!!,
                hlEnd = end,
                currentLabel = m.ayahTag(ayah),
                textHidden = false,
            )
        }

        _state.update { it.copy(
            statusText = statusText,
            pipelineStatus = result.status.name,
            confidence = result.confidence?.toInt(),
            lastLatencyMs = latencyMs,
        ) }
        // Ekrandaki ayetten (adimlama surerken ekrandaki ara ayet) hedefe; ara ayet tamami vurgulu
        // (imam okudu, biz duyamadik ya da tek parcada gecti)
        val stepMs = _state.value.settings.skippedAyahTenths.coerceIn(0, 20) * 100L
        val skipped = ayahStepper.moveTo(
            mushaf = m,
            shown = _state.value.currentAyah,
            target = ayah,
            locked = result.status == ChunkStatus.MATCHED,
            stepMs = stepMs,
            showSkipped = { a ->
                markShown()
                _state.update { it.copy(
                    currentAyah = a,
                    tentative = false,
                    hlStart = m.firstShownWord(a),
                    hlEnd = m.lastWordOf(a),
                    currentLabel = m.ayahTag(a),
                    textHidden = false,
                ) }
            },
            showTarget = { _state.update(atTarget) },
        )
        if (!skipped.isEmpty()) {
            SessionLog.d(TAG, "ara ayetler: ${m.label(skipped.first)} .. ${m.label(skipped.last)} → ${m.label(ayah)} " +
                    "(${stepMs}ms/ayet)")
        }
    }

    // ============================================================
    // ASR Test
    // ============================================================
    fun runAsrTest() {
        if (_state.value.asrInProgress) return
        asrJob?.cancel()
        asrJob = viewModelScope.launch {
            try {
                _state.update { it.copy(asrInProgress = true, asrLastResult = "", asrTimingInfo = "") }
                if (asrEngine.state.value !is AsrState.Ready) asrEngine.initialize()

                _state.update { it.copy(asrLastResult = "5 saniye kayıt...") }
                val audio = recordAudio5Seconds()
                if (audio == null) {
                    _state.update { it.copy(asrInProgress = false, asrLastResult = "Kayıt başarısız") }
                    return@launch
                }

                _state.update { it.copy(asrLastResult = "Çözümleniyor...") }
                val result = asrEngine.transcribe(audio)

                _state.update { it.copy(
                    asrInProgress = false,
                    asrLastResult = if (result.text.isBlank()) "(boş çıktı)" else result.text,
                    // Durum satirinda tek satir: kisa bicim (decoder + sure)
                    asrTimingInfo = "${result.decoder} ${result.inferenceMs}ms",
                ) }
            } catch (e: Throwable) {
                SessionLog.e(TAG, "ASR test hatasi", e)
                _state.update { it.copy(asrInProgress = false, asrLastResult = "Hata: ${e.message}") }
            }
        }
    }

    @RequiresPermission(android.Manifest.permission.RECORD_AUDIO)
    private suspend fun recordAudio5Seconds(): FloatArray? = withContext(Dispatchers.IO) {
        if (!recorder.hasPermission()) return@withContext null
        val sampleRate = 16000
        val totalSamples = sampleRate * 5

        val minBuffer = AudioRecord.getMinBufferSize(sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val bufferSize = maxOf(minBuffer, sampleRate * 2)

        val record = try {
            AudioRecord(MediaRecorder.AudioSource.MIC, sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, bufferSize)
        } catch (e: SecurityException) { return@withContext null }

        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release(); return@withContext null
        }

        try {
            record.startRecording()
            val pcm = ShortArray(totalSamples)
            var read = 0
            while (read < totalSamples) {
                val n = record.read(pcm, read, totalSamples - read)
                if (n <= 0) break
                read += n
            }
            record.stop()
            val out = FloatArray(read)
            for (i in 0 until read) out[i] = pcm[i].toFloat() / 32768f
            return@withContext out
        } finally { record.release() }
    }

    // ============================================================
    // Tests
    // ============================================================
    fun runAlignerTest() {
        alignerJob?.cancel()
        alignerJob = viewModelScope.launch(Dispatchers.IO) {
            try {
                _state.update { it.copy(alignerState = "Yükleniyor...", alignerResult = "") }
                ensureAligner()
                val al = aligner!!
                _state.update { it.copy(alignerState = "Test çalışıyor...") }
                val ctx = getApplication<Application>()
                val summary = AlignerTestRunner.runAll(ctx, al)
                val text = AlignerTestRunner.formatSummary(summary)
                _state.update { it.copy(
                    alignerState = if (summary.failedCases.isEmpty()) "Tüm test'ler geçti ✓" else "Bazıları başarısız",
                    alignerResult = text,
                ) }
            } catch (e: Throwable) {
                SessionLog.e(TAG, "Aligner test hatasi", e)
                _state.update { it.copy(alignerState = "Hata", alignerResult = "Hata: ${e.message}\n${e.stackTraceToString().take(800)}") }
            }
        }
    }

    fun runStateMachineTest() {
        stateMachineJob?.cancel()
        stateMachineJob = viewModelScope.launch(Dispatchers.IO) {
            try {
                _state.update { it.copy(stateMachineState = "Yükleniyor...", stateMachineResult = "") }
                ensureAligner()
                val al = aligner!!
                val idx = quranIndex!!
                _state.update { it.copy(stateMachineState = "Test çalışıyor...") }
                val ctx = getApplication<Application>()
                val summary = StateMachineTestRunner.runAll(ctx, idx, al)
                val text = StateMachineTestRunner.formatSummary(summary)
                _state.update { it.copy(
                    stateMachineState = if (summary.failedChecks.isEmpty()) "Tüm chunk'lar geçti ✓" else "Bazıları başarısız",
                    stateMachineResult = text,
                ) }
            } catch (e: Throwable) {
                SessionLog.e(TAG, "StateMachine test hatasi", e)
                _state.update { it.copy(
                    stateMachineState = "Hata",
                    stateMachineResult = "Hata: ${e.message}\n${e.stackTraceToString().take(800)}",
                ) }
            }
        }
    }

    fun runFuzzyTest() {
        fuzzyJob?.cancel()
        fuzzyJob = viewModelScope.launch(Dispatchers.Default) {
            try {
                _state.update { it.copy(fuzzyState = "Calisiyor...", fuzzyResult = "") }
                val ctx = getApplication<Application>()
                val summary = FuzzyTestRunner.runAll(ctx)
                val text = FuzzyTestRunner.formatSummary(summary)
                _state.update { it.copy(
                    fuzzyState = if (summary.failedCases.isEmpty()) "Tüm test'ler geçti ✓" else "Bazıları başarısız",
                    fuzzyResult = text,
                ) }
            } catch (e: Throwable) {
                SessionLog.e(TAG, "Fuzzy test hatasi", e)
                _state.update { it.copy(fuzzyState = "Hata", fuzzyResult = "Hata: ${e.message}") }
            }
        }
    }

    private suspend fun ensureQuranIndex() = withContext(Dispatchers.IO) {
        loadMutex.withLock {
            if (quranIndex != null) return@withLock
            // Yeni APK'daki quran.bin'i (ve degistiyse modeli) filesDir'e senkronla
            val asrDir = AssetSync.sync(getApplication<Application>())
            quranIndex = QuranIndex.load(File(asrDir, QURAN_BIN).absolutePath)
        }
    }

    private suspend fun ensureAligner() {
        if (aligner != null) return
        ensureQuranIndex()
        aligner = Aligner(quranIndex!!)
    }

    private suspend fun ensureMealLoader() = withContext(Dispatchers.IO) {
        loadMutex.withLock {
            if (mealLoader != null) return@withLock
            val asrDir = AssetSync.sync(getApplication<Application>())
            mealLoader = MealLoader.load(File(asrDir, MEAL_BIN).absolutePath)
        }
    }

    /** QuranIndex + MealLoader → MushafData (UI'daki tum Kuran listesi). */
    private suspend fun ensureMushaf() {
        if (_state.value.mushaf != null) return
        ensureQuranIndex()
        ensureMealLoader()
        val data = withContext(Dispatchers.IO) {
            loadMutex.withLock {
                _state.value.mushaf ?: MushafData.build(quranIndex!!, mealLoader)
            }
        }
        _state.update { if (it.mushaf == null) it.copy(mushaf = data) else it }
    }

    fun openSettings() { _state.update { it.copy(showSettingsSheet = true) } }
    fun closeSettings() { _state.update { it.copy(showSettingsSheet = false) } }
    fun setTheme(theme: AppTheme) { viewModelScope.launch { settingsRepo.setTheme(theme) } }
    fun setArabicSize(size: Int) { viewModelScope.launch { settingsRepo.setArabicSize(size) } }
    fun setMealSize(size: Int) { viewModelScope.launch { settingsRepo.setMealSize(size) } }
    fun setMotion(motion: Float) { viewModelScope.launch { settingsRepo.setMotion(motion) } }
    fun setIdleOpacity(opacity: Int) { viewModelScope.launch { settingsRepo.setIdleOpacity(opacity) } }
    fun setSkippedAyahTenths(value: Int) { viewModelScope.launch { settingsRepo.setSkippedAyahTenths(value) } }
    fun setGlassesEnabled(value: Boolean) { viewModelScope.launch { settingsRepo.setGlassesEnabled(value) } }
    fun setGlassesArabic(value: Boolean) { viewModelScope.launch { settingsRepo.setGlassesArabic(value) } }
    fun setGlassesBigText(value: Boolean) { viewModelScope.launch { settingsRepo.setGlassesBigText(value) } }
    fun setGlassesTextPx(value: Int) { viewModelScope.launch { settingsRepo.setGlassesTextPx(value) } }
    fun setGlassesBigHeader(value: Boolean) { viewModelScope.launch { settingsRepo.setGlassesBigHeader(value) } }
    fun setGlassesFixedSize(value: Boolean) { viewModelScope.launch { settingsRepo.setGlassesFixedSize(value) } }
    fun setGlassesHideRakat(value: Boolean) { viewModelScope.launch { settingsRepo.setGlassesHideRakat(value) } }
    fun setGlassesOnePage(value: Boolean) { viewModelScope.launch { settingsRepo.setGlassesOnePage(value) } }
    fun setGlassesOnePageMinPx(value: Int) { viewModelScope.launch { settingsRepo.setGlassesOnePageMinPx(value) } }
    fun setGlassesHideBlankHeader(value: Boolean) { viewModelScope.launch { settingsRepo.setGlassesHideBlankHeader(value) } }
    fun setGlassesHideStatus(value: Boolean) { viewModelScope.launch { settingsRepo.setGlassesHideStatus(value) } }
    fun setTextHoldTenths(value: Int) { viewModelScope.launch { settingsRepo.setTextHoldTenths(value) } }
    fun setMinConfidence(value: Int) { viewModelScope.launch { settingsRepo.setMinConfidence(value) } }
    fun setMinConfidenceFirstLock(value: Int) { viewModelScope.launch { settingsRepo.setMinConfidenceFirstLock(value) } }
    fun setWindowSlack(value: Int) { viewModelScope.launch { settingsRepo.setWindowSlack(value) } }
    fun setAsrDecoder(value: String) { viewModelScope.launch { settingsRepo.setAsrDecoder(value) } }

    /**
     * Logcat'i dosyaya yaz, son oturumun ses kaydiyla (WAV) birlikte share intent ac.
     * WAV + log → data/'ya konunca eval_pipeline.py ile telefonsuz tekrar oynatilabilir.
     */
    fun exportLog() {
        viewModelScope.launch(Dispatchers.IO) {
            val ctx = getApplication<Application>()
            val file = LogExporter.export(ctx)
            val wav = SessionAudioWriter.latest(ctx.cacheDir)
            val files = listOfNotNull(file?.takeIf { it.exists() }, wav)
            if (files.isNotEmpty()) {
                withContext(Dispatchers.Main) {
                    LogExporter.share(ctx, files)
                }
            } else {
                SessionLog.e(TAG, "Log export basarisiz")
            }
        }
    }

    // ============================================================
    // G2 GOZLUK — bkz. glasses/GlassesBridge, assets/g2 (Even Hub eklentisi)
    // ============================================================

    /** Ayardaki G2 anahtari: kopruyu ac / kapat (ayni durumdaysa bir sey yapmaz). Soket isi ana thread'de olmasin. */
    private fun applyGlasses(enabled: Boolean) {
        viewModelScope.launch(Dispatchers.IO) { glassesMutex.withLock { applyGlassesLocked(enabled) } }
    }

    private fun applyGlassesLocked(enabled: Boolean) {
        if (enabled && glasses == null) {
            val b = GlassesBridge(files = ::glassesFile, log = { SessionLog.d(TAG, "[g2] $it") })
            if (!b.start()) {
                _state.update { it.copy(glassesLink = "açılamadı (port ${GlassesBridge.DEFAULT_PORT} kullanımda)") }
                return
            }
            b.update(glassesStateOf(_state.value))
            glasses = b
            glassesLinkJob?.cancel()
            glassesLinkJob = viewModelScope.launch {
                var was = false
                while (true) {
                    val now = b.clientConnected()
                    if (now != was) SessionLog.d(TAG, if (now) "[g2] eklenti baglandi" else "[g2] eklenti baglantisi yok")
                    was = now
                    // tani: eklentiden kopruye hic istek gelmiyorsa engel Even uygulamasinda (bkz. GlassesBridge /ping.png)
                    val text = when {
                        // eski .ehpk kodu ciziyor (2: kopru adresine gecip hata sayfasinda kaliyor, 0: yazi boyutu yok)
                        now && b.clientVersion in 0 until GlassesBridge.PLUGIN_VERSION ->
                            "bağlı · eski eklenti (.ehpk'yi güncelleyin)"
                        now -> "bağlı" + screenLabel(b.clientScreen) +
                            (b.clientPackage.takeIf { it.isNotEmpty() }?.let { " · eklenti $it" } ?: "")
                        b.requestCount == 0 -> "eklenti bekleniyor · istek yok"
                        else -> "eklenti bekleniyor · son istek " +
                            "${(System.currentTimeMillis() - b.lastRequestMs) / 1000} sn önce"
                    }
                    if (_state.value.glassesLink != text) _state.update { it.copy(glassesLink = text) }
                    delay(GLASSES_LINK_POLL_MS)
                }
            }
        } else if (!enabled && glasses != null) {
            glassesLinkJob?.cancel()
            glasses?.stop()
            glasses = null
            _state.update { it.copy(glassesLink = null) }
        } else if (!enabled && _state.value.glassesLink != null) {
            _state.update { it.copy(glassesLink = null) }
        }
    }

    /** Eklentinin bildirdigi duzen → ayarlardaki baglanti satirina ek: " · büyük yazı 48 px" (bilinmiyorsa bos). */
    private fun screenLabel(desc: String): String {
        val parts = desc.split(' ')
        return when (parts[0]) {
            "buyuk" -> " · büyük yazı" + (parts.getOrNull(1)?.removeSuffix("px")?.toIntOrNull()?.let { " $it px" } ?: "") +
                (if ("sabit" in parts.drop(2)) " sabit" else "") + (if ("tek" in parts.drop(2)) " tek sayfa" else "")
            "normal" -> " · normal yazı"
            "arapca" -> " · arapça + meal"
            else -> ""
        }
    }

    /** Eklenti dosyalari (assets/g2) + fontlar (Arapca goruntu, buyuk yazi); bir kez okunup tutulur. */
    private fun glassesFile(name: String): ByteArray? {
        synchronized(glassesFileCache) {
            glassesFileCache[name]?.let { return it }
            val app = getApplication<Application>()
            val data = try {
                when (name) {
                    // eklenti fontlari: Arapca goruntu (KFGQPC) ve buyuk yazi (Manrope 700)
                    "kfgqpc.ttf" -> app.resources.openRawResource(R.font.kfgqpc_hafs).use { it.readBytes() }
                    "manrope.ttf" -> app.resources.openRawResource(R.font.manrope_700).use { it.readBytes() }
                    else -> app.assets.open("g2/$name").use { it.readBytes() }
                }
            } catch (e: Exception) {
                null
            }
            if (data != null) glassesFileCache[name] = data
            return data
        }
    }

    /** Ekran durumu → gozluk durumu: okunan ayet (adimlanan ara ayet dahil), meal, rekat, zikir / ezan karti. */
    private fun glassesStateOf(s: UiState): GlassesState {
        val ezan = s.ezan
        val zikir = s.zikir
        val (noteTitle, noteReading, noteTurkish) = when {
            ezan != null -> Triple(ezan.title, ezan.current?.reading ?: "", ezan.current?.turkish ?: "")
            zikir != null -> Triple(zikir.title, zikir.reading, zikir.turkish)
            else -> Triple("", "", "")
        }
        val status = when {
            !s.isListening -> s.statusText
            s.statusText.contains("kamet") -> "Kamet · Fatiha bekleniyor"
            s.statusText.startsWith("[") -> if (s.simFile != null) "Simülasyon" else "Dinleniyor"
            else -> s.statusText
        }
        val base = GlassesState(
            listening = s.isListening,
            sim = s.simFile != null,
            status = status,
            showArabic = s.settings.glassesArabic,
            bigText = s.settings.glassesBigText,
            textPx = s.settings.glassesTextPx,
            bigHeader = s.settings.glassesBigHeader,
            hideRakat = s.settings.glassesHideRakat,
            fixedSize = s.settings.glassesFixedSize,
            onePage = s.settings.glassesOnePage,
            onePageMinPx = s.settings.glassesOnePageMinPx,
            blankHeader = !s.settings.glassesHideBlankHeader,
            hideStatus = s.settings.glassesHideStatus,
            rakat = s.rakatLabel ?: "",
            noteTitle = noteTitle,
            noteReading = noteReading,
            noteTurkish = noteTurkish,
        )
        // Ses kesildi: ayet metni yok, gozlukte bos ekran / ust satirda rekat (zikir / ezan karti varsa o gosterilir)
        if (s.textHidden && s.isListening) return base.copy(blank = true)
        val m = s.mushaf ?: return base
        val a = s.currentAyah ?: return base
        val surah = m.surahOf(a)
        val first = m.firstShownWord(a)
        val last = m.lastWordOf(a)
        val progress = if (s.hlEnd in first..last) (s.hlEnd - first + 1).toDouble() / (last - first + 1) else 0.0
        return base.copy(
            surah = surah,
            ayah = m.ayahNumber(a),
            surahName = m.surahNameTr(surah),
            surahAyahCount = m.surahAyahCount(surah),
            tentative = s.tentative,
            progress = progress,
            meal = m.meal(a) ?: "",
            arabic = if (s.settings.glassesArabic) m.words(a).joinToString(" ") + " " + arabicDigits(m.ayahNumber(a)) else "",
        )
    }

    override fun onCleared() {
        super.onCleared()
        glassesLinkJob?.cancel()
        glasses?.stop()
        glasses = null
        stopPipeline()
        recorder.stop()
        asrEngine.close()
        quranIndex?.close()
        mealLoader?.close()
    }
}
