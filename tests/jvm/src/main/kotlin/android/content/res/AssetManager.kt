package android.content.res

import java.io.File
import java.io.InputStream

/** JVM stub: open("asr/x.json") → <dir>/asr/x.json */
class AssetManager(private val dir: File) {
    fun open(fileName: String): InputStream = File(dir, fileName).inputStream()
}
