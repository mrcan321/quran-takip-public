package com.tilavet.takip.ui.components

import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AudioFile
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tilavet.takip.ui.theme.LocalAppPalette
import com.tilavet.takip.ui.theme.LocalAppStyle

/* ============================================================
 * Mic toggle button (sağ alt)
 * Zumrut: her zaman dolu zumrut (ana eylem) + ince altin halka; dinlerken altin dalga halkasi.
 * ============================================================ */
@Composable
fun MicButton(
    isListening: Boolean,
    motion: Float,
    onToggle: () -> Unit,
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val haptic = LocalHapticFeedback.current

    // Pulsing outer ring when listening
    val infinite = rememberInfiniteTransition(label = "micRing")
    val ringScale by infinite.animateFloat(
        initialValue = 1f,
        targetValue = 1.4f,
        animationSpec = infiniteRepeatable(
            animation = tween((2000 / motion.coerceAtLeast(0.001f)).toInt(), easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "scale"
    )
    val ringAlpha by infinite.animateFloat(
        initialValue = 0.5f,
        targetValue = 0f,
        animationSpec = infiniteRepeatable(
            animation = tween((2000 / motion.coerceAtLeast(0.001f)).toInt(), easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "alpha"
    )

    val clickable = Modifier.clickable(
        interactionSource = remember { MutableInteractionSource() },
        indication = null,
    ) {
        haptic.performHapticFeedback(HapticFeedbackType.LongPress)
        onToggle()
    }

    if (style.ornate) {
        Box(contentAlignment = Alignment.Center) {
            if (isListening && motion > 0f) {
                Box(
                    Modifier
                        .size(64.dp)
                        .scale(ringScale)
                        .border(1.5.dp, style.gold.copy(alpha = ringAlpha * 1.6f), CircleShape)
                )
            }
            Box(
                modifier = Modifier
                    .size(58.dp)
                    .shadow(10.dp, CircleShape, ambientColor = style.shadow, spotColor = style.shadow)
                    .background(Brush.verticalGradient(listOf(style.headerBottom, palette.accent)), CircleShape)
                    .border(1.dp, style.gold.copy(alpha = if (isListening) 0.95f else 0.6f), CircleShape)
                    .then(clickable),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = if (isListening) Icons.Filled.Stop else Icons.Filled.Mic,
                    contentDescription = "Başlat/Durdur",
                    tint = style.onHeader,
                    modifier = Modifier.size(24.dp)
                )
            }
        }
        return
    }

    Box(contentAlignment = Alignment.Center) {
        if (isListening && motion > 0f) {
            Box(
                Modifier
                    .size(64.dp)
                    .scale(ringScale)
                    .border(1.dp, palette.accent.copy(alpha = ringAlpha), CircleShape)
            )
        }

        Box(
            modifier = Modifier
                .size(56.dp)
                .background(
                    color = if (isListening) palette.accent else palette.bgElev,
                    shape = CircleShape,
                )
                .border(
                    width = 1.dp,
                    color = if (isListening) palette.accent else palette.borderStrong,
                    shape = CircleShape,
                )
                .then(clickable),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = if (isListening) Icons.Filled.Stop else Icons.Filled.Mic,
                contentDescription = "Başlat/Durdur",
                tint = if (isListening) palette.bg else palette.fg,
                modifier = Modifier.size(22.dp)
            )
        }
    }
}

/* ============================================================
 * Simulasyon butonu (mikrofonun solunda): kayitli WAV'i mikrofon gibi oynat.
 * Bosta → dosya ikonu (dokununca menu: son oturum kayitlari + telefondan sec);
 * simulasyon calisirken → vurgulu (mod gostergesi); durdurma buyuk butonda (dokunursa o da durdurur).
 * Zumrut: nane yesili daire (gorsellerdeki ikon zeminleri), calisirken dolu zumrut.
 * ============================================================ */
@Composable
fun SimButton(
    simActive: Boolean,
    onClick: () -> Unit,
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val haptic = LocalHapticFeedback.current
    val bg = when {
        style.ornate && simActive -> palette.accent
        style.ornate -> style.mint
        simActive -> palette.accent.copy(alpha = 0.18f)
        else -> palette.bgElev
    }
    val borderColor = when {
        style.ornate && simActive -> style.gold
        style.ornate -> style.gold.copy(alpha = 0.35f)
        simActive -> palette.accent
        else -> palette.borderStrong
    }
    val tint = when {
        style.ornate && simActive -> style.onHeader
        style.ornate -> palette.accent
        simActive -> palette.accent
        else -> palette.fgDim
    }
    Box(
        modifier = Modifier
            .size(44.dp)
            .background(color = bg, shape = CircleShape)
            .border(width = 1.dp, color = borderColor, shape = CircleShape)
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null,
            ) {
                haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                onClick()
            },
        contentAlignment = Alignment.Center
    ) {
        Icon(
            imageVector = Icons.Filled.AudioFile,
            contentDescription = if (simActive) "Simülasyonu durdur" else "Simülasyon (kayıtlı ses)",
            tint = tint,
            modifier = Modifier.size(18.dp)
        )
    }
}

/* ============================================================
 * Audio level bar — yatay ince çubuk (zumrutte zumrut → altin dolgu)
 * ============================================================ */
@Composable
fun AudioLevelBar(
    level: Float,
    modifier: Modifier = Modifier,
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val animated by animateFloatAsState(
        targetValue = level.coerceIn(0f, 1f),
        animationSpec = tween(150),
        label = "level"
    )

    if (style.ornate) {
        Box(
            modifier = modifier
                .height(4.dp)
                .background(palette.fgGhost, RoundedCornerShape(2.dp))
        ) {
            Box(
                Modifier
                    .fillMaxHeight()
                    .fillMaxWidth(animated)
                    .background(Brush.horizontalGradient(listOf(palette.accent, style.gold)), RoundedCornerShape(2.dp))
            )
        }
        return
    }

    Box(
        modifier = modifier
            .height(2.dp)
            .background(palette.fgGhost, RoundedCornerShape(1.dp))
    ) {
        Box(
            Modifier
                .fillMaxHeight()
                .fillMaxWidth(animated)
                .background(palette.accent, RoundedCornerShape(1.dp))
        )
    }
}

/* ============================================================
 * Ust bar ikon butonu. Zumrut: koyu bant uzerinde cam daire (beyaz %9 + ince altin hat), fildisi ikon.
 * ============================================================ */
@Composable
fun IconBtn(
    onClick: () -> Unit,
    contentDescription: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val haptic = LocalHapticFeedback.current

    val base = if (style.ornate) Modifier
        .size(30.dp)
        .background(Color.White.copy(alpha = 0.09f), CircleShape)
        .border(1.dp, style.gold.copy(alpha = 0.28f), CircleShape)
    else Modifier
        .size(32.dp)
        .border(1.dp, palette.border, RoundedCornerShape(8.dp))

    Box(
        modifier = base
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null,
            ) {
                haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                onClick()
            },
        contentAlignment = Alignment.Center
    ) {
        Icon(
            imageVector = icon,
            contentDescription = contentDescription,
            tint = if (style.ornate) style.onHeader.copy(alpha = 0.9f) else palette.fgDim,
            modifier = Modifier.size(16.dp),
        )
    }
}

/* ============================================================
 * Live dot — pulse ederken accent (zumrutte koyu bant uzerinde: altin isilti)
 * ============================================================ */
@Composable
fun LiveDot(isActive: Boolean, motion: Float) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val infinite = rememberInfiniteTransition(label = "dot")
    val pulseAlpha by infinite.animateFloat(
        initialValue = 1f,
        targetValue = 0.6f,
        animationSpec = infiniteRepeatable(
            animation = tween((1000 / motion.coerceAtLeast(0.001f)).toInt(), easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "dotPulse"
    )
    val on = if (style.ornate) style.glow else palette.accent
    val off = if (style.ornate) style.onHeaderDim.copy(alpha = 0.6f) else palette.fgFaded

    Box(
        Modifier
            .size(6.dp)
            .background(
                color = when {
                    isActive && motion > 0f -> on.copy(alpha = pulseAlpha)
                    isActive -> on
                    else -> off
                },
                shape = CircleShape,
            )
    )
}

/* ============================================================
 * Empty state (Kuran yuklenirken)
 * ============================================================ */
@Composable
fun EmptyState(modifier: Modifier = Modifier) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current

    if (style.ornate) {
        Column(
            modifier = modifier.padding(horizontal = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            BrandLogo(Modifier.size(132.dp).shadow(14.dp, CircleShape, ambientColor = style.hudGlow, spotColor = style.hudGlow))
            Spacer(Modifier.height(26.dp))
            Text(
                text = "Tilavet Takip",
                color = style.headerTop,
                fontSize = 30.sp,
                fontWeight = FontWeight.SemiBold,
                fontFamily = style.display,
            )
            Spacer(Modifier.height(10.dp))
            OrnamentDivider(style.gold, width = 140.dp)
            Spacer(Modifier.height(12.dp))
            Text(
                text = "Duyduğun ayeti anlamaya\nbir adım daha yaklaş.",
                color = palette.fgDim,
                fontFamily = style.body,
                fontSize = 15.sp,
                lineHeight = 22.sp,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(16.dp))
            Text(
                text = "BAŞLATMAK İÇİN MİKROFONA DOKUN",
                color = style.goldInk,
                fontFamily = style.label,
                fontWeight = FontWeight.SemiBold,
                fontSize = 10.sp,
                letterSpacing = 2.sp,
                textAlign = TextAlign.Center,
            )
        }
        return
    }

    Column(
        modifier = modifier.padding(horizontal = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            modifier = Modifier
                .size(56.dp)
                .border(1.dp, palette.borderStrong, CircleShape),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = Icons.Filled.Mic,
                contentDescription = null,
                tint = palette.fgFaded,
                modifier = Modifier.size(22.dp)
            )
        }
        Spacer(Modifier.height(28.dp))
        Text(
            text = "Tilavet Takip",
            color = palette.fg,
            fontSize = 22.sp,
            fontFamily = style.display,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            text = "BAŞLATMAK İÇİN MİKROFONA DOKUN",
            color = palette.fgFaded,
            fontFamily = style.label,
            fontSize = 10.sp,
            letterSpacing = 1.2.sp,
        )
    }
}
