import subprocess
import time
import random
import json
import os
from pathlib import Path
import shlex
import threading

from services.music_player import AttachedPlayer, ipc_request, process_info

from config import MUSIC, RADIO
from services.audio import get_speaker_volume
from services.radio import RadioDirectory
from functools import wraps


def synchronized(method):
	@wraps(method)
	def wrapped(self, *args, **kwargs):
		with self._lock:
			return method(self, *args, **kwargs)
	return wrapped


class MusicService:

	def __init__(self):

		self._lock = threading.RLock()
		self.ipc_path = Path(MUSIC["IPC_SOCKET"])
		self.state_file = Path(MUSIC["STATE_FILE"])
		if not self.state_file.is_absolute():
			self.state_file = Path(__file__).resolve().parents[1] / self.state_file
		self.process = None
		self.playlist_urls = []
		self.playlist_names = []
		self.playlist_index = 0
		self.volume = self._initial_volume()
		self.radio = RadioDirectory()
		self._restore_player()

	def _save_state(self):

		if not self.is_playing():
			return
		self.state_file.parent.mkdir(parents=True, exist_ok=True)
		data = {"pid": self.process.pid, "playlist_urls": self.playlist_urls,
			"playlist_names": self.playlist_names, "playlist_index": self.playlist_index,
			"volume": self.volume}
		temporary = self.state_file.with_name(self.state_file.name + f".{os.getpid()}.tmp")
		try:
			with temporary.open("w") as output:
				os.chmod(temporary, 0o600)
				json.dump(data, output, ensure_ascii=False)
			os.replace(temporary, self.state_file)
		finally:
			temporary.unlink(missing_ok=True)

	def _restore_player(self):

		try:
			pid = int(ipc_request(self.ipc_path, ["get_property", "pid"]))
			info = process_info(pid)
			if not info or Path(info[2][0]).name != Path(MUSIC["PLAYER"]).name or f"--input-ipc-server={self.ipc_path}" not in info[2]:
				print("MUSIC RECOVERY: socket does not belong to this application's mpv", flush=True)
				return
			self.process = AttachedPlayer(pid)
			current_url = ipc_request(self.ipc_path, ["get_property", "path"])
			try:
				state = json.loads(self.state_file.read_text())
			except (OSError, ValueError):
				state = {}
			if not isinstance(state, dict):
				state = {}
			urls = state.get("playlist_urls", [])
			names = state.get("playlist_names", [])
			if isinstance(urls, list) and all(isinstance(url, str) for url in urls) and current_url in urls:
				self.playlist_urls = urls
				self.playlist_names = names if isinstance(names, list) and len(names) == len(urls) and all(isinstance(name, str) for name in names) else ["Mevcut radyo"] * len(urls)
				self.playlist_index = urls.index(current_url)
			else:
				self.playlist_urls = [current_url]
				self.playlist_names = ["Mevcut radyo"]
			self.volume = round(float(ipc_request(self.ipc_path, ["get_property", "volume"])))
			self._save_state()
			print("MUSIC REATTACHED: pid=", pid, flush=True)
			return
		except (OSError, ValueError, RuntimeError, TypeError, IndexError) as exc:
			if self.process is not None:
				print("MUSIC RECOVERY ERROR:", repr(exc), flush=True)
				return

		# One-time migration of a player launched by the former stdin-only code.
		legacy = []
		for directory in Path("/proc").iterdir():
			if not directory.name.isdigit():
				continue
			info = process_info(directory.name)
			if not info or not info[2] or Path(info[2][0]).name != Path(MUSIC["PLAYER"]).name:
				continue
			args = info[2]
			if "--no-video" not in args or any(arg.startswith("--input-ipc-server=") for arg in args):
				continue
			try:
				if (directory / "fd/1").resolve() != Path(MUSIC["LOG_FILE"]).resolve():
					continue
			except OSError:
				continue
			urls = [arg for arg in args[1:] if arg.startswith(("http://", "https://"))]
			if urls:
				legacy.append((int(directory.name), args, urls))
		if len(legacy) != 1:
			if legacy:
				print("MUSIC RECOVERY: multiple legacy players; no process changed", flush=True)
			return
		pid, args, urls = legacy[0]
		try:
			self.process = AttachedPlayer(pid)
		except ProcessLookupError:
			return
		self.playlist_urls = urls
		self.playlist_names = ["Mevcut radyo"] * len(urls)
		for arg in args:
			if arg.startswith("--volume="):
				try:
					self.volume = max(0, min(100, round(float(arg.split("=", 1)[1]))))
				except ValueError:
					pass
		self.stop()
		self._start_player(urls)
		print("MUSIC LEGACY MIGRATED: old_pid=", pid, "new_pid=", self.process.pid, flush=True)

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

	@synchronized
	def is_playing(self):

		return (
			self.process is not None and
			self.process.poll() is None
		)

	def list_genres(self):

		return ", ".join(
			self.radio.list_genre_labels()
		)

	@synchronized
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

		self.ipc_path.parent.mkdir(parents=True, exist_ok=True)
		# A live player is always stopped/adopted before starting a replacement.
		self.ipc_path.unlink(missing_ok=True)
		with open(MUSIC["LOG_FILE"], "a") as log_file:
			self.process = subprocess.Popen(
				[
					MUSIC["PLAYER"], "--no-video",
					f"--input-ipc-server={self.ipc_path}",
					f"--audio-device={MUSIC['AUDIO_DEVICE']}",
					f"--volume={self.volume}",
					*MUSIC.get("PLAYER_ARGS", []), *urls
				],
				stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
				start_new_session=True
			)
		time.sleep(RADIO["CONNECT_CHECK_SECONDS"])
		deadline = time.monotonic() + 2.0
		while True:
			if self.process.poll() is not None:
				raise RuntimeError(f"mpv exited with code {self.process.returncode}; see {MUSIC['LOG_FILE']}")
			try:
				ipc_request(self.ipc_path, ["get_property", "pid"])
				ipc_request(self.ipc_path, ["get_property", "path"])
				break
			except (OSError, RuntimeError):
				if time.monotonic() >= deadline:
					self.stop()
					raise RuntimeError("mpv IPC did not become ready")
				time.sleep(0.05)
		if not self.playlist_urls:
			self.playlist_urls = list(urls)
			self.playlist_names = ["Mevcut radyo"] * len(urls)
		self._save_state()

	@synchronized
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
		self.ipc_path.unlink(missing_ok=True)
		self.state_file.unlink(missing_ok=True)

		if hasattr(self, "log_file"):
			self.log_file.close()

		return True

	@synchronized
	def send_command(self, command):

		if not self.is_playing():
			return False
		parts = shlex.split(command)
		if len(parts) == 3 and parts[0] == "set":
			value = {"yes": True, "no": False}.get(parts[2], parts[2])
			if parts[1] == "volume":
				value = float(parts[2])
			parts = ["set_property", parts[1], value]
		try:
			ipc_request(self.ipc_path, parts)
		except (OSError, RuntimeError) as exc:
			print("MUSIC IPC ERROR:", repr(exc), flush=True)
			return False
		self._save_state()
		return True

	@synchronized
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

	@synchronized
	def pause(self):

		return self.send_command(
			"set pause yes"
		)

	@synchronized
	def resume(self):

		return self.send_command(
			"set pause no"
		)

	@synchronized
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

	@synchronized
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