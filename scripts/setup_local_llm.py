#!/usr/bin/env python3
"""Install the pinned official llama.cpp ARM64 binary and Qwen3-0.6B Q8."""

import hashlib
from pathlib import Path
import platform
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "b11669"
ARCHIVE = f"llama-{RELEASE}-bin-ubuntu-arm64.tar.gz"
SHA256 = "9ac6fda2058d35677608a06f751a50122ddfa4ce0ddb7f084466b8e79b6d4a99"
DESTINATION = ROOT / "tools/llama-runtime"


def main():
    if platform.machine() != "aarch64":
        raise RuntimeError("This installer targets the robot's Debian ARM64 host")
    DESTINATION.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / ARCHIVE
        url = f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/{ARCHIVE}"
        urllib.request.urlretrieve(url, archive)
        with archive.open("rb") as downloaded:
            digest = hashlib.file_digest(downloaded, "sha256").hexdigest()
        if digest != SHA256:
            raise RuntimeError("llama.cpp archive SHA256 mismatch")
        with tarfile.open(archive) as package:
            package.extractall(Path(temporary) / "extracted", filter="data")
        import shutil
        shutil.copytree(Path(temporary) / "extracted" / f"llama-{RELEASE}",
                        DESTINATION, dirs_exist_ok=True)
    from huggingface_hub import hf_hub_download
    hf_hub_download(
        "Qwen/Qwen3-0.6B-GGUF", "Qwen3-0.6B-Q8_0.gguf",
        local_dir=ROOT / "models/qwen3-0.6b",
    )
    print("Local Qwen3-0.6B is ready")


if __name__ == "__main__":
    main()
