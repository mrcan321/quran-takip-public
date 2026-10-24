#!/usr/bin/env python3
"""G2 eklentisini (tilavet-android/app/src/main/assets/g2) Even Hub simulatorunde uctan uca dener.

Uygulamanin kendi koprusu (glasses/GlassesBridge, tests/jvm `glasses-serve`) 127.0.0.1:18765'te calisir, senaryodaki
GlassesState'leri sirayla yayinlar; simulator (@evenrealities/evenhub-simulator, Xvfb altinda) eklentiyi acar.
Her adimda gozluk ekrani (576x288 PNG) kaydedilir, istenirse dokunmatik girdi gonderilir; sonunda simulator
konsolunda hata aranir.

  --mode same   gelistirici modu gibi: sayfa dogrudan kopruden (http://127.0.0.1:18765/)
  --mode cross  .ehpk gibi: sayfa baska kaynaktan (python http.server), kopruye cross-origin istek (CORS)
  --mode engel  .ehpk + Even uygulamasi kopruye fetch'i engelliyor (telefonda goruldu): eklenti goruntu yoklamasiyla
                kopruyu bulup sayfayi dogrudan kopruden acmali (konsolda "dogrudan kopruden" + "kopru bagli")

Gereken: Xvfb (xvfb-run), libwebkit2gtk-4.1, simulator ikilisi (npm @evenrealities/sim-linux-x64), JDK + tests/jvm
derlenmis (gradle installDist). Cikis kodu: konsolda hata / bos ekran varsa 1.
"""
import argparse
import json
import re
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
G2_DIR = REPO / "tilavet-android" / "app" / "src" / "main" / "assets" / "g2"
FONT_DIR = REPO / "tilavet-android" / "app" / "src" / "main" / "res" / "font"
JVM_BIN = REPO / "tests" / "jvm" / "build" / "install" / "tilavet-jvm-tests" / "bin" / "tilavet-jvm-tests"
AUTO = 9898

# Ayetel Kursi (KFGQPC yazimi, MushafData.displayText ile ayni donusum) — Arapca goruntu sayfalamasi icin uzun ayet
AYETEL_KURSI_AR = (
    "ٱللَّهُ لَآ إِلَٰهَ إِلَّا هُوَ ٱلۡحَيُّ ٱلۡقَيُّومُۚ لَا تَأۡخُذُهُۥ سِنَةٞ وَلَا نَوۡمٞۚ لَّهُۥ مَا فِي ٱلسَّمَٰوَٰتِ وَمَا فِي "
    "ٱلۡأَرۡضِۗ مَن ذَا ٱلَّذِي يَشۡفَعُ عِندَهُۥٓ إِلَّا بِإِذۡنِهِۦۚ يَعۡلَمُ مَا بَيۡنَ أَيۡدِيهِمۡ وَمَا خَلۡفَهُمۡۖ وَلَا يُحِيطُونَ "
    "بِشَيۡءٖ مِّنۡ عِلۡمِهِۦٓ إِلَّا بِمَا شَآءَۚ وَسِعَ كُرۡسِيُّهُ ٱلسَّمَٰوَٰتِ وَٱلۡأَرۡضَۖ وَلَا يَـُٔودُهُۥ حِفۡظُهُمَاۚ وَهُوَ "
    "ٱلۡعَلِيُّ ٱلۡعَظِيمُ ٢٥٥"
)
AYETEL_KURSI_TR = (
    "Allah, O'ndan başka ilah yoktur; diridir, kaimdir. O'nu uyuklama ve uyku tutmaz. Göklerde ve yerde ne varsa "
    "hepsi O'nundur. O'nun izni olmaksızın O'nun Katında şefaatte bulunacak kimdir? O, önlerindekini ve "
    "arkalarındakini bilir. (Onlar ise) Dilediği kadarının dışında, O'nun ilminden hiç bir şeyi kavrayıp-kuşatamazlar. "
    "O'nun kürsüsü, bütün gökleri ve yeri kaplayıp-kuşatmıştır. Onların korunması O'na güç gelmez. O, pek yücedir, "
    "pek büyüktür."
)
# Uzun meal (sayfalama): Bakara 282'nin uzunlugunda ornek metin
LONG_TR = " ".join([
    "Ey iman edenler, belirli bir süre için birbirinize borçlandığınız zaman, onu yazın.",
    "Bir yazıcı aranızda adaletle yazsın. Yazıcı, Allah'ın kendisine öğrettiği gibi yazmaktan kaçınmasın, yazsın.",
    "Borçlu olan da yazdırsın ve Rabbi olan Allah'tan sakınsın ve ondan hiçbir şey eksiltmesin.",
    "Eğer borçlu, aklı ermeyen ya da zayıf biri ise veya yazdırmaya gücü yetmiyorsa, velisi adaletle yazdırsın.",
    "Erkeklerinizden iki de şahit tutun; eğer iki erkek değilse, rıza göstereceğiniz şahitlerden bir erkek ve iki kadın",
    "olsun; biri unutursa diğeri ona hatırlatsın. Şahitler çağırıldıkları zaman kaçınmasınlar.",
    "Küçük veya büyük olsun, onu süresine kadar yazmaktan üşenmeyin. Bu, Allah Katında adalete daha uygun,",
    "şahitlik için daha sağlam ve şüpheye düşmemeniz için daha elverişlidir. Ancak aranızda devredeceğiniz peşin",
    "bir ticaret olursa, onu yazmamanızda size bir günah yoktur. Alışveriş yaptığınız zaman da şahit tutun.",
    "Yazıcıya da, şahide de zarar verilmesin. Eğer bunu yaparsanız, şüphesiz bu, sizin için bir fısktır.",
    "Allah'tan korkup-sakının. Allah size öğretiyor. Allah, her şeyi bilendir.",
])

BASE = dict(listening=True, status="Dinleniyor", rakat="1. REKÂT · KIYAM", bigText=False)
# Buyuk yazi (varsayilan): ustte sure / ayet satiri (gozlugun yazisi) + meal sigan en buyuk puntoda, 4 goruntu karosu
BIG = dict(BASE, bigText=True)
# Ayarlar → G2'DE SURE / AYET ADI: KAPALI — ekranin tamami meal
BIGN = dict(BIG, bigHeader=False)
KURSI = dict(surah=2, ayah=255, surahName="Bakara", surahAyahCount=286, meal=AYETEL_KURSI_TR)
FATIHA5 = dict(surah=1, ayah=5, surahName="Fâtiha", surahAyahCount=7, progress=0.5,
               meal="(Rabbimiz) Ancak Sana ibadet eder ve yalnızca Senden yardım dileriz.")
# adim adi → bu adimda gozluge giden karo sayisi siniri (konsoldaki "aktarim:" satirlari)
MAX_TILES = {
    # ADAY → kilit: sadece baslik degisir (gozlugun yazisi), buyuk yazi karolari yeniden gitmemeli
    "buyuk_aday_kilit": 0,
    # sabit yazi boyutunda blok ustten: 2 satirlik kisa metin sadece ust karolarda, alt karolar (zaten bos) gitmez
    "sabit_tekbir": 2,
}
# yazi tipi / kalinlik degisince (ayni ayet) gozluge en az bu kadar karo gitmeli: ekran aninda yeni fontla cizilir
MIN_TILES = {"font_atkinson_ince": 1, "font_atkinson_cok_kalin": 1, "font_lexend_kalin": 1, "font_inter_normal": 1,
             "font_manrope_geri": 1,
             # demo: cerceve 4 karonun hepsinde → ilk demo ekrani 4 karo; yazi tipi / boyutu degisince yeniden cizilir
             "demo_4_buyuk": 4, "demo_4_atkinson_64": 1, "demo_4_inter_30": 1,
             # mealde ayet adi: ayni ayet, yazi degisti → yeniden cizilir
             "ayet_adi_basta": 1, "ayet_adi_sonda": 1}
# bilerek bombos ekran (ust bilgi / durum yazisi gizli): gozluk goruntusunde cizili piksel OLMAMALI
EXPECT_EMPTY = {"bos_ustsuz", "durum_gizli_bosta", "durum_gizli_dinleniyor"}


def scenario(arabic):
    s = [
        ("buyuk_bosta", dict(BIG, listening=False, status="Hazır"), [], 3.0),
        ("buyuk_dinleniyor", dict(BIG, rakat=""), [], 2.5),
        ("buyuk_kevser_kisa", dict(BIG, surah=108, ayah=2, surahName="Kevser", surahAyahCount=3, progress=1.0,
                                   meal="Şu halde Rabbin için namaz kıl ve kurban kes."), [], 2.5),
        ("buyuk_aday", dict(BIG, **FATIHA5, tentative=True), [], 2.5),
        ("buyuk_aday_kilit", dict(BIG, **FATIHA5), [], 2.5),
        ("buyuk_kursi_basi", dict(BIG, **KURSI, progress=0.1), [], 2.5),
        ("buyuk_kursi_kaydir", dict(BIG, **KURSI, progress=0.1), ["down"], 2.0),
        ("buyuk_kursi_sonu", dict(BIG, **KURSI, progress=0.95), [], 2.5),
        ("buyuk_uzun_orta", dict(BIG, surah=2, ayah=282, surahName="Bakara", surahAyahCount=286, progress=0.5,
                                 meal=LONG_TR), [], 2.5),
        ("buyuk_tekbir", dict(BIG, noteTitle="TEKBİR", noteReading="Allâhu ekber", noteTurkish="Allah en büyüktür"),
         [], 2.5),
        ("buyuk_rekat_gizli", dict(BIG, **KURSI, progress=0.1, hideRakat=True), [], 2.5),
        # Ayarlar → YAZI KÜÇÜLECEKSE ÜST BİLGİYİ GİZLE: ust bilgi yaziyi kucultuyorsa ekranin tamami meal (duzen big)
        ("ust_oto_kursi", dict(BIG, **KURSI, progress=0.1, headerAutoHide=True), [], 3.0),
        ("ust_oto_kevser", dict(BIG, surah=108, ayah=2, surahName="Kevser", surahAyahCount=3, progress=1.0,
                                meal="Şu halde Rabbin için namaz kıl ve kurban kes.", headerAutoHide=True), [], 3.0),
        # Ayarlar → G2 MEALDE AYET ADI: BAŞTA / SONDA (SATIR ARTSA DA EKLE acik → her durumda eklenir)
        ("ayet_adi_basta", dict(BIG, surah=108, ayah=2, surahName="Kevser", surahAyahCount=3, progress=1.0,
                                meal="Şu halde Rabbin için namaz kıl ve kurban kes.", mealLabel="start",
                                mealLabelGrow=True), [], 2.5),
        ("ayet_adi_sonda", dict(BIG, surah=108, ayah=2, surahName="Kevser", surahAyahCount=3, progress=1.0,
                                meal="Şu halde Rabbin için namaz kıl ve kurban kes.", mealLabel="end",
                                mealLabelGrow=True), [], 2.5),
        # Ayarlar → G2 YAZI TİPİ / KALINLIĞI (sadece gozluk): her degisimde ekran yeni fontla yeniden cizilmeli (karo gider)
        ("font_atkinson_ince", dict(BIG, **KURSI, progress=0.1, bigFont="atkinson", bigWeight=300), [], 3.0),
        ("font_atkinson_cok_kalin", dict(BIG, **KURSI, progress=0.1, bigFont="atkinson", bigWeight=800), [], 2.5),
        ("font_lexend_kalin", dict(BIG, **KURSI, progress=0.1, bigFont="lexend", bigWeight=700), [], 3.0),
        ("font_inter_normal", dict(BIG, **KURSI, progress=0.1, bigFont="inter", bigWeight=500), [], 3.0),
        ("font_inter_kisa", dict(BIG, surah=108, ayah=2, surahName="Kevser", surahAyahCount=3, progress=1.0,
                                 meal="Şu halde Rabbin için namaz kıl ve kurban kes.", bigFont="inter", bigWeight=500),
         [], 2.5),
        ("font_manrope_geri", dict(BIG, **KURSI, progress=0.1), [], 2.5),
        # Ayarlar → G2 YAZI BOYUTU (en kucuk punto): kucuk / buyuk / en buyuk (kisa meal de 2 dengeli sayfa)
        ("buyuk_boyut_30", dict(BIG, **KURSI, progress=0.1, textPx=30), [], 2.5),
        ("buyuk_boyut_64", dict(BIG, **KURSI, progress=0.1, textPx=64), [], 2.5),
        ("buyuk_boyut_80", dict(BIG, surah=108, ayah=2, surahName="Kevser", surahAyahCount=3, progress=1.0,
                                textPx=80, meal="Şu halde Rabbin için namaz kıl ve kurban kes."), [], 2.5),
        # hizli ardisik ekranlar (ara ayetler): eskisinin kalan karolari birakilir, son ekran tam gorunmeli
        ("buyuk_hizli", [dict(BIG, **KURSI, progress=0.1), dict(BIG, **KURSI, progress=0.95),
                         dict(BIG, surah=2, ayah=256, surahName="Bakara", surahAyahCount=286, progress=0.2,
                              meal="Dinde zorlama yoktur. Gerçekten doğruluk sapıklıktan apaçık ayrılmıştır.")], [], 3.0),
        # baslik kapali: tum ekran meal, aday sonuk yazi, birden cok sayfada sag kenarda sayfa cubugu
        ("basliksiz_kursi", dict(BIGN, **KURSI, progress=0.1), [], 3.0),
        ("basliksiz_aday", dict(BIGN, **FATIHA5, tentative=True), [], 2.5),
        ("basliksiz_tekbir", dict(BIGN, noteTitle="TEKBİR", noteReading="Allâhu ekber", noteTurkish="Allah en büyüktür"),
         [], 2.5),
        # Ayarlar → G2 SABİT YAZI BOYUTU: kisa metin de uzun meal de ayardaki puntoda (48 px), blok ustten
        ("sabit_kursi", dict(BIG, **KURSI, progress=0.1, fixedSize=True), [], 2.5),
        ("sabit_kevser", dict(BIG, surah=108, ayah=2, surahName="Kevser", surahAyahCount=3, progress=1.0, fixedSize=True,
                              meal="Şu halde Rabbin için namaz kıl ve kurban kes."), [], 2.5),
        ("sabit_tekbir", dict(BIG, noteTitle="TEKBİR", noteReading="Allâhu ekber", noteTurkish="Allah en büyüktür",
                              fixedSize=True), [], 2.5),
        # Ayarlar → G2 AYETİ TEK EKRANA SIĞDIR: Bakara 2:282 (en uzun meal) tek sayfada, kucuk puntoda
        ("tek_sayfa_uzun", dict(BIG, surah=2, ayah=282, surahName="Bakara", surahAyahCount=286, progress=0.5,
                                meal=LONG_TR, onePage=True, onePageMinPx=12), [], 3.0),
        ("tek_sayfa_kursi_basliksiz", dict(BIGN, **KURSI, progress=0.5, onePage=True), [], 3.0),
        # Ayarlar → G2 TEK EKRAN EN KÜÇÜK YAZI 20 (varsayilan): Bakara 2:282 bu sinirda sigmaz → en az sayfa, 2. sayfa
        ("tek_sayfa_sinir_20", dict(BIG, surah=2, ayah=282, surahName="Bakara", surahAyahCount=286, progress=0.9,
                                    meal=LONG_TR, onePage=True, onePageMinPx=20), [], 3.0),
        # ses kesildi (zamm bitti, rukû): ayet metni kalkar, ustte rekat / durus (goruntu karolari yeniden kurulumla silinir)
        ("bos_rukû", dict(BIG, **KURSI, blank=True, blankHeader=True, rakat="1. REKÂT · RÜKÛ / SECDE"), [], 2.5),
        # Ayarlar → G2 BOŞ EKRANDA ÜST BİLGİYİ GİZLE (varsayilan): ekran bombos
        ("bos_ustsuz", dict(BIG, **KURSI, blank=True, blankHeader=False, rakat="1. REKÂT · RÜKÛ / SECDE"), [], 2.5),
        ("bos_sonra_okuma", dict(BIG, surah=108, ayah=2, surahName="Kevser", surahAyahCount=3, progress=1.0,
                                 meal="Şu halde Rabbin için namaz kıl ve kurban kes."), [], 2.5),
        # Ayarlar → G2 DURUM YAZISINI GİZLE: "Dinleme kapalı" / "Dinleniyor" yerine bos ekran; ayet gelince meal
        ("durum_gizli_bosta", dict(BIG, listening=False, status="Hazır", hideStatus=True), [], 2.5),
        ("durum_gizli_dinleniyor", dict(BIG, rakat="", hideStatus=True), [], 2.5),
        ("durum_gizli_ayet", dict(BIG, surah=108, ayah=2, surahName="Kevser", surahAyahCount=3, progress=1.0,
                                  meal="Şu halde Rabbin için namaz kıl ve kurban kes.", hideStatus=True), [], 2.5),

        # Ayarlar → G2 DEMO: cerceve + numarali satirlar (dinleme kapaliyken de); yazi tipi / boyutu degisince aninda
        ("demo_4_buyuk", dict(BIG, listening=False, status="Hazır", demo=4), [], 3.0),
        ("demo_1_buyuk", dict(BIG, listening=False, status="Hazır", demo=1), [], 2.5),
        ("demo_4_atkinson_64", dict(BIG, listening=False, status="Hazır", demo=4, bigFont="atkinson", textPx=64), [], 3.0),
        ("demo_4_inter_30", dict(BIG, listening=False, status="Hazır", demo=4, bigFont="inter", bigWeight=500, textPx=30),
         [], 3.0),
        ("demo_kapat", dict(BIG, listening=False, status="Hazır"), [], 2.5),

        ("bosta", dict(listening=False, status="Hazır", bigText=False), [], 2.5),
        ("dinleniyor", dict(BASE, rakat=""), [], 2.0),
        ("kamet", dict(BASE, rakat="", status="Kamet · Fatiha bekleniyor", noteTitle="KAMET",
                       noteReading="Kad kâmeti's-salâh", noteTurkish="Namaz başladı"), [], 2.0),
        ("fatiha_1_2", dict(BASE, surah=1, ayah=2, surahName="Fâtiha", surahAyahCount=7, progress=1.0,
                            meal="Hamd, alemlerin Rabbi olan Allah'a aittir."), [], 2.0),
        ("aday_1_5", dict(BASE, surah=1, ayah=5, surahName="Fâtiha", surahAyahCount=7, tentative=True, progress=0.5,
                          meal="(Rabbimiz) Ancak Sana ibadet eder ve yalnızca Senden yardım dileriz."), [], 2.0),
        ("uzun_basi", dict(BASE, surah=2, ayah=282, surahName="Bakara", surahAyahCount=286, progress=0.1,
                           meal=LONG_TR), [], 2.0),
        ("uzun_kaydir_asagi", dict(BASE, surah=2, ayah=282, surahName="Bakara", surahAyahCount=286, progress=0.1,
                                   meal=LONG_TR), ["down"], 1.5),
        ("uzun_ilerleme", dict(BASE, surah=2, ayah=282, surahName="Bakara", surahAyahCount=286, progress=0.9,
                               meal=LONG_TR), [], 2.0),
        ("tekbir", dict(BASE, rakat="1. REKÂT · RÜKÛ / SECDE", noteTitle="TEKBİR", noteReading="Allâhu ekber",
                        noteTurkish="Allah en büyüktür"), [], 2.0),
        # Ayarlar → G2 ÜST BİLGİ: KAPALI gozlugun kendi yazisinda da: baslik yok, 10 satir meal
        ("normal_basliksiz_uzun", dict(BASE, surah=2, ayah=282, surahName="Bakara", surahAyahCount=286, progress=0.1,
                                       meal=LONG_TR, bigHeader=False), [], 2.0),
        # Ayarlar → G2 REKÂT BİLGİSİNİ GİZLE: baslikta sadece "Fâtiha: 2"
        ("demo_4_normal", dict(BASE, listening=False, status="Hazır", demo=4), [], 2.5),
        ("demo_2_normal", dict(BASE, listening=False, status="Hazır", demo=2), [], 2.0),
        ("normal_rekat_gizli", dict(BASE, surah=1, ayah=2, surahName="Fâtiha", surahAyahCount=7, progress=1.0,
                                    meal="Hamd, alemlerin Rabbi olan Allah'a aittir.", hideRakat=True), [], 2.0),
        ("normal_ayet_adi_sonda", dict(BASE, surah=1, ayah=2, surahName="Fâtiha", surahAyahCount=7, progress=1.0,
                                       meal="Hamd, alemlerin Rabbi olan Allah'a aittir.", mealLabel="end"), [], 2.0),
    ]
    if arabic:
        s += [
            ("ar_kevser", dict(BASE, rakat="2. REKÂT · KIYAM", surah=108, ayah=1, surahName="Kevser", surahAyahCount=3,
                               progress=1.0, meal="Şüphesiz Biz sana Kevser'i verdik.",
                               arabic="إِنَّآ أَعۡطَيۡنَٰكَ ٱلۡكَوۡثَرَ ١", showArabic=True), [], 4.0),
            ("ar_kursi_basi", dict(BASE, surah=2, ayah=255, surahName="Bakara", surahAyahCount=286, progress=0.05,
                                   meal=AYETEL_KURSI_TR, arabic=AYETEL_KURSI_AR, showArabic=True), [], 3.0),
            ("ar_kursi_sonu", dict(BASE, surah=2, ayah=255, surahName="Bakara", surahAyahCount=286, progress=0.95,
                                   meal=AYETEL_KURSI_TR, arabic=AYETEL_KURSI_AR, showArabic=True), [], 3.0),
            ("ar_tekbir", dict(BASE, noteTitle="TEKBİR", noteReading="Allâhu ekber", noteTurkish="Allah en büyüktür",
                               showArabic=True), [], 2.5),
            # basliksiz Arapca: bant en ustte, altinda 6 satir meal
            ("ar_basliksiz_kursi", dict(BASE, surah=2, ayah=255, surahName="Bakara", surahAyahCount=286, progress=0.05,
                                        meal=AYETEL_KURSI_TR, arabic=AYETEL_KURSI_AR, showArabic=True, bigHeader=False),
             [], 3.0),
            ("ar_kapat", dict(BASE, surah=108, ayah=2, surahName="Kevser", surahAyahCount=3, progress=1.0,
                              meal="Şu halde Rabbin için namaz kıl ve kurban kes.", showArabic=False), [], 3.0),
        ]
    return s


def http_get(path, timeout=5):
    with urllib.request.urlopen(f"http://127.0.0.1:{AUTO}{path}", timeout=timeout) as r:
        return r.read()


def http_post(path, obj):
    req = urllib.request.Request(f"http://127.0.0.1:{AUTO}{path}", data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read()


def png_nonblank(data):
    """PNG'de cizili piksel var mi (zlib'i acip alfa/renk > 0 sayar)."""
    import struct
    import zlib
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        ln, typ = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h = struct.unpack(">II", chunk[:8])
        elif typ == b"IDAT":
            idat += chunk
        pos += 12 + ln
    raw = zlib.decompress(idat)
    return sum(1 for b in raw if b > 40) > 50


GEC_BRIDGE_SEC = 15   # --mode gec: kopru bu kadar sn sonra acilir (eski kod 3 hatada ~6 sn'de koru koruna gecerdi)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", required=True, help="evenhub-simulator ikilisi")
    ap.add_argument("--out", required=True)
    # gec: .ehpk gibi baska kaynak + fetch engeli, kopru eklenti acildiktan GEC_BRIDGE_SEC sonra acilir (telefonda APK
    # guncellenince uygulama acilmadan eklenti acildi → eski kod kapali kopruye gecip hata sayfasinda kaldi, APK #46)
    # gec-fetch: telefondaki gercek durum (APK #47 log'u) — .ehpk baska kaynakta, fetch tutuyor, kopru gec aciliyor:
    # sayfa gecisi olmadan baglanmali, font kopru gelince yuklenip buyuk yaziya gecmeli
    ap.add_argument("--mode", choices=["same", "cross", "engel", "gec", "gec-fetch"], default="same")
    ap.add_argument("--no-arabic", action="store_true")
    args = ap.parse_args()
    sim_bin = str(Path(args.sim).resolve())   # simulator gecici dizinde baslatilir: goreli yol orada bulunmaz
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    procs = []
    errors = []
    try:
        def start_bridge():
            p = subprocess.Popen([str(JVM_BIN), "glasses-serve", str(G2_DIR), str(FONT_DIR), "18765"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 encoding="utf-8")
            procs.append(p)
            for line in p.stdout:
                if line.startswith("hazir"):
                    break
            return p

        srv = None if args.mode in ("gec", "gec-fetch") else start_bridge()
        url = "http://127.0.0.1:18765/"
        if args.mode in ("cross", "engel", "gec", "gec-fetch"):
            # .ehpk gibi: paket dosyalari + CI'nin yazdigi g2-paket.json (paket surumu)
            pkg = Path(tempfile.mkdtemp(prefix="g2pkg-")) / "g2"
            shutil.copytree(G2_DIR, pkg)
            (pkg / "g2-paket.json").write_text('{"surum": "0.99.0"}', encoding="utf-8")
            web = subprocess.Popen([sys.executable, "-m", "http.server", "8771", "--bind", "127.0.0.1"], cwd=pkg,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            procs.append(web)
            url = "http://127.0.0.1:8771/index.html" + ("?test-fetch-engel=1" if args.mode in ("engel", "gec") else "")
        try:
            http_get("/api/ping", 1)
            print(f"port {AUTO}'da baska bir simulator acik — once onu kapatin")
            return 1
        except Exception:
            pass
        home = tempfile.mkdtemp(prefix="g2sim-")
        sim_log = out / "simulator.log"
        # ayri surec grubu: xvfb-run sonlaninca simulator ve Xvfb de kapansin (bkz. finally). GPU yok: yazilim cizimi.
        sim_env = dict(os.environ, HOME=home, LIBGL_ALWAYS_SOFTWARE="1", WEBKIT_DISABLE_DMABUF_RENDERER="1",
                       RUST_BACKTRACE="1")
        sim = subprocess.Popen(["xvfb-run", "-a", "-s", "-screen 0 1400x1000x24", sim_bin, url, "--automation-port",
                                str(AUTO), "--no-glow"], cwd=home, env=sim_env,
                               stdout=open(sim_log, "wb"), stderr=subprocess.STDOUT, start_new_session=True)
        procs.append(sim)
        t_open = time.time()
        while time.time() - t_open < 120:
            try:
                if http_get("/api/ping", 1) == b"pong":
                    break
            except Exception:
                pass
            if sim.poll() is not None:
                break
            time.sleep(0.5)
        else:
            sim_log_tail = sim_log.read_text(encoding="utf-8", errors="replace")[-3000:]
            print(f"simulator 120 sn'de acilmadi; cikti:\n{sim_log_tail}")
            return 1
        if sim.poll() is not None:
            sim_log_tail = sim_log.read_text(encoding="utf-8", errors="replace")[-3000:]
            print(f"simulator kapandi (kod {sim.returncode}); cikti:\n{sim_log_tail}")
            return 1
        print(f"simulator {time.time() - t_open:.0f} sn'de acildi")
        time.sleep(3)
        # soguk acilista simulatorun cizimi gec baslayabiliyor (yazilim GL): ilk ekran gorunene kadar bekle (en fazla 30 sn)
        t_draw = time.time()
        while time.time() - t_draw < 30 and not png_nonblank(http_get("/api/screenshot/glasses")):
            time.sleep(1)
        if srv is None:
            # kopru kapaliyken eklenti bekler (hata sayfasina gecmemeli), kopru acilinca kendiliginden baglanmali
            time.sleep(GEC_BRIDGE_SEC)
            png = http_get("/api/screenshot/glasses")
            (out / "00_kopru_kapali.png").write_bytes(png)
            srv = start_bridge()
            print(f"kopru {GEC_BRIDGE_SEC} sn gec acildi")
            time.sleep(8)
        report = []

        def transfers():
            """Konsoldaki "aktarim: N karo M ms" satirlarinin karo toplami (gozluge giden goruntu)."""
            n = 0
            for e in json.loads(http_get("/api/console")).get("entries", []):
                m = re.search(r"aktarim: (\d+) karo", e.get("message", ""))
                if m:
                    n += int(m.group(1))
            return n

        for i, (name, st, inputs, wait) in enumerate(scenario(not args.no_arabic)):
            before = transfers()
            for k, one in enumerate(st if isinstance(st, list) else [st]):
                if k:
                    time.sleep(0.05)
                srv.stdin.write(json.dumps(one, ensure_ascii=False) + "\n")
                srv.stdin.flush()
            time.sleep(wait)
            for inp in inputs:
                http_post("/api/input", {"action": inp})
                time.sleep(1.2)
            png = http_get("/api/screenshot/glasses")
            p = out / f"{i:02d}_{name}.png"
            p.write_bytes(png)
            drawn = png_nonblank(png)
            ok = not drawn if name in EXPECT_EMPTY else drawn
            sent = transfers() - before
            report.append(f"{p.name}: {'ok' if ok else ('CIZILI EKRAN' if drawn else 'BOS EKRAN')} (karo {sent})")
            if not ok:
                errors.append(f"{'bos olmali' if drawn else 'bos ekran'}: {name}")
            if name in MAX_TILES and sent > MAX_TILES[name]:
                errors.append(f"{name}: gozluge {sent} karo gitti (en fazla {MAX_TILES[name]})")
            if name in MIN_TILES and sent < MIN_TILES[name]:
                errors.append(f"{name}: gozluge {sent} karo gitti (en az {MIN_TILES[name]}; font degisimi cizilmedi)")
        cons = json.loads(http_get("/api/console"))
        (out / "console.json").write_text(json.dumps(cons, indent=1, ensure_ascii=False), encoding="utf-8")
        for e in cons.get("entries", []):
            m = e.get("message", "")
            if "ipc://localhost" in m:   # simulatorun kendi konsol aktarimi (sayfa gecisinde)
                continue
            if args.mode in ("gec", "gec-fetch") and m.startswith("[fetch] Load failed") and ":18765/" in m:
                continue   # kopru kapaliyken beklenen yoklama hatalari
            if e.get("level") == "error" or m.startswith(("[uncaught]", "[unhandledrejection]", "[fetch]")) or \
                    "hatasi" in m or "gonderilemedi" in m or "font yuklenemedi" in m:
                errors.append(m[:300])
        msgs = [e.get("message", "") for e in cons.get("entries", [])]
        if args.mode in ("engel", "gec"):
            for need in ("dogrudan kopruden", "kopru bagli"):
                if not any(need in m for m in msgs):
                    errors.append(f"engel modu: konsolda '{need}' yok (dogrudan gecis olmadi)")
        if args.mode == "gec-fetch":
            for need in ("kopru bagli", "kod: paket", "yeniden kuruldu: big"):
                if not any(need in m for m in msgs):
                    errors.append(f"gec-fetch modu: konsolda '{need}' yok")
            if any("dogrudan kopruden" in m for m in msgs):
                errors.append("gec-fetch modu: sayfa kopruye gecti (fetch tutarken gecis olmamali)")
        if args.mode == "cross":
            # .ehpk gibi baska kaynak, fetch tutuyor: kod koprudan (APK) blob import ile, sayfa gecisi YOK (telefonda kopru
            # adresine gecis ERR_CONNECTION_REFUSED oldu, APK #46-47)
            if not any("kod kopruden" in m for m in msgs):
                errors.append("cross modu: konsolda 'kod kopruden' yok (boot.js kopru kodunu yuklemedi)")
            if any("dogrudan kopruden" in m for m in msgs):
                errors.append("cross modu: sayfa kopruye gecti (fetch tutarken gecis olmamali)")
            if not any("kod: kopru-" in m for m in msgs):
                errors.append("cross modu: kopru bagli satirinda 'kod: kopru-N' yok")
            if not any("paket: 0.99.0" in m for m in msgs):
                errors.append("cross modu: paket surumu (g2-paket.json) okunmadi")
        print("\n".join(report))
        print(f"konsol: {len(cons.get('entries', []))} satir, hata {len(errors)}")
        for e in errors:
            print("  HATA", e)
        return 1 if errors else 0
    finally:
        for p in reversed(procs):
            try:
                if p.stdin:
                    p.stdin.close()
            except Exception:
                pass
            try:
                os.killpg(p.pid, signal.SIGTERM)   # sadece kendi grubu olanlar (simulator)
            except Exception:
                pass
            p.terminate()
            try:
                p.wait(5)
            except Exception:
                p.kill()


if __name__ == "__main__":
    sys.exit(main())
