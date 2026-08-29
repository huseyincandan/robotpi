import argparse
import time

try:
    from smbus2 import SMBus
except ImportError:
    from smbus import SMBus


PWR_MGMT_1 = 0x6B
WHO_AM_I = 0x75
ACCEL_XOUT_H = 0x3B

ACCEL_SCALE = 16384.0
GYRO_SCALE = 131.0


def read_word(bus, address, register):
    high = bus.read_byte_data(address, register)
    low = bus.read_byte_data(address, register + 1)
    value = (high << 8) | low

    if value >= 0x8000:
        value -= 0x10000

    return value


def read_values(bus, address):
    accel_x = read_word(bus, address, ACCEL_XOUT_H) / ACCEL_SCALE
    accel_y = read_word(bus, address, ACCEL_XOUT_H + 2) / ACCEL_SCALE
    accel_z = read_word(bus, address, ACCEL_XOUT_H + 4) / ACCEL_SCALE

    temp_raw = read_word(bus, address, ACCEL_XOUT_H + 6)
    temp_c = (temp_raw / 340.0) + 36.53

    gyro_x = read_word(bus, address, ACCEL_XOUT_H + 8) / GYRO_SCALE
    gyro_y = read_word(bus, address, ACCEL_XOUT_H + 10) / GYRO_SCALE
    gyro_z = read_word(bus, address, ACCEL_XOUT_H + 12) / GYRO_SCALE

    return accel_x, accel_y, accel_z, temp_c, gyro_x, gyro_y, gyro_z


def main():
    parser = argparse.ArgumentParser(
        description="Print MPU6050 accelerometer and gyroscope values."
    )
    parser.add_argument("--bus", type=int, default=1)
    parser.add_argument("--address", type=lambda value: int(value, 0), default=0x68)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--samples", type=int, default=0)
    args = parser.parse_args()

    with SMBus(args.bus) as bus:
        bus.write_byte_data(args.address, PWR_MGMT_1, 0)
        who_am_i = bus.read_byte_data(args.address, WHO_AM_I)

        print(
            f"MPU6050 bus={args.bus} address=0x{args.address:02x} "
            f"who_am_i=0x{who_am_i:02x}",
            flush=True,
        )

        sample_count = 0

        while args.samples <= 0 or sample_count < args.samples:
            values = read_values(bus, args.address)
            accel_x, accel_y, accel_z, temp_c, gyro_x, gyro_y, gyro_z = values

            print(
                f"{time.strftime('%H:%M:%S')} "
                f"accel(g) x={accel_x: .3f} y={accel_y: .3f} z={accel_z: .3f} "
                f"gyro(deg/s) x={gyro_x: .2f} y={gyro_y: .2f} z={gyro_z: .2f} "
                f"temp={temp_c: .1f}C",
                flush=True,
            )

            sample_count += 1

            if args.samples <= 0 or sample_count < args.samples:
                time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped.", flush=True)