package com.tilavet.takip.glasses

import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.io.OutputStream
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.net.URLDecoder
import java.util.concurrent.atomic.AtomicInteger

/**
 * G2 gozluk koprusu: telefonun icinde, sadece 127.0.0.1'e bagli kucuk HTTP sunucusu (internete cikmaz, disaridan
 * erisilmez). Even uygulamasinin icindeki G2 eklentisi (assets/g2) buradan okur:
 *   - GET /state?since=N&wait=S&surum=V&kod=K&ekran=E → GlassesState JSON; durum `since`ten farkliysa hemen, degilse
 *     S sn'ye kadar bekler (uzun yoklama: ayet degisince eklenti aninda ogrenir, bosta trafik yok). V: eklenti surumu
 *     (yoksa / eskiyse .ehpk guncellenmeli), K: kodun kaynagi (APK / paket), P (paket): .ehpk surumu, E: eklentinin
 *     gozluge son cizdigi duzen
 *     ("buyuk 48px", "normal", "arapca") — ayarlarda baglanti durumunun yaninda gorunur (tani)
 *   - GET / , /index.html, /<dosya> → eklenti dosyalari ([files]; gelistirici modunda Even uygulamasi sayfayi
 *     dogrudan buradan acar: http://localhost:18765/ — Even WebView'inde 127.0.0.1 ulasmiyor, localhost ulasiyor)
 *   - GET /ping.png → 1x1 PNG: .ehpk eklentisi goruntu istegiyle kopruye ag duzeyinde erisebiliyor mu bakar (fetch
 *     Even Hub'in kendi kaynagindan engellenirse sayfayi dogrudan kopruden acar)
 *   - OPTIONS → CORS on kontrolu (.ehpk paketi baska kaynaktan acilir, buraya cross-origin istek atar)
 * Android'siz (java.net) — JVM'de test edilir (tests/jvm, `glasses`).
 */
class GlassesBridge(
    private val files: (String) -> ByteArray?,
    private val port: Int = DEFAULT_PORT,
    private val log: (String) -> Unit = {},
) {
    companion object {
        const val DEFAULT_PORT = 18765
        /** Eklentinin guncel /state `surum`u: altindaki eski .ehpk kodu (2: kopru adresine sayfa gecisi yapip telefonda
         *  hata sayfasinda kaliyordu, 0: yazi boyutunu bilmiyor) — ayarlarda ".ehpk'yi guncelleyin". */
        const val PLUGIN_VERSION = 3
        /** Uzun yoklamada en fazla bekleme (sn). */
        const val MAX_WAIT_SEC = 25
        /** Bu kadar ms /state istegi gelmezse eklenti bagli sayilmaz (uzun yoklama en fazla 25 sn bekler). */
        const val CLIENT_TIMEOUT_MS = 35_000L
        /**
         * Son `cizildi` bu kadar ms icindeyse eklenti cizim bildiriyor sayilir (rukû / sessiz rekatlarda ekran dakikalarca
         * degismeyebilir; eklenti kapaninca zaten [CLIENT_TIMEOUT_MS] icinde bagli sayilmaz).
         */
        const val DRAWN_FRESH_MS = 600_000L
        private const val MAX_CONNECTIONS = 8
        private const val MAX_HEADER_BYTES = 8192
        private val FILE_NAME = Regex("[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
        private val SCREEN_DESC = Regex("[a-z0-9 ./-]{1,48}")
        private val TRANSFER = Regex("(\\d{1,2})x(\\d{1,6})")
        /** 1x1 seffaf PNG (/ping.png). */
        val PING_PNG: ByteArray = java.util.Base64.getDecoder()
            .decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

        fun contentType(name: String): String = when (name.substringAfterLast('.', "").lowercase()) {
            "html" -> "text/html; charset=utf-8"
            "js", "mjs" -> "text/javascript; charset=utf-8"
            "json" -> "application/json; charset=utf-8"
            "css" -> "text/css; charset=utf-8"
            "txt" -> "text/plain; charset=utf-8"
            "ttf" -> "font/ttf"
            "png" -> "image/png"
            "svg" -> "image/svg+xml"
            else -> "application/octet-stream"
        }
    }

    private val lock = Object()
    private var state = GlassesState()
    private var seq = 0L
    @Volatile private var server: ServerSocket? = null
    private val active = AtomicInteger(0)

    /** Son /state isteginin zamani (System.currentTimeMillis), 0 = hic. */
    @Volatile var lastPollMs = 0L
        private set

    /** Kopru acildigindan beri gelen istek sayisi ve son istegin zamani (tani: eklentiden hic istek geliyor mu). */
    @Volatile var requestCount = 0
        private set
    @Volatile var lastRequestMs = 0L
        private set
    /** Eklentinin gozluge son cizdigi duzen (/state `ekran`), "" = bilinmiyor. */
    @Volatile var clientScreen = ""
        private set
    /** Son /state isteginin eklenti surumu (`surum`): 0 = parametre yok (eski .ehpk kodu), -1 = istek yok. */
    @Volatile var clientVersion = -1
        private set
    /** Eklenti kodunun kaynagi (`kod`: "kopru-N" = APK'dan boot.js ile, "paket" = .ehpk'nin kendi kopyasi). */
    @Volatile var clientCode = ""
        private set
    /** Even'da acik .ehpk paketinin surumu (`paket`, CI: 0.<build>.0), "" = bilinmiyor. */
    @Volatile var clientPackage = ""
        private set
    /**
     * Gozlukte tamamen cizilen son durumun seq'i (/state `cizildi`; eklenti her ekranin son karosu gidince bildirir) ve
     * zamani. AyahStepper ara ayetin suresini gozlukte cizildigi andan sayar (yatsi 27.10: 1 sn'lik ara ayetin 1023 ms'si
     * gozluge aktarimda gecti, okunamadi).
     */
    @Volatile var drawnSeq = -1L
        private set
    @Volatile var lastDrawnMs = 0L
        private set
    // Her yeni (yontem, kaynak) bir kez log'a yazilir — .ehpk'nin hangi kaynaktan calistigi buradan gorulur
    private val seenKinds = java.util.Collections.synchronizedSet(HashSet<String>())

    val running: Boolean get() = server?.isClosed == false
    val boundPort: Int get() = server?.localPort ?: -1

    fun clientConnected(nowMs: Long = System.currentTimeMillis()): Boolean =
        lastPollMs > 0 && nowMs - lastPollMs < CLIENT_TIMEOUT_MS

    /**
     * Eklenti cizim bildiriyor mu (bagli ve son [DRAWN_FRESH_MS] icinde `cizildi` geldi): degilse (eski eklenti kodu, gozluk
     * ekrani baska uygulamada) beklemeye gerek yok.
     */
    fun reportsDrawing(nowMs: Long = System.currentTimeMillis()): Boolean =
        clientConnected(nowMs) && lastDrawnMs > 0 && nowMs - lastDrawnMs < DRAWN_FRESH_MS

    /** Sunucuyu ac (zaten aciksa bir sey yapmaz). false: port kullanimda / acilamadi. */
    @Synchronized
    fun start(): Boolean {
        if (running) return true
        val ss = try {
            ServerSocket().apply {
                reuseAddress = true
                bind(InetSocketAddress(InetAddress.getLoopbackAddress(), port), 16)
            }
        } catch (e: Exception) {
            log("kopru acilamadi (127.0.0.1:$port): ${e.message}")
            return false
        }
        server = ss
        Thread({ acceptLoop(ss) }, "g2-bridge").apply { isDaemon = true }.start()
        log("kopru acildi: http://127.0.0.1:${ss.localPort}/")
        return true
    }

    @Synchronized
    fun stop() {
        val ss = server ?: return
        server = null
        try { ss.close() } catch (_: Exception) {}
        synchronized(lock) { lock.notifyAll() }   // bekleyen uzun yoklamalar hemen donsun
        lastPollMs = 0L
        requestCount = 0
        lastRequestMs = 0L
        clientScreen = ""
        clientVersion = -1
        clientCode = ""
        clientPackage = ""
        drawnSeq = -1L
        lastDrawnMs = 0L
        seenKinds.clear()
        log("kopru kapandi")
    }

    /** Yeni ekran durumu; oncekinden farkliysa seq artar ve bekleyen yoklamalar uyanir. */
    fun update(s: GlassesState) {
        synchronized(lock) {
            if (s == state) return
            state = s
            seq++
            lock.notifyAll()
        }
    }

    fun current(): Pair<Long, GlassesState> = synchronized(lock) { seq to state }

    private fun acceptLoop(ss: ServerSocket) {
        while (!ss.isClosed) {
            val sock = try { ss.accept() } catch (e: Exception) { break }
            if (active.incrementAndGet() > MAX_CONNECTIONS) {
                active.decrementAndGet()
                try { sock.use { respond(it.getOutputStream(), 503, "text/plain; charset=utf-8", "mesgul".toByteArray(), false) } }
                catch (_: Exception) {}
                continue
            }
            Thread({
                try { handle(sock) } catch (_: Exception) {} finally {
                    active.decrementAndGet()
                    try { sock.close() } catch (_: Exception) {}
                }
            }, "g2-bridge-conn").apply { isDaemon = true }.start()
        }
    }

    private fun readHeader(sock: Socket): String? {
        val inp = BufferedInputStream(sock.getInputStream())
        val buf = ByteArrayOutputStream()
        var last4 = 0
        while (buf.size() < MAX_HEADER_BYTES) {
            val b = inp.read()
            if (b < 0) return null
            buf.write(b)
            last4 = (last4 shl 8) or b
            if (last4 == 0x0D0A0D0A || (last4 and 0xFFFF) == 0x0A0A) return buf.toString("ISO-8859-1")
        }
        return null
    }

    private fun handle(sock: Socket) {
        sock.soTimeout = 5000
        val header = readHeader(sock) ?: return
        val requestLine = header.lineSequence().firstOrNull()?.trim() ?: return
        val parts = requestLine.split(' ')
        if (parts.size < 2) return
        val method = parts[0]
        val target = parts[1]
        val out = sock.getOutputStream()
        val path = target.substringBefore('?')
        val query = parseQuery(target.substringAfter('?', ""))
        requestCount++
        lastRequestMs = System.currentTimeMillis()
        val headers = header.lineSequence().drop(1).mapNotNull { line ->
            val i = line.indexOf(':')
            if (i <= 0) null else line.substring(0, i).trim().lowercase() to line.substring(i + 1).trim()
        }.toMap()
        val origin = headers["origin"] ?: "-"
        // .ehpk sayfayi kopruden acinca hangi yoldan geldigi (goruntu yoklamasi / fetch / dugme) bir kez log'a
        if (path == "/" && query.containsKey("kaynak") && seenKinds.add("sayfa $target")) {
            log("eklenti sayfasi kopruden acildi: $target")
        }
        if (seenKinds.add("$method $origin")) {
            log("istek: $method $path kaynak=$origin host=${headers["host"] ?: "-"}" +
                (headers["access-control-request-private-network"]?.let { " ozel-ag=$it" } ?: "") +
                " ua=${headers["user-agent"]?.take(120) ?: "-"}")
        }
        when (method) {
            "OPTIONS" -> respond(out, 204, null, ByteArray(0), false, preflight = true)
            "GET", "HEAD" -> {
                val head = method == "HEAD"
                if (path == "/state") {
                    query["ekran"]?.let { noteScreen(it) }
                    clientVersion = query["surum"]?.toIntOrNull() ?: 0
                    query["kod"]?.let { noteCode(it) }
                    query["paket"]?.let { notePackage(it) }
                    query["aktarim"]?.let { noteTransfer(it) }
                    query["cizildi"]?.toLongOrNull()?.let { s ->
                        lastDrawnMs = System.currentTimeMillis()
                        if (s > drawnSeq) drawnSeq = s
                    }
                    val body = stateBody(query["since"]?.toLongOrNull(), query["wait"]?.toIntOrNull() ?: 0)
                    respond(out, 200, "application/json; charset=utf-8", body, head, noStore = true)
                    return
                }
                if (path == "/ping.png") {
                    respond(out, 200, "image/png", PING_PNG, head, noStore = true)
                    return
                }
                val name = if (path == "/" || path.isEmpty()) "index.html" else path.removePrefix("/")
                val data = if (FILE_NAME.matches(name)) files(name) else null
                if (data == null) respond(out, 404, "text/plain; charset=utf-8", "yok: $name".toByteArray(), head)
                else respond(out, 200, contentType(name), data, head)
            }
            else -> respond(out, 405, "text/plain; charset=utf-8", "desteklenmiyor".toByteArray(), false)
        }
    }

    /** Eklentinin bildirdigi ekran duzeni; duzen (ilk kelime) degisince log'a yazilir, punto degisimi sadece tutulur. */
    private fun noteScreen(desc: String) {
        if (!SCREEN_DESC.matches(desc) || desc == clientScreen) return
        if (desc.substringBefore(' ') != clientScreen.substringBefore(' ')) log("eklenti ekrani: $desc")
        clientScreen = desc
    }

    /** Eklenti kodunun kaynagi degisince log'a (telefonda hangi kodun cizdigi buradan gorulur). */
    private fun noteCode(code: String) {
        if (!SCREEN_DESC.matches(code) || code == clientCode) return
        clientCode = code
        log("eklenti kodu: $code")
    }

    /** Eklentinin gozluge ekran aktarimi ("4x820" = 4 karo 820 ms) — her ekran degisiminde bir satir (tani). */
    private fun noteTransfer(v: String) {
        val m = TRANSFER.matchEntire(v) ?: return
        log("eklenti aktarim: ${m.groupValues[1]} karo ${m.groupValues[2]} ms")
    }

    private fun notePackage(v: String) {
        if (!SCREEN_DESC.matches(v) || v == clientPackage) return
        clientPackage = v
        log("eklenti paketi: $v")
    }

    /** Durum `since`ten farkliysa hemen, degilse en fazla [waitSec] sn bekleyip guncel durumu dondurur. */
    private fun stateBody(since: Long?, waitSec: Int): ByteArray {
        lastPollMs = System.currentTimeMillis()
        val (s, st) = synchronized(lock) {
            val deadline = System.currentTimeMillis() + waitSec.coerceIn(0, MAX_WAIT_SEC) * 1000L
            while (since != null && seq == since && running) {
                val left = deadline - System.currentTimeMillis()
                if (left <= 0) break
                lock.wait(left)
            }
            seq to state
        }
        lastPollMs = System.currentTimeMillis()
        return st.toJson(s).toByteArray(Charsets.UTF_8)
    }

    private fun parseQuery(q: String): Map<String, String> =
        q.split('&').filter { it.isNotEmpty() }.associate { kv ->
            val k = kv.substringBefore('=')
            val v = kv.substringAfter('=', "")
            k to try { URLDecoder.decode(v, "UTF-8") } catch (_: Exception) { v }
        }

    private fun respond(
        out: OutputStream, code: Int, type: String?, body: ByteArray, head: Boolean,
        noStore: Boolean = false, preflight: Boolean = false,
    ) {
        val reason = when (code) {
            200 -> "OK"; 204 -> "No Content"; 404 -> "Not Found"; 405 -> "Method Not Allowed"
            else -> "Service Unavailable"
        }
        val sb = StringBuilder()
        sb.append("HTTP/1.1 ").append(code).append(' ').append(reason).append("\r\n")
        if (type != null) sb.append("Content-Type: ").append(type).append("\r\n")
        sb.append("Content-Length: ").append(if (code == 204) 0 else body.size).append("\r\n")
        sb.append("Cache-Control: ").append(if (noStore) "no-store" else "no-cache").append("\r\n")
        // .ehpk eklentisi baska kaynaktan (Even uygulamasinin paket kaynagi) buraya istek atar
        sb.append("Access-Control-Allow-Origin: *\r\n")
        sb.append("Access-Control-Allow-Private-Network: true\r\n")
        if (preflight) {
            sb.append("Access-Control-Allow-Methods: GET, HEAD, OPTIONS\r\n")
            sb.append("Access-Control-Allow-Headers: *\r\n")
            sb.append("Access-Control-Max-Age: 600\r\n")
        }
        sb.append("Connection: close\r\n\r\n")
        try {
            out.write(sb.toString().toByteArray(Charsets.ISO_8859_1))
            if (!head && code != 204) out.write(body)
            out.flush()
        } catch (_: SocketException) {
        }
    }
}
