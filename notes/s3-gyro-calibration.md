# S3 gyro kalibrasyonu

Açılışta motor çıkışları frenlenir. Ana döngü başladıktan sonra kalibrasyon,
komut işlemeyi veya watchdog'u bloke etmeden yapılır. Motor komutları sıfır,
enkoderler sabit, ivme büyüklüğü 0,85–1,15 g ve üç gyro ekseni ±5°/s içinde
olmalıdır. Her eksenin ölçüm aralığı iki saniye boyunca en fazla 0,8°/s
olmalıdır; en az 80 örnek gerekir. Hareket veya 100 ms üzeri örnek arası
boşluk pencereyi sıfırlar. Koşullar sağlanana kadar kalibrasyon bekler.

Yeniden kalibrasyon: HTTP `POST /gyro/calibrate` veya seri hat üzerinden
`GYRO_CALIBRATE`. Motorlardan biri komut alıyorsa istek reddedilir; önce
`STOP` / `/stopall` kullanın. Kabul edilen istek eski kalibrasyonu geçersiz
kılar. Robotu sabit tutun ve `/status` alanlarını izleyin:

- `gyroCalibration`: `waiting`, `collecting`, `ready`
- `gyroBiasReady`: geçerli ofset varsa 1
- `gyroCalSamples`: mevcut pencerenin örnek sayısı
- `rawGyroZ`, `gyroBiasZ`, `correctedGyroZ`: ham hız, ofset, fark (°/s)
- `imuValid`: son sensör ölçümü geçerli ve en fazla 100 ms yaşındaysa 1

Kalibrasyon yokken `correctedGyroZ=nan` gönderilir; tüketiciler hem
`gyroBiasReady` hem `imuValid` kontrol etmelidir. Gyro tabanlı düz sürüş
asistanı kalibrasyon tamamlanana kadar kapalıdır; enkoder kontrolü ve manuel
motor komutları çalışmaya devam eder. Sensör okuma hatası kalibrasyonu
geçersiz kılar ve hareketsizken yeniden ölçüm gerektirir.

Eski küçük-hata otomatik ofset takibi kaldırıldı; geçerli ofset yeni bir
kalibrasyona veya sensör okuma hatasına kadar sabit kalır. Sıcaklık kaynaklı
kayma görülürse robot dururken yeniden kalibre edin. Bu kontroller harici bir
sabitlik referansı değildir: enkoderler değişmeden tüm robotun çok yavaş,
sabit hızla taşınmasını kesin olarak ayırt edemez. Kalibrasyon sabit zeminde
yapılmalıdır. Eşikler gerçek donanımda doğrulanmalıdır.

UART `TELEM` biçimi ve ham gyro verisi değişmedi; Pi kendi ofsetini uygular.
Donanım kullanmadan kontrol: `python3 scripts/test_gyro_calibration.py`.
Bu kontrol gerçek kalibrasyon fonksiyonlarını host C++ derleyicisinde sentetik
ölçümlerle çalıştırır; ESP32 firmware derlemesi veya canlı test yerine geçmez.
