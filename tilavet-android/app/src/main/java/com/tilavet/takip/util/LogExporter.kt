package com.tilavet.takip.util

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Process
import android.util.Log
import androidx.core.content.FileProvider
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Uygulamanın kendi logcat çıktısını dosyaya yazıp paylaşan helper.
 *
 * Android'de bir uygulamanın **kendi PID'sinin** logcat'ini okumak
 * READ_LOGS permission'i gerektirmez (Android 4.1+).
 *
 * Kullanim:
 *   val file = LogExporter.export(context)
 *   LogExporter.share(context, listOfNotNull(file, SessionAudioWriter.latest(context.cacheDir)))
 */
object LogExporter {

    private const val TAG = "LogExporter"
    private const val MAX_LINES = 10000  // Cok fazla buyumesin
    private val FILTERED_TAGS = listOf(
        "AudioPipeline", "AudioRecorder", "MainViewModel", "SessionAudioWriter", "SessionLog", "PublicRecordings",
        "AssetSync",
        "Aligner", "QuranIndex", "MushafData", "OnnxAsrEngine", "SentencePieceDecoder",
        "AlignerTestRunner", "FuzzyTestRunner", "StateMachineTestRunner",
        "AndroidRuntime",
    )

    /**
     * Logcat'i okuyup cache dizininde bir dosyaya yazar, dosyayi don.
     */
    fun export(context: Context): File? {
        return try {
            val ts = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())
            val dir = File(context.cacheDir, "logs").apply { mkdirs() }
            val file = File(dir, "tilavet-log-$ts.txt")

            val pid = Process.myPid().toString()

            // logcat -d: dump and exit (live mode degil)
            // -v threadtime: zaman + thread bilgisi
            val cmd = listOf("logcat", "-d", "-v", "threadtime")
            val process = ProcessBuilder(cmd).redirectErrorStream(true).start()

            file.bufferedWriter().use { writer ->
                writer.write("=== Tilavet Takip Logcat ===\n")
                writer.write("Tarih: ${Date()}\n")
                writer.write("PID: $pid\n")
                writer.write("Filtre: PID=$pid + tag listesi\n")
                writer.write("Tag'ler: ${FILTERED_TAGS.joinToString(", ")}\n")
                writer.write("============================\n\n")

                BufferedReader(InputStreamReader(process.inputStream)).use { reader ->
                    var lineCount = 0
                    var matched = 0
                    val tagPattern = FILTERED_TAGS.joinToString("|") { Regex.escape(it) }
                    val lineRegex = Regex(
                        // threadtime format: MM-DD HH:MM:SS.mmm  PID  TID L tag: message
                        // Bizim ilgilendigimiz: ya PID match ya da TAG match
                        """^\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\s+(\d+)\s+\d+\s+[VDIWE]\s+($tagPattern)\s*:.*"""
                    )

                    val seen = ArrayList<String>(MAX_LINES)
                    reader.forEachLine { line ->
                        lineCount++
                        // Bize ait olan satirlari topla — ya PID matches ya da TAG bizim listemizde
                        val match = lineRegex.find(line) ?: return@forEachLine
                        val linePid = match.groupValues[1]
                        // Yalniz bizim PID veya bizim tag (PID 0 olabilir, system process'lar)
                        if (linePid == pid || true /* tag zaten filterlemis */) {
                            seen.add(line)
                            // Cap
                            if (seen.size > MAX_LINES) {
                                // En eskiyi at
                                seen.removeAt(0)
                            }
                            matched++
                        }
                    }

                    seen.forEach { writer.write(it); writer.newLine() }
                    writer.write("\n--- Toplam $matched satir / $lineCount okunan ---\n")
                }
            }

            process.waitFor()
            Log.d(TAG, "Log export edildi: ${file.absolutePath} (${file.length() / 1024} KB)")
            file
        } catch (e: Throwable) {
            Log.e(TAG, "export hata", e)
            null
        }
    }

    /**
     * Share intent ac — kullanici Drive, mail, vb. uygulama ile dosyayi paylaşabilir.
     */
    fun share(context: Context, file: File) = share(context, listOf(file))

    /**
     * Birden fazla dosyayi (log + son oturum WAV'i) tek seferde paylas.
     * Tek dosyada ACTION_SEND, birden fazlasinda ACTION_SEND_MULTIPLE.
     */
    fun share(context: Context, files: List<File>) {
        if (files.isEmpty()) return
        try {
            val authority = "${context.packageName}.fileprovider"
            val uris = ArrayList<Uri>(files.map { FileProvider.getUriForFile(context, authority, it) })
            val names = files.joinToString(", ") { it.name }

            val intent: Intent
            if (uris.size == 1) {
                intent = Intent(Intent.ACTION_SEND)
                intent.type = if (files[0].name.endsWith(".wav")) "audio/wav" else "text/plain"
                intent.putExtra(Intent.EXTRA_STREAM, uris[0])
            } else {
                intent = Intent(Intent.ACTION_SEND_MULTIPLE)
                intent.type = "*/*"
                intent.putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
            }
            intent.putExtra(Intent.EXTRA_SUBJECT, "Tilavet Takip — $names")
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            val title = if (uris.size == 1) "Logu paylaş" else "Log + ses kaydını paylaş"
            val chooser = Intent.createChooser(intent, title).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(chooser)
        } catch (e: Throwable) {
            Log.e(TAG, "share hata", e)
        }
    }
}
