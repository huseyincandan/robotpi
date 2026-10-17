#!/usr/bin/env python3
"""Build the pinned Qwen CPU engine on Debian ARM64 and download 0.6B weights.

Uses local Debian OpenBLAS packages, without changing system packages.
"""

from pathlib import Path
import platform
import subprocess


ROOT = Path(__file__).resolve().parents[1]
REVISION = "924694251d9e0f18e5d86bbd06aa3ab5f870002d"
ENGINE = ROOT / "tools/qwen-asr"
RUNTIME = ROOT / "tools/qwen-runtime"
SOURCES = [
    "qwen_asr.c", "qwen_asr_kernels.c", "qwen_asr_kernels_generic.c",
    "qwen_asr_kernels_neon.c", "qwen_asr_kernels_avx.c", "qwen_asr_audio.c",
    "qwen_asr_encoder.c", "qwen_asr_decoder.c", "qwen_asr_tokenizer.c",
    "qwen_asr_safetensors.c",
]


def main():
    if platform.machine() != "aarch64":
        raise RuntimeError("This setup script targets the robot's Debian ARM64 host")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if not ENGINE.exists():
        subprocess.run([
            "git", "clone", "https://github.com/antirez/qwen-asr.git", str(ENGINE)
        ], check=True)
    subprocess.run(["git", "checkout", REVISION], cwd=ENGINE, check=True)
    libdir = RUNTIME / "usr/lib/aarch64-linux-gnu/openblas-pthread"
    include = RUNTIME / "usr/include/aarch64-linux-gnu/openblas-pthread"
    if not (libdir / "libopenblas.so").exists():
        subprocess.run([
            "apt-get", "download", "libopenblas0-pthread", "libopenblas-pthread-dev"
        ], cwd=RUNTIME, check=True)
        for package in RUNTIME.glob("*.deb"):
            subprocess.run(["dpkg-deb", "-x", str(package), str(RUNTIME)], check=True)
    subprocess.run([
        "gcc", "-shared", "-fPIC", "-O3", "-mcpu=cortex-a76", "-ffast-math",
        "-DUSE_BLAS", "-DUSE_OPENBLAS", f"-I{include}", *SOURCES,
        "-o", "libqwen_asr.so", f"-L{libdir}",
        "-Wl,-rpath,$ORIGIN/../qwen-runtime/usr/lib/aarch64-linux-gnu/openblas-pthread",
        "-lopenblas", "-lm", "-lpthread",
    ], cwd=ENGINE, check=True)
    from huggingface_hub import snapshot_download
    snapshot_download(
        "Qwen/Qwen3-ASR-0.6B", local_dir=ROOT / "models/qwen3-asr-0.6b",
        allow_patterns=["config.json", "generation_config.json", "model.safetensors",
                        "vocab.json", "merges.txt"],
    )
    print("Qwen3-ASR 0.6B is ready")


if __name__ == "__main__":
    main()
