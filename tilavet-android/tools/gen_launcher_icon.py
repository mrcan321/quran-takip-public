"""
Uygulama ikonu: "Namazda Anla" logosu (yesil halka, kemer + yildiz + N, gozluk, acik kitap) → Android VectorDrawable.

Logo gorselinden (kullanicinin verdigi PNG) olculup elle cizildi — vektor oldugu icin her boyutta keskin.
108x108 viewport (adaptive icon); halka r=30 (guvenli alan r=33 icinde), maske disinda krem zemin kalir.

Cikti (res/drawable): ic_launcher_foreground.xml (gradyanli), ic_launcher_monochrome.xml (Android 13 tema ikonu,
tek renk), ic_launcher_background.xml (krem radyal).

    python tilavet-android/tools/gen_launcher_icon.py            # → tilavet-android/app/src/main/res/drawable/
    python tilavet-android/tools/gen_launcher_icon.py <klasor>   # baska yere (onizleme icin)
"""
import sys, os
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                          "..", "app", "src", "main", "res", "drawable")

def fmt(v): 
    s = f"{v:.2f}".rstrip('0').rstrip('.')
    return s if s not in ('-0', '') else '0'

def P(cmds, mirror=False):
    """cmds: [('M',x,y),('L',x,y),('C',x1,y1,x2,y2,x,y),('Z',)] → pathData; mirror: x → 108-x"""
    out = []
    for c in cmds:
        op, *v = c
        if mirror:
            v = [108 - a if i % 2 == 0 else a for i, a in enumerate(v)]
        out.append(op + ",".join(fmt(a) for a in v))
    return " ".join(out)

def lin(x1, y1, x2, y2, stops):
    items = "".join(f'\n                <item android:offset="{o}" android:color="{c}"/>' for o, c in stops)
    return (f'<gradient android:type="linear" android:startX="{fmt(x1)}" android:startY="{fmt(y1)}" '
            f'android:endX="{fmt(x2)}" android:endY="{fmt(y2)}">{items}\n            </gradient>')

def path(d, fill=None, grad=None, stroke=None, sgrad=None, sw=None, cap="round", join="round", mono=False):
    a = [f'android:pathData="{d}"']
    inner = ""
    if mono:
        if fill or grad: a.append('android:fillColor="#FF000000"')
        if stroke or sgrad:
            a.append('android:strokeColor="#FF000000"')
    else:
        if fill: a.append(f'android:fillColor="{fill}"')
        if stroke: a.append(f'android:strokeColor="{stroke}"')
        if grad: inner += f'\n        <aapt:attr name="android:fillColor">\n            {grad}\n        </aapt:attr>'
        if sgrad: inner += f'\n        <aapt:attr name="android:strokeColor">\n            {sgrad}\n        </aapt:attr>'
    if stroke or sgrad:
        a.append(f'android:strokeWidth="{fmt(sw)}"')
        a.append(f'android:strokeLineCap="{cap}"')
        a.append(f'android:strokeLineJoin="{join}"')
    attrs = "\n        ".join(a)
    if inner:
        return f'    <path\n        {attrs}>{inner}\n    </path>\n'
    return f'    <path\n        {attrs} />\n'

def circle(cx, cy, r):
    return f"M{fmt(cx - r)},{fmt(cy)} A{fmt(r)},{fmt(r)} 0 1,1 {fmt(cx + r)},{fmt(cy)} A{fmt(r)},{fmt(r)} 0 1,1 {fmt(cx - r)},{fmt(cy)} Z"

# ---- Sekiller ----
RING_R, RING_W = 30.0, 2.4

# Kemer (orta cizgi, stroke): dikey bacaklar, omuzdan sogan/ogee tepeye
ARCH = [('M', 44.0, 53.2), ('L', 44.0, 40.6),
        ('C', 44.0, 35.6, 47.6, 33.9, 50.6, 32.8), ('C', 52.3, 32.2, 53.4, 31.3, 54.0, 29.9),
        ('C', 54.6, 31.3, 55.7, 32.2, 57.4, 32.8), ('C', 60.4, 33.9, 64.0, 35.6, 64.0, 40.6),
        ('L', 64.0, 53.2)]
ARCH_W = 3.0

# 4 koseli yildiz (ic bukey kenarlar)
def star(cx, cy, r):
    k = r * 0.22
    return [('M', cx, cy - r), ('C', cx + k * 0.3, cy - k, cx + k, cy - k * 0.3, cx + r, cy),
            ('C', cx + k, cy + k * 0.3, cx + k * 0.3, cy + k, cx, cy + r),
            ('C', cx - k * 0.3, cy + k, cx - k, cy + k * 0.3, cx - r, cy),
            ('C', cx - k, cy - k * 0.3, cx - k * 0.3, cy - k, cx, cy - r), ('Z',)]
STAR = star(54.0, 37.6, 2.4)

# N: kemerin icini doldurur — sol govde (ust kesik egik), capraz yaprak, sag govde (ucu sivri)
N_LEFT = [('M', 46.1, 42.2), ('L', 49.6, 41.0), ('L', 49.6, 53.0), ('L', 46.1, 53.0), ('Z',)]
N_DIAG = [('M', 46.6, 41.2), ('C', 51.6, 42.6, 57.6, 47.2, 62.0, 53.0), ('L', 57.4, 53.0),
          ('C', 54.6, 49.4, 50.8, 46.4, 47.2, 45.4), ('C', 46.4, 44.6, 46.1, 42.2, 46.6, 41.2), ('Z',)]
N_RIGHT = [('M', 58.3, 44.2), ('C', 59.2, 43.0, 60.6, 42.1, 61.9, 41.7), ('L', 61.9, 53.0), ('L', 58.3, 53.0), ('Z',)]

# Gozluk: kalin ust kas (uclarda asagi kivrik mentese), derin yuvarlak camlar, kopru
BAR = [('M', 30.6, 52.4), ('L', 77.4, 52.4), ('C', 78.6, 52.4, 79.0, 53.4, 78.5, 54.4), ('L', 77.6, 57.0),
       ('L', 75.6, 57.0), ('L', 75.9, 55.2), ('L', 32.1, 55.2), ('L', 32.4, 57.0), ('L', 30.4, 57.0),
       ('L', 29.5, 54.4), ('C', 29.0, 53.4, 29.4, 52.4, 30.6, 52.4), ('Z',)]
LENS = [('M', 33.2, 54.8), ('C', 32.9, 59.6, 35.4, 63.4, 40.6, 63.4), ('C', 45.6, 63.4, 48.6, 61.2, 50.6, 57.8),
        ('L', 52.4, 55.2)]
LENS_W = 1.9
BRIDGE = [('M', 49.8, 54.8), ('C', 51.6, 55.4, 52.8, 56.4, 54.0, 57.6), ('C', 55.2, 56.4, 56.4, 55.4, 58.2, 54.8)]

# Acik kitap: ustte yesil, altta koyu sayfa (uclar kalin, ortaya incelir); ortada V
PAGE_G = [('M', 32.6, 62.4), ('C', 39.6, 63.8, 46.8, 67.0, 53.4, 72.0),
          ('C', 46.4, 69.4, 39.4, 66.6, 32.6, 65.2), ('C', 31.6, 65.0, 31.4, 62.6, 32.6, 62.4), ('Z',)]
PAGE_K = [('M', 30.6, 66.2), ('C', 38.4, 66.7, 46.6, 70.4, 54.0, 77.8),
          ('C', 46.0, 73.2, 38.0, 69.6, 30.8, 69.2), ('C', 29.8, 69.0, 29.6, 66.4, 30.6, 66.2), ('Z',)]

GREEN_DARK, GREEN, GREEN_LIGHT = "#FF0B3D22", "#FF1F6B3A", "#FF4E9C52"
INK = "#FF141B17"

def build(mono):
    s = ""
    s += path(circle(54, 54, RING_R), stroke="#000" if mono else None, sw=RING_W, mono=mono,
              sgrad=None if mono else lin(32, 26, 76, 84, [(0, "#FF2F7B3E"), (0.45, "#FF15502D"), (1, "#FF0A3820")]))
    s += path(P(ARCH), stroke="#000" if mono else None, sw=ARCH_W, cap="butt", mono=mono,
              sgrad=None if mono else lin(41, 40, 67, 40, [(0, "#FF0C4325"), (0.5, "#FF22703C"), (1, "#FF4A974F")]))
    s += path(P(STAR), fill=INK if mono else "#FF154A2C", mono=mono)
    s += path(P(N_LEFT), fill="#000" if mono else None, mono=mono,
              grad=None if mono else lin(48, 42, 48, 53, [(0, "#FF1C5E35"), (1, "#FF082F1B")]))
    s += path(P(N_RIGHT), fill="#000" if mono else None, mono=mono,
              grad=None if mono else lin(60, 42, 60, 53, [(0, "#FF3F8E48"), (1, "#FF16522F")]))
    s += path(P(N_DIAG), fill="#000" if mono else None, mono=mono,
              grad=None if mono else lin(47, 42, 61, 53, [(0, "#FF5BA85C"), (0.6, "#FF2C7D41"), (1, "#FF0F4527")]))
    s += path(P(BAR), fill="#000" if mono else INK, mono=mono)
    for m in (False, True):
        s += path(P(LENS, m), stroke="#000" if mono else INK, sw=LENS_W, mono=mono)
    s += path(P(BRIDGE), stroke="#000" if mono else INK, sw=2.0, mono=mono)
    for m in (False, True):
        s += path(P(PAGE_G, m), fill="#000" if mono else None, mono=mono,
                  grad=None if mono else lin(108 - 32.6 if m else 32.6, 63, 108 - 53.4 if m else 53.4, 72,
                                             [(0, "#FF54A257"), (1, "#FF15532F")]))
        s += path(P(PAGE_K, m), fill="#000" if mono else INK, mono=mono)
    return s

HEAD = ('<?xml version="1.0" encoding="utf-8"?>\n'
        '<!-- Namazda Anla logosu — tilavet-android/tools/gen_launcher_icon.py uretir, elle degistirme -->\n'
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
        '    xmlns:aapt="http://schemas.android.com/aapt"\n'
        '    android:width="108dp"\n    android:height="108dp"\n'
        '    android:viewportWidth="108"\n    android:viewportHeight="108">\n')
open(os.path.join(OUT, "ic_launcher_foreground.xml"), "w").write(HEAD + build(False) + "</vector>\n")
open(os.path.join(OUT, "ic_launcher_monochrome.xml"), "w").write(HEAD.replace('    xmlns:aapt="http://schemas.android.com/aapt"\n', '') + build(True) + "</vector>\n")
bg = (HEAD + path("M0,0 L108,0 L108,108 L0,108 Z", mono=False,
                  grad='<gradient android:type="radial" android:centerX="54" android:centerY="48" android:gradientRadius="64">'
                       '\n                <item android:offset="0" android:color="#FFFFFDF6"/>'
                       '\n                <item android:offset="0.7" android:color="#FFF8F2E4"/>'
                       '\n                <item android:offset="1" android:color="#FFEFE6D2"/>\n            </gradient>')
      + "</vector>\n")
open(os.path.join(OUT, "ic_launcher_background.xml"), "w").write(bg)
print("yazildi")
