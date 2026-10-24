package com.tilavet.takip

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tilavet.takip.ui.components.SettingsSheet
import com.tilavet.takip.ui.screens.MainScreen
import com.tilavet.takip.ui.theme.LocalAppPalette
import com.tilavet.takip.ui.theme.TilavetTheme
import com.tilavet.takip.util.PhoneControl

class MainActivity : ComponentActivity() {
    // Compose'taki viewModel() ile ayni ornek (ayni ViewModelStore)
    private val vm: MainViewModel by viewModels()

    // On plan servisi bildirimi (Android 13+); ardindan arka plan izni (iki pencere ust uste acilmasin)
    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) {
        if (!PhoneControl.isBackgroundUnrestricted(this)) PhoneControl.requestBackgroundUnrestricted(this)
    }

    companion object {
        /** Arka plan / bildirim izni bu surec icinde bir kez istenir (reddedilirse Ayarlar → ARKA PLANDA ÇALIŞMA uyarir). */
        private var askedPermissions = false
    }

    override fun onStart() {
        super.onStart()
        // Dinlerken on plan servisi arka planda baslatilamadiysa simdi ac (bkz. MainViewModel.onAppForeground)
        vm.onAppForeground()
        // Kullanici: "telefondaki app arka planda surekli acik kalabilsin; gerekirse izin istesin, arka plan izni istesin
        // yoksa uyarsin" → pil kisitlamasi muafiyeti (Android'in izin penceresi) + bildirim izni, acilista bir kez
        if (!askedPermissions) {
            askedPermissions = true
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
            ) {
                notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
            } else if (!PhoneControl.isBackgroundUnrestricted(this)) {
                PhoneControl.requestBackgroundUnrestricted(this)
            }
        }
    }

    override fun onStop() {
        vm.onAppBackground()
        super.onStop()
    }

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
            val context = LocalContext.current
            SettingsSheet(
                settings = state.settings,
                onDismiss = { viewModel.closeSettings() },
                onTheme = { viewModel.setTheme(it) },
                onArabicSize = { viewModel.setArabicSize(it) },
                onMealSize = { viewModel.setMealSize(it) },
                meals = state.meals,
                onMealId = { viewModel.setMealId(it) },
                onMotion = { viewModel.setMotion(it) },
                onIdleOpacity = { viewModel.setIdleOpacity(it) },
                onSkippedAyahTenths = { viewModel.setSkippedAyahTenths(it) },
                onTextHoldTenths = { viewModel.setTextHoldTenths(it) },
                bgUnrestricted = state.bgUnrestricted,
                onRequestBackground = { PhoneControl.requestBackgroundUnrestricted(context) },
                dndAccess = state.dndAccess,
                onMuteOnRecording = {
                    viewModel.setMuteOnRecording(it)
                    // tam sessiz icin Rahatsiz Etmeyin erisimi: acilirken yoksa sistem ayarina gotur
                    if (it && !state.dndAccess) PhoneControl.requestDndAccess(context)
                },
                onRequestDnd = { PhoneControl.requestDndAccess(context) },
                glassesDemo = state.glassesDemo,
                onGlassesDemo = { viewModel.setGlassesDemo(it) },
                glassesLink = state.glassesLink,
                onGlassesEnabled = { viewModel.setGlassesEnabled(it) },
                onGlassesArabic = { viewModel.setGlassesArabic(it) },
                onGlassesBigText = { viewModel.setGlassesBigText(it) },
                onGlassesTextPx = { viewModel.setGlassesTextPx(it) },
                onGlassesBigHeader = { viewModel.setGlassesBigHeader(it) },
                onGlassesFixedSize = { viewModel.setGlassesFixedSize(it) },
                onGlassesHideRakat = { viewModel.setGlassesHideRakat(it) },
                onGlassesFont = { viewModel.setGlassesFont(it) },
                onGlassesFontWeight = { viewModel.setGlassesFontWeight(it) },
                onGlassesOnePage = { viewModel.setGlassesOnePage(it) },
                onGlassesOnePageMinPx = { viewModel.setGlassesOnePageMinPx(it) },
                onGlassesHideBlankHeader = { viewModel.setGlassesHideBlankHeader(it) },
                onGlassesHideStatus = { viewModel.setGlassesHideStatus(it) },
                onGlassesMealLabel = { viewModel.setGlassesMealLabel(it) },
                onGlassesMealLabelGrow = { viewModel.setGlassesMealLabelGrow(it) },
                onGlassesHeaderAutoHide = { viewModel.setGlassesHeaderAutoHide(it) },
                onMinConfidence = { viewModel.setMinConfidence(it) },
                onMinConfidenceFirstLock = { viewModel.setMinConfidenceFirstLock(it) },
                onWindowSlack = { viewModel.setWindowSlack(it) },
                onAsrDecoder = { viewModel.setAsrDecoder(it) },
            )
        }
    }
}
