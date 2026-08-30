import re
import subprocess

from config import AUDIO


def _clamp_volume(
	volume
):

	return max(
		AUDIO.get("SPEAKER_MIN_VOLUME", 0),
		min(
			AUDIO.get("SPEAKER_MAX_VOLUME", 100),
			int(volume)
		)
	)


def _clamp_percent(
	percent
):

	return max(
		0,
		min(
			100,
			int(percent)
		)
	)


def set_microphone_capture_volume(
	volume
):

	volume = _clamp_percent(
		volume
	)

	subprocess.run(
		[
			"amixer",
			"-c",
			AUDIO["MICROPHONE_CARD"],
			"sset",
			"Mic",
			f"{volume}%",
			"cap"
		],
		check=True,
		capture_output=True,
		text=True
	)

	return volume


def get_speaker_volume():

	default_volume = _clamp_volume(
		AUDIO.get("SPEAKER_STARTUP_VOLUME", 70)
	)

	try:
		result = subprocess.run(
			[
				"amixer",
				"-c",
				AUDIO["SPEAKER_CARD"],
				"sget",
				"PCM"
			],
			check=True,
			capture_output=True,
			text=True
		)

	except subprocess.CalledProcessError:
		if AUDIO.get("SPEAKER_OPTIONAL", True):
			return default_volume

		raise

	match = re.search(
		r"\[(\d+)%\]",
		result.stdout
	)

	if not match:
		if AUDIO.get("SPEAKER_OPTIONAL", True):
			return default_volume

		raise RuntimeError(
			"Speaker volume not found"
		)

	return int(
		match.group(1)
	)


def set_speaker_volume(
	volume
):

	volume = _clamp_volume(
		volume
	)

	try:
		subprocess.run(
			[
				"amixer",
				"-c",
				AUDIO["SPEAKER_CARD"],
				"sset",
				"PCM",
				f"{volume}%",
				"unmute"
			],
			check=True,
			capture_output=True,
			text=True
		)

	except subprocess.CalledProcessError:
		if AUDIO.get("SPEAKER_OPTIONAL", True):
			return volume

		raise

	return get_speaker_volume()
