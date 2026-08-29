import subprocess
import hashlib
import math
import os
import re
import struct
import threading
import wave

from openai import OpenAI

from config import AUDIO
from config import SPEECH


class SpeechService:

	_audio_lock = threading.Lock()
	_state_lock = threading.Lock()
	_active_audio = 0

	@classmethod
	def is_speaking(cls):

		with cls._state_lock:
			return cls._active_audio > 0

	@classmethod
	def _begin_audio(cls):

		with cls._state_lock:
			cls._active_audio += 1

	@classmethod
	def _end_audio(cls):

		with cls._state_lock:
			cls._active_audio = max(
				0,
				cls._active_audio - 1
			)

	def __init__(self):

		self.piper_bin = SPEECH["PIPER_BIN"]
		self.model = SPEECH["PIPER_MODEL"]
		self.output_file = SPEECH["OUTPUT_FILE"]
		self.beep_file = SPEECH["BEEP_FILE"]
		self.end_beep_file = SPEECH["END_BEEP_FILE"]
		self.ready_beep_file = SPEECH["READY_BEEP_FILE"]
		self.client = None
		self._speaker_unavailable_logged = False

	def _get_client(self):

		if self.client is None:
			self.client = OpenAI()

		return self.client

	def _ensure_tone_file(self, tone_file, duration, frequency, volume):

		if os.path.exists(tone_file):
			return

		sample_rate = int(AUDIO["SAMPLE_RATE"])
		sample_count = int(sample_rate * duration)
		amplitude = int(32767 * volume)

		with wave.open(tone_file, "wb") as beep:
			beep.setnchannels(1)
			beep.setsampwidth(2)
			beep.setframerate(sample_rate)

			for index in range(sample_count):
				value = int(
					amplitude * math.sin(
						2 * math.pi * frequency * index / sample_rate
					)
				)
				beep.writeframesraw(
					struct.pack("<h", value)
				)

	def _ensure_beep_file(self):

		self._ensure_tone_file(
			self.beep_file,
			SPEECH["BEEP_DURATION"],
			SPEECH["BEEP_FREQUENCY"],
			SPEECH["BEEP_VOLUME"]
		)

	def _ensure_end_beep_file(self):

		self._ensure_tone_file(
			self.end_beep_file,
			SPEECH["END_BEEP_DURATION"],
			SPEECH["END_BEEP_FREQUENCY"],
			SPEECH["END_BEEP_VOLUME"]
		)

	def _ensure_ready_beep_file(self):

		self._ensure_tone_file(
			self.ready_beep_file,
			SPEECH["READY_BEEP_DURATION"],
			SPEECH["READY_BEEP_FREQUENCY"],
			SPEECH["READY_BEEP_VOLUME"]
		)

	def beep(self):

		self._ensure_beep_file()

		self._run_audio_command(
			[
				"aplay",
				"--quiet",
				"-D",
				AUDIO["SPEAKER_DEVICE"],
				self.beep_file
			],
		)

	def safe_beep(self):

		try:
			self.beep()

		except subprocess.CalledProcessError as exc:
			print(
				"BEEP ERROR:",
				repr(exc),
				flush=True
			)

	def end_beep(self):

		self._ensure_end_beep_file()

		self._run_audio_command(
			[
				"aplay",
				"--quiet",
				"-D",
				AUDIO["SPEAKER_DEVICE"],
				self.end_beep_file
			],
		)

	def ready_beep(self):

		self._ensure_ready_beep_file()

		self._run_audio_command(
			[
				"aplay",
				"--quiet",
				"-D",
				AUDIO["SPEAKER_DEVICE"],
				self.ready_beep_file
			],
		)

	def _run_audio_command(self, command, **kwargs):

		with self._audio_lock:
			self._begin_audio()

			try:
				subprocess.run(
					command,
					check=True,
					**kwargs
				)

			except subprocess.CalledProcessError:
				if AUDIO.get("SPEAKER_OPTIONAL", True):
					if not self._speaker_unavailable_logged:
						print(
							"SPEAKER OPTIONAL: playback unavailable, audio output skipped",
							flush=True
						)
						self._speaker_unavailable_logged = True
					return

				raise

			finally:
				self._end_audio()

	def _play(self, audio_file):

		self._run_audio_command(
			[
				"aplay",
				"-D",
				AUDIO["SPEAKER_DEVICE"],
				audio_file
			],
		)

	def _text_chunks(self, text):

		text = self._spoken_text(text)

		if not SPEECH.get("CHUNK_LONG_TEXT") or len(text) < SPEECH.get("CHUNK_MIN_CHARS", 140):
			return [text]

		parts = re.split(
			r"(?<=[.!?])\s+",
			text
		)
		chunks = []
		current = ""

		for part in parts:
			part = part.strip()

			if not part:
				continue

			candidate = f"{current} {part}".strip()

			if current and len(candidate) > SPEECH.get("CHUNK_MIN_CHARS", 140):
				chunks.append(current)
				current = part
			else:
				current = candidate

		if current:
			chunks.append(current)

		return chunks or [text]

	def _spoken_text(self, text):

		text = text.strip()
		text = re.sub(
			r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF]",
			"",
			text
		)
		text = re.sub(
			r"^[\s>*#\-•]+",
			"",
			text,
			flags=re.MULTILINE
		)
		text = re.sub(
			r"[*_`~]+",
			"",
			text
		)
		text = re.sub(
			r"\s+",
			" ",
			text
		)

		return text.strip()

	def _say_local_once(self, text):

		audio_file = self._local_cache_file(text)

		if audio_file and os.path.exists(audio_file):
			self._play_file(audio_file)
			return

		output_file = audio_file or self.output_file

		subprocess.run(
			[
				self.piper_bin,
				"--model",
				self.model,
				"--output_file",
				output_file
			],
			input=text,
			check=True,
			text=True
		)

		self._play_file(output_file)

	def _local_cache_file(self, text):

		cache_dir = SPEECH.get("LOCAL_CACHE_DIR")
		max_chars = SPEECH.get("LOCAL_CACHE_MAX_CHARS", 0)

		if not cache_dir or not max_chars or len(text) > max_chars:
			return None

		os.makedirs(
			cache_dir,
			exist_ok=True
		)
		digest = hashlib.sha1(
			text.encode("utf-8")
		).hexdigest()

		return os.path.join(
			cache_dir,
			f"{digest}.wav"
		)

	def _play_file(self, audio_file):

		devices = [AUDIO["SPEAKER_DEVICE"]] + AUDIO.get("SPEAKER_FALLBACK_DEVICES", [])
		last_error = None

		for device in devices:
			try:
				subprocess.run(
					[
						"aplay",
						"-D",
						device,
						audio_file
					],
					check=True
				)
				return

			except subprocess.CalledProcessError as exc:
				last_error = exc

				if not AUDIO.get("SPEAKER_OPTIONAL", True):
					print(
						"PLAYBACK DEVICE ERROR:",
						device,
						repr(exc),
						flush=True
					)

		if last_error:
			if AUDIO.get("SPEAKER_OPTIONAL", True):
				if not self._speaker_unavailable_logged:
					print(
						"SPEAKER OPTIONAL: playback unavailable on all devices, speech output skipped",
						flush=True
					)
					self._speaker_unavailable_logged = True
				return

			raise last_error

	def say_local(self, text):

		with self._audio_lock:
			self._begin_audio()

			try:
				for chunk in self._text_chunks(text):
					self._say_local_once(chunk)

			finally:
				self._end_audio()

	def _say_openai_once(self, text):

		with self._get_client().audio.speech.with_streaming_response.create(
			model=SPEECH["OPENAI_MODEL"],
			voice=SPEECH["OPENAI_VOICE"],
			input=text,
			response_format="wav"
		) as response:
			response.stream_to_file(
				SPEECH["OPENAI_OUTPUT_FILE"]
			)

		self._play_file(
			SPEECH["OPENAI_OUTPUT_FILE"]
		)

	def say_openai(self, text):

		with self._audio_lock:
			self._begin_audio()

			try:
				for chunk in self._text_chunks(text):
					self._say_openai_once(chunk)

			finally:
				self._end_audio()

	def say(self, text):

		if SPEECH["PROVIDER"] == "openai":
			self.say_openai(
				text
			)
			return

		self.say_local(
			text
		)
