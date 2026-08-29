import os
import subprocess
import time
import wave

from faster_whisper import WhisperModel
import numpy as np
from openai import OpenAI

from config import STT


class STTService:

	def __init__(self):

		self.model = None
		self.client = None
		self.last_audio_stats = {}
		self.last_had_audio = False

	def _get_client(self):

		if self.client is None:
			self.client = OpenAI()

		return self.client

	def _get_model(self):

		if self.model is None:
			self.model = WhisperModel(
				STT["MODEL"],
				device=STT["DEVICE"],
				compute_type=STT["COMPUTE_TYPE"]
			)

		return self.model

	def load(self):

		if STT["PROVIDER"] == "openai":
			return

		self._get_model()

	def record(self, cue=None, duration=None):

		try:
			os.remove(
				STT["RECORD_FILE"]
			)

		except FileNotFoundError:
			pass

		duration = duration or STT["RECORD_SECONDS"]

		if cue:
			cue()
			time.sleep(
				STT.get(
					"RECORD_AFTER_CUE_DELAY",
					0.15
				)
			)

		process = subprocess.Popen(
			[
				"arecord",
				"--quiet",
				"--device",
				STT["MICROPHONE_DEVICE"],
				"--format",
				"S16_LE",
				"--rate",
				str(STT["SAMPLE_RATE"]),
				"--channels",
				str(STT["CHANNELS"]),
				"--duration",
				str(duration),
				STT["RECORD_FILE"]
			]
		)

		return_code = process.wait()

		if return_code:
			raise subprocess.CalledProcessError(
				return_code,
				process.args
			)

		if STT["CHANNELS"] > 1:
			self.extract_channel(
				STT["RECORD_FILE"],
				STT.get(
					"MICROPHONE_SELECT_CHANNEL",
					0
				)
			)

		return STT["RECORD_FILE"]

	def extract_channel(self, audio_file, channel_index):

		with wave.open(audio_file, "rb") as audio:
			channels = audio.getnchannels()
			sample_width = audio.getsampwidth()
			frame_rate = audio.getframerate()
			frames = audio.readframes(audio.getnframes())

		samples = np.frombuffer(
			frames,
			dtype=np.int16
		).reshape(-1, channels)[:, channel_index].copy()

		with wave.open(audio_file, "wb") as audio:
			audio.setnchannels(1)
			audio.setsampwidth(sample_width)
			audio.setframerate(frame_rate)
			audio.writeframes(samples.tobytes())

	def transcribe(self, audio_file):

		if not self.has_speech(audio_file):
			return ""

		audio_file = self.trim_silence(audio_file)

		if STT["PROVIDER"] == "openai":
			with open(audio_file, "rb") as audio:
				transcription = self._get_client().audio.transcriptions.create(
					model=STT["OPENAI_MODEL"],
					file=audio,
					language=STT["LANGUAGE"],
					prompt=STT["OPENAI_PROMPT"]
				)

			return self.clean_text(
				transcription.text
			)

		segments, _ = self._get_model().transcribe(
			audio_file,
			language=STT["LANGUAGE"],
			vad_filter=STT["VAD_FILTER"]
		)

		return self.clean_text(
			" ".join(
			segment.text.strip()
			for segment in segments
			)
		)

	def clean_text(self, text):

		text = text.strip()

		if len(text) < STT["MIN_TEXT_LENGTH"]:
			return ""

		lower_text = text.lower().strip(" .,!?:;\"'")

		if lower_text in STT["IGNORE_TEXTS"]:
			return ""

		return text

	def has_speech(self, audio_file):

		with wave.open(audio_file, "rb") as audio:
			sample_rate = audio.getframerate()
			frames = audio.readframes(audio.getnframes())

		samples = np.frombuffer(
			frames,
			dtype=np.int16
		)

		skip_samples = int(
			sample_rate * STT["SILENCE_SKIP_SECONDS"]
		)
		samples = samples[skip_samples:]

		if not samples.size:
			return False

		absolute_samples = np.abs(
			samples.astype(np.int32)
		)

		rms = float(
			np.sqrt(
				np.mean(
					samples.astype(np.float32) ** 2
				)
			)
		)
		active_ratio = float(
			np.mean(
				absolute_samples >= STT["ACTIVE_SAMPLE_THRESHOLD"]
			)
		)

		print(
			"AUDIO LEVEL:",
			round(rms, 1),
			"active:",
			round(active_ratio, 3),
			flush=True
		)

		self.last_audio_stats = {
			"rms": rms,
			"active_ratio": active_ratio
		}
		self.last_had_audio = (
			rms >= STT.get("POSSIBLE_AUDIO_RMS", 400) or
			active_ratio >= STT.get("POSSIBLE_ACTIVE_RATIO", 0.015)
		)

		return (
			rms >= STT["MIN_AUDIO_RMS"] and
			active_ratio >= STT["MIN_ACTIVE_RATIO"]
		)

	def trim_silence(self, audio_file):

		if not STT.get("TRIM_SILENCE"):
			return audio_file

		with wave.open(audio_file, "rb") as audio:
			params = audio.getparams()
			sample_rate = audio.getframerate()
			frames = audio.readframes(audio.getnframes())

		samples = np.frombuffer(
			frames,
			dtype=np.int16
		)

		if not samples.size:
			return audio_file

		frame_samples = max(
			1,
			int(sample_rate * STT.get("TRIM_FRAME_MS", 30) / 1000)
		)
		frame_count = len(samples) // frame_samples

		if frame_count <= 0:
			return audio_file

		frames = samples[:frame_count * frame_samples].reshape(
			frame_count,
			frame_samples
		)
		frame_rms = np.sqrt(
			np.mean(
				frames.astype(np.float32) ** 2,
				axis=1
			)
		)
		active_frames = np.flatnonzero(
			frame_rms >= STT.get("TRIM_MIN_RMS", STT["MIN_AUDIO_RMS"])
		)

		if not active_frames.size:
			return audio_file

		padding_samples = int(
			sample_rate * STT.get("TRIM_PADDING_SECONDS", 0.2)
		)
		start = max(
			0,
			int(active_frames[0]) * frame_samples - padding_samples
		)
		end = min(
			len(samples),
			(int(active_frames[-1]) + 1) * frame_samples + padding_samples
		)

		trimmed_file = STT["TRIM_FILE"]

		with wave.open(trimmed_file, "wb") as audio:
			audio.setparams(params)
			audio.writeframes(
				samples[start:end].astype(np.int16).tobytes()
			)

		print(
			"TIMING: stt_trim",
			f"{len(samples) / sample_rate:.2f}s -> {(end - start) / sample_rate:.2f}s",
			flush=True
		)

		return trimmed_file

	def listen(self, cue=None, duration=None):

		start = time.monotonic()
		audio_file = self.record(
			cue=cue,
			duration=duration
		)
		print(
			f"TIMING: stt_record {time.monotonic() - start:.2f}s",
			flush=True
		)

		start = time.monotonic()
		text = self.transcribe(audio_file)
		print(
			f"TIMING: stt_transcribe {time.monotonic() - start:.2f}s",
			flush=True
		)

		return text