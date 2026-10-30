package com.tilavet.takip.util

import android.content.ContentUris
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.BaseColumns
import android.provider.MediaStore
import androidx.core.content.FileProvider
import java.io.File

/** Paylas penceresindeki bir oturum (ses + log, Uri'leriyle). */
typealias SessionRecording = RecordingMerge.Recording<Uri>

/**
 * Paylas penceresi (📤) icin son [RecordingMerge.MAX] oturum kaydi: once Download/Tilavet Takip (PublicRecordings'in
 * kopyalari — uygulamanin kendi ekledigi dosyalar izinsiz okunur; Android 9'da uygulamanin dis klasoru), sonra
 * cacheDir/sessions (henuz kopyalanmamis / sadece log'u kalan oturumlar). Su an yazilan oturum listelenmez.
 * IO thread'inde cagrilir.
 */
object RecordingCatalog {
    private const val TAG = "RecordingCatalog"

    fun list(context: Context): List<SessionRecording> {
        val public = try {
            publicEntries(context)
        } catch (e: Throwable) {
            SessionLog.w(TAG, "genel klasor okunamadi: ${e.message}")
            emptyList()
        }
        val busy = setOfNotNull(SessionAudioWriter.openFile?.name, SessionLog.currentFile?.name)
        return RecordingMerge.merge(listOf(public, cacheEntries(context)), busy)
    }

    private fun authority(context: Context) = "${context.packageName}.fileprovider"

    private fun publicEntries(context: Context): List<RecordingMerge.Entry<Uri>> {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val coll = MediaStore.Downloads.EXTERNAL_CONTENT_URI
            val proj = arrayOf(BaseColumns._ID, MediaStore.MediaColumns.DISPLAY_NAME, MediaStore.MediaColumns.SIZE)
            val sel = "${MediaStore.MediaColumns.RELATIVE_PATH} LIKE ? AND ${MediaStore.MediaColumns.DISPLAY_NAME} LIKE ?"
            val args = arrayOf("${Environment.DIRECTORY_DOWNLOADS}/${PublicRecordings.FOLDER}%", "tilavet-%")
            val out = ArrayList<RecordingMerge.Entry<Uri>>()
            context.contentResolver.query(coll, proj, sel, args, null)?.use { c ->
                val iId = c.getColumnIndexOrThrow(BaseColumns._ID)
                val iName = c.getColumnIndexOrThrow(MediaStore.MediaColumns.DISPLAY_NAME)
                val iSize = c.getColumnIndexOrThrow(MediaStore.MediaColumns.SIZE)
                while (c.moveToNext()) {
                    val name = c.getString(iName) ?: continue
                    out += RecordingMerge.Entry(name, c.getLong(iSize), ContentUris.withAppendedId(coll, c.getLong(iId)))
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
