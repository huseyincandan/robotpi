import time

from config import POWER_MONITOR
from services.i2c_bus import I2C_BUS_LOCK

try:
    from smbus2 import SMBus
except ImportError:
    from smbus import SMBus


CONFIG_REG = 0x00
SHUNT_VOLTAGE_REG = 0x01
BUS_VOLTAGE_REG = 0x02


class Ina219Service:

    def __init__(self):

        self.bus_number = POWER_MONITOR["BUS"]
        self.address = POWER_MONITOR["ADDRESS"]
        self.shunt_ohms = float(POWER_MONITOR["SHUNT_OHMS"])
        self.lock = I2C_BUS_LOCK
        self.bus = SMBus(self.bus_number)

        with self.lock:
            config = self._read_reg(CONFIG_REG)

        print(
            f"POWER MONITOR READY: bus={self.bus_number} address=0x{self.address:02x} "
            f"config=0x{config:04x}",
            flush=True
        )

    def _read_reg(self, reg):
        data = self.bus.read_i2c_block_data(self.address, reg, 2)
        return (data[0] << 8) | data[1]

    def read(self):

        with self.lock:
            bus_raw = self._read_reg(BUS_VOLTAGE_REG)
            shunt_raw = self._read_reg(SHUNT_VOLTAGE_REG)

        if shunt_raw > 32767:
            shunt_raw -= 65536

        bus_voltage = (bus_raw >> 3) * 0.004
        shunt_voltage = shunt_raw * 0.00001  # 10uV/LSB -> volt
        current_amps = (shunt_voltage / self.shunt_ohms) if self.shunt_ohms else 0.0
        power_watts = bus_voltage * current_amps

        return {
            "status": "OK",
            "bus_voltage": round(bus_voltage, 3),
            "shunt_voltage_mv": round(shunt_voltage * 1000.0, 2),
            "current_ma": round(current_amps * 1000.0, 1),
            "power_w": round(power_watts, 2),
            "battery_percent": self._voltage_to_percent(bus_voltage),
            "low_voltage": bus_voltage <= float(POWER_MONITOR["LOW_VOLTAGE_WARNING"]),
            "time": time.monotonic()
        }

    def _voltage_to_percent(self, voltage):

        # Li-ion bosalma egrisi dogrusal degil; bu sadece kaba bir dogrusal tahmin.
        min_v = float(POWER_MONITOR["MIN_VOLTAGE"])
        max_v = float(POWER_MONITOR["MAX_VOLTAGE"])

        if max_v <= min_v:
            return 0.0

        ratio = (voltage - min_v) / (max_v - min_v)
        return round(max(0.0, min(100.0, ratio * 100.0)), 1)
