import com.tilavet.takip.report.NamazReport
import com.tilavet.takip.report.ReportHtml
import com.tilavet.takip.util.RecordingMerge

/**
 * Namaz raporu (report/NamazReport + ReportHtml): oturum log'u → namaz / rekat / sure bolumleri → HTML. Log satirlari
 * telefonun SessionLog bicimindedir (yatsi 25.10 ve 27.10 kayitlarindan sadelestirildi).
 */
fun reportTests(): Int {
    var passed = 0
    var total = 0
    fun ok(name: String, cond: Boolean, detail: () -> String = { "" }) {
        total++
        if (cond) passed++ else println("  BASARISIZ: $name ${detail()}")
    }
    fun chunk(n: Int, before: String, after: String, verses: String, t: String) =
        "19:5$n D AudioPipeline: [chunk $n] $before→$after matched score=95,0 dec=RNNT | $verses [kilitli takip] " +
            "(parca=5sn 6,0s rms=0,0600 asr=900ms sm=1ms gecikme=901ms t=${t}s) txt='x'"

    // Yatsi 27.10 gibi: 1. rekat Fatiha + Mu'minun 23:51..23:68 (bosluklu), 2. rekat Fatiha + 23:68..23:77, sessiz rekat,
    // bolunmus selam (rekat satiri yok → namaz sonu yok, tek namaz)
    val yatsi = listOf(
        "=== Tilavet Takip oturum log'u: tilavet-20261027-194923.txt ===",
        chunk(2, "BEKLEME", "FATIHA", "1:2", "15,0"),
        "19:49:39.950 D MainViewModel: [rekat] t=15,0s 1. rekat (Fatiha)",
        chunk(3, "FATIHA", "FATIHA", "1:3,1:4", "20,0"),
        chunk(7, "FATIHA", "FATIHA", "1:6,1:7", "35,4"),
        chunk(12, "FATIHA", "ZAMM", "23:51", "57,5"),
        chunk(13, "ZAMM", "ZAMM", "23:51", "62,5"),
        chunk(21, "ZAMM", "ZAMM", "23:56,23:57", "102,5"),
        chunk(42, "ZAMM", "ZAMM", "23:68", "204,7"),
        "19:52:54.805 D MainViewModel: [metin] t=211,2s ses kesildi",
        chunk(49, "ZAMM", "ZAMM", "2:85", "234,9").replace("matched", "low_confidence"),   // kilit degil
        chunk(53, "ZAMM", "FATIHA", "1:2", "252,3"),
        "19:53:37.012 D MainViewModel: [rekat] t=252,3s 2. rekat (Fatiha)",
        chunk(59, "FATIHA", "FATIHA", "1:7", "282,3"),
        chunk(61, "FATIHA", "ZAMM", "23:68", "291,1"),
        chunk(64, "ZAMM", "ZAMM", "23:69,23:70", "306,1"),
        chunk(82, "ZAMM", "ZAMM", "23:77", "394,1"),
        "19:58:37.659 D MainViewModel: [rekat] t=553,1s sessiz rekat: 3. rekat (semiallah, okumadan 159 sn sonra)",
        "20:00:02.659 D MainViewModel: [zikir] t=638,1s SELAM",
    )
    val y = NamazReport.parse(yatsi.asSequence())
    ok("yatsi tek namaz", y.size == 1) { "${y.size}" }
    val r = y.firstOrNull()?.rakats ?: emptyList()
    fun segs(i: Int) = r.getOrNull(i)?.segments?.joinToString(" ") { "${it.surah}:${it.from}-${it.to}" } ?: "-"
    ok("1. rekat", r.getOrNull(0)?.no == 1 && segs(0) == "1:1-7 23:51-68") { segs(0) }
    ok("2. rekat (Fatiha yeni rekata tasindi)", r.getOrNull(1)?.no == 2 && segs(1) == "1:1-7 23:68-77") { segs(1) }
    ok("sessiz rekat", r.getOrNull(2)?.no == 3 && r[2].silent && r[2].segments.isEmpty())
    ok("ilk okuma zamani", y.firstOrNull()?.firstSec == 15.0)

    // Yatsi 25.10 gibi: kayit 1. rekatin zammi ortasinda (Bakara), selamla biten namaz, sonra kamet + yeni namaz;
    // surenin basina yakin ilk eslesme (Insan 76:2) surenin basindan, onceki rekatta kalinan yerden devam
    val iki = listOf(
        chunk(1, "BEKLEME", "BEKLEME", "2:104", "10,0").replace("matched", "pending"),
        chunk(2, "BEKLEME", "ZAMM", "2:104", "15,0"),
        chunk(5, "ZAMM", "ZAMM", "2:105", "28,1"),
        chunk(17, "ZAMM", "ZAMM", "2:107", "77,3"),
        chunk(27, "ARA", "FATIHA", "1:2,1:3,1:4", "124,1"),
        "19:51:02.000 D MainViewModel: [rekat] t=124,1s 2. rekat (Fatiha)",
        chunk(35, "FATIHA", "ZAMM", "76:2", "160,4"),
        chunk(43, "ZAMM", "ZAMM", "76:5", "195,9"),
        "19:56:00.000 D MainViewModel: [rekat] t=455,9s selam (namaz bitti, 4 rekat)",
        "19:57:00.000 D MainViewModel: [rekat] t=500,0s kamet: yeni namaz",
        chunk(60, "BEKLEME", "FATIHA", "1:2", "560,0"),
        "19:58:00.000 D MainViewModel: [rekat] t=560,0s 1. rekat (Fatiha)",
        chunk(66, "FATIHA", "ZAMM", "103:1,103:2", "600,0"),
        "19:59:00.000 D MainViewModel: [rekat] t=650,0s 2. rekat (Fatiha)",
        chunk(70, "ARA", "FATIHA", "1:2", "650,0"),
        chunk(75, "FATIHA", "ZAMM", "103:3", "690,0"),
    )
    val n = NamazReport.parse(iki.asSequence())
    ok("iki namaz", n.size == 2) { "${n.size}" }
    val a = n.getOrNull(0)?.rakats ?: emptyList()
    ok("ortadan baslayan rekat", a.getOrNull(0)?.no == null &&
        a[0].segments.joinToString { "${it.surah}:${it.from}-${it.to}" } == "2:104-107") { "${a.getOrNull(0)?.segments?.size}" }
    ok("sure basi", a.getOrNull(1)?.segments?.lastOrNull()?.let { it.surah == 76 && it.from == 1 && it.to == 5 } == true)
    ok("selam rekat sayisi", n.getOrNull(0)?.rakatCount == 4)
    val b = n.getOrNull(1)?.rakats ?: emptyList()
    ok("kalinan yerden devam", b.getOrNull(1)?.segments?.lastOrNull()?.let { it.surah == 103 && it.from == 3 && it.to == 3 } == true) {
        b.getOrNull(1)?.segments?.joinToString { "${it.surah}:${it.from}-${it.to}" } ?: "-"
    }

    // Sabah 28.10 gibi: Fatiha sonunda 6:141'e dogal gecis (6:141 / 23:78 esit), sonraki parca taze gecis duzeltmesiyle 23:78
    // → raporda En'am bolumu yok
    val sabah = listOf(
        chunk(10, "BEKLEME", "FATIHA", "1:2", "55,0"),
        "07:02:01.560 D MainViewModel: [rekat] t=55,0s 1. rekat (Fatiha)",
        chunk(16, "FATIHA", "FATIHA", "1:7", "85,0"),
        chunk(19, "FATIHA", "ZAMM", "6:141", "96,7").replace("[kilitli takip]", "[kilitli takip; dogal gecis]"),
        chunk(20, "ZAMM", "ZAMM", "23:78", "101,7").replace("[kilitli takip]",
            "[kilitli takip; taze gecis duzeltmesi: 23:78 100,0 (pencere 54,3; gecis parcasi 23:77-78 ayet basina oturuyor)]"),
        chunk(25, "ZAMM", "ZAMM", "23:81", "126,7"),
    )
    val sb = NamazReport.parse(sabah.asSequence()).firstOrNull()?.rakats?.firstOrNull()?.segments
        ?.joinToString(" ") { "${it.surah}:${it.from}-${it.to}" }
    ok("taze gecis duzeltmesi: yanlis bolum yok", sb == "1:1-7 23:78-81") { "$sb" }

    // HTML
    val text = object : ReportHtml.Text {
        override val mealName = "Ali Bulaç"
        override val tefsirName = "El-Muhtasar"
        override fun surahName(surah: Int) = when (surah) { 1 -> "Fâtiha"; 23 -> "Mü'minûn"; 2 -> "Bakara"; else -> "Sure $surah" }
        override fun surahArabic(surah: Int) = "سورة"
        override fun ayahCount(surah: Int) = when (surah) { 1 -> 7; 23 -> 118; 2 -> 286; 76 -> 31; 103 -> 3; else -> 10 }
        override fun arabic(surah: Int, ayah: Int) = "آية <$surah:$ayah>"
        override fun besmele() = "بسم الله"
        override fun meal(surah: Int, ayah: Int) = "Meal $surah:$ayah & \"tırnak\""
        override fun tefsir(surah: Int, ayah: Int) = "Tefsir $surah:$ayah"
    }
    val t0 = java.util.Calendar.getInstance().apply { set(2026, 9, 27, 19, 49, 23) }.timeInMillis
    val html = ReportHtml.render(listOf(ReportHtml.Session(t0, 665, y), ReportHtml.Session(t0 - 86_400_000L, 535, n)),
        text, t0, "QUJD")
    ok("html baslik", html.contains("<title>Namazda Okunan Ayetler</title>") && html.contains("viewport"))
    ok("html font", html.contains("base64,QUJD"))
    ok("html kacis", html.contains("&lt;23:51&gt;") && !html.contains("<23:51>") && html.contains("&amp; &quot;tırnak&quot;"))
    ok("html ayet etiketleri", html.contains("Mü'minûn: 77") && html.contains("Mü'minûn: 51") && !html.contains("Mü'minûn: 50"))
    ok("html fatiha 2. rekatta kapali", Regex("<details class=\"seg\"><summary>Fâtiha").containsMatchIn(html))
    ok("html sessiz rekat", html.contains("3. Rekât <span>sessiz okundu</span>"))
    ok("html besmele", html.contains("<div class=\"besmele\" dir=\"rtl\">بسم الله</div>"))   // 76:1'den
    ok("html tefsir", html.contains("<details class=\"tf\"><summary>Mü'minûn: 77</summary><p>Tefsir 23:77</p>"))
    ok("html tefsir tekrar yok", Regex("<summary>Fâtiha: 1</summary>").findAll(html).count() == 1)
    ok("html namaz adi", html.contains("Yatsı namazı") && html.contains("4 rekât"))
    ok("html bos rapor", ReportHtml.render(emptyList(), text, t0, null).contains("class=\"empty\""))

    // Rapordaki namaz sayisi (Ayarlar → RAPORDAKİ NAMAZ SAYISI, 1-7): en yeni oturumdan geriye, oturum icinde sondan basa;
    // namazsiz oturum atlanir, yeterince namaz yoksa olan kadar (kullanici 30.10: "yeni baslayan kullanici ... hata vermesin")
    val sA = ReportHtml.Session(t0, 665, y)                                // en yeni oturum: 1 namaz
    val sBos = ReportHtml.Session(t0 - 3_600_000L, 40, emptyList())        // namazsiz oturum (deneme)
    val sB = ReportHtml.Session(t0 - 86_400_000L, 535, n)                  // onceki gun: 2 namaz
    fun pick(c: Int) = ReportHtml.lastNamaz(sequenceOf(sA, sBos, sB), c)
    fun count(l: List<ReportHtml.Session>) = l.sumOf { it.namazlar.size }
    ok("son 1 namaz", pick(1).let { it.size == 1 && it[0].startMs == t0 && it[0].namazlar == y })
    ok("son 2 namaz: en yeni + onceki oturumun son namazi",
        pick(2).let { it.size == 2 && it[0].namazlar == y && it[1].startMs == sB.startMs && it[1].namazlar == listOf(n[1]) })
    ok("son 3 namaz: oturum icinde zaman sirasi", pick(3).let { count(it) == 3 && it[1].namazlar == n })
    ok("7 istenip 3 var: hata yok, olan kadar", count(pick(7)) == 3)
    ok("namazsiz oturum atlanir", pick(7).none { it.namazlar.isEmpty() })
    ok("hic kayit yok", ReportHtml.lastNamaz(emptySequence(), 5).isEmpty())
    ok("namazsiz kayitlar", ReportHtml.lastNamaz(sequenceOf(sBos, sBos), 3).isEmpty())
    ok("sinirlar: 0 → 1, 99 → 7", count(ReportHtml.lastNamaz(sequenceOf(sA, sB), 0)) == 1 &&
        count(ReportHtml.lastNamaz(generateSequence { sB }.take(10), 99)) == 7)
    var read = 0
    ReportHtml.lastNamaz(sequenceOf(sA, sBos, sB).onEach { read++ }, 1)
    ok("sadece gereken oturum okunur", read == 1) { "$read" }
    val h1 = ReportHtml.render(pick(1), text, t0, null, requested = 1)
    ok("html baslik: son 1 namaz", h1.contains("Son 1 namaz ·") && !h1.contains("kayıtlarda bu kadar")) {
        Regex("<div class=\"sub\">[^<]*").find(h1)?.value ?: "-"
    }
    val h7 = ReportHtml.render(pick(7), text, t0, null, requested = 7)
    ok("html baslik: eksik namaz notu", h7.contains("Son 3 namaz (ayarda 7; kayıtlarda bu kadar var)")) {
        Regex("<div class=\"sub\">[^<]*").find(h7)?.value ?: "-"
    }
    ok("html bos rapor basligi", ReportHtml.render(emptyList(), text, t0, null, requested = 3).let {
        it.contains("Namaz yok ·") && it.contains("class=\"empty\"")
    })

    // Paylas penceresi (📤) kayit listesi (util/RecordingMerge): genel klasor + cache birlesir, ayni oturumun sesi ve
    // log'u tek kayit, en yeniden eskiye, en fazla 30; kisa ses / bos log / su an yazilan oturum yok
    fun e(name: String, bytes: Long, src: String) = RecordingMerge.Entry(name, bytes, "$src:$name")
    val big = 44L + 32000L * 600          // 10 dk
    val pub = listOf(
        e("tilavet-20261028-070105.wav", big, "pub"), e("tilavet-20261028-070105.txt", 90_000, "pub"),
        e("tilavet-20261027-194923.wav", big, "pub"), e("tilavet-20261027-194923.txt", 80_000, "pub"),
        e("tilavet-20261026-180000.wav", 44L + 16000, "pub"),          // yarim sn: yanlislikla basma
        e("tilavet-20261026-180000.txt", 1_000, "pub"),
        e("tilavet-20261025-190000 (1).wav", big, "pub"),             // MediaStore'un ikinci kopyasi: ad uymuyor
        e("notlar.txt", 500, "pub"),
    )
    val cache = listOf(
        e("tilavet-20261028-070105.wav", big, "cache"),                // genel klasorde de var → genel olan alinir
        e("tilavet-20261029-200000.wav", big, "cache"), e("tilavet-20261029-200000.txt", 50_000, "cache"),  // kopyalanmamis
        e("tilavet-20261020-200000.txt", 30_000, "cache"),             // WAV'i silinmis, log kaldi
        e("tilavet-20261019-200000.txt", 900, "cache"),                // bos oturumun log'u
        e("tilavet-20261030-090000.wav", big, "cache"), e("tilavet-20261030-090000.txt", 4_000, "cache"),  // yaziliyor
    )
    val recs = RecordingMerge.merge(listOf(pub, cache), exclude = setOf("tilavet-20261030-090000.wav",
        "tilavet-20261030-090000.txt"))
    ok("kayitlar: yeniden eskiye", recs.map { it.stamp } == listOf("20261029-200000", "20261028-070105",
        "20261027-194923", "20261020-200000")) { recs.joinToString { it.stamp } }
    ok("kayitlar: genel klasor onde", recs.getOrNull(1)?.wav?.ref == "pub:tilavet-20261028-070105.wav")
    ok("kayitlar: ses + log birlikte", recs.getOrNull(0)?.files?.map { it.ref } ==
        listOf("cache:tilavet-20261029-200000.wav", "cache:tilavet-20261029-200000.txt"))
    ok("kayitlar: sadece log", recs.getOrNull(3)?.let { it.wav == null && it.log != null && it.durationSec == null } == true)
    ok("kayitlar: sure", recs.getOrNull(0)?.durationSec == 600)
    ok("kayitlar: baslangic zamani", recs.getOrNull(0)?.startMs?.let { ReportHtml.dateLabel(it) } == "29 Ekim 2026 Perşembe, 20:00")
    val many = (1..40).flatMap { d -> listOf(e("tilavet-202610%02d-0700%02d.wav".format(d % 28 + 1, d), big, "pub")) }
    ok("kayitlar: en fazla 30", RecordingMerge.merge(listOf(many)).size == 30)
    ok("kayitlar: bos", RecordingMerge.merge(listOf(emptyList<RecordingMerge.Entry<String>>())).isEmpty())
    println("report: $passed/$total")
    return if (passed == total) 0 else 1
}

// Elle bakmak icin: gercek oturum log'larindan rapor HTML'i. Metinler json'dan (names, arnames, counts, besmele ve
// ayahs: "s:a" → ar, meal, tefsir). Kullanim: report-file METIN.json CIKTI.html FONT.ttf|- LOG [LOG ...]
fun reportFile(args: List<String>): Int {
    val j = org.json.JSONObject(java.io.File(args[0]).readText())
    val names = j.getJSONObject("names")
    val arnames = j.getJSONObject("arnames")
    val counts = j.getJSONObject("counts")
    val ayahs = j.getJSONObject("ayahs")
    val text = object : ReportHtml.Text {
        override val mealName = "Ali Bulaç"
        override val tefsirName = "El-Muhtasar fi Tefsîri'l-Kur'ân (Tefsir Araştırmaları Merkezi)"
        override fun surahName(surah: Int) = names.optString("$surah", "Sure $surah")
        override fun surahArabic(surah: Int) = arnames.optString("$surah").ifEmpty { null }
        override fun ayahCount(surah: Int) = counts.optInt("$surah", 0)
        override fun arabic(surah: Int, ayah: Int): String {
            var t = ayahs.optJSONObject("$surah:$ayah")?.optString("ar") ?: ""
            val b = j.getString("besmele")
            if (ayah == 1 && surah != 1 && surah != 9 && t.startsWith(b)) t = t.removePrefix(b).trim()
            return t + " " + ayah.toString().map { '٠' + (it - '0') }.joinToString("")
        }
        override fun besmele() = j.getString("besmele")
        override fun meal(surah: Int, ayah: Int) = ayahs.optJSONObject("$surah:$ayah")?.optString("meal")
        override fun tefsir(surah: Int, ayah: Int) = ayahs.optJSONObject("$surah:$ayah")?.optString("tefsir")
    }
    val font = args[2].takeIf { it != "-" }?.let { java.util.Base64.getEncoder().encodeToString(java.io.File(it).readBytes()) }
    val sessions = args.drop(3).map { p ->
        val f = java.io.File(p)
        val m = Regex("""(\d{8})-(\d{6})""").find(f.name)
        val start = m?.let { java.text.SimpleDateFormat("yyyyMMdd-HHmmss").parse("${it.groupValues[1]}-${it.groupValues[2]}").time }
            ?: f.lastModified()
        ReportHtml.Session(start, null, f.useLines { NamazReport.parse(it) })
    }.sortedByDescending { it.startMs }
    java.io.File(args[1]).writeText(ReportHtml.render(sessions, text, System.currentTimeMillis(), font))
    println("rapor: ${sessions.size} kayit, ${sessions.sumOf { it.namazlar.size }} namaz → ${args[1]}")
    return 0
}
