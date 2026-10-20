package com.tilavet.takip.ui.theme

import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily

/**
 * Temalar. ZUMRUT (varsayilan, APK #30+): krem / zumrut yesili / altin, serif basliklar, cami kemeri ve silueti
 * susleri — "Namazda Anla" gorsellerinden ve marka metninden (sakin, manevi, modern; krem kagit zemin, derin orman
 * yesili, zeytin yesili, hafif altin, yumusak yesil isilti / yari saydam HUD kartlari, hafif Islami geometrik desen).
 * Digerleri eski (klasik) temalar, aynen duruyor.
 */
enum class AppTheme(val displayName: String, val isLight: Boolean) {
    ZUMRUT("Zümrüt", true),
    DARK("Karanlık", false),
    NIGHT("Gece", false),
    INK("Mürekkep", false),
    LIGHT("Gündüz", true),
    SEFA("Sefa", true),
    YESIM("Yeşim", false),
    BORDO("Bordo", false);

    companion object {
        val DEFAULT = ZUMRUT
        fun fromKey(key: String?): AppTheme = entries.find { it.name == key } ?: DEFAULT
    }
}

/**
 * Custom palette — Material3'ün dışında, bizim app'imize özel renkler.
 * Material3 ColorScheme yetersiz çünkü "fgDim", "fgFaded", "accentDim", "borderStrong" gibi nüanslarımız var.
 */
data class AppPalette(
    val bg: Color,
    val bgElev: Color,
    val bgCard: Color,
    val fg: Color,
    val fgDim: Color,
    val fgFaded: Color,
    val fgGhost: Color,
    val accent: Color,
    val accentDim: Color,
    val accentGlow: Color,
    val border: Color,
    val borderStrong: Color,
)

/**
 * Temanin renk disi karakteri: yazi tipleri ve susleme. Klasik temalar (eski 7 tema) [Styles.CLASSIC] ile eskisi
 * gibi cizilir; [ornate] temalar (ZUMRUT) koyu ust bant + cami silueti, kemerli sure basligi, okunan ayet karti,
 * altin ayraclar ve beyaz alt bar kullanir.
 */
data class AppStyle(
    /** Basliklar: sure adi, ust bant basligi, ayarlar basligi. */
    val display: FontFamily,
    /** Okuma metni: Turkce meal (zumrutte marka metni geregi okunakli sans-serif). */
    val body: FontFamily,
    /** Kucuk etiketler: durum satiri, ayet etiketi, alt bar, ayar etiketleri. */
    val label: FontFamily,
    /** Kucuk etiketlerin harf araligi carpani (Manrope buyuk harf etiketler daha genis aralikla guzel durur). */
    val labelTracking: Float = 1f,
    /** Meal yazi boyutu carpani (ayardaki boyut ayni gorunsun: Manrope, telefonda gorunen sistem fontundan iri). */
    val bodyScale: Float = 1f,
    val ornate: Boolean = false,
    // --- Sadece ornate temalarda kullanilir ---
    /** Altin: ince cizgiler, ayet sonu isareti, kemer ambleminin hatti, kucuk buyuk harf etiketler. */
    val gold: Color = Color.Unspecified,
    /** Altin etiket metni (krem zeminde okunur, daha koyu). */
    val goldInk: Color = Color.Unspecified,
    /** Ust bant (koyu zumrut) gradyani ustten alta. */
    val headerTop: Color = Color.Unspecified,
    val headerBottom: Color = Color.Unspecified,
    /** Ust bant uzerindeki yazi / ikon (fildisi) ve soluk hali (nane). */
    val onHeader: Color = Color.Unspecified,
    val onHeaderDim: Color = Color.Unspecified,
    /** Cami silueti (ust bantta, cok soluk). */
    val skyline: Color = Color.Unspecified,
    /** Gun batimi isiltisi (ust bandin sag ustu ve krem zeminin ustu). */
    val glow: Color = Color.Unspecified,
    /** Nane yesili yuvarlak ikon / etiket zemini. */
    val mint: Color = Color.Unspecified,
    /** Krem zemin gradyaninin alt rengi (ust = palette.bg). */
    val bgBottom: Color = Color.Unspecified,
    /** Kart golgesinin rengi (yesile calan, yumusak). */
    val shadow: Color = Color.Unspecified,
    /** Zeytin yesili: ikincil etiketler (okunmayan ayetin etiketi, alt bardaki slogan). */
    val olive: Color = Color.Unspecified,
    /** Okunan ayet kartinin yesil isiltisi (HUD) ve kartin ustteki yesil tonu. */
    val hudGlow: Color = Color.Unspecified,
    val hudTint: Color = Color.Unspecified,
)

object Styles {
    val CLASSIC = AppStyle(display = CormorantFamily, body = CormorantFamily, label = JetBrainsMonoFamily)

    val ZUMRUT = AppStyle(
        display = PlayfairFamily,
        body = ManropeFamily,
        label = ManropeFamily,
        labelTracking = 1.6f,
        bodyScale = 0.86f,
        ornate = true,
        gold = Color(0xFFC6A15B),
        goldInk = Color(0xFF9C7838),
        headerTop = Color(0xFF0E2A1F),
        headerBottom = Color(0xFF1A4433),
        onHeader = Color(0xFFF6F0E2),
        onHeaderDim = Color(0xFFA9C8B4),
        skyline = Color(0xFF2E6249),
        glow = Color(0xFFF0CF8E),
        mint = Color(0xFFE0ECE2),
        bgBottom = Color(0xFFF1E8D7),
        shadow = Color(0xFF173A2A),
        olive = Color(0xFF66733F),
        hudGlow = Color(0xFF2F7D4A),
        hudTint = Color(0xFFF1F7F0),
    )

    fun forTheme(theme: AppTheme): AppStyle = if (theme == AppTheme.ZUMRUT) ZUMRUT else CLASSIC
}

object Palettes {
    /** Krem kagit + zumrut + altin (varsayilan). */
    val ZUMRUT = AppPalette(
        bg = Color(0xFFF8F2E6), bgElev = Color(0xFFFFFDF8), bgCard = Color(0xFFEFE6D4),
        fg = Color(0xFF16231C), fgDim = Color(0xFF56645B),
        fgFaded = Color(0xFF9CA399), fgGhost = Color(0xFFE5DCCA),
        accent = Color(0xFF1D5A3D),
        accentDim = Color(0x3346916A), accentGlow = Color(0x99C6A15B),
        border = Color(0x1A8C7346), borderStrong = Color(0x338C7346),
    )

    val DARK = AppPalette(
        bg = Color(0xFF0A0A0A), bgElev = Color(0xFF141414), bgCard = Color(0xFF1A1A1A),
        fg = Color(0xFFF5F5F5), fgDim = Color(0xFF888888),
        fgFaded = Color(0xFF444444), fgGhost = Color(0xFF2A2A2A),
        accent = Color(0xFFD4A574),
        accentDim = Color(0x26D4A574), accentGlow = Color(0x4DD4A574),
        border = Color(0x0FFFFFFF), borderStrong = Color(0x1FFFFFFF),
    )

    val NIGHT = AppPalette(
        bg = Color(0xFF060818), bgElev = Color(0xFF0E1224), bgCard = Color(0xFF141832),
        fg = Color(0xFFE8EAF6), fgDim = Color(0xFF7882A8),
        fgFaded = Color(0xFF3D4566), fgGhost = Color(0xFF1A1F3A),
        accent = Color(0xFF6B9EFF),
        accentDim = Color(0x266B9EFF), accentGlow = Color(0x596B9EFF),
        border = Color(0x0FB4C8FF), borderStrong = Color(0x24B4C8FF),
    )

    val INK = AppPalette(
        bg = Color(0xFF000000), bgElev = Color(0xFF0C0C0C), bgCard = Color(0xFF141414),
        fg = Color(0xFFFFFFFF), fgDim = Color(0xFF999999),
        fgFaded = Color(0xFF555555), fgGhost = Color(0xFF1F1F1F),
        accent = Color(0xFFFFFFFF),
        accentDim = Color(0x14FFFFFF), accentGlow = Color(0x40FFFFFF),
        border = Color(0x12FFFFFF), borderStrong = Color(0x2EFFFFFF),
    )

    val LIGHT = AppPalette(
        bg = Color(0xFFFAFAFA), bgElev = Color(0xFFF0F0F0), bgCard = Color(0xFFE8E8E8),
        fg = Color(0xFF1A1A1A), fgDim = Color(0xFF666666),
        fgFaded = Color(0xFFAAAAAA), fgGhost = Color(0xFFD4D4D4),
        accent = Color(0xFFB8761E),
        accentDim = Color(0x21B8761E), accentGlow = Color(0x40B8761E),
        border = Color(0x12000000), borderStrong = Color(0x29000000),
    )

    val SEFA = AppPalette(
        bg = Color(0xFFF3EDE0), bgElev = Color(0xFFEDE5D3), bgCard = Color(0xFFE6DCC3),
        fg = Color(0xFF3A2F20), fgDim = Color(0xFF7A6A52),
        fgFaded = Color(0xFFB3A48A), fgGhost = Color(0xFFD8CDB3),
        accent = Color(0xFF8B5A2B),
        accentDim = Color(0x1F8B5A2B), accentGlow = Color(0x408B5A2B),
        border = Color(0x143A2F20), borderStrong = Color(0x2E3A2F20),
    )

    val YESIM = AppPalette(
        bg = Color(0xFF0C1A14), bgElev = Color(0xFF122620), bgCard = Color(0xFF18302A),
        fg = Color(0xFFEAF2EC), fgDim = Color(0xFF8AA896),
        fgFaded = Color(0xFF4A6357), fgGhost = Color(0xFF1F3530),
        accent = Color(0xFFC9A86A),
        accentDim = Color(0x26C9A86A), accentGlow = Color(0x52C9A86A),
        border = Color(0x0FC8E6D2), borderStrong = Color(0x24C8E6D2),
    )

    val BORDO = AppPalette(
        bg = Color(0xFF14080A), bgElev = Color(0xFF1F1014), bgCard = Color(0xFF2A161C),
        fg = Color(0xFFF5E6E8), fgDim = Color(0xFFB08488),
        fgFaded = Color(0xFF5E3A40), fgGhost = Color(0xFF2E1A20),
        accent = Color(0xFFD4AF37),
        accentDim = Color(0x26D4AF37), accentGlow = Color(0x59D4AF37),
        border = Color(0x0FFFC8C8), borderStrong = Color(0x24FFC8C8),
    )

    fun forTheme(theme: AppTheme): AppPalette = when (theme) {
        AppTheme.ZUMRUT -> ZUMRUT
        AppTheme.DARK -> DARK
        AppTheme.NIGHT -> NIGHT
        AppTheme.INK -> INK
        AppTheme.LIGHT -> LIGHT
        AppTheme.SEFA -> SEFA
        AppTheme.YESIM -> YESIM
        AppTheme.BORDO -> BORDO
    }
}

val LocalAppPalette = staticCompositionLocalOf { Palettes.ZUMRUT }
val LocalAppStyle = staticCompositionLocalOf { Styles.CLASSIC }
