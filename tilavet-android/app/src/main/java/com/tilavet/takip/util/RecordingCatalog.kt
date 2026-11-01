package com.tilavet.takip.util

import android.content.ContentUris
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.BaseColumns
import android.provider.DocumentsContract
import android.provider.MediaStore
import androidx.core.content.FileProvider
import java.io.File

/** Paylas penceresindeki bir oturum (ses + log, Uri'leriyle). */
typealias SessionRecording = RecordingMerge.Recording<Uri>

/**
 * Paylas penceresi (📤) icin son [RecordingMerge.MAX] oturum kaydi. Kaynaklar (oncelik sirasiyla):
 *  1. Kullanicinin bir kez sectigi klasor (Download/Tilavet Takip; SAF, kalici okuma izni) — klasordeki TUM dosyalar.
 *  2. Download/Tilavet Takip, MediaStore: uygulamanin kendi ekledigi dosyalar izinsiz okunur. Uygulama silinip yeniden
 *     kurulursa Android eski dosyalarin sahipligini dusurur → bunlar burada gorunmez (01.11: 📤'te 30 yerine 3 kayit);
 *     o zaman 1. kaynak gerekir. Android 9: uygulamanin dis klasoru.
 *  3. cacheDir/sessions (son 3 WAV, son 20 log; henuz kopyalanmamis oturum).
 * Su an yazilan oturum listelenmez. IO thread'inde cagrilir.
 */
object RecordingCatalog {
    private const val TAG = "RecordingCatalog"

    /** Liste + tani: her kaynakta kac dosya goruldu ([folderFiles] null = klasor secilmemis / izin yok). */
    class Listing(
        val recordings: List<SessionRecording>,
        val folderFiles: Int?,
        val publicFiles: Int,
        val cacheFiles: Int,
    ) {
        /** Paylas penceresinin altindaki tani satiri. */
        val info: String
            get() = buildString {
                if (folderFiles != null) append("Seçilen klasör: $folderFiles dosya · ")
                append("Download/${PublicRecordings.FOLDER}: $publicFiles dosya · uygulama içi: $cacheFiles dosya")
            }
    }

    fun list(context: Context, folder: Uri?): Listing {
        val folderEntries = folder?.takeIf { hasAccess(context, it) }?.let {
            try {
                folderEntries(context, it)
            } catch (e: Throwable) {
                SessionLog.w(TAG, "secilen klasor okunamadi: ${e.message}")
                null
            }
        }
        val public = try {
            publicEntries(context)
        } catch (e: Throwable) {
            SessionLog.w(TAG, "genel klasor okunamadi: ${e.message}")
            emptyList()
        }
        val cache = cacheEntries(context)
        val busy = setOfNotNull(SessionAudioWriter.openFile?.name, SessionLog.currentFile?.name)
        val recs = RecordingMerge.merge(listOfNotNull(folderEntries, public, cache), busy)
        return Listing(recs, folderEntries?.size, public.size, cache.size).also {
            SessionLog.d(TAG, "[paylas] liste: ${it.info} → ${recs.size} kayit")
        }
    }

    /** Klasor icin kalici okuma izni hala var mi. */
    fun hasAccess(context: Context, tree: Uri): Boolean =
        context.contentResolver.persistedUriPermissions.any { it.uri == tree && it.isReadPermission }

    /** Klasor seciciden donen adres: izni kalici yap (uygulama yeniden acilinca da okunsun). */
    fun takeAccess(context: Context, tree: Uri): Boolean = try {
        context.contentResolver.takePersistableUriPermission(tree, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        true
    } catch (e: Throwable) {
        SessionLog.w(TAG, "klasor izni alinamadi: ${e.message}")
        false
    }

    /** Klasor secicinin acilacagi yer (ipucu): Download/Tilavet Takip. */
    fun folderHint(): Uri = DocumentsContract.buildDocumentUri(
        "com.android.externalstorage.documents", "primary:${Environment.DIRECTORY_DOWNLOADS}/${PublicRecordings.FOLDER}",
    )

    private fun authority(context: Context) = "${context.packageName}.fileprovider"

    private fun folderEntries(context: Context, tree: Uri): List<RecordingMerge.Entry<Uri>> {
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, DocumentsContract.getTreeDocumentId(tree))
        val proj = arrayOf(
            DocumentsContract.Document.COLUMN_DOCUMENT_ID,
            DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_SIZE,
        )
        val out = ArrayList<RecordingMerge.Entry<Uri>>()
        context.contentResolver.query(children, proj, null, null, null)?.use { c ->
            while (c.moveToNext()) {
                val id = c.getString(0) ?: continue
                val name = c.getString(1) ?: continue
                out += RecordingMerge.Entry(name, c.getLong(2), DocumentsContract.buildDocumentUriUsingTree(tree, id))
            }
        }
        return out
    }

    private fun publicEntries(context: Context): List<RecordingMerge.Entry<Uri>> {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val coll = MediaStore.Downloads.EXTERNAL_CONTENT_URI
            val proj = arrayOf(BaseColumns._ID, MediaStore.MediaColumns.DISPLAY_NAME, MediaStore.MediaColumns.SIZE)
            val sel = "${MediaStore.MediaColumns.RELATIVE_PATH} LIKE ? AND ${MediaStore.MediaColumns.DISPLAY_NAME} LIKE ?"
            val args = arrayOf("${Environment.DIRECTORY_DOWNLOADS}/${PublicRecordings.FOLDER}%", "tilavet-%")
            val out = ArrayList<RecordingMerge.Entry<Uri>>()
            val cr = context.contentResolver
            cr.query(coll, proj, sel, args, null)?.use { c ->
                val iId = c.getColumnIndexOrThrow(BaseColumns._ID)
                val iName = c.getColumnIndexOrThrow(MediaStore.MediaColumns.DISPLAY_NAME)
                val iSize = c.getColumnIndexOrThrow(MediaStore.MediaColumns.SIZE)
                while (c.moveToNext()) {
                    val name = c.getString(iName) ?: continue
                    val uri = ContentUris.withAppendedId(coll, c.getLong(iId))
                    // MediaStore'un boyut sutunu bos / 0 olabiliyor (dosya sonradan yazildi): o zaman dosyanin kendisinden
                    // — 0 kalsaydi kayit "1 sn'den kisa" sayilip listeden dusuyordu
                    var size = c.getLong(iSize)
                    if (size <= 0) size = try {
                        cr.openFileDescriptor(uri, "r")?.use { it.statSize } ?: 0L
                    } catch (e: Throwable) {
                        0L
                    }
                    out += RecordingMerge.Entry(name, size, uri)
                }
            }
            return out
        }
        val dir = File(context.getExternalFilesDir(null) ?: return emptyList(), PublicRecordings.FOLDER)
        return dir.listFiles()?.map { f ->
            RecordingMerge.Entry(f.name, f.length(), FileProvider.getUriForFile(context, authority(context), f))
        } ?: emptyList()
    }

    private fun cacheEntries(context: Context): List<RecordingMerge.Entry<Uri>> {
        val dir = File(context.cacheDir, SessionAudioWriter.DIR)
        return dir.listFiles { f -> f.name.endsWith(".wav") || f.name.endsWith(".txt") }?.map { f ->
            RecordingMerge.Entry(f.name, f.length(), FileProvider.getUriForFile(context, authority(context), f))
        } ?: emptyList()
    }
}
