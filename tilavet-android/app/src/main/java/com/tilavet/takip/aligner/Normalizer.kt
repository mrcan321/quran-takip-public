package com.tilavet.takip.aligner

/**
 * Arapça metin normalizasyonu.
 *
 * Python tarafındaki [aligner.py.normalize_arabic] fonksiyonunun birebir port'u.
 * Aynı girdi → aynı çıktı garantisi vermek için her adım sırayla yapılır:
 *   1. Zero-width karakterleri (BOM, ZWJ, vb.) sil
 *   2. Arapça diakritikleri sil (harake, sukun, şedde, vb.)
 *   3. Karakter mapping (Hamza varyantları → ا, ى → ي, vb.)
 *   4. Whitespace normalize
 *
 * Bu sınıfta tüm regex/karakter aralıkları SAFI değer olarak yazıldı,
 * Python versiyonuyla karakter karakter karşılaştırılabilir.
 */
object Normalizer {

    // Zero-width karakterler — BOM ve görünmez Unicode kontrolleri
    // Python: r"[\uFEFF\u200B\u200C\u200D\u202A-\u202E]"
    private val ZERO_WIDTH_CHARS = setOf(
        '\uFEFF',  // BOM
        '\u200B',  // ZERO WIDTH SPACE
        '\u200C',  // ZERO WIDTH NON-JOINER
        '\u200D',  // ZERO WIDTH JOINER
        '\u202A', '\u202B', '\u202C', '\u202D', '\u202E',  // Bidi controls
    )

    // Arapça diakritikleri (harake, sukun, şedde, vb.)
    // Python: r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]"
    private fun isDiacritic(c: Char): Boolean {
        val code = c.code
        return when {
            code in 0x0610..0x061A -> true  // Various Arabic marks
            code in 0x064B..0x065F -> true  // Tashkil (harake)
            code == 0x0670 -> true          // Superscript Alef
            code in 0x06D6..0x06ED -> true  // Quranic annotations
            code == 0x0640 -> true          // Tatweel (kashida)
            else -> false
        }
    }

    // Karakter mapping
    // Python: NORMALIZATION_MAP — {أ إ آ ٱ → ا, ى ئ → ي, ؤ → و, ة → ه}
    private fun mapChar(c: Char): Char = when (c) {
        'أ', 'إ', 'آ', 'ٱ' -> 'ا'  // Hamza varyantları → ا
        'ى', 'ئ' -> 'ي'              // Alef Maksura, Yeh w/ Hamza → ي
        'ؤ' -> 'و'                   // Waw w/ Hamza → و
        'ة' -> 'ه'                   // Teh Marbuta → ه
        else -> c
    }

    /**
     * Tek bir Arapça string'i normalize eder.
     *
     * Aşamalar Python'daki ile birebir aynı sırada:
     *   1. ZERO_WIDTH.sub("", text)
     *   2. ARABIC_DIACRITICS.sub("", text)
     *   3. text.translate(NORMALIZATION_MAP)
     *   4. re.sub(r"\s+", " ", text).strip()
     */
    fun normalize(text: String): String {
        if (text.isEmpty()) return ""

        // Tek geçişli filter + map: zero-width sil, diacritic sil, map et
        val sb = StringBuilder(text.length)
        for (c in text) {
            if (c in ZERO_WIDTH_CHARS) continue
            if (isDiacritic(c)) continue
            sb.append(mapChar(c))
        }

        // Whitespace normalize (Python: re.sub(r"\s+", " ", text).strip())
        return collapseWhitespace(sb)
    }

    private fun collapseWhitespace(sb: StringBuilder): String {
        if (sb.isEmpty()) return ""

        val out = StringBuilder(sb.length)
        var inSpace = false
        var hasContent = false

        for (i in 0 until sb.length) {
            val c = sb[i]
            if (c.isWhitespace()) {
                if (hasContent) inSpace = true
            } else {
                if (inSpace) out.append(' ')
                out.append(c)
                hasContent = true
                inSpace = false
            }
        }
        return out.toString()
    }

    /**
     * Bir kelimenin trigram setini üretir.
     *
     * Python: word_to_trigrams(word) — padding "  word  " ile 3-gram set
     * Eğer word.length < 3 ise sadece kelimenin kendisini içeren set döner.
     */
    fun wordToTrigrams(word: String): Set<String> {
        if (word.length < 3) return setOf(word)

        val padded = "  $word  "
        val result = HashSet<String>(padded.length)
        for (i in 0..padded.length - 3) {
            result.add(padded.substring(i, i + 3))
        }
        return result
    }

    /**
     * Boşlukla ayrılmış metni token listesine çevirir.
     * Python: text.split()
     */
    fun tokenize(text: String): List<String> {
        return text.split(Regex("\\s+")).filter { it.isNotEmpty() }
    }
}
