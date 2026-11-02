package com.tilavet.takip.session

/**
 * Namaz sonu duasi yoklamasi (UI — zikir karti ve "namaz bitince dinlemeyi durdur"; state machine kararlarini ETKILEMEZ).
 *
 * Kullanici (sabah 02.11): "sondaki Allahumme ente's-selam ve minke's-selam'i anlamadi". Dua 5 sn'lik parcalara bolununce
 * ASR'de kayboluyor: telefonda selamdan sonra "المصدر كتاب" | "أحمد الله" | "السلام" | bos | bos — ayni sesin 10 sn'lik
 * penceresi (son iki parca) "اللهم أنت السلام إليك". Selamdan sonra [WINDOW_SEC] boyunca her sesli parcada son [PROBE_SEC] sn
 * ayrica taninir (AudioPipeline); metin dua ise (ZikirTracker.isDuaText) parca sonucuyla birlikte ZikirTracker'a gider.
 * Olcum (19 cami namazi, telefonun parca sinirlari, yerel ASR): dua karti hic acilmayan 3 cumada dua bulundu ("اللهم أنت
 * السلام", "تباركت يا ذا الجلال"), sabah 02.11'de 643 sn; karti olan 13 kayitta da bulundu, dua disinda hic tetiklenmedi.
 * Ilk duada (ya da parcanin kendi metni dua iken) yoklama biter; Kuran okumasi kilitlenince (teravihte yeni namaz) de.
 */
class DuaProbe {

    companion object {
        /** Selamdan sonra bu kadar sn yoklanir (ZikirTracker.DUA_AFTER_SELAM_SEC ile ayni). */
        const val WINDOW_SEC = ZikirTracker.DUA_AFTER_SELAM_SEC
        /** Yoklamada taninan ses: son iki parca (sabit 5 sn + 1 sn bindirme → 11 sn) icinden son 10 sn. */
        const val PROBE_SEC = 10.0
        const val SAMPLE_RATE = 16000

        /**
         * Onceki parca + bu parca (bindirme cikarilarak) → son [PROBE_SEC] sn. Parca [endSec]'te biter, uzunlugu
         * ornek sayisindan; onceki parcayla ortusen bas kisim (sabit kesimde 1 sn bindirme) atilir.
         */
        fun window(prev: FloatArray?, prevEndSec: Double, cur: FloatArray, curEndSec: Double): FloatArray {
            val want = (PROBE_SEC * SAMPLE_RATE).toInt()
            if (prev == null || prev.isEmpty()) return if (cur.size <= want) cur else cur.copyOfRange(cur.size - want, cur.size)
            val curStartSec = curEndSec - cur.size / SAMPLE_RATE.toDouble()
            val overlap = ((prevEndSec - curStartSec) * SAMPLE_RATE).toInt().coerceIn(0, cur.size)
            val joined = FloatArray(prev.size + cur.size - overlap)
            prev.copyInto(joined, 0)
            cur.copyInto(joined, prev.size, overlap, cur.size)
            return if (joined.size <= want) joined else joined.copyOfRange(joined.size - want, joined.size)
        }
    }

    private var windowEndSec = Double.NEGATIVE_INFINITY

    fun reset() {
        windowEndSec = Double.NEGATIVE_INFINITY
    }

    /** Yoklama penceresi acik mi (log / test). */
    fun active(nowSec: Double): Boolean = nowSec <= windowEndSec

    /**
     * Parca islendikten sonra: bu parca icin yoklama yapilsin mi.
     * @param text parcanin ASR metni
     * @param recitation parca Kuran okumasina kilitlendi (FATIHA / ZAMM eslesmesi) — yoklama biter
     * @param silent parca sessiz (RMS esigi alti) — yoklanmaz
     */
    fun shouldProbe(text: String, recitation: Boolean, silent: Boolean, endSec: Double): Boolean {
        if (StateMachine.namazSignal(text) == "selam") {
            windowEndSec = endSec + WINDOW_SEC
            return false
        }
        if (recitation || ZikirTracker.isDuaText(text)) {
            windowEndSec = Double.NEGATIVE_INFINITY
            return false
        }
        return !silent && endSec <= windowEndSec
    }

    /** Yoklama metni → dua mi (dua ise yoklama biter). */
    fun onProbeText(text: String): Boolean {
        val dua = ZikirTracker.isDuaText(text)
        if (dua) windowEndSec = Double.NEGATIVE_INFINITY
        return dua
    }
}
