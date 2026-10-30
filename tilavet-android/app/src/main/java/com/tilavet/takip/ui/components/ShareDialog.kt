package com.tilavet.takip.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.tilavet.takip.report.ReportHtml
import com.tilavet.takip.ui.theme.LocalAppPalette
import com.tilavet.takip.ui.theme.LocalAppStyle
import com.tilavet.takip.util.SessionRecording
import java.util.Locale

/**
 * 📤 Kayitlari paylas: en yeniden eskiye son 30 oturum (ses + oturum log'u, util/RecordingCatalog), asagi kayan liste,
 * coklu secim; secilenler (+ istenirse uygulama log'u / logcat) tek paylasimla Drive, e-posta ya da baska uygulamaya.
 * Acilista en son kayit secili (eski 📤 davranisi: son kayit + log). Kullanici (30.10).
 *
 * [recordings] null = liste hazirlaniyor.
 */
@Composable
fun ShareDialog(
    recordings: List<SessionRecording>?,
    onShare: (selected: List<SessionRecording>, includeLogcat: Boolean) -> Unit,
    onDismiss: () -> Unit,
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val selected = remember { mutableStateListOf<String>() }
    var logcat by remember { mutableStateOf(true) }
    var initialized by remember { mutableStateOf(false) }
    LaunchedEffect(recordings) {
        if (!initialized && recordings != null) {
            recordings.firstOrNull()?.let { selected.add(it.stamp) }
            initialized = true
        }
    }
    val shape = RoundedCornerShape(20.dp)
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Column(
            modifier = Modifier
                .fillMaxWidth(0.94f)
                .heightIn(max = 680.dp)
                .background(palette.bgElev, shape)
                .border(1.dp, if (style.ornate) style.gold.copy(alpha = 0.55f) else palette.borderStrong, shape)
                .padding(vertical = 16.dp),
        ) {
            Text(
                text = "KAYITLARI PAYLAŞ",
                fontFamily = style.label,
                fontWeight = FontWeight.Bold,
                fontSize = 13.sp,
                letterSpacing = style.tracking(1.2f).sp,
                color = if (style.ornate) style.goldInk else palette.accent,
                modifier = Modifier.padding(horizontal = 20.dp),
            )
            Spacer(Modifier.height(6.dp))
            Text(
                text = "En yeniden eskiye son 30 kayıt (ses + oturum log'u). Birden çok seçebilirsiniz; seçtikleriniz " +
                    "Drive, e-posta ya da başka bir uygulamaya gönderilir.",
                fontFamily = style.body,
                fontSize = 12.sp,
                lineHeight = 17.sp,
                color = palette.fgDim,
                modifier = Modifier.padding(horizontal = 20.dp),
            )
            Spacer(Modifier.height(10.dp))
            CheckRow(
                checked = logcat,
                title = "Uygulama log'u (logcat)",
                subtitle = "Hata ayıklama için uygulamanın şu anki günlüğü",
                onToggle = { logcat = !logcat },
            )
            Box(Modifier.fillMaxWidth().padding(horizontal = 20.dp).height(1.dp).background(palette.border))
            when {
                recordings == null -> Box(
                    modifier = Modifier.fillMaxWidth().height(120.dp),
                    contentAlignment = Alignment.Center,
                ) { CircularProgressIndicator(color = palette.accent) }
                recordings.isEmpty() -> Text(
                    text = "Henüz kayıt yok. Mikrofonla dinlenen her oturum burada listelenir.",
                    fontFamily = style.body,
                    fontSize = 13.sp,
                    color = palette.fgDim,
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 24.dp),
                )
                else -> LazyColumn(modifier = Modifier.fillMaxWidth().weight(1f, fill = false)) {
                    items(recordings, key = { it.stamp }) { r ->
                        CheckRow(
                            checked = r.stamp in selected,
                            title = r.startMs?.let { ReportHtml.dateLabel(it) } ?: r.stamp,
                            subtitle = describe(r),
                            onToggle = { if (r.stamp in selected) selected.remove(r.stamp) else selected.add(r.stamp) },
                        )
                    }
                }
            }
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().padding(start = 12.dp, end = 16.dp, top = 12.dp),
            ) {
                if (!recordings.isNullOrEmpty()) {
                    val all = selected.size == recordings.size
                    DialogButton(if (all) "HİÇBİRİ" else "TÜMÜ", primary = false) {
                        selected.clear()
                        if (!all) selected.addAll(recordings.map { it.stamp })
                    }
                }
                Spacer(Modifier.weight(1f))
                DialogButton("İPTAL", primary = false, onClick = onDismiss)
                Spacer(Modifier.width(8.dp))
                val chosen = recordings.orEmpty().filter { it.stamp in selected }
                val enabled = chosen.isNotEmpty() || logcat
                DialogButton(
                    text = if (chosen.isEmpty()) "PAYLAŞ" else "PAYLAŞ (${chosen.size})",
                    primary = true,
                    enabled = enabled,
                ) { onShare(chosen, logcat) }
            }
        }
    }
}

/** "12 dk 05 sn · ses 23,4 MB · log" */
private fun describe(r: SessionRecording): String {
    val parts = mutableListOf<String>()
    r.durationSec?.let { parts += "%d dk %02d sn".format(Locale.ROOT, it / 60, it % 60) }
    r.wav?.let { parts += "ses " + "%.1f MB".format(Locale("tr"), it.bytes / 1_048_576.0) }
    when {
        r.wav == null -> parts += "sadece log (ses dosyası yok)"
        r.log != null -> parts += "log"
        else -> parts += "log yok"
    }
    return parts.joinToString(" · ")
}

@Composable
private fun CheckRow(checked: Boolean, title: String, subtitle: String, onToggle: () -> Unit) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onToggle)
            .padding(start = 8.dp, end = 20.dp, top = 4.dp, bottom = 4.dp),
    ) {
        Checkbox(
            checked = checked,
            onCheckedChange = { onToggle() },
            colors = CheckboxDefaults.colors(
                checkedColor = palette.accent,
                uncheckedColor = palette.fgDim,
                checkmarkColor = palette.bg,
            ),
        )
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = title,
                fontFamily = style.body,
                fontWeight = FontWeight.SemiBold,
                fontSize = 14.sp,
                color = palette.fg,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = subtitle,
                fontFamily = style.body,
                fontSize = 12.sp,
                color = palette.fgDim,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun DialogButton(text: String, primary: Boolean, enabled: Boolean = true, onClick: () -> Unit) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val shape = RoundedCornerShape(12.dp)
    val bg = when {
        !primary -> palette.bgElev
        enabled -> palette.accent
        else -> palette.fgGhost
    }
    Box(
        contentAlignment = Alignment.Center,
        modifier = Modifier
            .background(bg, shape)
            .then(if (primary) Modifier else Modifier.border(1.dp, palette.border, shape))
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 10.dp),
    ) {
        Text(
            text = text,
            fontFamily = style.label,
            fontWeight = FontWeight.Bold,
            fontSize = 12.sp,
            letterSpacing = style.tracking(0.8f).sp,
            color = if (primary) palette.bg else palette.fgDim,
        )
    }
}
