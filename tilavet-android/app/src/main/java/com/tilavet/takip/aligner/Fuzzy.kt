package com.tilavet.takip.aligner

/**
 * RapidFuzz fuzz_py.py birebir Kotlin port'u — BIT-PARALLEL LCS.
 *
 * partial_ratio / ratio "Indel" benzerligi kullanir: indel_distance = |a| + |b| - 2 * LCS(a, b).
 * Eski surum LCS'yi karakter karakter DP ile hesapliyordu (O(|a| * |b|)); aligner BEKLEME'de
 * binlerce pencere x 3 faz tarandigi icin telefonda chunk basina 5-15 sn suruyordu.
 *
 * Simdi: Hyyro / Allison-Dix bit-parallel LCS. Kisa string'in her karakteri icin bir bit maskesi,
 * uzun string'in her karakterinde 64 pozisyon tek islemde:
 *     U = S & M[c];  S = (S + U) | (S & ~M[c]);   LCS = |a| - popcount(S)
 * Sonuc DP ile BIREBIR ayni (tam sayi LCS), sadece ~64 kat daha az islem.
 * Uzun string'ler icin 64 bitlik bloklar arasinda carry tasinir.
 *
 * Ek optimizasyonlar (sonucu degistirmez):
 *  - partial_ratio'da pencere hic shorter'dan uzun olmaz → tum pencereler shorter'in TEK pattern'iyle
 *    olculur (LCS simetrik); longer'in karakter→satir indeksleri bir kere hesaplanir.
 *  - Pattern <= 64 karakterde tek Long'luk hizli yol.
 *  - Pattern'ler 4 girisli LRU cache'te, yeniden kullanilan nesnelerde (aligner ayni recitedJoined'i
 *    binlerce pencereye karsi cagiriyor); token siralama regex'siz ve son sonuc cache'li.
 * JVM olcumu (43 aligner case): eski DP 22.6 sn → 2.6 sn (~10x), 51 fixture + 20000 rastgele cift birebir.
 */
object Fuzzy {

    // ============================================================
    // Pattern: kisa string'in karakter → bit maskesi tablosu
    // Yeniden kullanilabilir (init ile yeniden kurulur, bellek ayirmaz) — aligner binlerce kez cagiriyor.
    // ============================================================
    private class Pattern {
        var source: String = ""
        var start = 0
        var end = 0
        var len = 0
        var blocks = 0
        private var capacity = 0
        private var keys = CharArray(0)
        private var slots = IntArray(0)         // 0 = bos, >0 = maske satiri + 1
        private var used = IntArray(0)          // dolu slot indeksleri (hizli temizlik)
        private var usedCount = 0
        var maskData = LongArray(0)             // satir * blocks + blok
        private var rows = 0

        fun init(s: String, st: Int, en: Int) {
            source = s
            start = st
            end = en
            len = en - st
            blocks = (len + 63) ushr 6
            var cap = 16
            while (cap < len * 2) cap = cap shl 1
            if (cap > capacity) {
                capacity = cap
                keys = CharArray(cap)
                slots = IntArray(cap)
                used = IntArray(cap)
            } else {
                for (k in 0 until usedCount) slots[used[k]] = 0
            }
            usedCount = 0
            rows = 0
            if (maskData.size < len * blocks) maskData = LongArray(len * blocks)
            for (i in 0 until len) {
                val c = s[st + i]
                var row = findRow(c)
                if (row < 0) {
                    row = rows++
                    java.util.Arrays.fill(maskData, row * blocks, row * blocks + blocks, 0L)
                    insert(c, row)
                }
                val idx = row * blocks + (i ushr 6)
                maskData[idx] = maskData[idx] or (1L shl (i and 63))
            }
        }

        private fun hash(c: Char): Int = (c.code * -0x61c88647) ushr 16 and (capacity - 1)

        /** Karakterin maske satiri, pattern'de yoksa -1. */
        fun findRow(c: Char): Int {
            var h = hash(c)
            while (true) {
                val v = slots[h]
                if (v == 0) return -1
                if (keys[h] == c) return v - 1
                h = (h + 1) and (capacity - 1)
            }
        }

        private fun insert(c: Char, row: Int) {
            var h = hash(c)
            while (slots[h] != 0) h = (h + 1) and (capacity - 1)
            keys[h] = c
            slots[h] = row + 1
            used[usedCount++] = h
        }

        fun isFor(s: String, st: Int, en: Int): Boolean = source === s && start == st && end == en
    }

    /**
     * Kucuk LRU pattern cache (thread basina). Aligner ayni cagride hem okunan metnin hem de
     * siralanmis halinin pattern'ini istiyor — tek girisli cache birbirini eziyordu.
     */
    private class PatternCache {
        private val entries = Array(4) { Pattern() }
        private val stamps = LongArray(4)
        private var clock = 0L

        fun get(s: String, st: Int, en: Int): Pattern {
            clock++
            var oldest = 0
            for (k in entries.indices) {
                if (entries[k].isFor(s, st, en)) {
                    stamps[k] = clock
                    return entries[k]
                }
                if (stamps[k] < stamps[oldest]) oldest = k
            }
            entries[oldest].init(s, st, en)
            stamps[oldest] = clock
            return entries[oldest]
        }
    }

    private val patternCache = ThreadLocal.withInitial { PatternCache() }
    private val stateBuffer = ThreadLocal.withInitial { LongArray(8) }

    private fun patternFor(s: String, start: Int, end: Int): Pattern = patternCache.get()!!.get(s, start, end)

    private fun stateFor(blocks: Int): LongArray {
        var arr = stateBuffer.get()!!
        if (arr.size < blocks) {
            arr = LongArray(maxOf(blocks, arr.size * 2))
            stateBuffer.set(arr)
        }
        return arr
    }

    private val rowBuffer = ThreadLocal.withInitial { IntArray(256) }

    private fun rowBufferFor(n: Int): IntArray {
        var arr = rowBuffer.get()!!
        if (arr.size < n) {
            arr = IntArray(maxOf(n, arr.size * 2))
            rowBuffer.set(arr)
        }
        return arr
    }

    /** LCS(pattern, b[bStart, bEnd)) — bit-parallel. */
    private fun lcs(p: Pattern, b: String, bStart: Int, bEnd: Int): Int {
        if (p.len == 0 || bEnd <= bStart) return 0
        val rows = rowBufferFor(bEnd - bStart)
        for (j in bStart until bEnd) rows[j - bStart] = p.findRow(b[j])
        return lcsRows(p, rows, 0, bEnd - bStart)
    }

    /**
     * LCS(pattern, pencere) — pencere karakterleri pattern maske satiri olarak verilir (rows[j], yoksa -1).
     * Hyyro/Allison-Dix: U = S & M; S = (S + U) | (S & ~M); LCS = len - popcount(S)
     */
    private fun lcsRows(p: Pattern, rows: IntArray, bStart: Int, bEnd: Int): Int {
        if (p.len == 0 || bEnd <= bStart) return 0
        val blocks = p.blocks
        val masks = p.maskData
        if (blocks == 1) {
            // Hizli yol (pattern <= 64 karakter — aligner'da en yaygin durum): tek Long, elde yok
            var sw = -1L
            for (j in bStart until bEnd) {
                val row = rows[j]
                if (row < 0) continue   // Pattern'de olmayan karakter: M = 0 → S degismez
                val mw = masks[row]
                val u = sw and mw
                sw = (sw + u) or (sw and mw.inv())
            }
            val v = if (p.len == 64) sw else sw and ((1L shl p.len) - 1)
            return p.len - java.lang.Long.bitCount(v)
        }
        val s = stateFor(blocks)
        java.util.Arrays.fill(s, 0, blocks, -1L)
        for (j in bStart until bEnd) {
            val row = rows[j]
            if (row < 0) continue
            val base = row * blocks
            var carry = 0L
            for (w in 0 until blocks) {
                val sw = s[w]
                val mw = masks[base + w]
                val u = sw and mw
                val sum = sw + u + carry
                // tam toplayici elde biti (bit 63): (a & b) | ((a | b) & ~sum)
                carry = ((sw and u) or ((sw or u) and sum.inv())) ushr 63
                s[w] = sum or (sw and mw.inv())
            }
        }
        // S'de kalan 1 bitler = LCS'ye girmeyen pattern karakterleri (sadece ilk len bit sayilir)
        var ones = 0
        val lastBits = p.len and 63
        for (w in 0 until blocks) {
            var v = s[w]
            if (w == blocks - 1 && lastBits != 0) v = v and ((1L shl lastBits) - 1)
            ones += java.lang.Long.bitCount(v)
        }
        return p.len - ones
    }

    // ============================================================
    // Indel distance — a[aStart, aEnd) ve b[bStart, bEnd)
    // ============================================================
    private fun indelDistance(
        a: String, aStart: Int, aEnd: Int,
        b: String, bStart: Int, bEnd: Int,
    ): Int {
        val m = aEnd - aStart
        val n = bEnd - bStart
        if (m == 0) return n
        if (n == 0) return m
        // Kisa olan pattern olsun (daha az blok)
        return if (m <= n) {
            m + n - 2 * lcs(patternFor(a, aStart, aEnd), b, bStart, bEnd)
        } else {
            m + n - 2 * lcs(patternFor(b, bStart, bEnd), a, aStart, aEnd)
        }
    }

    private fun indelNormalizedSimilarity(
        a: String, aStart: Int, aEnd: Int,
        b: String, bStart: Int, bEnd: Int,
    ): Double {
        val maximum = (aEnd - aStart) + (bEnd - bStart)
        if (maximum == 0) return 1.0
        val dist = indelDistance(a, aStart, aEnd, b, bStart, bEnd)
        return 1.0 - (dist.toDouble() / maximum)
    }

    // ============================================================
    // ratio (Indel similarity)
    // ============================================================
    fun ratio(s1: String, s2: String): Double {
        if (s1.isEmpty() && s2.isEmpty()) return 100.0
        val lensum = s1.length + s2.length
        if (lensum == 0) return 100.0
        val dist = indelDistance(s1, 0, s1.length, s2, 0, s2.length)
        return (lensum - dist).toDouble() / lensum * 100.0
    }

    // ============================================================
    // partial_ratio (3-faz pencere arama)
    // ============================================================
    fun partialRatio(s1: String, s2: String): Double {
        if (s1.isEmpty() && s2.isEmpty()) return 100.0
        if (s1.isEmpty() || s2.isEmpty()) return 0.0

        val (shorter, longer) = if (s1.length <= s2.length) Pair(s1, s2) else Pair(s2, s1)

        var bestScore = partialRatioImpl(shorter, longer)

        if (bestScore < 100.0 && s1.length == s2.length) {
            val score2 = partialRatioImpl(longer, shorter)
            if (score2 > bestScore) bestScore = score2
        }

        return bestScore
    }

    /**
     * _partial_ratio_impl — assumes len(shorter) <= len(longer)
     * Her pencere shorter'in (cache'li) pattern'ine karsi bit-parallel LCS ile olculur.
     * Pencere hic bir fazda shorter'dan uzun olmadigi icin LCS simetrisiyle hep ayni pattern
     * kullanilir — pencere basina pattern kurulmaz (eski profilde en buyuk maliyet buydu).
     */
    private fun partialRatioImpl(shorter: String, longer: String): Double {
        val lenShort = shorter.length
        val lenLong = longer.length
        if (lenShort == 0) return 0.0

        // Karakter set'i = pattern tablosu (boxing'li HashSet<Char> yerine)
        val pat = patternFor(shorter, 0, lenShort)
        // longer'in her karakteri icin maske satiri (yoksa -1) — pencere basina hash aramasi yerine bir kere
        val rows = rowBufferFor(lenLong)
        for (j in 0 until lenLong) rows[j] = pat.findRow(longer[j])

        var bestSim = 0.0

        // ============ FAZ 1: longer[0..i), i in 1..lenShort-1 ============
        for (i in 1 until lenShort) {
            if (i > lenLong) break
            if (rows[i - 1] < 0) continue

            val sim = windowSimilarity(pat, rows, 0, i)
            if (sim > bestSim) {
                bestSim = sim
                if (bestSim >= 1.0) return 100.0
            }
        }

        // ============ FAZ 2: longer[i..i+lenShort), i in 0..lenLong-lenShort-1 ============
        for (i in 0 until (lenLong - lenShort)) {
            if (rows[i + lenShort - 1] < 0) continue

            val sim = windowSimilarity(pat, rows, i, i + lenShort)
            if (sim > bestSim) {
                bestSim = sim
                if (bestSim >= 1.0) return 100.0
            }
        }

        // ============ FAZ 3: longer[i..lenLong), i in lenLong-lenShort..lenLong-1 ============
        val phase3Start = maxOf(0, lenLong - lenShort)
        for (i in phase3Start until lenLong) {
            if (rows[i] < 0) continue

            val sim = windowSimilarity(pat, rows, i, lenLong)
            if (sim > bestSim) {
                bestSim = sim
                if (bestSim >= 1.0) return 100.0
            }
        }

        return bestSim * 100.0
    }

    /** indelNormalizedSimilarity(pattern kaynagi, pencere) — pencere onceden hesaplanmis satir indeksleriyle. */
    private fun windowSimilarity(p: Pattern, rows: IntArray, bStart: Int, bEnd: Int): Double {
        val maximum = p.len + (bEnd - bStart)
        if (maximum == 0) return 1.0
        val dist = maximum - 2 * lcsRows(p, rows, bStart, bEnd)
        return 1.0 - (dist.toDouble() / maximum)
    }

    // ============================================================
    // token_sort_ratio
    // ============================================================
    fun tokenSortRatio(s1: String, s2: String): Double {
        if (s1.isEmpty() && s2.isEmpty()) return 100.0
        if (s1.isEmpty() || s2.isEmpty()) return 0.0

        val sorted1 = sortTokens(s1)
        val sorted2 = sortTokens(s2)
        return ratio(sorted1, sorted2)
    }

    // Aligner ayni recitedJoined'i binlerce kez siralatiyordu — son sonucu cache'le (string kimligiyle)
    private val lastSorted = ThreadLocal<Pair<String, String>?>()

    private fun sortTokens(s: String): String {
        val cached = lastSorted.get()
        if (cached != null && cached.first === s) return cached.second
        val sorted = sortTokensUncached(s)
        lastSorted.set(Pair(s, sorted))
        return sorted
    }

    /** Python str.split() + sorted + join — regex'siz (bosluk karakterlerinde bol). */
    private fun sortTokensUncached(s: String): String {
        val tokens = ArrayList<String>()
        var i = 0
        val n = s.length
        while (i < n) {
            while (i < n && s[i].isWhitespace()) i++
            val st = i
            while (i < n && !s[i].isWhitespace()) i++
            if (i > st) tokens.add(s.substring(st, i))
        }
        if (tokens.isEmpty()) return ""
        tokens.sort()
        return tokens.joinToString(" ")
    }

    // ============================================================
    // Public test API'leri (debug için)
    // ============================================================
    fun debugIndelDistance(a: String, b: String): Int = indelDistance(a, 0, a.length, b, 0, b.length)
    fun debugIndelRatio(a: String, b: String): Double = indelNormalizedSimilarity(a, 0, a.length, b, 0, b.length)
}
