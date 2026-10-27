package com.tilavet.takip.report

import java.util.Calendar
import java.util.Locale

/**
 * Namaz raporu HTML'i (mobil telefonda okunur; tek dosya — paylasilinca da acilir): her namaz icin rekat rekat okunan
 * ayetler (Arapca KFGQPC yazisi + Turkce meal), sonda "isteyenler icin" acilir tefsir. Zumrut temasinin renkleri; telefon
 * koyu temadaysa koyu. Android'e bagli degil (tests/jvm `report`).
 */
object ReportHtml {

    /** Rapordaki metinler (uygulamada MushafData + secili meal + tefsir.bin; testte sahte). */
    interface Text {
        val mealName: String
        val tefsirName: String?
        fun surahName(surah: Int): String
        fun surahArabic(surah: Int): String?
        fun ayahCount(surah: Int): Int
        /** Ayet metni (KFGQPC yazimi, 1. ayette besmelesiz) + ayet sonu rakami. */
        fun arabic(surah: Int, ayah: Int): String
        fun besmele(): String
        fun meal(surah: Int, ayah: Int): String?
        fun tefsir(surah: Int, ayah: Int): String?
    }

    /** Bir kayit (oturum): baslangic zamani (epoch ms), sure (sn) ve icindeki namazlar. */
    class Session(val startMs: Long, val durationSec: Int?, val namazlar: List<NamazReport.Namaz>)

    private val MONTHS = listOf("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül",
        "Ekim", "Kasım", "Aralık")
    private val DAYS = listOf("Pazar", "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi")

    fun dateLabel(ms: Long): String {
        val c = Calendar.getInstance().apply { timeInMillis = ms }
        return "%d %s %d %s, %02d:%02d".format(Locale.ROOT, c[Calendar.DAY_OF_MONTH], MONTHS[c[Calendar.MONTH]],
            c[Calendar.YEAR], DAYS[c[Calendar.DAY_OF_WEEK] - 1], c[Calendar.HOUR_OF_DAY], c[Calendar.MINUTE])
    }

    /**
     * Namazin adi (tahmin): rekat sayisi (selamda RakatTracker) + saat + gun. Sesli okunan namazlar: sabah, cuma, aksam,
     * yatsi (teravih de 2 rekat).
     */
    fun namazName(startMs: Long, rakatCount: Int?): String {
        val c = Calendar.getInstance().apply { timeInMillis = startMs }
        val h = c[Calendar.HOUR_OF_DAY]
        val friday = c[Calendar.DAY_OF_WEEK] == Calendar.FRIDAY
        return when {
            rakatCount == 3 -> "Akşam namazı"
            rakatCount == 4 && h >= 16 -> "Yatsı namazı"
            rakatCount == 2 && h < 10 -> "Sabah namazı"
            rakatCount == 2 && friday && h in 11..15 -> "Cuma namazı"
            rakatCount == null && h < 10 -> "Sabah namazı"
            rakatCount == null && friday && h in 11..15 -> "Cuma namazı"
            else -> "Namaz"
        }
    }

    fun render(sessions: List<Session>, text: Text, createdMs: Long, arabicFontBase64: String?): String {
        val sb = StringBuilder(64 * 1024 + (arabicFontBase64?.length ?: 0))
        sb.append("<!doctype html><html lang=\"tr\"><head><meta charset=\"utf-8\">")
        sb.append("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">")
        sb.append("<title>Namazda Okunan Ayetler</title><style>")
        if (arabicFontBase64 != null) {
            sb.append("@font-face{font-family:'KFGQPC';src:url(data:font/ttf;base64,").append(arabicFontBase64)
                .append(") format('truetype');}")
        }
        sb.append(CSS).append("</style></head><body>")
        sb.append("<header class=\"top\"><div class=\"wrap\"><div class=\"kicker\">TİLAVET TAKİP</div>")
        sb.append("<h1>Namazda Okunan Ayetler</h1>")
        sb.append("<div class=\"sub\">Son ${sessions.size} kayıt · ${esc(dateLabel(createdMs))}</div></div></header>")
        sb.append("<main class=\"wrap\">")
        val items = sessions.flatMap { s -> s.namazlar.map { s to it } }
        if (items.isEmpty()) {
            sb.append("<p class=\"empty\">Son kayıtlarda takip edilen bir okuma yok. Namazda mikrofon düğmesine basıp ")
            sb.append("dinleyince okunan ayetler burada listelenir.</p>")
        } else if (items.size > 1) {
            sb.append("<nav class=\"toc\">")
            items.forEachIndexed { i, (s, n) ->
                sb.append("<a href=\"#n$i\"><b>${esc(namazName(s.startMs, n.rakatCount))}</b>")
                    .append("<span>${esc(dateLabel(s.startMs))} · ${esc(summary(n, text))}</span></a>")
            }
            sb.append("</nav>")
        }
        items.forEachIndexed { i, (s, n) -> namaz(sb, i, s, n, text) }
        if (items.isNotEmpty() && text.tefsirName != null) tefsir(sb, items, text)
        sb.append("<footer>Arapça metin: Tanzil (Osmanlı hattı), yazı tipi KFGQPC Hafs · Meal: ${esc(text.mealName)}")
        text.tefsirName?.let { sb.append(" · Tefsir: ${esc(it)} (QuranEnc)") }
        sb.append("<br>Ayetler namazda telefonun duyduğu okumadan otomatik çıkarıldı; duyulamayan kısımlar eksik olabilir.")
        sb.append("</footer></main></body></html>")
        return sb.toString()
    }

    /** "Fâtiha, Mü'minûn 51-77" — namazda okunan sureler. */
    fun summary(n: NamazReport.Namaz, text: Text): String {
        val parts = LinkedHashMap<Int, IntArray>()
        for (r in n.rakats) for (g in r.segments) {
            val p = parts.getOrPut(g.surah) { intArrayOf(g.from, g.to) }
            p[0] = minOf(p[0], g.from); p[1] = maxOf(p[1], g.to)
        }
        return parts.entries.joinToString(", ") { (s, p) ->
            if (s == 1 || (p[0] == 1 && p[1] == text.ayahCount(s))) text.surahName(s)
            else "${text.surahName(s)} ${range(p[0], p[1])}"
        }
    }

    private fun range(a: Int, b: Int) = if (a == b) "$a" else "$a-$b"

    private fun namaz(sb: StringBuilder, i: Int, s: Session, n: NamazReport.Namaz, text: Text) {
        sb.append("<section class=\"namaz\" id=\"n$i\"><h2>${esc(namazName(s.startMs, n.rakatCount))}</h2>")
        sb.append("<div class=\"meta\">${esc(dateLabel(s.startMs))}")
        n.rakatCount?.let { sb.append(" · $it rekât") }
        s.durationSec?.let { sb.append(" · kayıt ${(it + 30) / 60} dk") }
        sb.append("</div>")
        var fatihaShown = false
        for (r in n.rakats) {
            if (r.silent && r.segments.isEmpty()) {
                sb.append("<div class=\"rakat silent\">${r.no}. Rekât <span>sessiz okundu</span></div>")
                continue
            }
            if (r.segments.isEmpty()) continue
            sb.append("<div class=\"rakat\">")
            sb.append(if (r.no != null) "${r.no}. Rekât" else "Rekât <span>(kayıt namazın ortasında başladı)</span>")
            sb.append("</div>")
            for (g in r.segments) {
                val title = "${text.surahName(g.surah)} " +
                    (if (g.surah == 1 || (g.from == 1 && g.to == text.ayahCount(g.surah))) "" else range(g.from, g.to))
                if (g.surah == 1 && fatihaShown) {
                    // Fatiha her rekatta ayni: ilkinde acik, sonrakilerde kapali
                    sb.append("<details class=\"seg\"><summary>${esc(title.trim())} <i>(dokunun)</i></summary>")
                    ayahs(sb, g, text)
                    sb.append("</details>")
                    continue
                }
                if (g.surah == 1) fatihaShown = true
                sb.append("<div class=\"seg\"><div class=\"segh\"><span>${esc(title.trim())}</span>")
                text.surahArabic(g.surah)?.let { sb.append("<span class=\"arname\">${esc(it)}</span>") }
                sb.append("</div>")
                ayahs(sb, g, text)
                sb.append("</div>")
            }
        }
        sb.append("</section>")
    }

    private fun ayahs(sb: StringBuilder, g: NamazReport.Segment, text: Text) {
        if (g.from == 1 && g.surah != 1 && g.surah != 9) {
            sb.append("<div class=\"besmele\" dir=\"rtl\">${esc(text.besmele())}</div>")
        }
        for (a in g.from..g.to) {
            sb.append("<article class=\"ayah\"><div class=\"tag\">${esc(text.surahName(g.surah))}: $a</div>")
            sb.append("<div class=\"ar\" dir=\"rtl\" lang=\"ar\">${esc(text.arabic(g.surah, a))}</div>")
            text.meal(g.surah, a)?.let { sb.append("<p class=\"meal\">${esc(it)}</p>") }
            sb.append("</article>")
        }
    }

    private fun tefsir(sb: StringBuilder, items: List<Pair<Session, NamazReport.Namaz>>, text: Text) {
        sb.append("<section class=\"tefsir\"><h2>Tefsir</h2><p class=\"note\">İsteyenler için: ayete dokununca kısa ")
        sb.append("açıklaması açılır. Kaynak: ${esc(text.tefsirName ?: "")}.</p>")
        val seen = HashSet<Long>()
        items.forEachIndexed { i, (s, n) ->
            val list = n.rakats.flatMap { r -> r.segments.flatMap { g -> (g.from..g.to).map { g.surah to it } } }
                .filter { (su, a) -> seen.add((su.toLong() shl 16) or a.toLong()) }
            if (list.isEmpty()) return@forEachIndexed
            sb.append("<h3>${esc(namazName(s.startMs, n.rakatCount))} · ${esc(dateLabel(s.startMs))}</h3>")
            for ((su, a) in list) {
                val t = text.tefsir(su, a) ?: continue
                sb.append("<details class=\"tf\"><summary>${esc(text.surahName(su))}: $a</summary><p>${esc(t)}</p></details>")
            }
        }
        sb.append("</section>")
    }

    fun esc(s: String): String {
        val sb = StringBuilder(s.length + 16)
        for (c in s) when (c) {
            '<' -> sb.append("&lt;")
            '>' -> sb.append("&gt;")
            '&' -> sb.append("&amp;")
            '"' -> sb.append("&quot;")
            else -> sb.append(c)
        }
        return sb.toString()
    }

    private const val CSS = """
:root{--bg:#F8F2E6;--card:#fff;--ink:#1f2a24;--muted:#6f726b;--em:#0E2A1F;--em2:#1D5A3D;--gold:#9C7838;--mint:#E0ECE2;--line:#e8dfcc;--hud:#f3f8f2}
@media (prefers-color-scheme: dark){:root{--bg:#0f1914;--card:#16231c;--ink:#ece6d9;--muted:#9ea59f;--em:#d8eadf;--em2:#93c9a9;--gold:#d6b574;--mint:#1f3529;--line:#2a3a31;--hud:#1a2a21}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans",sans-serif;-webkit-text-size-adjust:100%}
.wrap{max-width:720px;margin:0 auto;padding:0 16px}
header.top{background:linear-gradient(160deg,#0E2A1F,#1A4433 70%,#1D5A3D);color:#F1E8D7;padding:22px 0 20px;border-radius:0 0 24px 24px;box-shadow:0 6px 18px rgba(14,42,31,.25)}
.kicker{font-size:11px;letter-spacing:.18em;color:#C6A15B;font-weight:700}
h1{font-family:Georgia,"Playfair Display",serif;font-weight:600;font-size:26px;margin:4px 0 2px;line-height:1.25}
.sub{font-size:13px;color:#cfe0d4}
main{padding-bottom:28px}
.toc{display:flex;flex-direction:column;gap:8px;margin:18px 0 6px}
.toc a{display:block;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:10px 14px;color:var(--ink);text-decoration:none}
.toc a b{display:block;color:var(--em2);font-size:15px}
.toc a span{font-size:13px;color:var(--muted)}
.namaz{margin-top:22px}
h2{font-family:Georgia,"Playfair Display",serif;font-weight:600;font-size:22px;color:var(--em2);margin:0;line-height:1.3}
.meta{font-size:13px;color:var(--muted);margin:2px 0 10px}
.rakat{margin:18px 0 6px;font-size:12px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--gold);display:flex;align-items:center;gap:8px}
.rakat:after{content:"";flex:1;height:1px;background:linear-gradient(90deg,var(--gold),transparent);opacity:.5}
.rakat span{letter-spacing:.02em;text-transform:none;font-weight:500;color:var(--muted)}
.rakat.silent{color:var(--muted)}
.seg{margin:6px 0 4px}
.segh,details.seg>summary{display:flex;justify-content:space-between;align-items:baseline;gap:10px;font-weight:600;color:var(--em2);font-size:16px;padding:2px 2px 4px}
details.seg>summary{cursor:pointer;list-style:none}
details.seg>summary i{font-style:normal;font-weight:400;font-size:12px;color:var(--muted)}
.arname{font-family:'KFGQPC','Noto Naskh Arabic',serif;font-weight:400;color:var(--gold);font-size:20px}
.besmele{font-family:'KFGQPC','Noto Naskh Arabic',serif;text-align:center;font-size:24px;color:var(--em2);margin:6px 0}
.ayah{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:12px 14px 10px;margin:10px 0;box-shadow:0 2px 8px rgba(0,0,0,.04)}
.tag{display:inline-block;background:var(--mint);color:var(--em2);font-size:12px;font-weight:700;letter-spacing:.04em;padding:2px 10px;border-radius:999px}
.ar{font-family:'KFGQPC','Noto Naskh Arabic','Amiri',serif;font-size:27px;line-height:2.15;text-align:right;margin:6px 0 2px;word-spacing:2px}
.meal{margin:6px 0 2px;font-size:16px;line-height:1.6}
.tefsir{margin-top:34px;border-top:1px solid var(--line);padding-top:16px}
.tefsir h3{font-size:14px;color:var(--gold);margin:18px 0 6px;font-weight:700}
.note,.empty{color:var(--muted);font-size:14px}
details.tf{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:6px 0;padding:0 12px}
details.tf summary{cursor:pointer;padding:9px 0;font-weight:600;color:var(--em2)}
details.tf p{margin:0 0 10px;font-size:15px}
footer{margin-top:28px;font-size:12px;color:var(--muted);line-height:1.5}
"""
}
