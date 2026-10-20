package android.util

/** JVM stub: uygulamadaki Log cagrilari sessizce yutulur (TILAVET_LOG=1 ise stderr'e yazilir). */
object Log {
    private val echo = System.getenv("TILAVET_LOG") == "1"
    private fun out(level: String, tag: String, msg: String): Int {
        if (echo) System.err.println("$level/$tag: $msg")
        return 0
    }
    @JvmStatic fun v(tag: String, msg: String): Int = out("V", tag, msg)
    @JvmStatic fun d(tag: String, msg: String): Int = out("D", tag, msg)
    @JvmStatic fun i(tag: String, msg: String): Int = out("I", tag, msg)
    @JvmStatic fun w(tag: String, msg: String): Int = out("W", tag, msg)
    @JvmStatic fun w(tag: String, msg: String, t: Throwable?): Int = out("W", tag, "$msg ${t?.message ?: ""}")
    @JvmStatic fun e(tag: String, msg: String): Int = out("E", tag, msg)
    @JvmStatic fun e(tag: String, msg: String, t: Throwable?): Int = out("E", tag, "$msg ${t?.message ?: ""}")
}
