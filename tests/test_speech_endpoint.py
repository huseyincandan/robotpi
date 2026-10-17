import tempfile
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
import wave

import numpy as np

from config import STT
from services.speech_endpoint import SpeechEndpoint
from services.stt import STTService


def frames(level, count):
    return [np.full(480, level, dtype=np.int16) for _ in range(count)]


class EndpointTests(unittest.TestCase):
    def test_loud_non_speech_does_not_extend_four_second_wait(self):
        detector = SpeechEndpoint(16000, start_timeout=4.0)
        for frame in frames(5000, 133):
            self.assertIsNone(detector.feed(frame, speech_detected=False))
        self.assertEqual(detector.feed(frames(5000, 1)[0], speech_detected=False), 'no_speech')
        self.assertFalse(detector.started)

    def test_detected_speech_before_deadline_keeps_recording(self):
        detector = SpeechEndpoint(16000, start_timeout=4.0, silence_seconds=1.2)
        for frame in frames(3000, 120):
            self.assertIsNone(detector.feed(frame, speech_detected=False))
        for frame in frames(1000, 20):
            self.assertIsNone(detector.feed(frame, speech_detected=True))
        self.assertTrue(detector.started)

    def test_real_silero_rejects_noise_and_tone_until_timeout(self):
        from openwakeword.vad import VAD
        vad = VAD()
        rng = np.random.default_rng(42)
        signals = [rng.normal(0, 600, 16000 * 5).astype(np.int16),
                   (3000 * np.sin(2 * np.pi * 440 * np.arange(16000 * 5) / 16000)).astype(np.int16)]
        for audio in signals:
            vad.reset_states()
            detector = SpeechEndpoint(16000, start_timeout=4)
            for i in range(0, len(audio) - 480, 480):
                frame = audio[i:i + 480]
                result = detector.feed(frame, bool(vad.predict(frame) >= STT['VAD_THRESHOLD']))
                if result:
                    break
            self.assertEqual(result, 'no_speech')
            self.assertAlmostEqual(detector.total_samples / 16000, 4.02)
            self.assertFalse(detector.started)

    def test_current_settings_preserve_pause_and_quiet_sentence_ending(self):
        detector = SpeechEndpoint(
            16000, silence_seconds=STT["END_SILENCE_SECONDS"],
            start_rms=STT["SPEECH_START_RMS"],
            continue_rms=STT["SPEECH_CONTINUE_RMS"]
        )
        for frame in frames(1000, 10) + frames(0, 30) + frames(300, 10) + frames(0, 39):
            self.assertIsNone(detector.feed(frame))
        self.assertEqual(detector.feed(frames(0, 1)[0]), "silence")

    def test_waits_for_speech_then_stops_after_600ms_silence(self):
        detector = SpeechEndpoint(16000)
        for frame in frames(0, 20) + frames(1200, 10) + frames(0, 19):
            self.assertIsNone(detector.feed(frame))
        self.assertEqual(detector.feed(frames(0, 1)[0]), "silence")

    def test_short_pause_and_quieter_speech_do_not_end_sentence(self):
        detector = SpeechEndpoint(16000)
        for frame in (frames(1200, 10) + frames(0, 10) + frames(500, 10)
                      + frames(0, 19)):
            self.assertIsNone(detector.feed(frame))
        self.assertEqual(detector.feed(frames(0, 1)[0]), "silence")

    def test_click_does_not_start_speech_and_wait_is_bounded(self):
        detector = SpeechEndpoint(16000)
        for frame in frames(1200, 1) + frames(0, 98):
            self.assertIsNone(detector.feed(frame))
        self.assertEqual(detector.feed(frames(0, 1)[0]), "no_speech")
        self.assertFalse(detector.started)


class RecordingTests(unittest.TestCase):
    def test_no_speech_endpoint_does_not_keep_session_awake_on_background_noise(self):
        service = STTService()
        service.last_had_audio = True
        def no_speech_record(**kwargs):
            service.last_record_reason = "no_speech"
            return "unused.wav"
        with patch.object(service, "record", side_effect=no_speech_record):
            with patch.object(service, "transcribe") as transcribe:
                self.assertEqual(service.listen(), "")
                transcribe.assert_not_called()
        self.assertFalse(service.last_had_audio)

    def record(self, raw_frames, max_seconds=10):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        filename = str(Path(temporary.name) / "record.wav")
        process = MagicMock()
        process.poll.return_value = None
        with patch.dict(STT, {"RECORD_FILE": filename, "CHANNELS": 6,
                              "MICROPHONE_SELECT_CHANNEL": 0}):
            with patch("services.stt.subprocess.Popen", return_value=process):
                with patch("services.stt.selectors.DefaultSelector"):
                    with patch("services.stt.os.read", side_effect=raw_frames), patch("services.stt.VAD") as vad:
                        vad.return_value.predict.return_value = 1.0
                        STTService()._record_until_silence(max_seconds)
        return filename, process

    def test_selected_channel_controls_endpoint_and_writes_valid_mono_wav(self):
        raw = []
        quiet_frames = round(STT["END_SILENCE_SECONDS"] / 0.03)
        frame_count = 10 + quiet_frames
        for mono in frames(1200, 10) + frames(0, quiet_frames):
            multichannel = np.full((480, 6), 2000, dtype=np.int16)
            multichannel[:, 0] = mono
            raw.append(multichannel.tobytes())
        filename, process = self.record(raw)
        with wave.open(filename) as audio:
            self.assertEqual(audio.getnchannels(), 1)
            self.assertEqual(audio.getframerate(), 16000)
            self.assertEqual(audio.getnframes(), frame_count * 480)
            samples = np.frombuffer(audio.readframes(frame_count * 480), dtype=np.int16)
        np.testing.assert_array_equal(samples[:4800], 1200)
        np.testing.assert_array_equal(samples[4800:], 0)
        process.terminate.assert_called_once()
        process.stdout.close.assert_called_once()

    def test_continuous_sound_still_stops_at_maximum_duration(self):
        raw = [np.full((480, 6), 1200, dtype=np.int16).tobytes()] * 20
        filename, _ = self.record(raw, max_seconds=0.1)
        with wave.open(filename) as audio:
            self.assertEqual(audio.getnframes(), 1600)

    def test_disconnect_reports_error_and_releases_capture(self):
        with self.assertRaisesRegex(RuntimeError, "stream ended"):
            self.record([b""])


if __name__ == "__main__":
    unittest.main()
