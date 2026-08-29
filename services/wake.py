import asyncio
import json
import re
import time

import numpy as np
from openwakeword.model import Model

from config import MUSIC
from config import RADIO
from config import SPEECH
from config import STT
from config import SYSTEM
from config import WAKE
from services.assistant import AssistantService
from services.audio import get_speaker_volume
from services.audio import set_speaker_volume
from services.intent import IntentService
from services.local_info import LocalInfoService
from services.movement import MovementService
from services.music import MusicService
from services.speech import SpeechService
from services.stt import STTService
from services.system import SystemService


def is_end_session_command(text):

	normalized = re.sub(
		r"[^\wçğıöşüÇĞİÖŞÜ]+",
		" ",
		text.lower()
	).strip()

	return any(
		command in normalized
		for command in STT["END_SESSION_COMMANDS"]
	)


def weather_followup_query(text):

	normalized = re.sub(
		r"[^\wçğıöşüÇĞİÖŞÜ]+",
		" ",
		text.lower()
	).strip()

	if not any(
		word in normalized
		for word in [
			"yarın",
			"yarin",
			"öbür gün",
			"obur gun",
			"bugün",
			"bugun"
		]
	):
		return ""

	if not any(
		word in normalized
		for word in [
			"nasıl",
			"nasil",
			"olacak",
			"durum"
		]
	):
		return ""

	return f"{text} hava durumu"


def volume_command_value(text):

	normalized = re.sub(
		r"\s+",
		" ",
		text.lower()
	).strip()
	normalized = normalized.replace(
		"%",
		" yüzde "
	)

	match = re.search(
		r"(?:yüzde|yuzde)\s*(\d+)",
		normalized
	)

	if match:
		return max(
			0,
			min(
				100,
				int(match.group(1))
			)
		)

	match = re.search(
		r"(?:yüzde|yuzde)\s*([a-zçğıöşü ]+)",
		normalized
	)

	if match:
		word_value = volume_word_value(
			match.group(1).strip()
		)

		if word_value is not None:
			return max(
				0,
				min(
					100,
					word_value
				)
			)

	match = re.search(
		r"\b(\d{1,3})\b",
		normalized
	)

	if match and any(word in normalized for word in ["yap", "ayarla", "olsun"]):
		return max(
			0,
			min(
				100,
				int(match.group(1))
			)
		)

	current = get_speaker_volume()

	if any(word in normalized for word in ["artır", "artir", "arttır", "arttir", "yükselt", "yukselt", "aç", "ac"]):
		return min(
			100,
			current + 10
		)

	if any(word in normalized for word in ["azalt", "kıs", "kis", "düşür", "dusur"]):
		return max(
			0,
			current - 10
		)

	return current


def volume_word_value(text):

	words = text.split()
	units = {
		"sifir": 0,
		"bir": 1,
		"iki": 2,
		"uc": 3,
		"üç": 3,
		"dort": 4,
		"dört": 4,
		"bes": 5,
		"beş": 5,
		"alti": 6,
		"altı": 6,
		"yedi": 7,
		"sekiz": 8,
		"dokuz": 9
	}
	tens = {
		"on": 10,
		"yirmi": 20,
		"otuz": 30,
		"kirk": 40,
		"kırk": 40,
		"elli": 50,
		"altmis": 60,
		"altmış": 60,
		"yetmis": 70,
		"yetmiş": 70,
		"seksen": 80,
		"doksan": 90,
		"yuz": 100,
		"yüz": 100
	}
	value = 0

	for word in words:
		if word in tens:
			value += tens[word]
			continue

		if word in units:
			value += units[word]
			continue

		break

	return value if value > 0 or words[:1] in [["sifir"]] else None


def apply_volume_command(text, music=None):

	volume = set_speaker_volume(
		volume_command_value(text)
	)

	if music:
		music.set_volume(
			volume
		)

	return volume


def log_timing(name, start):

	elapsed = time.monotonic() - start
	print(
		f"TIMING: {name} {elapsed:.2f}s",
		flush=True
	)
	return time.monotonic()


class WakeWordListener:

	def __init__(
		self,
		model_paths=None,
		device=None,
		threshold=0.5
	):

		self.model_paths = model_paths or []
		self.device = device or WAKE["MICROPHONE_DEVICE"]
		self.threshold = threshold
		self.model_sample_rate = 16000
		self.capture_sample_rate = WAKE.get(
			"CAPTURE_SAMPLE_RATE",
			48000
		)
		self.capture_channels = WAKE.get(
			"MICROPHONE_CHANNELS",
			1
		)
		self.select_channel = WAKE.get(
			"MICROPHONE_SELECT_CHANNEL",
			0
		)
		self.downsample_ratio = max(
			1,
			self.capture_sample_rate // self.model_sample_rate
		)
		self.chunk_samples = 1280
		self.capture_chunk_samples = int(
			self.chunk_samples *
			self.capture_sample_rate /
			self.model_sample_rate
		)
		self.process = None
		self.model = Model(
			wakeword_model_paths=self.model_paths
		)

	async def start(self):

		if self.process:
			return False

		self.process = await asyncio.create_subprocess_exec(
			"arecord",
			"--quiet",
			"--file-type",
			"raw",
			"--device",
			self.device,
			"--format",
			"S16_LE",
			"--rate",
			str(self.capture_sample_rate),
			"--channels",
			str(self.capture_channels),
			stdout=asyncio.subprocess.PIPE,
			stderr=asyncio.subprocess.DEVNULL
		)
		self.model.reset()
		return True

	async def stop(self):

		if not self.process:
			return

		if self.process.returncode is None:
			self.process.terminate()

		try:
			await asyncio.wait_for(
				self.process.wait(),
				timeout=1
			)

		except asyncio.TimeoutError:
			self.process.kill()
			await self.process.wait()

		self.process = None

	async def listen_once(self):

		started = await self.start()

		bytes_per_chunk = (
			self.capture_chunk_samples *
			self.capture_channels *
			2
		)

		if started:
			for _ in range(WAKE["STARTUP_DISCARD_CHUNKS"]):
				await self.process.stdout.readexactly(
					bytes_per_chunk
				)

		data = await self.process.stdout.readexactly(
			bytes_per_chunk
		)

		capture_audio = np.frombuffer(
			data,
			dtype=np.int16
		)

		if self.capture_channels > 1:
			capture_audio = capture_audio.reshape(
				-1,
				self.capture_channels
			)[:, self.select_channel]

		audio = capture_audio[::self.downsample_ratio].copy()

		predictions = self.model.predict(
			audio
		)

		detected = {
			name: float(score)
			for name, score in predictions.items()
			if score >= self.threshold
		}

		return predictions, detected


async def listen_for_seconds(
	seconds,
	threshold=0.5
):

	listener = WakeWordListener(
		threshold=threshold
	)

	end_time = asyncio.get_running_loop().time() + seconds

	try:
		while asyncio.get_running_loop().time() < end_time:
			predictions, detected = await listener.listen_once()

			if detected:
				print(
					json.dumps(
						detected,
						ensure_ascii=False
					),
					flush=True
				)

		return predictions

	finally:
		await listener.stop()


async def run_wake_loop(
	motor=None,
	music=None,
	movement=None,
	speech=None
):

	listener = WakeWordListener(
		threshold=WAKE["THRESHOLD"]
	)

	speech = speech or SpeechService()
	stt = STTService()
	assistant = AssistantService()
	intent_service = IntentService()
	local_info = LocalInfoService()
	movement = movement or (MovementService(motor) if motor else None)
	system = SystemService()
	music = music or MusicService()
	last_wake = 0
	wake_hits = 0
	stt_task = asyncio.create_task(
		asyncio.to_thread(
			stt.load
		)
	)

	print(
		"READY: say hey jarvis",
		flush=True
	)
	await asyncio.to_thread(
		speech.ready_beep
	)

	try:
		while True:
			if SpeechService.is_speaking():
				await listener.stop()
				await asyncio.sleep(0.1)
				continue

			if music.is_playing() and not WAKE["LISTEN_DURING_MUSIC"]:
				await listener.stop()
				await asyncio.sleep(1)
				continue

			try:
				predictions, _ = await listener.listen_once()

				if SpeechService.is_speaking():
					wake_hits = 0
					continue

			except Exception as exc:
				print(
					"WAKE ERROR:",
					repr(exc),
					flush=True
				)
				await listener.stop()
				await asyncio.sleep(1)
				continue

			score = float(
				predictions.get(
					WAKE["MODEL_NAME"],
					0
				)
			)
			threshold = WAKE["THRESHOLD"]
			consecutive_detections = WAKE["CONSECUTIVE_DETECTIONS"]

			if music.is_playing():
				threshold = WAKE["MUSIC_THRESHOLD"]
				consecutive_detections = WAKE["MUSIC_CONSECUTIVE_DETECTIONS"]

			if score < threshold:
				wake_hits = 0
				continue

			wake_hits += 1

			if wake_hits < consecutive_detections:
				continue

			wake_hits = 0

			now = time.monotonic()

			if now - last_wake < WAKE["COOLDOWN_SECONDS"]:
				continue

			last_wake = now

			print(
				"WAKE WORD:",
				WAKE["MODEL_NAME"],
				score,
				flush=True
			)

			try:
				wake_start = time.monotonic()
				music_paused_for_wake = False

				if music.is_playing():
					print(
						"MUSIC PAUSED FOR WAKE WORD",
						flush=True
					)
					music_paused_for_wake = await asyncio.to_thread(
						music.pause
					)
					await asyncio.sleep(
						WAKE["MUSIC_COMMAND_PAUSE_SECONDS"]
					)

				assistant.reset()

				if not music_paused_for_wake:
					step_start = time.monotonic()
					await asyncio.to_thread(
						speech.say_local,
						SPEECH["WAKE_RESPONSE"]
					)
					log_timing(
						"wake_response_tts",
						step_start
					)

					await asyncio.sleep(
						SPEECH["WAKE_RESPONSE_PAUSE"]
					)

				await listener.stop()
				await stt_task

				print(
					"LISTENING FOR COMMAND",
					flush=True
				)

				empty_turns = 0
				music_started = False
				session_ended = False
				last_weather_turn = False

				while True:
					while SpeechService.is_speaking():
						await asyncio.sleep(0.1)

					step_start = time.monotonic()
					text = await asyncio.to_thread(
						stt.listen,
						speech.safe_beep if music_paused_for_wake else speech.beep,
						WAKE["MUSIC_COMMAND_RECORD_SECONDS"] if music_paused_for_wake else None
					)
					log_timing(
						"stt_listen_record_and_transcribe",
						step_start
					)

					if SpeechService.is_speaking():
						print(
							"STT IGNORED DURING SPEECH",
							flush=True
						)
						continue

					print(
						"STT:",
						text or "<empty>",
						flush=True
					)

					if text:
						step_start = time.monotonic()
						intent = await asyncio.to_thread(
							intent_service.classify,
							text
						)
						log_timing(
							"intent_classify",
							step_start
						)

						print(
							"INTENT:",
							intent,
							flush=True
						)

						if intent["type"] == "chat" and last_weather_turn:
							weather_query = weather_followup_query(
								text
							)

							if weather_query:
								intent = {
									"type": "web.search",
									"query": weather_query
								}
								print(
									"INTENT OVERRIDE:",
									intent,
									flush=True
								)

						if is_end_session_command(text) and intent["type"] != "system.shutdown" and not music_paused_for_wake:
							print(
								"SESSION ENDED BY COMMAND",
								flush=True
							)
							session_ended = True
							break

						if music_paused_for_wake and intent["type"] not in ["music.stop", "music.pause", "music.resume", "music.next", "music.previous", "music.genres", "robot.move", "audio.volume"]:
							await asyncio.to_thread(
								music.resume
							)
							music_started = True
							print(
								"IGNORED NON-STOP COMMAND AFTER MUSIC WAKE; MUSIC RESUMED",
								flush=True
							)
							break

						if intent["type"] == "music.play":
							query = intent["query"]

							if music_paused_for_wake:
								await asyncio.to_thread(
									music.stop
								)

							try:
								station_name = await asyncio.to_thread(
									music.play,
									query
								)

							except Exception as exc:
								print(
									"MUSIC PLAY ERROR:",
									repr(exc),
									flush=True
								)
								await asyncio.to_thread(
									speech.say,
									RADIO["ERROR_RESPONSE"]
								)

								empty_turns = 0
								await asyncio.sleep(0.1)
								continue

							await asyncio.to_thread(
								speech.say,
								f"{RADIO['PLAYING_RESPONSE_PREFIX']}{station_name}."
							)
							print(
								"SESSION ENDED BY MUSIC",
								flush=True
							)
							session_ended = True
							music_started = True
							break

						if intent["type"] == "music.genres":
							answer = RADIO["GENRES_LIST_RESPONSE_PREFIX"] + music.list_genres() + "."

							print(
								"ASSISTANT:",
								answer,
								flush=True
							)

							await asyncio.to_thread(
								speech.say,
								answer
							)

							empty_turns = 0
							await asyncio.sleep(0.1)
							continue

						if intent["type"] == "music.stop":
							stopped = await asyncio.to_thread(
								music.stop
							)
							await asyncio.to_thread(
								speech.say,
								MUSIC["STOP_RESPONSE"] if stopped else MUSIC["NOT_PLAYING_RESPONSE"]
							)

							if music_paused_for_wake:
								print(
									"SESSION ENDED BY MUSIC STOP",
									flush=True
								)
								session_ended = True
								break

							continue

						if intent["type"] == "music.pause":
							paused = await asyncio.to_thread(
								music.pause
							)

							if music_paused_for_wake and paused:
								print(
									"SESSION ENDED BY MUSIC PAUSE",
									flush=True
								)
								session_ended = True
								break

							await asyncio.to_thread(
								speech.say,
								MUSIC["PAUSE_RESPONSE"] if paused else MUSIC["NOT_PLAYING_RESPONSE"]
							)
							continue

						if intent["type"] == "music.resume":
							resumed = await asyncio.to_thread(
								music.resume
							)

							if music_paused_for_wake and resumed:
								music_started = True
								print(
									"SESSION ENDED BY MUSIC RESUME",
									flush=True
								)
								session_ended = True
								break

							await asyncio.to_thread(
								speech.say,
								MUSIC["RESUME_RESPONSE"] if resumed else MUSIC["NOT_PLAYING_RESPONSE"]
							)
							continue

						if intent["type"] == "music.next":
							changed = await asyncio.to_thread(
								music.next
							)

							if music_paused_for_wake and changed:
								await asyncio.to_thread(
									music.resume
								)
								music_started = True
								print(
									"SESSION ENDED BY MUSIC NEXT",
									flush=True
								)
								session_ended = True
								break

							await asyncio.to_thread(
								speech.say,
								MUSIC["NEXT_RESPONSE"] if changed else MUSIC["NOT_PLAYING_RESPONSE"]
							)
							continue

						if intent["type"] == "music.previous":
							changed = await asyncio.to_thread(
								music.previous
							)

							if music_paused_for_wake and changed:
								await asyncio.to_thread(
									music.resume
								)
								music_started = True
								print(
									"SESSION ENDED BY MUSIC PREVIOUS",
									flush=True
								)
								session_ended = True
								break

							await asyncio.to_thread(
								speech.say,
								MUSIC["PREVIOUS_RESPONSE"] if changed else MUSIC["NOT_PLAYING_RESPONSE"]
							)
							continue

						if intent["type"] == "audio.volume":
							volume = await asyncio.to_thread(
								apply_volume_command,
								intent["query"] or text,
								music
							)
							answer = f"Ses seviyesi yüzde {volume}."

							print(
								"ASSISTANT:",
								answer,
								flush=True
							)

							if music_paused_for_wake:
								await asyncio.to_thread(
									music.resume
								)
								music_started = True
								print(
									"MUSIC RESUMED AFTER VOLUME COMMAND",
									flush=True
								)
								break

							await asyncio.to_thread(
								speech.say,
								answer
							)

							empty_turns = 0
							await asyncio.sleep(0.1)
							continue

						if intent["type"] == "local.time":
							answer = local_info.answer(text)

							print(
								"ASSISTANT:",
								answer,
								flush=True
							)

							await asyncio.to_thread(
								speech.say,
								answer
							)

							await asyncio.sleep(
								SPEECH["ASSISTANT_RESPONSE_PAUSE"]
							)

							empty_turns = 0
							await asyncio.sleep(0.1)
							continue

						if intent["type"] == "robot.move":
							if not movement:
								answer = "Motor servisi hazır değil."

							else:
								answer = await asyncio.to_thread(
									movement.execute,
									intent["query"] or text
								)

							print(
								"ASSISTANT:",
								answer,
								flush=True
							)

							if music_paused_for_wake:
								await asyncio.to_thread(
									music.resume
								)
								music_started = True
								print(
									"MUSIC RESUMED AFTER MOVE COMMAND",
									flush=True
								)
								break

							await asyncio.to_thread(
								speech.say,
								answer
							)

							await asyncio.sleep(
								SPEECH["ASSISTANT_RESPONSE_PAUSE"]
							)

							empty_turns = 0
							await asyncio.sleep(0.1)
							continue

						if intent["type"] == "system.shutdown":
							await asyncio.to_thread(
								speech.say,
								SYSTEM["SHUTDOWN_RESPONSE"]
							)
							await asyncio.to_thread(
								system.shutdown
							)
							print(
								"SYSTEM SHUTDOWN REQUESTED",
								flush=True
							)
							return

						if intent["type"] == "web.search":
							last_weather_turn = assistant._looks_like_weather(
								text
							) or assistant._looks_like_weather(
								intent["query"]
							)

							step_start = time.monotonic()
							answer = await asyncio.to_thread(
								assistant.ask_with_web,
								text,
								intent["query"]
							)
							log_timing(
								"assistant_web_answer",
								step_start
							)

							print(
								"ASSISTANT:",
								answer,
								flush=True
							)

							step_start = time.monotonic()
							await asyncio.to_thread(
								speech.say,
								answer
							)
							log_timing(
								"assistant_tts",
								step_start
							)

							await asyncio.sleep(
								SPEECH["ASSISTANT_RESPONSE_PAUSE"]
							)

							empty_turns = 0
							await asyncio.sleep(0.1)
							continue

						if music_paused_for_wake:
							await asyncio.to_thread(
								music.stop
							)

						step_start = time.monotonic()
						answer = await asyncio.to_thread(
							assistant.ask,
							text
						)
						log_timing(
							"assistant_answer",
							step_start
						)

						print(
							"ASSISTANT:",
							answer,
							flush=True
						)

						step_start = time.monotonic()
						await asyncio.to_thread(
							speech.say,
							answer
						)
						log_timing(
							"assistant_tts",
							step_start
						)

						await asyncio.sleep(
							SPEECH["ASSISTANT_RESPONSE_PAUSE"]
						)

						empty_turns = 0
						await asyncio.sleep(0.1)
						continue

					empty_turns += 1

					if stt.last_had_audio:
						print(
							"STT HEARD AUDIO BUT NO TEXT; LISTENING AGAIN",
							flush=True
						)
						empty_turns = 0
						continue

					if empty_turns >= STT["EMPTY_TURNS_TO_SLEEP"]:
						if music_paused_for_wake:
							await asyncio.to_thread(
								music.resume
							)
							music_started = True
							print(
								"MUSIC RESUMED AFTER FALSE WAKE",
								flush=True
							)

						print(
							"SESSION ENDED BY SILENCE",
							flush=True
						)
						session_ended = True
						break

				if not music_started and not music_paused_for_wake:
					await asyncio.to_thread(
						speech.end_beep
					)

				print(
					"REARMING WAKE WORD",
					flush=True
				)
				log_timing(
					"wake_session_total",
					wake_start
				)

				last_wake = time.monotonic()

				rearm_delay = WAKE["REARM_DELAY_SECONDS"]

				if music_started:
					rearm_delay = WAKE["MUSIC_REARM_DELAY_SECONDS"]

				await asyncio.sleep(
					rearm_delay
				)

				print(
					"READY: say hey jarvis",
					flush=True
				)

				if not music_started:
					await asyncio.to_thread(
						speech.ready_beep
					)

			except Exception as exc:
				print(
					"VOICE ERROR:",
					repr(exc),
					flush=True
				)

			finally:
				await listener.stop()

	except asyncio.CancelledError:
		if not stt_task.done():
			stt_task.cancel()

		await listener.stop()
		raise

	finally:
		await listener.stop()