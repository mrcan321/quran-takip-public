package com.tilavet.takip.asr

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.util.Log
import com.tilavet.takip.util.AssetSync
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.nio.FloatBuffer
import java.nio.LongBuffer

/**
 * FastConformer Hybrid ASR motoru (CTC veya RNNT greedy).
 *
 * Python referansi: scripts/onnx_asr.py (ayni dongu, NeMo ile birebir dogrulandi).
 *
 * Sorumluluklari:
 *   1. Asset'leri (~460 MB) internal storage'a senkronla (AssetSync — yeni APK'da degisen model gelir)
 *   2. ONNX Runtime session'lari: ana graph + (model v2+) RNNT decoder ve joint
 *   3. Raw audio → transkripsiyon
 *      CTC : logprobs argmax + collapse
 *      RNNT: enc_proj uzerinde greedy (her frame en fazla max_symbols token)
 *   4. SentencePiece detokenize
 *
 * Asset dosyalari (assets/asr/ altinda):
 *   - fastconformer_full.onnx (+ .data)  audio → logprobs [+ enc_proj, enc_len]
 *   - rnnt_decoder.onnx, rnnt_joint.onnx  (model v2+)
 *   - tokenizer.model, meta.json
 *
 * Thread safety: transcribe() tek coroutine'den (AudioPipeline chunk consumer) cagrilir.
 */
class OnnxAsrEngine(private val context: Context) {

    companion object {
        private const val TAG = "OnnxAsrEngine"

        // ONEMLI: ONNX graph dosyasi icinde external weight dosyasinin adi
        // sabit olarak "fastconformer_full.onnx.data" olarak yazili (AssetSync bu isimle kopyalar).
        private const val MODEL = "fastconformer_full.onnx"
        private const val RNNT_DECODER = "rnnt_decoder.onnx"
        private const val RNNT_JOINT = "rnnt_joint.onnx"
        private const val TOKENIZER = "tokenizer.model"
        private const val META = "meta.json"

        // Ana graph I/O
        private const val INPUT_AUDIO = "audio_signal"
        private const val INPUT_LENGTH = "length"
        private const val OUTPUT_LOGPROBS = "logprobs"
        private const val OUTPUT_ENC_PROJ = "enc_proj"
        private const val OUTPUT_ENC_LEN = "enc_len"
    }

    private val _state = MutableStateFlow<AsrState>(AsrState.Idle)
    val state: StateFlow<AsrState> = _state.asStateFlow()

    private var ortEnv: OrtEnvironment? = null
    private var session: OrtSession? = null
    private var decoderSession: OrtSession? = null
    private var jointSession: OrtSession? = null
    private var tokenizer: SentencePieceDecoder? = null
    private var blankIdx: Int = 1024
    private var sampleRate: Int = 16000
    private var hasEncLen = false

    // RNNT boyutlari (meta.json "rnnt")
    private var rnntLayers = 1
    private var rnntHidden = 640
    private var rnntMaxSymbols = 10

    /** Kullanicinin sectigi decoder (tuner). RNNT yoksa CTC'ye duser. */
    @Volatile
    var preferredDecoder: AsrDecoder = AsrDecoder.RNNT

    val rnntAvailable: Boolean
        get() = decoderSession != null && jointSession != null

    /** Bir sonraki transcribe()'in kullanacagi decoder. */
    val activeDecoder: AsrDecoder
        get() = if (preferredDecoder == AsrDecoder.RNNT && rnntAvailable) AsrDecoder.RNNT else AsrDecoder.CTC

    /**
     * Engine'i ilk kez yukler. Tekrar cagrildiginda zaten yukli ise hizla doner.
     */
    suspend fun initialize() = withContext(Dispatchers.IO) {
        if (session != null) {
            Log.d(TAG, "initialize: zaten yukli")
            return@withContext
        }

        try {
            _state.value = AsrState.LoadingAssets

            // 1. Asset'leri internal storage'a senkronla (yeni APK'da model degistiyse kopyalar)
            val asrDir = AssetSync.sync(context)
            val modelFile = File(asrDir, MODEL)
            val decFile = File(asrDir, RNNT_DECODER)
            val jointFile = File(asrDir, RNNT_JOINT)
            Log.d(TAG, "Asset'ler hazir: model ${File(asrDir, "$MODEL.data").length() / 1024 / 1024} MB, " +
                    "rnnt ${if (decFile.exists() && jointFile.exists()) "var" else "yok"}")

            // 2. Meta
            val meta = JSONObject(File(asrDir, META).readText())
            blankIdx = meta.optInt("blank_idx", 1024)
            sampleRate = meta.optInt("sample_rate", 16000)
            val rnnt = meta.optJSONObject("rnnt")
            Log.d(TAG, "Meta: blank_idx=$blankIdx, sample_rate=$sampleRate, export_id=${meta.optString("export_id", "-")}")

            // 3. Tokenizer
            tokenizer = File(asrDir, TOKENIZER).inputStream().use { SentencePieceDecoder.fromInputStream(it) }
            Log.d(TAG, "Tokenizer yuklendi: vocab_size=${tokenizer?.vocabSize}")

            // 4. ONNX Runtime
            _state.value = AsrState.InitializingModel
            val env = OrtEnvironment.getEnvironment()
            ortEnv = env
            val mainOpts = OrtSession.SessionOptions().apply {
                setIntraOpNumThreads(4)  // A34 6 buyuk + 2 kucuk core, 4 buyuk yeter
                setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
            }
            // ONNX Runtime modelin yanindaki .data dosyasini otomatik bulup mmap eder
            val main = env.createSession(modelFile.absolutePath, mainOpts)
            session = main
            hasEncLen = OUTPUT_ENC_LEN in main.outputNames
            Log.d(TAG, "Ana session: inputs=${main.inputNames}, outputs=${main.outputNames}")

            // 5. RNNT (model v2+). Kucuk graph'lar, adim basina cok kisa → tek thread daha hizli.
            if (rnnt != null && OUTPUT_ENC_PROJ in main.outputNames && decFile.exists() && jointFile.exists()) {
                rnntLayers = rnnt.getInt("pred_layers")
                rnntHidden = rnnt.getInt("pred_hidden")
                rnntMaxSymbols = rnnt.optInt("max_symbols", 10)
                val smallOpts = OrtSession.SessionOptions().apply {
                    setIntraOpNumThreads(1)
                    setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
                }
                decoderSession = env.createSession(decFile.absolutePath, smallOpts)
                jointSession = env.createSession(jointFile.absolutePath, smallOpts)
                Log.d(TAG, "RNNT hazir: LSTM ${rnntLayers}x$rnntHidden, max_symbols=$rnntMaxSymbols")
            } else {
                Log.w(TAG, "RNNT yok (model v1?) — sadece CTC")
            }

            _state.value = AsrState.Ready
        } catch (e: Throwable) {
            Log.e(TAG, "initialize hatasi", e)
            _state.value = AsrState.Error(e.message ?: "Yukleme hatasi", e)
            throw e
        }
    }

    /**
     * Verilen ses verisini transkribe et.
     *
     * @param audio 16kHz mono float32 PCM, range [-1.0, 1.0]
     * @return AsrResult (text + token IDs + zaman metrikleri + kullanilan decoder)
     */
    suspend fun transcribe(audio: FloatArray): AsrResult = withContext(Dispatchers.Default) {
        val sess = session ?: throw IllegalStateException("Engine yukli degil, initialize() cagir")
        val dec = tokenizer ?: throw IllegalStateException("Tokenizer yukli degil")
        val env = ortEnv ?: throw IllegalStateException("OrtEnvironment yok")

        require(audio.isNotEmpty()) { "Bos audio array verildi" }

        val decoder = activeDecoder
        val audioDurationMs = (audio.size * 1000L) / sampleRate
        val t0 = System.nanoTime()

        val audioTensor = OnnxTensor.createTensor(env, FloatBuffer.wrap(audio), longArrayOf(1, audio.size.toLong()))
        val lengthTensor = OnnxTensor.createTensor(env, LongBuffer.wrap(longArrayOf(audio.size.toLong())), longArrayOf(1))

        try {
            // 1. Encoder — sadece gereken ciktilar hesaplanir
            val mainOutput = if (decoder == AsrDecoder.RNNT) OUTPUT_ENC_PROJ else OUTPUT_LOGPROBS
            val requested = if (hasEncLen) setOf(mainOutput, OUTPUT_ENC_LEN) else setOf(mainOutput)

            val encoded = sess.run(mapOf(INPUT_AUDIO to audioTensor, INPUT_LENGTH to lengthTensor), requested).use { out ->
                val tensor = out.get(mainOutput).get() as OnnxTensor
                val shape = tensor.info.shape      // [1, T, D]
                var frameCount = shape[1].toInt()
                // Son frame padding olabilir: NeMo decode'u sadece gecerli frame'lerde yapar
                if (hasEncLen) {
                    val encLen = (out.get(OUTPUT_ENC_LEN).get() as OnnxTensor).longBuffer.get(0).toInt()
                    frameCount = minOf(frameCount, encLen)
                }
                Encoded(tensor.floatBuffer.toArray(), frameCount, shape[2].toInt())
            }
            val values = encoded.values
            val frames = encoded.frames
            val dim = encoded.dim
            val tEncoder = System.nanoTime()

            // 2. Decode
            val ids = if (decoder == AsrDecoder.RNNT) {
                rnntGreedy(env, values, frames, dim)
            } else {
                ctcGreedy(values, frames, dim)
            }

            // 3. Detokenize
            val text = dec.decode(ids)

            val inferenceMs = (System.nanoTime() - t0) / 1_000_000L
            val decodeMs = (System.nanoTime() - tEncoder) / 1_000_000L
            Log.d(TAG, "transcribe[$decoder]: ${audio.size} sample (${audioDurationMs}ms), $frames frame, " +
                    "${ids.size} token, ${inferenceMs}ms (decode ${decodeMs}ms)")

            return@withContext AsrResult(
                text = text,
                tokenIds = ids,
                numTokens = ids.size,
                inferenceMs = inferenceMs,
                audioDurationMs = audioDurationMs,
                decoder = decoder,
            )
        } finally {
            audioTensor.close()
            lengthTensor.close()
        }
    }

    // ============================================================
    // CTC: argmax + blank/tekrar collapse
    // ============================================================
    private fun ctcGreedy(logprobs: FloatArray, frames: Int, vocab: Int): IntArray {
        val ids = ArrayList<Int>()
        var prev = -1
        for (t in 0 until frames) {
            val id = argmax(logprobs, t * vocab, vocab)
            if (id != blankIdx && id != prev) ids.add(id)
            prev = id
        }
        return ids.toIntArray()
    }

    // ============================================================
    // RNNT greedy — scripts/onnx_asr.py rnnt_ids() ile birebir:
    //   g, state = decoder(SOS=blank, sifir state)
    //   her t icin en fazla max_symbols kez:
    //       k = argmax joint(enc_proj[t], g)
    //       blank → sonraki frame (state DEGISMEZ)
    //       degilse → k'yi ekle, g, state = decoder(k, state)
    // ============================================================
    private class Encoded(val values: FloatArray, val frames: Int, val dim: Int)
    private class PredOut(val g: FloatArray, val h: FloatArray, val c: FloatArray)

    private fun rnntGreedy(env: OrtEnvironment, encProj: FloatArray, frames: Int, dim: Int): IntArray {
        val decS = decoderSession ?: throw IllegalStateException("RNNT decoder yok")
        val jointS = jointSession ?: throw IllegalStateException("RNNT joint yok")
        val stateSize = rnntLayers * rnntHidden

        var pred = predStep(env, decS, blankIdx, FloatArray(stateSize), FloatArray(stateSize))
        val ids = ArrayList<Int>()
        val f = FloatArray(dim)
        for (t in 0 until frames) {
            System.arraycopy(encProj, t * dim, f, 0, dim)
            for (s in 0 until rnntMaxSymbols) {
                val k = jointArgmax(env, jointS, f, pred.g)
                if (k == blankIdx) break
                ids.add(k)
                pred = predStep(env, decS, k, pred.h, pred.c)
            }
        }
        return ids.toIntArray()
    }

    private fun predStep(env: OrtEnvironment, decS: OrtSession, token: Int, h: FloatArray, c: FloatArray): PredOut {
        val stateShape = longArrayOf(rnntLayers.toLong(), 1, rnntHidden.toLong())
        OnnxTensor.createTensor(env, LongBuffer.wrap(longArrayOf(token.toLong())), longArrayOf(1, 1)).use { tokT ->
            OnnxTensor.createTensor(env, FloatBuffer.wrap(h), stateShape).use { hT ->
                OnnxTensor.createTensor(env, FloatBuffer.wrap(c), stateShape).use { cT ->
                    decS.run(mapOf("token" to tokT, "h_in" to hT, "c_in" to cT)).use { out ->
                        return PredOut(
                            g = (out.get("g").get() as OnnxTensor).floatBuffer.toArray(),
                            h = (out.get("h_out").get() as OnnxTensor).floatBuffer.toArray(),
                            c = (out.get("c_out").get() as OnnxTensor).floatBuffer.toArray(),
                        )
                    }
                }
            }
        }
    }

    private fun jointArgmax(env: OrtEnvironment, jointS: OrtSession, f: FloatArray, g: FloatArray): Int {
        OnnxTensor.createTensor(env, FloatBuffer.wrap(f), longArrayOf(1, 1, f.size.toLong())).use { fT ->
            OnnxTensor.createTensor(env, FloatBuffer.wrap(g), longArrayOf(1, 1, g.size.toLong())).use { gT ->
                jointS.run(mapOf("f" to fT, "g" to gT)).use { out ->
                    val logits = (out.get("logits").get() as OnnxTensor).floatBuffer.toArray()
                    return argmax(logits, 0, logits.size)
                }
            }
        }
    }

    // ============================================================
    // Yardimcilar
    // ============================================================
    private fun argmax(values: FloatArray, offset: Int, length: Int): Int {
        var best = 0
        var bestVal = values[offset]
        for (i in 1 until length) {
            val v = values[offset + i]
            if (v > bestVal) {
                bestVal = v
                best = i
            }
        }
        return best
    }

    private fun FloatBuffer.toArray(): FloatArray {
        val arr = FloatArray(remaining())
        get(arr)
        return arr
    }

    /** PCM short -> float32 [-1, 1] donusumu */
    fun shortPcmToFloat(pcm: ShortArray): FloatArray {
        val out = FloatArray(pcm.size)
        for (i in pcm.indices) {
            out[i] = pcm[i].toFloat() / 32768f
        }
        return out
    }

    fun close() {
        try {
            decoderSession?.close()
            jointSession?.close()
            session?.close()
            ortEnv?.close()
        } catch (e: Throwable) {
            Log.e(TAG, "close hatasi", e)
        }
        decoderSession = null
        jointSession = null
        session = null
        ortEnv = null
        tokenizer = null
        _state.value = AsrState.Idle
    }
}
