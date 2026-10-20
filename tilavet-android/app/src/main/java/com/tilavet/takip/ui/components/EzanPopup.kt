package com.tilavet.takip.ui.components

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.layout.positionInParent
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tilavet.takip.session.EzanView
import com.tilavet.takip.ui.theme.LocalAppPalette
import com.tilavet.takip.ui.theme.LocalAppStyle
import com.tilavet.takip.ui.theme.QURAN_FONT_SCALE
import com.tilavet.takip.ui.theme.QuranFontFamily
import kotlinx.coroutines.launch
import kotlin.math.abs
import kotlin.math.roundToInt
import kotlin.math.sign

/** Kart genisliginin bu kadari kadar yana surukleyip birakinca kart atilir (kapanir). */
private const val SWIPE_DISMISS_FRACTION = 0.3f

/** Kirmizi kapatma butonu rengi (tema bagimsiz). */
private val CloseRed = Color(0xFFD93A3A)

/**
 * Ezan / kamet penceresi: tum cumleler (Arapca + Turkce anlami), okunan cumle vurgulu.
 * Okunmus cumleler normal, sonrakiler soluk. Okunan cumle gorunur kalacak sekilde kendiliginden kayar.
 *
 * Kapatma: sag ustteki kirmizi carpi, ya da karti saga/sola surukleyip birakmak (kart donerek ucar ve
 * kaybolur; az surukleyince yerine yaylanir). Ezan/kamet bitince ViewModel kendisi kapatir.
 */
@Composable
fun EzanPopup(view: EzanView, onDismiss: () -> Unit, modifier: Modifier = Modifier) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val scope = rememberCoroutineScope()
    val offsetX = remember { Animatable(0f) }
    var widthPx by remember { mutableStateOf(1f) }
    var gone by remember { mutableStateOf(false) }

    fun flyAway(direction: Float) {
        if (gone) return
        gone = true
        scope.launch {
            offsetX.animateTo(direction * widthPx * 1.4f, tween(durationMillis = 260))
            onDismiss()
        }
    }

    val shape = RoundedCornerShape(20.dp)
    Column(
        modifier = modifier
            .onSizeChanged { widthPx = it.width.toFloat().coerceAtLeast(1f) }
            .offset { IntOffset(offsetX.value.roundToInt(), 0) }
            .graphicsLayer {
                val f = (abs(offsetX.value) / widthPx).coerceIn(0f, 1f)
                alpha = 1f - 0.7f * f
                rotationZ = 10f * offsetX.value / widthPx    // yana atilan kart gibi hafif doner
            }
            .then(
                // Zumrut: yesil isiltili HUD karti (okunan ayet karti gibi)
                if (style.ornate) Modifier.shadow(18.dp, shape, ambientColor = style.hudGlow, spotColor = style.hudGlow)
                else Modifier.shadow(14.dp, shape)
            )
            .background(palette.bgElev, shape)
            .border(1.dp, palette.accentGlow, shape)
            .pointerInput(Unit) {
                detectHorizontalDragGestures(
                    onDragEnd = {
                        if (abs(offsetX.value) > widthPx * SWIPE_DISMISS_FRACTION) flyAway(sign(offsetX.value))
                        else scope.launch { offsetX.animateTo(0f, spring()) }
                    },
                    onDragCancel = { scope.launch { offsetX.animateTo(0f, spring()) } },
                ) { change, dragAmount ->
                    change.consume()
                    scope.launch { offsetX.snapTo(offsetX.value + dragAmount) }
                }
            }
            .padding(start = 14.dp, end = 10.dp, top = 10.dp, bottom = 12.dp),
    ) {
        // Baslik + kirmizi carpi (zumrutte basta altin kemer amblemi)
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (style.ornate) {
                ArchEmblem(style.gold, Modifier.size(15.dp, 18.dp))
                Spacer(Modifier.width(8.dp))
            }
            Text(
                view.title,
                fontFamily = style.label, fontSize = 12.sp,
                fontWeight = if (style.ornate) FontWeight.Bold else null,
                color = palette.accent, letterSpacing = style.tracking(1f).sp,
            )
            Spacer(Modifier.weight(1f))
            Box(
                modifier = Modifier
                    .size(32.dp)
                    .background(CloseRed, CircleShape)
                    .clickable { flyAway(1f) },
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Filled.Close, contentDescription = "Kapat", tint = Color.White, modifier = Modifier.size(20.dp))
            }
        }
        Spacer(Modifier.height(4.dp))

        val scroll = rememberScrollState()
        val curIdx = view.rows.indexOf(view.current)
        var curTop by remember { mutableStateOf(-1) }
        LaunchedEffect(curIdx, curTop) {
            if (curTop >= 0) scroll.animateScrollTo((curTop - 60).coerceAtLeast(0))
        }
        Column(modifier = Modifier.fillMaxWidth().weight(1f, fill = false).verticalScroll(scroll)) {
            view.rows.forEachIndexed { i, phrase ->
                val isCurrent = i == curIdx
                val past = curIdx >= 0 && i < curIdx
                val arabicColor = when {
                    isCurrent -> palette.accent
                    past -> palette.fgDim
                    else -> palette.fgFaded
                }
                val turkishColor = when {
                    isCurrent -> palette.fg
                    past -> palette.fgDim
                    else -> palette.fgFaded
                }
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(end = 4.dp, top = 2.dp, bottom = 2.dp)
                        .background(if (isCurrent) palette.accentDim else Color.Transparent, RoundedCornerShape(12.dp))
                        .then(if (isCurrent) Modifier.onGloballyPositioned { curTop = it.positionInParent().y.toInt() } else Modifier)
                        .padding(horizontal = 10.dp, vertical = if (isCurrent) 8.dp else 4.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text(
                        phrase.arabic,
                        modifier = Modifier.fillMaxWidth(),
                        style = TextStyle(
                            fontFamily = QuranFontFamily,
                            fontSize = (if (isCurrent) 27 else 19).sp * QURAN_FONT_SCALE,
                            color = arabicColor,
                            textAlign = TextAlign.Center,
                            textDirection = TextDirection.Rtl,
                        ),
                    )
                    Text(
                        phrase.turkish,
                        modifier = Modifier.fillMaxWidth(),
                        fontSize = if (isCurrent) 15.sp else 12.sp,
                        color = turkishColor,
                        textAlign = TextAlign.Center,
                    )
                }
            }
        }
    }
}
