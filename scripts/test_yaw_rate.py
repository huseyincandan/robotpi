"""Host checks of S3 yaw controller transitions and fault stops; no hardware."""
from pathlib import Path
import subprocess
import tempfile
s=(Path(__file__).resolve().parents[1]/'MotorEspS3.ino').read_text()
state=s[s.index('bool yawRateActive'):s.index('void motorInit')]
logic=s[s.index('bool driveYawRate'):s.index('void handleYawRate')]
prefix=r'''
#include <cmath>
#include <algorithm>
#include <cassert>
#include <cstdio>
using std::isfinite;
template<class T> T constrain(T x,T a,T b){return std::max(a,std::min(b,x));}
unsigned long clockMs=1000,lastImuReadMs=1000;
unsigned long millis(){return clockMs;}
bool mpuReady=true,gyroBiasReady=true,lastGyroZValid=true;
float lastGyroZ=0,gyroBiasZ=0;
int motorRL=0,motorRR=1,output=0,stops=0;
void motorWrite(int,int){}
'''
mocks=r'''
void disableTankDrive(){yawRateActive=false;}
void driveTank(int,int,bool=true){yawRateActive=false;output=0;}
void stopAll(){yawRateActive=false;output=0;stops++;}
void applyTankDrive(int,int omega){output=omega;}
void step(float rate){clockMs+=20;lastImuReadMs=clockMs;lastGyroZ=rate;}
'''
tests=r'''
int main(){
 assert(driveYawRate(0,20));
 step(0);pollYawRateControl();assert(output>0&&output<=2.01f);
 for(int i=0;i<99;i++){step(0);pollYawRateControl();assert(output>=0&&output<=100);}
 assert(output>=80&&output<90);assert(fabs(yawIntegral)<=60);
 assert(yawErrorDps==20);assert(yawFeedforwardPwm==47.0f);
 assert(yawRequestedPwm>=0&&yawRequestedPwm<=YAW_MAX_PWM);
 float oldIntegral=yawIntegral;assert(driveYawRate(0,20));assert(yawIntegral==oldIntegral);
 assert(driveYawRate(0,-20));assert(yawIntegral==0&&yawOutput==0);
 step(0);pollYawRateControl();assert(output<0);
 clockMs+=120;pollYawRateControl();assert(!yawRateActive&&output==0);
 assert(!driveYawRate(0,20));
 lastImuReadMs=clockMs;assert(driveYawRate(0,20));
 assert(driveYawRate(0,0));assert(!yawRateActive&&output==0);
 assert(!driveYawRate(0,NAN));assert(!driveYawRate(0,61));assert(!driveYawRate(156,20));
 gyroBiasReady=false;assert(!driveYawRate(0,20));gyroBiasReady=true;
 assert(driveYawRate(0,20));clockMs+=160;lastImuReadMs=clockMs;pollYawRateControl();
 assert(!yawRateActive&&output==0);
 puts("PASS: limits, anti-windup, keepalive, reversal, stale IMU, stop, invalid targets, calibration and control gap");
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d)/'test.cpp';p.write_text(prefix+state+mocks+logic+tests)
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror',str(p),'-o',d+'/test'],check=True)
 subprocess.run([d+'/test'],check=True)
