import atexit
import os
import shutil
import sys
import threading
from datetime import datetime

from config import LOGGING


_current_log_dir = None
_log_file = None
_original_stdout = sys.stdout
_original_stderr = sys.stderr


class TeeStream:

	def __init__(self, *streams):

		self.streams = streams
		self.lock = threading.Lock()

	def write(self, data):

		with self.lock:
			for stream in self.streams:
				stream.write(data)
				stream.flush()

		return len(data)

	def flush(self):

		with self.lock:
			for stream in self.streams:
				stream.flush()

	def isatty(self):

		return any(
			hasattr(stream, "isatty") and stream.isatty()
			for stream in self.streams
		)


def setup_run_logging():

	global _current_log_dir
	global _log_file

	if _current_log_dir:
		return _current_log_dir

	logs_dir = os.path.abspath(
		LOGGING["DIR"]
	)
	os.makedirs(
		logs_dir,
		exist_ok=True
	)

	if LOGGING.get("RESET_ON_START", False):
		_reset_logs_dir(logs_dir)

	run_prefix = "run-" + datetime.now().strftime(
		"%Y%m%d-%H%M%S"
	)
	run_dir = _create_unique_run_dir(
		logs_dir,
		run_prefix
	)

	log_path = os.path.join(
		run_dir,
		LOGGING["APP_LOG_FILE"]
	)
	_log_file = open(
		log_path,
		"a",
		encoding="utf-8",
		buffering=1
	)

	sys.stdout = TeeStream(
		_original_stdout,
		_log_file
	)
	sys.stderr = TeeStream(
		_original_stderr,
		_log_file
	)

	_current_log_dir = run_dir

	_write_run_metadata(run_dir)
	_prune_old_runs(logs_dir, run_dir)

	atexit.register(
		shutdown_run_logging
	)

	print(
		"LOG DIR:",
		run_dir,
		flush=True
	)

	return run_dir


def _reset_logs_dir(logs_dir):

	for name in os.listdir(logs_dir):
		path = os.path.join(logs_dir, name)

		if os.path.isdir(path):
			shutil.rmtree(path, ignore_errors=True)
			continue

		try:
			os.remove(path)
		except Exception:
			pass


def get_current_log_dir():

	return _current_log_dir


def shutdown_run_logging():

	global _log_file

	sys.stdout = _original_stdout
	sys.stderr = _original_stderr

	if _log_file and not _log_file.closed:
		_log_file.close()

	_log_file = None


def _write_run_metadata(run_dir):

	metadata_path = os.path.join(
		run_dir,
		"metadata.txt"
	)

	with open(
		metadata_path,
		"w",
		encoding="utf-8"
	) as metadata_file:
		metadata_file.write(
			"started_at=" + datetime.now().isoformat(timespec="seconds") + "\n"
		)
		metadata_file.write(
			"cwd=" + os.getcwd() + "\n"
		)
		metadata_file.write(
			"python=" + sys.executable + "\n"
		)


def _create_unique_run_dir(logs_dir, run_prefix):

	for index in range(100):
		suffix = "" if index == 0 else f"-{index}"
		run_dir = os.path.join(
			logs_dir,
			run_prefix + suffix
		)

		try:
			os.makedirs(
				run_dir,
				exist_ok=False
			)
			return run_dir

		except FileExistsError:
			continue

	raise RuntimeError(
		"Could not create a unique run log directory."
	)


def _prune_old_runs(logs_dir, current_run_dir):

	keep_runs = LOGGING["KEEP_RUNS"]
	run_dirs = []

	for name in os.listdir(logs_dir):
		path = os.path.join(
			logs_dir,
			name
		)

		if name.startswith("run-") and os.path.isdir(path):
			run_dirs.append(path)

	run_dirs.sort(
		key=lambda path: os.path.getmtime(path),
		reverse=True
	)

	for old_run_dir in run_dirs[keep_runs:]:
		if old_run_dir == current_run_dir:
			continue

		shutil.rmtree(
			old_run_dir,
			ignore_errors=True
		)
