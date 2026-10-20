package com.tilavet.takip.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.googlefonts.Font
import androidx.compose.ui.text.googlefonts.GoogleFont
import androidx.compose.ui.text.font.Font as ResourceFont
import androidx.compose.ui.unit.sp
import com.tilavet.takip.R

/**
 * Google Fonts üzerinden dinamik font yükleme.
 * İlk açılışta indirir, sonra cache'ler. Offline'da fallback serif/monospace kullanır.
 *
 * Cormorant Garamond → Türkçe meal (edebi serif)
 * JetBrains Mono     → UI/teknik öğeler
 *
 * Kuran metni ise APK'ya GOMULU (res/font/kfgqpc_hafs.ttf) — bkz. QuranFontFamily.
 */

private val provider = GoogleFont.Provider(
    providerAuthority = "com.google.android.gms.fonts",
    providerPackage = "com.google.android.gms",
    certificates = R.array.com_google_android_gms_fonts_certs
)

private val cormorantGoogleFont = GoogleFont("Cormorant Garamond")
private val jetbrainsMonoGoogleFont = GoogleFont("JetBrains Mono")

val CormorantFamily = FontFamily(
    Font(googleFont = cormorantGoogleFont, fontProvider = provider, weight = FontWeight.Normal),
    Font(googleFont = cormorantGoogleFont, fontProvider = provider, weight = FontWeight.Medium),
    Font(googleFont = cormorantGoogleFont, fontProvider = provider, weight = FontWeight.SemiBold),
)

/**
 * Kuran metni: KFGQPC HAFS Uthmanic Script (Kral Fahd Mushaf Basim Kompleksi, v0.18 — Tarteel / quran.com'daki
 * font). APK'ya gomulu: eskiden Google Fonts'tan indirilen Amiri Quran telefonda hic yuklenmiyordu (namazda
 * internet yok), ekranda sistem fontu cikiyordu. Lisans (fontun icinde): ucretsiz kullanim/kopyalama/dagitim;
 * satilamaz, degistirilemez → dosya degistirilmeden (alt kume yok) kopyalandi.
 * Ayet numarasi bu fontta Arapca rakamlarla yazilinca sus cerceveli ayet isareti olarak cizilir.
 */
val QuranFontFamily = FontFamily(ResourceFont(R.font.kfgqpc_hafs, FontWeight.Normal))

/**
 * KFGQPC ayni punto degerinde onceki (sistem Naskh) fonttan ~%16 dar ciziyor (14:2'nin ilk 8 kelimesi,
 * 26 sp: Noto Naskh 832 px, KFGQPC 717 px). Ayarlardaki Arapca boyut ayni gorunsun diye bu katsayiyla buyutulur.
 */
const val QURAN_FONT_SCALE = 1.15f

val JetBrainsMonoFamily = FontFamily(
    Font(googleFont = jetbrainsMonoGoogleFont, fontProvider = provider, weight = FontWeight.Normal),
    Font(googleFont = jetbrainsMonoGoogleFont, fontProvider = provider, weight = FontWeight.Medium),
)

/*
 * Zumrut temasinin yazi tipleri — APK'ya GOMULU (res/font, Google Fonts'tan statik TTF'ler, SIL Open Font License
 * 1.1, dosyalar degistirilmedi; telif satirlari + lisans metni res/raw/ofl_fonts.txt). Google Fonts saglayicisi
 * telefonda yuklenmiyor (namazda internet yok) — bu tema sistem fontuna dusmesin diye gomulu.
 *   Playfair Display → basliklar (zarif, yuksek kontrastli serif)
 *   Manrope          → meal (400, marka metni: govdede cok okunakli modern sans-serif) + etiketler / butonlar
 *                      (500-700, buyuk harf + genis aralik)
 * Turkce karakterlerin hepsi (ğ ş ı İ ç ö ü â î û) iki fontta da var.
 */
val PlayfairFamily = FontFamily(
    ResourceFont(R.font.playfair_500, FontWeight.Medium),
    ResourceFont(R.font.playfair_600, FontWeight.SemiBold),
    ResourceFont(R.font.playfair_700, FontWeight.Bold),
)

val ManropeFamily = FontFamily(
    ResourceFont(R.font.manrope_400, FontWeight.Normal),
    ResourceFont(R.font.manrope_500, FontWeight.Medium),
    ResourceFont(R.font.manrope_600, FontWeight.SemiBold),
    ResourceFont(R.font.manrope_700, FontWeight.Bold),
)

/**
 * Temanin Material tipografisi: fontFamily verilmeyen Text'ler (ör. ezan penceresindeki Turkce) de temaya uyar.
 * Klasik temalarda eskisiyle ayni (Cormorant / JetBrains Mono).
 */
fun typographyFor(style: AppStyle): Typography = Typography(
    bodyLarge = TextStyle(
        fontFamily = style.body,
        fontSize = 17.sp,
        fontWeight = FontWeight.Normal,
        lineHeight = 26.sp,
    ),
    titleLarge = TextStyle(
        fontFamily = style.display,
        fontSize = 22.sp,
        fontWeight = FontWeight.Medium,
        letterSpacing = (-0.01).sp,
    ),
    labelMedium = TextStyle(
        fontFamily = style.label,
        fontSize = 11.sp,
        letterSpacing = 0.6.sp,
    ),
    labelSmall = TextStyle(
        fontFamily = style.label,
        fontSize = 10.sp,
        letterSpacing = 0.6.sp,
    ),
)
