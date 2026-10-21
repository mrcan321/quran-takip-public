package com.tilavet.takip.session

/**
 * app.py'deki NamazState enum + SessionState dataclass'larin Kotlin port'u.
 */

enum class NamazState {
    BEKLEME,
    FATIHA,
    ZAMM,
    ARA,
}

/**
 * Bekleyen aday match.
 *
 * BEKLEME state'inde ilk match bulundugunda hemen kilitleyemiyoruz —
 * bir sonraki chunk'ta dogrulanmasi lazim. Bu data class o adayin
 * detaylarini tutar.
 */
data class PendingMatch(
    val surah: Int,
    val ayah: Int,
    val wordIndex: Int,
    val chunkIndex: Int,
    /** Belirsiz aday: ikinci yerin son ayeti — geriye giden parca dogrulamaz (StateMachine, asr 21.10) */
    val altSurah: Int? = null,
    val altAyah: Int? = null,
)

/**
 * Bir oturum (namaz) suresince state machine'in tum durum bilgisi.
 * app.py'deki SessionState dataclass ile birebir.
 */
data class SessionState(
    var state: NamazState = NamazState.BEKLEME,
    var lastWordIndex: Int? = null,
    var lastSurah: Int? = null,
    var lastAyah: Int? = null,
    var lostChunks: Int = 0,
    var totalChunks: Int = 0,
    var matchedChunks: Int = 0,
    val stateTransitions: MutableList<String> = mutableListOf(),
    var pendingMatch: PendingMatch? = null,
    /** Kilitliyken pencere disinda bulunan aday konum (sure gecisi) — sonraki chunk dogrularsa gecilir. */
    var jumpCandidate: PendingMatch? = null,
    /** Kilitli suredeki en ileri ayet (geri dogru cop eslesmeler dogal gecis kararini bozmasin). */
    var maxAyah: Int? = null,
    /**
     * Namaz sinyali beklemesi (kamet / rukû / selam): bu parca indeksine kadar sadece Fatiha ya da kalinan
     * yerden devam kilitlenir (StateMachine.KAMET_HOLD_CHUNKS).
     */
    var holdUntil: Int? = null,
    /** BEKLEME'de kilit vermeyen son parcalarin temiz metni: (parca indeksi, metin) — StateMachine.SEARCH_CONCAT_CHUNKS. */
    var searchTexts: List<Pair<Int, String>> = emptyList(),
    /** Son zamm konumu (hatimle teravihte sonraki rekat buradan devam eder) — StateMachine.CONTINUE_AHEAD; selam/kamette silinmez. */
    var zammSurah: Int? = null,
    var zammAyah: Int? = null,
    /** Son "sadece tekbir" parcasinin indeksi — StateMachine.TEKBIR_TEVHID_CHUNKS. */
    var lastTekbirChunk: Int? = null,
)

/**
 * Bir chunk islemenin sonucu. UI ve loglama icin.
 */
data class ChunkResult(
    val chunkIndex: Int,
    val stateBefore: NamazState,
    val state: NamazState,
    val status: ChunkStatus,
    val rms: Double,
    val text: String? = null,
    val reason: String? = null,
    val confidence: Double? = null,
    val wordCount: Int? = null,
    // Match bulunduysa
    val verses: List<VerseRef>? = null,
    val matchStartWordIdx: Int? = null,
    val matchEndWordIdx: Int? = null,
    // Pending durumunda
    val pendingSurah: Int? = null,
    val pendingAyah: Int? = null,
    /** Kilitliyken baska yere gecis adayi (PENDING): kilit yerinde kalir, sonraki chunk dogrulamazsa duser. */
    val jumpCandidate: Boolean = false,
    /**
     * Belirsiz aday (PENDING, BEKLEME / kilit kaybi): ikinci yer (araliga degmeyen) AMBIGUOUS_MARGIN'den yakin
     * ("قل أعوذ برب" 113:1 / 114:1) — UI ekrani kaydirmaz; aday dogrulaninca kayar. State machine karari etkilenmez.
     */
    val ambiguous: Boolean = false,
    /** Kamet/ezan algilandi (EMPTY): onceki kilit silindi, Fatiha bekleniyor — UI vurguyu temizler. */
    val kamet: Boolean = false,
    /** Tilavet sonu "صدق الله العظيم" (EMPTY): kilit / adaylar bitti — UI vurguyu temizler (kamet gibi, ezan / rekat yok). */
    val tilavetEnd: Boolean = false,
    // Diagnostics
    val preferredRange: IntRange? = null,
    val inPreferred: Boolean = false,
    val nearSurahEnd: Boolean = false,
    val lockAbandoned: Boolean = false,
    val gapFilled: Int = 0,
)

enum class ChunkStatus {
    SILENT,        // RMS dusuk, ses yok
    EMPTY,         // ASR bos string dondurdu
    TOO_SHORT,     // Kelime sayisi yetersiz
    LOW_CONFIDENCE, // Skor esik altinda
    PENDING,       // Aday bulundu ama dogrulama bekleniyor
    MATCHED,       // Eslesme bulundu, state guncellendi
}

/**
 * Bir ayet referansi (sure_no, ayet_no).
 */
data class VerseRef(
    val surah: Int,
    val ayah: Int,
    /** Match'ten gelen kelimeler (UI highlight icin) */
    val matchedFromAlignment: Boolean = true,
)
