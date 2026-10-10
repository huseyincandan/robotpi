# 2026-10-01 S3 hareket testleri

IMU correctedGyroZ trapez integrasyonu, HTTP üzerinden Pi kontrolü. Düz sürüş ±70 PWM, yaklaşık 1 saniye; dönüş 80 PWM, son 20° için 72 PWM. Her test tek deneme. S3 gyro ofseti 0,335°/s. Bağımsız fiziksel açı/mesafe ölçümü yapılmadı.

| Test/hedef | IMU açı (°) | Süre (s) | RL/RR tik |
|---|---:|---:|---|
| straight 70 | 0.84 | 0.97 | 616 / 761 |
| straight -70 | -0.08 | 1.0 | -733 / -826 |
| turn 45 | 46.28 | 1.09 | -514 / 1283 |
| turn -45 | -49.77 | 0.99 | 826 / -1082 |
| turn 90 | 93.71 | 1.6 | -1266 / 2123 |
| turn -90 | -97.61 | 1.6 | 1626 / -1899 |
| turn 180 | 180.63 | 3.24 | -2296 / 4242 |
| turn -180 | -185.5 | 3.04 | 3028 / -3665 |

Düz sürüşte son yön sapması küçük; ileri enkoder farkı ortalamaya göre %21,1, geri %11,9. Dönüşlerde sağ teker tik büyüklüğü her testte daha yüksek. Sebep tek başına bu verilerden belirlenemez (mekanik fark, sürüş, enkoder ölçeği veya kayma araştırılmalı).

Dönüş hedef aşımı 0,63–7,61°. Ters yön testlerinde aşım daha büyük. Dur isteği öncesi son ölçümden duruş sonuna 1,0–5,9° ek açı gözlendi; HTTP/örnekleme gecikmesi ve mekanik duruş etkileri bu testte ayrıştırılmadı. Tepe hızları 66–76°/s. S3 içinde dönüş hız kontrolü ve hedefe yaklaşırken kontrollü yavaşlama önerilir.

Tüm testlerde dur yanıtı OK; timeout, geçersiz IMU veya reboot saptanmadı. Testler sonunda enkoderler sabit ve IMU geçerli. Açılar IMU tahminidir; tek denemeler tekrarlanabilirlik veya uzun mesafe navigasyon doğrulaması değildir.
