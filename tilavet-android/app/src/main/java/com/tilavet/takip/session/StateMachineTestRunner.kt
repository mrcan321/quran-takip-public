package com.tilavet.takip.session

import android.content.Context
import android.util.Log
import com.tilavet.takip.aligner.Aligner
import com.tilavet.takip.aligner.QuranIndex
import org.json.JSONArray
import org.json.JSONObject

object StateMachineTestRunner {

    private const val TAG = "StateMachineTestRunner"
    private const val FIXTURE_PATH = "asr/state_machine_fixture.json"
    private const val SCORE_TOLERANCE = 1.5  // skor yuvarlama toleransi

    data class CheckResult(
        val scenarioIdx: Int,
        val chunkIdx: Int,
        val description: String,
        val expectedStatus: String,
        val actualStatus: String,
        val expectedState: String,
        val actualState: String,
        val passed: Boolean,
        val failReason: String?,
    )

    data class TestSummary(
        val totalChecks: Int,
        val passedCount: Int,
        val failedChecks: List<CheckResult>,
        val totalMs: Long,
    ) {
        val passRate: Double get() = if (totalChecks > 0) passedCount.toDouble() / totalChecks * 100 else 0.0
    }

    fun runAll(context: Context, index: QuranIndex, aligner: Aligner): TestSummary {
        val tStart = System.nanoTime()
        val json = context.assets.open(FIXTURE_PATH).bufferedReader().use { it.readText() }
        val root = JSONObject(json)
        val scenarios = root.getJSONArray("scenarios")
        Log.d(TAG, "Fixture yuklendi: ${scenarios.length()} senaryo")

        val results = mutableListOf<CheckResult>()
        var passed = 0
        val sm = StateMachine(index, aligner)

        for (sIdx in 0 until scenarios.length()) {
            val scenario = scenarios.getJSONObject(sIdx)
            val description = scenario.getString("description")
            val chunks = scenario.getJSONArray("chunks")
            Log.d(TAG, "[$sIdx] $description (${chunks.length()} chunk)")

            // Her senaryo icin yeni state
            val state = SessionState()

            for (cIdx in 0 until chunks.length()) {
                val chunkJson = chunks.getJSONObject(cIdx)
                val input = chunkJson.getJSONObject("input")
                val expected = chunkJson.getJSONObject("expected")

                val rms = input.getDouble("rms")
                val text = input.getString("text")

                val tCase = System.nanoTime()
                val actual = try {
                    sm.processChunk(rms, text, cIdx, state)
                } catch (e: Throwable) {
                    Log.e(TAG, "[$sIdx/$cIdx] Hata: ${e.message}", e)
                    results.add(CheckResult(
                        scenarioIdx = sIdx, chunkIdx = cIdx, description = description,
                        expectedStatus = expected.getString("status"),
                        actualStatus = "EXCEPTION",
                        expectedState = expected.getString("state"),
                        actualState = "?",
                        passed = false,
                        failReason = "Exception: ${e.message}",
                    ))
                    continue
                }
                val durMs = (System.nanoTime() - tCase) / 1_000_000L

                val (ok, reason) = compareChunk(expected, actual)
                if (ok) passed++

                Log.d(TAG, "  [$sIdx/$cIdx] ${actual.stateBefore.name} → ${actual.state.name}  " +
                        "${actual.status.name.lowercase()}  ${if (ok) "✓" else "✗ $reason"}  (${durMs}ms)")

                results.add(CheckResult(
                    scenarioIdx = sIdx, chunkIdx = cIdx, description = description,
                    expectedStatus = expected.getString("status"),
                    actualStatus = actual.status.name.lowercase(),
                    expectedState = expected.getString("state"),
                    actualState = actual.state.name,
                    passed = ok,
                    failReason = reason,
                ))
            }
        }

        val totalMs = (System.nanoTime() - tStart) / 1_000_000L
        val failed = results.filter { !it.passed }
        Log.d(TAG, "==========")
        Log.d(TAG, "Sonuc: $passed / ${results.size} gecti (${totalMs}ms)")
        for (f in failed.take(15)) {
            Log.d(TAG, "  FAIL [${f.scenarioIdx}/${f.chunkIdx}]: ${f.failReason}")
        }
        return TestSummary(totalChecks = results.size, passedCount = passed,
            failedChecks = failed, totalMs = totalMs)
    }

    private fun compareChunk(expected: JSONObject, actual: ChunkResult): Pair<Boolean, String?> {
        // Status
        val expStatus = expected.getString("status").lowercase()
        val actStatus = actual.status.name.lowercase()
        if (expStatus != actStatus) {
            return Pair(false, "status: exp=$expStatus got=$actStatus")
        }

        // State
        val expState = expected.getString("state")
        val actState = actual.state.name
        if (expState != actState) {
            return Pair(false, "state: exp=$expState got=$actState")
        }

        // State before
        val expStateBefore = expected.getString("state_before")
        if (expStateBefore != actual.stateBefore.name) {
            return Pair(false, "state_before: exp=$expStateBefore got=${actual.stateBefore.name}")
        }

        // Match-related fields (sadece matched/pending'de relevant)
        if (actStatus == "matched") {
            val expMatchStart = expected.optIntOrNull("match_start")
            val expMatchEnd = expected.optIntOrNull("match_end")
            if (expMatchStart != null && actual.matchStartWordIdx != expMatchStart) {
                return Pair(false, "match_start: exp=$expMatchStart got=${actual.matchStartWordIdx}")
            }
            if (expMatchEnd != null && actual.matchEndWordIdx != expMatchEnd) {
                return Pair(false, "match_end: exp=$expMatchEnd got=${actual.matchEndWordIdx}")
            }
            val expScore = expected.optDoubleOrNull("score")
            if (expScore != null && actual.confidence != null) {
                val delta = kotlin.math.abs(actual.confidence - expScore)
                if (delta > SCORE_TOLERANCE) {
                    return Pair(false, "score: exp=$expScore got=${actual.confidence} Δ=$delta")
                }
            }
            val expGap = expected.optInt("gap_filled", 0)
            if (actual.gapFilled != expGap) {
                return Pair(false, "gap_filled: exp=$expGap got=${actual.gapFilled}")
            }
        }

        if (actStatus == "pending") {
            val expSurah = expected.optIntOrNull("pending_surah")
            val expAyah = expected.optIntOrNull("pending_ayah")
            if (expSurah != null && actual.pendingSurah != expSurah) {
                return Pair(false, "pending_surah: exp=$expSurah got=${actual.pendingSurah}")
            }
            if (expAyah != null && actual.pendingAyah != expAyah) {
                return Pair(false, "pending_ayah: exp=$expAyah got=${actual.pendingAyah}")
            }
            val expAmbiguous = expected.optBoolean("ambiguous", false)
            if (actual.ambiguous != expAmbiguous) {
                return Pair(false, "ambiguous: exp=$expAmbiguous got=${actual.ambiguous}")
            }
        }

        return Pair(true, null)
    }

    fun formatSummary(summary: TestSummary): String {
        val sb = StringBuilder()
        sb.append("Toplam: ${summary.totalChecks} chunk\n")
        sb.append("Geçen:  ${summary.passedCount} (${"%.1f".format(summary.passRate)}%)\n")
        sb.append("Süre:   ${summary.totalMs}ms\n\n")
        if (summary.failedChecks.isEmpty()) {
            sb.append("✓ Tüm chunk'lar Python ile uyumlu\n")
        } else {
            sb.append("✗ ${summary.failedChecks.size} chunk başarısız:\n\n")
            for (f in summary.failedChecks.take(15)) {
                sb.append("[s=${f.scenarioIdx}, c=${f.chunkIdx}]\n")
                sb.append("  ${f.failReason}\n")
            }
        }
        return sb.toString()
    }

    // JSON yardimcilari
    private fun JSONObject.optIntOrNull(key: String): Int? {
        if (isNull(key)) return null
        if (!has(key)) return null
        return getInt(key)
    }
    private fun JSONObject.optDoubleOrNull(key: String): Double? {
        if (isNull(key)) return null
        if (!has(key)) return null
        return getDouble(key)
    }
}
