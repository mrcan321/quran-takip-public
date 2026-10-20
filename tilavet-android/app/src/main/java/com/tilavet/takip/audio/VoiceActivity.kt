package com.tilavet.takip.audio

import kotlin.math.max

/**
 * "Ses kesildi mi" — okunan ayetin metnini ses kesilince ekrandan (telefon + G2) kaldirmak icin. Kullanici (yatsi 19.10):
 * "zamm suresinden sonra rukuya gidilince ayet ekranda asili kalmasin, ekran bos kalsin; ses kesildikten sonra metnin ne
 * kadar kalacagini ayarlardan girebileyim (0-10 sn)". O kayitta 7:53 rukû / secde boyunca 50 sn, vaazdaki Fatiha dakikalarca
 * ekranda kaldi.
 *
 * Konusma esigi okunan sesin kendisinden ogrenilir: son [LEVEL_CHUNKS] eslesen (kilit / gorunen aday) okuma parcasinin
 * RMS medyaninin [QUIET_RATIO]'u. Cerceve RMS'i (100 ms) [MEDIAN_FRAMES] cercevelik medyanla yumusatilir (tek tik / oksuruk
 * sessizligi bozmasin). Sabit esik (0.006) gurultulu camide rukû / secdede hic 3 sn sessizlik bulmuyordu; son 30 sn'nin
 * p10 / p90'indan uyarlamali esik telefon titresimi / amin korosundan sonra alcak sesli okumayi "sessiz" sayiyordu (aksam #2,
 * Ra'd bolumunde 15 sn). Okuma seviyesine gore esikle 6 gercek namazda (3 sn) okuma icinde yanlis silme 0, okuma bitince
 * metin cogunlukla 2.5-8 sn'de kalkiyor (aksam #2'de Ra'd'dan sonra telefon titresimi → 21 sn, [TextHold.NO_MATCH_SEC]) —
 * bkz. JVM `hide` testi.
 *
 * Android'siz (JVM'de test edilir). Cerceve akisi (AudioPipeline okuyucu) ve parca sonuclari (tuketici) farkli is
 * parcaciklarinda → senkron.
 */
class VoiceActivity {
    companion object {
        const val QUIET_RATIO = 0.3
        const val MEDIAN_FRAMES = 5
        const val LEVEL_CHUNKS = 5
    }

    private val levels = ArrayDeque<Double>()
    private val recent = ArrayDeque<Double>()

    /** Son konusma cercevesinin bitis zamani (oturumdaki sn); okuma seviyesi bilinmeden hic konusma sayilmaz. */
    @Volatile
    var lastVoiceSec = Double.NEGATIVE_INFINITY
        private set

    /** Ekranda gosterilen okuma parcasi (kilit / aday): esik bu parcalarin RMS'inden. */
    @Synchronized
    fun addRecitationLevel(chunkRms: Double) {
        levels.addLast(chunkRms)
        while (levels.size > LEVEL_CHUNKS) levels.removeFirst()
    }

    /** 100 ms'lik cerceve (bitis zamani, RMS) → konusma mi. */
    @Synchronized
    fun onFrame(endSec: Double, rms: Double): Boolean {
        recent.addLast(rms)
        while (recent.size > MEDIAN_FRAMES) recent.removeFirst()
        if (levels.isEmpty()) return false
        val voiced = median(recent) > QUIET_RATIO * median(levels)
        if (voiced) lastVoiceSec = endSec
        return voiced
    }

    @Synchronized
    fun reset() {
        levels.clear()
        recent.clear()
        lastVoiceSec = Double.NEGATIVE_INFINITY
    }

    /** numpy.median ile ayni (cift sayida ortadaki ikisinin ortalamasi). */
    private fun median(xs: Collection<Double>): Double {
        val s = xs.sorted()
        val n = s.size
        return if (n % 2 == 1) s[n / 2] else (s[n / 2 - 1] + s[n / 2]) / 2.0
    }
}

/** Ses kesilince metni kaldirma karari (ayar: Ayarlar → SES KESİLİNCE METİN, 0-10 sn, 0.1 sn adim). */
object TextHold {
    /** Varsayilan 3 sn (onda bir sn): 6 gercek namazda okuma icinde yanlis silme 0 (2 sn'de 1). */
    const val DEFAULT_TENTHS = 30
    const val MAX_TENTHS = 100
    /** Ayar 0 olsa da metin en az bu kadar sessizlikten sonra kalkar (kelime arasi duraklama silmesin). */
    const val MIN_QUIET_SEC = 0.5
    /**
     * Ses surse de bu kadar sn yeni okuma eslesmesi gelmezse metin kalkar: yatsi (19.10) vaazinda okunan Fatiha / Felak'tan
     * sonra Turkce konusma okuma kadar yuksek → "ses kesilmedi", Fatiha 157 sn ekranda kaldi. 10 gercek kayitta okuma
     * icinde iki eslesme arasi en fazla 12.1 sn.
     */
    const val NO_MATCH_SEC = 20.0

    /**
     * Ekrandaki ayet metni kalkmali mi: hem son konusmadan hem ayetin ekranda son guncellenmesinden [holdSec] gecti
     * (ikinci sart okuma ortasinda sesin "sessiz" sanildigi anlara karsi — eslesmeler gelmeye devam ediyor) ya da ses
     * surse de [NO_MATCH_SEC] yeni eslesme yok (vaaz / sohbet).
     */
    fun shouldHide(nowSec: Double, lastVoiceSec: Double, shownSec: Double, holdSec: Double): Boolean =
        (nowSec - lastVoiceSec >= max(holdSec, MIN_QUIET_SEC) && nowSec - shownSec >= holdSec) ||
            nowSec - shownSec >= max(holdSec, NO_MATCH_SEC)
}
