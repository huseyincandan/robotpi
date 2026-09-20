# Çalıştırma ve log düzeni

Geliştirme/test ve GPIO26 üretim başlatması aynı launcher'ı kullanır. Uygulama
ve ROS düğümlerini ayrı terminallerden elle başlatmayın.

## Geliştirme veya test

```bash
.venv/bin/python scripts/run_app.py --launch-mode manual
```

## Üretim / GPIO26

`hamsibot-gpio26-autostart.service`, GPIO26 kapalıysa aynı launcher'ı
`--launch-mode gpio26` ile çağırır. Servis günlüğü:

```bash
sudo journalctl -u hamsibot-gpio26-autostart.service -f
```

## Bir çalıştırmanın logları

Her başlatma `logs/run-YYYYMMDD-HHMMSS/` altında tek bir dizin oluşturur:

- `metadata.txt`: başlatma modu, çalışma dizini ve uygulama Python'ı
- `app.log`: FastAPI, motor, IMU ve watchdog kayıtları
- `nav2.log`, `explore.log`: planlama/hedef ve keşif kayıtları
- `cmdvel_bridge.log`, `imu_bridge.log`, `ekf.log`: ROS köprüleri

Bir teşhiste yalnızca aynı `run-*` dizinindeki dosyaları karşılaştırın.
`/tmp/robotpi_*.log` eski çalıştırmalardan kalmış olabilir; artık yeni
çalıştırmaların kaynak kaydı değildir.
