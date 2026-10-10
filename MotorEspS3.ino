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

// Pi tarafindaki config.py POWER_MONITOR degerleriyle ayni (SHUNT_OHMS,
// MIN/MAX_VOLTAGE, LOW_VOLTAGE_WARNING) - /power buradan hesaplanan yuzde/akim
// Pi'nin web arayuzunde gosterdigiyle ayni cikmasi icin bu degerler senkron
// tutulmali.
const float BATTERY_SHUNT_OHMS = 0.1f;
const float BATTERY_MIN_VOLTAGE = 9.9f;
const float BATTERY_MAX_VOLTAGE = 12.6f;
const float BATTERY_LOW_VOLTAGE_WARNING = 10.5f;

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
// Gyro 50Hz okunur ve filtrelenir; hiz esitlemeyi encoder PI yapar.
const float STRAIGHT_GYRO_KP = 0.45f;      // PWM birimi / (derece/s) hata
const float STRAIGHT_HEADING_KP = 2.5f;    // PWM birimi / derece birikmis yon hatasi
const int STRAIGHT_GYRO_MAX_CORRECTION = 20; // PWM birimi ust sinir
const float STRAIGHT_GYRO_DEADBAND_DPS = 1.0f;
const float STRAIGHT_HEADING_DEADBAND_DEG = 0.4f;
const float STRAIGHT_HEADING_MAX_DEG = 15.0f;
const float STRAIGHT_GYRO_FILTER_ALPHA = 0.25f;
const unsigned long IMU_READ_INTERVAL_MS = 20;
// A stationary window must pass encoder, acceleration and gyro checks.
// Absolute rate limit also rejects steady rotation (low variance alone cannot).
const unsigned long GYRO_CAL_WINDOW_MS = 2000;
const unsigned long GYRO_CAL_SETTLE_MS = 500;
const float GYRO_CAL_MAX_RATE_DPS = 5.0f;
const float GYRO_CAL_MAX_SPREAD_DPS = 0.8f;
int commandedPwmRL = 0;
int commandedPwmRR = 0;
unsigned long lastMotorMotionMs = 0;
bool gyroCalibrationPending = true;
const char *gyroCalibrationState = "waiting";
unsigned long gyroCalStartMs = 0;
unsigned long gyroCalLastSampleMs = 0;
unsigned int gyroCalSamples = 0;
float gyroCalSumZ = 0;
float gyroCalMin[3] = {0, 0, 0};
float gyroCalMax[3] = {0, 0, 0};
int32_t gyroCalEncRL = 0;
int32_t gyroCalEncRR = 0;

void resetGyroCalibrationWindow() {
  gyroCalSamples = 0;
  gyroCalStartMs = 0;
  gyroCalibrationState = "waiting";
}

// 2026-09-22: ayni PWM'de sag enkoderin soldan %7-%13 fazla tik urettigi
// iki duz-surustle dogrulandi. Gyro tek basina sasinin sapmasini gec fark
// eder; once iki tekerin ENKODER HIZINI esitleyen hizli ic dongu, onun
// ustunde de gyro ile gercek yaw duzeltmesi kullanilir. Bu dongu sadece
// DRIVE/FWD/BWD ile istenen duz suruste aktiftir; SET (tek teker) ve istemli
// donuslere kesinlikle karismaz.
const unsigned long STRAIGHT_CONTROL_INTERVAL_MS = 50;
const float STRAIGHT_ENCODER_KP = 0.12f;       // PWM / (50ms tik farki)
const float STRAIGHT_ENCODER_KI = 0.55f;       // PWM / (tik*saniye farki)
const int STRAIGHT_ENCODER_MAX_CORRECTION = 40;
bool tankDriveActive = false;
bool straightAssistActive = false;
int tankCommandVx = 0;
int tankCommandOmega = 0;
int32_t straightPrevEncRL = 0;
int32_t straightPrevEncRR = 0;
int32_t lastStraightDeltaRL = 0;
int32_t lastStraightDeltaRR = 0;
float straightEncoderIntegral = 0.0f;
int straightEncoderCorrection = 0;
float lastStraightGyroRateCorrection = 0.0f;
float lastStraightHeadingCorrection = 0.0f;
int lastStraightCorrectedOmega = 0;
int lastStraightPwmRL = 0;
int lastStraightPwmRR = 0;
int lastStraightAppliedVx = 0;
unsigned long lastStraightControlMs = 0;
float straightHeadingErrorDeg = 0.0f;
float lastGyroZ = 0.0f;
bool lastGyroZValid = false;
float lastAx = 0.0f;
float lastAy = 0.0f;
float lastAz = 0.0f;
float lastGx = 0.0f;
float lastGy = 0.0f;
float lastRawGyroZ = 0.0f;
unsigned long lastImuReadMs = 0;

// /status uzerinden Pi'ye gec kalmadan tarayicidan pil/gerilim durumunu gormek icin son okunan deger
float lastBusV = 0;
float lastShuntMv = 0;
unsigned long lastPowerReadMs = 0;

// Encoder feedback drives the Pi's fixed-PWM pulse controller. 10 Hz left
// each 150-PWM pulse active for at least ~100 ms, far longer than the
// controller's 14 Hz output interval; publish at 50 Hz so the bridge can
// close the position loop before a full high-power pulse accumulates.
const unsigned long TELEM_INTERVAL_MS = 20;
const unsigned long POWER_READ_INTERVAL_MS = 5000;
const unsigned long POWER_MAX_AGE_MS = 20000;
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

// 2026-09-27 dusuk-PWM kalibrasyonunda TB6612 cikislari fiziksel olarak
// degistirildi: sol motor artik A (PIN_RL), sag motor B (PIN_RR) kanalinda.
// Havada 76 PWM testinde bu eslesme RL=~2160, RR=~2230 tik ile dengelendi.
// Enkoder pinleri fiziksel tekerlerde oldugu icin burada yalnizca motor cikis
// eslesmesi degisir. Iki motorun fwd kutuplulugu mevcut kablolamada dogrudur.
Motor motorRL = {PIN_RL_IN1, PIN_RL_IN2, PIN_RL_PWM, false};
Motor motorRR = {PIN_RR_IN1, PIN_RR_IN2, PIN_RR_PWM, false};

// TURNRATE uses degrees/second with the measured gyro Z sign; DRIVE remains PWM.
bool yawRateActive = false;
float yawTargetDps = 0;
float yawIntegral = 0;
float yawOutput = 0;
float yawErrorDps = 0;
float yawFeedforwardPwm = 0;
float yawRequestedPwm = 0;
int yawVx = 0;
unsigned long yawLastMs = 0;
const float YAW_MAX_DPS = 60.0f;
const float YAW_MAX_PWM = 255.0f;
const float YAW_KP = 0.4f;
const float YAW_KI = 0.8f;
// The previous fixed 55-PWM feedforward produced ~18-20 dps for an 8-dps
// target on the current wheels. Reduce the base and soften the output ramp;
// validate these provisional values with the guarded hardware pulse test.
const float YAW_FEEDFORWARD_BASE_PWM = 40.0f;
const float YAW_FEEDFORWARD_PWM_PER_DPS = 0.35f;
const float YAW_OUTPUT_SLEW_PWM_PER_SEC = 100.0f;
const char *yawFault = "none";

void motorInit(const Motor &m) {
  pinMode(m.in1, OUTPUT);
  pinMode(m.in2, OUTPUT);
  ledcAttach(m.pwm, PWM_FREQ, PWM_RES);
}

// speed: -255 (full reverse) .. 255 (full forward)
void motorWrite(const Motor &m, int speed) {
  speed = constrain(speed, -255, 255);
  if (m.pwm == PIN_RL_PWM) commandedPwmRL = speed;
  if (m.pwm == PIN_RR_PWM) commandedPwmRR = speed;
  if (speed != 0) {
    lastMotorMotionMs = millis();
    if (gyroCalibrationPending) resetGyroCalibrationWindow();
  }
  if (speed == 0) {
    // TB6612FNG: IN1=HIGH, IN2=HIGH kisa fren; iki tekerin stopta
    // farkli miktarda suzulup robotu dondurmesini azaltir.
    digitalWrite(m.in1, HIGH);
    digitalWrite(m.in2, HIGH);
    ledcWrite(m.pwm, 255);
    return;
  }
  if (m.reversed) speed = -speed;
  digitalWrite(m.in1, speed > 0);
  digitalWrite(m.in2, speed < 0);
  ledcWrite(m.pwm, abs(speed));
}

void resetStraightController() {
  noInterrupts();
  straightPrevEncRL = encPosRL;
  straightPrevEncRR = encPosRR;
  interrupts();
  straightEncoderIntegral = 0.0f;
  straightEncoderCorrection = 0;
  lastStraightControlMs = millis();
  straightHeadingErrorDeg = 0.0f;
}

void applyTankDrive(int vx, int omega, int encoderCorrection = 0) {
  int appliedVx = vx;
  int correctedOmega = omega;
  float gyroRateCorrection = 0.0f;
  float headingCorrection = 0.0f;
  if (straightAssistActive && omega == 0 && vx != 0) {
    if (gyroBiasReady && lastGyroZValid) {
      float gzError = lastGyroZ - gyroBiasZ;
      if (fabs(gzError) >= STRAIGHT_GYRO_DEADBAND_DPS) {
        gyroRateCorrection = -STRAIGHT_GYRO_KP * gzError;
      }
      if (fabs(straightHeadingErrorDeg) >= STRAIGHT_HEADING_DEADBAND_DEG) {
        headingCorrection = -STRAIGHT_HEADING_KP * straightHeadingErrorDeg;
      }
    }
    float gyroCorrection = constrain(gyroRateCorrection + headingCorrection,
                                     -STRAIGHT_GYRO_MAX_CORRECTION,
                                     STRAIGHT_GYRO_MAX_CORRECTION);
    correctedOmega = (int) (gyroCorrection + encoderCorrection);
  }

  int rawL = appliedVx - correctedOmega;
  int rawR = appliedVx + correctedOmega;

  int maxMag = max(abs(rawL), abs(rawR));
  if (maxMag > 255) {
    rawL = rawL * 255 / maxMag;
    rawR = rawR * 255 / maxMag;
  }

  lastStraightGyroRateCorrection = gyroRateCorrection;
  lastStraightHeadingCorrection = headingCorrection;
  lastStraightCorrectedOmega = correctedOmega;
  lastStraightPwmRL = rawL;
  lastStraightPwmRR = rawR;
  lastStraightAppliedVx = appliedVx;

  motorWrite(motorRL, rawL);
  motorWrite(motorRR, rawR);
}

// vx: ileri(+)/geri(-), omega: sola/CCW(+), saga/CW(-); hepsi -255..255.
// Yeni komut sadece hedefi kaydeder; pollStraightDriveControl() 20Hz'de
// enkoder farkini kapatarak motor cikisini surekli gunceller.
void driveTank(int vx, int omega, bool applyStraightGyroCorrection = true) {
  yawRateActive = false;
  yawTargetDps = 0; yawOutput = 0; yawIntegral = 0;
  vx = constrain(vx, -255, 255);
  omega = constrain(omega, -255, 255);
  if (vx == 0 && omega == 0) {
    tankDriveActive = false;
    straightAssistActive = false;
    lastStraightAppliedVx = 0;
    motorWrite(motorRL, 0);
    motorWrite(motorRR, 0);
    return;
  }

  bool nextStraightAssist = applyStraightGyroCorrection && omega == 0 && vx != 0;
  // Pi/web keep-alive komutlari ayni duz-surus niyetini siklikla tekrarlar
  // ve guvenlik katmani PWM buyuklugunu kucuk miktarlarda degistirebilir.
  // Bunlar PI durumunu sifirlamamali: aksi halde her yeni DRIVE, onceki
  // encoder duzeltmesini silip tekerleri yeniden esit PWM'e dondurur.
  bool directionChanged = (vx > 0) != (tankCommandVx > 0);
  if (!tankDriveActive || directionChanged ||
      nextStraightAssist != straightAssistActive) {
    resetStraightController();
  }
  tankDriveActive = true;
  straightAssistActive = nextStraightAssist;
  tankCommandVx = vx;
  tankCommandOmega = omega;
  applyTankDrive(vx, omega,
                 nextStraightAssist ? straightEncoderCorrection : 0);
}

void disableTankDrive() {
  yawRateActive = false;
  tankDriveActive = false;
  straightAssistActive = false;
  straightEncoderIntegral = 0.0f;
  straightEncoderCorrection = 0;
  straightHeadingErrorDeg = 0.0f;
}

void pollStraightDriveControl() {
  if (!tankDriveActive || !straightAssistActive || tankCommandVx == 0) return;
  unsigned long now = millis();
  unsigned long elapsedMs = now - lastStraightControlMs;
  if (elapsedMs < STRAIGHT_CONTROL_INTERVAL_MS) return;
  lastStraightControlMs = now;

  int32_t encRL, encRR;
  noInterrupts();
  encRL = encPosRL;
  encRR = encPosRR;
  interrupts();

  int32_t deltaRL = encRL - straightPrevEncRL;
  int32_t deltaRR = encRR - straightPrevEncRR;
  straightPrevEncRL = encRL;
  straightPrevEncRR = encRR;
  lastStraightDeltaRL = deltaRL;
  lastStraightDeltaRR = deltaRR;

  // r-l farkinin isareti ileri/geri harekette de dogrudan istenen omega
  // isaretidir; sag fazla donerse negatif omega sol PWM'yi artirip sag
  // PWM'yi azaltir.
  float tickDifference = (float) (deltaRR - deltaRL);
  float dtSec = elapsedMs / 1000.0f;
  straightEncoderIntegral += tickDifference * dtSec;
  straightEncoderIntegral = constrain(straightEncoderIntegral, -40.0f, 40.0f);
  float correction = -STRAIGHT_ENCODER_KP * tickDifference
                   - STRAIGHT_ENCODER_KI * straightEncoderIntegral;
  correction = constrain(correction,
                         -STRAIGHT_ENCODER_MAX_CORRECTION,
                         STRAIGHT_ENCODER_MAX_CORRECTION);
  straightEncoderCorrection = (int) correction;
  applyTankDrive(tankCommandVx, tankCommandOmega, straightEncoderCorrection);
}

void stopAll() {
  driveTank(0, 0);
}

bool driveYawRate(int vx, float rate) {
  if (!isfinite(rate) || fabs(rate) > YAW_MAX_DPS || abs(vx) > 155) {
    stopAll(); yawFault = "invalid_target"; return false;
  }
  if (!mpuReady || !gyroBiasReady || !lastGyroZValid ||
      millis() - lastImuReadMs > 100) {
    stopAll(); yawFault = "imu_unavailable"; return false;
  }
  yawFault = "none";
  if (fabs(rate) < 0.1f) {
    driveTank(vx, 0, true);
    yawTargetDps = 0; yawOutput = 0; yawIntegral = 0;
    return true;
  }
  bool restart = !yawRateActive || (rate > 0) != (yawTargetDps > 0);
  disableTankDrive();
  yawRateActive = true;
  yawTargetDps = rate; yawVx = vx;
  if (restart) {
    yawIntegral = 0; yawOutput = 0; yawLastMs = millis();
    motorWrite(motorRL, 0); motorWrite(motorRR, 0);
  }
  return true;
}

void pollYawRateControl() {
  if (!yawRateActive) return;
  unsigned long now = millis();
  if (!mpuReady || !gyroBiasReady || !lastGyroZValid || now - lastImuReadMs > 100) {
    stopAll(); yawFault = "imu_unavailable"; return;
  }
  unsigned long elapsed = now - yawLastMs;
  if (elapsed < 20) return;
  if (elapsed > 150) { stopAll(); yawFault = "control_gap"; return; }
  yawLastMs = now;
  float dt = elapsed / 1000.0f;
  float error = yawTargetDps - (lastGyroZ - gyroBiasZ);
  yawErrorDps = error;
  float candidate = constrain(yawIntegral + YAW_KI * error * dt, -60.0f, 60.0f);
  float feedforward = copysignf(YAW_FEEDFORWARD_BASE_PWM, yawTargetDps)
                    + YAW_FEEDFORWARD_PWM_PER_DPS * yawTargetDps;
  yawFeedforwardPwm = feedforward;
  float requested = feedforward + YAW_KP * error + candidate;
  // Conditional integration prevents windup at the PWM limit.
  if (fabs(requested) < YAW_MAX_PWM || requested * error < 0) yawIntegral = candidate;
  requested = constrain(feedforward + YAW_KP * error + yawIntegral, -YAW_MAX_PWM, YAW_MAX_PWM);
  // No reverse torque during a turn; STOP still applies the hardware brake immediately.
  if (requested * yawTargetDps < 0) requested = 0;
  yawRequestedPwm = requested;
  yawOutput += constrain(requested - yawOutput,
                          -YAW_OUTPUT_SLEW_PWM_PER_SEC * dt,
                          YAW_OUTPUT_SLEW_PWM_PER_SEC * dt);
  applyTankDrive(yawVx, (int) roundf(yawOutput));
}

void handleYawRate() {
  if (!server.hasArg("vx") || !server.hasArg("dps")) {
    server.send(400, "text/plain", "ERR missing vx/dps"); return;
  }
  char *end;
  String rateText = server.arg("dps");
  float rate = strtof(rateText.c_str(), &end);
  if (end == rateText.c_str() || *end != '\0') {
    stopAll(); server.send(400, "text/plain", "ERR invalid rate"); return;
  }
  bool ok = driveYawRate(server.arg("vx").toInt(), rate);
  lastCmdWasWeb = true; lastWebCmdMs = millis();
  server.send(ok ? 200 : 409, "text/plain", ok ? "OK" : yawFault);
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
.drive-controls{display:grid;grid-template-columns:1fr 1fr;gap:8px;max-width:420px;margin:20px auto 0}
.drive-controls button{font-size:15px;padding:14px 8px}
.joy-wrap{margin:20px auto}
.joy-base{position:relative;width:180px;height:180px;background:#333;border-radius:50%;margin:10px auto;touch-action:none}
.joy-stick{position:absolute;width:70px;height:70px;background:#1976d2;border-radius:50%;top:55px;left:55px}
.topbar{display:flex;flex-direction:column;align-items:center;gap:4px;max-width:420px;margin:0 auto}
.battery-info{text-align:center;font-size:13px;color:#999}
.battery-info.battery-low{color:#ff5c5c;font-weight:bold}
</style></head><body>
<div class="topbar">
<h1>RoboMotor Kontrol Paneli</h1>
<div class="battery-info" id="batteryInfo">Pil: -</div>
</div>
<div class="joy-wrap"><h2>Joystick</h2>
<div id="joyBase" class="joy-base"><div id="joyStick" class="joy-stick"></div></div>
<div id="joyDbg" style="font-size:13px;color:#999"></div>
</div>
<div class="drive-controls">
<button class="fwd" id="drive_fwd">ILERI (DOGRUDAN)</button>
<button class="bwd" id="drive_bwd">GERI (DOGRUDAN)</button>
<button class="fwd" id="drive_corrected_fwd">DUZELTMELI ILERI</button>
<button class="bwd" id="drive_corrected_bwd">DUZELTMELI GERI</button>
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

function sendTank(vx,assist){fetch(`/drive?vx=${vx}&omega=0&assist=${assist?1:0}`).catch(()=>{});}
function bindDriveHold(id,vx,assist){
  const el=document.getElementById(id);
  let activePointerId=null, keepAliveTimer=null;
  const start=(e)=>{
    e.preventDefault();
    activePointerId=e.pointerId;
    el.setPointerCapture(e.pointerId);
    sendTank(vx,assist);
    if(keepAliveTimer) clearInterval(keepAliveTimer);
    keepAliveTimer=setInterval(()=>sendTank(vx,assist),100);
  };
  const stop=(e)=>{
    if(activePointerId===null || e.pointerId!==activePointerId) return;
    e.preventDefault();
    clearInterval(keepAliveTimer);
    keepAliveTimer=null;
    activePointerId=null;
    sendTank(0,assist);
  };
  el.addEventListener('pointerdown',start);
  el.addEventListener('pointerup',stop);
  el.addEventListener('pointercancel',stop);
}
bindDriveHold('drive_fwd',150,false);
bindDriveHold('drive_bwd',-150,false);
bindDriveHold('drive_corrected_fwd',150,true);
bindDriveHold('drive_corrected_bwd',-150,true);

const batteryInfo=document.getElementById('batteryInfo');
function loadBattery(){
  fetch('/power').then(r=>r.json()).then(data=>{
    if(!data || data.status!=='OK'){
      batteryInfo.textContent='Pil: -';
      batteryInfo.classList.remove('battery-low');
      return;
    }
    batteryInfo.textContent=`Pil: ${data.bus_voltage.toFixed(2)}V / ${data.battery_percent}% / ${data.current_ma.toFixed(0)}mA`;
    batteryInfo.classList.toggle('battery-low',Boolean(data.low_voltage));
  }).catch(()=>{
    batteryInfo.textContent='Pil: -';
    batteryInfo.classList.remove('battery-low');
  });
}
loadBattery();
setInterval(loadBattery,2000);

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
  // Kontrol paneli speed gondermez ve WEB_SPEED'i kullanmaya devam eder.
  // Teshis/calibration icin ise /set?motor=RL&dir=fwd&speed=76 ile tam PWM
  // degeri verilebilir; tek-teker komutu tank/gyro kontrolunden bagimsizdir.
  int speedMag = server.hasArg("speed")
      ? constrain(server.arg("speed").toInt(), 0, 255)
      : WEB_SPEED;
  int speed = (dir == "fwd") ? speedMag : (dir == "bwd") ? -speedMag : 0;
  disableTankDrive(); // tek-teker testini 50Hz tank kontrolu ezmesin
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
  char buf[900];
  snprintf(buf, sizeof(buf),
           "bootCount=%d lastResetReason=%d uptimeMs=%lu busV=%.3f shuntMv=%.3f powerAgeMs=%lu "
           "straightActive=%d encoderCorrection=%d encoderDeltaRL=%ld encoderDeltaRR=%ld "
           "filteredGyroZ=%.3f gyroBiasZ=%.3f imuAgeMs=%lu headingErrorDeg=%.3f "
           "gyroRateCorrection=%.3f headingCorrection=%.3f "
           "correctedOmega=%d appliedVx=%d pwmRL=%d pwmRR=%d "
           "rawGyroZ=%.3f correctedGyroZ=%.3f gyroBiasReady=%d "
           "gyroCalibration=%s gyroCalSamples=%u imuValid=%d "
           "yawActive=%d yawTargetDps=%.3f yawMeasuredDps=%.3f yawErrorDps=%.3f "
           "yawFeedforwardPwm=%.2f yawIntegralPwm=%.2f yawRequestedPwm=%.2f "
           "yawOutput=%.2f yawPwmRL=%d yawPwmRR=%d yawFault=%s\n",
           bootCount, lastResetReason, millis(), lastBusV, lastShuntMv,
           lastPowerReadMs == 0 ? 0 : millis() - lastPowerReadMs,
           straightAssistActive, straightEncoderCorrection,
           (long) lastStraightDeltaRL, (long) lastStraightDeltaRR,
           lastGyroZ, gyroBiasZ,
           lastImuReadMs == 0 ? 0 : millis() - lastImuReadMs,
           straightHeadingErrorDeg,
           lastStraightGyroRateCorrection, lastStraightHeadingCorrection,
           lastStraightCorrectedOmega, lastStraightAppliedVx,
           commandedPwmRL, commandedPwmRR,
           lastRawGyroZ, gyroBiasReady ? lastRawGyroZ - gyroBiasZ : NAN,
           gyroBiasReady, gyroCalibrationState, gyroCalSamples,
           mpuReady && lastGyroZValid && millis() - lastImuReadMs <= 100,
           yawRateActive, yawTargetDps, lastGyroZ - gyroBiasZ, yawErrorDps,
           yawFeedforwardPwm, yawIntegral, yawRequestedPwm, yawOutput,
           commandedPwmRL, commandedPwmRR, yawFault);
  server.send(200, "text/plain", buf);
}

// Pi'nin web arayuzundeki "Pil: X.XXV / Y.Y% / ZZZmA" gostergesiyle ayni
// degerleri, ayni formulle uretir (bkz. services/power.py _voltage_to_percent).
void handlePower() {
  unsigned long ageMs = lastPowerReadMs == 0 ? 0xFFFFFFFF : millis() - lastPowerReadMs;

  if (!inaReady || lastPowerReadMs == 0 || ageMs > POWER_MAX_AGE_MS) {
    server.send(200, "application/json", "{\"status\":\"ERROR\"}");
    return;
  }

  float ratio = (BATTERY_MAX_VOLTAGE <= BATTERY_MIN_VOLTAGE)
      ? 0.0f
      : (lastBusV - BATTERY_MIN_VOLTAGE) / (BATTERY_MAX_VOLTAGE - BATTERY_MIN_VOLTAGE);
  float percent = ratio * 100.0f;
  if (percent < 0.0f) percent = 0.0f;
  if (percent > 100.0f) percent = 100.0f;

  float currentMa = lastShuntMv / BATTERY_SHUNT_OHMS;
  bool lowVoltage = lastBusV <= BATTERY_LOW_VOLTAGE_WARNING;

  char buf[200];
  snprintf(buf, sizeof(buf),
           "{\"status\":\"OK\",\"bus_voltage\":%.3f,\"battery_percent\":%.1f,"
           "\"current_ma\":%.1f,\"low_voltage\":%s}",
           lastBusV, percent, currentMa, lowVoltage ? "true" : "false");
  server.send(200, "application/json", buf);
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
.difference{grid-column:1/-1}
.pin .num{font-size:13px;color:#999}
.pin .val{font-size:32px;font-weight:bold;margin-top:6px}
button{font-size:16px;padding:12px 24px;margin-top:10px;border:none;border-radius:6px;cursor:pointer;background:#b71c1c;color:#fff}
a{color:#1976d2}
</style></head><body>
<h1>Enkoder Pozisyon Testi</h1>
<div class="grid">
<div class="pin"><div class="num">Sol Teker (RL, GPIO 37/38)</div><div class="val" id="vRL">0</div></div>
<div class="pin"><div class="num">Sag Teker (RR, GPIO 39/40)</div><div class="val" id="vRR">0</div></div>
<div class="pin difference"><div class="num">Enkoder Yuzde Farki</div><div class="val" id="vDiff">0.0%</div></div>
</div>
<button onclick="fetch('/encreset')">SIFIRLA</button>
<p><a href="/">Kontrol paneline don</a></p>
<script>
async function poll(){
  try{
    const r=await fetch('/encvalues');
    const t=await r.text();
    const values={};
    t.trim().split(' ').forEach(pair=>{
      const [name,val]=pair.split('=');
      const el=document.getElementById('v'+name);
      if(el){
        el.textContent=val;
        values[name]=Number(val);
      }
    });
    if(Number.isFinite(values.RL) && Number.isFinite(values.RR)){
      const average=(Math.abs(values.RL)+Math.abs(values.RR))/2;
      const percent=average===0 ? 0 : Math.abs(values.RL-values.RR)/average*100;
      document.getElementById('vDiff').textContent=percent.toFixed(1)+'%';
    }
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
  bool applyStraightCorrection = !server.hasArg("assist") || server.arg("assist") != "0";
  driveTank(vx, omega, applyStraightCorrection);
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

// Non-blocking: the main loop continues serving commands and watchdogs.
bool calibrateGyroBias() {
  if (commandedPwmRL != 0 || commandedPwmRR != 0) return false;
  gyroBiasReady = false;
  gyroCalibrationPending = true;
  resetGyroCalibrationWindow();
  lastMotorMotionMs = millis();
  return true;
}

void updateGyroCalibration(float ax, float ay, float az,
                           float gx, float gy, float gz, unsigned long now) {
  if (!gyroCalibrationPending) return;
  int32_t rl, rr;
  noInterrupts();
  rl = encPosRL;
  rr = encPosRR;
  interrupts();
  float accelSquared = ax * ax + ay * ay + az * az;
  if (commandedPwmRL != 0 || commandedPwmRR != 0 ||
      now - lastMotorMotionMs < GYRO_CAL_SETTLE_MS ||
      !isfinite(accelSquared) || !isfinite(gx) || !isfinite(gy) || !isfinite(gz) ||
      accelSquared < 0.85f * 0.85f || accelSquared > 1.15f * 1.15f ||
      fabs(gx) > GYRO_CAL_MAX_RATE_DPS || fabs(gy) > GYRO_CAL_MAX_RATE_DPS ||
      fabs(gz) > GYRO_CAL_MAX_RATE_DPS) {
    resetGyroCalibrationWindow();
    return;
  }
  if (gyroCalSamples && (rl != gyroCalEncRL || rr != gyroCalEncRR ||
                         now - gyroCalLastSampleMs > 100)) {
    resetGyroCalibrationWindow();
    return;
  }
  float rates[3] = {gx, gy, gz};
  if (gyroCalSamples == 0) {
    gyroCalStartMs = now;
    gyroCalEncRL = rl;
    gyroCalEncRR = rr;
    gyroCalSumZ = 0;
    for (int i = 0; i < 3; ++i) gyroCalMin[i] = gyroCalMax[i] = rates[i];
  }
  for (int i = 0; i < 3; ++i) {
    gyroCalMin[i] = min(gyroCalMin[i], rates[i]);
    gyroCalMax[i] = max(gyroCalMax[i], rates[i]);
    if (gyroCalMax[i] - gyroCalMin[i] > GYRO_CAL_MAX_SPREAD_DPS) {
      resetGyroCalibrationWindow();
      return;
    }
  }
  gyroCalibrationState = "collecting";
  gyroCalLastSampleMs = now;
  gyroCalSumZ += gz;
  ++gyroCalSamples;
  if (now - gyroCalStartMs >= GYRO_CAL_WINDOW_MS && gyroCalSamples >= 80) {
    gyroBiasZ = gyroCalSumZ / gyroCalSamples;
    gyroBiasReady = true;
    gyroCalibrationPending = false;
    gyroCalibrationState = "ready";
    lastGyroZ = gz;
    straightHeadingErrorDeg = 0;
    Serial.printf("GYRO BIAS Z: %.3f dps (%u stationary samples)\n",
                  gyroBiasZ, gyroCalSamples);
  }
}

void handleGyroCalibrate() {
  if (!calibrateGyroBias()) {
    server.send(409, "text/plain", "ERR motors active");
    return;
  }
  server.send(202, "text/plain", "OK calibration pending; keep robot stationary");
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
      lastBusV = v;
      lastShuntMv = s;
      lastPowerReadMs = millis();
      Serial.println("INA219 HAZIR");
    } else {
      Serial.println("INA219 bulunamadi, tekrar denenecek");
    }
  }
}

void pollImu() {
  if (!ENABLE_TELEMETRY || !mpuReady) return;
  unsigned long now = millis();
  if (now - lastImuReadMs < IMU_READ_INTERVAL_MS) return;

  unsigned long previousReadMs = lastImuReadMs;
  float ax, ay, az, gx, gy, gz;
  if (!mpuReadMotion(ax, ay, az, gx, gy, gz)) {
    mpuReady = false;
    lastGyroZValid = false;
    gyroBiasReady = false;
    gyroCalibrationPending = true;
    resetGyroCalibrationWindow();
    return;
  }
  lastImuReadMs = now;
  lastAx = ax;
  lastAy = ay;
  lastAz = az;
  lastGx = gx;
  lastGy = gy;
  lastRawGyroZ = gz;
  if (!lastGyroZValid) lastGyroZ = gz;
  else lastGyroZ += STRAIGHT_GYRO_FILTER_ALPHA * (gz - lastGyroZ);
  lastGyroZValid = true;

  updateGyroCalibration(ax, ay, az, gx, gy, gz, now);
  if (tankDriveActive && straightAssistActive && gyroBiasReady && previousReadMs != 0) {
    float dtSec = (now - previousReadMs) / 1000.0f;
    straightHeadingErrorDeg += (lastGyroZ - gyroBiasZ) * dtSec;
    straightHeadingErrorDeg = constrain(straightHeadingErrorDeg,
                                        -STRAIGHT_HEADING_MAX_DEG,
                                        STRAIGHT_HEADING_MAX_DEG);
  }
}

void pollPower() {
  if (!ENABLE_TELEMETRY || !inaReady) return;
  unsigned long now = millis();
  if (lastPowerReadMs != 0 && now - lastPowerReadMs < POWER_READ_INTERVAL_MS) return;

  float busV, shuntMv;
  if (!inaReadPower(busV, shuntMv)) {
    inaReady = false;
    return;
  }
  lastBusV = busV;
  lastShuntMv = shuntMv;
  lastPowerReadMs = now;
}

// Onbellekteki son sensor degerlerini TELEM_INTERVAL_MS'de bir Pi'ye gonderir.
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
  if (!mpuReady || !inaReady || !lastGyroZValid || lastPowerReadMs == 0) return;

  // encPosRL/encPosRR: 32-bit hizalanmis okuma tek instruction'da atomik (ISR yari yolda
  // kesmez), pollEncoderDebug()/handleEncValues() de ayni sekilde kilitsiz okuyor.
  PiSerial.printf("TELEM %.4f %.4f %.4f %.3f %.3f %.3f %.4f %.3f %ld %ld\n",
                  lastAx, lastAy, lastAz, lastGx, lastGy, lastRawGyroZ,
                  lastBusV, lastShuntMv,
                  (long) encPosRL, (long) encPosRR);
}

// Pi'den gelen satir tabanli komutlari isle. Desteklenen komutlar:
//   TURNRATE <vx_pwm> <gyro_z_dps> - gyro feedback, +/-60 dps, vx +/-155
//   DRIVE <vx> <omega>  - genel karisik surus, ileri/geri + donus (-255..255)
//   FWD [hiz]  BWD [hiz]  LEFT [hiz]  RIGHT [hiz]  - temel yon komutlari (hiz verilmezse WEB_SPEED kullanilir)
//   SET <motor> <fwd|bwd|stop> [hiz]  - tek tekeri dogrudan kontrol et (motor: RL/RR, hiz: 0-255, verilmezse WEB_SPEED)
//   GYRO_CALIBRATE - motorlar duruyorsa hareketsizlik dogrulamali kalibrasyon
//   STOP  - tum motorlari durdur
//   PING  - baglanti testi, PONG doner
//   TESTMODE <timeout_ms> <sure_s>  - kontrol/donus testleri icin komut zaman asimini gecici uzatir
//                                     (timeout_ms en fazla 5000, sure_s en fazla 60s ile sinirli - sure dolunca
//                                     otomatik olarak normal 250ms'e doner)
//   TESTMODE_OFF  - test modunu hemen kapatip normal 250ms zaman asimina doner
// Her komuta "OK"/"ERR ..." veya ilgili yanit satiri ile cevap verilir.
// Pi hem UART (PiSerial) hem de USB (Serial) uzerinden baglanabilir; cevap komutun geldigi akisa yazilir.
// Ayrica: Pi'nin istegi disinda, S3 PiSerial'a 50Hz "TELEM ..." satiri gonderir
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
  } else if (cmd == "GYRO_CALIBRATE") {
    out.println(calibrateGyroBias() ? "OK calibration pending" : "ERR motors active");
  } else if (cmd == "TURNRATE") {
    int vx; float rate; char extra;
    if (sscanf(rest.c_str(), "%d %f %c", &vx, &rate, &extra) != 2) {
      stopAll(); out.println("ERR invalid target"); return;
    }
    out.println(driveYawRate(vx, rate) ? "OK" : "ERR yaw control");
  } else if (cmd == "DRIVE") {
    int sp2 = rest.indexOf(' ');
    if (sp2 == -1) { out.println("ERR eksik parametre"); return; }
    int vx = constrain(rest.substring(0, sp2).toInt(), -255, 255);
    int omega = constrain(rest.substring(sp2 + 1).toInt(), -255, 255);
    driveTank(vx, omega, omega == 0);
    out.println("OK");
  } else if (cmd == "FWD" || cmd == "BWD" || cmd == "LEFT" || cmd == "RIGHT") {
    int speed = rest.length() ? constrain(rest.toInt(), 0, 255) : WEB_SPEED;
    if (cmd == "FWD") driveTank(speed, 0, true);
    else if (cmd == "BWD") driveTank(-speed, 0, true);
    else if (cmd == "LEFT") driveTank(0, -speed, false);
    else driveTank(0, speed, false); // RIGHT
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
    disableTankDrive(); // tek-teker UART komutu tank kontrolunden bagimsizdir
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

  // Brake before sensor initialization/calibration; keep the driver disabled
  // until both motor outputs have been configured.
  pinMode(PIN_STBY, OUTPUT);
  digitalWrite(PIN_STBY, LOW);
  motorInit(motorRL);
  motorInit(motorRR);
  encoderInit();
  stopAll();
  digitalWrite(PIN_STBY, HIGH);

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setClock(100000);
  if (ENABLE_TELEMETRY) initSensors();
  calibrateGyroBias(); // samples collected later by pollImu(), without blocking
  neopixelWrite(RGB_BUILTIN, 0, 0, 0);

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
  server.on("/turnrate", handleYawRate);
  server.on("/status", handleStatus);
  server.on("/gyro/calibrate", HTTP_POST, handleGyroCalibrate);
  server.on("/power", handlePower);
  server.on("/encoders", handleEncoders);
  server.on("/encvalues", handleEncValues);
  server.on("/encreset", handleEncReset);
  server.begin();
}

void loop() {
  server.handleClient();
  ArduinoOTA.handle();
  pollPiSerial();
  pollImu();
  pollPower();
  pollStraightDriveControl();
  pollYawRateControl();
  pollTelemetry();
  pollEncoderDebug();
}
