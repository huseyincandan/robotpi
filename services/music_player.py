"""mpv IPC and identity-checked handles for players surviving an app restart."""

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time


def process_info(pid):
    try:
        directory = Path('/proc') / str(pid)
        if directory.stat().st_uid != os.getuid():
            return None
        stat = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
        args = (directory / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
        return stat[0], stat[19], [os.fsdecode(arg) for arg in args]
    except (OSError, IndexError, ValueError):
        return None


class AttachedPlayer:
    def __init__(self, pid):
        self.pid = int(pid)
        info = process_info(self.pid)
        if not info or info[0] in ('Z', 'X'):
            raise ProcessLookupError(self.pid)
        self.started = info[1]

    def poll(self):
        info = process_info(self.pid)
        return None if info and info[0] not in ('Z', 'X') and info[1] == self.started else 0

    def terminate(self):
        self._signal(signal.SIGTERM)

    def kill(self):
        self._signal(signal.SIGKILL)

    def _signal(self, sig):
        if self.poll() is None:
            try:
                os.kill(self.pid, sig)
            except ProcessLookupError:
                pass

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired('mpv', timeout)
            time.sleep(0.03)
        return 0


def ipc_request(path, command):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(1.0)
        connection.connect(str(path))
        connection.sendall(json.dumps({'command': command, 'request_id': 1}).encode() + b'\n')
        pending = b''
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            chunk = connection.recv(65536)
            if not chunk:
                break
            pending += chunk
            if len(pending) > 1_000_000:
                raise RuntimeError('mpv IPC response too large')
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                response = json.loads(line)
                if response.get('request_id') != 1:
                    continue
                if response.get('error') != 'success':
                    raise RuntimeError(f"mpv command failed: {response.get('error')}")
                return response.get('data')
        raise TimeoutError('mpv IPC did not answer')
