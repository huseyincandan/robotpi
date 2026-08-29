from aiortc.contrib.media import (
	MediaPlayer,
	MediaRecorder
)
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


def _audio_options():

	return {
		"sample_rate": AUDIO["SAMPLE_RATE"],
		"channels": AUDIO["CHANNELS"]
	}


def _speaker_options():

	options = _audio_options()

	options.update({
		"buffer_size": AUDIO["SPEAKER_BUFFER_SIZE"]
	})

	return options


def create_microphone_player():

	return MediaPlayer(
		AUDIO["MICROPHONE_DEVICE"],
		format=AUDIO["MICROPHONE_FORMAT"],
		options=_audio_options()
	)


def create_speaker_recorder():

	return MediaRecorder(
		AUDIO["SPEAKER_DEVICE"],
		format=AUDIO["SPEAKER_FORMAT"],
		options=_speaker_options()
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
