package com.tilavet.takip.ui.theme

import android.app.Activity
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

/* Tema verisi (AppTheme, AppPalette, AppStyle, Palettes, Styles) Palette.kt'de — Android'e bagli degil,
 * masaustu Compose duzeneginde de derlenir. Burada sadece pencere (sistem cubuklari) ve Material sarmalayici. */

/** Material3 için minimal ColorScheme — biz çoğunlukla AppPalette kullanıyoruz */
private fun colorSchemeFor(palette: AppPalette, isLight: Boolean): ColorScheme {
    val base = if (isLight) lightColorScheme() else darkColorScheme()
    return base.copy(
        background = palette.bg,
        surface = palette.bgElev,
        onBackground = palette.fg,
        onSurface = palette.fg,
        primary = palette.accent,
        onPrimary = palette.bg,
    )
}

@Composable
fun TilavetTheme(
    appTheme: AppTheme = AppTheme.DEFAULT,
    content: @Composable () -> Unit
) {
    val palette = Palettes.forTheme(appTheme)
    val style = Styles.forTheme(appTheme)
    val view = LocalView.current

    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            val insets = WindowCompat.getInsetsController(window, view)
            if (style.ornate) {
                // Ustte koyu zumrut bant (acik renk ikonlar), altta beyaz alt bar (koyu ikonlar)
                window.statusBarColor = style.headerTop.toArgb()
                window.navigationBarColor = palette.bgElev.toArgb()
                insets.isAppearanceLightStatusBars = false
                insets.isAppearanceLightNavigationBars = true
            } else {
                window.statusBarColor = palette.bg.toArgb()
                window.navigationBarColor = palette.bg.toArgb()
                insets.isAppearanceLightStatusBars = appTheme.isLight
                insets.isAppearanceLightNavigationBars = appTheme.isLight
            }
        }
    }

    CompositionLocalProvider(LocalAppPalette provides palette, LocalAppStyle provides style) {
        MaterialTheme(
            colorScheme = colorSchemeFor(palette, appTheme.isLight),
            typography = typographyFor(style),
            content = content
        )
    }
}
