import com.tilavet.takip.data.MealCatalog
import com.tilavet.takip.data.MealLoader
import java.io.File
import java.nio.file.Files

/**
 * Secilebilir mealler (Ayarlar → MEAL): uygulamanin kendi MealCatalog + MealLoader'i ile <asr>/meals/index.tsv ve her meal
 * dosyasi (scripts/build_meals.py). Satir "meals: N/M"; hata sayisi = cikis kodu.
 *   meals <asr dizini>
 */
fun mealTests(asrDir: File): Int {
    var total = 0
    val fails = ArrayList<String>()
    fun ok(name: String, cond: Boolean, detail: () -> String = { "" }) {
        total++
        if (!cond) fails += "$name ${detail()}".trim()
    }

    // katalog ayristirma (dosyasiz): yorum / bos / eksik alan / tekrarlayan id, bilinmeyen id → varsayilan
    val parsed = MealCatalog.parse("# id\tfile\tmerged\tname\tdesc\n\nbulac\tmeal.bin\t0\tAli Bulaç\tX\nkisa\tyok\n" +
        "esed\tmeals/esed.bin\t3\tMuhammed Esed\tKur'an Mesajı\nesed\tmeals/b.bin\t0\tB\tB\n")
    ok("parse", parsed.editions.map { it.id } == listOf("bulac", "esed") && parsed.editions[1].merged == 3) {
        parsed.editions.toString()
    }
    ok("parse bos → varsayilan", MealCatalog.parse("").editions.single() == MealCatalog.FALLBACK)
    ok("resolve bilinmeyen", parsed.resolve("yok").id == "bulac" && parsed.resolve(null).id == "bulac")
    ok("resolve", parsed.resolve("esed").id == "esed")
    val tmp = Files.createTempDirectory("meals").toFile()
    ok("resolve dosyasi yok → varsayilan", parsed.resolve("esed", tmp).id == "bulac")
    ok("load index yok → varsayilan", MealCatalog.load(tmp).editions.single() == MealCatalog.FALLBACK)
    tmp.deleteRecursively()

    val index = File(asrDir, MealCatalog.INDEX)
    ok("index.tsv var", index.isFile) { index.path }
    if (index.isFile) {
        val cat = MealCatalog.load(asrDir)
        ok("ilk meal varsayilan", cat.editions.first().id == MealCatalog.DEFAULT_ID && cat.editions.first().file == "meal.bin") {
            cat.editions.first().toString()
        }
        ok("id'ler tekil", cat.editions.map { it.id }.toSet().size == cat.editions.size)
        val listed = cat.editions.map { it.file }.toSet()
        val onDisk = File(asrDir, "meals").listFiles { f -> f.name.endsWith(".bin") }.orEmpty().map { "meals/${it.name}" }
        ok("dosyalar = index", onDisk.toSet() == listed - "meal.bin") { "disk=$onDisk index=$listed" }
        val base = MealLoader.load(File(asrDir, "meal.bin").path)
        for (e in cat.editions) {
            ok("${e.id} ad", e.name.isNotBlank())
            ok("${e.id} resolve", cat.resolve(e.id, asrDir) == e)
            val m = try {
                MealLoader.load(File(asrDir, e.file).path)
            } catch (ex: Exception) {
                ok("${e.id} acilir", false) { ex.toString() }
                continue
            }
            ok("${e.id} 6236 meal", m.mealCount == 6236) { "${m.mealCount}" }
            ok("${e.id} 114 sure", m.surahCount == 114) { "${m.surahCount}" }
            var empty = 0
            var merged = 0
            for (s in 1..114) {
                val info = m.getSurahInfo(s)
                val bi = base.getSurahInfo(s)
                if (info != bi) ok("${e.id} sure $s", false) { "$info / $bi" }
                for (a in 1..(bi?.ayahCount ?: 0)) {
                    val t = m.getMeal(s, a)
                    if (t.isNullOrEmpty()) empty++
                    else if (a > 1 && t == m.getMeal(s, a - 1)) merged++
                }
            }
            ok("${e.id} bos meal yok", empty == 0) { "$empty" }
            ok("${e.id} birlesik = index", merged == e.merged) { "$merged / ${e.merged}" }
            ok("${e.id} birlesik <= 100", merged <= 100) { "$merged" }
            m.close()
        }
        base.close()
    }
    for (f in fails) println("  HATA $f")
    println("meals: ${total - fails.size}/$total")
    return fails.size
}
