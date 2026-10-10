# Pi üzerinden S3 derleme ve yükleme

Araçlar `.arduino-local/` içinde tutulur ve Git'e eklenmez. Arduino CLI
1.5.1 ve Espressif ESP32 core 3.3.10 kullanılır. Paket ve derleme önbelleği de
aynı dizindedir. Grafik arayüz veya arka plan servisi gerekmez.

Proje kökünden doğrulanmış ESP32-S3 profiliyle derleme:

```bash
python3 scripts/s3_firmware.py build
```

Kullanıcının çalışan OTA ayarları varsayılandır: ESP32S3 Dev Module,
4 MB flash, PSRAM Disabled, Default 4MB with spiffs, QIO 80MHz.
Tam FQBN: `esp32:esp32:esp32s3:FlashSize=4M,PSRAM=disabled,PartitionScheme=default,FlashMode=qio`.
Betik ESP32 paket sürümünün 3.3.10 olduğunu doğrular.
Kart seçeneklerini listelemek için:

```bash
.arduino-local/bin/arduino-cli --config-file .arduino-local/arduino-cli.yaml board details --fqbn esp32:esp32:esp32s3
python3 scripts/s3_firmware.py boards
```

Doğrulanmış tam FQBN ve S3 IP adresiyle yükleme biçimi:

```bash
python3 scripts/s3_firmware.py upload --port 'S3_IP_ADRESI' --protocol network
```

OTA parolası CLI tarafından istenir. USB yükleme için port `/dev/ttyACM0`
gibi bir cihaz yolu, protokol `serial` olmalıdır. Yükleme öncesinde robotu
ve navigasyonu durdurun; USB portunu başka bir süreç kullanmamalıdır.
S3 üzerinde OTA destekli firmware ve OTA uyumlu bölüm düzeni bulunmalıdır.

Betik her yüklemeden önce mevcut `MotorEspS3.ino` dosyasını yeniden derler.
Arduino'nun klasör/ad eşleştirme gereksinimi için geçici sketch kopyası
`.arduino-local/sketch/MotorEspS3/` içinde oluşturulur. Asıl kaynak kökteki
`MotorEspS3.ino` dosyasıdır. Binary çıktıları `.arduino-local/firmware/` içindedir.

Kurulu paketleri ve alan kullanımını görmek için:

```bash
.arduino-local/bin/arduino-cli --config-file .arduino-local/arduino-cli.yaml core list
du -sh .arduino-local
```

Canlı doğrulama: ESP32 core 3.3.10 ve yukarıdaki FQBN ile program
1.031.476 bayt (%78), global RAM 53.076 bayt (%16). OTA hedefi
192.168.1.168 (robomotor.local); yükleme başarılı. Açılış kalibrasyonu
101 örnekle ready, gyroBiasZ=0,274°/s; 20 hareketsiz durum örneğinde
düzeltilmiş gyro ortalaması -0,014°/s (aralık -0,289…0,192°/s).
Motor hareket testi yapılmadı.
