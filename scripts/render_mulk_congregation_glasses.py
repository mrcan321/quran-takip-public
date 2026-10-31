#!/usr/bin/env python3
"""Namazda Anla: congregation prayer, eyewear and time-verified Mulk 67:10–11 demo.
Pexels/Unsplash stock + CC0 authentic human recitation. No third-party promo material.
"""
import os, pathlib, subprocess, math, urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT=pathlib.Path.cwd()
A=ROOT/'.prayer_demo_assets'
OUT=ROOT/'public'/'videos'
A.mkdir(exist_ok=True,parents=True)
OUT.mkdir(exist_ok=True,parents=True)
W,H,FPS=720,1280,25
WHITE=(248,246,238); PALE=(207,221,215); GOLD=(232,190,113); TEAL=(107,229,208)
MULK='https://upload.wikimedia.org/wikipedia/commons/6/6e/Chapter_67%2C_Al-Mulk_%28Murattal%29_-_Recitation_of_the_Holy_Qur%27an.mp3'
MEDIA={
 'congregation':('https://videos.pexels.com/video-files/10724507/10724507-hd_1280_720_30fps.mp4','mp4'),
 'mosque':('https://videos.pexels.com/video-files/8165092/8165092-hd_1280_720_25fps.mp4','mp4'),
 'prayer':('https://videos.pexels.com/video-files/8165164/8165164-hd_1080_1920_25fps.mp4','mp4'),
 'eyewear':('https://videos.pexels.com/video-files/5708165/5708165-hd_1080_1920_25fps.mp4','mp4'),
 'product':('https://images.unsplash.com/photo-1693496481492-1abae85f5277?w=1400&q=85','jpg'),
 'mulk':(MULK,'mp3')
}
# Word recognition was checked against original Wikimedia CC0 audio:
# 67:09 approx 135.6–160.8; 67:10 approx 160.8–176.8; 67:11 approx 176.8–187.8
REC_START=160.55
VERSE_BOUNDARY=176.8-REC_START
VERSES_DURATION=187.9-REC_START
# Scenes: duration total and matching onset of recitation are checked in code.
SCENES=[
 ('congregation',0.7,4.5,'Bir cami.','Bir cemaat.','intro'),
 ('congregation',5.0,4.0,'İmam okuyor.','Hepimiz işitiyoruz.','intro'),
 ('mosque',1.5,4.5,'Peki ya anlamı?','Namazda onu da takip edebilseydik...','intro'),
 ('prayer',2.6,3.0,'Gözlerimiz namazda.','Anlamı merak ediyoruz.','intro'),
 ('product',0.0,4.3,'NAMAZDA ANLA','Zarif bir gözlük deneyimi.','product'),
 ('eyewear',2.8,4.7,'AYET.  MEAL.','Görüş alanında.','product'),
 ('congregation',0.0,VERSE_BOUNDARY,'MÜLK 67:10','','verse10'),
 ('mosque',0.0,VERSES_DURATION-VERSE_BOUNDARY,'MÜLK 67:11','','verse11'),
 ('product',0.0,5.2,'DİNLE. ANLA. DÜŞÜN.','namazdaanla.org','outro')
]
AR10=['وَقَالُوا لَوْ كُنَّا نَسْمَعُ أَوْ نَعْقِلُ','مَا كُنَّا فِي أَصْحَابِ السَّعِيرِ']
TR10=['“Kulak verseydik ya da aklımızı kullansaydık,','alevli ateşin halkından olmazdık” derler.']
AR11=['فَاعْتَرَفُوا بِذَنْبِهِمْ','فَسُحْقًا لِأَصْحَابِ السَّعِيرِ']
TR11=['Böylece suçlarını itiraf ederler.','Alevli ateşin halkı uzak olsun!']
def run(args):
 subprocess.run(list(map(str,args)),check=True)
def font(n,bold=False,arabic=False):
 paths=(
 ['/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf','/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
 if arabic else
 ['/usr/share/fonts/truetype/lato/Lato-Heavy.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'] if bold else
 ['/usr/share/fonts/truetype/lato/Lato-Regular.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'])
 for p in paths:
  if pathlib.Path(p).exists():return ImageFont.truetype(p,n)
 raise FileNotFoundError(paths)
def load_assets():
 for key,(url,ext) in MEDIA.items():
  p=A/(key+'.'+ext)
  if p.exists() and p.stat().st_size>50000:continue
  print('Download',key,flush=True)
  run(['curl','--fail','--location','--silent','--show-error','--retry','3','--max-time','120',url,'-o',p])
  if p.stat().st_size<50000:raise RuntimeError('Invalid media: '+key)
def phrase(img,x,y,s,f,color,shadow=True):
 d=ImageDraw.Draw(img,'RGBA')
 if shadow:d.text((x+2,y+3),s,font=f,fill=(0,0,0,175),stroke_width=2,stroke_fill=(0,0,0,120))
 d.text((x,y),s,font=f,fill=color)
def vignette(img):
 d=ImageDraw.Draw(img,'RGBA')
 for y in range(H):
  k=max(0,(y-540)/(H-540))
  if k>0:d.line((0,y,W,y),fill=(1,13,17,int(198*k**1.1)))
 for y in range(280):
  d.line((0,y,W,y),fill=(1,12,15,int(135*(1-y/280))))
def rounded_box(d,xy,r=20,fill=None,outline=None,width=2):
 d.rounded_rectangle(xy,radius=r,fill=fill,outline=outline,width=width)
def overlay(i,scene):
 key,offset,dur,title,sub,kind=scene
 img=Image.new('RGBA',(W,H),(0,0,0,0));d=ImageDraw.Draw(img,'RGBA')
 vignette(img)
 phrase(img,48,43,'NAMAZDA ANLA',font(24,True),WHITE)
 d.rounded_rectangle((48,99,123,105),radius=3,fill=GOLD)
 if kind in ('intro','product'):
  size=56 if len(title)<19 else 43
  if kind=='product':size=58
  phrase(img,47,914,title,font(size,True),WHITE)
  if sub:phrase(img,48,1022,sub,font(23),PALE)
  if kind=='product':
   rounded_box(d,(46,1130,424,1169),20,fill=(4,36,39,183),outline=(114,211,189,130),width=1)
   phrase(img,67,1137,'PROTOTİP GÖSTERİMİ',font(16,True),TEAL,False)
 elif kind.startswith('verse'):
  verse=10 if kind=='verse10' else 11
  arab=AR10 if verse==10 else AR11
  trans=TR10 if verse==10 else TR11
  rounded_box(d,(34,364,688,928),24,fill=(2,23,29,220),outline=(121,221,198,200),width=2)
  rounded_box(d,(58,396,294,436),17,fill=(15,88,79,200))
  phrase(img,75,405,'●  TİLAVET TAKİBİ',font(17,True),(190,248,224),False)
  phrase(img,560,405,f'{verse}/30',font(20,True),GOLD,False)
  da=ImageDraw.Draw(img,'RGBA')
  ff=font(51,arabic=True)
  for j,line in enumerate(arab):
   try:da.text((628,487+j*86),line,font=ff,fill=WHITE,anchor='ra',direction='rtl')
   except Exception:da.text((75,487+j*86),line,font=ff,fill=WHITE)
  d.line((72,696,645,696),fill=(153,221,196,160),width=2)
  for j,line in enumerate(trans):phrase(img,72,736+j*51,line,font(23,True),WHITE,False)
  phrase(img,73,868,f'MÜLK SURESİ  /  67:{verse}',font(19,True),GOLD,False)
  phrase(img,50,1005,'İmam okurken, anlam da görüş alanında.',font(22),WHITE)
  phrase(img,50,1200,'EKRAN SİMÜLASYONU',font(15),PALE,False)
 elif kind=='outro':
  d.rectangle((0,0,W,H),fill=(5,20,23,145))
  phrase(img,53,469,'NAMAZDA',font(70,True),WHITE)
  phrase(img,53,555,'ANLA',font(129,True),GOLD)
  d.line((55,710,606,710),fill=TEAL,width=3)
  phrase(img,55,775,'Dinle. Anla. Düşün.',font(32,True),WHITE)
  phrase(img,55,838,'namazdaanla.org',font(27),TEAL)
  phrase(img,55,1185,'Tanıtım amaçlı gözlük ekranı simülasyonu.',font(15),PALE)
 phrase(img,50,1231,'namazdaanla.org',font(16),PALE,False)
 path=A/f'lay_{i:02}.png'
 img.save(path)
 return path
def main():
 load_assets()
 durations=sum(x[2] for x in SCENES)
 rec_at=sum(x[2] for x in SCENES[:6])
 print('rec at',rec_at,'boundary',VERSE_BOUNDARY,'duration',VERSES_DURATION,'total',durations,flush=True)
 assert abs(rec_at-25.0)<.1
 assert abs(VERSE_BOUNDARY-16.25)<.01
 segs=[]
 for i,sc in enumerate(SCENES):
  key,offset,dur,_,_,kind=sc
  layer=overlay(i,sc)
  out=A/f'seg_{i:02}.mp4'
  src=A/(key+('.jpg' if key=='product' else '.mp4'))
  scale=f'scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1'
  if key=='product':
   # Ken Burns from authentic licensed photo of slim black spectacles.
   base=f'[0:v]scale=900:1600:force_original_aspect_ratio=increase,crop=900:1600,zoompan=z=1.0+0.05*on/{int(dur*FPS)}:x=(iw-iw/zoom)/2:y=(ih-ih/zoom)/2:d={int(dur*FPS)}:s={W}x{H}:fps={FPS},setsar=1'
   args=['-loop','1','-framerate',str(FPS),'-i',src]
  else:
   base=f'[0:v]fps={FPS},{scale},eq=contrast=1.05:saturation=0.88'
   args=['-ss',str(offset),'-i',src]
  fc=base+'[base];[base][1:v]overlay=0:0:format=auto,format=yuv420p'
  # short softness at cuts, no lyrics or distracting music during recitation
  if dur>2:fc+=f',fade=t=in:st=0:d=0.12,fade=t=out:st={dur-0.15:.3f}:d=0.15'
  fc+='[v]'
  cmd=['ffmpeg','-hide_banner','-loglevel','error','-y']+args+['-loop','1','-i',layer,'-filter_complex',fc,'-map','[v]','-t',str(dur),'-r',str(FPS),'-c:v','libx264','-crf','22','-preset','veryfast','-pix_fmt','yuv420p','-an',out]
  print('Render scene',i,kind,flush=True)
  run(cmd);segs.append(out)
 lst=A/'concat.txt'
 lst.write_text(''.join(f"file '{x.resolve()}'\n" for x in segs))
 joined=A/'joined.mp4'
 run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',lst,'-c','copy',joined])
 # Original synthesized ambient sound for 0..25 and closing. During actual recitation, no background bed.
 audio=A/'sound.m4a'
 run(['ffmpeg','-hide_banner','-loglevel','error','-y',
      '-f','lavfi','-i',f'sine=frequency=123.47:sample_rate=44100:duration={durations}',
      '-f','lavfi','-i',f'sine=frequency=185.0:sample_rate=44100:duration={durations}',
      '-ss',str(REC_START),'-t',str(VERSES_DURATION),'-i',A/'mulk.mp3',
      '-filter_complex',
      f'[0:a]volume=0.010[pad1];[1:a]volume=0.009[pad2];[pad1][pad2]amix=inputs=2:normalize=0,afade=t=in:st=0:d=1.5,volume=enable=between(t\\,25\\,52.35):volume=0.00[bed];'
      f'[2:a]aresample=44100,afade=t=in:st=0:d=.10,afade=t=out:st={VERSES_DURATION-0.25:.2f}:d=.25,adelay={round(rec_at*1000)}|{round(rec_at*1000)},volume=1.05[rec];'
      f'[bed][rec]amix=inputs=2:normalize=0:duration=longest,alimiter=limit=0.85,afade=t=out:st={durations-1.5:.2f}:d=1.4[a]',
      '-map','[a]','-t',str(durations),'-c:a','aac','-b:a','160k',audio])
 finished=OUT/'namazda-anla-mulk-cemaat-gozluk.mp4'
 run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',joined,'-i',audio,'-map','0:v','-map','1:a','-c:v','copy','-c:a','copy','-shortest','-movflags','+faststart',finished])
 cover=OUT/'namazda-anla-mulk-cemaat-gozluk-kapak.jpg'
 run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss','37','-i',finished,'-frames:v','1','-update','1','-q:v','3',cover])
 sidecar=OUT/'namazda-anla-mulk-cemaat-gozluk-kaynaklar.txt'
 sidecar.write_text("""NAMAZDA ANLA — MÜLK 67:10-11 KIRAATLI TANITIM
Gerçek insan kıraati: Aaqib Azeez / Atcovi, Wikimedia Commons CC0:
https://commons.wikimedia.org/wiki/File:Chapter_67,_Al-Mulk_(Murattal)_-_Recitation_of_the_Holy_Qur%27an.mp3
Kesit: 67:10 160.55–176.8 saniye; 67:11 176.8–187.9 saniye.
Ses kesitini belirlemek için Whisper ASR ile Arapça transkripsiyon karşılaştırıldı.
Ayet metni ve açıklayıcı Türkçe anlam: https://quran.com/tr/mulk/7-11
Ayetler, uyarıyı inkâr edenlerin pişmanlığı bağlamındadır; Arapça bilmemek hakkında bir hüküm değildir.
Gerçek cami ve cemaat stok çekimleri:
https://www.pexels.com/video/people-praying-in-mosque-10724507/
https://www.pexels.com/video/a-man-praying-in-a-mosque-8165092/
https://www.pexels.com/video/a-man-wearing-taqiyah-while-praying-8165164/
Gerçek gözlük stok videosu: https://www.pexels.com/video/man-wearing-eye-glasses-reading-a-book-5708165/
Gözlük fotoğrafı: https://unsplash.com/photos/a-pair-of-glasses-sitting-on-top-of-a-table-xrw9em94WaE
Fotoğraf: Steve Johnson. Kaynak medya: photo-1693496481492-1abae85f5277.
Not: Ürün sahneleri ve gözlük ekranı tanıtım simülasyonudur; gerçek cihazın veya camide çekilmiş prototip kullanıcısının birebir kaydı değildir.
Kayıt kıraati ile stok videodaki kişilerin aynı ortamda olduğu ileri sürülmez.
Görseller özgün bir tanıtım kurgusudur; referans IQRA AI filminden ses/görüntü kullanılmamıştır.
Pexels License: https://www.pexels.com/license/
Unsplash License: https://unsplash.com/license
""",encoding='utf-8')
 import json
 meta={'length':round(durations,2),'recitation_at':rec_at,'verse_10_audio':{'source_start':REC_START,'source_end':176.8,'video_start':rec_at,'video_end':rec_at+VERSE_BOUNDARY},'verse_11_audio':{'source_start':176.8,'source_end':187.9,'video_start':rec_at+VERSE_BOUNDARY,'video_end':rec_at+VERSES_DURATION},'output':str(finished),'size_bytes':finished.stat().st_size}
 (OUT/'mulk-video-sync.json').write_text(json.dumps(meta,indent=2,ensure_ascii=False))
 print('VIDEO_COMPLETE',json.dumps(meta,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
