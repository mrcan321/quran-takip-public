package com.tilavet.takip.util

import android.util.Log
import java.io.BufferedWriter
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Oturum log'u: pipeline / ViewModel satirlarini logcat'e yazar, mikrofon oturumu aciksa ayni satirlari oturumun
 * WAV'inin yanindaki .txt dosyasina da ekler (cacheDir/sessions/tilavet-YYYYMMDD-HHmmss.txt).
 *
 * Neden: logcat tamponu telefonun tum uygulamalarina ortak — uzun oturumda bastaki satirlar siliniyor (yatsi 19.10:
 * 20 dk'lik kaydin ilk 8 dk'si log'da yoktu). Dosyadaki satirlar WAV ile birlikte Download/Tilavet Takip'e kopyalanir
 * (PublicRecordings) → kayit + tam log dosya yoneticisinden alinir.
 *
 * Birden cok thread'den cagrilir (pipeline, ViewModel, G2 koprusu) → yazma senkron.
 */
object SessionLog {

    private const val TAG = "SessionLog"
    private val lock = Any()
    private var writer: BufferedWriter? = null
    private var current: File? = null
    private val timeFmt = SimpleDateFormat("HH:mm:ss.SSS", Locale.US)

    /** Oturum dosyasini ac (oncekini kapatir). Hata olursa sadece logcat'e yazilir. */
    fun start(file: File) {
        synchronized(lock) {
            closeLocked()
            try {
                writer = file.bufferedWriter()
                current = file
                writer?.write("=== Tilavet Takip oturum log'u: ${file.name} — ${Date()} ===\n")
                writer?.flush()
            } catch (e: Throwable) {
                writer = null
                current = null
                Log.e(TAG, "Oturum log'u acilamadi: ${file.name}", e)
            }
        }
    }

    /**
     * Oturum dosyasini kapat. [file] verilirse sadece o dosya aciksa kapatir — eski oturumun gec biten kapanisi
     * yeni oturumun log'unu kapatmasin.
     */
    fun stop(file: File? = null) {
        synchronized(lock) {
            if (file == null || current == file) closeLocked()
        }
    }

    /** Su an yazilan dosya (yayinlarken atlanir). */
    val currentFile: File? get() = synchronized(lock) { current }

    fun d(tag: String, msg: String) {
        Log.d(tag, msg)
        append("D", tag, msg, null)
    }

    fun w(tag: String, msg: String) {
        Log.w(tag, msg)
        append("W", tag, msg, null)
    }

    fun e(tag: String, msg: String, t: Throwable? = null) {
        if (t != null) Log.e(tag, msg, t) else Log.e(tag, msg)
        append("E", tag, msg, t)
    }

    private fun append(level: String, tag: String, msg: String, t: Throwable?) {
        synchronized(lock) {
            val w = writer ?: return
            try {
                w.write("${timeFmt.format(Date())} $level $tag: $msg\n")
                if (t != null) w.write("    ${t.javaClass.simpleName}: ${t.message}\n")
                w.flush()   // satir seyrek (parca basina ~1); uygulama olse de dosyada kalsin
            } catch (e: Throwable) {
                Log.e(TAG, "Oturum log'u yazilamadi, kapatildi", e)
                closeLocked()
            }
        }
    }

    private fun closeLocked() {
        try {
            writer?.close()
        } catch (_: Throwable) {
        }
        writer = null
        current = null
    }
}
