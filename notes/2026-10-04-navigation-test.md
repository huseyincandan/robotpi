# Navigasyon testi — 2026-10-04

Uygulama `.venv/bin/python scripts/run_app.py --launch-mode manual` ile
çalışıyordu. İlk denemelerde test sırasını ve izleme betiğini yanlış kurdum:

- Nav2 kapalıyken `/map/pose` bayat olabiliyor; doğru sıra Nav2'yi açmak,
  poz/IMU/LIDAR verisinin tazeliğini doğrulamak, sonra Explore'u başlatmak.
- ROS CLI teşhisinde ilk olarak uygulamanın kullandığı ROS ortamı yerine
  farklı workspace'i kaynak gösterdim. Doğru ortamda Python 3.12 ve ROS mesaj
  tipleri sorunsuz yüklendi; önceki Python 3.12/3.13 uyuşmazlığı iddiam
  geçersizdi.
- IMU `time` ve `telemetry_received_at` değerleri monotonic saatte saniyedir;
  bunları Unix wall-clock ile kıyaslayan preflight geçemez. Gyro zaten derece/s
  verdiği için entegre derece sonucuna ayrıca `degrees()` uygulamak da yanlıştı.
- LIDAR sektör değeri `null` gelebilir; izleyici bunu sayıya çevirmeden
  karşılaştırmıştı. Eksik sektör artık test hatası olarak ele alındı.

Bu hatalardan ayrı gerçek bir başlatma pürüzü de bulundu. `start_nav2()` önce
TF hazır olmasını bekliyor; eski kontrol iki saniyelik yeni bir ROS CLI süreci
başlatıp `/tf` içindeki tek `TFMessage`'ı arıyordu. `map→odom` dönüşümü canlı
TF ağacında bulunmasına rağmen soğuk DDS keşfinde bu kontrol bir kez başarısız
oldu ve Nav2'yi başlatmadı. `_wait_for_tf_pair()` artık TF mesajı metnini
aramak yerine `tf2_ros tf2_echo` ile gerçek frame çiftini çözüyor; değişiklik
başlatma güvenlik kontrolünü koruyup bu zamanlama yarışını azaltıyor.

Son kontrollü denemede Nav2 ve Explore başarıyla başladı. Explore haritadaki
tek güvenli frontier için yaklaşık 0.59 m hedef (0.79 m sınırdan 0.20 m
standoff) seçti ve hedef kabul edildi. Yaklaşık 2 saniyelik hareket örneklerinde
motor komutları görüldü; IMU yaw değişimi ve harita pozu yaklaşık 23° dönüşte
birbirini doğruladı. Harita pozu en son x=0.026 m, y=0.006 m gösterdi. LIDAR
sağ sektör yaklaşık 44 cm'den 39 cm'ye, ultrasonik engel ölçümü yaklaşık
28.6 cm'ye indi.

İzleyici, test için belirlenen 1800 enkoder-tik sınırını aşınca Explore'u
durdurdu; bu bir Nav2/robot arızası değil, kısa hareket için koyduğum test
sınırıydı. Explore durdurulunca Nav2 eylemi iptal oldu; ardından Nav2 de
durduruldu. Son durum: iki motor komutu 0, Nav2/Explore durmuş, blokaj, güç
ve sensör hatası yok. Bu kısa koşu Nav2'nin frontier seçip hareket komutu
iletebildiğini ve dönüşte IMU/SLAM yön değişiminin uyumlu olduğunu gösteriyor.
Tam navigasyon başarısı veya uzun mesafeli engelden kaçınma performansı için
yeterli bir koşu değil.

Ana test kaydı: `logs/navigation-tests-2026-10-04/005430.json`.

## Açık alandaki takip testi — 10:22 (Europe/Istanbul)

Uygulama kapalı olduğundan `scripts/run_app.py --launch-mode manual` ile
başlatıldı. Nav2 açıldıktan sonra poz, IMU ve LIDAR tazeliği doğrulandı;
ultrasonik ölçüm kararlıydı. Başlangıçta LIDAR sektörleri F/L/B/R yaklaşık
246/299/213/55 cm, ultrasonik mesafe yaklaşık 90 cm idi.

Explore tek bir güvenli frontier seçti: sınır 0.67 m, hedef 0.47 m ve 0.20 m
standoff. Hedef kabul edildi. Robot ağırlıklı olarak sola döndü; IMU dönüşü
yaklaşık -65°, son SLAM pozu -66.4° oldu. Enkoder değişimleri RL +2166,
RR -364 tik verdi. Mevcut 13816 tik/m ve 0.142 m iz genişliğiyle enkoder
odometrisi yaklaşık 6.5 cm ilerleme ve -73.9° dönüş hesaplıyor; SLAM'ın
başlangıca göre 6.6 cm konum değişimiyle ilerleme uyuşuyor, dönüş farkı
yaklaşık 8°.

İzleme, 65° IMU dönüş sınırında keşfi durdurdu. Durma anındaki ön LIDAR
yaklaşık 50 cm, ultrasonik ölçüm 39 cm idi; son okumada yaklaşık 46 cm ve
34 cm oldu. Bu nedenle hedefe varılmadı ve uzun süreli engel aşma sınanmadı.
Son durumda motor komutları sıfır, Nav2/Explore durmuş, blokaj ve güç/sensör
hatası yok. Bu koşu önceki kısa denemeden daha iyi bir doğrulama: hedef seçimi,
gerçek hareket, enkoderle konum ilerlemesi ve IMU-SLAM dönüş uyumu görüldü.
Yine de tek frontier'a ulaşma/keşfi tamamlama gözlenmedi; sonraki testte açık
güvenli alanı koruyup hedefi tamamlayacak kadar ilerlemeyi izlemek gerekir.

Kayıt: `logs/navigation-tests-2026-10-04/102243.json`.

## Harita büyüme denemesi — 10:33 (Europe/Istanbul)

`live_map.pgm` görüntüsünde alanın çoğu bilinmiyordu (395×388 hücre, %0.678
bilinen). Meta/scan dışa aktarıcıları ve `/map` publisher çalışıyordu. Explore
bir hedef kabul etti fakat kısa koşu boyunca robot ağırlıklı döndü; bilinen
hücre oranı %0.678'de kaldı ve hedef tamamlanmadı. Öne hareket esnasında
kararlı ultrasonik ölçüm 30 cm altına indiği için izleyici Explore ve Nav2'yi
durdurdu. Son LIDAR ön mesafesi yaklaşık 38 cm, ultrasonik 27.9 cm idi. Son
motor komutları sıfır; blokaj/güç/sensör hatası yok.

Bu, arayüz zoom sorunundan çok gerçek SLAM occupancy haritasının seyrek
olduğunu gösteriyor. Yalnızca test süresinin kısa olduğunu söylemek yeterli
değil: robot hedefe ilerlemedi ve sensör önünde yakın engel buldu. Güvenli,
daha geniş boşlukta hedef ilerlemesini ve SLAM harita hücrelerinin değişimini
yeniden sınamak gerekiyor. Kayıt:
`logs/navigation-tests-2026-10-04/103354.json`.


## Daha açık konumda daha uzun Explore denemesi (11:15)

Kullanıcı robotu ön tarafı açık olacak şekilde yeniden konumlandırdı ve daha büyük teste izin verdi. Başlangıçta ultrasonik 87.5 cm (stabil), LIDAR ön 243 cm, sağ 49 cm idi. Nav2/SLAM başlatıldı; poz 0,0 noktasında yenilendi. Explore tek frontier buldu: sınır 0.67 m, hedef 0.47 m ve Nav2 hedefi (0.44,-0.17). İlk saniyede poz yaklaşık 9.5° döndü; enkoder farkı RL +1373, RR -7, gyro Z -29.4°/s oldu. LIDAR ön 76 cm okudu. Testi izleyen Python kodunda eksik `math` importu nedeniyle hata çıktı; `finally` bloğu Explore, motor ve Nav2 durdurmayı başardı. Durdurma sonrası ultrasonik 39.85 cm, LIDAR sektörleri ön/sol/arka/sağ 47/69.5/88.6/48.3 cm gösterdi. Harita bilinen hücre oranı 0.678% olarak kaldı. Yakın engel durumunda devam edilmedi. Sonuç: bu deneme harita büyütmedi; hedefe doğru dönme, açılan ön koridoru net biçimde izleyemedi ve teker hareketi ağırlıkla dönüş gösterdi. Ayrıntı: `logs/navigation-tests-2026-10-04/111500.json`.


## Kullanıcı açıklamasından sonra devam edilen test (10:45)

Kullanıcı, robotun biraz sağa dönmüş olduğunu ve önündeki duvara yeterli mesafe bulunduğunu belirtti; önceki erken durdurma kararımı düzelterek yeniden Nav2/Explore başlattım. Başlangıçta ön LIDAR 46.9 cm, ultrasonik 86.3 cm (stabil; hemen önce ultrasonikte 40-97 cm arası kararsız okumalar görülmüştü). Explore çalıştı. 4 saniyelik harekette IMU gyro Z kısa sürelerle -37.9, -23.8 ve +40.6°/s ölçtü; harita pozu en fazla yaklaşık 64° yön değişimi gösterdi. Enkoderler RL +2107, RR +160 tik kaydetti; motor komutları bazı örneklerde dönüş ağırlıklıydı. Ultrasonik mesafe 27.3, 25.1, 30.4 ve 22.2 cm olarak okundu; LIDAR ön 32.6-39.2 cm aralığına indi. Stabil ultrasonik 22.2 cm ölçümü 25 cm koruma eşiğini geçtiği için Explore, motorlar ve Nav2 durduruldu. Haritadaki bilinen hücre oranı %0.678'de kaldı, yeni hücre eklenmedi. Bu koşu açık başlangıca rağmen hedefe doğru işe yarar düz ilerleme/harita büyümesi sağlamadı; yaw/enkoder/gyro birlikte dönüşü doğruluyor. Robot şu an duruyor. Ayrıntılı örnekler: `logs/navigation-tests-2026-10-04/104506_continued.json`.


## Kullanıcı geri bildirimiyle düşük yakınlık kesmesiyle Explore testi (10:56)

Önceki 25 cm durdurma eşiğinin uygulamaya değil test izleyicime ait olduğu doğrulandı. Kullanıcı duvara yaklaşınca robotun engelden dönüp gezinmeyi sürdürmesini istedi. 25 cm eşiğini tekrar uygulamadım; güvenlik için yalnızca 15 cm koruma sınırı, sensör/IMU/poz kaybı ve Nav2 motor hatası takip edildi. 30 saniyelik Explore koşusu kendi süre sınırında sona erdi. Harita 395×388 hücre / %0.678 bilinen alan düzeyinden 475×463 hücre / %2.773 bilinen alana büyüdü (+5060 bilinen hücre). Enkoder farkı RL +6016, RR +1267; harita pozu yönü toplam yaklaşık 133.8° değişti. Bu kez robot engelden döndü ve harita topladı; 25 cm test kesmesi hareketi engellemedi.

Ancak Nav2 tek hedefte kaldı: (0.44,-0.17), hedef 0.47 m. `explore.log` hedef aktifken yeniden frontier seçimini ertelediğini yazdı. Yaklaşık 23. saniyede Nav2 `Failed to make progress` dedi ve `Running backup` ile kurtarma başlattı; testin sonunda Explore/Navigation kapatılınca kurtarma iptal oldu. Bazı örneklerde enkoder/poz birkaç saniye değişmedi. Yani bu koşu harita büyümesi sağladı ama hedef tamamlama veya kurtarmadan sonra başka yöne yeniden hedefleme doğrulanmadı. Kod tarafındaki esas gezinme iyileştirmesi, hedef ilerlemediğinde recovery tamamlanmadan sonsuza dek beklemek yerine mevcut hedefi bırakıp başka uygun frontier seçmeye dair olacak; 25 cm global kesme bu çözümün parçası değil. Bitişte motor komutları sıfır, Nav2/Explore durmuş, güç/sensör hatası yok. Kayıt: `logs/navigation-tests-2026-10-04/105601_avoidance.json`.


### Test süresiyle ilgili düzeltme

`105601_avoidance.json` ve `nav2.log` birlikte incelendi. Önceki “Explore kurtarma sonrasında yeni hedef seçmiyor” sonucu henüz doğrulanmış değil: bu koşunun izleyicisi 30 saniyede testi kendi sonlandırdı. Nav2 yaklaşık 22 saniyede `Failed to make progress` alıp `Running backup` recovery adımına girmişti; `explore_lite` aktif goal varken frontier yeniden seçimini ertelemesi beklenen davranış. Test bitişinde Nav2/Explore stop edilince backup iptal edildi ve logda `Failed to get result for backup in node halt!` yazdı. Bu yüzden kurtarma akışı tamamlanamadan test kesildi. Doğru sonraki teşhis, keyfî yakınlık kesmesi olmadan ve en az bir tam recovery döngüsünü tamamlayacak daha uzun (yaklaşık 90 sn) izlemeli koşudur. 25 cm kesme izleyicime aitti; son 30 sn koşusunun `duration_30s` ile bittiği test JSON'unda kayıtlıdır.


## Sınırlandırılmış Nav2 kurtarma denemesi (11:16)

Kullanıcı duvar önünde yeterli boşluk olduğunu belirtti; bu koşuda harici yakınlık
kesmesi kullanılmadı. Nav2 davranış ağacında bir tam kurtarma turuyla
sınırlandı; Spin mesafesi 1.57 rad'dan 0.60 rad'a indirildi (0.12 rad/s hız
sınırında 10 saniyelik Nav2 davranış süresine sığması için). 110 saniyelik
Explore koşusunda ilk hedefte iki geri gitme denemesi başarısız oldu. Nav2
hedefi bıraktı ve Explore yaklaşık 60. saniyede aynı frontier'ı kara listeye
alıp farklı bir hedef seçti. İkinci hedefte yine `Failed to make progress`
oluştu; bir kısa geri gitme başarılı oldu. Test sabit süresi dolunca sona
erdi ve Explore/Navigation güvenli biçimde kapatıldı. Harita bilinen alanı
%2.931'den %3.574'e büyüdü (+1934 hücre). LIDAR ön mesafesi koşu içinde
~26 cm'ye kadar düşüp sonra açıldı; bu yüzden robotun engelden dönüp veri
topladığı görüldü. Ultrasonik sensör aynı 22.807 cm değerinde takılı kaldı;
bu koşuda güvenilir değişken ölçüm gibi kullanılamaz.

Bu test, sınırlı BT kurtarmasının yeni hedef seçimine izin verdiğini gösterdi;
ancak sonraki hedefteki ilerleme sorunu ve koşunun yeni hedef tamamlanmadan
bitmesi nedeniyle sürekli navigasyon başarısını kanıtlamadı. Kayıt:
`logs/run-20261004-102028` içindeki `nav2.log` ve `explore.log` (uygulama yeni
başlatıldığında önceki run günlük dizini temizlenmiş olabilir).

## Aktif hedefte ilerleme bekçisi düzeltmesi (11:20)

Kaynak incelemesinde `Explore::makePlan()` başındaki `goal_active_` erken
çıkışının, fonksiyonun altındaki mevcut ilerleme-zaman aşımı kontrolünü
ulaşılamaz yaptığı doğrulandı. Aktif hedef takibini erken dönüş içine taşıdım:
robot hedefe en az 10 cm daha yaklaşınca ilerleme süresi yenileniyor; `progress_timeout`
boyunca anlamlı yaklaşma olmazsa yalnızca aktif frontier kara listeye alınıyor,
Nav2 hedefi iptal ediliyor ve iptal tamamlanınca planner başka frontier seçiyor.
Bu, duvara yaklaşınca acil durdurma eklemez; yerel Nav2 engel kaçınması ve
kurtarmaları süre boyunca çalışır.

Düzeltilen `explore_lite` paketi ROS 2 Jazzy ile başarıyla derlendi ve çalışma
alanına kuruldu. Bu oturumda fiziksel yeniden test başlatılamadı: uygulama
GPIO'ya erişemedi (`can not open gpiochip`) ve ortamda `/dev/gpiochip*` aygıtı
yoktu. Dolayısıyla kaynak/derleme doğrulaması var, canlı hareket doğrulaması
bekliyor. Kaynak için tekrar uygulanabilir tam fark:
`patches/m-explore-active-progress-watchdog.patch`.

## Düzeltilmiş uygulamayla canlı Explore doğrulaması (11:31–11:36)

İlk deneme girişinde normal kısıtlı araç kabuğu GPIO düğümlerini göstermiyordu;
yetkili kabukta Pi 5'in gerçek aygıtları ve robotpi'nin gpio/i2c grupları
bulundu. Ayrıca port 5000'de 10:20'den beri çalışan uygulama varken ikinci
örneği başlatma girişimi port çakışmasıyla kapandı ve ilk örneğin tuttuğu run
log klasörünü temizledi. Bu yüzden eski örneğin Nav2 alt süreçleri log
hedeflerini açamadı; `/odom` gelmeyince başlangıç EKF zaman aşımına uğradı.
Motor komutlarının sıfır olduğu doğrulanıp eski uygulama tek örnek olarak,
donanım erişimli kabukta yeniden başlatıldı. Bu sefer `DISTANCE SERVICE READY`,
IMU ve S3 UART hazırdı. Nav2/SLAM başarıyla çalıştı; LIDAR ön/sol/sağ 184/103/44
cm, ultrasonik 107 cm verdi.

Düzeltilmiş `explore_lite` binary'siyle 150 saniye Explore çalıştırıldı. Test
izleyicisi 12 cm acil sınırından başka yakınlık kesmesi uygulamadı. Üç frontier
hedefi kabul edildi; ilk iki hedef Nav2 `Failed to make progress` ve sınırlı
backup kurtarmaları ardından abort edildi, Explore her ikisini kara listeye
alıp yeni hedefe geçti. Bilinen PGM hücreleri 15.881'den 23.994'e (+8.113; aynı
481×390 grid içinde yaklaşık %8,47'den %12,79'a) yükseldi. SLAM pozu örnekleme
aralığında yaklaşık 45 cm konum değişimi ve yaklaşık 67° yön değişimi gösterdi.
En yakın ön LIDAR 37,4 cm, en yakın ultrasonik 29,9 cm oldu; bu mesafelerde
robot durdurulmadı ve sensör/güç hatası oluşmadı. 150 saniyelik test süresi
bitince Explore ve Nav2 API üzerinden kapatıldı; son motor komutları 0.

Bu canlı koşu, kullanıcının istediği davranışın ana bölümünü doğruladı: robot
30 cm civarında duvara gelince takılıp kalmadı; kurtarma denedi, hedefleri
bıraktı, başka frontier'lara yöneldi ve haritayı büyüttü. Yeni 120 saniyelik
hedef-ilerleme bekçisi derlenmiş ve çalışan binary'deydi, ancak logda
`No meaningful progress ...` kaydı görülmedi; bu koşuda hedef geçişleri Nav2'nin
kendi abort sonucundan sonra oldu. Dolayısıyla bekçinin doğrudan tetiklenmesi
ayrı bir doğrulama konusu; bu test başarılı frontier değiştirme ve engel
çevresinde devam etme davranışını doğruluyor.

Kayıt: `logs/navigation-tests-2026-10-04/1133_active_goal_watchdog.json`;
uygulama/Nav2 logları: `logs/run-20261004-113130/`.
