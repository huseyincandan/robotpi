import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(
	0,
	str(Path(__file__).resolve().parents[1])
)

from services.wake import listen_for_seconds


async def main():

	parser = argparse.ArgumentParser()
	parser.add_argument(
		"--seconds",
		type=float,
		default=5
	)
	parser.add_argument(
		"--threshold",
		type=float,
		default=0.5
	)

	args = parser.parse_args()

	print(
		"OpenWakeWord listening locally...",
		flush=True
	)

	last_predictions = await listen_for_seconds(
		args.seconds,
		threshold=args.threshold
	)

	print(
		"Last scores:",
		{
			name: round(float(score), 4)
			for name, score in last_predictions.items()
		},
		flush=True
	)


if __name__ == "__main__":
	asyncio.run(
		main()
	)