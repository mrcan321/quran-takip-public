package com.tilavet.takip.data

import android.util.Log
import androidx.compose.runtime.Stable
import com.tilavet.takip.aligner.QuranIndex

/**
 * Mushaf gorunumu icin ayet tablosu — tum Kuran tek liste (sure basliklari + 6236 ayet).
 *
 * QuranIndex (quran.bin) kelime bazli; UI ayet bazli calisir. Burada bir kere (~10-30 ms):
 *   ayet → sure/ayet no, ilk kelime pozisyonu
 *   sure → ilk ayet
 *   liste satiri → sure basligi (negatif) veya ayet (>= 0)
 * Kelime metinleri (Uthmani) ve meal isteyince okunur, son ~300 ayet cache'lenir.
 *
 * Besmele: alquran.cloud Uthmani metni 1. ayetlerin basina besmele ekliyor (Fatiha ve Tevbe haric).
 * Mushaf'taki gibi besmele sure basliginda gosterilir, 1. ayetten gizlenir (kelime pozisyonlari
 * degismez — aligner/state machine ayni global indeksleri kullanmaya devam eder).
 *
 * @Stable: olusturulduktan sonra degismez (icteki cache disaridan gorunmez) — Compose, ses seviyesi
 * gibi sik guncellemelerde ayet satirlarini bosuna yeniden cizmesin.
 */
@Stable
class MushafData private constructor(
    private val index: QuranIndex,
    private val meals: MealLoader?,
    val ayahCount: Int,
    private val ayahSurah: IntArray,      // ayet → sure no
    private val ayahNo: IntArray,         // ayet → sure icindeki ayet no
    private val ayahFirstWord: IntArray,  // ayet → ilk kelime pozisyonu (ayahCount+1 boy, son = wordCount)
    private val ayahSkip: IntArray,       // ayet → basta gizlenecek kelime sayisi (besmele)
    private val surahFirstAyah: IntArray, // sure (1..114) → ilk ayet indeksi, [115] = ayahCount
    val itemCount: Int,
    private val items: IntArray,          // liste satiri → ayet indeksi veya -sure (baslik)
    private val ayahItem: IntArray,       // ayet → liste satiri
    /** Sure basliginda gosterilecek Uthmani besmele (2. surenin 1. ayetinden). */
    val besmele: String,
) {
    companion object {
        /**
         * Korpus metni (Tanzil Uthmani, alquran.cloud) → KFGQPC HAFS fontunun bekledigi yazim (Tarteel /
         * quran.com metni gibi). Sadece EKRAN icin; kelime sayisi ve pozisyonlar degismez (hizalama ayni).
         * Tanzil ile KFGQPC iki isaretin kodunu ters kullaniyor; KFGQPC'de bazi kodlar noktali daire olarak cizili:
         *   - U+0652 (Tanzil sukun)               → U+06E1 (Medine mushafindaki "ۡ")
         *   - U+06DF (okunmayan harf yuvarlak sifiri) → U+0652 (KFGQPC'de yuvarlak sifir bu kodda; 06DF noktali daire)
         *   - tatweel + ust elif ("مَـٰ")          → ust elif ("مَٰ") — KFGQPC'de tatweel uzun cizgi
         *     (hemze/kucuk ye/vav onundeki tatweel mushaf yazimi, kalir)
         *   - U+06EB (12:11 ismam, noktali daire)   → U+06EC (kucuk daire)
         *   - U+06E3 (52:37 alttaki kucuk sin)      → cizilmez (fontta yok, noktali daire)
         * HarfBuzz ile 6236 ayet kontrol edildi: donusumden sonra noktali daire glifi yok.
         */
        fun displayText(t: String): String {
            val sb = StringBuilder(t.length)
            for (i in t.indices) {
                when (val c = t[i]) {
                    '\u0640' -> if (i + 1 >= t.length || t[i + 1] != '\u0670') sb.append(c)
                    '\u0652' -> sb.append('\u06E1')
                    '\u06DF' -> sb.append('\u0652')
                    '\u06EB' -> sb.append('\u06EC')
                    '\u06E3' -> {}
                    else -> sb.append(c)
                }
            }
            return sb.toString()
        }

        private const val TAG = "MushafData"
        private val BESMELE_NORMALIZED = listOf("بسم", "الله", "الرحمن", "الرحيم")
        private const val CACHE_SIZE = 300

        fun build(index: QuranIndex, meals: MealLoader?): MushafData {
            val t0 = System.nanoTime()
            val n = index.wordCount

            // 1. Ayet sinirlari (kelimeler sure/ayet sirasinda)
            val surahs = ArrayList<Int>(6300)
            val ayahs = ArrayList<Int>(6300)
            val firsts = ArrayList<Int>(6300)
            var prev = -1
            for (pos in 0 until n) {
                val sa = index.getSurahAyah(pos)
                if (sa != prev) {
                    surahs.add(sa ushr 16)
                    ayahs.add(sa and 0xFFFF)
                    firsts.add(pos)
                    prev = sa
                }
            }
            val ayahCount = firsts.size
            val ayahSurah = surahs.toIntArray()
            val ayahNo = ayahs.toIntArray()
            val ayahFirstWord = IntArray(ayahCount + 1).also { arr ->
                for (i in 0 until ayahCount) arr[i] = firsts[i]
                arr[ayahCount] = n
            }

            // 2. Sure → ilk ayet
            val surahFirstAyah = IntArray(116) { -1 }
            for (a in 0 until ayahCount) {
                val s = ayahSurah[a]
                if (s in 1..114 && surahFirstAyah[s] < 0) surahFirstAyah[s] = a
            }
            surahFirstAyah[115] = ayahCount

            // 3. Besmele gizleme (Fatiha ve Tevbe haric 1. ayetler)
            val ayahSkip = IntArray(ayahCount)
            var besmele = ""
            for (s in 1..114) {
                if (s == 1 || s == 9) continue
                val a = surahFirstAyah[s]
                if (a < 0) continue
                val first = ayahFirstWord[a]
                val len = ayahFirstWord[a + 1] - first
                if (len <= 4) continue  // tek basina besmele olamaz, dokunma
                val isBesmele = (0 until 4).all { k -> index.getNormalized(first + k) == BESMELE_NORMALIZED[k] }
                if (isBesmele) {
                    ayahSkip[a] = 4
                    if (besmele.isEmpty()) besmele = (0 until 4).joinToString(" ") { k -> displayText(index.getText(first + k)) }
                }
            }
            if (besmele.isEmpty()) {
                // Korpusta 1. ayetlerde besmele yoksa Fatiha 1:1'i kullan
                val a = surahFirstAyah[1]
                if (a >= 0) besmele = (ayahFirstWord[a] until ayahFirstWord[a + 1]).joinToString(" ") { displayText(index.getText(it)) }
            }

            // 4. Liste satirlari: her surenin basinda baslik
            val items = IntArray(ayahCount + 114)
            val ayahItem = IntArray(ayahCount)
            var k = 0
            for (a in 0 until ayahCount) {
                if (a == 0 || ayahSurah[a] != ayahSurah[a - 1]) items[k++] = -ayahSurah[a]
                ayahItem[a] = k
                items[k++] = a
            }

            val ms = (System.nanoTime() - t0) / 1_000_000L
            Log.d(TAG, "Hazir: $ayahCount ayet, $k satir, besmele gizlenen sure ${ayahSkip.count { it > 0 }} (${ms}ms)")
            return MushafData(
                index, meals, ayahCount, ayahSurah, ayahNo, ayahFirstWord, ayahSkip,
                surahFirstAyah, k, items, ayahItem, besmele,
            )
        }
    }

    // ============================================================
    // Liste
    // ============================================================
    /** Liste satiri: >= 0 ayet indeksi, < 0 → -sure (sure basligi). */
    fun itemAt(listIndex: Int): Int = items[listIndex]

    /** LazyColumn key'i (benzersiz, Int): baslik -sure, ayet indeksi. */
    fun itemKey(listIndex: Int): Int = items[listIndex]

    fun listIndexOfAyah(ayah: Int): Int = ayahItem[ayah]

    /** Satirin ait oldugu sure (baslik veya ayet). */
    fun surahOfItem(listIndex: Int): Int {
        val v = items[listIndex.coerceIn(0, itemCount - 1)]
        return if (v < 0) -v else ayahSurah[v]
    }

    /** Satirdaki (veya basliktan sonraki ilk) ayet. */
    fun ayahOfItem(listIndex: Int): Int {
        val v = items[listIndex.coerceIn(0, itemCount - 1)]
        return if (v >= 0) v else surahFirstAyah[-v]
    }

    // ============================================================
    // Ayet
    // ============================================================
    fun surahOf(ayah: Int): Int = ayahSurah[ayah]
    fun ayahNumber(ayah: Int): Int = ayahNo[ayah]

    /** (sure, ayet no) → global ayet indeksi, yoksa null. */
    fun ayahIndex(surah: Int, ayah: Int): Int? {
        if (surah !in 1..114) return null
        val first = surahFirstAyah[surah]
        if (first < 0) return null
        val a = first + ayah - 1
        return if (a < ayahCount && ayahSurah[a] == surah && ayahNo[a] == ayah) a else null
    }

    /** Global kelime pozisyonu → ayet indeksi (ikili arama). */
    fun ayahOfWord(pos: Int): Int {
        var lo = 0
        var hi = ayahCount - 1
        while (lo < hi) {
            val mid = (lo + hi + 1) ushr 1
            if (ayahFirstWord[mid] <= pos) lo = mid else hi = mid - 1
        }
        return lo
    }

    /** Ayette gosterilen ilk kelimenin global pozisyonu (besmele gizliyse ondan sonrasi). */
    fun firstShownWord(ayah: Int): Int = ayahFirstWord[ayah] + ayahSkip[ayah]

    /** Ayetin son kelimesinin global pozisyonu. */
    fun lastWordOf(ayah: Int): Int = ayahFirstWord[ayah + 1] - 1

    /**
     * Okunan ayet [from]'dan [to]'ya giderken atlanan ayetler (ekranda sirayla gosterilir; bos = dogrudan git):
     * - Ayni sure, ileri: aradaki ayetler, en fazla [max] tane (ardisik ayet, geri gidis, daha uzak atlama → bos).
     * - Baska sureye gecis (Fatiha → zamm, sure → sure, zamm → 2. rekat Fatiha'si) surenin basina yakin bir ayete:
     *   surenin basindan hedefe kadar, en fazla [maxOpening] tane — imam sureyi bastan okudu, ilk ayet(ler) gec
     *   tanindi (cuma #2: Asr'a 103:3'te kilit, 103:1-2 hic gorunmedi). Fatiha'da 1:1 (besmele) sessiz okunur →
     *   1:2'den. Hedef surenin ortasindaysa (zamm ortadan baslayabilir: 21:102) bos.
     */
    fun skippedAyahs(from: Int, to: Int, max: Int, maxOpening: Int = 0): IntRange {
        val s = ayahSurah[to]
        if (ayahSurah[from] == s)
            return if (to - from in 2..max + 1) (from + 1) until to else IntRange.EMPTY
        val first = surahFirstAyah[s] + if (s == 1) 1 else 0
        return if (to - first in 1..maxOpening) first until to else IntRange.EMPTY
    }

    /** Ayni suredeki sonraki ayet, sure bittiyse null. */
    fun nextAyahInSurah(ayah: Int): Int? =
        if (ayah + 1 < ayahCount && ayahSurah[ayah + 1] == ayahSurah[ayah]) ayah + 1 else null

    private val wordCache = object : LinkedHashMap<Int, List<String>>(CACHE_SIZE, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<Int, List<String>>?): Boolean =
            size > CACHE_SIZE
    }

    /** Ayetin gosterilen (Uthmani, KFGQPC yazimina cevrilmis — bkz. displayText) kelimeleri. */
    fun words(ayah: Int): List<String> = synchronized(wordCache) {
        wordCache.getOrPut(ayah) {
            (firstShownWord(ayah) until ayahFirstWord[ayah + 1]).map { displayText(index.getText(it)) }
        }
    }

    fun meal(ayah: Int): String? = meals?.getMeal(ayahSurah[ayah], ayahNo[ayah])

    fun surahInfo(surah: Int): MealLoader.SurahInfo? = meals?.getSurahInfo(surah)

    fun surahNameTr(surah: Int): String = surahInfo(surah)?.nameTr ?: "Sure $surah"

    fun surahAyahCount(surah: Int): Int = surahFirstAyah[surah + 1].let { next ->
        // bir sonraki surenin ilk ayeti - bu surenin ilk ayeti
        var nxt = next
        var s = surah + 1
        while (nxt < 0 && s < 115) { s++; nxt = surahFirstAyah[s] }
        nxt - surahFirstAyah[surah]
    }

    /** Log etiketi: "Rahman 55:5" (sure numarasi analiz icin kalir; ekranda [ayahTag]). */
    fun label(ayah: Int): String = "${surahNameTr(ayahSurah[ayah])} ${ayahSurah[ayah]}:${ayahNo[ayah]}"

    /**
     * Ekrandaki ayet etiketi: "A'râf: 55" — once sure adi, sonra ayet numarasi (kullanici: "7:55 gibi gostermesin";
     * ayet satiri, alt bar, G2 basligi ayni bicimde).
     */
    fun ayahTag(ayah: Int): String = "${surahNameTr(ayahSurah[ayah])}: ${ayahNo[ayah]}"
}
