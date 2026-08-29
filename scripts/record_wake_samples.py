import argparse
import math
import subprocess
import time
from pathlib import Path


def record_sample(
	output_path,
	seconds,
	device
):

	subprocess.run(
		[
			"arecord",
			"--quiet",
			"--file-type",
			"wav",
			"--device",
			device,
			"--format",
			"S16_LE",
			"--rate",
			"48000",
			"--channels",
			"1",
			"--duration",
			str(math.ceil(seconds)),
			str(output_path)
		],
		check=True
	)


def main():

	parser = argparse.ArgumentParser()
	parser.add_argument(
		"--count",
		type=int,
		default=20
	)
	parser.add_argument(
		"--seconds",
		type=float,
		default=2
	)
	parser.add_argument(
		"--label",
		default="hamsibot"
	)
	parser.add_argument(
		"--device",
		default="dsnoop:CARD=U0x46d0x825,DEV=0"
	)

	args = parser.parse_args()

	output_dir = Path("data/wake") / args.label / "positive"
	output_dir.mkdir(
		parents=True,
		exist_ok=True
	)

	print(
		"Her kayitta 'Hey HamsiBot' de. Enter kaydi baslatir.",
		flush=True
	)

	for index in range(1, args.count + 1):
		input(
			f"{index}/{args.count} icin hazirsan Enter'a bas..."
		)

		output_path = output_dir / f"{args.label}_{index:03d}.wav"

		print(
			"Kayit basladi",
			flush=True
		)

		record_sample(
			output_path,
			args.seconds,
			args.device
		)

		print(
			f"Kaydedildi: {output_path}",
			flush=True
		)

		time.sleep(
			0.4
		)

	print(
		"Tamamlandi.",
		flush=True
	)


if __name__ == "__main__":
	main()