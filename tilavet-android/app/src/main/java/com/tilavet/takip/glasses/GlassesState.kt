package com.tilavet.takip.glasses

/**
 * Even Realities G2 gozlugune giden ekran durumu: G2 eklentisi (assets/g2, Even uygulamasinin WebView'inde calisir)
 * GlassesBridge'in /state adresinden JSON olarak okur ve gozluge yazar. UiState'ten turetilir (MainViewModel);
 * state machine kararlarini ETKILEMEZ. Android'siz — JVM'de test edilir (tests/jvm, `glasses`).
 *
 * Gozluk fontunda Arapca harf yok (G2 firmware fontu: Latin / Kiril / Yunan / CJK) → ayet metni gozlukte eklentinin
 * cizdigi gri tonlu goruntu olarak gosterilir (istege bagli); Turkce meal ve basliklar duz metin.
 */
data class GlassesState(
    /** Pipeline calisiyor (mikrofon ya da simulasyon). */
    val listening: Boolean = false,
    val sim: Boolean = false,
    /** Kisa durum ("Dinleniyor", "kamet: Fatiha bekleniyor"...). */
    val status: String = "",
    /** Okunan ayet; 0 = henuz yok. */
    val surah: Int = 0,
    val ayah: Int = 0,
    val surahName: String = "",
    val surahAyahCount: Int = 0,
    /** Dogrulanmamis aday (ekrandaki "ADAY"). */
    val tentative: Boolean = false,
    /** Okunan ayette imamin geldigi yer: son vurgulu kelime / ayetin kelime sayisi (0-1) — uzun mealde sayfa secimi. */
    val progress: Double = 0.0,
    val meal: String = "",
    /** Ayet metni (KFGQPC yazimi, MushafData.displayText) — eklenti Arapca goruntusu icin. */
    val arabic: String = "",
    /** Ayarlar → G2'DE ARAPÇA: eklenti ayet metnini goruntu olarak da cizer. */
    val showArabic: Boolean = false,
    /** Ayarlar → G2 YAZI: BÜYÜK (varsayilan) — sadece meal, sigan en buyuk puntoda (eklentide goruntu olarak cizilir). */
    val bigText: Boolean = true,
    /** Ayarlar → G2 YAZI BOYUTU: buyuk yazida en kucuk punto (px; kisa metin daha buyuk, sigmayan sayfalanir). */
    val textPx: Int = DEFAULT_TEXT_PX,
    /** Ayarlar → G2'DE SURE / AYET ADI: buyuk yazida ustte gozlugun kendi yazisiyla "Bakara 2:255 · 1/3" (ADAY da orada). */
    val bigHeader: Boolean = true,
    /** Ayarlar → G2 SABİT YAZI BOYUTU: buyuk yazi her metinde textPx (kisa metin buyutulmez, uzun meal kucultulmez). */
    val fixedSize: Boolean = false,
    /**
     * Ayarlar → G2 AYETİ TEK EKRANA SIĞDIR: buyuk yazida uzun meal sayfalara bolunmez, punto gerektigi kadar kuculur
     * (onePageMinPx'e kadar). Kullanici: "bir ayet 2 veya 3 sayfada gosterilince tum ayeti okumak zor".
     */
    val onePage: Boolean = false,
    /**
     * Ayarlar → G2 TEK EKRAN EN KÜÇÜK YAZI (px, MIN..MAX_ONE_PAGE_PX): tek ekranda punto en fazla buna iner; bu puntoda da
     * sigmayan meal sayfalanir (en az sayfa). Kullanici: "alt siniri kullaniciya birak, altinda kalacaksa sayfalama yaptir".
     */
    val onePageMinPx: Int = DEFAULT_ONE_PAGE_PX,
    /**
     * Ses kesildi (TextHold): okunan ayet metni kalkti — gozlukte alti bos, ustte rekat / durus (blankHeader) ya da ekran
     * bombos. Kullanici: "zammdan sonra rukuya gidilince ayet asili kalmasin, ekran bos kalsin".
     */
    val blank: Boolean = false,
    /**
     * Ayarlar → G2 BOŞ EKRANDA ÜST BİLGİ: bos ekranda (blank) ustte rekat / durus. Varsayilan KAPALI — kullanici (APK
     * #102): "ekran bos kaldiginda ust bilgi durmasin; bir ayara bagla" (APK #52-102 hep gosteriyordu).
     */
    val blankHeader: Boolean = false,
    /**
     * Ayarlar → G2 DURUM YAZISINI GİZLE: dinleme kapaliyken ("Dinleme kapalı") ve dinlenirken ayet bulunana kadar
     * ("Dinleniyor", "Kamet · Fatiha bekleniyor") gozluk ekrani bos. Kullanici: "ekran bombos olsun".
     */
    val hideStatus: Boolean = false,
    /** "2. REKÂT · KIYAM" (RakatTracker), bos = gosterme. */
    val rakat: String = "",
    /**
     * Zikir karti / ezan penceresi: baslik ("TEKBİR", "KAMET"), okunus, Turkce anlami; bos baslik = yok. Gozlukte sadece
     * Turkce anlami yazilir (layout.js noteText; kullanici: "Allahu ekber Allah en buyuktur olmasin"), okunus yedek.
     */
    val noteTitle: String = "",
    val noteReading: String = "",
    val noteTurkish: String = "",
) {
    /** /state yaniti. [seq]: durum her degistiginde artar (eklenti uzun yoklamada `since` olarak geri yollar). */
    fun toJson(seq: Long): String {
        val sb = StringBuilder(256 + meal.length + arabic.length * 2)
        sb.append('{')
        sb.append("\"v\":1,\"seq\":").append(seq)
        sb.append(",\"listening\":").append(listening)
        sb.append(",\"sim\":").append(sim)
        sb.append(",\"status\":").append(quote(status))
        sb.append(",\"surah\":").append(surah)
        sb.append(",\"ayah\":").append(ayah)
        sb.append(",\"surahName\":").append(quote(surahName))
        sb.append(",\"surahAyahCount\":").append(surahAyahCount)
        sb.append(",\"tentative\":").append(tentative)
        sb.append(",\"progress\":").append(if (progress.isFinite()) "%.3f".format(java.util.Locale.ROOT, progress) else "0")
        sb.append(",\"meal\":").append(quote(meal))
        sb.append(",\"arabic\":").append(quote(arabic))
        sb.append(",\"showArabic\":").append(showArabic)
        sb.append(",\"bigText\":").append(bigText)
        sb.append(",\"textPx\":").append(textPx)
        sb.append(",\"bigHeader\":").append(bigHeader)
        sb.append(",\"fixedSize\":").append(fixedSize)
        sb.append(",\"onePage\":").append(onePage)
        sb.append(",\"onePageMinPx\":").append(onePageMinPx)
        sb.append(",\"blank\":").append(blank)
        sb.append(",\"blankHeader\":").append(blankHeader)
        sb.append(",\"hideStatus\":").append(hideStatus)
        sb.append(",\"rakat\":").append(quote(rakat))
        sb.append(",\"noteTitle\":").append(quote(noteTitle))
        sb.append(",\"noteReading\":").append(quote(noteReading))
        sb.append(",\"noteTurkish\":").append(quote(noteTurkish))
        sb.append('}')
        return sb.toString()
    }

    companion object {
        /** Buyuk yazinin en kucuk puntosu: varsayilan ve ayar araligi (eklenti de ayni sinirlari uygular, layout.js BIG_PX). */
        const val DEFAULT_TEXT_PX = 48
        const val MIN_TEXT_PX = 30
        const val MAX_TEXT_PX = 80

        /** Tek ekran modunda en kucuk punto: varsayilan ve ayar araligi (layout.js ONE_PAGE_PX ile ayni). */
        const val DEFAULT_ONE_PAGE_PX = 20
        const val MIN_ONE_PAGE_PX = 12
        const val MAX_ONE_PAGE_PX = 40

        /** JSON string: ", \, kontrol karakterleri ve satir ayiricilari (U+2028/2029) kacirilir; digerleri UTF-8 aynen. */
        fun quote(s: String): String {
            val sb = StringBuilder(s.length + 2)
            sb.append('"')
            for (c in s) {
                when {
                    c == '"' -> sb.append("\\\"")
                    c == '\\' -> sb.append("\\\\")
                    c == '\n' -> sb.append("\\n")
                    c == '\r' -> sb.append("\\r")
                    c == '\t' -> sb.append("\\t")
                    c < ' ' || c == ' ' || c == ' ' -> sb.append("\\u%04x".format(c.code))
                    else -> sb.append(c)
                }
            }
            sb.append('"')
            return sb.toString()
        }
    }
}
