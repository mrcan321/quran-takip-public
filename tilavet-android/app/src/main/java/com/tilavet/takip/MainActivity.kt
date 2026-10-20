package com.tilavet.takip

import android.Manifest
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tilavet.takip.ui.components.SettingsSheet
import com.tilavet.takip.ui.screens.MainScreen
import com.tilavet.takip.ui.theme.LocalAppPalette
import com.tilavet.takip.ui.theme.TilavetTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)

        setContent {
            val viewModel: MainViewModel = viewModel()
            val state by viewModel.state.collectAsStateWithLifecycle()

            TilavetTheme(appTheme = state.settings.theme) {
                AppRoot(viewModel = viewModel)
            }
        }
    }
}

@Composable
private fun AppRoot(viewModel: MainViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val palette = LocalAppPalette.current

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { /* sonuç sessizce kabul */ }

    // Dinlerken / simulasyonda ekran kararmasin: kullanici ekrana dokunmadan takibi izliyor (namazda ve
    // kayitli sesi dinlerken). Durunca normal zaman asimina doner.
    val view = LocalView.current
    DisposableEffect(state.isListening) {
        view.keepScreenOn = state.isListening
        onDispose { view.keepScreenOn = false }
    }

    // Simulasyon: telefondan ses dosyasi sec (WAV; baska bicimde baslik okunamaz → ekranda hata)
    val wavPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument()
    ) { uri -> if (uri != null) viewModel.startSimulation(uri) }

    Box(modifier = Modifier.fillMaxSize().background(palette.bg)) {
        MainScreen(
            state = state,
            onToggleListening = {
                if (!state.isListening) {
                    permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                }
                viewModel.toggleListening()
            },
            onOpenSettings = { viewModel.openSettings() },
            onAsrTest = {
                permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                viewModel.runAsrTest()
            },
            onAlignerTest = { viewModel.runAlignerTest() },
            onFuzzyTest = { viewModel.runFuzzyTest() },
            onStateMachineTest = { viewModel.runStateMachineTest() },
            onLogExport = { viewModel.exportLog() },
            onEzanDismiss = { viewModel.dismissEzan() },
            onZikirDismiss = { viewModel.dismissZikir() },
            // Durum satirinin en saginda: hangi CI build'i / commit test ediliyor
            buildLabel = if (BuildConfig.CI_BUILD > 0) "#${BuildConfig.CI_BUILD} · ${BuildConfig.GIT_SHA}"
            else BuildConfig.GIT_SHA,
            onSimMenuOpen = { viewModel.refreshSimRecordings() },
            onSimRecording = { viewModel.startSimulation(it) },
            onSimPickFile = { wavPicker.launch(arrayOf("audio/*")) },
            onSimStop = { viewModel.toggleListening() },
        )

        if (state.showSettingsSheet) {
            SettingsSheet(
                settings = state.settings,
                onDismiss = { viewModel.closeSettings() },
                onTheme = { viewModel.setTheme(it) },
                onArabicSize = { viewModel.setArabicSize(it) },
                onMealSize = { viewModel.setMealSize(it) },
                onMotion = { viewModel.setMotion(it) },
                onIdleOpacity = { viewModel.setIdleOpacity(it) },
                onSkippedAyahTenths = { viewModel.setSkippedAyahTenths(it) },
                onTextHoldTenths = { viewModel.setTextHoldTenths(it) },
                glassesLink = state.glassesLink,
                onGlassesEnabled = { viewModel.setGlassesEnabled(it) },
                onGlassesArabic = { viewModel.setGlassesArabic(it) },
                onGlassesBigText = { viewModel.setGlassesBigText(it) },
                onGlassesTextPx = { viewModel.setGlassesTextPx(it) },
                onGlassesBigHeader = { viewModel.setGlassesBigHeader(it) },
                onGlassesFixedSize = { viewModel.setGlassesFixedSize(it) },
                onGlassesOnePage = { viewModel.setGlassesOnePage(it) },
                onGlassesOnePageMinPx = { viewModel.setGlassesOnePageMinPx(it) },
                onGlassesHideBlankHeader = { viewModel.setGlassesHideBlankHeader(it) },
                onGlassesHideStatus = { viewModel.setGlassesHideStatus(it) },
                onMinConfidence = { viewModel.setMinConfidence(it) },
                onMinConfidenceFirstLock = { viewModel.setMinConfidenceFirstLock(it) },
                onWindowSlack = { viewModel.setWindowSlack(it) },
                onAsrDecoder = { viewModel.setAsrDecoder(it) },
            )
        }
    }
}
