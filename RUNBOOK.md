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

## 2026-10-11 genel keşif denemesi

Uygulama `scripts/run_app.py --launch-mode manual` ile açıldı. Robotun önceki
güne göre konumu değiştiğinden harita `output/maps/pre-general-test-20261011-082939`
altında arşivlenip `/map/reset` çağrıldı. İlk sıfırlama, Nav2/odometri köprüleri
henüz kapalıyken `/set_pose` zaman aşımına uğradı ve 20 s içinde harita çıktısı
vermedi. Nav2 açılınca taze harita 108×60 hücre ve sıfır başlangıç pozu ile
oluştu. Test kaydı: `logs/nav2-supervised-20261011-083041`.

100 saniyelik gözetimli keşifte 1092 LiDAR taraması, 219 harita iletisi,
iki plan ve 2183 odometri iletisi kaydedildi. İki Nav2 hedefine ulaşıldı;
odometri yolu 2,626 m, net yer değiştirme 0,844 m. Bilinen boş harita
hücreleri 1555→3681, harita 108×60→186×67 oldu (5 cm/hücre). En büyük
ardışık `map→odom` düzeltmesi 4,1 cm ve 2,86° idi. Motor/sensör hatası,
çarpışma veya Nav2 kurtarma eylemi kaydedilmedi; bu nedenle yeni BackUp
dalının otomatik çağrılması bu koşuda test edilemedi.

İkinci hedef sonrasında explore_lite iki frontier bulmaya devam etti, ancak
36 aday hedefin tamamı global costmap'teki `frontier_goal_max_cost: 100`
sınırını aştı (`Frontier rejects: distance=0 direction=36 costmap=0
bounds=0 cost=36`; yön sayacı ilk geçişe ait). Son costmap'te boş maliyet
2197 hücre, 101-252 arası şişirilmiş maliyet 4374 hücreydi; 1-100 arası
hücre yoktu. Keşif kalan süreyi `no_safe_frontier` durumunda durarak
geçirdi. Bu kayıt haritalamanın çalıştığını gösterir, ancak odanın tümünün
haritalandığını göstermez. Hedef yerleştirme ile maliyet eşiği beraber
incelenmelidir; sırf ilerlesin diye çarpışma sınırı yükseltilmemelidir.

### Frontier hedefi kök neden incelemesi ve düzeltme

Sabit 40 cm geri çekilme, bir frontier'ın robotla arasındaki doğru üzerindeki
her hedefi şişirilmiş maliyet bölgesine düşürüyordu. `frontier_goal_max_standoff`
ile önce aynı doğruda 40–100 cm aralığı taranıyor. Doğrusal arama başarısızsa
global costmap'te robota düşük maliyetli hücrelerle bağlı olan, frontier'a
40–100 cm mesafedeki bilinen boş hücreler deneniyor. `frontier_goal_max_cost`
100 olarak kaldı; bilinmeyen veya yüksek maliyetli hücreye hedef gönderilmiyor.
Explore fork'unun tekrarlanabilir kaynak farkı
`patches/m-explore-integrated-20261010.patch` dosyasına işlendi.

İlk canlı denemede doğrusal arama 50 cm geri çekilmiş hedef seçti. Robot
yaklaşık `(0,24; -0,63)` odometri konumuna giderek `(0,29; -0,60)` hedefinin
10 cm konum toleransına ulaştı, ancak zorunlu son yön düzeltmesini 39 cm
önündeki duvar yakınında tamamlayamadığı için Nav2 `Failed to make progress`
ve BackUp üretti (`logs/nav2-supervised-20261011-084117`). Frontier hedefleri
gözlem konumları olduğundan Nav2 goal checker
`nav2_controller::PositionGoalChecker` olarak değiştirildi; canlı ROS parametresi
bu eklentinin yüklendiğini doğruladı. Bu değişiklik Nav2'nin diğer hedefleri
için de son yaw koşulunu kaldırır; özel son yön gerektiren ilerideki eylemler
ayrı bir goal checker veya son dönüş eylemi kullanmalıdır.

İkinci denemede robotun eski konumundan doğrusal arama hedef bulamadı;
bağlı hücre araması `forward/connected` modunda 1,11 m uzakta güvenli hedef
buldu. Nav2 hedefe ulaştı ve haritadaki bilinen boş alan 3860→3927 hücreye
çıktı (`logs/nav2-supervised-20261011-084712`, 547 tarama, 1,43 m odometri
yolu). Önceki denemede 3681→3863 hücre, 643 tarama ve 2,34 m odometri yolu
vardı. İkinci hedef sonrasında kalan tek frontier `(-2,21; 0,72)` merkezli,
17 hücreli; tüm doğrudan hedefler maliyet sınırını aşıyor. Son costmap/map
kaydında robotun düşük maliyetli bağlı bölgesinden bu frontier'a en yakın
aday yaklaşık 1,98 m uzakta; 1 m gözlem bandına erişilebilir hücre yok.
Bu, kalan sınırın mevcut harita/engel/şişirme koşullarında erişilemediğini
gösterir. Odanın tümünün eksiksiz haritalandığı iddia edilmemeli; dar geçidin
fiziksel genişliği ve LiDAR'da görünen duvar çizgisi yerinde doğrulanmadan
maliyet sınırı gevşetilmemeli. Denemeler sonunda explore, Nav2 ve motorlar
durduruldu.

## 2026-10-14 koridor testi

Robot koridora taşındıktan sonra eski harita `output/maps/pre-corridor-test-20261014-1843/`
altına arşivlendi ve yeni SLAM haritası başlatıldı. Nav2 ileri yönlü 18 cm
diferansiyel State Lattice (`config/lattice_primitives_diff_18cm.json`) ve
`FollowPath.use_rotate_to_heading=true`, `allow_reversing=false` ile çalışıyor.
İlk karşılaştırmada planlar ileri yönlü olduğu halde denetleyici ters sürüş
üretiyordu; bu iki ayar düzeltildikten sonra ileri sürüş baskın hale geldi.

İlk uzun denemede robot yaklaşık 2,2 m yer değiştirdi ve harita büyüdü, ancak
sol LiDAR ~28 cm yakınındaki bir engel ile önde LiDAR'ın görmediği alçak engel
yakınında kurtarma başarısız oldu (`logs/nav2-supervised-20261014-184837`).
Kullanıcı alçak engelin gerçek olduğunu doğruladı. Özerk sürüşün ultrasonik
yakın durdurması daha önce kapatılmıştı; tekrar açıldı ve ~9,34 cm okumada
Nav2 kaynaklı ileri komutun `BLOCKED/ultrasonic` döndüğü canlı doğrulandı.

Ultrasonik 9,34 cm değerinde hareket sırasında bile değişmeyince gpiozero'nun
başarısız yankıları smoothing kuyruğunda yok sayıp eski değeri tutabildiği
yerel kütüphane kodunda görüldü. `FreshDistanceSensor` son geçerli yankının
zamanını izliyor; 0,5 s içinde yankı yoksa hizmet eski okumayı geçersiz sayıp
örnek kümesini temizliyor. Kısa kontrollü geri testte enkoderler ~1600 tik
geriledi; uygulama yeniden başlatılınca ultrasonik ~27 cm ölçtü. Nav2'ye
yalnızca tüm pencere boyunca kararlı, güveni >=0,7 olan median Range okumaları
veriliyor; yakın tekil kümeler yalnız bağımsız motor güvenlik kontrolünde
kalıyor. Yerel ve genel RangeLayer tekrar etkin.

Filtreli RangeLayer ile 25 s gözetimli koşuda 2,69 m odometri yolu, iki
ulaşılan hedef ve bilinen serbest harita hücresinde 1635→12981 artış görüldü
(`logs/nav2-supervised-20261014-190443`). 60 s koşuda 5,06 m, 12981→17628
hücre ve üç başarılı BackUp; arada bir planlama ve ilerleme hatası oldu ama
keşif başka hedeflere devam etti (`logs/nav2-supervised-20261014-190546`).
90 s koşuda 7,87 m odometri yolu, 17856→22571 serbest hücre, iki başarılı
BackUp ve iki başarısız hedef görüldü; robot süre sonuna kadar hareket etti
(`logs/nav2-supervised-20261014-190744`). Bu sayaçlar haritanın tamamlandığı
veya her koşulda otonom kaçışın garantilendiği anlamına gelmez. Test sonunda
explore, Nav2 ve motorlar durduruldu; pil ~11,78 V idi.

Ek doğrulama: 45 s yakın mesafe denemesinde gözetim betiğinin sabit 32 cm
ön eşiği, Nav2'nin geri/dönüş kurtarmasını erken kesiyordu. Betik artık bu
eşiği yalnız gerçekten ileri sürerken uygular; her yönde 18 cm mutlak sınır
ve 12 cm kararlı ultrasonik alçak-engel sınırı korunur. Bu durumda robot
güvenli şekilde dönüp 5,14 m yol aldı; harita 24455→25581 serbest hücreye
çıktı (`logs/nav2-supervised-20261014-193309`).

120 s denemede 8,57 m yol alınmasına karşın harita yalnız 25582→25973
serbest hücre büyüdü (`logs/nav2-supervised-20261014-193447`). Motorun
`motion_stall` engeli, kısa geri kaçıştan sonra ileri komutları uzun süre
reddedebiliyordu: önceki yönü açmak için 6 cm öteleme şarttı. Bağımsız
gövde pozu 0,35 rad dönerse veya LiDAR'ın en az iki sektörü anlamlı değişirse
eski yön engeli de artık kaldırılır (`services/motion_progress.py`). Bu,
fiziksel olarak dönmeyen teker hareketinin kilidi kaldırmasına izin vermez.
Uygulama bu kodla yeniden başlatıldı. Sonraki 60 s koşuda 4,96 m yol,
2534→16276 serbest hücre, bir hedef başarısı ve güvenli geri kurtarma görüldü;
sonda `motion_stall_blocked_direction=null`, motorlar ve Nav2 duruyordu
(`logs/nav2-supervised-20261014-193751`). Bir başka hedef, gerçek yerel
maliyet haritasında ayak izi yakınında 0,22 m'de öldürücü engel varken RPP
çarpışma öngörüsüyle reddedildi; explorer alternatif hedef seçti. Bu son
hedef hatası serbest yol varmış gibi davranılarak giderilmemeli. IMU bir
`impact` durdurması kaydetti; fiziksel temas olup olmadığı doğrulanmadı.
Koridorun/evin tüm haritasının tamamlandığı henüz doğrulanmadı.
