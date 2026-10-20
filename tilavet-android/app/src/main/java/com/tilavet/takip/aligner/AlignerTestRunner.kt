package com.tilavet.takip.aligner

import android.content.Context
import android.util.Log
import org.json.JSONObject
import kotlin.math.abs

object AlignerTestRunner {

    private const val TAG = "AlignerTestRunner"
    private const val FIXTURE_PATH = "asr/aligner_test_fixture.json"
    private const val SCORE_TOLERANCE = 0.5

    data class CaseResult(
        val transcription: String,
        val description: String,
        val expectedMatch: ExpectedMatch?,
        val actualMatch: AlignmentMatch?,
        val passed: Boolean,
        val failReason: String?,
        val durationMs: Long,
    )

    data class ExpectedMatch(
        val startWordIdx: Int,
        val endWordIdx: Int,
        val score: Double,
        val firstSurah: Int,
        val firstAyah: Int,
        val lastSurah: Int,
        val lastAyah: Int,
    )

    data class TestSummary(
        val totalCases: Int,
        val passedCount: Int,
        val failedCases: List<CaseResult>,
        val slowestCases: List<CaseResult>,
        val totalMs: Long,
    ) {
        val passRate: Double get() = if (totalCases > 0) passedCount.toDouble() / totalCases * 100 else 0.0
    }

    fun runAll(context: Context, aligner: Aligner): TestSummary {
        val tStart = System.nanoTime()

        val json = context.assets.open(FIXTURE_PATH).bufferedReader().use { it.readText() }
        val root = JSONObject(json)
        val cases = root.getJSONArray("cases")

        Log.d(TAG, "Fixture yuklendi: ${cases.length()} test case")

        val results = mutableListOf<CaseResult>()
        var passed = 0

        for (i in 0 until cases.length()) {
            val c = cases.getJSONObject(i)
            val transcription = c.getString("transcription")
            val description = c.getString("description")
            val preferredRange = parsePreferredRange(c)
            val expected = parseExpectedMatch(c)

            val tCase = System.nanoTime()
            Log.d(TAG, "[$i/${cases.length()}] BASLIYOR: '${transcription.take(40)}'")

            val actual = try {
                aligner.align(transcription, preferredRange)
            } catch (e: Throwable) {
                Log.e(TAG, "[$i] ALIGN HATA: ${e.message}", e)
                null
            }

            val durationMs = (System.nanoTime() - tCase) / 1_000_000L
            Log.d(TAG, "[$i/${cases.length()}] BITTI ${durationMs}ms — match=${actual != null}")

            val (ok, reason) = compareCase(expected, actual)
            if (ok) passed++

            results.add(CaseResult(
                transcription = transcription,
                description = description,
                expectedMatch = expected,
                actualMatch = actual,
                passed = ok,
                failReason = reason,
                durationMs = durationMs,
            ))
        }

        val totalMs = (System.nanoTime() - tStart) / 1_000_000L
        val failed = results.filter { !it.passed }
        val slowest = results.sortedByDescending { it.durationMs }.take(5)

        Log.d(TAG, "==========")
        Log.d(TAG, "Sonuc: $passed / ${results.size} gecti (${totalMs}ms toplam)")
        Log.d(TAG, "En yavas 5:")
        for (s in slowest) {
            Log.d(TAG, "  ${s.durationMs}ms '${s.transcription.take(50)}'")
        }
        for (f in failed.take(10)) {
            Log.d(TAG, "  FAIL '${f.transcription.take(40)}': ${f.failReason}")
        }

        return TestSummary(
            totalCases = results.size,
            passedCount = passed,
            failedCases = failed,
            slowestCases = slowest,
            totalMs = totalMs,
        )
    }

    private fun parsePreferredRange(c: JSONObject): IntRange? {
        if (c.isNull("preferred_range")) return null
        val arr = c.getJSONArray("preferred_range")
        return arr.getInt(0)..arr.getInt(1)
    }

    private fun parseExpectedMatch(c: JSONObject): ExpectedMatch? {
        if (c.isNull("expected_match")) return null
        val m = c.getJSONObject("expected_match")
        return ExpectedMatch(
            startWordIdx = m.getInt("start_word_idx"),
            endWordIdx = m.getInt("end_word_idx"),
            score = m.getDouble("score"),
            firstSurah = m.getInt("first_surah"),
            firstAyah = m.getInt("first_ayah"),
            lastSurah = m.getInt("last_surah"),
            lastAyah = m.getInt("last_ayah"),
        )
    }

    private fun compareCase(
        expected: ExpectedMatch?,
        actual: AlignmentMatch?,
    ): Pair<Boolean, String?> {
        if (expected == null && actual == null) return Pair(true, null)
        if (expected == null && actual != null) {
            return Pair(false, "expected null, got match (${actual.startWordIdx}-${actual.endWordIdx} score=${"%.1f".format(actual.score)})")
        }
        if (expected != null && actual == null) {
            return Pair(false, "expected match (${expected.startWordIdx}-${expected.endWordIdx}), got null")
        }
        expected!!; actual!!
        if (actual.startWordIdx != expected.startWordIdx) {
            return Pair(false, "start_idx mismatch: expected ${expected.startWordIdx}, got ${actual.startWordIdx}")
        }
        if (actual.endWordIdx != expected.endWordIdx) {
            return Pair(false, "end_idx mismatch: expected ${expected.endWordIdx}, got ${actual.endWordIdx}")
        }
        val scoreDelta = abs(actual.score - expected.score)
        if (scoreDelta > SCORE_TOLERANCE) {
            return Pair(false, "score Δ=${"%.2f".format(scoreDelta)} (exp ${"%.2f".format(expected.score)}, got ${"%.2f".format(actual.score)})")
        }
        return Pair(true, null)
    }

    fun formatSummary(summary: TestSummary): String {
        val sb = StringBuilder()
        sb.append("Toplam: ${summary.totalCases} case\n")
        sb.append("Geçen:  ${summary.passedCount} (${"%.1f".format(summary.passRate)}%)\n")
        sb.append("Süre:   ${summary.totalMs}ms\n\n")

        sb.append("En yavaş 5:\n")
        for (s in summary.slowestCases) {
            sb.append("  ${s.durationMs}ms  '${s.transcription.take(35)}'\n")
        }
        sb.append("\n")

        if (summary.failedCases.isEmpty()) {
            sb.append("✓ Tüm case'ler bit-perfect Python ile uyumlu\n")
        } else {
            sb.append("✗ ${summary.failedCases.size} case başarısız:\n\n")
            for (f in summary.failedCases.take(20)) {
                val preview = if (f.transcription.length > 35) f.transcription.take(35) + "..." else f.transcription
                sb.append("'$preview'\n")
                sb.append("  ${f.failReason}\n")
            }
            if (summary.failedCases.size > 20) {
                sb.append("\n... ve ${summary.failedCases.size - 20} tane daha\n")
            }
        }

        return sb.toString()
    }
}
