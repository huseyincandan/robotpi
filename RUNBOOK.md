# Çalıştırma ve log düzeni

Geliştirme/test ve GPIO26 üretim başlatması aynı launcher'ı kullanır. Uygulama
ve ROS düğümlerini ayrı terminallerden elle başlatmayın.

## Geliştirme veya test

```bash
.venv/bin/python scripts/run_app.py --launch-mode manual
```

Bu launcher çalışma dizinini ayarlar ve uygulamayı başlatmadan önce ROS
ortamlarını doğru sırayla yükler:

1. `~/.micromamba/envs/ros2_jazzy/setup.bash` (ROS 2 Jazzy underlay)
2. `~/ros2_nav_ws/install/setup.bash` (robotun ROS workspace'i)

Uygulamayı doğrudan `uvicorn app:app` ile veya ayrı bir ROS ortamı kaynak
ederek başlatmayın. ROS CLI komutlarını elle çalıştırırken de aynı iki setup
dosyasını aynı sırayla kaynak edin. Daha önce tanı sırasında yanlışlıkla
`~/ros2_ws/install/setup.bash` kullanılmış ve Python/ROS uyuşmazlığı olduğu
sonucu çıkarılmıştı; bu teşhis geçersizdi. Doğru workspace ve underlay ile ROS
mesaj tipleri ve TF kontrolü çalışıyor.

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

## 2026-10-10 navigasyon kalibrasyonu

`base_link` arka tahrik aksının dönme merkezindedir. Yerinde dönüşte LIDAR'ın
aksın yaklaşık 7 cm önünde olduğu ardışık taramalarla ölçüldü; eski -8,5 cm
ofseti gövde merkezine göreydi. `config.py` LIDAR ofseti +0,07 m, Nav2
footprint'i de aynı aks referansındadır. Doğrulama kaydı:
`logs/laser-tf-validation-20261010-151030` ve
`logs/motion-calibration-2026-10-10/151054.json`.

LIDAR `/scan` açısı aynı fiziksel ışınlarla `[-pi, pi)` sırasına alındı. Bir
SLAM sıfırlamasından sonraki eski küçük harita robotun önünü kapsamıyordu;
uygulama yeniden başlatılıp açı sırası düzeltildikten sonraki ilk harita önü
kapladı. Bu iki işlemin etkisi ayrı ayrı ölçülmediğinden 180° SLAM sıçramasının
kalıcı olarak giderildiği varsayılmamalıdır. Harita sıçrama izleyicisi açık
kalır ve sıçramada keşfi durdurur.

`run_supervised_explore.py` süreli hareket testini ROS bag ile kaydeder ve
sonunda keşfi, motoru ve Nav2'yi durdurur. `--front-abort-cm` değeri LIDAR
ile ön tampon arasındaki yaklaşık 20 cm dikkate alınarak seçilmelidir.
`logs/nav2-supervised-20261010-152542` denemesinde 40 saniyede altı Nav2
hedefine ulaşıldı; yaklaşık 4,3 m odometri yolu kaydedildi. Yakın alan
denemesi `logs/nav2-supervised-20261010-151609` önceki XY-only ilerleme
denetçisinin yerinde dönüşü yanlışlıkla başarısız saydığını gösterdi; artık
`PoseProgressChecker` hem dönüşü hem konum değişimini izliyor.

Haritalama Nav2 kapatılınca da çalışır; bu nedenle `/nav2/stop` yalnızca
keşif ve Nav2'yi durdurur. Odometri, IMU ve EKF köprüleri uygulama kapanana
kadar açık kalır. Önceki yaşam döngüsünde bu üçü durunca SLAM 48° ve 177°
yapay yön sıçramaları üretmiş, izleyici de haritayı sıfırlamıştı. Düzeltme
sonrası Nav2 kapalıyken bir dakika boyunca harita güncellendi ve durağan
pozun en büyük yön adımı 0,01° oldu. `/nav2/start` köprüleri yeniden
başlatmadan Nav2'yi geri açtı.

## 2026-10-10 küçük haritadan keşfe başlama

İlk sıfırlama denemesinde explore_lite tek frontier bulduğu halde robot hiç
hareket etmedi. Tanılama sayacı 696 aday noktanın tamamının yalnızca
`min_goal_distance + frontier_goal_standoff = 0,85 m` koşuluyla elendiğini
gösterdi; maliyet veya yön reddi yoktu. Motor arızası değildi.

Asıl haritalama zincirinde `/odom` 1,3°→91,6° ve `/scan` 255 mesaj değişirken
52 `/map` mesajının tümü aynı kaldı (`logs/slam-turn-diagnostic-live`).
`check_min_dist_and_heading_precisely: true` ile SLAM yerinde dönüşte de yeni
tarama ekliyor. 1° LIDAR ışınları için 2,5 cm hücre ve iki geçiş koşulu çok
seyrek bir başlangıç haritası bırakıyordu; harita 5 cm ve
`min_pass_through: 1` yapıldı. Düzeltme sonrası 90° dönüşte bilinen boş hücre
sayısı 532→2695 çıktı.

Normal ayarlarla `logs/nav2-supervised-20261010-201229` denemesinde 35 saniye
keşif çalıştı, iki hedef tamamlandı, odometri yolu 2,58 m oldu. Bilinen boş
hücreler 1049→5476, harita 190×68 hücreye genişledi; en büyük ardışık
`map→odom` yön adımı 3,06° idi. Yakın frontier dışında hiç aday yoksa yama
uygulanmış explore_lite Nav2 `Spin` eylemiyle en fazla dört çarpışma denetimli
45° tarama yapıyor. 10 m test eşiğiyle bu dal dört kez tamamlandı, sonra
durdu; normal eşik 0,45 m'ye geri alındı.

İkinci normal keşif `logs/nav2-supervised-20261010-201728` kaydında yaklaşık
3,09 m odometri yolu ve bir tamamlanan Nav2 hedefi üretti; bilinen boş
hücreler 4107→5550 oldu. Sağ LIDAR sektörü 24,2 cm'ye düşünce test
betiğinin 25 cm çevre sınırı keşfi ve Nav2'yi durdurdu. Bu, tüm odanın
tamamlandığı anlamına gelmez. Test sonrasında robot sağ yanda yaklaşık
23 cm açıklıkla duruyor; sonraki hareket testi mevcut konumdan başlarsa
önce çevre açıklığı yeniden ölçülmelidir.

Üçüncü normal keşif `logs/nav2-supervised-20261010-201926` kaydında robot
sağda 23 cm açıklıkla başladığı yerden uzaklaşarak 4,47 m odometri yolu
katetti. Haritadaki bilinen boş hücreler 5511→6333 oldu; 107 harita iletisi
kaydedildi. Gözetimli testin yan açıklık sınırı bu denemede 20 cm idi;
Nav2 hareket etmeyi sürdürürken ön LiDAR 31,42 cm ölçünce 32 cm ön sınırı
testi durdurdu. Keşif, motor ve Nav2 durdu; ardından motor komutu sıfır
doğrulandı. Bu deneme dar yan açıklıktan çıkıp haritayı büyütebildiğini
gösterir, ancak odanın tamamının haritalandığını göstermez.

Çalışan ROS forkunun birleşik yaması
`patches/m-explore-integrated-20261010.patch` dosyasındadır. Bu yama eski
parçalı `m-explore-*.patch` dosyalarına ek olarak değil, temiz upstream
forkuna tek başına uygulanır; ardından `explore_lite` yeniden derlenir.

## 2026-10-10 sıfırdan oda keşfi denemesi

`/map/reset` eski harita arşivlendikten sonra başarılı oldu (`odom_reset=true`,
`outputs_ready=true`). Kullanıcının isteğiyle robot önünde 31 cm LiDAR
açıklığı olan mevcut konumdan, Nav2 çarpışma denetimi açıkken 45 saniyelik
gözetimli keşif yapıldı: `logs/nav2-supervised-20261010-205013`. 543 tarama,
110 harita iletisi, 5 yol planı kaydedildi. Bilinen boş hücreler 879→5393,
odometri yolu 3,48 m oldu. En büyük ardışık `map→odom` düzeltmesi 8,7 cm ve
2,26° idi. İlk Nav2 hedefi tamamlandı.

Denemenin sonunda ön LiDAR yaklaşık 20-23 cm ölçtü; ultrasonik yaklaşık 8 cm
gösterdi. Nav2 denetleyicisi dört kez `detected collision ahead` dedi.
Mevcut kurtarma ağacı her seferinde 0,60 rad Spin denedi, fakat davranış
sunucusu `Collision Ahead - Exiting Spin` ile döngüyü reddetti. Keşif yeni
frontier hedefleri seçse de robot o yakınlıkta ilerleyemedi. Test süresi
dolunca keşif, motor ve Nav2 kapatıldı; motor komutu sıfır doğrulandı. Bu
deneme sıfırdan haritanın büyüdüğünü, fakat tam oda kapsamının henüz
doğrulanmadığını gösteriyor. Son pozda ön açıklık kritik olduğundan başka
hareket denemesi önce güvenli geri kaçış/kurtarma tasarımı ya da fiziksel
yeniden konumlandırma gerektirir.

Bu durumdan sonra kurtarma ağacı tek bir hedef için en fazla bir kez
çarpışma denetimli 18 cm/0,08 m/s BackUp deneyip yeniden planlayacak şekilde
değiştirildi; geri hareket güvenli değilse 0,60 rad Spin denenir. İkinci
FollowPath hatası hedefi explore_lite'a başarısız döndürür; fork gerçek
Nav2 abort hata kodunu taşıyan hedefi kara listeye alır. Pi motor katmanı
geri giderken arka LiDAR açıklığını 50 ms aralıkla ayrıca denetler.
15 birim testi geçti ve Nav2 yeni BT ile açıldı. Canlı geri hareket testi
henüz yapılmadı: mevcut pozda ön LiDAR ~22 cm, ultrasonik ~8 cm, dinlenme
gerilimi ~10,96 V. Ultrasonik sensör LiDAR ile aynı yükseklikte değildir
(kullanıcıya göre aralarında 10-12 cm var); iki değerin aynı nesneyi
göstermesi beklenmemelidir. Şarjdan sonra arka açıklık ölçülerek kısa
fiziksel kaçış testi yapılmalıdır.

Kullanıcının düşük pille tek kısa teste onayı üzerine, mevcut pozda Nav2
`/backup` eylemine `target.x=-0.18 m`, `speed=0.08 m/s`, `time_allowance=8 s`
gönderildi. Eylem 2,33 s'de `SUCCEEDED`, `error_code=0` ile tamamlandı;
geri gidilen odometri mesafesi 0,1800 m. Test öncesi arka LiDAR yaklaşık
131 cm, ön LiDAR 22 cm; sonrası arka yaklaşık 182 cm, ön yaklaşık 29 cm
(sektör minimumları geometri nedeniyle 18 cm bire bir değişmek zorunda
değil). Test sonu pil 10,904 V, motor komutu sıfır; Nav2 durduruldu.
Bu, fiziksel BackUp eylemini doğrular. Yeni BT'nin çarpışma sonrası BackUp
dalına canlı keşifte girildiği ayrıca doğrulanmadı; şarj sonrası kısa keşif
bu entegrasyon için gereklidir.
