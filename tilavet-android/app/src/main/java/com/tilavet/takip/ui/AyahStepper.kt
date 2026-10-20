package com.tilavet.takip.ui

import com.tilavet.takip.data.MushafData
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Atlanan ayetleri sirayla gosterme: kilitli eslesme ayni surede birden fazla ayet ileri giderse (ör. 1:2 → 1:5
 * — aradaki parca bos dondu ya da tek parcaya iki kisa ayet sigdi) ekran aradaki ayetlerde (1:3, 1:4) [stepMs]
 * kadar durur, sonra okunan ayete gecer. Kullanici atlanan ayetleri de okuyabilsin (ayar: 0-2 sn, 0 = kapali).
 *
 * - Sadece kilitli eslesmede (aday degil), ayni surede ve en fazla [maxSkipped] ara ayette; geri gidis ve uzak
 *   atlama dogrudan gider.
 * - Baska sureye gecis surenin basina yakin bir ayete (en fazla [maxOpening] ayet sonrasina) dustuyse surenin
 *   basindan baslar: cuma #2'de Asr'a 103:3'te kilitlenip 103:1-2 hic gorunmemisti (Fatiha'da 1:2'den — besmele
 *   sessiz). Hedef surenin ortasindaysa (zamm ortadan baslayabilir) dogrudan.
 * - Adimlama surerken yeni konum gelirse ekrandaki ara ayetten yeni hedefe devam eder; ekrandaki ara ayet
 *   suresini doldurur (yarida kesilmez). Geri gidis adimlamayi keser, hedef hemen gosterilir; baska sureye
 *   gecis keser ve (basina yakinsa) yeni surenin basindan baslar.
 *
 * Android'e bagli degil (masaustu Compose duzeneginde test edilir); zaman kaynagi monoton.
 */
class AyahStepper(
    private val scope: CoroutineScope,
    private val maxSkipped: Int = MAX_SKIPPED,
    private val maxOpening: Int = MAX_OPENING,
    private val nowMs: () -> Long = { System.nanoTime() / 1_000_000L },
) {
    companion object {
        /** Bundan fazla ayet atlanirsa (ayni surede) aradakiler sirayla gosterilmez, dogrudan gidilir. */
        const val MAX_SKIPPED = 7
        /** Sure gecisinde hedef surenin en fazla bu kadar ayet icindeyse (5. ayete kadar) bastan gosterilir. */
        const val MAX_OPENING = 4
    }

    private var job: Job? = null
    private var shownAtMs = 0L   // ekrandaki ara ayetin gosterildigi an

    /** Adimlama suruyor mu (ekranda ara ayet var). */
    val isStepping: Boolean get() = job?.isActive == true

    /** Suren adimlamayi keser (kamet, yeni oturum). */
    fun cancel() {
        job?.cancel()
        job = null
    }

    /**
     * Yeni okunan ayet.
     * @param shown ekrandaki ayet (adimlama surerken ekrandaki ara ayet; null = yok)
     * @param target yeni okunan ayet
     * @param locked kilitli eslesme (aday degil) — ara ayetler sadece kilitliyken gosterilir
     * @param stepMs ara ayet suresi (0 = kapali)
     * @param showSkipped ara ayeti ekrana koy
     * @param showTarget hedefi ekrana koy (adimlama yoksa hemen, varsa en sonda cagrilir)
     * @return gosterilecek ara ayetler (bos = yok)
     */
    fun moveTo(
        mushaf: MushafData,
        shown: Int?,
        target: Int,
        locked: Boolean,
        stepMs: Long,
        showSkipped: (Int) -> Unit,
        showTarget: () -> Unit,
    ): IntRange {
        val wasStepping = isStepping
        cancel()
        val skipped = if (locked && shown != null && stepMs > 0) mushaf.skippedAyahs(shown, target, maxSkipped, maxOpening)
        else IntRange.EMPTY
        // Adimlama surerken ayni yone devam: ekrandaki ara ayet suresini doldursun
        val forward = shown != null && target > shown && mushaf.surahOf(shown) == mushaf.surahOf(target)
        val firstWait = if (wasStepping && forward && stepMs > 0)
            (shownAtMs + stepMs - nowMs()).coerceIn(0L, stepMs) else 0L
        if (skipped.isEmpty() && firstWait == 0L) {
            showTarget()
            return skipped
        }
        job = scope.launch {
            if (firstWait > 0) delay(firstWait)
            for (a in skipped) {
                showSkipped(a)
                shownAtMs = nowMs()
                delay(stepMs)
            }
            showTarget()
        }
        return skipped
    }
}
