#include <WiFi.h>
#include <WebServer.h>
#include <ESPmDNS.h>
#include <ArduinoOTA.h>

// Onboard addressable RGB LED (WS2812) for ESP32-S3
#ifndef RGB_BUILTIN
#define RGB_BUILTIN 48
#endif

// TODO: kendi ev Wi-Fi bilgilerinizi girin
const char *WIFI_SSID = "Deco AP";
const char *WIFI_PASSWORD = "Candan.2162";
const char *HOSTNAME = "robomotor"; // http://robomotor.local
const char *OTA_PASSWORD = "robomotor123"; // kablosuz yukleme sifresi

WebServer server(80);
const int WEB_SPEED = 150; // web arayuzundeki ileri/geri butonlarinin sabit hizi (-255..255)

// 4WD skid-steer drive (regular wheels) via 2x TB6612FNG (STBY shared)
#define PIN_STBY 2

// TB6612 #1 (front): PWMA=4 AIN2=5 AIN1=6 BIN1=7 BIN2=15 PWMB=16
#define PIN_FL_IN1 6
#define PIN_FL_IN2 5
#define PIN_FL_PWM 4

#define PIN_FR_IN1 7
#define PIN_FR_IN2 15
#define PIN_FR_PWM 16

// TB6612 #2 (rear): PWMA=9 AIN2=10 AIN1=11 BIN1=12 BIN2=13 PWMB=14
#define PIN_RL_IN1 11
#define PIN_RL_IN2 10
#define PIN_RL_PWM 9

#define PIN_RR_IN1 12
#define PIN_RR_IN2 13
#define PIN_RR_PWM 14

const int PWM_FREQ = 20000; // above audible range
const int PWM_RES = 8;      // 0-255 duty

// Raspberry Pi 5 baglantisi: ayri bir donanim UART (USB uzerindeki debug Serial'dan bagimsiz)
// Kablolama: S3 GPIO17(TX) -> Pi RXD, S3 GPIO18(RX) -> Pi TXD, ortak GND
#define PIN_PI_UART_TX 17
#define PIN_PI_UART_RX 18
const unsigned long PI_UART_BAUD = 115200;
HardwareSerial PiSerial(1);

const unsigned long PI_CMD_TIMEOUT_MS = 250; // Pi guc/baglanti kaybinda motorlari daha hizli durdur
unsigned long lastPiCmdMs = 0;

struct Motor {
  uint8_t in1, in2, pwm;
  bool reversed; // motor karsi yonde monte edildiyse yon tersine cevrilir
};

// sol taraftaki motorlar fiziksel olarak ters monte edildigi icin reversed=true
Motor motorFL = {PIN_FL_IN1, PIN_FL_IN2, PIN_FL_PWM, true};
Motor motorFR = {PIN_FR_IN1, PIN_FR_IN2, PIN_FR_PWM, false};
Motor motorRL = {PIN_RL_IN1, PIN_RL_IN2, PIN_RL_PWM, true};
Motor motorRR = {PIN_RR_IN1, PIN_RR_IN2, PIN_RR_PWM, false};

void motorInit(const Motor &m) {
  pinMode(m.in1, OUTPUT);
  pinMode(m.in2, OUTPUT);
  ledcAttach(m.pwm, PWM_FREQ, PWM_RES);
}

// speed: -255 (full reverse) .. 255 (full forward)
const int MIN_EFFECTIVE_SPEED = 60; // bu esigin altindaki komutlar surtunmeyi yenip motoru fiilen cevirmeyebilir
// Yerinde donuste (vx=0) 4 tekerlek de birden yanal kaymali surtunmeyi yenmek
// zorunda - bu, duz gitmekten cok daha fazla tork ister. MIN_EFFECTIVE_SPEED
// bunun icin yetersiz kaliyordu: nav2 dis=0 omega!=0 komutu gonderiyor, gyro
// donusun gerceklesmedigini gosteriyor, robot hicbir yere hareket etmiyordu.
const int MIN_EFFECTIVE_PIVOT_SPEED = 130;

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

// vx: forward(+)/back(-), omega: rotate cw(+)/ccw(-); each -255..255 (no strafe, regular wheels)
void skidSteerDrive(int vx, int omega) {
  // vx buyudukce donus payini azalt: bir tarafin tamamen bosta kalip patinaj yapmasini engeller
  int scaledOmega = (omega * (255 - abs(vx))) / 255;
  int left = vx - scaledOmega;
  int right = vx + scaledOmega;
  int minEffective = (vx == 0 && omega != 0) ? MIN_EFFECTIVE_PIVOT_SPEED : MIN_EFFECTIVE_SPEED;
  motorWrite(motorFL, left, minEffective);
  motorWrite(motorRL, left, minEffective);
  motorWrite(motorFR, right, minEffective);
  motorWrite(motorRR, right, minEffective);
}

void stopAll() {
  skidSteerDrive(0, 0);
}

// dir: "fwd" ileri, "bwd" geri, herhangi baska deger dur
Motor *motorByName(const String &name) {
  if (name == "FL") return &motorFL;
  if (name == "FR") return &motorFR;
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
button{font-size:15px;padding:10px 12px;margin:3px;border:none;border-radius:6px;cursor:pointer}
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
<div class="panel"><h2>On Sol</h2>
<button class="fwd" id="FL_fwd">Ileri</button>
<button class="bwd" id="FL_bwd">Geri</button></div>
<div class="panel"><h2>On Sag</h2>
<button class="fwd" id="FR_fwd">Ileri</button>
<button class="bwd" id="FR_bwd">Geri</button></div>
<div class="panel"><h2>Arka Sol</h2>
<button class="fwd" id="RL_fwd">Ileri</button>
<button class="bwd" id="RL_bwd">Geri</button></div>
<div class="panel"><h2>Arka Sag</h2>
<button class="fwd" id="RR_fwd">Ileri</button>
<button class="bwd" id="RR_bwd">Geri</button></div>
</div>
<button class="stopall" onclick="fetch('/stopall')">TUMUNU DURDUR</button>
<script>
function send(motor,dir){fetch(`/set?motor=${motor}&dir=${dir}`);}
function bindHold(id,motor,dir){
  const el=document.getElementById(id);
  const start=(e)=>{e.preventDefault();send(motor,dir);};
  const stop=(e)=>{e.preventDefault();send(motor,'stop');};
  el.addEventListener('pointerdown',start);
  el.addEventListener('pointerup',stop);
  el.addEventListener('pointerleave',stop);
  el.addEventListener('pointercancel',stop);
}
['FL','FR','RL','RR'].forEach(m=>{
  bindHold(m+'_fwd',m,'fwd');
  bindHold(m+'_bwd',m,'bwd');
});

(function(){
  const base=document.getElementById('joyBase');
  const stick=document.getElementById('joyStick');
  const radius=55; // merkezden izin verilen maksimum surukleme mesafesi (px)
  let dragging=false, lastSend=0, inFlight=null;

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
    const vx=Math.round((-dy/radius)*255);
    const omega=Math.round((-dx/radius)*255); // saga cekince saga, sola cekince sola donsun
    document.getElementById('joyDbg').textContent=`vx:${vx} omega:${omega}`;
    sendDrive(vx,omega);
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
    setStick(0,0);
    sendDrive(0,0); // birakinca hemen dur, kuyrukta bekleyen eski komutlari iptal ederek
  }

  base.addEventListener('pointerdown',(e)=>{dragging=true;base.setPointerCapture(e.pointerId);handleMove(e);});
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
  server.send(200, "text/plain", "OK");
}

void handleStopAll() {
  stopAll();
  server.send(200, "text/plain", "OK");
}

void handleDrive() {
  if (!server.hasArg("vx") || !server.hasArg("omega")) {
    server.send(400, "text/plain", "eksik parametre");
    return;
  }
  int vx = constrain(server.arg("vx").toInt(), -255, 255);
  int omega = constrain(server.arg("omega").toInt(), -255, 255);
  skidSteerDrive(vx, omega);
  server.send(200, "text/plain", "OK");
}

// Pi'den gelen satir tabanli komutlari isle. Desteklenen komutlar:
//   DRIVE <vx> <omega>  - genel karisik surus (-255..255), joystick ile ayni mantik
//   FWD [hiz]  BWD [hiz]  LEFT [hiz]  RIGHT [hiz]  - temel yon komutlari (hiz verilmezse WEB_SPEED kullanilir)
//   SET <motor> <fwd|bwd|stop> [hiz]  - tek tekeri dogrudan kontrol et (motor: FL/FR/RL/RR, hiz: 0-255, verilmezse WEB_SPEED)
//   STOP  - tum motorlari durdur
//   PING  - baglanti testi, PONG doner
// Her komuta "OK"/"ERR ..." veya ilgili yanit satiri ile cevap verilir.
// Pi hem UART (PiSerial) hem de USB (Serial) uzerinden baglanabilir; cevap komutun geldigi akisa yazilir.
void handlePiCommand(String line, Stream &out) {
  line.trim();
  if (line.length() == 0) return;
  int sp = line.indexOf(' ');
  String cmd = (sp == -1) ? line : line.substring(0, sp);
  String rest = (sp == -1) ? "" : line.substring(sp + 1);
  cmd.toUpperCase();
  lastPiCmdMs = millis(); // herhangi bir komut baglantinin canli oldugunu gosterir

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
    skidSteerDrive(vx, omega);
    out.println("OK");
  } else if (cmd == "FWD" || cmd == "BWD" || cmd == "LEFT" || cmd == "RIGHT") {
    int speed = rest.length() ? constrain(rest.toInt(), 0, 255) : WEB_SPEED;
    if (cmd == "FWD") skidSteerDrive(speed, 0);
    else if (cmd == "BWD") skidSteerDrive(-speed, 0);
    else if (cmd == "LEFT") skidSteerDrive(0, -speed);
    else skidSteerDrive(0, speed); // RIGHT
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
  if (lastPiCmdMs != 0 && millis() - lastPiCmdMs > PI_CMD_TIMEOUT_MS) {
    stopAll();
    lastPiCmdMs = 0;
  }
}

void setup() {
  Serial.begin(115200);
  PiSerial.begin(PI_UART_BAUD, SERIAL_8N1, PIN_PI_UART_RX, PIN_PI_UART_TX); // Pi 5 UART hatti

  neopixelWrite(RGB_BUILTIN, 0, 0, 0); // LED kapali kalsin

  pinMode(PIN_STBY, OUTPUT);
  digitalWrite(PIN_STBY, HIGH); // enable both TB6612 drivers

  motorInit(motorFL);
  motorInit(motorFR);
  motorInit(motorRL);
  motorInit(motorRR);
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
  server.begin();
}

void loop() {
  server.handleClient();
  ArduinoOTA.handle();
  pollPiSerial();
}
