package android.content

import android.content.res.AssetManager

/** JVM stub: fixture runner'lari sadece context.assets.open(...) kullanir. */
abstract class Context {
    abstract val assets: AssetManager
}

/** Asset'leri bir klasorden okuyan Context (APK'daki assets/ = android-assets-staged/). */
class DirContext(dir: java.io.File) : Context() {
    override val assets: AssetManager = AssetManager(dir)
}
