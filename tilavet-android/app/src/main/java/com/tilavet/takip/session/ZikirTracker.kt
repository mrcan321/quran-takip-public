package com.tilavet.takip.session

/**
 * Namaz zikirleri (rükünler arasi) — ekrandaki zikir karti icin (state machine kararlarini ETKILEMEZ).
 *
 * Kullanici: "rukunler arasindaki Allahu ekber, semiallahu limen hamideh gibi sozleri de yakala ve Turkce anlamlarini
 * ezan/kametteki gibi popup olarak goster; esselamu aleykum de." Her parcanin ASR metninde aranir:
 *   - tekbir: parca agirlikla "الله أكبر" (tekbir ciftleri ve diger zikirler cikinca en fazla 1 kelime kalir) ve parca
 *     Kuran'a eslesmedi — "الله أكبر" Kuran'da 3 ayette ayet ortasinda geciyor (9:72, 29:45, 40:10)
 *   - semiallah: "سمع الله" + "قول" disi kelime, "استمع الله" ya da bozuk "لمن حمد…" (namazSignal'in tek basina "حمده" kurali kart icin yok)
 *   - "ربنا (و)لك الحمد"
 *   - selam ("السلام عليكم/عليك", bolunmus "عليكم ورحمة") ve namaz sonu duasi ("أنت السلام", "منك السلام", "تباركت",
 *     "ذا الجلال"): son Kuran okumasindan en az [AFTER_RECITATION_SEC] sonra — Hani Rifai teravihinde okuma arasinda ASR
 *     "السلام عليكم" uydurdu (RakatTracker ile ayni kural)
 * Olcum (36 gercek + 67 dis kaynak + 6 sentetik kayit, iki zincir): Kuran okunan anda ya da tek sureli kayitta 0 kart;
 * cuma #3: iftitah tekbiri 75 sn, semiallah 160 / 266 sn, secde tekbirleri, selam 350 sn; aksam #2: selam 450, dua 470 sn.
 * Kamette (ezan penceresi acikken) kart gosterilmez — MainViewModel.
 */
// Arapca virgul (،) yok: KFGQPC fontu onu dolu daire olarak ciziyor
enum class NamazZikri(val title: String, val arabic: String, val reading: String, val turkish: String) {
    TEKBIR("TEKBİR", "اللهُ أَكْبَرُ", "Allâhu ekber", "Allah en büyüktür"),
    SEMIALLAH(
        "RÜKÛDAN KALKIŞ", "سَمِعَ اللهُ لِمَنْ حَمِدَهُ", "Semiallâhu limen hamideh",
        "Allah, kendisine hamd edeni işitti",
    ),
    RABBENA("RÜKÛDAN KALKIŞ", "رَبَّنَا لَكَ الْحَمْدُ", "Rabbenâ leke'l-hamd", "Rabbimiz! Hamd sana mahsustur"),
    SELAM(
        "SELAM", "السَّلَامُ عَلَيْكُمْ وَرَحْمَةُ اللهِ", "Esselâmu aleyküm ve rahmetullâh",
        "Allah'ın selamı ve rahmeti üzerinize olsun",
    ),
    DUA(
        "NAMAZ SONU DUASI", "اللَّهُمَّ أَنْتَ السَّلَامُ وَمِنْكَ السَّلَامُ تَبَارَكْتَ يَا ذَا الْجَلَالِ وَالْإِكْرَامِ",
        "Allâhümme ente's-selâm ve minke's-selâm tebârekte yâ ze'l-celâli ve'l-ikrâm",
        "Allah'ım! Sen selamsın, esenlik ancak sendendir. Ey celal ve ikram sahibi! Sen ne yücesin",
    ),
}

class ZikirTracker {

    companion object {
        /** Selam / dua son Kuran okumasindan bu kadar sn sonra gelmediyse okuma arasindaki ASR uydurmasi sayilir. */
        const val AFTER_RECITATION_SEC = 20.0
        /**
         * Selamdan sonra bu kadar sn icinde "اللهم ..." ile baslayan ya da "يا ذا" iceren ilk parca namaz sonu duasi
         * ("اللهم أنت السلام ومنك السلام تباركت يا ذا الجلال والإكرام"). Yatsi (19.10): dua ASR'de "اللهم كسر" (5 sn parca),
         * "يا ذا العلي" (12 sn pencere) — "أنت السلام" / "تباركت" / "ذا الجلال" hic cikmadi, kart acilmadi. "اللهم" Kuran'da
         * 5 yerde, "يا ذا" 2 yerde (18:86, 18:94) gecer → sadece selamdan sonra, namaz basina bir kez.
         */
        const val DUA_AFTER_SELAM_SEC = 90.0
        private val TEKBIR_WORDS = setOf("اكبر", "اغبر", "اكبار")

        private fun tokens(text: String?): List<String> =
            (text ?: "").trim().split(Regex("\\s+")).map { StateMachine.bareToken(it) }.filter { it.isNotEmpty() }

        /** Metindeki zikirler, metindeki sirayla (art arda ayni zikir bir kez). */
        fun detect(text: String?): List<NamazZikri> {
            val t = tokens(text)
            val out = ArrayList<NamazZikri>()
            fun add(z: NamazZikri) { if (out.isEmpty() || out.last() != z) out.add(z) }
            for (i in t.indices) {
                val w = t[i]
                val next = t.getOrNull(i + 1)
                when {
                    w == "سمع" && next == "الله" && i + 2 < t.size && t[i + 2] != "قول" -> add(NamazZikri.SEMIALLAH)
                    // "استمع الله" (ASR, aksam 22.10): Kuran'da "استمع" sadece 72:1'de ("استمع نفر")
                    w == "استمع" && next == "الله" -> add(NamazZikri.SEMIALLAH)
                    // Tek basina "حمده" (namazSignal'de rukû) kart icin yetmez: sentetik teravihte Kureys 106:4
                    // "أطعمهم" → ASR "الذي حمده منه" okuma ortasinda kart acti
                    w == "لمن" && next != null && next.startsWith("حمد") -> add(NamazZikri.SEMIALLAH)
                    w == "ربنا" && (next == "لك" || next == "ولك") && t.getOrNull(i + 2) == "الحمد" -> add(NamazZikri.RABBENA)
                    w == "السلام" && (next == "عليكم" || next == "عليك") -> add(NamazZikri.SELAM)
                    // parca sinirinda bolunen selam ("السلام" onceki parcada)
                    (w == "عليكم" || w == "عليك") && (next == "ورحمه" || next == "رحمه") && t.getOrNull(i - 1) != "السلام" ->
                        add(NamazZikri.SELAM)
                    ((w == "انت" || w == "منك" || w == "ومنك") && next == "السلام") || w == "تباركت" ||
                        (w == "ذا" && next == "الجلال") -> add(NamazZikri.DUA)
                    w == "الله" && next != null && next in TEKBIR_WORDS -> add(NamazZikri.TEKBIR)
                }
            }
            return out
        }

        /** Parca agirlikla tekbir mi: tekbir ciftleri ve namaz zikirleri cikinca en fazla 1 kelime kalir. */
        fun tekbirDominant(text: String?): Boolean {
            val t = tokens(text)
            val rest = ArrayList<String>()
            var i = 0
            while (i < t.size) {
                if (t[i] == "الله" && i + 1 < t.size && t[i + 1] in TEKBIR_WORDS) { i += 2; continue }
                if (t[i] in TEKBIR_WORDS) { i++; continue }
                rest.add(t[i]); i++
            }
            val (cleaned, _) = StateMachine.stripNamazPhrases(rest.joinToString(" "))
            return tokens(cleaned).size <= 1
        }
    }

    private var lastRecitationSec = Double.NEGATIVE_INFINITY
    private var lastSelamSec = Double.NEGATIVE_INFINITY
    private var duaAfterSelam = false

    fun reset() {
        lastRecitationSec = Double.NEGATIVE_INFINITY
        lastSelamSec = Double.NEGATIVE_INFINITY
        duaAfterSelam = false
    }

    /** Selamdan sonraki ilk dua parcasi ("اللهم ...", "يا ذا ...") — bkz. DUA_AFTER_SELAM_SEC. */
    private fun duaOpening(text: String?): Boolean {
        val t = tokens(text)
        return t.firstOrNull() == "اللهم" || (0 until t.size - 1).any { t[it] == "يا" && t[it + 1] == "ذا" }
    }

    /**
     * Bir parcanin sonucu → gosterilecek zikirler (metin sirasiyla; bos = yok).
     * @param t parcanin oturumdaki bitis zamani (sn)
     */
    fun onChunk(r: ChunkResult, t: Double): List<NamazZikri> {
        val found = detect(r.text).toMutableList()
        if (NamazZikri.DUA !in found && !duaAfterSelam && t - lastSelamSec in 0.0..DUA_AFTER_SELAM_SEC &&
            r.status != ChunkStatus.MATCHED && duaOpening(r.text)) {
            found.add(NamazZikri.DUA)
        }
        // Dua basladiktan sonra (selamdan sonra DUA_AFTER_SELAM_SEC icinde) duadaki "السلام" selam karti acmaz: yatsi #2
        // (20.10) "أنت السلام ومنك السلام" → ASR "السلام عليكم" 3. selam karti. Dua karti dua surdukce tekrar gosterilir
        // (aksam #2: 470 / 475 / 480 sn — dua okunurken kart acik kalsin).
        val inDua = duaAfterSelam && t - lastSelamSec <= DUA_AFTER_SELAM_SEC
        val out = found.filter { z ->
            when (z) {
                NamazZikri.TEKBIR -> r.status != ChunkStatus.MATCHED && tekbirDominant(r.text)
                NamazZikri.SELAM -> t - lastRecitationSec >= AFTER_RECITATION_SEC && !inDua
                NamazZikri.DUA -> t - lastRecitationSec >= AFTER_RECITATION_SEC
                else -> true
            }
        }
        if (NamazZikri.SELAM in out) {
            lastSelamSec = t
            duaAfterSelam = false
        }
        if (NamazZikri.DUA in out) duaAfterSelam = true
        if (r.status == ChunkStatus.MATCHED && (r.state == NamazState.FATIHA || r.state == NamazState.ZAMM)) {
            lastRecitationSec = t
        }
        return out
    }
}
