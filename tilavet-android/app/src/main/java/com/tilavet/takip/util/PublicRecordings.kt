package com.tilavet.takip.util

import android.content.ContentValues
import android.content.Context
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import java.io.File

/**
 * Mikrofon oturumlarinin kaydini (WAV) ve oturum log'unu (.txt) dosya yoneticisinden alinabilen klasore kopyalar.
 *
 * Kullanici: "kayitlarin hangi dizinde oldugunu soyle, file explorer ile alirim" — cacheDir/sessions uygulamaya ozel
 * (dosya yoneticisi goremez) ve sadece son 3 oturumu tutar. Cami kayitlari egitim verisi olacak (bkz. training/).
 *
 * - Android 10+ (API 29+): MediaStore Downloads → Download/Tilavet Takip (izin gerekmez; uygulama silinse de kalir).
 * - Android 9: uygulamanin dis klasoru Android/data/com.tilavet.takip/files/Tilavet Takip/ (izin gerekmez).
 * - Kopyalananlar silinmez (kullanici aldiktan sonra kendisi siler); cache'teki kopyaya ".pub" isareti konur, ayni
 *   dosya iki kez kopyalanmaz. Su an yazilan oturum (SessionAudioWriter.openFile / SessionLog.currentFile) atlanir.
 * - Uygulama oturum ortasinda kapanirsa (header ~10 sn'de bir guncel) bir sonraki acilista kopyalanir.
 * - Simulasyon oturumlari kaydedilmez (SessionAudioWriter acilmaz) → buraya da gelmez.
 */
object PublicRecordings {

    private const val TAG = "PublicRecordings"
    const val FOLDER = "Tilavet Takip"
    private const val MIN_WAV_BYTES = 44 + 16000 * 2   // 1 sn'den kisa kayitlar (yanlislikla basma) kopyalanmaz

    /** Kullaniciya gosterilecek klasor yolu. */
    fun describe(context: Context): String =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) "Download/$FOLDER"
        else "Android/data/${context.packageName}/files/$FOLDER"

    /**
     * cacheDir/sessions'taki henuz kopyalanmamis kayitlari ve log'larini kopyala. IO thread'inden cagrilmali.
     * Donus: kopyalanan dosya sayisi.
     */
    @Synchronized
    fun publishPending(context: Context): Int {
        val dir = File(context.cacheDir, SessionAudioWriter.DIR)
        val files = dir.listFiles { f -> f.name.endsWith(".wav") || f.name.endsWith(".txt") } ?: return 0
        val busy = setOfNotNull(SessionAudioWriter.openFile?.name, SessionLog.currentFile?.name)
        var n = 0
        for (f in files.sortedBy { it.name }) {
            if (f.name in busy) continue
            val marker = File(dir, f.name + ".pub")
            if (marker.exists()) continue
            if (f.name.endsWith(".wav") && f.length() < MIN_WAV_BYTES) continue
            if (f.name.endsWith(".txt")) {
                // Log'u, WAV'i kopyalanacak/kopyalanmis oturumlarda al (kisa / bos oturumun log'u gerekmez)
                val wav = File(dir, f.name.removeSuffix(".txt") + ".wav")
                if (!wav.exists() || wav.length() < MIN_WAV_BYTES) continue
            }
            val ok = try {
                copy(context, f)
            } catch (e: Throwable) {
                SessionLog.e(TAG, "Kayit kopyalanamadi: ${f.name}", e)
                false
            }
            if (ok) {
                try { marker.createNewFile() } catch (_: Throwable) {}
                n++
                SessionLog.d(TAG, "[kayit] ${describe(context)}/${f.name} (${f.length() / 1024} KB)")
            }
        }
        return n
    }

    private fun copy(context: Context, f: File): Boolean {
        val mime = if (f.name.endsWith(".wav")) "audio/x-wav" else "text/plain"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val cr = context.contentResolver
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, f.name)
                put(MediaStore.MediaColumns.MIME_TYPE, mime)
                put(MediaStore.MediaColumns.RELATIVE_PATH, "${Environment.DIRECTORY_DOWNLOADS}/$FOLDER")
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }
            val uri = cr.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: return false
            try {
                val out = cr.openOutputStream(uri) ?: throw IllegalStateException("cikis acilamadi")
                out.use { o -> f.inputStream().use { it.copyTo(o, 1 shl 16) } }
                cr.update(uri, ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }, null, null)
            } catch (e: Throwable) {
                try { cr.delete(uri, null, null) } catch (_: Throwable) {}
                throw e
            }
            return true
        }
        val outDir = File(context.getExternalFilesDir(null) ?: return false, FOLDER).apply { mkdirs() }
        f.copyTo(File(outDir, f.name), overwrite = true)
        return true
    }
}
