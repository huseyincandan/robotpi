#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <ArduinoOTA.h>
#include <Wire.h>
#include <esp_system.h>

// Onboard addressable RGB LED (WS2812) for ESP32-S3
#ifndef RGB_BUILTIN
#define RGB_BUILTIN 48
#endif

// Arduino'nun otomatik urettigi fonksiyon prototipleri struct tanimindan once
// eklenebiliyor (motorWrite/motorInit/motorByName Motor* kullaniyor) - ileri
// bildirim bu siralama sorununu onler, struct'in kendisi asagida degismeden kalir.
struct Motor;

// TODO: kendi ev Wi-Fi bilgilerinizi girin
const char *WIFI_SSID = "Deco AP";
const char *WIFI_PASSWORD = "Candan.2162";
const char *HOSTNAME = "robomotor"; // http://robomotor.local
const char *OTA_PASSWORD = "robomotor123"; // kablosuz yukleme sifresi

WebServer server(80);
const int WEB_SPEED = 150; // web arayuzundeki ileri/geri butonlarinin sabit hizi (-255..255)

// 2026-09-05: mecanumdan vazgecildi - on tekerler kaldirilip serbest donen
// sarhos teker (caster) takildi, artik sadece arka 2 teker (RL/RR) tahrikli,
// normal diferansiyel (skid-steer) surus. Tek TB6612FNG kullanilir.
#define PIN_STBY 2

// TB6612 (arka tekerlekler, tek surus kaynagi): PWMA=9 AIN2=10 AIN1=11 BIN1=12 BIN2=13 PWMB=14
#define PIN_RL_IN1 11
#define PIN_RL_IN2 10
#define PIN_RL_PWM 9

#define PIN_RR_IN1 12
#define PIN_RR_IN2 13
#define PIN_RR_PWM 14

const int PWM_FREQ = 20000; // above audible range
const int PWM_RES = 8;      // 0-255 duty

// 2026-09-13: elle cevirme testiyle eslesme belirlendi - sol teker (RL) 37/38,
// sag teker (RR) 39/40 pinlerine bagli. A/B kanal sirasi (hangisi once tetikliyor)
// henuz dogrulanmadi ama quadrature kod her iki sirada da calisir, sadece pozitif/negatif
// yon isareti ters cikarsa asagidaki QUAD_TABLE indeksleme sirasi (A<<1|B) yer degistirilebilir.
#define ENC_RL_A 37
#define ENC_RL_B 38
#define ENC_RR_A 39
#define ENC_RR_B 40

volatile int32_t encPosRL = 0;
volatile int32_t encPosRR = 0;
volatile uint8_t encStateRL = 0;
volatile uint8_t encStateRR = 0;

// standart quadrature gray-code gecis tablosu: index=(eskiState<<2)|yeniState, deger=-1/0/+1
static const int8_t QUAD_TABLE[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};

void IRAM_ATTR encUpdateRL() {
  uint8_t newState = (digitalRead(ENC_RL_A) << 1) | digitalRead(ENC_RL_B);
  encPosRL += QUAD_TABLE[(encStateRL << 2) | newState];
  encStateRL = newState;
}

// 2026-09-13: RL'ye gore RR ters isaretli cikti (ileri cevirince RR eksiye
// gidiyordu) - RR icin A/B okuma sirasi RL'ye gore ters oldugu icin bit
// sirasi (B<<1)|A ile degistirilip isaret RL ile ayni yone getirildi.
void IRAM_ATTR encUpdateRR() {
  uint8_t newState = (digitalRead(ENC_RR_B) << 1) | digitalRead(ENC_RR_A);
  encPosRR += QUAD_TABLE[(encStateRR << 2) | newState];
  encStateRR = newState;
}

void encoderInit() {
  pinMode(ENC_RL_A, INPUT_PULLUP);
  pinMode(ENC_RL_B, INPUT_PULLUP);
  pinMode(ENC_RR_A, INPUT_PULLUP);
  pinMode(ENC_RR_B, INPUT_PULLUP);
  encStateRL = (digitalRead(ENC_RL_A) << 1) | digitalRead(ENC_RL_B);
  encStateRR = (digitalRead(ENC_RR_B) << 1) | digitalRead(ENC_RR_A);
  attachInterrupt(digitalPinToInterrupt(ENC_RL_A), encUpdateRL, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENC_RL_B), encUpdateRL, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENC_RR_A), encUpdateRR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENC_RR_B), encUpdateRR, CHANGE);
}

// test amacli: enkoder pozisyonlarini ~500ms'de bir USB Seri Monitor'e de yazar
const unsigned long ENC_DEBUG_INTERVAL_MS = 500;
unsigned long lastEncDebugMs = 0;

void pollEncoderDebug() {
  unsigned long now = millis();
  if (now - lastEncDebugMs < ENC_DEBUG_INTERVAL_MS) return;
  lastEncDebugMs = now;
  Serial.printf("ENC RL=%ld RR=%ld\n", (long) encPosRL, (long) encPosRR);
}

// Raspberry Pi 5 baglantisi: ayri bir donanim UART (USB uzerindeki debug Serial'dan bagimsiz)
// Kablolama: S3 GPIO17(TX) -> Pi RXD, S3 GPIO18(RX) -> Pi TXD, ortak GND
#define PIN_PI_UART_TX 17
#define PIN_PI_UART_RX 18
const unsigned long PI_UART_BAUD = 115200;
HardwareSerial PiSerial(1);

// 2026-09-06: IMU (MPU6050) + guc monitoru (INA219), Pi'nin kendi I2C hattinda
// motor calisirken olusan EMI'nin "lost arbitration"/"SDA stuck low" seklinde
// I2C'yi kilitlemesi yuzunden buraya, S3'un kendi I2C hattina tasindi. Burada
// okunup Pi'ye UART uzerinden "TELEM ..." satiri olarak aktarilir - UART tek
// bayt hatasinda I2C gibi tum hatti kilitlemedigi icin motor EMI'sine karsi
// daha dayanikli (bkz. services/imu.py EspImuBridge, services/power.py EspPowerBridge).
#define PIN_I2C_SDA 41
#define PIN_I2C_SCL 42

const uint8_t MPU_ADDR = 0x68;
const uint8_t MPU_REG_PWR_MGMT_1 = 0x6B;
const uint8_t MPU_REG_WHO_AM_I = 0x75;
const uint8_t MPU_REG_ACCEL_XOUT_H = 0x3B;
const float MPU_ACCEL_SCALE = 16384.0f; // +-2g varsayilan aralik
const float MPU_GYRO_SCALE = 131.0f;    // +-250dps varsayilan aralik

const uint8_t INA_ADDR = 0x40;
const uint8_t INA_REG_CONFIG = 0x00;
const uint8_t INA_REG_SHUNT_VOLTAGE = 0x01;
const uint8_t INA_REG_BUS_VOLTAGE = 0x02;

// 2026-09-06 test: kesik kesik surus sorununun I2C telemetri okumasindan
// (MPU6050/INA219) kaynaklanip kaynaklanmadigini izole etmek icin gecici
// kapatma anahtari - I2C okumasi sorunun nedeni OLMADIGI test edilerek
// dogrulandi (bkz. bootCount testi), simdi INA219'dan besleme gerilimi/akim
// okuyup pil zayifligi ihtimalini kontrol etmek icin tekrar acildi.
const bool ENABLE_TELEMETRY = true;

// 2026-09-06: kesik kesik surus sorunu web joystick/butonlarindaki pointerleave
// mouse-drift hatasiydi (bkz. bindHold), duzeltme onaylandi - bekci GUVENLIK
// icin tekrar true: false iken komut gelmese bile motor SONSUZA KADAR
// calismaya devam eder (2026-09-02'deki duvara carpma olayinin sebebi buydu).
const bool ENABLE_CMD_WATCHDOG = true;

// 2026-09-06 test: OTA ile guncellenirken USB seri monitor olmadigi icin,
// ESP32'nin motor kalkisinda kendi kendini resetleyip resetlemedigini seri
// baglanti gerektirmeden gormek icin - RTC_DATA_ATTR yazilim/panik/brownout
// resetlerinde SIFIRLANMAZ (sadece tam guc kesintisinde sifirlanir), bu
// yuzden /status adresinden okunup butona basmadan once/sonra karsilastirilabilir.
RTC_DATA_ATTR int bootCount = 0;
RTC_DATA_ATTR int lastResetReason = 0;

bool mpuReady = false;
bool inaReady = false;
unsigned long lastSensorInitAttemptMs = 0;
const unsigned long SENSOR_INIT_RETRY_MS = 3000; // sensor(ler) baslangicta/gecici olarak yoksa periyodik tekrar dene

// 2026-09-07: iki arka teker enkodersiz - ayni PWM'de bile motor verimi/tutunma
// farkindan robot "duz git" komutunda bir yana kayiyordu (kullanici canli test
// ile dogruladi: x=0,y=35 komutunde ~1-2s icinde ~15 derece donme olustu).
// Enkoder bu farki YAKALAYAMAZ (patinajda mil hala "dogru" donuyor gibi
// gorunur) - ama IMU gyro_z, sasinin GERCEKTE ne kadar donmus oldugunu olcer,
// nedeni (motor farki/patinaj) fark etmeksizin. Bu yuzden sabit trim yerine
// gyro tabanli kapali dongu tercih edildi: bkz. driveTank() ve calibrateGyroBias().
float gyroBiasZ = 0.0f;
bool gyroBiasReady = false;
// Kp/limit degerleri ilk tahmin - canli test edilmeden guvenilir sayilmamali.
// Duz giderken sapma devam ederse Kp yukseltilebilir; duzeltme sapmayi
// TERSINE cevirirse (kotulestiriyorsa) isaret (+/-) ters demektir, Kp'nin
// onune eksi koy.
const float STRAIGHT_GYRO_KP = 1.2f;       // PWM birimi / (derece/s) hata
const int STRAIGHT_GYRO_MAX_CORRECTION = 60; // PWM birimi ust sinir
const float STRAIGHT_GYRO_DEADBAND_DPS = 1.5f; // bu esigin altindaki sapma gyro gurultusu sayilir, duzeltme uygulanmaz

// /status uzerinden Pi'ye gec kalmadan tarayicidan pil/gerilim durumunu gormek icin son okunan deger
float lastBusV = 0;
float lastShuntMv = 0;
unsigned long lastPowerReadMs = 0;

const unsigned long TELEM_INTERVAL_MS = 100; // ~10Hz - Pi'nin 150-200ms komut ritmiyle catismaz
unsigned long lastTelemMs = 0;

const unsigned long PI_CMD_TIMEOUT_MS = 250; // Pi guc/baglanti kaybinda motorlari daha hizli durdur
unsigned long lastPiCmdMs = 0;
// bu zaman asimi SADECE Pi UART/USB baglantisi icin - ESP32'nin kendi web
// arayuzunden (joystick/butonlar) surulurken devreye girmesin diye izleniyor;
// web tarafinin kendi WEB_CMD_TIMEOUT_MS bekci mekanizmasi asagida ayrica var.
bool lastCmdWasWeb = false;

// Web joystick/butonlari tarayicinin "birak->dur" JS'ine guveniyordu - wifi/tarayici
// baglantisi koparsa veya pointerup ESP32'ye ulasmazsa motor sonsuza kadar son
// komutu uygulamaya devam ediyordu (2026-09-02: kullanici duvara carpip
// duramadi). Pi komutlarindaki gibi burada da sunucu tarafinda bagimsiz bir
// zaman asimi bekcisi eklendi - joystick suruklerken ~10Hz (100ms) komut
// gonderiliyor, 300ms bu akisi rahat tolere eder ama baglanti koparsa hizla durur.
const unsigned long WEB_CMD_TIMEOUT_MS = 300;
unsigned long lastWebCmdMs = 0;

// TESTMODE: donus/kontrol testlerinde ara siralarda 250ms'i asan gecikme olursa
// motorun "kesik kesik" durup kalkmasini test etmek/gecici olarak asmak icin.
// Guvenlik: hem zaman asimi hem de test modunun kendisi sinirlandirilir - Pi
// baglantiyi kaybederse robot yine de en gec PI_CMD_TEST_MODE_MAX_DURATION_MS
// icinde normal 250ms davranisina geri doner, sonsuza kadar acik kalamaz.
const unsigned long PI_CMD_TEST_TIMEOUT_MAX_MS = 5000;
const unsigned long PI_CMD_TEST_MODE_MAX_DURATION_MS = 60000UL;
unsigned long activeCmdTimeoutMs = PI_CMD_TIMEOUT_MS;
unsigned long testModeExpiresAtMs = 0; // 0 = test modu kapali

struct Motor {
  uint8_t in1, in2, pwm;
  bool reversed; // motor karsi yonde monte edildiyse yon tersine cevrilir
};

// 2026-09-13: enkoderli motorlara gecince kablo kutuplari eskisinin tersi
// oldu, ileri/geri komutu tum tekerlerde ters donuyordu - her iki reversed
// bayragi da ters cevrilerek duzeltildi (RL/RR arasindaki bagil fark korunur).
// 2026-09-13 (later): ileri/geri artik dogruydu ama sol/sag yer degistirmisti -
// yeni motorlar TB6612'ye eski motorlarin tam tersi tarafa baglanmis (fiziksel
// solda montajli motor RR pinlerine, sagdaki RL pinlerine kablolu). Duzeltme
// icin pin+reversed ciftleri (fiziksel motora ait) oldugu gibi tutulup sadece
// RL/RR etiketleri karsilikli degistirildi.
Motor motorRL = {PIN_RR_IN1, PIN_RR_IN2, PIN_RR_PWM, true};
Motor motorRR = {PIN_RL_IN1, PIN_RL_IN2, PIN_RL_PWM, false};

void motorInit(const Motor &m) {
  pinMode(m.in1, OUTPUT);
  pinMode(m.in2, OUTPUT);
  ledcAttach(m.pwm, PWM_FREQ, PWM_RES);
}

// speed: -255 (full reverse) .. 255 (full forward)
const int MIN_EFFECTIVE_SPEED = 60; // bu esigin altindaki komutlar surtunmeyi yenip motoru fiilen cevirmeyebilir
// Yerinde donuste/yana kaymada 4 tekerlek de birden rulo/yanal surtunmeyi
// yenmek zorunda - bu, duz gitmekten cok daha fazla tork ister. MIN_EFFECTIVE_SPEED
// bunun icin yetersiz kaliyordu: nav2 dis=0 omega!=0 komutu gonderiyor, gyro
// donusun gerceklesmedigini gosteriyor, robot hicbir yere hareket etmiyordu.
// Tekerlek basina surtunme/agirlik dagilimi esit degil - 2026-08-30 gozlemi:
// donus baslarken bazen sadece en dusuk surtunmeli tek teker donup patinaj
// yapiyor, digerleri statik surtunmeyi yenemiyor, net donus olmuyor.
// 2026-08-31: floor 130->150, sonra breakaway gucu 220->240 yukseltildi, ama
// guc sadece ilk PIVOT_BREAKAWAY_MS suresince uygulanip sonra dusuruluyordu.
// 2026-08-31 (later): kullanici hala patinaj bildirdi - breakaway suresi
// dolunca guc dusunce bazi (agir yuklu/yuksek surtunkeli) tekerlekler donmeye
// devam edemiyor, tekrar surunmeye/patinaja donuyordu. Zaman asimi tamamen
// kaldirildi: donus (pivot-like) suregeldigi surece PIVOT_BREAKAWAY_SPEED
// butun sure boyunca uygulanir, sadece donus bitince normal guce donulur.
// 2026-09-05: mecanum yana kayma (vy) kaldirildi - artik sadece vx/omega var.
// 2026-09-05 (later): normal tekerlere + on sarhos tekere gecilince 240 (~%94)
// artik asiri agresif kaldi - mecanum rulolarin dusuk tutunmasi icin
// yukseltilmisti, gercek lastikler cok daha iyi tutunuyor. Ilk nav2/explore
// donus komutunda robot sert ve hizli tam tur atti. Guvenli baslangic icin
// dusuruldu - gerekirse tekrar canli test ederek ayarlanabilir.
const int PIVOT_BREAKAWAY_SPEED = 110;

bool isPivotLike(int vx, int omega) {
  return omega != 0 && abs(omega) > abs(vx);
}

// 2026-09-05 (later still): PIVOT_BREAKAWAY_SPEED'in donus SUREGELDIGI SURECE
// sabit uygulanmasi (bkz. yukaridaki 2026-08-31 notu) mecanum tekerlerin dusuk
// tutunmasi icin gerekliydi, ama nav2'nin DWB planlayicisi kendi
// max_vel_theta/acc_lim_theta kinematik modeline gore komut veriyor - eger
// firmware kucuk bir omega komutunu sessizce PIVOT_BREAKAWAY_SPEED'e (~%43)
// yukseltip SURDURURSE, robot nav2'nin varsaydigindan kat kat hizli doner ve
// DWB'nin simule ettigi yorunge ile gercek pozisyon surekli sapar - bu da
// "No valid trajectories"/"Failed to make progress" hatalarina ve sert/
// yalpalayan donuslere yol aciyordu. Normal tekerler mecanuma gore cok daha
// iyi tutundugu icin artik statik surtunmeyi yenmek sadece kisa bir "kick"
// gerektiriyor - kick bitince gercekten istenen (dusuk) hiza dusuluyor, boylece
// nav2'nin komut ettigi hiz ile motorun fiilen dondugu hiz birbirine yakin
// kalir. Eger bu, dusuk hizli donuslerde yine patinaja/durmaya yol acarsa
// (2026-08-31'deki gibi), KICK_MS artirilabilir veya MIN_EFFECTIVE_SPEED
// yukseltilebilir - ama once bu haliyle canli test edilmeli.
const unsigned long PIVOT_BREAKAWAY_KICK_MS = 180;
unsigned long pivotStartMs = 0;
bool pivotActive = false;
int pivotOmegaSign = 0;

// Pi'nin config.py'daki PURE_PIVOT_FORWARD_CREEP_PERCENT'iyle ayni deger -
// ESP32'nin kendi web arayuzundeki joystick Pi'den gecmedigi icin bu enjeksiyonu
// hic gormuyordu; boylece Pi'ye ihtiyac duymadan ayni "saf pivot" davranisi
// ESP32 web arayuzunde de test edilebilir. Sadece handleDrive() (web joystick)
// icinde uygulanir - Pi'nin DRIVE komutu (handlePiCommand) buna dokunmaz, cunku
// nav2'nin kendi Spin recovery'si tam yerinde donus bekliyor.
const float PURE_PIVOT_FORWARD_CREEP_PERCENT = 30.0;

void motorWrite(const Motor &m, int speed, int minEffective = MIN_EFFECTIVE_SPEED) {
  speed = constrain(speed, -255, 255);
  if (speed != 0 && abs(speed) < minEffective) {
    speed = (speed > 0) ? minEffective : -minEffective; // zayif komutlari calisir esige yukselt
  }
  if (m.reversed) speed = -speed;
  digitalWrite(m.in1, speed > 0);
  digitalWrite(m.in2, speed < 0);
  ledcWrite(m.pwm, abs(speed));
}

// vx: ileri(+)/geri(-), omega: saat yonu(+)/tersi(-); hepsi -255..255
// Klasik 2 tekerlekli diferansiyel (skid-steer) surus: sol=vx-omega, sag=vx+omega.
void driveTank(int vx, int omega) {
  // Sadece "duz git" niyetinde (omega=0, komutlu donus yok) gyro duzeltmesi
  // uygula - donus komutu varken (pivot/nav2 spin) karismasin diye omega!=0
  // durumuna hic dokunulmuyor, pivot tespiti de hep ORIJINAL omega'yi kullanir.
  int correctedOmega = omega;
  if (omega == 0 && vx != 0 && gyroBiasReady && mpuReady) {
    float ax, ay, az, gx, gy, gz;
    if (mpuReadMotion(ax, ay, az, gx, gy, gz)) {
      float gzError = gz - gyroBiasZ;
      if (fabs(gzError) >= STRAIGHT_GYRO_DEADBAND_DPS) {
        float correction = -STRAIGHT_GYRO_KP * gzError;
        correction = constrain(correction, -STRAIGHT_GYRO_MAX_CORRECTION, STRAIGHT_GYRO_MAX_CORRECTION);
        correctedOmega = (int) correction;
      }
    }
  }

  int rawL = vx - correctedOmega;
  int rawR = vx + correctedOmega;

  int maxMag = max(abs(rawL), abs(rawR));
  if (maxMag > 255) {
    rawL = rawL * 255 / maxMag;
    rawR = rawR * 255 / maxMag;
  }

  bool pivotLike = isPivotLike(vx, omega);
  int omegaSign = (omega > 0) - (omega < 0);
  if (pivotLike) {
    if (!pivotActive || omegaSign != pivotOmegaSign) {
      pivotStartMs = millis();
      pivotActive = true;
      pivotOmegaSign = omegaSign;
    }
  } else {
    pivotActive = false;
    pivotOmegaSign = 0;
  }

  // Statik surtunmeyi yenmek icin sadece kisa bir baslangic "kick"i - suresi
  // dolunca gercekten istenen hiza (MIN_EFFECTIVE_SPEED tabaniyla) dusulur,
  // nav2'nin komut ettigi hizla motorun fiilen dondugu hiz uyumlu kalsin diye
  // (bkz. yukaridaki isPivotLike ustundeki 2026-09-05 (later still) notu).
  int minEffective = MIN_EFFECTIVE_SPEED;
  if (pivotLike) {
    unsigned long elapsed = millis() - pivotStartMs;
    minEffective = (elapsed < PIVOT_BREAKAWAY_KICK_MS) ? PIVOT_BREAKAWAY_SPEED : MIN_EFFECTIVE_SPEED;
  }

  motorWrite(motorRL, rawL, minEffective);
  motorWrite(motorRR, rawR, minEffective);
}

void stopAll() {
  driveTank(0, 0);
}

// dir: "fwd" ileri, "bwd" geri, herhangi baska deger dur
Motor *motorByName(const String &name) {
  if (name == "RL") return &motorRL;
  if (name == "RR") return &motorRR;
  return nullptr;
}

const char PAGE_HTML[] PROGMEM = R"HTML(
<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RoboMotor Kontrol</title>
<style>
body{font-family:sans-serif;text-align:center;background:#111;color:#eee}
h1{margin-top:20px;font-size:20px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;max-width:420px;margin:20px auto}
.panel{background:#222;border-radius:10px;padding:12px}
.panel h2{margin:0 0 8px;font-size:15px}
button{font-size:15px;padding:10px 12px;margin:3px;border:none;border-radius:6px;cursor:pointer;touch-action:none;-webkit-user-select:none;user-select:none;-webkit-touch-callout:none}
.fwd{background:#2e7d32;color:#fff}
.bwd{background:#c62828;color:#fff}
.stop{background:#555;color:#fff}
.stopall{background:#b71c1c;color:#fff;font-size:18px;padding:14px 28px;margin-top:10px}
.joy-wrap{margin:20px auto}
.joy-base{position:relative;width:180px;height:180px;background:#333;border-radius:50%;margin:10px auto;touch-action:none}
.joy-stick{position:absolute;width:70px;height:70px;background:#1976d2;border-radius:50%;top:55px;left:55px}
</style></head><body>
<h1>RoboMotor Kontrol Paneli</h1>
<div class="joy-wrap"><h2>Joystick</h2>
<div id="joyBase" class="joy-base"><div id="joyStick" class="joy-stick"></div></div>
<div id="joyDbg" style="font-size:13px;color:#999"></div>
</div>
<div class="grid">
<div class="panel"><h2>Sol Teker</h2>
<button class="fwd" id="RL_fwd">Ileri</button>
<button class="bwd" id="RL_bwd">Geri</button></div>
<div class="panel"><h2>Sag Teker</h2>
<button class="fwd" id="RR_fwd">Ileri</button>
<button class="bwd" id="RR_bwd">Geri</button></div>
</div>
<button class="stopall" onclick="fetch('/stopall')">TUMUNU DURDUR</button>
<p><a href="/encoders" style="color:#1976d2">Enkoder Testi</a></p>
<script>
function send(motor,dir){fetch(`/set?motor=${motor}&dir=${dir}`);}
function bindHold(id,motor,dir){
  const el=document.getElementById(id);
  // pointer capture olmadan fare butonu basiliyken imlec elemandan biraz kayarsa
  // pointerleave erken 'stop' gonderiyordu (kesik kesik donme sebebi buydu)
  let activePointerId=null, keepAliveTimer=null;
  const start=(e)=>{
    e.preventDefault();
    activePointerId=e.pointerId;
    el.setPointerCapture(e.pointerId);
    send(motor,dir);
    if(keepAliveTimer) clearInterval(keepAliveTimer);
    keepAliveTimer=setInterval(()=>send(motor,dir),100);
  };
  const stop=(e)=>{
    if(activePointerId===null || e.pointerId!==activePointerId) return;
    e.preventDefault();
    if(keepAliveTimer){clearInterval(keepAliveTimer);keepAliveTimer=null;}
    activePointerId=null;
    send(motor,'stop');
  };
  el.addEventListener('pointerdown',start);
  el.addEventListener('pointerup',stop);
  el.addEventListener('pointercancel',stop);
}
['RL','RR'].forEach(m=>{
  bindHold(m+'_fwd',m,'fwd');
  bindHold(m+'_bwd',m,'bwd');
});

(function(){
  const base=document.getElementById('joyBase');
  const stick=document.getElementById('joyStick');
  const radius=55; // merkezden izin verilen maksimum surukleme mesafesi (px)
  let dragging=false, lastSend=0, inFlight=null, curVx=0, curOmega=0, keepAliveTimer=null;

  function setStick(dx,dy){
    stick.style.left=(55+dx)+'px';
    stick.style.top=(55+dy)+'px';
  }

  function sendDrive(vx,omega){
    if(inFlight) inFlight.abort(); // onceki istek bitmemiş olsa bile en son komut kazansin, kuyruk olusmasin
    inFlight=new AbortController();
    fetch(`/drive?vx=${vx}&omega=${omega}`,{signal:inFlight.signal}).catch(()=>{});
  }

  function update(dx,dy){
    const now=Date.now();
    if(now-lastSend<100) return; // asiri istek gondermeyi onle (~10Hz)
    lastSend=now;
    curVx=Math.round((-dy/radius)*255);
    curOmega=Math.round((-dx/radius)*255); // saga cekince saga, sola cekince sola donsun
    document.getElementById('joyDbg').textContent=`vx:${curVx} omega:${curOmega}`;
    sendDrive(curVx,curOmega);
  }

  function handleMove(e){
    if(!dragging) return;
    e.preventDefault();
    const rect=base.getBoundingClientRect();
    let dx=e.clientX-(rect.left+rect.width/2);
    let dy=e.clientY-(rect.top+rect.height/2);
    const dist=Math.hypot(dx,dy);
    if(dist>radius){dx=dx/dist*radius;dy=dy/dist*radius;}
    setStick(dx,dy);
    update(dx,dy);
  }

  function endDrag(e){
    if(!dragging) return;
    dragging=false;
    if(keepAliveTimer){clearInterval(keepAliveTimer);keepAliveTimer=null;}
    setStick(0,0);
    sendDrive(0,0); // birakinca hemen dur, kuyrukta bekleyen eski komutlari iptal ederek
  }

  base.addEventListener('pointerdown',(e)=>{
    dragging=true;
    base.setPointerCapture(e.pointerId);
    handleMove(e);
    // parmak sabit basili tutulup pointermove tetiklenmezse ESP32'nin kendi
    // WEB_CMD_TIMEOUT_MS (300ms) bekcisi motoru otomatik durduruyordu - bu
    // yuzden surukleme suregeldigi surece son komutu periyodik tekrar gonder.
    if(keepAliveTimer) clearInterval(keepAliveTimer);
    keepAliveTimer=setInterval(()=>{ if(dragging) sendDrive(curVx,curOmega); },100);
  });
  base.addEventListener('pointermove',handleMove);
  base.addEventListener('pointerup',endDrag);
  base.addEventListener('pointerleave',endDrag);
  base.addEventListener('pointercancel',endDrag);
})();
</script>
</body></html>
)HTML";

void handleRoot() {
  server.sendHeader("Cache-Control", "no-store"); // telefon tarayicisi eski JS'i onbellekten kullanmasin
  server.send_P(200, "text/html", PAGE_HTML);
}

void handleSet() {
  if (!server.hasArg("motor") || !server.hasArg("dir")) {
    server.send(400, "text/plain", "eksik parametre");
    return;
  }
  Motor *m = motorByName(server.arg("motor"));
  if (!m) {
    server.send(400, "text/plain", "gecersiz motor");
    return;
  }
  String dir = server.arg("dir");
  int speed = (dir == "fwd") ? WEB_SPEED : (dir == "bwd") ? -WEB_SPEED : 0;
  motorWrite(*m, speed);
  lastCmdWasWeb = true; // Pi zaman asimi bu komutu durdurmasin
  lastWebCmdMs = millis(); // web bekcisi: bu komuttan itibaren say
  server.send(200, "text/plain", "OK");
}

void handleStopAll() {
  stopAll();
  lastCmdWasWeb = true;
  lastWebCmdMs = 0; // zaten durduruldu, bekci tekrar tetiklenmesin
  server.send(200, "text/plain", "OK");
}

void handleStatus() {
  char buf[220];
  snprintf(buf, sizeof(buf),
           "bootCount=%d lastResetReason=%d uptimeMs=%lu busV=%.3f shuntMv=%.3f powerAgeMs=%lu\n",
           bootCount, lastResetReason, millis(), lastBusV, lastShuntMv,
           lastPowerReadMs == 0 ? 0 : millis() - lastPowerReadMs);
  server.send(200, "text/plain", buf);
}

// JS'in ~300ms'de bir fetch ile okudugu yon farkindali enkoder pozisyonlari
void handleEncValues() {
  char buf[64];
  snprintf(buf, sizeof(buf), "RL=%ld RR=%ld\n", (long) encPosRL, (long) encPosRR);
  server.send(200, "text/plain", buf);
}

void handleEncReset() {
  encPosRL = 0;
  encPosRR = 0;
  server.send(200, "text/plain", "OK");
}

// USB Seri Monitor'e erisim olmadan (OTA ile) enkoder testi icin - tarayicidan
// canli izlenebilen sayfa; RL/RR yon farkindali (quadrature) pozisyonlarini gosterir.
const char ENC_PAGE_HTML[] PROGMEM = R"HTML(
<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Enkoder Testi</title>
<style>
body{font-family:sans-serif;text-align:center;background:#111;color:#eee}
h1{margin-top:20px;font-size:20px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;max-width:420px;margin:20px auto}
.pin{background:#222;border-radius:10px;padding:16px}
.pin .num{font-size:13px;color:#999}
.pin .val{font-size:32px;font-weight:bold;margin-top:6px}
button{font-size:16px;padding:12px 24px;margin-top:10px;border:none;border-radius:6px;cursor:pointer;background:#b71c1c;color:#fff}
a{color:#1976d2}
</style></head><body>
<h1>Enkoder Pozisyon Testi</h1>
<div class="grid">
<div class="pin"><div class="num">Sol Teker (RL, GPIO 37/38)</div><div class="val" id="vRL">0</div></div>
<div class="pin"><div class="num">Sag Teker (RR, GPIO 39/40)</div><div class="val" id="vRR">0</div></div>
</div>
<button onclick="fetch('/encreset')">SIFIRLA</button>
<p><a href="/">Kontrol paneline don</a></p>
<script>
async function poll(){
  try{
    const r=await fetch('/encvalues');
    const t=await r.text();
    t.trim().split(' ').forEach(pair=>{
      const [name,val]=pair.split('=');
      const el=document.getElementById('v'+name);
      if(el) el.textContent=val;
    });
  }catch(e){}
}
setInterval(poll,300);
poll();
</script>
</body></html>
)HTML";

void handleEncoders() {
  server.sendHeader("Cache-Control", "no-store");
  server.send_P(200, "text/html", ENC_PAGE_HTML);
}

void handleDrive() {
  if (!server.hasArg("vx") || !server.hasArg("omega")) {
    server.send(400, "text/plain", "eksik parametre");
    return;
  }
  int vx = constrain(server.arg("vx").toInt(), -255, 255);
  int omega = constrain(server.arg("omega").toInt(), -255, 255);
  if (vx == 0 && omega != 0) {
    // saf pivot: Pi'nin nav2/explore/ros2 disi kaynaklarda yaptigi ayni ileri
    // kaymayi burada da enjekte et, boylece Pi'ye gec kalmadan ESP32 web
    // arayuzunden de test edilebilir.
    vx = round(PURE_PIVOT_FORWARD_CREEP_PERCENT / 100.0 * 255);
  }
  driveTank(vx, omega);
  lastCmdWasWeb = true; // Pi zaman asimi bu komutu durdurmasin
  lastWebCmdMs = millis(); // web bekcisi: bu komuttan itibaren say
  server.send(200, "text/plain", "OK");
}

// register'e tek bayt yazar (ornek: MPU6050 uyandirma) - basarisizsa false doner
bool i2cWriteReg(uint8_t addr, uint8_t reg, uint8_t value) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

// register'i secip ardindan N bayt okur (repeated start, MSB once) - basarisizsa false doner, out degismez
bool i2cReadBytes(uint8_t addr, uint8_t reg, uint8_t *out, uint8_t len) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false; // false: hatti birakma (repeated start)
  if (Wire.requestFrom((int) addr, (int) len) != (int) len) return false;
  for (uint8_t i = 0; i < len; i++) out[i] = Wire.read();
  return true;
}

// MPU6050'den ivme (g) + gyro (derece/s) okur - registerlar/olcekler services/imu.py ile ayni
bool mpuReadMotion(float &ax, float &ay, float &az, float &gx, float &gy, float &gz) {
  uint8_t buf[14];
  if (!i2cReadBytes(MPU_ADDR, MPU_REG_ACCEL_XOUT_H, buf, 14)) return false;

  int16_t rawAx = (buf[0] << 8) | buf[1];
  int16_t rawAy = (buf[2] << 8) | buf[3];
  int16_t rawAz = (buf[4] << 8) | buf[5];
  // buf[6..7] sicaklik registeri, kullanilmiyor
  int16_t rawGx = (buf[8] << 8) | buf[9];
  int16_t rawGy = (buf[10] << 8) | buf[11];
  int16_t rawGz = (buf[12] << 8) | buf[13];

  ax = rawAx / MPU_ACCEL_SCALE;
  ay = rawAy / MPU_ACCEL_SCALE;
  az = rawAz / MPU_ACCEL_SCALE;
  gx = rawGx / MPU_GYRO_SCALE;
  gy = rawGy / MPU_GYRO_SCALE;
  gz = rawGz / MPU_GYRO_SCALE;
  return true;
}

// Acilista (robot hareketsizken) gyro_z sapmasini olcup gyroBiasZ'e yazar -
// bu yapilmazsa duz-git duzeltmesi (driveTank icindeki gzError) sensorun
// dinlenme sapmasini gercek donus sanip surekli gereksiz duzeltme uygular.
// MPU henuz hazir degilse sessizce atlanir - o zaman gyroBiasZ 0 kalir,
// sonraki uptime boyunca tekrar denenmez (nadir durum, yeniden acilista duzelir).
void calibrateGyroBias() {
  if (!mpuReady) return;
  const int SAMPLES = 40;
  float sum = 0;
  int ok = 0;
  for (int i = 0; i < SAMPLES; i++) {
    float ax, ay, az, gx, gy, gz;
    if (mpuReadMotion(ax, ay, az, gx, gy, gz)) {
      sum += gz;
      ok++;
    }
    delay(5);
  }
  if (ok > 0) {
    gyroBiasZ = sum / ok;
    gyroBiasReady = true;
  }
  Serial.printf("GYRO BIAS Z: %.3f dps (%d/%d ornek)\n", gyroBiasZ, ok, SAMPLES);
}

// INA219'dan bus voltaji (V) + shunt voltaji (mV) okur - akim hesabi (shunt_ohms gerektirir)
// bilerek Pi tarafinda yapiliyor, config.py tek dogru kaynak olarak kalsin diye
bool inaReadPower(float &busVoltage, float &shuntVoltageMv) {
  uint8_t buf[2];

  if (!i2cReadBytes(INA_ADDR, INA_REG_BUS_VOLTAGE, buf, 2)) return false;
  int16_t rawBus = (buf[0] << 8) | buf[1];
  busVoltage = (rawBus >> 3) * 0.004f;

  if (!i2cReadBytes(INA_ADDR, INA_REG_SHUNT_VOLTAGE, buf, 2)) return false;
  int16_t rawShunt = (buf[0] << 8) | buf[1];
  shuntVoltageMv = rawShunt * 0.01f; // 10uV/LSB -> mV

  return true;
}

// MPU6050/INA219'u tespit edip hazir hale getirmeyi dener; biri/ikisi de takiliysa
// (henuz gec baglanmis, gevsek kablo vb.) loop() icinde periyodik tekrar denenir
void initSensors() {
  lastSensorInitAttemptMs = millis();

  if (!mpuReady) {
    if (i2cWriteReg(MPU_ADDR, MPU_REG_PWR_MGMT_1, 0x00)) {
      uint8_t who = 0;
      if (i2cReadBytes(MPU_ADDR, MPU_REG_WHO_AM_I, &who, 1)) {
        mpuReady = true;
        Serial.printf("MPU6050 HAZIR: who_am_i=0x%02X\n", who);
      }
    }
    if (!mpuReady) Serial.println("MPU6050 bulunamadi, tekrar denenecek");
  }

  if (!inaReady) {
    float v, s;
    if (inaReadPower(v, s)) {
      inaReady = true;
      Serial.println("INA219 HAZIR");
    } else {
      Serial.println("INA219 bulunamadi, tekrar denenecek");
    }
  }
}

// TELEM_INTERVAL_MS'de bir Pi'ye "TELEM ax ay az gx gy gz busV shuntMv encRL encRR" satiri gonderir;
// okuma basarisiz olursa o dongude hic satir gonderilmez (Pi tarafi bunu bayatlik/timeout ile anlar).
// encRL/encRR: 2026-09-13'te eklenen kadranaj (quadrature) enkoderlerin kumulatif tik sayaclari -
// navigasyonda gercek tekerlek odometrisi icin kullanilir (bkz. services/motor.py _parse_telemetry,
// scripts/ros2_cmdvel_bridge.py encoder-based odom).
void pollTelemetry() {
  if (!ENABLE_TELEMETRY) return;

  unsigned long now = millis();

  if ((!mpuReady || !inaReady) && now - lastSensorInitAttemptMs >= SENSOR_INIT_RETRY_MS) {
    initSensors();
  }

  if (now - lastTelemMs < TELEM_INTERVAL_MS) return;
  lastTelemMs = now;

  float ax, ay, az, gx, gy, gz, busV, shuntMv;
  bool mpuOk = mpuReady && mpuReadMotion(ax, ay, az, gx, gy, gz);
  bool inaOk = inaReady && inaReadPower(busV, shuntMv);

  if (!mpuOk) mpuReady = false; // bir sonraki dongude initSensors tekrar dener
  if (!inaOk) inaReady = false;

  if (!mpuOk || !inaOk) return; // eksik veri gonderilmez

  lastBusV = busV;
  lastShuntMv = shuntMv;
  lastPowerReadMs = now;

  // encPosRL/encPosRR: 32-bit hizalanmis okuma tek instruction'da atomik (ISR yari yolda
  // kesmez), pollEncoderDebug()/handleEncValues() de ayni sekilde kilitsiz okuyor.
  PiSerial.printf("TELEM %.4f %.4f %.4f %.3f %.3f %.3f %.4f %.3f %ld %ld\n",
                  ax, ay, az, gx, gy, gz, busV, shuntMv,
                  (long) encPosRL, (long) encPosRR);
}

// Pi'den gelen satir tabanli komutlari isle. Desteklenen komutlar:
//   DRIVE <vx> <omega>  - genel karisik surus, ileri/geri + donus (-255..255)
//   FWD [hiz]  BWD [hiz]  LEFT [hiz]  RIGHT [hiz]  - temel yon komutlari (hiz verilmezse WEB_SPEED kullanilir)
//   SET <motor> <fwd|bwd|stop> [hiz]  - tek tekeri dogrudan kontrol et (motor: RL/RR, hiz: 0-255, verilmezse WEB_SPEED)
//   STOP  - tum motorlari durdur
//   PING  - baglanti testi, PONG doner
//   TESTMODE <timeout_ms> <sure_s>  - kontrol/donus testleri icin komut zaman asimini gecici uzatir
//                                     (timeout_ms en fazla 5000, sure_s en fazla 60s ile sinirli - sure dolunca
//                                     otomatik olarak normal 250ms'e doner)
//   TESTMODE_OFF  - test modunu hemen kapatip normal 250ms zaman asimina doner
// Her komuta "OK"/"ERR ..." veya ilgili yanit satiri ile cevap verilir.
// Pi hem UART (PiSerial) hem de USB (Serial) uzerinden baglanabilir; cevap komutun geldigi akisa yazilir.
// Ayrica: Pi'nin istegi disinda, S3 PiSerial'a ~10Hz "TELEM ..." satiri gonderir
// (bkz. pollTelemetry()) - bu bir komut CEVABI degildir, Pi tarafi bunu asenkron
// olarak dinleyip ayristirir (services/motor.py _serial_reader_loop).
void handlePiCommand(String line, Stream &out) {
  line.trim();
  if (line.length() == 0) return;
  int sp = line.indexOf(' ');
  String cmd = (sp == -1) ? line : line.substring(0, sp);
  String rest = (sp == -1) ? "" : line.substring(sp + 1);
  cmd.toUpperCase();
  lastPiCmdMs = millis(); // herhangi bir komut baglantinin canli oldugunu gosterir
  lastCmdWasWeb = false; // Pi tekrar komut gonderiyor, zaman asimi izlemesi Pi'ye geri donsun

  if (cmd == "PING") {
    out.println("PONG");
  } else if (cmd == "STOP") {
    stopAll();
    out.println("OK");
  } else if (cmd == "DRIVE") {
    int sp2 = rest.indexOf(' ');
    if (sp2 == -1) { out.println("ERR eksik parametre"); return; }
    int vx = constrain(rest.substring(0, sp2).toInt(), -255, 255);
    int omega = constrain(rest.substring(sp2 + 1).toInt(), -255, 255);
    driveTank(vx, omega);
    out.println("OK");
  } else if (cmd == "FWD" || cmd == "BWD" || cmd == "LEFT" || cmd == "RIGHT") {
    int speed = rest.length() ? constrain(rest.toInt(), 0, 255) : WEB_SPEED;
    if (cmd == "FWD") driveTank(speed, 0);
    else if (cmd == "BWD") driveTank(-speed, 0);
    else if (cmd == "LEFT") driveTank(0, -speed);
    else driveTank(0, speed); // RIGHT
    out.println("OK");
  } else if (cmd == "SET") {
    int sp2 = rest.indexOf(' ');
    if (sp2 == -1) { out.println("ERR eksik parametre"); return; }
    Motor *m = motorByName(rest.substring(0, sp2));
    if (!m) { out.println("ERR gecersiz motor"); return; }
    String rest2 = rest.substring(sp2 + 1);
    int sp3 = rest2.indexOf(' ');
    String dir = (sp3 == -1) ? rest2 : rest2.substring(0, sp3);
    // opsiyonel hiz (0-255): "SET FL fwd 80" gibi, verilmezse WEB_SPEED kullanilir
    int speedMag = (sp3 == -1) ? WEB_SPEED : constrain(rest2.substring(sp3 + 1).toInt(), 0, 255);
    int speed = (dir == "fwd") ? speedMag : (dir == "bwd") ? -speedMag : 0;
    motorWrite(*m, speed);
    out.println("OK");
  } else if (cmd == "TESTMODE") {
    int sp2 = rest.indexOf(' ');
    if (sp2 == -1) { out.println("ERR eksik parametre"); return; }
    unsigned long reqTimeoutMs = (unsigned long) rest.substring(0, sp2).toInt();
    unsigned long reqDurationS = (unsigned long) rest.substring(sp2 + 1).toInt();
    activeCmdTimeoutMs = constrain(reqTimeoutMs, PI_CMD_TIMEOUT_MS, PI_CMD_TEST_TIMEOUT_MAX_MS);
    testModeExpiresAtMs = millis() + constrain(reqDurationS * 1000UL, 0UL, PI_CMD_TEST_MODE_MAX_DURATION_MS);
    out.println("OK");
  } else if (cmd == "TESTMODE_OFF") {
    activeCmdTimeoutMs = PI_CMD_TIMEOUT_MS;
    testModeExpiresAtMs = 0;
    out.println("OK");
  } else {
    out.println("ERR bilinmeyen komut");
  }
}

// verilen akistan (UART ya da USB) satir satir komut toplayip isler; her akisin kendi tampon degiskeni olmali
void pollCommandStream(Stream &in, Stream &out, String &buf) {
  while (in.available()) {
    char c = in.read();
    if (c == '\n') {
      handlePiCommand(buf, out);
      buf = "";
    } else if (c != '\r') {
      buf += c;
      if (buf.length() > 96) buf = ""; // asiri uzun/bozuk satiri at
    }
  }
}

// PiSerial (UART) ve Serial (USB) akislarini bagimsiz tamponlarla dinler, baglanti kesilirse motorlari durdurur
void pollPiSerial() {
  static String uartBuf;
  static String usbBuf;
  pollCommandStream(PiSerial, PiSerial, uartBuf);
  pollCommandStream(Serial, Serial, usbBuf);
  if (testModeExpiresAtMs != 0 && millis() > testModeExpiresAtMs) {
    activeCmdTimeoutMs = PI_CMD_TIMEOUT_MS; // test modu suresi doldu, guvenli varsayilana don
    testModeExpiresAtMs = 0;
  }
  if (!ENABLE_CMD_WATCHDOG) return;
  if (!lastCmdWasWeb && lastPiCmdMs != 0 && millis() - lastPiCmdMs > activeCmdTimeoutMs) {
    stopAll();
    lastPiCmdMs = 0;
  }
  if (lastCmdWasWeb && lastWebCmdMs != 0 && millis() - lastWebCmdMs > WEB_CMD_TIMEOUT_MS) {
    stopAll(); // tarayici/wifi baglantisi koptu, son komutta sonsuza dek takili kalma
    lastWebCmdMs = 0;
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  bootCount++;
  lastResetReason = (int) esp_reset_reason(); // 1=power-on, 3=yazilim, 4=panik/wdt, 15=brownout
  // 2026-09-06 test: motor kalkis aninda besleme gerilimi cokup ESP32'nin
  // brown-out/panik nedeniyle kendi kendini resetleyip resetlemedigini
  // gormek icin - eger test sirasinda bu satir tekrar basiliyorsa (yeniden
  // WiFi taramasi/baglanmasi ile birlikte), sorun elektriksel (guc hatti).
  Serial.printf("ACILIS - reset nedeni: %d, bootCount=%d\n", lastResetReason, bootCount);
  PiSerial.begin(PI_UART_BAUD, SERIAL_8N1, PIN_PI_UART_RX, PIN_PI_UART_TX); // Pi 5 UART hatti

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setClock(100000); // Pi'deki EMI arastirmasinda da 100kHz kullanildi, tutarlilik icin ayni
  if (ENABLE_TELEMETRY) initSensors();
  calibrateGyroBias(); // robot bu noktada hareketsiz varsayilir (acilis)

  neopixelWrite(RGB_BUILTIN, 0, 0, 0); // LED kapali kalsin

  pinMode(PIN_STBY, OUTPUT);
  digitalWrite(PIN_STBY, HIGH); // enable both TB6612 drivers

  motorInit(motorRL);
  motorInit(motorRR);
  encoderInit();
  stopAll(); // web arayuzunden komut gelene kadar dur

  WiFi.mode(WIFI_STA);
  WiFi.setHostname(HOSTNAME);
  WiFi.setSleep(false); // modem sleep kapali: joystick komutlarinda gecikme olmasin

  Serial.println("Bulunan Wi-Fi aglari:");
  int n = WiFi.scanNetworks();
  for (int i = 0; i < n; i++) {
    Serial.printf("  %s (%ddBm) kanal:%d %s\n", WiFi.SSID(i).c_str(), WiFi.RSSI(i), WiFi.channel(i),
                  (WiFi.encryptionType(i) == WIFI_AUTH_OPEN) ? "acik" : "sifreli");
  }

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("WiFi baglaniyor");
  unsigned long startMs = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startMs < 20000) {
    delay(500);
    Serial.printf(" (durum:%d)", WiFi.status());
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("IP adresi: ");
    Serial.println(WiFi.localIP());
    if (MDNS.begin(HOSTNAME)) {
      Serial.println("Adres: http://robomotor.local");
    }

    ArduinoOTA.setHostname(HOSTNAME);
    ArduinoOTA.setPassword(OTA_PASSWORD);
    ArduinoOTA.onStart([]() { stopAll(); }); // yukleme sirasinda motorlar dursun
    ArduinoOTA.begin();
    Serial.println("OTA hazir (kablosuz yukleme icin bekleniyor)");
  } else {
    Serial.println("WiFi baglantisi kurulamadi! SSID/sifreyi ve 2.4GHz uyumlulugunu kontrol edin.");
  }

  server.on("/", handleRoot);
  server.on("/set", handleSet);
  server.on("/stopall", handleStopAll);
  server.on("/drive", handleDrive);
  server.on("/status", handleStatus);
  server.on("/encoders", handleEncoders);
  server.on("/encvalues", handleEncValues);
  server.on("/encreset", handleEncReset);
  server.begin();
}

void loop() {
  server.handleClient();
  ArduinoOTA.handle();
  pollPiSerial();
  pollTelemetry();
  pollEncoderDebug();
}
