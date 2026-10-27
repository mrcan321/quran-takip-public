package com.tilavet.takip.report

/**
 * Namaz raporu (ana ekran → RAPOR): oturum log'undan (SessionLog, cacheDir/sessions/tilavet-YYYYMMDD-HHmmss.txt) namazda
 * okunan ayetler — namaz, rekat, sure bolumu. Kullanici (27.10): "anaekranda bir buton ile son 3 kayda ait namazda okunan
 * ayetleri guzel bir rapor html sunsun; ayetin arapcasi turkce meali olsun; rapor bitiminde isteyenler icin tefsir".
 *
 * Kaynak satirlar (pipeline / ViewModel log'u):
 *   [chunk N] ZAMM→ZAMM matched score=… | 23:56,23:57 [...] (… t=102,5s) txt='…'   kilitli eslesme ve ayetleri
 *   [rekat] t=…s 2. rekat (Fatiha) · sessiz rekat: 3. rekat (…) · kamet: yeni namaz · selam (namaz bitti, 4 rekat)
 * Imam ayetleri sirayla okur: ayni surede ileri giden eslesmeler arasi doldurulur (ASR'nin bos dondugu / tek parcada gecen
 * ayetler — ekranda da AyahStepper gosterir); Fatiha hep tam (1-7, besmele sessiz); bir surenin basina yakin (ilk
 * [OPENING] ayet) ilk eslesme surenin basindan; onceki rekatta kalinan yerden devam eden zamm kaldigi yerden.
 * Rekat satiri, rekati baslatan Fatiha parcasindan sonra yazildigi icin o Fatiha yeni rekata tasinir.
 *
 * Android'e bagli degil (tests/jvm `report`).
 */
object NamazReport {

    /**
     * Ayni surede bu kadar ayet ileri giden eslesme ayni bolum (aradakiler okundu, duyulamadi): imam ayni rekatta sureyi
     * kesintisiz okur; ASR'nin bos dondugu bir dakikada 10+ kisa ayet gecebilir.
     */
    const val GAP_FILL = 20
    /** Yeni sureye ilk eslesme bu ayete kadarsa bolum surenin basindan (AyahStepper.MAX_OPENING + 1). */
    const val OPENING = 5

    class Segment(val surah: Int, val from: Int, var to: Int)

    /** [no] null = kayit namazin ortasinda basladi (rekat bilinmiyor); [silent] = sessiz rekat (3. / 4.). */
    class Rakat(val no: Int?, val silent: Boolean = false) {
        val segments = mutableListOf<Segment>()
    }

    class Namaz {
        val rakats = mutableListOf<Rakat>()
        /** Selamda rekat sayaci (RakatTracker), bilinmiyorsa null. */
        var rakatCount: Int? = null
        /** Ilk okunan ayetin oturumdaki zamani (sn). */
        var firstSec: Double? = null
        val isEmpty: Boolean get() = rakats.all { it.segments.isEmpty() }
    }

    private val CHUNK = Regex("""\[chunk \d+] \w+→(\w+) matched score=\S+ dec=\w+ \| ([\d:,]+) .*?\bt=([\d.,]+)s\)""")
    private val RAKAT_FATIHA = Regex("""\[rekat] t=[\d.,]+s (\d+)\. rekat \(Fatiha""")
    private val RAKAT_SILENT = Regex("""\[rekat] t=[\d.,]+s sessiz rekat: (\d+)\. rekat""")
    private val KAMET = Regex("""\[rekat] t=[\d.,]+s kamet: yeni namaz""")
    private val SELAM = Regex("""\[rekat] t=[\d.,]+s selam \(namaz bitti(?:, (\d+) rekat)?""")

    /** Oturum log'unun satirlari → namazlar (bos olanlar atilir). */
    fun parse(lines: Sequence<String>): List<Namaz> = Parser().apply { lines.forEach { line(it) } }.result()

    private class Parser {
        val out = mutableListOf<Namaz>()
        var cur = Namaz()
        var rakat: Rakat? = null
        /** Son parcanin yeni actigi Fatiha bolumu (rekat satiri gelince yeni rekata tasinir). */
        var pendingFatiha: Pair<Rakat, Segment>? = null

        fun line(l: String) {
            CHUNK.find(l)?.let { m ->
                pendingFatiha = null
                val state = m.groupValues[1]
                if (state != "FATIHA" && state != "ZAMM") return
                val t = m.groupValues[3].replace(',', '.').toDoubleOrNull()
                if (cur.firstSec == null) cur.firstSec = t
                for (v in m.groupValues[2].split(',')) {
                    val (s, a) = v.split(':').mapNotNull { it.toIntOrNull() }.takeIf { it.size == 2 } ?: continue
                    add(s, a)
                }
                return
            }
            RAKAT_FATIHA.find(l)?.let { m ->
                val r = Rakat(m.groupValues[1].toInt())
                pendingFatiha?.let { (old, seg) ->
                    if (old.segments.lastOrNull() === seg) {
                        old.segments.removeAt(old.segments.size - 1)
                        r.segments += seg
                        if (old.segments.isEmpty()) cur.rakats.remove(old)
                    }
                }
                pendingFatiha = null
                cur.rakats += r
                rakat = r
                return
            }
            RAKAT_SILENT.find(l)?.let { m ->
                val r = Rakat(m.groupValues[1].toInt(), silent = true)
                cur.rakats += r
                rakat = r
                return
            }
            if (KAMET.containsMatchIn(l)) {
                close()
                return
            }
            SELAM.find(l)?.let { m ->
                cur.rakatCount = m.groupValues[1].toIntOrNull()
                close()
            }
        }

        fun add(s: Int, a: Int) {
            val r = rakat ?: Rakat(null).also { cur.rakats += it; rakat = it }
            val last = r.segments.lastOrNull()
            if (s == 1) {
                if (last?.surah != 1) {
                    val seg = Segment(1, 1, 7)
                    r.segments += seg
                    pendingFatiha = r to seg
                }
                return
            }
            if (last != null && last.surah == s && a >= last.from - 2 && a <= last.to + GAP_FILL) {
                if (a > last.to) last.to = a
                return
            }
            // onceki rekatta (ayni namazda) bu surede kalinan yerden devam
            val prev = cur.rakats.flatMap { it.segments }.lastOrNull { it.surah == s && it !== last }
            val from = when {
                prev != null && a > prev.to && a <= prev.to + GAP_FILL -> prev.to + 1
                a <= OPENING && prev == null -> 1
                else -> a
            }
            r.segments += Segment(s, from, a)
        }

        fun close() {
            if (!cur.isEmpty) out += cur
            cur = Namaz()
            rakat = null
            pendingFatiha = null
        }

        fun result(): List<Namaz> {
            if (!cur.isEmpty) out += cur
            return out
        }
    }
}
