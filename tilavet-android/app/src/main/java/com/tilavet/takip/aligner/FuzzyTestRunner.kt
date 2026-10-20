package com.tilavet.takip.aligner

import android.content.Context
import android.util.Log
import org.json.JSONObject
import kotlin.math.abs

/**
 * Fuzzy test fixture runner.
 *
 * fuzzy_test_fixture.json dosyasini APK assets'ten okur, her case icin
 * Kotlin'in ureteceği partial_ratio ve token_sort_ratio sonuclarini
 * Python'un ureteceği sonuclar ile karsilastirir.
 *
 * Tolerans: 0.01 (yuvarlama hatalari icin). Birebir matematiksel uyum
 * gerektigi icin daha buyuk fark kabul edilemez.
 */
object FuzzyTestRunner {

    private const val TAG = "FuzzyTestRunner"
    private const val FIXTURE_PATH = "asr/fuzzy_test_fixture.json"
    private const val TOLERANCE = 0.01

    data class CaseResult(
        val s1: String,
        val s2: String,
        val expectedPartial: Double,
        val actualPartial: Double,
        val expectedSorted: Double,
        val actualSorted: Double,
        val passed: Boolean,
    ) {
        val partialDelta: Double get() = abs(expectedPartial - actualPartial)
        val sortedDelta: Double get() = abs(expectedSorted - actualSorted)
    }

    data class TestSummary(
        val totalCases: Int,
        val passedCount: Int,
        val failedCases: List<CaseResult>,
        val totalMs: Long,
    ) {
        val passRate: Double get() = if (totalCases > 0) passedCount.toDouble() / totalCases * 100 else 0.0
    }

    /**
     * Fixture'i oku, her case'i calistir, sonuclari topla.
     */
    fun runAll(context: Context): TestSummary {
        val t0 = System.nanoTime()

        // Asset'ten fixture'i oku
        val json = context.assets.open(FIXTURE_PATH).bufferedReader().use { it.readText() }
        val root = JSONObject(json)
        val cases = root.getJSONArray("cases")

        Log.d(TAG, "Fixture yuklendi: ${cases.length()} test case")

        val results = mutableListOf<CaseResult>()
        var passed = 0

        for (i in 0 until cases.length()) {
            val c = cases.getJSONObject(i)
            val s1 = c.getString("s1")
            val s2 = c.getString("s2")
            val expectedPartial = c.getDouble("partial_ratio")
            val expectedSorted = c.getDouble("token_sort_ratio")

            val actualPartial = Fuzzy.partialRatio(s1, s2)
            val actualSorted = Fuzzy.tokenSortRatio(s1, s2)

            val partialOk = abs(expectedPartial - actualPartial) <= TOLERANCE
            val sortedOk = abs(expectedSorted - actualSorted) <= TOLERANCE
            val ok = partialOk && sortedOk

            if (ok) passed++

            results.add(CaseResult(
                s1, s2,
                expectedPartial, actualPartial,
                expectedSorted, actualSorted,
                ok,
            ))
        }

        val totalMs = (System.nanoTime() - t0) / 1_000_000L
        val failed = results.filter { !it.passed }

        Log.d(TAG, "Sonuc: $passed / ${results.size} gecti (${totalMs}ms)")
        for (f in failed.take(10)) {
            Log.d(TAG, "  FAIL '${f.s1.take(20)}' / '${f.s2.take(20)}': " +
                    "partial Δ=${"%.2f".format(f.partialDelta)} " +
                    "(exp ${f.expectedPartial}, got ${"%.2f".format(f.actualPartial)})  " +
                    "sorted Δ=${"%.2f".format(f.sortedDelta)} " +
                    "(exp ${f.expectedSorted}, got ${"%.2f".format(f.actualSorted)})")
        }

        return TestSummary(
            totalCases = results.size,
            passedCount = passed,
            failedCases = failed,
            totalMs = totalMs,
        )
    }

    /**
     * Sonucu UI'da gosterilebilecek metin formatinda dondurur.
     */
    fun formatSummary(summary: TestSummary): String {
        val sb = StringBuilder()
        sb.append("Toplam: ${summary.totalCases} case\n")
        sb.append("Geçen:  ${summary.passedCount} (${"%.1f".format(summary.passRate)}%)\n")
        sb.append("Süre:   ${summary.totalMs}ms\n\n")

        if (summary.failedCases.isEmpty()) {
            sb.append("✓ Tüm case'ler bit-perfect Python ile uyumlu\n")
        } else {
            sb.append("✗ ${summary.failedCases.size} case başarısız:\n\n")
            for (f in summary.failedCases.take(15)) {
                sb.append("'${f.s1.take(25)}' / '${f.s2.take(25)}'\n")
                if (f.partialDelta > TOLERANCE) {
                    sb.append("  partial: bekl ${"%.2f".format(f.expectedPartial)} ")
                    sb.append("got ${"%.2f".format(f.actualPartial)} ")
                    sb.append("(Δ${"%.2f".format(f.partialDelta)})\n")
                }
                if (f.sortedDelta > TOLERANCE) {
                    sb.append("  sorted:  bekl ${"%.2f".format(f.expectedSorted)} ")
                    sb.append("got ${"%.2f".format(f.actualSorted)} ")
                    sb.append("(Δ${"%.2f".format(f.sortedDelta)})\n")
                }
            }
            if (summary.failedCases.size > 15) {
                sb.append("\n... ve ${summary.failedCases.size - 15} tane daha\n")
            }
        }

        return sb.toString()
    }
}
