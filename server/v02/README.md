# v0.2 — Yarı-streaming Kuran meal takibi

## Bitti mi?
Evet. Çalışıyor. Namazda kullanılabilir durum.

## Özellikler
- Flask + WebSocket + NeMo
- 5sn chunk, 1sn overlap
- Session state: last_word_index, last_surah, last_ayah
- Preferred_range: sadece ileri git
- Arayı doldurma: max 3 ayet otomatik eklenir
- Min kelime: hot=2, cold=3
- Sure isimleri (Tr + Ar)
- Türkçe meal (Ali Bulaç — `scripts/download_meal.py`)

## Test sonuçları
- Rahmân suresi: 9/14 chunk başarılı, monotonic
- Rahmân kısa ayetler artık yakalanıyor
- Arayı doldurma çalışıyor
- Gecikme: ~5 saniye

## Bilinen sorunlar
- Besmele → sure kilidi (Fatiha'ya kilitlenip Bakara'ya kayıyor)
- 5sn gecikme (chunk süresi nedeniyle)

## Nasıl çalıştırılır
    cd v02
    python app.py
    # tarayıcıdan http://localhost:5000
