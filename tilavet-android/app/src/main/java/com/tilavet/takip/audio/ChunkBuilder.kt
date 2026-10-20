package com.tilavet.takip.audio

import kotlin.math.sqrt

/**
 * Duraklamada kesen parcalayici — scripts/vad_chunker.py PauseChunker ile birebir.
 *
 * Eskiden ses sabit 5 sn'lik parcalarla isleniyordu: okunan son kelime ekrana ortalama ~3.5 sn geriden
 * geliyordu ve parca siniri kelimeyi ortasindan kesebiliyordu. Imam ayet sonlarinda (ve uzun ayetlerde
 * vakf yerlerinde) duraklar — parcayi duraklamada kesip hemen islersek sonuc duraklamanin icinde gelir,
 * kelime de bolunmez. Bu da "ayet bitti → ekran sonraki ayete kaysin" davranisinin temeli.
 *
 * Kural (her 100 ms'lik cercevede):
 *   - Sessizlik esigi uyarlamali: son 5 sn'nin cerceve RMS'lerinden gurultu (p20) ve konusma (p90);
 *     esik = gurultu + 0.3 * (konusma - gurultu). Dinamik aralik yoksa (konusma < 2*gurultu + 0.002)
 *     duraklama algilanmaz → eski sabit 5 sn davranisi.
 *   - Parcada >= 1.5 sn yeni ses ve >= 1 sn konusma varken son 0.5 sn sessizse → kes (bindirme yok).
 *   - Duraklama gelmezse 5 sn'de kes (1 sn bindirmeyle, eski sabit parca gibi).
 * Olcum (30 kayit, ~1 sn islem dahil): kelime → ekran ort. 3.4 → 3.0 sn, ayet sonu → ekran medyan 3.4 → 2.1 sn.
 *
 * HIBRIT (APK #14+): pauseCutEnabled sadece kilitliyken (FATIHA/ZAMM) true — BEKLEME/ARA'da sabit 5 sn.
 * Her yerde duraklama kesimi (APK #11-13) CI eval'de BEKLEME'de yanlis kilit uretti (ilk kilit 17/0 → 14/2,
 * yanlis kilitli chunk 0 → 7); kilitliyken kisa parca hic yanlis kilit uretmedi. Anahtari chunk consumer
 * her parcanin sonucundan sonra gunceller (~1 sn ASR); 1.5 sn'den (MIN) once kesim olmadigi icin isleme
 * 1.5 sn'den kisa surdukce parca sinirlari eval'dekiyle (vad_chunker.chunks_pause(pause_enabled=...)) ayni.
 */
internal class ChunkBuilder {
    companion object {
        const val FRAME = 1600              // 100 ms analiz cercevesi
        const val HISTORY_FRAMES = 50       // esik icin son 5 sn
        const val MIN_CHUNK_FRAMES = 15     // 1.5 sn: bundan kisa parca duraklamada kesilmez
        const val MAX_CHUNK_FRAMES = 50     // 5.0 sn: duraklama gelmezse
        const val PAUSE_FRAMES = 5          // 0.5 sn sessizlik = duraklama
        const val MIN_SPEECH_FRAMES = 10    // parcada en az 1 sn konusma
        const val OVERLAP_SAMPLES = 16000  // zorunlu kesimde 1 sn bindirme (16 kHz)
        const val SILENT_RATIO = 0.3
    }

    // Kayittan gelen ornekler degisken boyutta olabilir → 100 ms'lik analiz cercevelerine tamamla
    private val pending = FloatArray(FRAME)
    private var pendingN = 0

    private val frames = ArrayList<FloatArray>()
    private val silent = ArrayList<Boolean>()
    private val history = ArrayDeque<Double>()
    private var tail = FloatArray(0)

    /** false → sadece 5 sn'de kes (sabit parca). Sessizlik gecmisi her durumda tutulur. */
    @Volatile
    var pauseCutEnabled = false

    /** Ornek ekle; bir parca tamamlandiysa (ses, duraklama_kesimi_mi) don. */
    fun addSamples(samples: FloatArray): Pair<FloatArray, Boolean>? {
        var out: Pair<FloatArray, Boolean>? = null
        var i = 0
        while (i < samples.size) {
            val n = minOf(FRAME - pendingN, samples.size - i)
            System.arraycopy(samples, i, pending, pendingN, n)
            pendingN += n
            i += n
            if (pendingN == FRAME) {
                pendingN = 0
                addFrame(pending.copyOf())?.let { out = it }
            }
        }
        return out
    }

    private fun addFrame(frame: FloatArray): Pair<FloatArray, Boolean>? {
        var sumSq = 0.0
        for (v in frame) sumSq += v.toDouble() * v
        val rms = sqrt(sumSq / frame.size)
        silent.add(isSilent(rms))
        frames.add(frame)
        val n = frames.size
        val speech = n - silent.count { it }
        val pause = n >= PAUSE_FRAMES && (n - PAUSE_FRAMES until n).all { silent[it] }
        if (pauseCutEnabled && n >= MIN_CHUNK_FRAMES && pause && speech >= MIN_SPEECH_FRAMES) return cut(true)
        if (n >= MAX_CHUNK_FRAMES) return cut(false)
        return null
    }

    private fun isSilent(rms: Double): Boolean {
        history.addLast(rms)
        if (history.size > HISTORY_FRAMES) history.removeFirst()
        val s = history.sorted()
        val m = s.size
        val noise = s[(0.2 * (m - 1)).toInt()]
        val speech = s[(0.9 * (m - 1)).toInt()]
        if (speech < 2 * noise + 0.002) return false
        return rms < noise + SILENT_RATIO * (speech - noise)
    }

    private fun cut(pauseCut: Boolean): Pair<FloatArray, Boolean> {
        var total = tail.size
        for (f in frames) total += f.size
        val combined = FloatArray(total)
        System.arraycopy(tail, 0, combined, 0, tail.size)
        var off = tail.size
        for (f in frames) {
            System.arraycopy(f, 0, combined, off, f.size)
            off += f.size
        }
        // Duraklamada kesildiyse sinirda kelime yok → bindirme gereksiz; 5 sn'de kesildiyse son 1 sn tekrar
        tail = if (pauseCut) FloatArray(0) else combined.copyOfRange(maxOf(0, total - OVERLAP_SAMPLES), total)
        frames.clear()
        silent.clear()
        return Pair(combined, pauseCut)
    }
}
