package com.tilavet.takip.asr

/**
 * ASR decoder secimi.
 *
 * CTC  — encoder + CTC head, argmax + collapse. Hizli ama kelime birlestirebiliyor
 *        ("الرحمن الرحيم" → "الرَّحْمَنَِّحِيمِ").
 * RNNT — ayni encoder + LSTM prediction network + joint, greedy (NeMo GreedyRNNTInfer ile ayni).
 *        Server/benchmark bunu kullaniyor. eval.yml: medyan skor 79.2 → 91.5, ≥90 chunk 39 → 65.
 */
enum class AsrDecoder {
    CTC,
    RNNT;

    companion object {
        fun fromKey(key: String?): AsrDecoder =
            values().firstOrNull { it.name.equals(key, ignoreCase = true) } ?: RNNT
    }
}

/**
 * ASR motoru tarafindan dondurulen sonuc.
 */
data class AsrResult(
    val text: String,
    val tokenIds: IntArray,
    val numTokens: Int,
    val inferenceMs: Long,
    val audioDurationMs: Long,
    val decoder: AsrDecoder = AsrDecoder.CTC,
) {
    val rtf: Float
        get() = if (audioDurationMs > 0) inferenceMs.toFloat() / audioDurationMs else 0f

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is AsrResult) return false
        return text == other.text &&
                tokenIds.contentEquals(other.tokenIds) &&
                numTokens == other.numTokens &&
                inferenceMs == other.inferenceMs &&
                audioDurationMs == other.audioDurationMs &&
                decoder == other.decoder
    }

    override fun hashCode(): Int {
        var result = text.hashCode()
        result = 31 * result + tokenIds.contentHashCode()
        result = 31 * result + numTokens
        result = 31 * result + inferenceMs.hashCode()
        result = 31 * result + audioDurationMs.hashCode()
        result = 31 * result + decoder.hashCode()
        return result
    }
}

/**
 * Engine yukleme/calistirma sirasindaki durum.
 */
sealed class AsrState {
    object Idle : AsrState()
    object LoadingAssets : AsrState()       // Asset'leri internal storage'a kopyaliyor
    object InitializingModel : AsrState()   // ONNX session olusturuyor
    object Ready : AsrState()
    data class Error(val message: String, val cause: Throwable? = null) : AsrState()
}
