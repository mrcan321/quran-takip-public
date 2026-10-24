import com.tilavet.takip.glasses.GlassesBridge
import com.tilavet.takip.glasses.GlassesState
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.Socket
import java.net.URL

/**
 * G2 gozluk koprusu (glasses/GlassesBridge + GlassesState) — uygulamadaki kod, gercek soketle:
 *   glasses                         otomatik kontroller (JSON, uzun yoklama, dosyalar, CORS, kapatma); hata sayisi = cikis kodu
 *   glasses-serve <g2dir> <fontdir> [port]
 *                                   eklentiyi simulatorde denemek icin: dosyalari sunar, stdin'den gelen her JSON satirini
 *                                   (GlassesState alanlari) yayinlar; stdin kapaninca biter (tests/g2/sim_check.py)
 */
private class Check {
    var total = 0
    val failures = ArrayList<String>()
    fun ok(name: String, cond: Boolean, detail: () -> String = { "" }) {
        total++
        if (!cond) failures.add("$name ${detail()}".trim())
    }
}

private data class Resp(val code: Int, val headers: Map<String, String>, val body: ByteArray, val ms: Long)

private fun http(port: Int, path: String, method: String = "GET"): Resp {
    val t0 = System.nanoTime()
    val c = URL("http://127.0.0.1:$port$path").openConnection() as HttpURLConnection
    c.requestMethod = method
    c.connectTimeout = 3000
    c.readTimeout = 40_000
    val code = c.responseCode
    val body = try { (if (code >= 400) c.errorStream else c.inputStream)?.use { it.readBytes() } ?: ByteArray(0) }
        catch (_: Exception) { ByteArray(0) }
    val headers = c.headerFields.filterKeys { it != null }.mapKeys { it.key.lowercase() }.mapValues { it.value.joinToString(",") }
    c.disconnect()
    return Resp(code, headers, body, (System.nanoTime() - t0) / 1_000_000)
}

/** Ham istek (HttpURLConnection OPTIONS / bilinmeyen yontemleri kisitliyor). */
private fun raw(port: Int, request: String): String =
    Socket("127.0.0.1", port).use { s ->
        s.soTimeout = 5000
        s.getOutputStream().write(request.toByteArray(Charsets.ISO_8859_1))
        s.getOutputStream().flush()
        s.getInputStream().readBytes().toString(Charsets.UTF_8)
    }

fun glassesTests(): Int {
    val ck = Check()

    // 1. JSON: kacis + alanlar (org.json ile geri okunur)
    val tricky = GlassesState(
        listening = true, surah = 2, ayah = 255, surahName = "Bakara", surahAyahCount = 286, tentative = true,
        progress = 0.4567, meal = "Allah \"O\" ki;\nyeni satır\t\\ ters bölü \u0001   son", arabic = "ٱللَّهُ لَآ إِلَٰهَ ٢٥٥",
        showArabic = true, bigText = false, rakat = "1. REKÂT · KIYAM", noteTitle = "TEKBİR", noteReading = "Allâhu ekber", noteTurkish = "Allah en büyüktür",
    )
    val j = JSONObject(tricky.toJson(7))
    ck.ok("json seq", j.getLong("seq") == 7L)
    ck.ok("json meal", j.getString("meal") == tricky.meal) { j.getString("meal") }
    ck.ok("json arabic", j.getString("arabic") == tricky.arabic)
    ck.ok("json progress", Math.abs(j.getDouble("progress") - 0.457) < 1e-9) { j.get("progress").toString() }
    ck.ok("json alanlar", j.getBoolean("tentative") && j.getBoolean("showArabic") && j.getInt("surah") == 2 &&
        j.getInt("ayah") == 255 && j.getString("rakat") == tricky.rakat && j.getString("noteTitle") == "TEKBİR")
    ck.ok("json NaN", JSONObject(GlassesState(progress = Double.NaN).toJson(0)).getDouble("progress") == 0.0)
    ck.ok("json buyuk yazi", !j.getBoolean("bigText") && JSONObject(GlassesState().toJson(0)).getBoolean("bigText"))
    ck.ok("json yazi boyutu", JSONObject(GlassesState().toJson(0)).getInt("textPx") == GlassesState.DEFAULT_TEXT_PX &&
        JSONObject(GlassesState(textPx = 64).toJson(0)).getInt("textPx") == 64)
    ck.ok("json sure / ayet satiri", JSONObject(GlassesState().toJson(0)).getBoolean("bigHeader") &&
        !JSONObject(GlassesState(bigHeader = false).toJson(0)).getBoolean("bigHeader"))
    ck.ok("json demo", JSONObject(GlassesState().toJson(0)).getInt("demo") == 0 &&
        JSONObject(GlassesState(demo = 4).toJson(0)).getInt("demo") == 4)
    run {
        val d = JSONObject(GlassesState().toJson(0))
        val e = JSONObject(GlassesState(mealLabel = "end", mealLabelGrow = true).toJson(0))
        ck.ok("json mealLabel", d.getString("mealLabel") == "off" && !d.getBoolean("mealLabelGrow") &&
            e.getString("mealLabel") == "end" && e.getBoolean("mealLabelGrow") &&
            GlassesState.MEAL_LABELS.keys.toList() == listOf("off", "start", "end"))
    }
    ck.ok("json rekat bilgisi gizli", !JSONObject(GlassesState().toJson(0)).getBoolean("hideRakat") &&
        JSONObject(GlassesState(hideRakat = true).toJson(0)).getBoolean("hideRakat"))
    ck.ok("json yazi tipi / kalinlik", JSONObject(GlassesState().toJson(0)).let {
        it.getString("bigFont") == "manrope" && it.getInt("bigWeight") == 700
    } && JSONObject(GlassesState(bigFont = "lexend", bigWeight = 300).toJson(0)).let {
        it.getString("bigFont") == "lexend" && it.getInt("bigWeight") == 300
    })
    // ayarlardaki secenekler eklentiyle ayni (layout.js BIG_FONTS / BIG_WEIGHTS)
    val layoutJs = generateSequence(File("").absoluteFile) { it.parentFile }
        .map { File(it, "tilavet-android/app/src/main/assets/g2/layout.js") }.firstOrNull { it.isFile }?.readText()
    ck.ok("yazi tipleri = layout.js", layoutJs != null && GlassesState.FONTS.keys.all { Regex("\\n  $it: \\{").containsMatchIn(layoutJs) } &&
        Regex("BIG_WEIGHTS = \\[([0-9, ]+)]").find(layoutJs)?.groupValues?.get(1)?.split(", ")?.map { it.toInt() } ==
        GlassesState.WEIGHTS.keys.toList()) { "layout.js BIG_FONTS / BIG_WEIGHTS" }
    ck.ok("json sabit yazi boyutu", !JSONObject(GlassesState().toJson(0)).getBoolean("fixedSize") &&
        JSONObject(GlassesState(fixedSize = true).toJson(0)).getBoolean("fixedSize"))
    ck.ok("json bos ekran (ses kesildi)", !JSONObject(GlassesState().toJson(0)).getBoolean("blank") &&
        JSONObject(GlassesState(blank = true).toJson(0)).getBoolean("blank"))
    ck.ok("json tek ekrana sigdir", !JSONObject(GlassesState().toJson(0)).getBoolean("onePage") &&
        JSONObject(GlassesState(onePage = true).toJson(0)).getBoolean("onePage"))
    ck.ok("json tek ekran alt siniri", JSONObject(GlassesState().toJson(0)).getInt("onePageMinPx") == GlassesState.DEFAULT_ONE_PAGE_PX &&
        JSONObject(GlassesState(onePageMinPx = 14).toJson(0)).getInt("onePageMinPx") == 14)
    ck.ok("json bos ekranda ust bilgi (varsayilan yok)", !JSONObject(GlassesState().toJson(0)).getBoolean("blankHeader") &&
        JSONObject(GlassesState(blankHeader = true).toJson(0)).getBoolean("blankHeader"))
    ck.ok("json durum yazisi gizli", !JSONObject(GlassesState().toJson(0)).getBoolean("hideStatus") &&
        JSONObject(GlassesState(hideStatus = true).toJson(0)).getBoolean("hideStatus"))

    // 2. Kopru: gercek soket, rastgele port
    val files = mapOf(
        "index.html" to "<html>g2</html>".toByteArray(),
        "app.js" to "console.log(1)".toByteArray(),
        "kfgqpc.ttf" to ByteArray(1000) { it.toByte() },
    )
    val logs = ArrayList<String>()
    val b = GlassesBridge(files = { files[it] }, port = 0, log = { synchronized(logs) { logs.add(it) } })
    ck.ok("start", b.start())
    ck.ok("start tekrar", b.start())
    val port = b.boundPort
    ck.ok("port", port > 0) { "$port" }
    ck.ok("istemci yok", !b.clientConnected())

    val r0 = http(port, "/state")
    val s0 = JSONObject(r0.body.toString(Charsets.UTF_8))
    ck.ok("state 200", r0.code == 200) { "${r0.code}" }
    ck.ok("state tipi", r0.headers["content-type"]?.startsWith("application/json") == true) { "${r0.headers["content-type"]}" }
    ck.ok("state cors", r0.headers["access-control-allow-origin"] == "*" &&
        r0.headers["access-control-allow-private-network"] == "true") { r0.headers.toString() }
    ck.ok("state no-store", r0.headers["cache-control"] == "no-store")
    ck.ok("state bos", s0.getLong("seq") == 0L && !s0.getBoolean("listening"))
    ck.ok("istemci bagli", b.clientConnected())

    // uzun yoklama: durum degisince hemen doner
    val st1 = GlassesState(listening = true, surah = 108, ayah = 2, surahName = "Kevser", meal = "Şu halde Rabbin için namaz kıl ve kurban kes.")
    var waited: Resp? = null
    val th = Thread { waited = http(port, "/state?since=0&wait=10") }
    th.start()
    Thread.sleep(400)
    b.update(st1)
    th.join(5000)
    val w = waited
    ck.ok("uzun yoklama doner", w != null && w.code == 200)
    if (w != null) {
        val jw = JSONObject(w.body.toString(Charsets.UTF_8))
        ck.ok("uzun yoklama yeni seq", jw.getLong("seq") == 1L && jw.getInt("surah") == 108) { jw.toString() }
        ck.ok("uzun yoklama hizli", w.ms in 300..2500) { "${w.ms} ms" }
        ck.ok("uzun yoklama utf8", jw.getString("meal") == st1.meal)
    }
    // ayni durum: seq artmaz
    b.update(st1.copy())
    ck.ok("ayni durum seq", b.current().first == 1L)
    // degismeyen durumda bekleme suresi kadar bekler
    val r2 = http(port, "/state?since=1&wait=1")
    ck.ok("bekleme suresi", r2.ms in 900..3000) { "${r2.ms} ms" }
    ck.ok("bekleme sonra ayni", JSONObject(r2.body.toString(Charsets.UTF_8)).getLong("seq") == 1L)
    // since farkliysa (uygulama yeniden basladi) hemen
    val r3 = http(port, "/state?since=57&wait=10")
    ck.ok("eski since hemen", r3.ms < 1500) { "${r3.ms} ms" }
    // wait ust siniri: 100 → 25 sn'ye kirpilir (burada sadece hatasiz donmesi; sure ust sinir icin degil)

    // 3. Dosyalar
    val ri = http(port, "/")
    ck.ok("index", ri.code == 200 && ri.body.contentEquals(files["index.html"]!!) &&
        ri.headers["content-type"]?.startsWith("text/html") == true) { "${ri.code} ${ri.headers["content-type"]}" }
    val rj = http(port, "/app.js")
    ck.ok("js tipi", rj.code == 200 && rj.headers["content-type"]?.startsWith("text/javascript") == true)
    val rf = http(port, "/kfgqpc.ttf")
    ck.ok("font", rf.code == 200 && rf.body.size == 1000 && rf.headers["content-type"] == "font/ttf")
    ck.ok("404", http(port, "/yok.js").code == 404)
    ck.ok("yol disi", http(port, "/../asr/quran.bin").code == 404)
    ck.ok("alt dizin", http(port, "/a/b.js").code == 404)
    val rh = http(port, "/app.js", "HEAD")
    ck.ok("HEAD", rh.code == 200 && rh.body.isEmpty())
    val rp = http(port, "/ping.png?t=1")
    ck.ok("ping.png", rp.code == 200 && rp.headers["content-type"] == "image/png" &&
        rp.body.contentEquals(GlassesBridge.PING_PNG) && rp.body.size > 60) { "${rp.code} ${rp.headers["content-type"]}" }
    ck.ok("istek sayaci", b.requestCount >= 10 && b.lastRequestMs > 0) { "${b.requestCount}" }
    // eklentinin bildirdigi gozluk duzeni (ayarlarda baglanti satiri); gecersiz deger yok sayilir, duzen degisimi log'da
    ck.ok("ekran yok", b.clientScreen == "")
    http(port, "/state?since=-1&wait=0&ekran=buyuk%2048px")
    ck.ok("ekran bildirimi", b.clientScreen == "buyuk 48px") { b.clientScreen }
    http(port, "/state?since=-1&wait=0&ekran=%3Cscript%3E")
    ck.ok("ekran gecersiz", b.clientScreen == "buyuk 48px") { b.clientScreen }
    http(port, "/state?since=-1&wait=0&ekran=buyuk%2064px%20sabit")
    ck.ok("ekran sabit punto", b.clientScreen == "buyuk 64px sabit") { b.clientScreen }
    http(port, "/state?since=-1&wait=0&ekran=buyuk%2064px")
    ck.ok("ekran punto", b.clientScreen == "buyuk 64px") { b.clientScreen }
    ck.ok("ekran logu", synchronized(logs) { logs.count { it.startsWith("eklenti ekrani:") } == 1 }) {
        synchronized(logs) { logs.toString() }
    }
    // eklenti surumu: parametresiz istek = eski .ehpk kodu (0), yeni kod surum yollar
    ck.ok("surum yok = eski eklenti", b.clientVersion == 0) { "${b.clientVersion}" }
    http(port, "/state?since=-1&wait=0&surum=3&kod=kopru-3&paket=0.49.0&ekran=buyuk%2048px")
    ck.ok("paket surumu + logu", b.clientPackage == "0.49.0" &&
        synchronized(logs) { logs.count { it == "eklenti paketi: 0.49.0" } == 1 }) { b.clientPackage }
    ck.ok("surum", b.clientVersion == 3) { "${b.clientVersion}" }
    ck.ok("kod kaynagi + logu", b.clientCode == "kopru-3" &&
        synchronized(logs) { logs.count { it == "eklenti kodu: kopru-3" } == 1 }) { "${b.clientCode} ${synchronized(logs) { logs }}" }
    ck.ok("host logu", synchronized(logs) { logs.any { it.contains(" host=127.0.0.1:") } }) { synchronized(logs) { logs.toString() } }
    // gozluge aktarim suresi (tani): gecerli deger log'a, bozuk deger yok sayilir
    http(port, "/state?since=-1&wait=0&surum=3&aktarim=4x820")
    http(port, "/state?since=-1&wait=0&surum=3&aktarim=4x820;rm")
    http(port, "/state?since=-1&wait=0&surum=3&aktarim=x")
    ck.ok("aktarim logu", synchronized(logs) {
        logs.count { it == "eklenti aktarim: 4 karo 820 ms" } == 1 && logs.count { it.startsWith("eklenti aktarim:") } == 1
    }) { synchronized(logs) { logs.toString() } }
    // .ehpk sayfayi kopruden acinca hangi yoldan geldigi log'da (bir kez)
    val pg = http(port, "/?kaynak=ehpk&yol=goruntu")
    http(port, "/?kaynak=ehpk&yol=goruntu")
    ck.ok("gecis sayfasi + logu", pg.code == 200 && synchronized(logs) {
        logs.count { it == "eklenti sayfasi kopruden acildi: /?kaynak=ehpk&yol=goruntu" } == 1
    }) { synchronized(logs) { logs.toString() } }

    // 4. CORS on kontrolu + desteklenmeyen yontem (ham soket)
    val pre = raw(port, "OPTIONS /state HTTP/1.1\r\nHost: 127.0.0.1\r\nOrigin: https://x.example\r\n" +
        "Access-Control-Request-Method: GET\r\nAccess-Control-Request-Private-Network: true\r\n\r\n")
    ck.ok("OPTIONS 204", pre.startsWith("HTTP/1.1 204")) { pre.lineSequence().first() }
    ck.ok("OPTIONS basliklar", pre.contains("Access-Control-Allow-Methods: GET") &&
        pre.contains("Access-Control-Allow-Private-Network: true") && pre.contains("Access-Control-Allow-Origin: *"))
    ck.ok("POST 405", raw(port, "POST /state HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\n\r\n").startsWith("HTTP/1.1 405"))
    ck.ok("bozuk istek", runCatching { raw(port, "\r\n\r\n") }.isSuccess)
    // .ehpk'nin kaynagi log'da gorunmeli (tani: eklenti hangi kaynaktan istek atiyor)
    ck.ok("kaynak logu", synchronized(logs) { logs.any { it.contains("istek: OPTIONS /state kaynak=https://x.example host=127.0.0.1 ozel-ag=true") } }) {
        synchronized(logs) { logs.toString() }
    }

    // 5. Ayni portta ikinci kopru acilamaz
    val b2 = GlassesBridge(files = { null }, port = port)
    ck.ok("port kullanimda", !b2.start())

    // 6. Kapatma bekleyen yoklamayi hemen bitirir
    var late: Resp? = null
    val th2 = Thread { late = runCatching { http(port, "/state?since=1&wait=20") }.getOrNull() }
    th2.start()
    Thread.sleep(400)
    val t0 = System.nanoTime()
    b.stop()
    th2.join(5000)
    val stopMs = (System.nanoTime() - t0) / 1_000_000
    ck.ok("kapatinca yoklama biter", !th2.isAlive && stopMs < 2000) { "$stopMs ms" }
    ck.ok("kapandi", !b.running && runCatching { http(port, "/state") }.isFailure && b.clientScreen == "" &&
        b.clientVersion == -1 && b.clientCode == "" && b.clientPackage == "")
    ck.ok("tekrar acilir", b.start() && b.running)
    b.stop()

    println("glasses: ${ck.total - ck.failures.size}/${ck.total}")
    ck.failures.forEach { println("  HATA $it") }
    return if (ck.failures.isEmpty()) 0 else 1
}

fun glassesServe(dir: File, fontDir: File, port: Int): Int {
    // uygulamadaki gibi: eklenti fontlari res/font'tan (MainViewModel.glassesFile)
    val fonts = mapOf("kfgqpc.ttf" to "kfgqpc_hafs.ttf", "manrope.ttf" to "manrope_700.ttf")
    // buyuk yazi fontlari (Ayarlar → G2 YAZI TİPİ): assets/g2fonts/<id>.ttf, kopruden /g2font-<id>.ttf
    val bigFonts = File(dir.parentFile, "g2fonts")
    val b = GlassesBridge(
        files = { name ->
            fonts[name]?.let { File(fontDir, it).readBytes() }
                ?: (if (name.startsWith("g2font-")) File(bigFonts, name.removePrefix("g2font-")) else File(dir, name))
                    .takeIf { it.isFile }?.readBytes()
        },
        port = port,
        log = { println("[kopru] $it") },
    )
    if (!b.start()) return 1
    println("hazir ${b.boundPort}")
    System.out.flush()
    // Her stdin satiri bir GlassesState (JSON, alan adlari /state ile ayni); stdin kapaninca kopru kapanir
    val reader = System.`in`.bufferedReader(Charsets.UTF_8)
    while (true) {
        val line = reader.readLine() ?: break
        if (line.isBlank()) continue
        val s = JSONObject(line)
        b.update(GlassesState(
            listening = s.optBoolean("listening"), sim = s.optBoolean("sim"), status = s.optString("status"),
            surah = s.optInt("surah"), ayah = s.optInt("ayah"), surahName = s.optString("surahName"),
            surahAyahCount = s.optInt("surahAyahCount"), tentative = s.optBoolean("tentative"),
            progress = s.optDouble("progress", 0.0), meal = s.optString("meal"), arabic = s.optString("arabic"),
            showArabic = s.optBoolean("showArabic"), bigText = s.optBoolean("bigText", true),
            textPx = s.optInt("textPx", GlassesState.DEFAULT_TEXT_PX), bigHeader = s.optBoolean("bigHeader", true),
            hideRakat = s.optBoolean("hideRakat"),
            fixedSize = s.optBoolean("fixedSize"), onePage = s.optBoolean("onePage"),
            bigFont = s.optString("bigFont", GlassesState.DEFAULT_FONT),
            bigWeight = s.optInt("bigWeight", GlassesState.DEFAULT_WEIGHT),
            onePageMinPx = s.optInt("onePageMinPx", GlassesState.DEFAULT_ONE_PAGE_PX), blank = s.optBoolean("blank"),
            blankHeader = s.optBoolean("blankHeader"), hideStatus = s.optBoolean("hideStatus"),
            rakat = s.optString("rakat"),
            noteTitle = s.optString("noteTitle"), noteReading = s.optString("noteReading"), noteTurkish = s.optString("noteTurkish"),
            demo = s.optInt("demo", 0),
            mealLabel = s.optString("mealLabel", GlassesState.MEAL_LABEL_OFF),
            mealLabelGrow = s.optBoolean("mealLabelGrow", false),
        ))
        println("durum ${b.current().first}")
        System.out.flush()
    }
    b.stop()
    return 0
}
