"""Run the sketch's actual calibration logic with synthetic sensor samples.

Requires a host C++ compiler; does not access or move hardware.
"""
from pathlib import Path
import subprocess
import tempfile

sketch = (Path(__file__).resolve().parents[1] / 'MotorEspS3.ino').read_text()
state = sketch[sketch.index('const unsigned long GYRO_CAL_WINDOW_MS'):sketch.index('// /status uzerinden')]
# Only calibration globals and reset helper, excluding unrelated IMU globals.
state = state[:state.index('bool tankDriveActive')]
logic = sketch[sketch.index('bool calibrateGyroBias()'):sketch.index('void handleGyroCalibrate()')]
source = r'''
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cassert>
#include <cstdio>
using std::min; using std::max; using std::isfinite;
unsigned long clockMs = 0;
unsigned long millis() { return clockMs; }
void noInterrupts() {} void interrupts() {}
struct { template<class... A> void printf(const char*, A...) {} } Serial;
float gyroBiasZ=0, lastGyroZ=0, straightHeadingErrorDeg=0;
bool gyroBiasReady=false;
int32_t encPosRL=0, encPosRR=0;
''' + state + logic + r'''
void sample(float z=.275f, float x=0, float accel=1, unsigned long dt=20) {
  clockMs += dt;
  updateGyroCalibration(0,0,accel,x,0,z,clockMs);
}
void reset() {
  commandedPwmRL=commandedPwmRR=0;
  assert(calibrateGyroBias());
}
int main() {
  reset();
  for(int i=0;i<130;i++) sample();
  assert(gyroBiasReady && fabs(gyroBiasZ-.275f)<.001f);
  commandedPwmRR=64;
  assert(!calibrateGyroBias());
  reset();
  for(int i=0;i<200;i++) sample(43.66f);
  assert(!gyroBiasReady && gyroCalSamples==0);
  for(int i=0;i<130;i++) sample();
  assert(gyroBiasReady);
  reset();
  for(int i=0;i<200;i++) { encPosRL++; sample(); }
  assert(!gyroBiasReady);
  reset();
  for(int i=0;i<200;i++) sample(i%2 ? 1.0f : -1.0f);
  assert(!gyroBiasReady);
  reset();
  for(int i=0;i<200;i++) sample(.275f,6);
  assert(!gyroBiasReady);
  reset();
  for(int i=0;i<200;i++) sample(.275f,0,1.5f);
  assert(!gyroBiasReady);
  reset();
  for(int i=0;i<80;i++) sample();
  sample(.275f,0,1,200);
  assert(gyroCalSamples==0 && !gyroBiasReady);
  for(int i=0;i<130;i++) sample();
  assert(gyroBiasReady);
  reset();
  for(int i=0;i<200;i++) sample(NAN);
  assert(!gyroBiasReady);
  reset(); commandedPwmRL=64;
  for(int i=0;i<200;i++) sample();
  assert(!gyroBiasReady);
  puts("PASS: stationary bias, moving motor rejection, large offset, encoders, vibration, other-axis rotation, acceleration, sample gap, NaN, single-wheel motion");
}
'''
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / 'calibration.cpp'
    binary = Path(directory) / 'calibration'
    cpp.write_text(source)
    subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror', str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
