import android.content.DirContext
import com.tilavet.takip.aligner.Aligner
import com.tilavet.takip.aligner.AlignerTestRunner
import com.tilavet.takip.aligner.FuzzyTestRunner
import com.tilavet.takip.aligner.QuranIndex
import com.tilavet.takip.audio.ChunkBuilder
import com.tilavet.takip.audio.TextHold
import com.tilavet.takip.audio.VoiceActivity
import com.tilavet.takip.audio.WavReader
import com.tilavet.takip.session.ChunkStatus
import com.tilavet.takip.session.EzanEvent
import com.tilavet.takip.session.EzanTracker
import com.tilavet.takip.session.NamazState
import com.tilavet.takip.session.RakatTracker
import com.tilavet.takip.session.SessionState
import com.tilavet.takip.session.StateMachine
import com.tilavet.takip.session.StateMachineTestRunner
import com.tilavet.takip.session.ZikirTracker
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Locale
import kotlin.system.exitProcess

/**
 * APK oncesi test kapisinin Kotlin tarafi (tests/gate.py cagirir). Uygulamanin kendi kaynaklari derlenir; ciktilar
 * Python referansiyla / altin dosyalarla gate.py'de karsilastirilir.
 *
 *   fixtures <assets> <out.json>      Fuzzy (51) + Aligner (43) + StateMachine fixture'lari — uygulamadaki Σ # ▶ runner'lari
 *   trace    <assets> <trjson> <out>  TRJSON'daki her zincir/kayit icin karar izi ("0:M1:2 1:S 2:P113:1 ...", skorsuz)
 *   rakat    <assets> <trjson> <out>  RakatTracker olaylari + etiket degisimleri (zaman)
 *   ezan     <assets> <trjson> <out>  EzanTracker pencere olaylari
 *   zikir    <assets> <trjson> <out>  ZikirTracker zikir kartlari ("ezan": o an ezan/kamet penceresi acik → UI gostermez)
 *   hide     <assets> <trjson> <wavdir> <out>  Ses kesilince metni kaldirma (VoiceActivity + TextHold, varsayilan 3 sn):
 *                                    kaydin WAV'i 100 ms cerceve, parca sonuclari bitis + 1 sn'de ekranda → "HIDE t" / "SHOW t"
 *   chunks   <f32dir> <out>           ChunkBuilder parca sinirlari (always / toggle modlari; Python vad_chunker ile karsilastirilir)
 *   wav      <dir> <out>              WavReader ile her *.wav → <ad>.wavreader.f32 (Python soundfile ile karsilastirir)
 *   glasses                           G2 gozluk koprusu (GlassesBridge) otomatik kontrolleri — bkz. GlassesTests.kt
 *   meals <asr>                       secilebilir mealler (meals/index.tsv + dosyalar, MealCatalog / MealLoader) — MealTests.kt
 *
 * <assets>: android-assets-staged (icinde asr/quran.bin ve fixture'lar). StateMachine/Aligner telefon varsayilanlariyla
 * (ilk kilit 70, pencere ±2) — eval ve fixture ile ayni.
 */
fun main(args: Array<String>) {
    if (args.isEmpty()) {
        System.err.println("kullanim: fixtures|trace|rakat|ezan|zikir|chunks|wav|glasses|meals ...")
        exitProcess(2)
    }
    val code = when (args[0]) {
        "fixtures" -> fixtures(File(args[1]), File(args[2]))
        "trace" -> trace(File(args[1]), File(args[2]), File(args[3]))
        "rakat" -> rakat(File(args[1]), File(args[2]), File(args[3]))
        "ezan" -> ezan(File(args[1]), File(args[2]), File(args[3]))
        "zikir" -> zikir(File(args[1]), File(args[2]), File(args[3]))
        "hide" -> hide(File(args[1]), File(args[2]), File(args[3]), File(args[4]))
        "chunks" -> chunks(File(args[1]), File(args[2]))
        "wav" -> wav(File(args[1]), File(args[2]))
        "glasses" -> glassesTests()
        "meals" -> mealTests(File(args[1]))   // <asr dizini>: Ayarlar → MEAL (MealCatalog + MealLoader)
        "glasses-serve" -> glassesServe(File(args[1]), File(args[2]), args.getOrNull(3)?.toInt() ?: 18765)  // g2dir, fontdir
        else -> { System.err.println("bilinmeyen komut ${args[0]}"); 2 }
    }
    exitProcess(code)
}

private fun engine(assets: File): Pair<QuranIndex, Aligner> {
    val idx = QuranIndex.load(File(assets, "asr/quran.bin").absolutePath)
    // Ayni parca metinleri (gercek kayitlar, bilesikler, zorlama) defalarca hizalaniyor: buyuk onbellek
    val al = Aligner(idx).apply { defaultWindowSlack = 2; cacheSize = 500_000 }
    return idx to al
}

private fun fixtures(assets: File, out: File): Int {
    val ctx = DirContext(assets)
    val (idx, al) = engine(assets)
    val fz = FuzzyTestRunner.runAll(ctx)
    val ag = AlignerTestRunner.runAll(ctx, al)
    val sm = StateMachineTestRunner.runAll(ctx, idx, al)
    val res = JSONObject()
        .put("fuzzy", JSONObject().put("total", fz.totalCases).put("passed", fz.passedCount))
        .put("aligner", JSONObject().put("total", ag.totalCases).put("passed", ag.passedCount))
        .put("state_machine", JSONObject().put("total", sm.totalChecks).put("passed", sm.passedCount)
            .put("failures", JSONArray(sm.failedChecks.map { "[${it.scenarioIdx}/${it.chunkIdx}] ${it.failReason}" })))
    out.writeText(res.toString(2))
    println(FuzzyTestRunner.formatSummary(fz))
    println(AlignerTestRunner.formatSummary(ag))
    println(StateMachineTestRunner.formatSummary(sm))
    return 0
}

/** TRJSON parcasi: rms, metin, parca bitis zamani (yoksa 5 sn izgarasi). */
private data class Chunk(val rms: Double, val text: String, val endSec: Double)

private fun readTrjson(f: File): Map<String, Map<String, List<Chunk>>> {
    val byCfg = sortedMapOf<String, MutableMap<String, List<Chunk>>>()
    for (line in f.readLines()) {
        val i = line.indexOf("TRJSON ")
        if (i < 0) continue
        val d = JSONObject(line.substring(i + 7))
        val ch = d.getJSONArray("chunks")
        val list = (0 until ch.length()).map { k ->
            val a = ch.getJSONArray(k)
            Chunk(
                a.getDouble(0),
                if (a.isNull(1)) "" else a.getString(1),
                if (a.length() > 2 && !a.isNull(2)) a.getDouble(2) else (k + 1) * 5.0,
            )
        }
        byCfg.getOrPut(d.getString("config")) { sortedMapOf() }[d.getString("file")] = list
    }
    return byCfg
}

private fun trace(assets: File, trjson: File, out: File): Int {
    val (idx, al) = engine(assets)
    val sm = StateMachine(idx, al).apply { minConfidenceFirstLock = 70.0 }
    val sb = StringBuilder()
    for ((cfg, files) in readTrjson(trjson)) for ((fn, chunks) in files) {
        val st = SessionState()
        val cells = chunks.mapIndexed { k, c ->
            val r = sm.processChunk(c.rms, c.text, k, st)
            when (r.status) {
                ChunkStatus.MATCHED -> r.verses!![r.gapFilled].let { v -> "$k:M${v.surah}:${v.ayah}" }
                ChunkStatus.PENDING -> "$k:P${r.pendingSurah}:${r.pendingAyah}" + (if (r.ambiguous) "?" else "")
                ChunkStatus.LOW_CONFIDENCE -> "$k:L"
                ChunkStatus.TOO_SHORT -> "$k:S"
                else -> "$k:-"
            }
        }
        sb.append(cfg).append('\t').append(fn).append('\t').append(cells.joinToString(" ")).append('\n')
    }
    out.writeText(sb.toString())
    return 0
}

private fun rakat(assets: File, trjson: File, out: File): Int {
    val (idx, al) = engine(assets)
    val sm = StateMachine(idx, al).apply { minConfidenceFirstLock = 70.0 }
    val sb = StringBuilder()
    for ((cfg, files) in readTrjson(trjson)) for ((fn, chunks) in files) {
        val st = SessionState()
        val rt = RakatTracker()
        var last: String? = null
        val lines = ArrayList<String>()
        for ((k, c) in chunks.withIndex()) {
            val r = sm.processChunk(c.rms, c.text, k, st)
            val ev = rt.onChunk(r, c.endSec)
            val lab = rt.label(c.endSec)
            if (ev != null) lines += String.format(Locale.ROOT, "%.1f olay %s", c.endSec, ev)
            if (lab != last) { lines += String.format(Locale.ROOT, "%.1f etiket %s", c.endSec, lab ?: "-"); last = lab }
        }
        for (l in lines) sb.append(cfg).append('\t').append(fn).append('\t').append(l).append('\n')
        sb.append(cfg).append('\t').append(fn).append('\t').append("son rekat=${rt.rakat} toplam=${rt.completedTotal} namaz=${rt.completedNamaz}\n")
    }
    out.writeText(sb.toString())
    return 0
}

private fun zikir(assets: File, trjson: File, out: File): Int {
    val (idx, al) = engine(assets)
    val sm = StateMachine(idx, al).apply { minConfidenceFirstLock = 70.0 }
    val sb = StringBuilder()
    for ((cfg, files) in readTrjson(trjson)) for ((fn, chunks) in files) {
        val st = SessionState()
        val ez = EzanTracker()
        val zt = ZikirTracker()
        var ezOpen = false
        for ((k, c) in chunks.withIndex()) {
            val r = sm.processChunk(c.rms, c.text, k, st)
            val locked = r.status == ChunkStatus.MATCHED && (r.state == NamazState.FATIHA || r.state == NamazState.ZAMM)
            val e = ez.onChunk(c.text, r.kamet, locked, c.endSec)
            // MainViewModel ile ayni: ezan/kamet penceresi acikken (ya da bu parcada olay varken) zikir karti yok
            val busy = ezOpen || e != EzanEvent.NONE
            ezOpen = e == EzanEvent.OPEN || e == EzanEvent.CHANGED || (ezOpen && e == EzanEvent.NONE)
            val z = zt.onChunk(r, c.endSec)
            if (z.isNotEmpty()) {
                sb.append(cfg).append('\t').append(fn).append('\t')
                    .append(String.format(Locale.ROOT, "%.1f %s%s", c.endSec, z.joinToString(","), if (busy) " ezan" else ""))
                    .append('\n')
            }
        }
    }
    out.writeText(sb.toString())
    return 0
}

/**
 * Ses kesilince metni kaldirma (MainViewModel.checkTextHold ile ayni): sonuc parca bitisinden ~1 sn sonra ekranda
 * (ASR + hizalama, eval PROC_SEC); kilit / gorunen aday hem gosterir hem ses esigini ogretir; kamet vurguyu siler.
 */
private fun hide(assets: File, trjson: File, wavDir: File, out: File): Int {
    val (idx, al) = engine(assets)
    val sm = StateMachine(idx, al).apply { minConfidenceFirstLock = 70.0 }
    val holdSec = TextHold.DEFAULT_TENTHS / 10.0
    val sb = StringBuilder()
    for ((cfg, files) in readTrjson(trjson)) for ((fn, chunks) in files) {
        val wav = File(wavDir, fn)
        if (!wav.exists()) continue
        val st = SessionState()
        // (gorunme zamani, parca RMS'i | kamet → null, gosterilen sure)
        val shows = ArrayList<Triple<Double, Double?, Int>>()
        for ((k, c) in chunks.withIndex()) {
            val r = sm.processChunk(c.rms, c.text, k, st)
            if (r.kamet) shows.add(Triple(c.endSec + 1.0, null, 0))
            else if (r.status == ChunkStatus.MATCHED) {
                shows.add(Triple(c.endSec + 1.0, c.rms, r.verses!!.last().surah))
            } else if (r.status == ChunkStatus.PENDING && !r.jumpCandidate && !r.ambiguous) {
                shows.add(Triple(c.endSec + 1.0, c.rms, r.pendingSurah ?: 0))
            }
        }
        val voice = VoiceActivity()
        var shown = false
        var hidden = false
        var shownAt = 0.0
        var si = 0
        var total = 0L
        val lines = ArrayList<String>()
        WavReader(wav.inputStream()).use { rd ->
            val buf = FloatArray(1600)
            while (true) {
                val n = rd.read(buf)
                if (n < buf.size) break
                total += n
                val t = total / 16000.0
                var sq = 0.0
                for (i in 0 until n) sq += buf[i].toDouble() * buf[i]
                voice.onFrame(t, kotlin.math.sqrt(sq / n))
                while (si < shows.size && shows[si].first <= t) {
                    val lvl = shows[si].second
                    if (lvl == null) {
                        shown = false
                    } else {
                        voice.addRecitationLevel(lvl)
                        shown = true; hidden = false; shownAt = t
                        lines.add(String.format(Locale.ROOT, "SHOW %.1f %d", t, shows[si].third))
                    }
                    si++
                }
                if (shown && !hidden && TextHold.shouldHide(t, voice.lastVoiceSec, shownAt, holdSec)) {
                    hidden = true
                    lines.add(String.format(Locale.ROOT, "HIDE %.1f", t))
                }
            }
        }
        for (line in lines) sb.append(cfg).append('\t').append(fn).append('\t').append(line).append('\n')
    }
    out.writeText(sb.toString())
    return 0
}

private fun ezan(assets: File, trjson: File, out: File): Int {
    val (idx, al) = engine(assets)
    val sm = StateMachine(idx, al).apply { minConfidenceFirstLock = 70.0 }
    val sb = StringBuilder()
    for ((cfg, files) in readTrjson(trjson)) for ((fn, chunks) in files) {
        val st = SessionState()
        val ez = EzanTracker()
        for ((k, c) in chunks.withIndex()) {
            val r = sm.processChunk(c.rms, c.text, k, st)
            val locked = r.status == ChunkStatus.MATCHED && (r.state == NamazState.FATIHA || r.state == NamazState.ZAMM)
            val e = ez.onChunk(c.text, r.kamet, locked, c.endSec)
            if (e != EzanEvent.NONE) {
                sb.append(cfg).append('\t').append(fn).append('\t')
                    .append(String.format(Locale.ROOT, "%.1f %s %s %s", c.endSec, e, ez.view?.title ?: "-", ez.view?.current ?: "-")).append('\n')
            }
        }
    }
    out.writeText(sb.toString())
    return 0
}

/** Hibrit anahtar senaryolari (Python vad_chunker ile ayni): always → hep acik, toggle → kesim sayisi % 3 != 0 iken acik. */
private fun chunks(dir: File, out: File): Int {
    val sb = StringBuilder()
    for (mode in listOf("always", "toggle")) {
        for (f in dir.listFiles()!!.filter { it.name.endsWith(".f32") && !it.name.endsWith(".wavreader.f32") }.sortedBy { it.name }) {
            val bb = ByteBuffer.wrap(f.readBytes()).order(ByteOrder.LITTLE_ENDIAN)
            val a = FloatArray(bb.remaining() / 4) { bb.getFloat() }
            val cb = ChunkBuilder()
            cb.pauseCutEnabled = mode == "always"
            val cuts = ArrayList<String>()
            var i = 0
            while (i + 1600 <= a.size) {
                val r = cb.addSamples(a.copyOfRange(i, i + 1600))
                if (r != null) {
                    cuts.add(String.format(Locale.ROOT, "%.1f%s:%d", (i + 1600) / 16000.0, if (r.second) "p" else "", r.first.size))
                    if (mode == "toggle") cb.pauseCutEnabled = cuts.size % 3 != 0
                }
                i += 1600
            }
            sb.append(mode).append('\t').append(f.name.removeSuffix(".f32")).append('\t').append(cuts.joinToString(" ")).append('\n')
        }
    }
    out.writeText(sb.toString())
    return 0
}

private fun wav(dir: File, out: File): Int {
    val sb = StringBuilder()
    for (f in dir.listFiles { x -> x.name.endsWith(".wav") }!!.sortedBy { it.name }) {
        try {
            WavReader(f.inputStream()).use { r ->
                val buf = FloatArray(1600)
                val all = java.io.ByteArrayOutputStream()
                var total = 0
                while (true) {
                    val n = r.read(buf)
                    if (n <= 0) break
                    val bb = ByteBuffer.allocate(n * 4).order(ByteOrder.LITTLE_ENDIAN)
                    for (i in 0 until n) bb.putFloat(buf[i])
                    all.write(bb.array())
                    total += n
                    if (n < buf.size) break
                }
                File(dir, f.nameWithoutExtension + ".wavreader.f32").writeBytes(all.toByteArray())
                sb.append("${f.name}\t${r.info}\t$total\n")
            }
        } catch (e: Exception) {
            sb.append("${f.name}\tHATA ${e.message}\t0\n")
        }
    }
    out.writeText(sb.toString())
    return 0
}
