#!/usr/bin/env python3
"""Namazda Anla live-action promo. Licensed Pexels recordings and original overlays."""
import pathlib, shutil, subprocess
from PIL import Image, ImageDraw, ImageFont
W,H,FPS=720,1280,25
ROOT=pathlib.Path.cwd(); WORK=ROOT/'.promo_render'; DEST=ROOT/'public'/'videos'
WORK.mkdir(exist_ok=True);DEST.mkdir(parents=True,exist_ok=True)
GOLD=(237,199,131); WHITE=(244,244,239); PALE=(210,221,219)
CLIPS={
 'congregation':('10724507','hd_1280_720_30fps'),
 'reader':('8165475','hd_1080_1920_25fps'),
 'glasses':('5708165','hd_1080_1920_25fps'),
 'prayer':('8165164','hd_1080_1920_25fps'),
 'closing':('8165478','hd_720_1280_25fps'),
 'mosque':('8165092','hd_1280_720_25fps'),
 'page':('8165565','hd_720_1280_25fps'),
}
SCENES=[
 ('congregation',1.0,3.7,['Her gün','dinliyoruz.'],'Peki anlamını biliyor muyuz?', 'story'),
 ('reader',1.5,4.0,['Ayetlerin','sesi...'],'Kulaklarımıza ulaşır.', 'story'),
 ('glasses',3.0,4.0,['Ya anlamı?'],'Kalbimize de ulaşabilir.', 'story'),
 ('page',2.3,5.4,['Duyduğun ayetin','anlamını takip et.'],'Arapça tilavet  ·  Türkçe anlam', 'interface'),
 ('prayer',2.0,4.1,['Dinle.','Anla. Düşün.'],'Namazda Kur’an ile daha bilinçli bağ.', 'story'),
 ('closing',3.0,4.0,['Anlamak,','fark etmektir.'],'Ayet üzerinde kendin düşün.', 'story'),
 ('glasses',17.0,5.3,['NAMAZDA','ANLA'],'Duyduğun ayetin anlamıyla buluş.', 'end'),
]
def run(cmd):
 print('+',' '.join(map(str,cmd))[:250],flush=True)
 subprocess.run(list(map(str,cmd)),check=True)
def font(bold=False,arabic=False,size=44):
 paths=(['/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'] if arabic else
 ['/usr/share/fonts/truetype/lato/Lato-Heavy.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'] if bold else
 ['/usr/share/fonts/truetype/lato/Lato-Regular.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'])
 for path in paths:
  if pathlib.Path(path).exists():return ImageFont.truetype(path,size)
 raise RuntimeError('Font missing')
def text(img,xy,msg,f,fill,anchor=None):
 kw={'font':f,'fill':fill}
 if anchor:kw['anchor']=anchor
 ImageDraw.Draw(img).text(xy,msg,**kw)
def gradient(img,top=True,maximum=175,limit=420):
 d=ImageDraw.Draw(img,'RGBA')
 if top:
  for y in range(limit):d.line([(0,y),(W,y)],fill=(5,15,19,int(maximum*(1-y/limit)**1.45)))
 else:
  for y in range(H-limit,H):d.line([(0,y),(W,y)],fill=(3,14,18,int(maximum*((y-(H-limit))/limit)**1.3)))
def overlay(i,lines,subtitle,kind):
 img=Image.new('RGBA',(W,H),(0,0,0,0));d=ImageDraw.Draw(img,'RGBA')
 if kind=='end':
  d.rectangle((0,0,W,H),fill=(1,13,17,180))
  d.line((60,400,160,400),fill=GOLD,width=3)
  text(img,(60,443),'NAMAZDA',font(True,size=73),WHITE)
  text(img,(60,535),'ANLA',font(True,size=112),GOLD)
  text(img,(60,713),subtitle,font(size=29),WHITE)
  d.line((60,800,660,800),fill=(237,199,131,120),width=2)
  text(img,(60,830),'namazdaanla.org',font(size=27),GOLD)
  text(img,(60,1155),'TANITIM FİLMİ',font(size=17),(230,232,232,180))
 else:
  gradient(img,True,160,300);gradient(img,False,206,550)
  text(img,(54,55),'NAMAZDA ANLA',font(True,size=23),WHITE)
  d.rounded_rectangle((54,98,115,103),radius=3,fill=GOLD)
  if kind=='interface':
   d.rounded_rectangle((42,392,678,885),radius=27,fill=(4,23,28,234),outline=(237,199,131,158),width=2)
   d.rounded_rectangle((70,422,288,464),radius=19,fill=(15,76,70,220))
   text(img,(88,429),'●  TİLAVET TAKİBİ',font(True,size=16),(176,241,215))
   text(img,(620,506),'رَبِّ زِدْنِي عِلْمًا',font(arabic=True,size=65),WHITE,anchor='ra')
   d.line((88,614,630,614),fill=(237,199,131,95),width=2)
   text(img,(88,657),'Rabbim, ilmimi artır!',font(True,size=35),WHITE)
   text(img,(89,724),'TÂHÂ 20:114',font(True,size=21),GOLD)
   text(img,(88,792),'Ekran deneyimi görselleştirilmiştir.',font(size=16),(212,223,225))
  y=965 if kind=='interface' else 900
  titleFont=font(True,size=56 if kind=='interface' else 65)
  for j,line in enumerate(lines):
   text(img,(56,y+j*82),line,titleFont,GOLD if j==1 and kind!='interface' else WHITE)
  text(img,(57,y+len(lines)*84+17),subtitle,font(size=23),PALE)
  text(img,(56,1225),'namazdaanla.org',font(size=17),(228,236,232,198))
 p=WORK/f'overlay_{i:02d}.png';img.save(p);return p
def main():
 if not shutil.which('ffmpeg'):raise SystemExit('ffmpeg missing')
 for key,(vid,variant) in CLIPS.items():
  path=WORK/f'{key}.mp4'
  if not path.exists() or path.stat().st_size<200000:
   url=f'https://videos.pexels.com/video-files/{vid}/{vid}-{variant}.mp4'
   run(['curl','-fL','--retry','3','--max-time','90','-sS',url,'-o',path])
 total=0; segments=[]
 for i,(key,offset,duration,lines,subtitle,kind) in enumerate(SCENES):
  total+=duration;png=overlay(i,lines,subtitle,kind);out=WORK/f'seg{i:02d}.mp4'
  filt=f'[0:v]fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,eq=contrast=1.07:saturation=0.96[bg];[bg][1:v]overlay=0:0:format=auto,format=yuv420p,fade=t=in:st=0:d=0.22,fade=t=out:st={duration-0.24:.3f}:d=0.24[v]'
  run(['ffmpeg','-y','-hide_banner','-loglevel','error','-ss',str(offset),'-t',str(duration),'-i',WORK/f'{key}.mp4','-loop','1','-i',png,'-filter_complex',filt,'-map','[v]','-an','-t',str(duration),'-r',str(FPS),'-c:v','libx264','-preset','veryfast','-crf','22','-pix_fmt','yuv420p','-movflags','+faststart',out]);segments.append(out)
 listfile=WORK/'list.txt';listfile.write_text(''.join(f"file '{p.resolve()}'\n" for p in segments))
 joined=WORK/'joined.mp4'
 run(['ffmpeg','-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',listfile,'-c','copy',joined])
 dur=round(total,2);audio=WORK/'ambient.m4a'
 mix='[0:a]volume=0.032[a0];[1:a]volume=0.024[a1];[2:a]volume=0.019[a2];[a0][a1][a2]amix=inputs=3:normalize=0,lowpass=f=1200,aecho=0.8:0.35:800:0.13,afade=t=in:st=0:d=1.4,afade=t=out:st='+str(dur-2.1)+':d=2[a]'
 run(['ffmpeg','-y','-hide_banner','-loglevel','error','-f','lavfi','-i',f'sine=frequency=130.813:sample_rate=44100:duration={dur}','-f','lavfi','-i',f'sine=frequency=164.814:sample_rate=44100:duration={dur}','-f','lavfi','-i',f'sine=frequency=196.00:sample_rate=44100:duration={dur}','-filter_complex',mix,'-map','[a]','-c:a','aac','-b:a','160k',audio])
 final=DEST/'namazda-anla-gercek-insanlar.mp4'
 run(['ffmpeg','-y','-hide_banner','-loglevel','error','-i',joined,'-i',audio,'-map','0:v','-map','1:a','-c:v','copy','-c:a','copy','-shortest','-movflags','+faststart',final])
 run(['ffmpeg','-y','-hide_banner','-loglevel','error','-ss','14','-i',final,'-frames:v','1','-q:v','3','-update','1',DEST/'namazda-anla-gercek-insanlar-kapak.jpg'])
 sources="""NAMAZDA ANLA TANITIM - KAYNAKLAR
Gerçek insan ve cami çekimleri Pexels lisansı altında:
https://www.pexels.com/legal-pages/license/
Atif Dar: https://www.pexels.com/video/people-praying-in-mosque-10724507/
Alena Darmel: https://www.pexels.com/video/man-reading-quran-8165475/
Tima Miroshnichenko: https://www.pexels.com/video/man-wearing-eye-glasses-reading-a-book-5708165/
Alena Darmel: https://www.pexels.com/video/a-man-wearing-taqiyah-while-praying-8165164/
Alena Darmel: https://www.pexels.com/video/a-man-closing-the-book-of-quran-after-praying-8165478/
Alena Darmel: https://www.pexels.com/video/man-closing-a-book-8165565/
Alena Darmel: https://www.pexels.com/video/a-man-praying-in-a-mosque-8165092/
Stok görüntülerdeki kişilerin Namazda Anla ürününü kullandığı veya desteklediği ileri sürülmez.
Ürün arayüzü grafikle canlandırılmıştır; görüntüler gerçek cihaz kaydı değildir.
Ses müziği özgün olarak üretilmiştir.
"""
 (DEST/'namazda-anla-video-kaynaklar.txt').write_text(sources)
 print('VIDEO_OK',final,final.stat().st_size,'duration',dur,flush=True)
if __name__=='__main__':main()
