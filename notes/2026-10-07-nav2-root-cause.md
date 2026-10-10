# Nav2 kök neden incelemesi — 2026-10-07

## Son durum

Uygulama `scripts/run_app.py --launch-mode manual` ile çalışıyor. ROS 2 Jazzy
ortamı ve Nav2 ayakta; son testten sonra Explore durduruldu. Uygulamayı veya
Nav2'yi yeniden başlatmak şu an gerekmiyor. Devam testi için kullanılan kısa
komut:

```bash
curl -sS -X POST http://127.0.0.1:5000/explore/start
sleep 12
curl -sS -X POST http://127.0.0.1:5000/explore/stop
```

## İncelenen kayıt

Bag: `logs/nav2-resume-20261007-215743/`

Kayıt yaklaşık 23.05 saniye / 11 MiB; `/scan`, `/evaluation`, `/cmd_vel_nav`,
`/cmd_vel_smoothed`, `/cmd_vel`, `/odom`, `/plan`, `/received_global_plan`,
`/local_costmap/costmap_raw`, `/tf` içeriyor. Aynı uygulama çalıştırmasının
logları `logs/run-20261007-203738/` altında.

Explore hedefi `(0.70, -1.44)` oldu; mevcut yön yaklaşık `-95°`, hedefin son
plan yönü yaklaşık `-77°`. Hareket şu sırada gerçekleşti:

1. DWB ilk değerlendirmede 203 aday üretti; 68 aday `BaseObstacle` tarafından
   reddedildi, diğerleri geçerliydi. Seçilen komutlar başlangıçta küçüktü.
2. Yaklaşık 11.4 s'de yeni değerlendirmede 192 adayın tamamı `Oscillation`
   tarafından reddedildi. `nav2.log` bunu `No valid trajectories` olarak
   kaydediyor.
3. Özel davranış ağacındaki `Spin spin_dist="0.60"` recovery yaklaşık 2 s
   boyunca `+0.45 rad/s` komut gönderdi. Odometri yaw'ı `-95°`'den `-42°`
   civarına değişti. Kullanıcının gördüğü ilk sola dönüş bu kurtarma Spin'i.
4. Nav2 hedefi yeniden denedi; DWB negatif angular komutla sağa döndü. Yaw
   tekrar `-152°` civarına geldi. Explore testi 12 s'de durdurduğu için hedef
   iptal edildi; bu nedenle kesit hedefin tamamlanması hakkında hüküm vermez.

LIDAR sektör hesabını ertesi gün yeniden doğrularken ilk analizimde bir hata
bulundu: `/scan` açıları `angle_min=0` ile `[0, 2π)` aralığında, dolayısıyla
`angle < 0` ile sağ sektörü aramam yanlıştı. Doğru wrap-around hesabıyla bag
başlangıcında ön sektörün min/medyanı yaklaşık 0.30/0.31 m, sol sektörün
0.33/0.72 m, arka sektörün 0.73/0.79 m ve sağ sektörün 0.88/1.44 m çıktı.
Ön sektördeki 30–32 cm yüzey costmap master gridinde aynı yerde 254 (lethal)
olarak bulundu. Bu yüzden önceki “sağ sektör yok” çıkarımı geçersizdir; önceki
yorum hatası için kullanıcıya açıkça düzeltme yapılmalı.

Önceki Nav2 hareket bagında ultrasonic topic yoktu. Aşağıdaki 2026-10-08 statik
bag ile o belirsizlik giderildi ve o andaki LIDAR/sonar ayrışması eşzamanlı
olarak doğrulandı.

## Teşhis ve açık sorular

- Sol yönlü dönüşün kaynağı kesin: DWB başarısızlığı sonrası BT Spin recovery.
- Sonraki sağ yönlü dönüş hedef takibinin DWB komutu; rastgele motor yönü
  hatası değil. Ancak uzun süre pivot seçmesi ayrıca incelenmeli.
- Bu bagda ilk tüm-aday reddi `Oscillation`; `oscillation_reset_time=0.2`
  ayarı bunu her seferinde önlemiyor. Önceki kayıtta küçük ters işaretli
  düzeltmeler de aynı kilitlenmeye yol açmıştı.
- Kayıtta bazı değerlendirme anlarında 192 adayın tamamı geçerli, bazı
  anlarda sadece Oscillation nedeniyle tümü reddedilmiş. Dolayısıyla
  Oscillation latch/recovery davranışı gerçek bir konu.
- Costmap master grid ve scan endpointleri eşleşiyor: örnek tarama noktaları
  aynı konumda lethal 254. Ancak `/tf_static` olmadığından scan noktalarını
  base pose'a taşıyan x/y/yaw bagda doğrulanmış değil; ayrıca obstacle/range
  layer kaynakları ayrı ayrı eşlenmedi. Hangi kaynak bu yakın/lethal noktaları
  üretiyor, gerçek engel mi yoksa yanlış sensör TF/montajı mı, henüz açık.
- İlk evaluation'da 119 adet geçerli ileri hız adayı vardı. En ucuz ileri-yay
  adayının toplam skoru 27.15 (vx=0.065, wz=-0.32), seçilen pivot adayının
  skoru 25.88 (vx=0, wz≈0.021) idi. Dolayısıyla DWB hareketi tümden
  yasaklamamıştı; BaseObstacle puanı yay adayını artırmış, costmap/path/goal
  toplam skoru pivotu az farkla tercih ettirmişti. Bu, yerinde dönüşün yakın
  costmap engelleriyle ilişkisini destekler; hangi fiziksel/layer kaynağının
  maliyet ürettiği ayrıca kanıtlanmalı.
- Gözlem: odometri x/y, pivot boyunca çok az değişti; yaklaşık 20–23 s
  aralığında ilerleme başladı. Değerlendirme tablosunda geçerli ilerleyen
  adaylar bulunduğu anlar olsa da, bagın kesitinde DWB çoğunlukla pivot komutu
  seçti. Nedenini belirlemek için her değerlendirmede tüm geçerli adayların
  skor bileşenlerini kıyaslamak ve aynı zaman damgalı costmap/scan konumunu
  analiz etmek gerekiyor.
- Bagın sonuna doğru global costmap `StaticLayer: Resizing static layer to
  609 X 560` uyarısı verdi; dinamik SLAM map güncellemesi olabilir. Bu tek
  başına dönüşün sebebi olarak doğrulanmış değil.

## Yarınki devam sırası

1. Önceki tarama hesabı hatasını kullanıcıya düzelt. Robot hareketsiz ve
   Explore kapalıyken LIDAR'ın sektör mesafelerini, ultrasonic Range'i ve
   `base_link`→`laser` TF'sini eşzamanlı al. Bu çalışma ortamından canlı Pi
   HTTP/ROS soketleri sandbox `EPERM` ile kapalı; kullanıcı Pi terminalinde
   read-only teşhis komutlarını çalıştırmalı.
2. Geometri doğrulanınca bagda tüm-aday Oscillation reddini ve önceki seçilen vx/wz işaretini
   Nav2 Jazzy Oscillation critic uygulamasıyla eşleştir; 0.2 reset time'ın
   neden latch'i sıfırlamadığını kanıtla. Bir parametre daha gelişigüzel
   değiştirme.
3. Her scan/costmap mesajı için obstacle/range/master katmanlarını ve footprint
   geometrisini eşleştir. Hangi layer 253/254 üretiyor, scan ışınıyla ve gerçek
   engelle tutarlı mı, sorularına cevap ver.
4. DWB'nin en düşük skorlu geçerli adayını ve seçilen adayı aynı evaluation
   mesajı içinde karşılaştır; saf dönüş yerine ileri-yay adaylarını hangi
   critic'in pahalılaştırdığını belirle.
5. Bulgulara göre kök sebep olan TF/sensör geometrisi, kritik durumu veya
   recovery BT akışını düzelt. Sadece ölçümle desteklenen değişiklik yap;
   sonra kontrollü kısa Explore bagı ile doğrula.

Önceki kısa denemede `oscillation_reset_time=0.2` yüklüydü; tüm aday reddi
   ve kurtarma Spin'i yine oluştu. YAML parametresinin Nav2'de yüklü olduğu
   kullanıcı `ros2 param get` ile doğruladı. Çalışma alanında çok sayıda
   kullanıcı değişikliği var; ilgisiz dosyaları değiştirmeden incele.

## 2026-10-08 devam başlangıcı

Uygulama `scripts/run_app.py --launch-mode manual` ile açıldı. İlk hazır
kontrolünde Nav2/Explore ve cmd_vel/IMU/EKF köprüleri durmuştu. Robotun o anki
konumunda LIDAR sektörleri front/left/back/right = 228.8/60.2/177.5/54.77 cm,
297 nokta gösterdi. Ultrasonik 96.35 cm bildirdi ancak `stable=false`, spread
6.43 cm idi (nearest cluster 5 örnek, spread 2.62 cm). Bu konum, önceki
21:57 bagındaki 30-32 cm ön LIDAR yüzeyiyle aynı koşul değil; o bag bulgusu
bugünkü pozisyona genellenmemeli.

Sonraki adım: Explore kapalı kalacak; kullanıcı Pi terminalinden sadece
`POST /nav2/start` ile Nav2/SLAM/bridge altyapısını başlatıp status ve sensör
hazırlığını doğrulayacak. Ardından robot hareket ettirilmeden kısa bag
alınacak: `/scan`, `/ultrasonic_range`, `/tf`, `/tf_static`, `/odom`,
`/local_costmap/costmap_raw`, `/local_costmap/published_footprint`. Bu oturumun
agent ortamı `127.0.0.1:5000` ve ROS DDS soketlerine EPERM verdiği için canlı
okumayı kullanıcı Pi terminalinden alıyor.

Nav2 başlatıldı; response `Navigation2 launch started`, ardından status
`nav2_status=running`, `explore_status=stopped`, cmdvel/IMU/EKF köprüleri
running doğrulandı. Sabit pozda API LIDAR front/left/back/right =
228.55/59.85/177.45/54.90 cm (298 nokta). API ultrasonic 96.40 cm,
`stable=true`, confidence 0.228, spread 2.32 cm.

### Eşzamanlı sabit sensör kaydı

Bag: `logs/nav2-sensor-check-20261008-203400/` (4.57 s; 45 `/scan`, 45
`/ultrasonic_range`, 1 `/tf_static`, 92 `/odom`, 5 local master costmap, 23
published footprint). Explore kapalı, hareket yok; odom tüm kayıt boyunca
`x=y=yaw=0`.

- `/tf_static`: `base_link -> laser`, xyz=(-0.085, 0, 0) m, yaw=0°.
- Ultrasonic `Range` mesajları `frame_id=base_link`; range 1.006–1.130 m,
  ortalama 1.048 m. Bridge fiziksel sensör uzaklığına x=0.115 m ofset ekliyor;
  bu değer Nav2'ye base-link merkezinden ölçülmüş gibi gönderiliyor.
- LaserScan doğrultusu base eksenine hizalı. Ultrasonic FOV'si olan ±12° içinde
  45 taramanın her birinde en yakın geçerli lidar dönüşü en az 3.175 m; bu
  aralıktaki minimumların medyanı 4.056 m. Ön 15° LIDAR sektör min değeri
  yaklaşık 2.286 m. Dolayısıyla 1.0–1.13 m ultrasonic yankısı aynı yatay ışın
  konisinde LIDAR tarafından görülmüyor.
- Local master costmap'te robot ön merkez çizgisinde x=1.05 m hücre maliyeti
  253–254, x=1.10–1.20 m aralığı lethal 254; x=0.8–0.9 m çevresi yüksek
  inflation maliyetli. Aynı yerde ultrasonic mesajı 1.0–1.13 m. LIDAR'ın
  ±12° içindeki ışınları bu yakın hücrelere düşmüyor. Lokal costmap'te static
  layer yok; bu nedenle yakın ön engel işareti `RangeSensorLayer` ile uyumlu.

### Şu anki kök bulgu

Nav2'nin bu pozda önü kapalı değerlendirmesine yol açan doğrudan girdi,
ultrasonic Range katmanıdır: yaklaşık 1.05 m'ye koni biçimli engel projekte
ediyor; eşzamanlı yatay LIDAR aynı doğrultuda 3.17 m'den yakın engel görmüyor.
Bu bir DWB eşik ayarı problemi değil, iki sensörün fiziksel gözlemi/geometrisi
arasındaki farktır. Henüz kesin olmayan nokta ultrasonic yankısının gerçek,
LIDAR düzlemi dışında kalan alçak bir nesneye mi; aşağı/yan eğimli sensörün
zemin/yansımaya mı; yoksa başka bir multipath/yankı sorununa mı ait olduğudur.
Kod ultrasonic'i `base_link` merkezine, sıfır yaw/pitch ile bağlıyor; x ofseti
0.115 m olarak range'e katılıyor. LIDAR TF x=-0.085 m/yaw0 statik transformu
alınmış ve bagde kaydedilmiş; fiziksel montaj ölçüsü yine de ayrıca teyit
edilmeli.

Sonraki adım hareket testi değil: düz, geniş, dikey bir karton/pano hedefi robot
önünde ölçülmüş yaklaşık 1.5 m'ye koyup robotu sabit tutarak LIDAR ve
ultrasonik ölçümlerini tekrar kaydet. LIDAR hedefi ~1.5 m (laser origin farkı
hesaba katılarak), Range mesajı base merkezinden ~1.5 m göstermeli. Ultrasonic
~1.0 m'de kalırsa pano öncesi yankı (zemin/yan hedef/sensör eğimi) veya
ultrasonic açı/frame varsayımı doğrulanacak. İki sensör pano mesafesinde
eşleşirse ilk yankı ortamda LIDAR düzleminden geçen başka bir cisme ait olabilir.
Sonuç görülmeden RangeSensorLayer kapatılmayacak veya gevşetilmeyecek.

### 2026-10-08 duvar hedefli tekrar kaydı

Kullanıcı robotun önünde yaklaşık 150 cm'de bir duvar olduğunu bildirdi; Nav2
running, Explore stopped kaldı ve robot sabitken `logs/nav2-wall-check-20261008-204004/`
bag'i alındı (4.60 s; 47 scan, 46 ultrasonic Range, 92 odom, 5 local raw
costmap, 23 footprint).

- API LIDAR front=157.42 cm. Ham scan'de 0° ışın medyanı 1.576 m, min/max
  1.574/1.576 m; ±15° ön koni minimumlarının medyanı 1.5745 m. Dar, kararlı
  duvar yüzeyi ve kullanıcının ~1.5 m mesafe tahminiyle uyuşuyor. LIDAR
  `base_link`'in 8.5 cm gerisinde (`base_link -> laser x=-0.085 m`), dolayısıyla
  1.576 m lazer menzili gövde merkezinden daha uzaktaki duvarı beklenen şekilde
  ölçüyor.
- API ultrasonic=90.06 cm, stable=true. Ham `/ultrasonic_range` aralığı
  0.914–1.133 m, medyanı 0.998 m. Robot sabitken değerler dar bir aralıkta
  tekrarlanıyor; bu gürültüden ziyade tutarlı ama duvarla uyuşmayan bir yankı.
  Base-link'e gönderilen Range, gerçek uygulama ölçümüne bridge'in eklediği
  0.115 m ofseti de içeriyor.
- Ham LIDAR'da merkez doğrultudaki duvar 1.576 m'de. Ultrasonic'in yaklaşık
  1.0 m'lik ölçümü bu yüzey değil; sensör daha yakın/alçak/yan bir yansıtıcı
  görüyor olabilir ya da fiziksel açı/frame kalibrasyonu hatalı olabilir.
  Pano hedefi testi bu farkı doğruladı: duvarı LIDAR doğru görüyor, Range
  katmanı duvar öncesinde bir engel projekte ediyor. Bu, Nav2'nin önü açıkken
  neden engel varmış gibi davranabildiğine dair kuvvetli ve ölçülmüş bir
  açıklama; fakat yankının fiziksel kaynağı henüz bulunmadı.
- Kayıttaki `/local_costmap/costmap_raw` master costmap'tir; tek başına hücreyi
  hangi katmanın ürettiğini ayırmaz. Önceki eşzamanlı obstacle/range layer
  sorgusu Range katmanında yakın ön alanın lethal olduğunu göstermişti. Bu
  wall bag'inde layer servisleri kaydedilmedi; bu nedenle bu özel bag'deki her
  lethal hücrenin kaynağı kesin olarak ayrıştırılmış sayılmamalı.

Takip adımı: Range katmanını devreden çıkarmadan önce ultrasonik sensörün
fiziksel beam'ini test et. Düz, dikey duvar hedefi aynı yerdeyken sensörün
önünde zemine doğru görüş hattı veya aradaki nesne olup olmadığını gözle;
sonra sensörü duvara yatay ve dik hizalı tutup aynı `/ultrasonic_range` kaydını
al. Mümkünse karton hedefi LIDAR ve sonar düzleminde aynı anda kaplayacak
yükseklikte tut. Okuma ~1.5 m'ye yaklaşırsa sorun mevcut görüş/yansıma veya
montaj açısıdır; ~1.0 m'de kalırsa HC-SR04/sensör yazılımı ya da kalibrasyonu
incelenmeli. Nav2 hareket denemelerini Range kaynağı anlaşılana kadar
beklet; katmanı kapatma/threshold değiştirme.

### Ultrasonic Range-layer A/B denemesi (2026-10-08)

`config/nav2_params.yaml` içindeki local ve global `range_layer.enabled` geçici
olarak `false` yapıldı; YAML parse edildi, obstacle layer `true` kaldı. Pi'de
Nav2 stop/start sonrasında iki `ros2 param get` de `False` döndü. 10 s Explore
denemesinde aynı DWB abortu yine çıktı:

```
No valid trajectories out of 192!
0.08: Oscillation/Trajectory is oscillating.
0.92: RotateToGoal/Nonrotation command near goal.
Running spin
```

Yeni app logu `logs/run-20261008-203130/nav2.log`: hedef (0.24, 0.63), ret
yaklaşık 9.5 s sonra. `BaseObstacle` ret gerekçeleri görünmüyor; bu olayda
Range katmanı DWB'nin tüm adayları reddetmesinin doğrudan sebebi değil. Bu,
ultrasoniğin her navigasyon davranışına etkisiz olduğunu kanıtlamaz; yalnızca
bu all-trajectories abortunun kaynağını açıklamadığını gösterir.

Önemli: kapalı `RangeSensorLayer` plugin yine de instantiate olup topic'e
subscribe ediyor; bu beklenebilir. `scripts/diagnose_costmap_layers.py` range
plugin'in kendi hücrelerinde footprint içinde 6, yakın çevrede 29 nonzero
hücre (max=127) gösterdi. Bu servis plugin'in iç haritasını verir; tek başına
kapalı layer'ın master costmap'e birleştirildiğini kanıtlamaz. Obstacle layer
bu sırada sıfırdı. Parametre `false` olduğundan Nav2'nin aktif kompozisyonuna
katılmaması beklenir; bunu kesinleştirmek için bag içindeki master costmap ve
evaluation beraber izlenecek.

Sonraki adım hareketi tekrar gözlemekle yetinmemek; aynı kısa koşuda
`/evaluation`, `/cmd_vel_nav`, `/cmd_vel_smoothed`, `/cmd_vel`, `/odom`,
`/plan`, `/received_global_plan`, `/transformed_global_plan`, `/scan` ve local
master costmap'i rosbag'e kaydetmek. DWB'nin 192 aday içinden hangi örneklerin
RotateToGoal veya Oscillation tarafından reddedildiğini, goal tolerance
durumunu ve ilk spin öncesi gerçek komutları zaman eşleştirerek incele.


### 2026-10-08 DWB critic bag (`logs/nav2-critic-20261008-205344`)

Kullanıcı Range layer kapalı A/B koşulunda kısa Explore çalışmasını kaydetti. Bag
19.05 s / 9.8 MiB; Explore sürüşü yaklaşık 8 s. `evaluation` ve komut/odometri
kayıtları aynı anda mevcut. Kullanıcının gözlemi: kısa ileri hareketler ve sağ-sol
düzeltmeleri, anlamlı keşif ilerlemesi yok.

- Bu capture'da Explore'un hedefi/planı sık sık değişmiyor: `/plan` bir kez
  yayımlandı; 67 `received_global_plan` güncellemesinde aynı uç hedef korunuyor
  (yaklaşık map (0.62, 1.30)). Dolayısıyla bu olayda küçük hareketlerin sebebi
  hızlı frontier hedefi churn'ü değil.
- Yerel DWB değerlendirmelerinde `BaseObstacle` bu adayları reddetmiyor; ham
  maliyeti örneklerde sıfır. `RotateToGoal` da bu bag'in çoğunda sıfır, çünkü
  robot henüz XY hedef penceresinde değil. `Oscillation` bazı adayları eliyor
  ama yasal adaylar kalıyor. Bu bag, önceki ayrı 10 s koşusundaki “0/192 legal”
  hatasını yeniden üretmiyor; iki durumu aynı olay gibi yorumlamamak gerekir.
- Seçilen `cmd_vel_nav` önce yaklaşık +0.144 m/s ve -0.19 rad/s sağ yaw komutu
  veriyor; açısal komut kısa sürede yaklaşık -0.45 rad/s'ye çıkar. Sonra
  translasyon sıfıra yakınken açısal komut pozitif tarafa geçiyor. Odometri ilk
  ~8 s içinde yaklaşık +0.22 m x, +0.51 m y ve -32° son yön değişimi gösteriyor;
  ara yaw sapması ~-50°'ye ulaşıp geri geliyor. Yani gözlenen sağ-sol hareket
  komut ve poz ölçümünde gerçek; yalnızca recovery davranışından ibaret değil.
  Açısal komut işaret değiştirdikten sonra fiziksel yaw'ın bir süre eski yönde
  sürmesi gecikme/atalet veya komut->motor dinamiği etkisine işaret eder, ancak
  tek bag nedenselliği ayırmaz.
- Kullanıcının canlı parametre sorgusu `PathAlign.scale=12.0`,
  `GoalAlign.scale=10.0`, `RotateToGoal.scale=3.0`, `xy_goal_tolerance=0.1` verdi.
  Bag'deki `CriticScore.scale` değerleri `PathAlign=0.30`, `GoalAlign=0.25`;
  bunlar parametrelerle uyumludur, çünkü PathAlign ve MapGrid tabanlı
  GoalAlign/PathDist/GoalDist critic'leri parametre scale'ını
  `costmap_resolution * 0.5` ile çarpar. 5 cm çözünürlükte çarpan 0.025'tir:
  12 -> 0.30, 10 -> 0.25, 1 -> 0.025. Önceki “parametre ve etkin scale
  uyuşmuyor” çıkarımı hatalıydı; burada parametre yükleme sorunu yok.
- `/plan` pose yaw'ları ara waypointlerde 0 iken, smoother sonrası
  `/received_global_plan` ara yaw'ları yol segmentinin yaklaşık 180° tersi
  yönünde. Bu orientation anomalisi ayrı araştırma konusu olabilir; DWB PathAlign
  ve GoalAlign ağırlıklarının ters olmasıyla aynı şey değildir ve tek başına
  ilk dönüşü açıklanmış sayılmaz. Final pose yaw hedefi ayrıca farklıdır.
- Önceki ayrı koşudaki `0/192` logunda Oscillation ve
  `RotateToGoal/Nonrotation command near goal` retleri birlikte vardı. Bu
  mekanizma hedef XY penceresinde translasyonu yasaklarken salınım critic'inin
  kalan dönüş yönünü yasaklayıp tüm örnekleri bitirebilir. Ancak o log için
  eşzamanlı evaluation bag yok; neden olasılığı güçlü olsa da aynı anın pozuyla
  henüz doğrulanmış değil.

Range layer test boyunca false bırakıldı; bu bag'de DWB'nin kısa sağ-sol
hareketlerini ultrasonic kaynaklı obstacle reddi açıklamıyor. Sonraki kontrollü
kaydı manuel taşıma sonrası mevcut pozdan başlat; kayıtla beraber başlangıç ve
bitiş map pozu/scan/odometri not edilsin.


### Bag scale alanı hakkında düzeltme (2026-10-08)

`CriticScore.scale`, `critic->getScale()` değeridir ve DWB bunu raw score ile
çarpıp toplam skora ekler. Ancak MapGrid critic'lerinin `getScale()` override'ı
parametre değerini `costmap_resolution * 0.5` ile çarpar. 0.05 m çözünürlükte
`PathAlign 12 * 0.025 = 0.30`, `GoalAlign 10 * 0.025 = 0.25`,
`PathDist/GoalDist 1 * 0.025 = 0.025` olur. Dolayısıyla bag ile canlı parametre
dökümü arasında uyumsuzluk yoktur. Önceki “scale mismatch” teşhisi geri
alınmıştır. [Jazzy MapGrid getScale](https://api.nav2.org/nav2-jazzy/html/map__grid_8hpp_source.html),
[PathAlign scale davranışı](https://api.nav2.org/nav2-jazzy/html/path__align_8cpp_source.html).


### Sonraki test başlangıç durumu

2026-10-08 kullanıcı robotun önünü açmak için cihazı eliyle taşıdığını belirtti.
Nav2 status sorgusunda `nav2_status=running`, `explore_status=stopped`; bu
durum test öncesi başlangıç olarak not edildi. Taşıma öncesi global poz ile yeni
poz kıyaslanmayacak; yeni kısa bag'in ilk pose/scan değerleri kendi başlangıcı
olacak. Testi başlatmadan hemen önce `/lidar/readings`, `/ultrasonic/readings`,
`/map/health`, `/nav2/status` ve motor status kaydedilmeli.


### Taşıma sonrası yeniden kontrol (`logs/nav2-recheck-20261008-210409`)

Kullanıcı robotu elle taşıdı; bu yeni testin yeni başlangıç konumudur. Önceki
map pozuyla doğrudan kıyas yapılmamalı. Başlangıçta motor sıfır, LIDAR front
242.58 cm, ultrasonic 96.46 cm, mapping provider ready idi. Range layer A/B
testinde iki costmap plugin'i `enabled=false` kalmıştı.

Bag 23.999 s, 97 evaluation, 97 DWB command, 1 `/plan`, 99 received plan,
98 transformed plan ve 480 `/odom` örneği içeriyor. Explore logu 13 frontier
buluyor ve `boundary=1.10m, target=0.90m, standoff=0.20m, mode=forward`
hedefini gönderiyor. Global planın ucu sabit; DWB çalışırken frontier hedefine
tekrar tekrar yeni `/plan` gelmiyor. Hareketin sonu kullanıcı Explore'u
durdurduğunda `follow_path` iptal ediliyor; bag içinde hedefe başarıyla varma
veya controller abortu görünmüyor.

Önemli koordinat düzeltmesi: map çerçevesindeki global plan hedefi ile odom
çerçevesindeki robot pozu çıkarılarak önceki yanıtta söylenen 0.5 m sonuç
hatalıydı. `/transformed_global_plan` ve `/odom` aynı `odom` çerçevesinde
eşleştirilince başlangıçta hedef 0.90 m uzakta, hedef doğrultusu başlangıç yaw'ına
göre +54.9° solda. Robot başlangıçta odom (0.716,0.878), yaw 10.95°; bitişte
(1.115,1.491), yaw 79.66°: yer değiştirme 0.73 m, yaw +68.7°. Son örnekte
transformed hedef (1.133,1.831), mesafe 0.34 m, gövde-hedef bearing hatası
yaklaşık 7°. Böylece kaydedilmiş tek hedefe doğru ilerlemiş ve yönünü hedefe
yaklaştırmıştır; bu koşudaki büyük sola dönüş hedefe ilk yaklaşım geometrisine
uygun bir kavis, rastgele sağ-sol oscillation değildir. Bu 12 s'lik hareket
hedefe varmayı değerlendirecek kadar uzun sürmemiştir.

DWB bu bag'de tüm adayları engel veya yasal-trajectory gerekçesiyle reddetmiyor;
`BaseObstacle` raw score sıfır ve legal seçenekler kalıyor. Son bölümlerde
Oscillation bazı örnekleri eliyor, ancak legal seçenekler korunuyor. Önceki
0/192 abortuyla bu koşu aynı değil. Robot son bölümde yavaşlıyor: son
`evaluation` örneği `vx=0`, `wz=-0.021` seçiyor; hemen ardından kullanıcı
`explore/stop` ile action'ı iptal ediyor. Bunun 0.34 m kala neden yavaşladığı
ayrı incelenmeli; bu capture tamamlanmış navigasyon sonucunu kanıtlamıyor.

Bu bag'de 98 DWB evaluation mesajı ve her birinde 203 örnek aday var; scale
değerleri yukarıdaki costmap çözünürlüğü normalizasyonuyla canlı 12/10/3
parametreleriyle uyuşuyor. `/odom` 23 s bag içinde başlangıç (0,0,0°)'dan
(+0.224,+0.880 m, +88.0°)'ye geldi; bu bag başındaki odom yeniden başlangıcını
yansıtır, tek başına hareket doğruluğu ölçümü değildir. Explore 16 frontier
bulup 2.42 m sınır/2.22 m hedef uzaklıklı tek forward hedef seçti. DWB önce
yerinde dönüp sonra translasyona geçti; testin sonunda açısal komutlarda küçük
sağ-sol düzeltmeler yaptı. `/plan` kaydedilmedi, bu nedenle hedef yönü/plan
geometrisi bu bag'den çıkarılamaz. Explore 12 s sonra kullanıcı tarafından
durduruldu; goal cancellation normaldi ve hedefe varma/abort sonucu gözlenmedi.
Bu scale araştırması kapanmıştır; küçük sağ-sol hareketlerin kök nedenini
bulmuş sayılmıyoruz.

Sonraki ROS incelemesinde `/evaluation` publisher sayısı 1 ve tek publisher
`/controller_server` olarak doğrulandı; ikinci/eski controller olasılığı
elenmiş oldu. `ros2 param dump ... | grep 'PathAlign.scale'` boş çıktı; bu,
YAML çıktısının parametreleri iç içe anahtarlarla yazması nedeniyle filtre
eşleşmemesi olabilir ve tek başına parametrenin eksik olduğunu göstermez.

Scale kontrol bag'i `logs/nav2-scale-check-20261008-211514` yerel rosbag2_py ile
okundu: 98 evaluation; PathAlign 0.30 (bazı örneklerde 0'a düşmesi critic'in
hedefe yakın davranışıdır), GoalAlign 0.25, PathDist/GoalDist 0.025, RotateToGoal
3.0, BaseObstacle 0.1 ve Oscillation 1.0. Her değerlendirmede 203 örnek aday
vardı; scale'lar parametrelerle beklenen şekilde tutarlı. `/evaluation` veri
analizi önceki yanlış çıkarımı düzeltti.

### Statik sensör/costmap kaydı (`logs/sensor-frame-check-20261008-212257`)

3.57 s'lik hareketsiz bag 35 `/scan`, 35 `/ultrasonic_range`, 4 local master
costmap ve 18 footprint örneği içeriyor. LIDAR `laser` frame'inde; TF'de
`base_link -> laser` translation x=-0.085 m, yaw=0. Robot yönü
`odom -> base_link` yaw=1.683 rad (~96.4°). Ultrasonik frame `base_link`, FOV
24°; 35 örneğin tamamı 1.01923 m (kayıt boyunca sıfır değişim).

Robot koordinatına çevrilmiş LIDAR taramalarında doğrudan ön ±10° sektöründe
en yakın dönüş ~1.83-1.84 m, medyan ~3.0 m; ön ±30° en yakın ~1.76 m. Sağ
sektörde yaklaşık 0.56-0.57 m, sol sektörde yaklaşık 2.42 m. Böylece önceki
API özetindeki `front~176 cm`, `right~55 cm` değerleri bag ile tutarlı;
ultrasonik yaklaşık 1.02 m'de başka/alt seviyede bir yüzey görebilir veya
sensör okuması sabit/stale olabilir. Sadece bag bu iki ihtimali ayırmıyor.

Footprint ile aynı odom koordinatındaki master costmap'te yüksek maliyetli
hücreler sağ-ön yanda yoğunlaşıyor; merkez önü dar koridorunda ±0.25 m lateral
bantta lethal/inscribed hücre yok. Costmap yüksek maliyet bandı sağda yaklaşık
0.4-0.6 m'lik aralıkta başlıyor. `range_layer.enabled=false` olduğundan bu
ultrasonik Range mesajı DWB/costmap kararı için kullanılmıyor; bu koşudaki
sağ-ön engel LIDAR/costmap tarafından görülüyor. Tek başına bu statik kayıt
Nav2'nin dönüşünü veya önceki oscillation abortunu kanıtlamaz; sonraki Explore
bag'inde `/plan`, transformed plan, `/evaluation`, komut, scan, TF ve costmap
birlikte kaydedilerek seçilen yayın yönünün sağ-ön engelden kaçış olup olmadığı
kontrol edilmeli.

### Web haritası güncelliği ve görüntü (`2026-10-08`)

Web UI `/map/latest` ile SLAM `/map` OccupancyGrid'inden üretilen
`output/maps/live_map.pgm` dosyasını gösteriyor; overlay yalnızca map-frame
robot oku. `/scan` noktaları bu UI katmanına çizilmiyor. Arayüz harita/poz
dosyasını panel ilk açılırken veya Yenile'ye basıldığında yüklüyordu; panel
açık kaldığı sürece görüntü ve robot oku otomatik yenilenmiyordu. Bu, ekranda
eski engel/poz görünmesinin doğrulanmış bir UI sebebi. `static/js/app.js` şimdi
panel görünürken harita sağlığını, PGM'yi ve oku 2 saniyede bir beraber
yeniliyor; `templates/index.html` JS cache-buster sürümü artırıldı. Tarayıcıda
sayfayı yeniden yüklemek gerekir.

Canlı dosyalar kontrol edildiğinde meta/pose/scan yaşları 1 saniyeden azdı;
PGM 594x519, 2.5 cm/piksel, değer sayımları unknown=255753, free=49990,
occupied=2543. Mevcut `live_scan.json` ön sektöründeki birçok endpoint mevcut
PGM'deki occupied piksellere 1 piksel komşulukta denk geliyor. Bu, o anda SLAM
haritasının LIDAR taramasıyla tutarlı olduğunu gösterir; kullanıcının gördüğü
tekil izlerin fiziksel engel mi, geçmiş tarama/poz hizalama izi mi olduğunu
kanıtlamaz. UI otomatik güncellendikten sonra da sabit ortamda görünen ince
izler kalırsa SLAM pose/scan hizalamasını incelemek için aynı anda `/map`,
`/scan`, `/tf` bag'i gerekir. Bu incelemede fiziksel ortama yeni hareket
komutu verilmedi.

### Ultrasonik sensörün haritaya etkisi ve reset durumu

Ultrasonik `/ultrasonic_range` topic'i `ros2_cmdvel_bridge.py` tarafından
yayınlanmaya devam ediyor; ancak SLAM exporter sadece `/map` OccupancyGrid'ini
okuyor, `/scan` ise SLAM'in LIDAR girdisi. Ultrasonik Range doğrudan SLAM
haritasına yazılmıyor. Nav2 local ve global `range_layer.enabled` YAML'da
`false`; kullanıcı Nav2'yi yeniden başlatıp runtime parametrelerini `False`
olarak da doğrulamıştı. Python güvenlik yolu ultrasoniği çok yakın mesafe acil
durdurması için tutuyor; bu, haritaya hücre eklemiyor.

Son Oct 8 uygulama logu `logs/run-20261008-203130/app.log`; logda SLAM yaw'ı
yaklaşık 97.1° değişirken IMU gyro yaw değişimi yalnızca -0.03° ve gyro tepe
hızı 0.17°/s kaydedilmiş. Watchdog olayı yakalamış, fakat
`MAP_JUMP_AUTO_RECOVERY_ENABLED=False` nedeniyle reset/restart yapılmamış.
Bu, SLAM scan/pose hizasızlığının haritadaki ince çift/yanlış izler için
ultrasonikten çok daha güçlü, logla desteklenen bir şüphe olduğunu gösteriyor;
tek başına o izlerin kaynağını ispatlamaz.

Uygulama başlangıcındaki `CLEAN_OUTPUT_ON_START=False`, bu nedenle app restart
eski `live_map.pgm` dosyasını başlangıçta silmiyor. App başlatılırken
`Ros2SlamService` SLAM/LIDAR/exporter süreçlerini başlatıyor; sonraki `/map`
mesajı PGM'yi güncelliyor. `nav2/stop` ve `nav2/start` tek başına SLAM haritasını
temizlemiyor. `map_reset.json` son açık reseti 2026-09-20 gösteriyor; Oct 8
logunda jump sonrası otomatik reset olmadığı açık. Dolayısıyla Oct 8'de
`/map/reset` çağrısına dair kanıt yok ve yeni Nav2 testleri eski/current SLAM
oturumu içindeki haritayı kullanmış olabilir.

Harita reseti (`2026-10-08 21:36`) ilk denemede, Nav2/EKF kapalı olduğu için
`/set_pose` 5 s timeout ile başarısız oldu; endpoint canlı harita dosyalarını
sildiği için `map_reset.json` `pending` kaldı. Nav2 Explore kapalıyken yeniden
başlatılıp EKF servisi açıldıktan sonra reset başarıyla tamamlandı:
`mode=slam_toolbox_clear_changes_and_stop`, `odom_reset=true`,
`outputs_ready=true`. Yeni `/map/pose` (0,0,0°), PGM/meta ve LIDAR scan hazır;
iki aktif costmap'te `range_layer.enabled=False`. Reset sonrası ilk PGM 421x283,
unknown=118357, free=744, occupied=42 hücre; robot hareket etmeden taze map
neredeyse boş ve yalnızca başlangıç scan izlerini içeriyor.

Reset sonrası ciddi ayrı ultrasonik hata ölçüldü: API `distance_cm=-2659.58`,
ROS `/ultrasonic_range` ise `range=-26.4808 m` yayınladı (geçerli min 0.02 m,
max 4.2 m). Aynı `DistanceService.read_centimeters()` ham gpiozero değerini
filtresiz kabul ediyor; 7 negatif örnek kümelenip `stable=true` olabiliyor.
Range layer kapalı olduğundan bu haritaya yazmıyor; fakat köprü invalid Range
mesajı yayımlıyor ve motor güvenlik yolu `<=12 cm` gördüğü için bir sonraki
ileri Nav2 komutunu engelleyebilir. Bu doğrulanmış ölçümle Explore başlatılmamalı;
önce sensör/kablo/echo ve yazılım geçerleme politikası düzeltilip doğrulanmalı.
