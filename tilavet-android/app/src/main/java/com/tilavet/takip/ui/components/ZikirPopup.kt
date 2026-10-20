package com.tilavet.takip.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tilavet.takip.session.NamazZikri
import com.tilavet.takip.ui.theme.LocalAppPalette
import com.tilavet.takip.ui.theme.LocalAppStyle
import com.tilavet.takip.ui.theme.QURAN_FONT_SCALE
import com.tilavet.takip.ui.theme.QuranFontFamily

/**
 * Namaz zikri karti (rükünler arasi: tekbir, semiallah, rabbena, selam, namaz sonu duasi — bkz. ZikirTracker):
 * Arapca + okunus + Turkce anlami. Ezan/kamet penceresiyle ayni yerde ve ayni gorunumde, ama tek cumle ve kisa sureli
 * (ViewModel birkac saniye sonra kapatir). Dokununca ya da carpiyla kapanir.
 */
@Composable
fun ZikirPopup(zikir: NamazZikri, onDismiss: () -> Unit, modifier: Modifier = Modifier) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val shape = RoundedCornerShape(20.dp)
    Column(
        modifier = modifier
            .then(
                // Zumrut: yesil isiltili HUD karti (ezan penceresi gibi)
                if (style.ornate) Modifier.shadow(18.dp, shape, ambientColor = style.hudGlow, spotColor = style.hudGlow)
                else Modifier.shadow(14.dp, shape)
            )
            .background(palette.bgElev, shape)
            .border(1.dp, palette.accentGlow, shape)
            .clickable { onDismiss() }
            .padding(start = 14.dp, end = 10.dp, top = 10.dp, bottom = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (style.ornate) {
                ArchEmblem(style.gold, Modifier.size(15.dp, 18.dp))
                Spacer(Modifier.width(8.dp))
            }
            Text(
                zikir.title,
                fontFamily = style.label, fontSize = 12.sp,
                fontWeight = if (style.ornate) FontWeight.Bold else null,
                color = palette.accent, letterSpacing = style.tracking(1f).sp,
            )
            Spacer(Modifier.weight(1f))
            Box(
                modifier = Modifier
                    .size(26.dp)
                    .background(palette.accentDim, CircleShape)
                    .clickable { onDismiss() },
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Filled.Close, contentDescription = "Kapat", tint = palette.fgDim, modifier = Modifier.size(16.dp))
            }
        }
        Spacer(Modifier.height(4.dp))
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(palette.accentDim, RoundedCornerShape(12.dp))
                .padding(horizontal = 10.dp, vertical = 8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                zikir.arabic,
                modifier = Modifier.fillMaxWidth(),
                style = TextStyle(
                    fontFamily = QuranFontFamily,
                    fontSize = (if (zikir == NamazZikri.DUA) 21 else 27).sp * QURAN_FONT_SCALE,
                    color = palette.accent,
                    textAlign = TextAlign.Center,
                    textDirection = TextDirection.Rtl,
                ),
            )
            Text(
                zikir.reading,
                modifier = Modifier.fillMaxWidth(),
                fontSize = 13.sp,
                fontStyle = FontStyle.Italic,
                color = palette.fgDim,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(2.dp))
            Text(
                zikir.turkish,
                modifier = Modifier.fillMaxWidth(),
                fontSize = 15.sp,
                color = palette.fg,
                textAlign = TextAlign.Center,
            )
        }
    }
}
