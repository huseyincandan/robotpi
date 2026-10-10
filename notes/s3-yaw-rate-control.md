# S3 açısal hız kontrolü — canlı ayar bekliyor

Yeni `TURNRATE <vx_pwm> <gyro_z_dps>` komutu ve HTTP
`/turnrate?vx=0&dps=20` uç noktası, PWM tabanlı DRIVE'dan ayrıdır.
Gyro Z işareti kullanılır. Hedef en fazla ±60°/s, ileri PWM ±155,
dönüş düzeltmesi ±100 PWM. Kontrol 50 Hz; başlangıç kazançları Kp=0,4,
Ki=4,0 ve ön besleme 55 sign(rate)+0,35 rate. Bunlar henüz yerde
ayarlanmamıştır. PWM değişimi 160 birim/s ile sınırlıdır; sıfır hareket
hedefi ve STOP doğrudan frenler. IMU/kalibrasyon geçersizliği veya kontrol
zamanlaması boşluğu durdurur. Mevcut komut watchdog'ları korunur.

Pi `/drive` uç noktasına isteğe bağlı `yaw_rate_dps` eklendi. Motor servisi
bu değeri TURNRATE ile gönderir ve aynı komutu keepalive'da tekrarlar.
Mevcut engel/sensör kontrolleri korunur. Nav2 köprüsü
`--s3-yaw-rate-control` ile rad/s hedefini derece/s'ye çevirir; bu modda
eski minimum dönüş PWM yüzdesi uygulanmaz. Launcher seçeneği
`MAP["ROS2_S3_YAW_RATE_CONTROL"]`, canlı doğrulamaya kadar **False**.
İleri hız hâlâ PWM'dir; tam teker hız kontrolü eklenmedi.

Tamamlanması gereken fiziksel testler:
1. Tekerler havada, motorlar kapalıyken önce sol sonra sağ tekerin tam
   5 turundaki enkoder farklarını ölç. Her ölçüm öncesi/sonrası sayaç oku.
2. Robot tekrar yerdeyken ±10, ±20, ±30°/s hedeflerini kısa sürelerle
   karşılaştır; hız, salınım, doygunluk ve duruş süresini ölçerek kazançları ayarla.
3. Hedefe yaklaşırken açı hatasına göre hız isteğini azaltarak her yönde
   45/90/180° dönüşleri en az üçer kez tekrarla. Fiziksel açıyla karşılaştır.
4. İşaretli/ölçülmüş mesafede ileri-geri odometriyi doğrula.
5. Yalnız bu kontrollerden sonra Nav2 seçeneğini açıp LiDAR ile hedef
   navigasyonunu mevcut RUNBOOK launcher'ı üzerinden test et.

Host kontrolleri:
`python3 scripts/test_yaw_rate.py`
`python3 scripts/test_motor_rate_protocol.py`
`python3 scripts/test_gyro_calibration.py`

Bu testler gerçek motor dinamiği veya kazanç kararlılığını doğrulamaz.

Elle enkoder karşılaştırması (2026-10-01): Sol 5 tur +13.861 tik
(~2.772/tur), sağ 5 tur +13.692 tik (~2.738/tur). Diğer tekerin sayacı
her ölçümde sabit kaldı. Kullanıcı iki tekerde de başlangıç/bitiş hizasının
kesin olmadığını belirtti. Gözlenen fark %1,23; beş turluk toplamlar
arasında yaklaşık 22° hizalama farkına eşdeğer. Belirsizlik sınırı
ölçülmediğinden bu fark ölçek düzeltmesi için kullanılmadı. Bu ölçüm,
önceki sürüşte görülen %12–21 tik farkının sabit enkoder ölçek farkından
kaynaklandığına güçlü kanıt sağlamıyor; mekanik/dinamik sebepler açık.
Yerde hız kontrolü testinden önce robotun tekrar yere indirildiği doğrulanmalı.
