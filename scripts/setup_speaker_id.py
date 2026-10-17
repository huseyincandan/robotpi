#!/usr/bin/env python3
"""Download the pinned CPU speaker embedding model; does not enroll anyone."""
from pathlib import Path
import hashlib
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / 'models/speaker/campplus-en.onnx'
SHA256 = '357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b'
URL = ('https://github.com/k2-fsa/sherpa-onnx/releases/download/'
       'speaker-recongition-models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx')

if __name__ == '__main__':
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    if not MODEL.exists() or hashlib.sha256(MODEL.read_bytes()).hexdigest() != SHA256:
        temporary = MODEL.with_suffix('.download')
        try:
            urllib.request.urlretrieve(URL, temporary)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != SHA256:
                raise RuntimeError('Speaker model checksum mismatch')
            temporary.replace(MODEL)
        finally:
            temporary.unlink(missing_ok=True)
    print(MODEL)
