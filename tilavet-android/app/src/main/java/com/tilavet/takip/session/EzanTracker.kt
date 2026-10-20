package com.tilavet.takip.session

/**
 * Ezan / kamet takibi — ekrandaki ezan/kamet penceresi icin (state machine kararlarini ETKILEMEZ).
 *
 * Acilis: state machine'in kamet/ezan sinyali (`ChunkResult.kamet`: Kuran'da hic gecmeyen kaliplar —
 * "حي على", "قامت", "الفلاح", "أشهد أن", "أن محمد"...; 34 kaydin transkriptlerinde yanlis alarm 0).
 * Acikken her parcanin ASR metninde ezan/kamet cumleleri aranir, okunan cumle isaretlenir.
 *
 * Kapanis (yeni bir ses beklemeden):
 *   - son "لا إله إلا الله" (cumleler ilerledikten sonra) → END_FINAL (UI kisa bir sure gosterip kapatir)
 *   - son tekbirden sonra [FINAL_TEKBIR_TIMEOUT_SEC] icinde tevhid duyulmadiysa → END_TIMEOUT
 *     (cuma kameti: son "لا إله إلا الله" ASR'de kayboldu; namazin iftitah tekbiri kameti uzatmasin)
 *   - [PHRASE_TIMEOUT_SEC] boyunca hic ezan/kamet cumlesi yok → END_TIMEOUT
 *   - Kuran'a kilit (FATIHA/ZAMM eslesmesi) → END_QURAN (namaz basladi)
 *
 * Cuma #3 (16.10): kametin ortasi (hayya'lar, kad kamet) ASR'de cop ("شركة الهدى...", "المصدر كتاب", "نور العصا");
 * pencere 10 sn'de "محمد رسول الله" ile acilip 25 sn cumle gelmeyince 35 sn'de kapaniyordu, kamet 45 sn'ye kadar
 * suruyordu. Ustelik sondaki "الله أكبر الله أكبر / لا إله إلا الله" taninsa bile hayya'lar duyulmadigi icin bastaki
 * tekbir / sehadet sayilip (sira geri gitmez) atlaniyordu. Artik: Resul sehadetinden sonra gelen tekbir son tekbir,
 * (اشهد'siz) tevhid son tevhid; zaman asimi 40 sn.
 *
 * Cumle tanima ASR hatalarina dayanikli anahtar kelime kurallariyla (cuma kameti: "بل قام بالصلاة" =
 * قد قامت الصلاة, "الصلاة حي الصلاة" = حي على الصلاة, "عما يرزق الله أن محمد" = أشهد أن محمدا رسول الله;
 * cuma #2: "خير الصلاة على الصلاة" = حي على الصلاة, "مضت الصلاة" = قد قامت الصلاة).
 * Sira hep ileri gider: ezanda her cumle 2 kez okunur, geriye eslesme ASR bozuklugudur.
 */
// Arapca virgul (،) yok: KFGQPC fontu onu dolu daire olarak ciziyor
// reading: okunus (G2 gozlugunde Arapca harf yok — gozlukte okunus + anlam gosterilir)
enum class EzanPhrase(val arabic: String, val turkish: String, val reading: String) {
    TEKBIR_BAS("اللهُ أَكْبَرُ  اللهُ أَكْبَرُ", "Allah en büyüktür, Allah en büyüktür", "Allâhu ekber, Allâhu ekber"),
    SEHADET_TEVHID("أَشْهَدُ أَنْ لَا إِلٰهَ إِلَّا اللهُ", "Şehadet ederim ki Allah'tan başka ilah yoktur", "Eşhedü en lâ ilâhe illallâh"),
    SEHADET_RESUL("أَشْهَدُ أَنَّ مُحَمَّدًا رَسُولُ اللهِ", "Şehadet ederim ki Muhammed Allah'ın Resûlüdür", "Eşhedü enne Muhammeden Resûlullâh"),
    HAYYA_SALAH("حَيَّ عَلَى الصَّلَاةِ", "Haydin namaza", "Hayye ale's-salâh"),
    HAYYA_FELAH("حَيَّ عَلَى الْفَلَاحِ", "Haydin kurtuluşa", "Hayye ale'l-felâh"),
    SABAH("الصَّلَاةُ خَيْرٌ مِنَ النَّوْمِ", "Namaz uykudan hayırlıdır", "Es-salâtü hayrun mine'n-nevm"),
    KAMET("قَدْ قَامَتِ الصَّلَاةُ", "Namaz başladı", "Kad kâmeti's-salâh"),
    TEKBIR_SON("اللهُ أَكْبَرُ  اللهُ أَكْبَرُ", "Allah en büyüktür, Allah en büyüktür", "Allâhu ekber, Allâhu ekber"),
    TEVHID("لَا إِلٰهَ إِلَّا اللهُ", "Allah'tan başka ilah yoktur", "Lâ ilâhe illallâh"),
}

/** Ekrandaki pencerenin icerigi. */
data class EzanView(
    /** "EZAN", "KAMET" ya da (henuz belli degilse) "EZAN · KAMET". */
    val title: String,
    /** Gosterilen satirlar (sabah ve kamet satirlari sadece duyulunca eklenir). */
    val rows: List<EzanPhrase>,
    /** Okunan cumle (null = henuz tanınmadı). */
    val current: EzanPhrase?,
)

enum class EzanEvent { NONE, OPEN, CHANGED, END_FINAL, END_TIMEOUT, END_QURAN }

class EzanTracker {

    companion object {
        /**
         * Bu kadar saniye hic ezan/kamet cumlesi tanınmazsa pencere kapanir (cuma #3 kameti: Resul sehadeti 10 sn,
         * sonraki tanınan cumle son tekbir 40 sn; 25 sn'de kapaniyordu). Kuran'a kilit pencereyi zaten hemen kapatir.
         */
        const val PHRASE_TIMEOUT_SEC = 40.0
        /** Son tekbirden sonra tevhid bu kadar saniyede gelmezse kapanir. */
        const val FINAL_TEKBIR_TIMEOUT_SEC = 12.0
        /**
         * Kad kamet cumlesi duyulmadan son tekbire gelindiyse: pencere acilisindan son tekbire bu kadar saniyeden kisa
         * surduyse kamet (Turkiye'de kamet 30-50 sn; cuma #3: 10 → 40 sn), uzunsa ezan (makamli ezan 2-4 dk; dis kaynak
         * ezan_003: 30 → 135 sn). Eskiden hayya'lardan sonra kamet gelmediyse "EZAN" deniyordu; cuma #3'te hayya'lar
         * ASR'de yoktu.
         */
        const val KAMET_MAX_SEC = 60.0
        /** Bir anahtar kelimenin "yakininda" sayilan kelime sayisi. */
        private const val NEAR = 4

        private val TEKBIR = setOf("اكبر", "اغبر", "اكبار")
        private val SALAH = setOf("الصلاه", "صلاه", "بالصلاه")
        private val FELAH = setOf("الفلاح", "فلاح")

        /**
         * Metindeki ezan/kamet cumleleri, metindeki sirayla. [reached] o ana kadar ulasilan en ileri cumle
         * (tekbir ve tevhidin bastaki mi sondaki mi oldugunu ayirmak icin).
         */
        fun detect(text: String, reached: EzanPhrase? = null): List<EzanPhrase> {
            val t = text.trim().split(Regex("\\s+")).map { StateMachine.bareToken(it) }.filter { it.isNotEmpty() }
            val out = ArrayList<EzanPhrase>()
            var maxOrd = reached?.ordinal ?: -1
            val used = BooleanArray(t.size)
            fun near(i: Int, pred: (String) -> Boolean): Int? {
                for (j in maxOf(0, i - NEAR)..minOf(t.size - 1, i + NEAR)) if (j != i && pred(t[j])) return j
                return null
            }
            fun add(p: EzanPhrase) {
                if (out.isEmpty() || out.last() != p) out.add(p)
                if (p.ordinal > maxOrd) maxOrd = p.ordinal
            }
            for (i in t.indices) {
                if (used[i]) continue
                val w = t[i]
                when {
                    // Tekbir: Resul sehadetinden sonra ancak sondaki tekbir olabilir (hayya'lar ASR'de kaybolsa da;
                    // ilk sehadetten sonra degil — sabit parcanin 1 sn bindirmesinde bastaki tekbirin kirintisi kalabilir).
                    // "الله اغفر" (cuma #3 kamet sonu) da tekbir — sadece pencere acikken bakildigi icin guvenli.
                    w in TEKBIR || (w == "اغفر" && i > 0 && t[i - 1] == "الله") ->
                        add(if (maxOrd >= EzanPhrase.SEHADET_RESUL.ordinal) EzanPhrase.TEKBIR_SON else EzanPhrase.TEKBIR_BAS)
                    w == "اشهد" || w == "شهد" -> {
                        // Sehadet: ardindan (4 kelime icinde) Muhammed/Resul geliyorsa ikinci sehadet
                        var resul = false
                        for (j in i + 1..minOf(t.size - 1, i + NEAR)) {
                            if (t[j].startsWith("محمد") || t[j] == "رسول") { resul = true; used[j] = true }
                            if (t[j] == "اله" || t[j] == "الا") used[j] = true
                        }
                        add(if (resul) EzanPhrase.SEHADET_RESUL else EzanPhrase.SEHADET_TEVHID)
                    }
                    w.startsWith("محمد") || w == "رسول" -> add(EzanPhrase.SEHADET_RESUL)
                    w == "حي" -> {
                        if (near(i) { it in FELAH } != null) add(EzanPhrase.HAYYA_FELAH)
                        else if (near(i) { it in SALAH || it == "علي" } != null) add(EzanPhrase.HAYYA_SALAH)
                        near(i) { it in SALAH || it in FELAH }?.let { used[it] = true }
                    }
                    w in FELAH -> add(EzanPhrase.HAYYA_FELAH)
                    // "على الصلاة" / "خير الصلاة" (hayya → "خير"): hayye ale's-salah; "على الفلاح" FELAH kuralinda
                    (w == "علي" || w == "خير") && i + 1 < t.size && t[i + 1] in SALAH -> {
                        add(EzanPhrase.HAYYA_SALAH)
                        used[i + 1] = true
                    }
                    // "مضت الصلاة" = قد قامت الصلاة
                    w == "مضت" && near(i) { it in SALAH } != null -> {
                        add(EzanPhrase.KAMET)
                        near(i) { it in SALAH }?.let { used[it] = true }
                    }
                    w == "قامت" || (w == "قام" && near(i) { it in SALAH } != null) -> {
                        add(EzanPhrase.KAMET)
                        near(i) { it in SALAH }?.let { used[it] = true }
                    }
                    w == "النوم" -> add(EzanPhrase.SABAH)
                    w == "اله" && i > 0 && t[i - 1] == "لا" -> {
                        // "لا اله الا الله": Resul sehadetinden once sehadetin kendisi (اشهد duyulmamis), sonra
                        // ezan/kamet sonu (sehadet-i tevhid Resul'den once okunur)
                        add(if (maxOrd >= EzanPhrase.SEHADET_RESUL.ordinal) EzanPhrase.TEVHID else EzanPhrase.SEHADET_TEVHID)
                    }
                }
            }
            return out
        }
    }

    private var active = false
    private var current: EzanPhrase? = null
    private var kametSeen = false
    private var sabahSeen = false
    private var lastPhraseSec = 0.0
    private var openSec = 0.0
    private var finalTekbirSec: Double? = null

    /** Pencere acikken icerigi; kapaliyken null. */
    var view: EzanView? = null
        private set

    fun reset() {
        active = false
        current = null
        kametSeen = false
        sabahSeen = false
        finalTekbirSec = null
        view = null
    }

    /**
     * Bir parcanin sonucu.
     * @param text ASR metni (ham)
     * @param kamet state machine kamet/ezan sinyali verdi
     * @param quranLocked parca Kuran'a kilitli eslesti (FATIHA/ZAMM)
     * @param endSec parcanin bittigi an (oturum/dosya saniyesi)
     */
    fun onChunk(text: String?, kamet: Boolean, quranLocked: Boolean, endSec: Double): EzanEvent {
        var event = EzanEvent.NONE
        if (!active) {
            if (!kamet) return EzanEvent.NONE
            reset()
            active = true
            lastPhraseSec = endSec
            openSec = endSec
            event = EzanEvent.OPEN
        }
        if (quranLocked) {
            reset()
            return EzanEvent.END_QURAN
        }
        val before = current
        val phrases = detect(text ?: "", current)
        for (p in phrases) {
            val cur = current
            if (cur != null && p.ordinal < cur.ordinal) continue   // sira geri gitmez (tekrar / ASR bozuklugu)
            if (p == EzanPhrase.KAMET) kametSeen = true
            if (p == EzanPhrase.SABAH) sabahSeen = true
            if (p == EzanPhrase.TEKBIR_SON && finalTekbirSec == null) finalTekbirSec = endSec
            current = p
        }
        if (phrases.isNotEmpty()) lastPhraseSec = endSec
        view = buildView()
        if (current == EzanPhrase.TEVHID) {
            active = false
            return EzanEvent.END_FINAL
        }
        val ft = finalTekbirSec
        if ((ft != null && endSec - ft >= FINAL_TEKBIR_TIMEOUT_SEC) || endSec - lastPhraseSec >= PHRASE_TIMEOUT_SEC) {
            reset()
            return EzanEvent.END_TIMEOUT
        }
        if (event == EzanEvent.NONE && current != before) event = EzanEvent.CHANGED
        return event
    }

    private fun buildView(): EzanView {
        val rows = EzanPhrase.values().filter {
            when (it) {
                EzanPhrase.SABAH -> sabahSeen
                EzanPhrase.KAMET -> kametSeen
                else -> true
            }
        }
        val ft = finalTekbirSec
        val title = when {
            kametSeen -> "KAMET"
            sabahSeen -> "EZAN"
            // Kamet cumlesi duyulmadan son tekbire gelindi: kisa surduyse kamet, uzunsa ezan (bkz. KAMET_MAX_SEC)
            ft != null -> if (ft - openSec <= KAMET_MAX_SEC) "KAMET" else "EZAN"
            else -> "EZAN · KAMET"
        }
        return EzanView(title, rows, current)
    }
}
