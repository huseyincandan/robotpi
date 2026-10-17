"""Own the local llama.cpp server for the lifetime of the web application."""

from pathlib import Path
import json
import subprocess
import time
import urllib.request

from config import LLM
from services.llm import is_local


ROOT = Path(__file__).resolve().parents[1]


class LocalLLMRuntime:
    def __init__(self):
        self.process = None
        self.log = None

    def ready(self):
        try:
            url = LLM["BASE_URL"].rstrip("/") + "/models"
            with urllib.request.urlopen(url, timeout=1) as response:
                data = json.load(response)
            return any(item.get("id") == LLM["MODEL"] for item in data.get("data", []))
        except (OSError, ValueError):
            return False

    def start(self):
        if not is_local():
            return
        if self.ready():
            print("LOCAL LLM READY: reusing Qwen server", flush=True)
            return
        binary = ROOT / LLM["SERVER_BIN"]
        model = ROOT / LLM["MODEL_FILE"]
        if not binary.is_file() or not model.is_file():
            raise FileNotFoundError("Local Qwen assets missing; run scripts/setup_local_llm.py")
        log_path = ROOT / "logs/qwen-llm-server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = log_path.open("ab")
        self.process = subprocess.Popen([
            str(binary), "--model", str(model), "--alias", LLM["MODEL"],
            "--host", "127.0.0.1", "--port", str(LLM["PORT"]),
            "--ctx-size", str(LLM["CONTEXT_SIZE"]),
            "--threads", str(LLM["CPU_THREADS"]),
            "--threads-batch", str(LLM["CPU_THREADS"]),
            "--parallel", "1", "--n-gpu-layers", "0", "--jinja",
            "--reasoning", "off",
        ], stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log)
        deadline = time.monotonic() + LLM["STARTUP_TIMEOUT_SECONDS"]
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.stop()
                raise RuntimeError(f"Local Qwen server exited; see {log_path}")
            if self.ready():
                print("LOCAL LLM READY: Qwen3-0.6B, thinking disabled", flush=True)
                return
            time.sleep(0.2)
        self.stop()
        raise TimeoutError(f"Local Qwen startup timed out; see {log_path}")

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None
