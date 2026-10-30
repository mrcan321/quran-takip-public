package com.tilavet.takip.util

import android.content.Context
import com.tilavet.takip.R
import com.tilavet.takip.data.MealLoader
import com.tilavet.takip.data.MushafData
import com.tilavet.takip.report.NamazReport
import com.tilavet.takip.report.ReportHtml
import java.io.File
import java.text.SimpleDateFormat
import java.util.Base64
import java.util.Locale

/**
 * Ana ekran → RAPOR: oturum log'larindan (cacheDir/sessions, son SessionAudioWriter.LOG_KEEP oturum) en son N namazda
 * (Ayarlar → RAPORDAKİ NAMAZ SAYISI, 1-7; ReportHtml.lastNamaz) okunan ayetler →
 * cacheDir/reports/namaz-raporu.html (tek dosya: KFGQPC fontu icinde; uygulama icinde gosterilir, paylasilinca da acilir).
 * Tefsir assets/asr/tefsir.bin'den (scripts/build_tefsir.py; yoksa tefsir bolumu yok).
 */
object NamazReportBuilder {
    private const val TAG = "NamazReport"
    const val DIR = "reports"
    const val FILE_NAME = "namaz-raporu.html"
    const val TEFSIR_BIN = "tefsir.bin"
    const val TEFSIR_NAME = "El-Muhtasar fi Tefsîri'l-Kur'ân (Tefsir Araştırmaları Merkezi)"
    private val NAME = Regex("""tilavet-(\d{8}-\d{6})""")

    /**
     * IO'da cagrilir. [mealName] secili meal (Ayarlar → MEAL), [namazCount] rapordaki namaz sayisi (1-7). Kayitlarda daha az
     * namaz varsa olan kadar (hic yoksa bos rapor); okunamayan log atlanir.
     */
    fun build(ctx: Context, mushaf: MushafData, mealName: String, asrDir: File, namazCount: Int): File {
        val all = SessionAudioWriter.listLogs(ctx.cacheDir).asSequence().mapNotNull { log ->
            val namazlar = try {
                log.useLines { NamazReport.parse(it) }
            } catch (e: Exception) {
                SessionLog.w(TAG, "log okunamadi: ${log.name} ${e.message}")
                return@mapNotNull null
            }
            val wav = SessionAudioWriter.wavOf(log)
            ReportHtml.Session(startMs(log), if (wav.exists()) SessionAudioWriter.durationSec(wav) else null, namazlar)
        }
        val sessions = ReportHtml.lastNamaz(all, namazCount)
        val tefsir = File(asrDir, TEFSIR_BIN).takeIf { it.exists() }?.let {
            try {
                MealLoader.load(it.absolutePath)
            } catch (e: Exception) {
                SessionLog.w(TAG, "tefsir acilamadi: ${e.message}")
                null
            }
        }
        val font = try {
            ctx.resources.openRawResource(R.font.kfgqpc_hafs).use { Base64.getEncoder().encodeToString(it.readBytes()) }
        } catch (e: Exception) {
            null
        }
        try {
            val html = ReportHtml.render(sessions, MushafText(mushaf, tefsir, mealName), System.currentTimeMillis(), font,
                requested = namazCount)
            val dir = File(ctx.cacheDir, DIR).apply { mkdirs() }
            val out = File(dir, FILE_NAME)
            out.writeText(html)
            SessionLog.d(TAG, "rapor: ${sessions.size} kayit, ${sessions.sumOf { it.namazlar.size }}/$namazCount namaz → " +
                "${out.name} (${out.length() / 1024} KB)")
            return out
        } finally {
            tefsir?.close()
        }
    }

    /** Dosya adindan baslangic zamani (tilavet-20261027-194923.txt), olmazsa dosya zamani. */
    private fun startMs(f: File): Long {
        val m = NAME.find(f.name) ?: return f.lastModified()
        return try {
            SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).parse(m.groupValues[1])?.time ?: f.lastModified()
        } catch (e: Exception) {
            f.lastModified()
        }
    }

    private class MushafText(
        private val m: MushafData,
        private val tefsir: MealLoader?,
        override val mealName: String,
    ) : ReportHtml.Text {
        override val tefsirName: String? = if (tefsir != null) TEFSIR_NAME else null
        override fun surahName(surah: Int) = m.surahNameTr(surah)
        override fun surahArabic(surah: Int) = m.surahInfo(surah)?.nameAr
        override fun ayahCount(surah: Int) = m.surahAyahCount(surah)
        override fun arabic(surah: Int, ayah: Int): String {
            val a = m.ayahIndex(surah, ayah) ?: return ""
            return m.words(a).joinToString(" ") + " " + ayah.toString().map { '٠' + (it - '0') }.joinToString("")
        }
        override fun besmele() = m.besmele
        override fun meal(surah: Int, ayah: Int) = m.ayahIndex(surah, ayah)?.let { m.meal(it) }
        override fun tefsir(surah: Int, ayah: Int) = tefsir?.getMeal(surah, ayah)
    }
}
