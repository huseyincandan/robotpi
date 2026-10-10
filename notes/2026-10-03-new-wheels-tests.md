# 2026-10-03 Yeni teker karşılaştırması

Önceki 2026-10-01 PWM testiyle aynı yöntem: düz ±70 PWM yaklaşık 0,9 saniye; dönüş 80 PWM, son 20° için 72 PWM. Pi HTTP üzerinden IMU açı integrasyonuyla durdurdu. TURNRATE kullanılmadı, firmware/kazanç değiştirilmedi. Güncel yüklü firmware integral kazancı status üzerinden doğrulanamıyor; bu parametre PWM testinde kullanılmaz.

| Hedef | Son IMU açı ° | Süre s | RL/RR tik | Tik farkı % |
|---|---:|---:|---|---:|
| straight 70.0 | -2.3 | 0.94 | 904 / 789 | 13.59 |
| straight -70.0 | -2.45 | 0.99 | -967 / -1022 | 5.53 |
| turn 45.0 | 50.12 | 1.11 | -578 / 1129 | 64.56 |
| turn -45.0 | -53.89 | 0.93 | 812 / -947 | 15.35 |
| turn -90.0 | -95.9 | 1.53 | 1517 / -1759 | 14.77 |
| turn 90.0 | 93.54 | 1.53 | -1293 / 1867 | 36.33 |
| straight 70.0 | 3.49 | 0.96 | 871 / 878 | 0.80 |
| straight -70.0 | -2.1 | 0.96 | -830 / -831 | 0.12 |

Geçersiz/başlatılmayan denemeler:
- turn 90.0: Telemetry gap or reboot, son geçerli açı 17.17°; dur yanıtı OK
- turn 90.0: Not stationary, son geçerli açı 0°; dur yanıtı OK
- turn 180.0: Telemetry gap or reboot, son geçerli açı 78.85°; dur yanıtı OK

Eski → yeni dönüş sonuçları: +45: 46,28 → 50,12; -45: -49,77 → -53,89; +90: 93,71 → 93,54; -90: -97,61 → -95,90. Eski tek ölçüm ile yeninin tek geçerli ölçümü karşılaştırılmıştır; kesin teker etkisi ayrıştırılamaz.

Yeni düz sürüş ileri -2,30 / +3,49°, geri -2,45 / -2,10°. Eski ileri +0,84°, geri -0,08°. Enkoder farkı yeni ileri %13,59 / %0,80, geri %5,53 / %0,12; eski %21,1 / %11,9. Tik dengesi iyileşse de IMU yön doğruluğunda iyileşme görülmedi. Sabit trim için ileri sapma işareti tutarlı değil.

Teker çapı, etkin yuvarlanma çevresi ve zemin koşulları ölçülmedi. Tik sayısından gerçek hız/mesafe artışı çıkarılamaz. Çap değiştiyse odometri ticks_per_meter fiziksel mesafe ile yeniden kalibre edilmeli.

İki hareket denemesi 200 ms örnekleme sınırı nedeniyle kesildi, bir deneme hareketsizlik kontrolünden geçmedi. Sonrasında IMU tekrar kararlı ve uptime ilerliyor; reset bulgusu yok. 180° için geçerli sonuç yok. İletişim kaynaklı kesintiler giderilmeden HTTP tabanlı hassas açı değerlendirmesi sınırlıdır.
