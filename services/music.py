import subprocess
import time
import random

from config import MUSIC, RADIO
from services.audio import get_speaker_volume
from services.radio import RadioDirectory


class MusicService:

	def __init__(self):

		self.process = None
		self.playlist_urls = []
		self.playlist_names = []
		self.playlist_index = 0
		self.volume = self._initial_volume()
		self.radio = RadioDirectory()

	def _initial_volume(self):

		try:
			return get_speaker_volume()

		except Exception as exc:
			print(
				"MUSIC VOLUME INIT ERROR:",
				repr(exc),
				flush=True
			)
			return MUSIC["VOLUME"]

	def is_playing(self):

		return (
			self.process is not None and
			self.process.poll() is None
		)

	def list_genres(self):

		return ", ".join(
			self.radio.list_genre_labels()
		)

	def play(self, query):

		self.stop()

		genre = self.radio.resolve_genre(query)
		stations = self.radio.find_stations(genre)

		if not stations:
			raise RuntimeError(
				f"no radio stations found for genre {genre['KEY']}"
			)

		self.playlist_urls = [
			station["url"] for station in stations
		]
		self.playlist_names = [
			station["name"] for station in stations
		]
		self.playlist_index = random.randrange(
			len(self.playlist_urls)
		)
		attempts = min(
			len(self.playlist_urls),
			RADIO["MAX_STATION_ATTEMPTS"]
		)
		last_error = None

		for _ in range(attempts):
			url = self.playlist_urls[self.playlist_index]
			name = self.playlist_names[self.playlist_index]

			try:
				self._start_player([url])

				print(
					"MUSIC PLAY:",
					genre["KEY"],
					name,
					url,
					flush=True
				)

				return name

			except Exception as exc:
				last_error = exc
				print(
					"MUSIC STATION FAILED:",
					url,
					repr(exc),
					flush=True
				)
				self.playlist_index = (
					self.playlist_index + 1
				) % len(self.playlist_urls)

		raise RuntimeError(
			f"radio unavailable for genre {genre['KEY']}: {last_error!r}"
		)

	def _start_player(self, urls):

		log_file = open(
			MUSIC["LOG_FILE"],
			"a"
		)

		self.process = subprocess.Popen(
			[
				MUSIC["PLAYER"],
				"--no-video",
				f"--audio-device={MUSIC['AUDIO_DEVICE']}",
				f"--volume={self.volume}",
				*urls
			],
			stdin=subprocess.PIPE,
			stdout=log_file,
			stderr=subprocess.STDOUT,
			text=True
		)
		self.log_file = log_file

		time.sleep(
			RADIO["CONNECT_CHECK_SECONDS"]
		)

		if self.process.poll() is not None:
			raise RuntimeError(
				f"mpv exited with code {self.process.returncode}; see {MUSIC['LOG_FILE']}"
			)

	def stop(self):

		if not self.is_playing():
			self.process = None
			return False

		self.process.terminate()

		try:
			self.process.wait(
				timeout=2
			)

		except subprocess.TimeoutExpired:
			self.process.kill()
			self.process.wait()

		self.process = None

		if hasattr(self, "log_file"):
			self.log_file.close()

		return True

	def send_command(self, command):

		if not self.is_playing():
			return False

		try:
			self.process.stdin.write(
				f"{command}\n"
			)
			self.process.stdin.flush()

		except (BrokenPipeError, AttributeError):
			return False

		return True

	def set_volume(self, volume):

		volume = max(
			0,
			min(
				100,
				int(volume)
			)
		)
		self.volume = volume

		if self.is_playing():
			self.send_command(
				f"set volume {volume}"
			)

		return self.volume

	def pause(self):

		return self.send_command(
			"set pause yes"
		)

	def resume(self):

		return self.send_command(
			"set pause no"
		)

	def next(self):

		if self.playlist_urls:
			return self._move_playlist(1)

		changed = self.send_command(
			"playlist-next force"
		)

		print(
			"MUSIC NEXT:",
			changed,
			flush=True
		)

		return changed

	def previous(self):

		if self.playlist_urls:
			return self._move_playlist(-1)

		changed = self.send_command(
			"playlist-prev force"
		)

		print(
			"MUSIC PREVIOUS:",
			changed,
			flush=True
		)

		return changed

	def _move_playlist(self, offset):

		self.playlist_index = (
			self.playlist_index + offset
		) % len(self.playlist_urls)
		url = self.playlist_urls[self.playlist_index]
		label = "NEXT" if offset > 0 else "PREVIOUS"

		try:
			self.stop()
			self._start_player([url])
			changed = True

		except Exception as exc:
			print(
				f"MUSIC {label} ERROR:",
				repr(exc),
				flush=True
			)
			changed = False

		print(
			f"MUSIC {label}:",
			changed,
			self.playlist_index + 1,
			"/",
			len(self.playlist_urls),
			flush=True
		)

		return changed