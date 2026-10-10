# Sensör kontrolü ve kısa hareket doğrulaması

Standart launcher: logs/run-20261004-000224. Nav2/keşif kapalı.
Mevcut config 13816 tik/m, etkin iz genişliği 0.142 m; değiştirilmedi.

Hareketsiz: enkoder kayması 0/0, IMU 10 Hz, gyro std 0.12–0.15 dps.
LiDAR durağan x std 0.38–0.59 mm, eşleştirme RMSE yaklaşık 6 mm.

| Test | LiDAR | IMU yön değişimi |
|---|---|---|
| İleri | 0.1580 m, +0.51° | +0.36° |
| Geri | -0.1609 m, -2.00° | -1.88° |
| +45° dönüş | +46.50° | +46.03° |
| -45° dönüş | -45.20° | -45.24° |

Kısa doğrulama çifti yaklaşık 14132 tik/m (%2.3 mevcut ayardan fazla).
Tek çift ve kısa mesafe nedeniyle yeniden ayarlama yapılmadı. Hesap mevcut
scriptin LiDAR x yaklaşımını kullanır; LiDAR montaj ofseti/yay yolu düzeltmesi
uygulanmamıştır. Dönüş etkin genişliği iki yönde 0.1421/0.1550 m; tek sabite
zorlamak için yeterli tekrarlı veri yok. Dönüşler PWM kontrollüdür, TURNRATE
doğrulaması değildir.

Ultrasonik önceki 5–6 cm yerine kararlı 77–79 cm okuyor, ancak ileri 15.8 cm
harekette 76.95 -> 78.82 cm, geri harekette 78.79 -> 77.15 cm okudu.
LiDAR ön yüzey mesafesi 105.5 -> 89.65 -> 105.7 cm ile tarama eşleştirmesini
destekliyor. Ultrasoniğin kararlı olması doğru ön yüzeyi gördüğünü kanıtlamıyor;
yönelim, görüş alanı/şasi yansıması ve bilinen hedefle ayrıca kontrol gerekli.
Bu verilerden ultrasonik ölçek kalibrasyonu çıkarılmadı.

Test scriptine eski LiDAR verisinde durma, hareket öncesi canlı açıklık kontrolü,
düz sürüşte 8° sapma sınırı ve başarısız düz test sonrası diziyi kesme eklendi.
Ham sonuçlar logs/motion-calibration-2026-10-04/000413.json ve 000501.json.
