"""Persistent CPU inference for the Qwen3-ASR model via antirez/qwen-asr."""

import ctypes
from pathlib import Path
import threading


PROJECT_DIR = Path(__file__).resolve().parents[1]


class QwenASRModel:
    # The native engine uses a global worker pool; serialize native calls.
    _lock = threading.Lock()

    def __init__(self, model_dir, library_path, threads=3, language="tr"):
        self._ctx = None
        model_dir = (PROJECT_DIR / model_dir).resolve()
        library_path = (PROJECT_DIR / library_path).resolve()
        for path in (library_path, model_dir / "model.safetensors"):
            if not path.is_file():
                raise FileNotFoundError(
                    f"Qwen ASR asset missing: {path}; run scripts/setup_qwen_asr.py"
                )
        self._lib = ctypes.CDLL(str(library_path))
        self._lib.qwen_set_threads.argtypes = [ctypes.c_int]
        self._lib.qwen_set_threads.restype = None
        self._lib.openblas_set_num_threads.argtypes = [ctypes.c_int]
        self._lib.openblas_set_num_threads.restype = None
        self._lib.qwen_load.argtypes = [ctypes.c_char_p]
        self._lib.qwen_load.restype = ctypes.c_void_p
        self._lib.qwen_set_force_language.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self._lib.qwen_set_force_language.restype = ctypes.c_int
        self._lib.qwen_transcribe.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        # Keep the allocated pointer so it can be freed after decoding.
        self._lib.qwen_transcribe.restype = ctypes.c_void_p
        self._lib.qwen_free.argtypes = [ctypes.c_void_p]
        self._lib.qwen_free.restype = None
        self._libc = ctypes.CDLL(None)
        self._libc.free.argtypes = [ctypes.c_void_p]
        self._libc.free.restype = None
        with self._lock:
            ctypes.c_int.in_dll(self._lib, "qwen_verbose").value = 0
            self._lib.openblas_set_num_threads(max(1, threads))
            self._lib.qwen_set_threads(max(1, threads))
            self._ctx = self._lib.qwen_load(str(model_dir).encode())
            if not self._ctx:
                raise RuntimeError(f"Could not load Qwen ASR from {model_dir}")
            language = "Turkish" if language == "tr" else language
            if self._lib.qwen_set_force_language(self._ctx, language.encode()) != 0:
                self._lib.qwen_free(self._ctx)
                self._ctx = None
                raise ValueError(f"Unsupported Qwen ASR language: {language}")

    def transcribe(self, audio_file):
        with self._lock:
            if not self._ctx:
                raise RuntimeError("Qwen ASR model is closed")
            result = self._lib.qwen_transcribe(
                self._ctx, str(Path(audio_file).resolve()).encode()
            )
            if not result:
                raise RuntimeError("Qwen ASR transcription failed")
            try:
                return ctypes.string_at(result).decode("utf-8").strip()
            finally:
                self._libc.free(result)

    def close(self):
        with self._lock:
            if self._ctx:
                self._lib.qwen_free(self._ctx)
                self._ctx = None
