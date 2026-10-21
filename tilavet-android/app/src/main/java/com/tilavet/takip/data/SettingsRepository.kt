package com.tilavet.takip.data

import android.content.Context
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import com.tilavet.takip.audio.TextHold
import com.tilavet.takip.glasses.GlassesState
import com.tilavet.takip.ui.theme.AppTheme
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "tilavet_settings")

data class AppSettings(
    val theme: AppTheme = AppTheme.DEFAULT,
    val arabicSize: Int = 26,
    val mealSize: Int = 21,
    // Ayarlar → MEAL: secili meal (data/MealCatalog, scripts/build_meals.py; varsayilan Ali Bulac)
    val mealId: String = MealCatalog.DEFAULT_ID,
    val motion: Float = 1f,        // 0, 0.5, 1
    val idleOpacity: Int = 42,     // 0-80
    // Takip ayni surede birden fazla ayet ileri atlayinca (ör. 1:2 → 1:5) aradaki her ayetin ekranda
    // kalma suresi, 0.1 sn biriminde (0-20 → 0-2 sn; 0 = kapali, dogrudan atlar)
    val skippedAyahTenths: Int = 5,
    // Even Realities G2 gozluk koprusu (127.0.0.1:18765, bkz. glasses/GlassesBridge) ve gozlukte Arapca goruntu
    val glassesEnabled: Boolean = false,
    val glassesArabic: Boolean = false,
    // Gozlukte sadece meal, mumkun oldugunca buyuk yazi (eklenti cizer); false = gozluk fontu (baslik + 9 satir)
    val glassesBigText: Boolean = true,
    // Buyuk yazida en kucuk punto (px, 30-80): kisa metin daha buyuk cizilir, sigmayan meal sayfalara bolunur
    val glassesTextPx: Int = GlassesState.DEFAULT_TEXT_PX,
    // Gozlukte ustte sure / ayet adi + rekat (gozlugun kendi yazisiyla, aninda degisir) — butun yazi duzenlerinde
    val glassesBigHeader: Boolean = true,
    // Ust bilgide rekat / durus gizli: sadece "Sure: ayet"
    val glassesHideRakat: Boolean = false,
    // Buyuk yazida sabit punto (glassesTextPx): kisa metin buyutulmez, uzun meal kucultulmez — sayfalara bolunur
    val glassesFixedSize: Boolean = false,
    // Buyuk yazida uzun meal sayfalanmaz, punto gerektigi kadar kuculur (GlassesState.onePage)
    val glassesOnePage: Boolean = false,
    // Tek ekranda en kucuk punto (px, 12-40): bunda da sigmayan meal sayfalanir
    val glassesOnePageMinPx: Int = GlassesState.DEFAULT_ONE_PAGE_PX,
    // Ses kesilince (bos gozluk ekrani) ustteki rekat / durus satirini da gizle (GlassesState.blankHeader = !bu);
    // varsayilan gizli (kullanici: "ekran bos kaldiginda ust bilgi durmasin")
    val glassesHideBlankHeader: Boolean = true,
    // Gozlukte "Dinleme kapalı" / "Dinleniyor" gibi durum yazilari yerine bos ekran (GlassesState.hideStatus)
    val glassesHideStatus: Boolean = false,
    // Ses kesildikten sonra okunan ayet metni bu kadar (onda bir sn, 0-100) ekranda kalir — bkz. audio/TextHold
    val textHoldTenths: Int = TextHold.DEFAULT_TENTHS,
    // === TUNER (debug) ===
    val minConfidence: Int = 50,           // 0-100, normal match esik (kilitli iken)
    val minConfidenceFirstLock: Int = 70,  // 0-100, ilk kilit / kilit-terk esik
    val windowSlack: Int = 2,              // 0-5, aligner pencere genisligi (yukseldikce yavas)
    val asrDecoder: String = "RNNT",       // "RNNT" | "CTC" — AsrDecoder.fromKey
)

class SettingsRepository(private val context: Context) {

    private object Keys {
        // APK #30: yeni varsayilan tema (Zumrut) eski kurulumlarda da bir kere gelsin diye yeni anahtar —
        // eski "theme" anahtari (secilmis eski tema) okunmuyor; kullanici ayarlardan istedigi temaya donebilir.
        val THEME = stringPreferencesKey("theme_v2")
        val ARABIC_SIZE = intPreferencesKey("arabic_size")
        val MEAL_SIZE = intPreferencesKey("meal_size")
        val MEAL_ID = stringPreferencesKey("meal_id")
        val MOTION = floatPreferencesKey("motion")
        val IDLE_OPACITY = intPreferencesKey("idle_opacity")
        val SKIPPED_AYAH_TENTHS = intPreferencesKey("skipped_ayah_tenths")
        val GLASSES_ENABLED = booleanPreferencesKey("glasses_enabled")
        val GLASSES_ARABIC = booleanPreferencesKey("glasses_arabic")
        val GLASSES_BIG_TEXT = booleanPreferencesKey("glasses_big_text")
        val GLASSES_TEXT_PX = intPreferencesKey("glasses_text_px")
        val GLASSES_BIG_HEADER = booleanPreferencesKey("glasses_big_header")
        val GLASSES_FIXED_SIZE = booleanPreferencesKey("glasses_fixed_size")
        val GLASSES_HIDE_RAKAT = booleanPreferencesKey("glasses_hide_rakat")
        val GLASSES_ONE_PAGE = booleanPreferencesKey("glasses_one_page")
        val GLASSES_ONE_PAGE_MIN_PX = intPreferencesKey("glasses_one_page_min_px")
        val GLASSES_HIDE_BLANK_HEADER = booleanPreferencesKey("glasses_hide_blank_header")
        val GLASSES_HIDE_STATUS = booleanPreferencesKey("glasses_hide_status")
        val TEXT_HOLD_TENTHS = intPreferencesKey("text_hold_tenths")
        val MIN_CONFIDENCE = intPreferencesKey("min_confidence")
        val MIN_CONFIDENCE_FIRST_LOCK = intPreferencesKey("min_confidence_first_lock")
        val WINDOW_SLACK = intPreferencesKey("window_slack")
        val ASR_DECODER = stringPreferencesKey("asr_decoder")
    }

    val settings: Flow<AppSettings> = context.dataStore.data.map { prefs ->
        AppSettings(
            theme = AppTheme.fromKey(prefs[Keys.THEME]),
            arabicSize = prefs[Keys.ARABIC_SIZE] ?: 26,
            mealSize = prefs[Keys.MEAL_SIZE] ?: 21,
            mealId = prefs[Keys.MEAL_ID] ?: MealCatalog.DEFAULT_ID,
            motion = prefs[Keys.MOTION] ?: 1f,
            idleOpacity = prefs[Keys.IDLE_OPACITY] ?: 42,
            skippedAyahTenths = prefs[Keys.SKIPPED_AYAH_TENTHS] ?: 5,
            glassesEnabled = prefs[Keys.GLASSES_ENABLED] ?: false,
            glassesArabic = prefs[Keys.GLASSES_ARABIC] ?: false,
            glassesBigText = prefs[Keys.GLASSES_BIG_TEXT] ?: true,
            glassesTextPx = prefs[Keys.GLASSES_TEXT_PX] ?: GlassesState.DEFAULT_TEXT_PX,
            glassesBigHeader = prefs[Keys.GLASSES_BIG_HEADER] ?: true,
            glassesFixedSize = prefs[Keys.GLASSES_FIXED_SIZE] ?: false,
            glassesHideRakat = prefs[Keys.GLASSES_HIDE_RAKAT] ?: false,
            glassesOnePage = prefs[Keys.GLASSES_ONE_PAGE] ?: false,
            glassesOnePageMinPx = prefs[Keys.GLASSES_ONE_PAGE_MIN_PX] ?: GlassesState.DEFAULT_ONE_PAGE_PX,
            glassesHideBlankHeader = prefs[Keys.GLASSES_HIDE_BLANK_HEADER] ?: true,
            glassesHideStatus = prefs[Keys.GLASSES_HIDE_STATUS] ?: false,
            textHoldTenths = prefs[Keys.TEXT_HOLD_TENTHS] ?: TextHold.DEFAULT_TENTHS,
            minConfidence = prefs[Keys.MIN_CONFIDENCE] ?: 50,
            minConfidenceFirstLock = prefs[Keys.MIN_CONFIDENCE_FIRST_LOCK] ?: 70,
            windowSlack = prefs[Keys.WINDOW_SLACK] ?: 2,
            asrDecoder = prefs[Keys.ASR_DECODER] ?: "RNNT",
        )
    }

    suspend fun setTheme(theme: AppTheme) {
        context.dataStore.edit { it[Keys.THEME] = theme.name }
    }

    suspend fun setArabicSize(size: Int) {
        context.dataStore.edit { it[Keys.ARABIC_SIZE] = size }
    }

    suspend fun setMealSize(size: Int) {
        context.dataStore.edit { it[Keys.MEAL_SIZE] = size }
    }

    suspend fun setMealId(id: String) {
        context.dataStore.edit { it[Keys.MEAL_ID] = id }
    }

    suspend fun setMotion(motion: Float) {
        context.dataStore.edit { it[Keys.MOTION] = motion }
    }

    suspend fun setIdleOpacity(opacity: Int) {
        context.dataStore.edit { it[Keys.IDLE_OPACITY] = opacity }
    }

    suspend fun setSkippedAyahTenths(value: Int) {
        context.dataStore.edit { it[Keys.SKIPPED_AYAH_TENTHS] = value.coerceIn(0, 20) }
    }

    suspend fun setGlassesEnabled(value: Boolean) {
        context.dataStore.edit { it[Keys.GLASSES_ENABLED] = value }
    }

    suspend fun setGlassesArabic(value: Boolean) {
        context.dataStore.edit { it[Keys.GLASSES_ARABIC] = value }
    }

    suspend fun setGlassesBigText(value: Boolean) {
        context.dataStore.edit { it[Keys.GLASSES_BIG_TEXT] = value }
    }

    suspend fun setGlassesTextPx(value: Int) {
        context.dataStore.edit {
            it[Keys.GLASSES_TEXT_PX] = value.coerceIn(GlassesState.MIN_TEXT_PX, GlassesState.MAX_TEXT_PX)
        }
    }

    suspend fun setGlassesBigHeader(value: Boolean) {
        context.dataStore.edit { it[Keys.GLASSES_BIG_HEADER] = value }
    }

    suspend fun setGlassesFixedSize(value: Boolean) {
        context.dataStore.edit { it[Keys.GLASSES_FIXED_SIZE] = value }
    }

    suspend fun setGlassesHideRakat(value: Boolean) {
        context.dataStore.edit { it[Keys.GLASSES_HIDE_RAKAT] = value }
    }

    suspend fun setGlassesOnePage(value: Boolean) {
        context.dataStore.edit { it[Keys.GLASSES_ONE_PAGE] = value }
    }

    suspend fun setGlassesOnePageMinPx(value: Int) {
        context.dataStore.edit {
            it[Keys.GLASSES_ONE_PAGE_MIN_PX] = value.coerceIn(GlassesState.MIN_ONE_PAGE_PX, GlassesState.MAX_ONE_PAGE_PX)
        }
    }

    suspend fun setGlassesHideBlankHeader(value: Boolean) {
        context.dataStore.edit { it[Keys.GLASSES_HIDE_BLANK_HEADER] = value }
    }

    suspend fun setGlassesHideStatus(value: Boolean) {
        context.dataStore.edit { it[Keys.GLASSES_HIDE_STATUS] = value }
    }

    suspend fun setTextHoldTenths(value: Int) {
        context.dataStore.edit { it[Keys.TEXT_HOLD_TENTHS] = value.coerceIn(0, TextHold.MAX_TENTHS) }
    }

    suspend fun setMinConfidence(value: Int) {
        context.dataStore.edit { it[Keys.MIN_CONFIDENCE] = value }
    }

    suspend fun setMinConfidenceFirstLock(value: Int) {
        context.dataStore.edit { it[Keys.MIN_CONFIDENCE_FIRST_LOCK] = value }
    }

    suspend fun setWindowSlack(value: Int) {
        context.dataStore.edit { it[Keys.WINDOW_SLACK] = value }
    }

    suspend fun setAsrDecoder(value: String) {
        context.dataStore.edit { it[Keys.ASR_DECODER] = value }
    }
}
