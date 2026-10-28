package com.tilavet.takip.util

import android.content.Context

/**
 * Onceki namazin son zamm konumu (sure, ayet): hatimle okuyan imam ertesi namazda kaldigi yerden devam eder. Mikrofon
 * oturumu baslarken [MAX_AGE_MS] icindeyse StateMachine'e verilir (SessionState.zammSurah / zammAyah) → Fatiha sonundaki
 * gecis aramasinda devam penceresi ilk zammda da kullanilir (bkz. StateMachine CONTINUE_*). Sabah 28.10: dunku yatsi
 * 23:77'de bitti, "وهو الذي أنشأ" 6:141 / 23:78 ayni skor → telefon 6:141'e (En'am) gecti. Kayitlar tarih sirasiyla
 * zincirlenince (16 cami namazi) sadece bu kayit degisti (tests: eval_pipeline.PREV_ZAMM). Simulasyonda okunmaz / yazilmaz.
 */
object ZammMemory {
    private const val PREFS = "zamm_memory"
    private const val K_SURAH = "surah"
    private const val K_AYAH = "ayah"
    private const val K_TIME = "time"
    /** Bundan eski konum kullanilmaz (yatsi → sabah ~11 sa; bir namaz kacirilsa da). */
    const val MAX_AGE_MS = 48L * 3600 * 1000

    /** Kayitli konum ve yasi (ms); yoksa / [MAX_AGE_MS]'den eskiyse null. */
    fun load(ctx: Context, nowMs: Long = System.currentTimeMillis()): Pair<Pair<Int, Int>, Long>? {
        val p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val s = p.getInt(K_SURAH, 0)
        val a = p.getInt(K_AYAH, 0)
        val t = p.getLong(K_TIME, 0L)
        val age = nowMs - t
        if (s <= 0 || a <= 0 || t <= 0L || age < 0 || age > MAX_AGE_MS) return null
        return (s to a) to age
    }

    fun save(ctx: Context, zamm: Pair<Int, Int>, nowMs: Long = System.currentTimeMillis()) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putInt(K_SURAH, zamm.first)
            .putInt(K_AYAH, zamm.second)
            .putLong(K_TIME, nowMs)
            .apply()
    }
}
