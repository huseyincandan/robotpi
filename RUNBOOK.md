# Çalıştırma ve log düzeni

Geliştirme/test ve GPIO26 üretim başlatması aynı launcher'ı kullanır. Uygulama
ve ROS düğümlerini ayrı terminallerden elle başlatmayın.

## Müzik oynatıcısını yeniden başlatma sonrası devralma

mpv, `/tmp/hamsibot-mpv.sock` JSON IPC soketiyle yönetilir. Uygulama yeniden
başlarken açık oynatıcıya tekrar bağlanır; radyo uygulama kapanınca çalmaya
devam edebilir. İstasyon listesi, sıra ve ses seviyesi atomik olarak
`output/music/state.json` dosyasına yazılır. Dosya yoksa veya bozuksa açık
oynatıcıdan mevcut yayın ve ses seviyesi okunur. Başka süreçlerin yanlışlıkla
durdurulmaması için sahiplik, mpv komut satırı ve süreç başlangıç kimliği
kontrol edilir.

Eski, yalnız stdin ile yönetilen sürümden kalmış tek bir mpv varsa, uygulamanın
mpv log dosyasına yazdığı doğrulanır ve aynı yayın/ses seviyesiyle IPC kullanan
oynatıcıya bir kez taşınır; kısa bir ses kesintisi olabilir. Eski bellekte
kalmış istasyon listesinin tamamı kurtarılamaz; yeni başlatılan listeler
bundan sonra durum dosyasında korunur.

Müzik sırasında uyandırma dinlemesi açıktır. Test ayarında normal/müzikli
eşik 0,25 ve gerekli art arda algılama sayısı 1'dir; radyo devralınınca daha
katı bir eşiğe geçilmez. `WAKE LEVEL` her 5 saniyede tepe puanı ve etkin eşiği
yazar. `LOG_SCORE_INTERVAL_SECONDS=0` bu tanılama çıktısını kapatır.
Uyandırma algılanınca müzik duraklatılır ve normalde olduğu gibi sesli
"Efendim Hüseyin?" yanıtı verilir. Müzikli komut kaydının üst sınırı da
10 saniyedir; sessizlikte erken bitiş uygulanır.

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

## Yerel sohbet, niyet ve web planı: Qwen3-0.6B

Konuşma metni, seçilen niyet, verilen yanıt ve aşama süreleri her oturumun
`logs/run-*/app.log` dosyasında yazılır; son 10 oturum korunur. Genel bilgi
soruları sohbet olarak yanıtlanır. Müzik türlerini listeleme niyeti için
müzik/radyo bağlamı gerekir. "İnternetten araştır" gibi konu belirtmeyen
devam istekleri son kullanıcı konusuna bağlanır; konu yoksa açıklama istenir.
Arama sonuçlarına temel konu uygunluğu filtresi uygulanır; filtre güvenilirlik
doğrulaması değildir, açıkça alakasız sonuçların yanıta taşınmasını engeller.
Bing RSS sonuçları hatalı veya boşsa Brave Search HTML sonuçları denenir;
yanıta verilen arama bağlamında gerçek sağlayıcının adı korunur. Her iki
kaynak da konuya uygun sonuç vermezse asistan bunu açıkça söyler.
`SPEECH:` satırları yerel komut yanıtları dahil gerçekten seslendirmeye
gönderilen metni de kaydeder. Kayıt `no_speech` ile bittiyse arka planın
sesli örnek oranı oturumu açık tutmaz; iki boş turdan sonra uyandırma
dinleyicisine dönülür.

2026-10-16 denemesinde Qwen3-0.6B Q8, niyet ve web planı örneklerini
çözebildi; genel Türkçe sohbette temel bilgi ve aritmetik hataları sürdü.
Bu nedenle etkin `LLM.PROVIDER` tekrar `openai` yapıldı. Yerel model ve
bağlantı kodu yeniden denemek için saklanır. Sonuçlar
`logs/qwen-llm-benchmark.json` ve `logs/qwen-llm-chat-benchmark.json` içindedir.

`LLM.PROVIDER="qwen"` sohbeti, niyet sınıflandırmasını, web arama planını ve
arama sonuçlarının yanıtlanmasını aynı yerel Qwen3-0.6B servisine yönlendirir.
STT ayrı Qwen3-ASR 0.6B, seslendirme Piper olarak kalır. Hava durumu ve web
arama verileri hâlâ internetten alınır; bu servisler OpenAI gerektirmez.

Kurulum:

```bash
.venv/bin/python scripts/setup_local_llm.py
ROBOTPI_DISABLE_MOTORS=1 .venv/bin/python scripts/run_app.py --launch-mode manual
```

Kurulum, llama.cpp `b11669` resmî ARM64 paketini SHA256 ile doğrulayıp
`tools/llama-runtime` altına kurar ve resmî `Qwen/Qwen3-0.6B-GGUF` Q8_0 ağırlığını indirir. Uygulama
başlarken yalnız `127.0.0.1:8081` adresinde llama-server açılır; kapanırken
kendi başlattığı sunucuyu kapatır. Model bellekte kalır. Düşünme kapalıdır,
bağlam 4096, yanıt sınırı 128 token, işlemci iş parçacığı sayısı 3'tür.
Sunucu günlüğü `logs/qwen-llm-server.log` dosyasındadır. `TIMING: llm`
satırları her çağrının modelini ve süresini gösterir. JSON işlevleri şema ile
kısıtlanır; tanınmayan niyetler komut olarak çalıştırılmaz.

OpenAI'ya dönüş: `config.py` içinde yalnız `LLM.PROVIDER="openai"` yapıp
uygulamayı yeniden başlatın. `ASSISTANT.MODEL`, `INTENT.MODEL` ve
`WEB.PLAN_MODEL` eski OpenAI modellerini dönüş için saklar; Qwen seçiliyken
etkin model `LLM.MODEL` değeridir. Otomatik buluta geçiş yapılmaz.
Normal sesli sohbet için `STT.ECHO_TEST_MODE=False` kullanılır.

## Yerel STT testi: Qwen3-ASR 0.6B

STT varsayılanı `Qwen/Qwen3-ASR-0.6B`; Türkçe zorlanır. Resmî ağırlıklar
`models/qwen3-asr-0.6b` altında tutulur. CPU çıkarımı, MIT lisanslı
[`antirez/qwen-asr`](https://github.com/antirez/qwen-asr) C motorunun
`924694251d9e0f18e5d86bbd06aa3ab5f870002d` sürümüyle yapılır.
Model süreç içinde bir kez yüklenir; her kayıt için yeniden yüklenmez.

Debian ARM64 Pi üzerinde kurulum/yeniden derleme:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/setup_qwen_asr.py
ROBOTPI_DISABLE_MOTORS=1 .venv/bin/python scripts/run_app.py --launch-mode manual
```

Kurulum GCC, git, apt-get ve dpkg-deb gerektirir. OpenBLAS paketleri yalnız
`tools/qwen-runtime` altına açılır; sistem paketleri değiştirilmez.
`STT.CPU_THREADS=3` kullanılır. `STT.ECHO_TEST_MODE=True` iken Hey Jarvis ve
kayıt bipinden sonra çözülen metin Piper ile aynen okunur; intent/LLM veya
hareket komutu çalıştırılmaz. Her denemeden sonra yeniden Hey Jarvis beklenir.
Normal konuşmaya dönmek için `ECHO_TEST_MODE=False` yapıp yeniden başlatın.

Kayıt sabit süre beklemez: ReSpeaker'ın işlenmiş kanalında konuşma sonrasında
1,2 saniye sessizlikte biter (`END_SILENCE_SECONDS`). Konuşma başlamazsa
4 saniye sonra kapanır; normal kayıt üst sınırı 10 saniyedir. Müzik komutunun
özel süre sınırı korunur. RMS başlangıç/devam eşikleri 450/250'dir; başlangıç
için en az 0,12 saniye etkin ses gerekir. `STOP_ON_SILENCE=False` eski sabit
süreli kayda döner. Son kırpma eşiği 250 RMS, kenar payı 0,35 saniyedir.
`STT RECORD END` satırı bitiş nedenini ve ses süresini yazar.

## Pi kamera web yayını

WebRTC yayını CSI kamerayı Picamera2/libcamera üzerinden açar; USB webcam
için kullanılan doğrudan OpenCV/V4L2 yakalaması artık kullanılmaz.
Raspberry Pi OS paketleri `python3-picamera2` ve `python3-libcamera` gereklidir
(bu Pi'de kurulu). Yerel libcamera bağları nedeniyle bunları pip ile kurmayın.
Kamera açılırken `/usr/lib/python3/dist-packages` uygulamanın Python arama
yolunun sonuna eklenir; sanal ortam paketleri önceliğini korur. Sanal ortam
Python'ı sistem Python'ıyla aynı sürümde olmalıdır.

`config.py` içindeki `CAMERA` ayarları 320×240 / 15 FPS yakalamayı korur.
Kamera montajı düzeltildiği için `ROTATION_CCW_DEGREES: 0` kullanılır.
Tarayıcıya kırpılmadan 320×240 görüntü gönderilir; CSS ile ayrıca döndürme
yapılmaz. Montaj değişirse bu ayar 0, 90, 180 veya 270 olabilir.

Yalnız kamera kontrolünde motor sürücüsünü açmadan başlatmak için:

```bash
ROBOTPI_DISABLE_MOTORS=1 .venv/bin/python scripts/run_app.py --launch-mode manual
```

Kamera ilk web bağlantısında açılır, bağlantı kesilince veya uygulama
kapanınca serbest bırakılır. Kareler olay döngüsünü bloke etmeden okunur;
WebRTC zaman damgaları sensör zamanından hesaplanır.

## 2026-10-15 yakın ultrasonik engel ve kurtarma

Ultrasonik ölçümler yalnızca `ULTRASONIC.MAPPING_MAX_DISTANCE_CM = 20`
aralığında, kararlı ve güveni en az 0,7 ise `/ultrasonic_range` üzerinden
Nav2'nin yerel/global costmap'lerine gönderilir. 20 cm üstündeki ölçümler
ne engel eklemek ne de engel silmek için kullanılır. Bu, SLAM'in kalıcı
LIDAR haritasını değil navigasyonun engel katmanlarını günceller.

Mesafe artık sensör yüzeyinden ölçülen gerçek mesafedir; gövde ofseti
mesafeye eklenmez. `base_link → ultrasonic_link` statik TF'si sensörü arka
aksın 0,27 m önüne taşır. Böylece sonar konisinin başlangıcı da doğru yerde
olur. İki costmap'te `clear_on_max_reading: false` kullanılır; güven
sınırındaki 20 cm'lik gerçek engel, boş alan bildirimi olarak yorumlanmaz.
12 cm ileri durdurma ve arka LIDAR kontrolleri korunur.

Davranış ağacının standart `WouldAPlannerRecoveryHelp` filtresi
`ComputePathToPose.START_OCCUPIED = 205` hatasında kurtarmaya izin vermiyordu:
robot aynı yerde kalırken yeni frontier hedefleri de reddediliyordu.
Bu hata artık bir kez çarpışma denetimli BackUp, gerekirse Spin denemesine
izin verir. Gerçek engeli silme, çarpışma denetimini kapatma veya sınırsız
geri çekilme yapılmaz.

Gözetimli denemede yakın ön sonar engeli yalnızca ileri hareketi durdurur;
geri çekilme/dönüş sırf ön sonar yakın diye kesilmez. Her yöndeki 18 cm
LIDAR alt sınırı, pil ve sensör arıza denetimleri yürürlüktedir.

Canlı doğrulama:

- Yaklaşık 8,7 cm sonar engeli iki costmap'te de maliyet 254 olarak görüldü.
- Aynı konumdan Nav2 BackUp ile 12 cm geri çekilme başarılı oldu.
- 205 hatası ardından otomatik BackUp çalıştı; 18 cm kurtarma tamamlandı.
- `logs/nav2-supervised-20261015-203602` kaydında yaklaşık 3,94 m odometri
  yolu ve bir başarılı navigasyon hedefi var. Sonraki engelli hedefte
  kurtarma/reseçim görüldü; deneme 30,63 cm ön LIDAR ölçümünde gözetimli
  32 cm ileri sınırıyla durdu. Tüm ortamda hatasız gezinme kanıtı değildir.

ROS tanı ve kayıt komutlarında aynı underlay/workspace'i yükleyip
`export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` kullanın; uygulamanın ROS
süreçleri de bu middleware ile çalışır.

## Sürekli gezinme oturumu

`/explore/start` ve `/wander/start` gezinme isteğini açar. Bir hedefin
başarısız olması, yakın engel, geçici kara liste veya frontier kalmaması
bu isteği kapatmaz. Nav2 mevcut çarpışma denetimli kurtarmalarını dener;
aktif hedef yokken uygulamanın takip döngüsü keşfi yeniden değerlendirir:

- Kapanmış keşif süreci 10 saniyelik beklemeden sonra yeniden başlatılır.
- Hedef bulamayan/bekleyen keşif 30 saniyeden sonra yeniden başlatılır;
  böylece geçici frontier kara listesi de yenilenir.
- Aktif navigasyon hedefi takip döngüsü tarafından kesilmez.
- Uygun güvenli hedef yoksa motorlar bekleyebilir; bu, oturumun kapandığı
  anlamına gelmez. Sırf hareket sürsün diye engel silinmez veya rastgele
  motor komutu verilmez. Keşif bitince bilinen alanda devriye yapılmaz.

`/nav2/status` içinde `explore_running` ve `exploration_intent` oturum
isteğini; `explore_active` aktif hedefi; `explore_process_running` gerçek
keşif sürecini gösterir. `waiting_for_frontiers` durumunda web arayüzündeki
düğme hâlâ “Durdur” olarak kalır. Bu, eski `explore_running = aktif hedef`
anlamından kasıtlı değişikliktir.

`/explore/stop`, `/wander/stop` veya `/nav2/stop` isteği kapatır. Durdurma,
devam eden başlatma/yeniden denemeyi nesil sayacıyla geçersiz kılar; geç
tamamlanan bir işlem gezinmeyi yeniden açamaz. Uygulama kapanışında da
takip döngüsü iptal edilir. Kritik pil, sensör arızası ve harita bozulması
nedeniyle mevcut güvenlik duruşları korunur; bunların ardından operatör
onayı olmadan oturum yeniden açılmaz.

`scripts/run_supervised_explore.py` ayrı bir **süreli test aracıdır**:
32 cm ön sınırı, 18 cm genel sınır veya süre sonu nedeniyle navigasyonu
bilerek kapatır. Sürekli kullanım başlatmak için bu aracı kullanmayın.
Uygulamanın web düğmelerini veya yukarıdaki HTTP uçlarını kullanın.

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

### Konuşmacı tanıma

`SPEAKER_ID` yerel CAMPPlus (sherpa-onnx, CPU, tek iş parçacığı) kullanır.
Uyandırmadan önceki son 2,5 saniye yalnızca RAM'de tutulur. Uyandırma tahmini
komut kaydıyla doğrulanır; çelişkili veya belirsiz sonuçlarda isim kullanılmaz.
Komut tek başına daha yüksek eşikle eşleşebilir. Tanıma STT ile paraleldir;
LLM yanıtı sonucu beklemez. Doğrulanan kimlik oturum bitince temizlenir.
Ses kimliği yetkilendirme amacıyla kullanılmaz. Eşikler Türkçe gerçek kayıtlarla
henüz kalibre edilmedi; model VoxCeleb İngilizce verisiyle eğitilmiştir.

Profil yokken çıkarım/model yükleme yapılmaz. Şu an kimse kaydedilmedi.
Kurulum: `.venv/bin/python scripts/setup_speaker_id.py` (bağımlılık requirements.txt).
Daha sonra açıkça profil eklemek için, her grupta en az üç farklı mono PCM16
16 kHz WAV kaydıyla:

```
.venv/bin/python scripts/speaker_profiles.py enroll --name Ada --wake wake1.wav wake2.wav wake3.wav --command command1.wav command2.wav command3.wav
.venv/bin/python scripts/speaker_profiles.py list
.venv/bin/python scripts/speaker_profiles.py delete PROFIL_ID
curl -X POST http://127.0.0.1:5000/speakers/reload
```

`GET /speakers/status` profil adlarını ve geçerli oturum durumunu gösterir.
Şablonlar git dışında `data/speakers/profiles.json` içinde 0600 izniyle tutulur;
özellik ham sesi arşivlemez. CLI değişikliklerinden sonra reload çağrılmalıdır.

Sesli profil kaydı da desteklenir: uyandırmada eşleşme yoksa robot adını sorar,
duyduğu adı doğrulatır. Kayıtlı isim için uzun bir cümleyle tekrar karşılaştırır.
Eşleşmezse ilk kayıt olup olmadığını sorar; aynı isimdeki mevcut profili
üzerine yazmaz, ayrı bir ad/soyad ister. Yeni kişi kayıt sorusuna evet derse
üç uyandırma ve üç komut cümlesi toplar. Sessizlik/iptal/eksik veya tutarsız
örneklerde profil kaydedilmez; her örnek en fazla iki kez denenir. Başarılı
kayıt hemen ve sonraki uygulama başlangıçlarında kullanılabilir. Bilinen
uyandırma sesi sonraki komutla doğrulanamazsa aynı konuşmalı akışa geçer.
Bu diyalog LLM'ye veya hareket/araç komutlarına yönlendirilmez.

Sohbet sırasında `Ses profilimi oluştur` veya `Ses profilimi güncelle`
denebilir. Bu talepler LLM/araç sınıflandırmasından önce yerel diyaloga gider.
Güncelleme adın doğrulanmasını, mevcut sesle yeniden eşleşmeyi ve sesli onayı
ister. Altı yeni örnek tamamlanınca aynı profil kimliğiyle atomik olarak
kaydedilir. İptal, tutarsız örnekler veya yazma hatasında eski kayıt korunur.
Kayıtlı profil bulunamazsa yeni kayıt için onay istenir.

İsim onayında `hayır` demek kayıt akışını iptal etmez; ad yeniden sorulur.
Uyandırma eşleşmesi varsa selamlama `Efendim, [isim]?` olur. Selamlama eşleşme
sonucunu en fazla 250 ms bekler; sonuç belirsizse genel selamlama kullanılır.
Profil varsa model uygulama açılışında ısıtılır. Bu selamlama tahmini kimliği
kullanır; sohbet kimliği yine sonraki komutla doğrulanır.

Komut dinlemesinde tek boş tur yeterlidir (`EMPTY_TURNS_TO_SLEEP=1`).
Konuşma başlangıcı 4 saniye beklenir; ortam sesinin yüksekliği tek başına
beklemeyi uzatmaz. openWakeWord paketindeki Silero VAD tek CPU iş parçacığıyla
30 ms karelerde çalışır (eşik 0.5). Konuşma yoksa STT çağrılmadan Hey Jarvis
bekleme moduna dönülür. 4 saniye kayıt süresidir; bip/kayıt hazırlığı ve kapanış
sinyali buna küçük bir ek süre getirir. Başlamış cümledeki 1.2 saniye duraklama
sınırı korunur. VAD, uzaktaki başka insan konuşmasını da konuşma sayabilir.

Güncel haber araması genel web aramasından ayrıdır (`services/news.py`). TRT
manşet RSS ve NTV Atom akışları paralel alınır; konu sorgusunda Google News
RSS de denenir. Başlık/özet/kaynak/yayın tarihi birlikte bağlama konur. Bugün
isteğinde İstanbul takvim gününden eski; diğer güncel haber isteklerinde 24
saatten eski, tarihsiz veya gelecekte görünen içerik elenir. Kaynaklar
sırayla harmanlanır; genel haber anasayfaları arama özeti olarak sunulmaz.
Hiç uygun haber yoksa bunu açıkça söyler. LLM 3–5 kısa başlık okuyacak şekilde
yönlendirilir. Haber içeriği RSS/Atom özetidir, makale tam metni değildir.

TV/ortam sesi kaynaklı yanlış uyanmaları azaltmak için wake eşiği normalde 0.35, müzik çalarken 0.30 ve
ardışık algılama sayısı her iki durumda 2'dir. İzole tek skor sıçraması
yeterli değildir. Kayıt hatası/robot konuşması sırasında ardışık sayaç temizlenir.
Bu ayarlar odada gerçek ses/TV karşılaştırmasıyla yeniden değerlendirilebilir.

Kısa uyandırma telaffuzlarını kaçırmamak için iki komşu karede ana eşik
şartı yerine biri ana eşiği (normal 0.35, müzik 0.30), ikisi de doğrulama
eşiğini (normal 0.20, müzik 0.18) geçmelidir. Tek izole sıçrama hâlâ yetmez.

Güçlü tek kare de uyanmaya yeter: normalde 0.60, müzikte 0.50. Daha düşük
skorlarda komşu kare doğrulaması geçerlidir. Uyandırma kaydına robot
konuşmadan önce 240 ms kuyruk eklenir; konuşmacı için son 1.6 saniye kullanılır.
Kayıtlı profiller varken wake eşleşmezse hemen ad sorulmaz: önce komut sesiyle
tekrar denenir. Komut da doğrulanamazsa isim/profil diyaloguna geçilir.
SPEAKER SCORE satırları eşleşmenin neden reddedildiğini takip etmek içindir.

Profil diyalogundaki iptal kontrolü Türkçe büyük İ harfini de normalize eder.
`İptal`, `iptal et`, `vazgeçtim` kayıt işlemini sonlandırır. Logda görülen
`İpter` STT yanlışı da iptal sayılır. Açık `sohbeti bitir`/`görüşürüz` gibi
komutlar, konuşmacı doğrulama ve profil sorusundan önce Hey Jarvis moduna döner.

Konuşma kimliği (`session_name`) selamlamada kullanılan wake eşleşmesini
korur. Kısa/gürültülü/eşleşmeyen komut tek başına bu kimliği silmez. Başka bir
kayıtlı kişiyle açık eşleşme çelişki sayılır ve isim kullanımı durur; otomatik
kayıt diyalogu açılmaz. `confirmed_name` iki aşamalı/uzun komut doğrulamasını
ayrı tutar; profil güncelleme için yeniden doğrulama hâlâ gerekir.
Otomatik isim sorusu ancak wake eşleşmesi yoksa ve yeterli komut örneğinin
çıkarımı tamamlanıp kimlik belirlenememişse açılır; kısa ses, bekleyen iş veya
model hatası yeni kişi sayılmaz. Açık profil oluştur/güncelle talepleri sürer.
