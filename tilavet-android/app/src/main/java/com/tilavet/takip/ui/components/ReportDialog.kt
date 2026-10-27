package com.tilavet.takip.ui.components

import android.annotation.SuppressLint
import android.net.Uri
import android.webkit.WebView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.IosShare
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.tilavet.takip.ui.theme.LocalAppPalette
import com.tilavet.takip.ui.theme.LocalAppStyle
import java.io.File

/**
 * Namaz raporu (ana ekran → 📄): son 3 kayitta okunan ayetler — util/NamazReportBuilder'in urettigi HTML tam ekranda
 * (WebView, internetsiz; dosya cacheDir/reports). Ustte paylas (HTML dosyasi; tarayicida / baska telefonda da acilir) ve kapat.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun ReportDialog(file: File, onShare: () -> Unit, onDismiss: () -> Unit) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Column(modifier = Modifier.fillMaxSize().background(palette.bg).systemBarsPadding()) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().background(palette.bgElev).padding(start = 16.dp, end = 4.dp),
            ) {
                Text(
                    "NAMAZ RAPORU",
                    color = palette.accent,
                    fontFamily = style.label,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 13.sp,
                    letterSpacing = style.tracking(1f).sp,
                    modifier = Modifier.weight(1f),
                )
                IconButton(onClick = onShare) {
                    Icon(Icons.Filled.IosShare, contentDescription = "Raporu paylaş", tint = palette.fgDim)
                }
                IconButton(onClick = onDismiss) {
                    Icon(Icons.Filled.Close, contentDescription = "Kapat", tint = palette.fgDim)
                }
            }
            // Sayfa bir kez yuklenir (update yok): ana ekran sik yeniden cizilir (ses seviyesi), WebView bastan yuklenip
            // kaydirma yeri kaybolmasin; yeni rapor dosyasi = yeni WebView (key)
            key(file) { AndroidView(
                factory = { ctx ->
                    WebView(ctx).apply {
                        settings.allowFileAccess = true      // cacheDir/reports/namaz-raporu.html
                        settings.javaScriptEnabled = false
                        settings.builtInZoomControls = true
                        settings.displayZoomControls = false
                        loadUrl(Uri.fromFile(file).toString())
                    }
                },
                modifier = Modifier.fillMaxWidth().weight(1f),
            ) }
        }
    }
}
