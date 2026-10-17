import ctypes
import unittest
from unittest.mock import MagicMock, patch

from services.qwen_asr import QwenASRModel
from services.stt import STTService


class QwenNativeTests(unittest.TestCase):
    def model(self):
        model = QwenASRModel.__new__(QwenASRModel)
        model._ctx = 123
        model._lib = MagicMock()
        model._libc = MagicMock()
        return model

    def test_decodes_turkish_and_releases_native_result(self):
        model = self.model()
        result = ctypes.create_string_buffer("Bugün hava nasıl?".encode())
        pointer = ctypes.addressof(result)
        model._lib.qwen_transcribe.return_value = pointer
        self.assertEqual(model.transcribe("test.wav"), "Bugün hava nasıl?")
        model._libc.free.assert_called_once_with(pointer)

    def test_native_failure_is_not_reported_as_silence(self):
        model = self.model()
        model._lib.qwen_transcribe.return_value = None
        with self.assertRaisesRegex(RuntimeError, "transcription failed"):
            model.transcribe("test.wav")
        model._libc.free.assert_not_called()

    def test_close_releases_model_once_and_rejects_later_calls(self):
        model = self.model()
        model.close()
        model.close()
        model._lib.qwen_free.assert_called_once_with(123)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            model.transcribe("test.wav")


class STTIntegrationTests(unittest.TestCase):
    def test_local_provider_uses_trimmed_audio_and_reuses_qwen_model(self):
        service = STTService()
        with patch("services.stt.QwenASRModel") as constructor:
            constructor.return_value.transcribe.return_value = "Merhaba dünya."
            with patch.object(service, "has_speech", return_value=True):
                with patch.object(service, "trim_silence", return_value="trimmed.wav"):
                    self.assertEqual(service.transcribe("recording.wav"), "Merhaba dünya.")
                    self.assertEqual(service.transcribe("recording.wav"), "Merhaba dünya.")
            constructor.assert_called_once()
            constructor.return_value.transcribe.assert_called_with("trimmed.wav")
        self.assertIsNone(service.client)

    def test_silence_does_not_load_model(self):
        service = STTService()
        with patch.object(service, "has_speech", return_value=False):
            with patch("services.stt.QwenASRModel") as constructor:
                self.assertEqual(service.transcribe("silence.wav"), "")
                constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
