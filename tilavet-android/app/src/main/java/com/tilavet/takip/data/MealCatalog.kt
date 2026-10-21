package com.tilavet.takip.data

import java.io.File

/**
 * Secilebilir mealler (Ayarlar → MEAL) — scripts/build_meals.py'nin yazdigi asr/meals/index.tsv.
 *
 * Satir: id \t dosya (asr/'a gore: "meal.bin" ya da "meals/<id>.bin") \t birlesik ayet \t ad \t aciklama; "#" yorum.
 * Sira = Ayarlar'daki sira, ilki varsayilan (Ali Bulac, meal.bin). Meal eklemek icin sadece build_meals.py'deki liste
 * degisir; uygulama kodu degismez. Android'siz (JVM'de test edilir).
 */
class MealCatalog private constructor(val editions: List<MealEdition>) {

    data class MealEdition(
        val id: String,
        val name: String,
        val desc: String,
        /** asr/ klasorune gore dosya yolu. */
        val file: String,
        /** Ayni suredeki onceki ayetle birebir ayni meal sayisi (ayetler tek cumlede cevrilmis). */
        val merged: Int,
    )

    /** id → baski; bilinmeyen id ya da dosyasi olmayan baski → varsayilan (ilk satir). */
    fun resolve(id: String?, asrDir: File? = null): MealEdition {
        val hit = editions.firstOrNull { it.id == id }
        if (hit != null && (asrDir == null || File(asrDir, hit.file).isFile)) return hit
        return editions.first()
    }

    companion object {
        const val INDEX = "meals/index.tsv"
        const val DEFAULT_ID = "bulac"

        /** index.tsv yoksa / bozuksa sadece varsayilan meal (meal.bin) — eski APK'nin asset'leriyle de calissin. */
        val FALLBACK = MealEdition(DEFAULT_ID, "Ali Bulaç", "Kur'an-ı Kerim ve Türkçe Anlamı", "meal.bin", 0)

        fun parse(text: String): MealCatalog {
            val list = ArrayList<MealEdition>()
            for (line in text.lineSequence()) {
                if (line.isBlank() || line.startsWith("#")) continue
                val f = line.split('\t')
                if (f.size < 5 || f[0].isBlank() || f[1].isBlank()) continue
                if (list.any { it.id == f[0] }) continue
                list += MealEdition(id = f[0], name = f[3], desc = f[4], file = f[1], merged = f[2].toIntOrNull() ?: 0)
            }
            if (list.isEmpty()) list += FALLBACK
            return MealCatalog(list)
        }

        /** asr/meals/index.tsv'yi oku (asrDir = filesDir/asr). */
        fun load(asrDir: File): MealCatalog {
            val f = File(asrDir, INDEX)
            return try {
                if (f.isFile) parse(f.readText(Charsets.UTF_8)) else MealCatalog(listOf(FALLBACK))
            } catch (_: Exception) {
                MealCatalog(listOf(FALLBACK))
            }
        }
    }
}
