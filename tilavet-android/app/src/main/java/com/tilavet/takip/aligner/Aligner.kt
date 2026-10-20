package com.tilavet.takip.aligner

import android.util.Log

/**
 * Kuran metni hizalama — aligner.py.align_transcription Kotlin port'u.
 *
 * OPTIMIZE EDILMIS VERSIYON (Adim 4d hotfix):
 *   1. Daha aktif min_hits — saf Python ratio'ya guvenmiyoruz, daha siki ele
 *   2. Window string caching — ayni (start, len) icin tek hesap
 *   3. Early exit threshold dusuruldu (98 -> 95) hiz icin
 *   4. Score-based pruning: dusuk skorlarda erken atla
 */
class Aligner(private val index: QuranIndex) {

    /** Runtime'da degistirilebilen pencere genisligi. Default 2 (production hizi icin). */
    @Volatile
    var defaultWindowSlack: Int = 2

    /**
     * Son hizalamalarin onbellegi (saf fonksiyon: ayni metin + pencere + ayar → ayni sonuc). Bir parcada ayni metin
     * birden cok kez hizalanabiliyor (tum Kuran / ikinci yer / gecis aramasi); JVM test kapisinda (tests/jvm) ayni
     * parca metinleri bilesik senaryolarda tekrar ediyor → buyuk tutulur. 0 = kapali.
     */
    var cacheSize: Int = 32
    private val cache = object : LinkedHashMap<String, AlignmentMatch?>(64, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, AlignmentMatch?>?): Boolean =
            size > cacheSize
    }

    companion object {
        private const val TAG = "Aligner"

        const val DEFAULT_WINDOW_SLACK = 5
        const val DEFAULT_MIN_SCORE_THRESHOLD = 40.0
        const val EARLY_EXIT_SCORE = 98.0  // Python ile birebir
        const val PARTIAL_WEIGHT = 0.6
        const val SORT_WEIGHT = 0.4

        private val BISMILLAH_TOKENS = setOf("بسم", "الله", "الرحمن", "الرحيم")
    }

    /**
     * @param excludeRange bu kelime araligina degen pencereler atlanir — "en iyi eslesmenin disindaki en iyi ikinci
     *        yer" (StateMachine.UNIQUE_LOCK_*, fark payi ile tek parcada kilit). aligner.py exclude_range ile birebir.
     */
    fun align(
        transcription: String,
        preferredRange: IntRange? = null,
        windowSlack: Int = -1,  // -1 = auto (5, Python default)
        minScoreThreshold: Double = DEFAULT_MIN_SCORE_THRESHOLD,
        excludeRange: IntRange? = null,
    ): AlignmentMatch? {
        // Auto windowSlack: defaultWindowSlack (instance field, runtime'da degisir)
        val effectiveWindowSlack = if (windowSlack >= 0) windowSlack else defaultWindowSlack
        if (cacheSize <= 0) {
            return alignUncached(transcription, preferredRange, effectiveWindowSlack, minScoreThreshold, excludeRange)
        }
        val key = "$transcription|$preferredRange|$effectiveWindowSlack|$minScoreThreshold|$excludeRange"
        synchronized(cache) {
            if (cache.containsKey(key)) return cache[key]
        }
        val r = alignUncached(transcription, preferredRange, effectiveWindowSlack, minScoreThreshold, excludeRange)
        synchronized(cache) { cache[key] = r }
        return r
    }

    private fun alignUncached(
        transcription: String,
        preferredRange: IntRange?,
        effectiveWindowSlack: Int,
        minScoreThreshold: Double,
        excludeRange: IntRange?,
    ): AlignmentMatch? {
        val tStart = System.nanoTime()

        // 1. Tokenize ve normalize
        val recitedTokens = transcription.split(Regex("\\s+"))
            .map { Normalizer.normalize(it) }
            .filter { it.isNotEmpty() }

        if (recitedTokens.isEmpty()) return null

        // 2. Sadece besmele ise eşleşme yok
        if (isBismillahOnly(recitedTokens)) return null

        // 3. Başlangıçta besmele varsa atla
        val processedTokens = stripBismillahPrefix(recitedTokens)
        if (processedTokens.isEmpty()) return null

        val recitedJoined = processedTokens.joinToString(" ")
        val n = processedTokens.size
        val corpusSize = index.wordCount

        // 4. Aday pozisyonları bul.
        // Strateji: Çok aday varsa cok yavas oluyor.
        // (aday * windows * 2 fuzzy çağrı). 3000 aday * 11 window * 2 = 66K fuzzy.
        // Bu telefonda ~30sn surer, kabul edilemez.
        // Cözüm: min_hits'i adaylar 3000'in altına inene kadar arttır.
        // Eger cok sikistirsak match'i kaybedebiliriz, ama aligner score >= 40 bulamazsa
        // None doner, app pratikte zaten reddederdi.
        val initialHits = maxOf(2, n / 2)
        var currentMinHits = initialHits
        var candidatePositions = index.findCandidatePositions(
            processedTokens, minHits = currentMinHits, positionFilter = preferredRange,
        )

        // Eger cok aday varsa min_hits'i arttir (her zaman aktif — test sonucu kanitladi).
        // 3000+ aday hem cok yavas hem de neredeyse her zaman gercek match'i de iceriyor.
        while (candidatePositions.size > 3000 && currentMinHits < n) {
            currentMinHits++
            val tighter = index.findCandidatePositions(
                processedTokens, minHits = currentMinHits, positionFilter = preferredRange,
            )
            if (tighter.isEmpty()) {
                currentMinHits--
                break
            }
            candidatePositions = tighter
        }

        // Hic aday yoksa min_hits=1 ile son sans
        if (candidatePositions.isEmpty()) {
            candidatePositions = index.findCandidatePositions(
                processedTokens, minHits = 1, positionFilter = preferredRange,
            )
            currentMinHits = 1
        }

        Log.d(TAG, "  candidate=${candidatePositions.size}, min_hits=$currentMinHits")

        if (candidatePositions.isEmpty()) return null

        // 5. ±N expansion — Python ile birebir.
        // Trigram lookup tam başlangıç pozisyonunu yakalamayabilir, ±2 ile şans veriyoruz.
        // Performans test'te gosterdi ki burayi kapatmak doğruluğu bozuyor.
        val expansionRange = -2..2
        val expandedStarts = HashSet<Int>(candidatePositions.size * 5)
        for (pos in candidatePositions) {
            for (offset in expansionRange) {
                val s = pos + offset
                if (s !in 0 until corpusSize) continue
                if (preferredRange != null && s !in preferredRange) continue
                if (excludeRange != null && s in excludeRange) continue
                expandedStarts.add(s)
            }
        }

        if (expandedStarts.isEmpty()) return null

        val sortedStarts = expandedStarts.toIntArray().also { it.sort() }

        // 6. Fuzzy match — pencere boyutu × aday başlangıç
        val candidateCount = sortedStarts.size
        Log.d(TAG, "align: n=$n, candidates=$candidateCount, " +
                "windows=${effectiveWindowSlack * 2 + 1}, " +
                "max_combos=${candidateCount * (effectiveWindowSlack * 2 + 1)}")

        // Window cache: (start, length) -> normalized string
        // Buyuk corpus icin once tum benzersiz (start, len) kombinasyonlari icin
        // joinNormalized hesaplamayi optimize et
        val windowCache = HashMap<Long, String>()

        var bestScore = -1.0
        var bestStart = 0
        var bestEnd = 0

        val minWindowSize = maxOf(1, n - effectiveWindowSlack)
        val maxWindowSize = n + effectiveWindowSlack

        for (windowSize in minWindowSize..maxWindowSize) {
            if (windowSize > corpusSize) continue
            val maxStart = corpusSize - windowSize

            for (i in sortedStarts) {
                if (i > maxStart) continue
                if (preferredRange != null && i + windowSize - 1 > preferredRange.last) continue
                if (excludeRange != null && i <= excludeRange.last && i + windowSize - 1 >= excludeRange.first) continue

                // Window string'i cache'den al veya hesapla
                val key = (i.toLong() shl 32) or windowSize.toLong()
                val candidate = windowCache.getOrPut(key) {
                    index.joinNormalized(i, i + windowSize - 1)
                }

                val partial = Fuzzy.partialRatio(recitedJoined, candidate)

                // Optimizasyon: partial cok dusukse sorted'i hesaplama
                // Python'da bu kontrol yok ama best_score'u gecemeyecek case'leri atlayalim
                // En iyi sonuc partial * 0.6 + 100 * 0.4 = partial * 0.6 + 40
                val maxPossibleScore = PARTIAL_WEIGHT * partial + SORT_WEIGHT * 100.0
                if (maxPossibleScore <= bestScore) continue

                val sorted = Fuzzy.tokenSortRatio(recitedJoined, candidate)
                val rawScore = PARTIAL_WEIGHT * partial + SORT_WEIGHT * sorted

                if (rawScore > bestScore) {
                    bestScore = rawScore
                    bestStart = i
                    bestEnd = i + windowSize - 1
                    if (rawScore >= EARLY_EXIT_SCORE) {
                        val ms = (System.nanoTime() - tStart) / 1_000_000L
                        Log.d(TAG, "align EARLY EXIT @ ${ms}ms (score=$rawScore)")
                        return AlignmentMatch(bestStart, bestEnd, rawScore, transcription)
                    }
                }
            }
        }

        val ms = (System.nanoTime() - tStart) / 1_000_000L
        Log.d(TAG, "align bitti ${ms}ms, best=$bestScore @ $bestStart-$bestEnd")

        if (bestScore < minScoreThreshold) return null

        return AlignmentMatch(bestStart, bestEnd, bestScore, transcription)
    }

    /**
     * aligner.py is_bismillah_only ile birebir. Basta tam besmele varsa karar, besmeleden sonra
     * kalan kelime sayisina gore verilir ("بسم الله الرحمن الرحيم قل هو الله" sure basi artik
     * reddedilmiyor — eskiden الله de besmele sayildigi icin 5/7 oranla reddediliyordu).
     */
    private fun isBismillahOnly(normalizedTokens: List<String>): Boolean {
        if (normalizedTokens.isEmpty()) return false
        val rest = stripBismillahPrefix(normalizedTokens)
        if (rest.size < normalizedTokens.size) return rest.size < 2
        // Basta tam besmele yok (eksik/bozuk okunmus olabilir) → oran kurali
        var bismillahCount = 0
        for (t in normalizedTokens) {
            if (t in BISMILLAH_TOKENS) bismillahCount++
        }
        return bismillahCount >= 3 &&
                bismillahCount.toDouble() / normalizedTokens.size >= 0.6
    }

    private fun stripBismillahPrefix(normalizedTokens: List<String>): List<String> {
        if (normalizedTokens.size < 4) return normalizedTokens
        var bismillahInFirstFour = 0
        for (i in 0 until 4) {
            if (normalizedTokens[i] in BISMILLAH_TOKENS) bismillahInFirstFour++
        }
        return if (bismillahInFirstFour >= 3) {
            normalizedTokens.subList(4, normalizedTokens.size)
        } else {
            normalizedTokens
        }
    }

    fun formatMatch(match: AlignmentMatch?): String {
        if (match == null) return "(eşleşme yok)"
        val startWord = index.getWord(match.startWordIdx)
        val endWord = index.getWord(match.endWordIdx)
        val loc = if (startWord.surah == endWord.surah && startWord.ayah == endWord.ayah) {
            "Sure ${startWord.surah}:${startWord.ayah} (kelime ${startWord.wordIdxInAyah + 1}-${endWord.wordIdxInAyah + 1})"
        } else {
            "Sure ${startWord.surah}:${startWord.ayah} → ${endWord.surah}:${endWord.ayah}"
        }
        val sb = StringBuilder()
        for (i in match.startWordIdx..match.endWordIdx) {
            if (i > match.startWordIdx) sb.append(' ')
            sb.append(index.getWord(i).text)
        }
        return "$loc\n  ${sb}\n  (skor: ${"%.1f".format(match.score)}/100)"
    }
}

data class AlignmentMatch(
    val startWordIdx: Int,
    val endWordIdx: Int,
    val score: Double,
    val recitedText: String,
)
