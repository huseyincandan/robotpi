"""Local two-stage speaker matching. Recognition never waits on the voice path."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading
import time
import unicodedata
import uuid
import wave

import numpy as np
from config import SPEAKER_ID

ROOT = Path(__file__).resolve().parents[1]


def load_audio(filename):
    with wave.open(str(filename), 'rb') as audio:
        if audio.getsampwidth() != 2 or audio.getnchannels() != 1 or audio.getframerate() != 16000:
            raise ValueError('Speaker audio must be mono 16-bit PCM WAV at 16000 Hz')
        return np.frombuffer(audio.readframes(audio.getnframes()), np.int16).copy()


def unit_vector(vector):
    vector = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if vector.ndim != 1 or not np.all(np.isfinite(vector)) or norm < 1e-8:
        raise ValueError('Invalid speaker embedding')
    return vector / norm


class SpeakerIdentityService:
    def __init__(self, config=None, extractor=None):
        self.config = dict(SPEAKER_ID if config is None else config)
        self.profile_file = ROOT / self.config['PROFILE_FILE']
        self._extractor = extractor
        self._lock = threading.RLock()
        self._inference_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='speaker-id')
        self._future = None
        self._profiles = {}
        self._session = 0
        self._wake = None
        self._command = None
        self._command_evaluated = False
        self._name = None
        self._conflict = False
        self.last_error = None
        self.reload_profiles()

    def reload_profiles(self):
        try:
            data = json.loads(self.profile_file.read_text())
            if data.get('model') != self.config['MODEL_ID']:
                raise ValueError('Speaker profiles belong to a different model')
            profiles = {}
            for item in data['speakers']:
                wake = unit_vector(item['wake'])
                command = unit_vector(item['command'])
                if len(wake) != self.config['EMBEDDING_DIM'] or len(command) != len(wake):
                    raise ValueError('Wrong speaker embedding dimension')
                profiles[item['id']] = {**item, 'wake': wake, 'command': command}
            with self._lock:
                self._profiles = profiles
                self._reset_session()
                self.last_error = None
        except FileNotFoundError:
            with self._lock:
                self._profiles = {}
                self._reset_session()
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            with self._lock:
                self._profiles = {}
                self._reset_session()
                self.last_error = str(exc)
            print('SPEAKER PROFILE ERROR:', str(exc), flush=True)

    def _reset_session(self):
        self._session += 1
        self._wake = self._command = self._name = None
        self._conflict = False
        self._command_evaluated = False

    def begin_session(self, wake_audio):
        with self._lock:
            self._reset_session()
        self._submit('wake', wake_audio)

    def end_session(self):
        with self._lock:
            self._reset_session()

    def submit_command_file(self, filename):
        with self._lock:
            if not self.config['ENABLED'] or not self._profiles or self._name or self._conflict:
                return
        try:
            # Copy before STT overwrites its temporary WAV on the next turn.
            self._submit('command', load_audio(filename))
        except (OSError, ValueError, wave.Error) as exc:
            print('SPEAKER AUDIO ERROR:', str(exc), flush=True)

    def _submit(self, phase, audio):
        with self._lock:
            if not self.config['ENABLED'] or not self._profiles:
                return False
            if self._future is not None and not self._future.done():
                # Keep at most one job; never build a queue behind slow inference.
                print('SPEAKER SKIPPED: worker busy', flush=True)
                return False
            snapshot = np.asarray(audio, dtype=np.int16).copy()
            self._future = self._executor.submit(self._recognize, phase, snapshot, self._session)
            return True

    def _prepare(self, samples, phase):
        samples = np.asarray(samples, dtype=np.int16)
        frame_size = 480
        count = len(samples) // frame_size
        if count == 0:
            return None
        rms = np.sqrt(np.mean(samples[:count * frame_size].reshape(count, frame_size).astype(np.float32) ** 2, axis=1))
        active = np.flatnonzero(rms >= self.config['MIN_RMS'])
        required = self.config['MIN_WAKE_SECONDS'] if phase == 'wake' else self.config['MIN_COMMAND_SECONDS']
        if len(active) * 0.03 < required:
            return None
        start = max(0, int(active[0]) * frame_size - 1600)
        end = min(len(samples), (int(active[-1]) + 1) * frame_size + 1600)
        if phase == 'wake':
            start = max(start, end - round(self.config.get('MAX_WAKE_AUDIO_SECONDS', 1.6) * 16000))
        else:
            end = min(end, start + round(self.config['MAX_AUDIO_SECONDS'] * 16000))
        return samples[start:end].astype(np.float32) / 32768.0

    def warmup(self):
        with self._lock:
            enabled = self.config['ENABLED'] and bool(self._profiles)
        if enabled:
            with self._inference_lock:
                self._load_extractor()

    def _load_extractor(self):
        if self._extractor is None:
            import sherpa_onnx
            configuration = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(ROOT / self.config['MODEL_FILE']), num_threads=1, provider='cpu')
            if not configuration.validate():
                raise RuntimeError('Speaker model missing; run scripts/setup_speaker_id.py')
            self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(configuration)

    def _embedding(self, samples):
        with self._inference_lock:
            self._load_extractor()
            stream = self._extractor.create_stream()
            stream.accept_waveform(sample_rate=16000, waveform=samples)
            stream.input_finished()
            if not self._extractor.is_ready(stream):
                raise ValueError('Insufficient speaker audio')
            return unit_vector(self._extractor.compute(stream))

    def _match(self, vector, phase):
        with self._lock:
            profiles = list(self._profiles.values())
        ranked = sorted(((float(np.dot(vector, item[phase])), item) for item in profiles),
                        key=lambda pair: pair[0], reverse=True)
        if not ranked:
            return None
        score, profile = ranked[0]
        margin = score - ranked[1][0] if len(ranked) > 1 else 1.0
        print(f"SPEAKER SCORE {phase}: best={profile['name']} similarity={score:.4f} margin={margin:.4f}", flush=True)
        if score < self.config['THRESHOLD'] or margin < self.config['MIN_MARGIN']:
            return None
        return {'id': profile['id'], 'name': profile['name'], 'score': round(score, 4)}

    def _recognize(self, phase, audio, session):
        started = time.monotonic()
        try:
            try:
                os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), self.config['WORKER_NICE'])
            except (AttributeError, OSError):
                pass
            samples = self._prepare(audio, phase)
            match = None if samples is None else self._match(self._embedding(samples), phase)
            with self._lock:
                if session != self._session:
                    return
                self.last_error = None
                if phase == 'wake':
                    self._wake = match
                else:
                    self._command = match
                    self._command_evaluated = samples is not None
                    if match and self._wake and match['id'] != self._wake['id']:
                        self._conflict = True
                        self._name = None
                    elif match and (self._wake or match['score'] >= self.config['COMMAND_ALONE_THRESHOLD']):
                        self._name = match['name']
                print(f'SPEAKER {phase}: match={match} confirmed={self._name} conflict={self._conflict}', flush=True)
        except Exception as exc:
            with self._lock:
                if session == self._session:
                    self._name = None
                    self.last_error = str(exc)
            print('SPEAKER ERROR:', repr(exc), flush=True)
        finally:
            print(f'TIMING: speaker_{phase} {time.monotonic() - started:.3f}s', flush=True)

    def confirmed_name(self):
        with self._lock:
            return self._name

    def session_name(self):
        """Use the same identity as the greeting unless there is contrary evidence.

        A short/noisy command is missing evidence, not a different speaker.
        This conversational name is not proof for replacing a stored profile.
        """
        with self._lock:
            if self._conflict:
                return None
            return self._name or (self._wake['name'] if self._wake else None)

    def should_offer_identification(self):
        with self._lock:
            return bool(self.config['ENABLED'] and not self.session_name()
                        and not self._wake and not self._conflict and not self.last_error
                        and self._command_evaluated
                        and (self._future is None or self._future.done()))

    def status(self):
        with self._lock:
            return {'enabled': self.config['ENABLED'], 'profiles': [
                {'id': item['id'], 'name': item['name']} for item in self._profiles.values()],
                'confirmed_name': self._name, 'session_name': self.session_name(),
                'command_evaluated': self._command_evaluated, 'wake_match': self._wake,
                'command_match': self._command, 'conflict': self._conflict,
                'busy': self._future is not None and not self._future.done(), 'error': self.last_error}

    def enroll(self, name, wake_files, command_files):
        name = ' '.join(unicodedata.normalize('NFC', name).split())
        if not 1 <= len(name) <= 64 or any(not (c.isalpha() or c in " '-") for c in name):
            raise ValueError('Name must contain only letters, spaces, apostrophes or hyphens')
        if len(wake_files) < 3 or len(command_files) < 3:
            raise ValueError('At least three wake and three command recordings are required')
        with self._lock:
            if any(item['name'].casefold() == name.casefold() for item in self._profiles.values()):
                raise ValueError('This name is already enrolled; delete that profile before replacing it')
        templates = {}
        for phase, files in (('wake', wake_files), ('command', command_files)):
            vectors = []
            for filename in files:
                samples = self._prepare(load_audio(filename), phase)
                if samples is None:
                    raise ValueError(f'Not enough clear speech in {filename}')
                vectors.append(self._embedding(samples))
            templates[phase] = unit_vector(np.mean(vectors, axis=0))
        item = {'id': uuid.uuid4().hex, 'name': name, **templates}
        with self._lock:
            self._profiles[item['id']] = item
            self._save_profiles()
        return item['id']

    def profile_named(self, name):
        with self._lock:
            return next(({'id': item['id'], 'name': item['name']} for item in self._profiles.values()
                         if item['name'].casefold() == name.casefold()), None)

    def prepare_sample(self, audio, phase):
        return self._prepare(audio, phase)

    def verify_claim(self, name, audio):
        samples = self._prepare(audio, 'command')
        if samples is None:
            return False
        match = self._match(self._embedding(samples), 'command')
        if not match or match['name'].casefold() != name.casefold():
            return False
        with self._lock:
            self._name = match['name']
            self._conflict = False
        return True

    def enroll_samples(self, name, wake_samples, command_samples, update=False):
        # Arrays are float32 prepared audio, held only until enrollment completes.
        name = ' '.join(unicodedata.normalize('NFC', name).split())
        if not 1 <= len(name) <= 64 or any(not (c.isalpha() or c in " '-") for c in name):
            raise ValueError('Invalid speaker name')
        with self._lock:
            original = self.profile_named(name)
            if update and (not original or self._name != original['name']):
                raise ValueError('Verify the existing speaker before updating')
            original_item = self._profiles.get(original['id']) if original else None
        if len(wake_samples) < 3 or len(command_samples) < 3:
            raise ValueError('Three samples per phase are required')
        templates = {}
        for phase, samples in (('wake', wake_samples), ('command', command_samples)):
            vectors = [self._embedding(sample) for sample in samples]
            if any(float(np.dot(a, b)) < 0.65 for i, a in enumerate(vectors) for b in vectors[i + 1:]):
                raise ValueError('Enrollment samples are inconsistent; try again in a quiet room')
            templates[phase] = unit_vector(np.mean(vectors, axis=0))
        item = {'id': original['id'] if update else uuid.uuid4().hex, 'name': name, **templates}
        with self._lock:
            if update and (self._profiles.get(item['id']) is not original_item or self._name != original['name']):
                raise ValueError('Speaker changed during update')
            if not update and self.profile_named(name):
                raise ValueError('A profile with this name already exists')
            self._profiles[item['id']] = item
            try:
                self._save_profiles()
            except Exception:
                if update:
                    self._profiles[item['id']] = original_item
                else:
                    del self._profiles[item['id']]
                raise
            self._name = name
            self._conflict = False
        return item['id']

    def delete(self, profile_id):
        with self._lock:
            if profile_id not in self._profiles:
                return False
            del self._profiles[profile_id]
            self._reset_session()
            self._save_profiles()
            return True

    def _save_profiles(self):
        self.profile_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.profile_file.with_suffix('.tmp')
        data = {'version': 1, 'model': self.config['MODEL_ID'], 'speakers': [
            {**item, 'wake': item['wake'].tolist(), 'command': item['command'].tolist()}
            for item in self._profiles.values()]}
        try:
            with temporary.open('w') as output:
                os.chmod(temporary, 0o600)
                json.dump(data, output, ensure_ascii=False)
            os.replace(temporary, self.profile_file)
        finally:
            temporary.unlink(missing_ok=True)

    def close(self):
        self.end_session()
        self._executor.shutdown(wait=False, cancel_futures=True)
