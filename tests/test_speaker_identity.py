import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
from config import SPEAKER_ID
from services.speaker_identity import SpeakerIdentityService


class SpeakerIdentityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        config = {**SPEAKER_ID, 'PROFILE_FILE': str(Path(self.directory.name) / 'profiles.json'), 'EMBEDDING_DIM': 2}
        self.service = SpeakerIdentityService(config)
        self.audio = np.full(32000, 1000, np.int16)
        self.service._embedding = lambda samples: np.array([1., 0.])

    def tearDown(self):
        self.service.close()
        self.directory.cleanup()

    def profiles(self):
        self.service._profiles = {
            'a': dict(id='a', name='Ada', wake=np.array([1., 0.]), command=np.array([1., 0.])),
            'b': dict(id='b', name='Ece', wake=np.array([0., 1.]), command=np.array([0., 1.]))}

    def test_no_profiles_does_not_run_model(self):
        self.service._embedding = lambda _: self.fail('Model must remain unloaded')
        self.service.begin_session(self.audio)
        self.assertIsNone(self.service._future)
        self.assertIsNone(self.service.confirmed_name())

    def test_wake_is_tentative_command_confirms_and_session_clears(self):
        self.profiles()
        session = self.service._session
        self.service._recognize('wake', self.audio, session)
        self.assertIsNone(self.service.confirmed_name())
        self.service._recognize('command', self.audio, session)
        self.assertEqual(self.service.confirmed_name(), 'Ada')
        self.service.end_session()
        self.assertIsNone(self.service.confirmed_name())

    def test_conflicting_speakers_stay_unknown(self):
        self.profiles()
        session = self.service._session
        self.service._recognize('wake', self.audio, session)
        self.service._embedding = lambda _: np.array([0., 1.])
        self.service._recognize('command', self.audio, session)
        self.assertTrue(self.service.status()['conflict'])
        self.assertIsNone(self.service.confirmed_name())

    def test_stale_background_result_is_ignored(self):
        self.profiles()
        entered, release = threading.Event(), threading.Event()
        def embedding(_):
            entered.set()
            release.wait(2)
            return np.array([1., 0.])
        self.service._embedding = embedding
        self.service._submit('command', self.audio)
        self.assertTrue(entered.wait(1))
        self.assertFalse(self.service._submit('command', self.audio))
        self.service.end_session()
        release.set()
        self.service._future.result(2)
        self.assertIsNone(self.service.confirmed_name())

    def test_ambiguous_match_rejected(self):
        self.profiles()
        self.service._profiles['b']['command'] = np.array([1., 0.])
        self.assertIsNone(self.service._match(np.array([1., 0.]), 'command'))

    def test_speaker_callback_precedes_stt_and_failure_does_not_break_it(self):
        from services.stt import STTService
        calls = []
        def callback(filename):
            calls.append('speaker')
            raise RuntimeError('test extraction failure')
        service = STTService(on_recorded=callback)
        with patch.object(service, 'record', return_value='copied.wav'), patch.object(
                service, 'transcribe', side_effect=lambda _: calls.append('stt') or 'Merhaba'):
            self.assertEqual(service.listen(), 'Merhaba')
        self.assertEqual(calls, ['speaker', 'stt'])

    def test_assistant_forgets_confirmed_identity_on_reset(self):
        from services.assistant import AssistantService
        assistant = AssistantService()
        assistant.set_speaker('Ada')
        self.assertIn('Ada', assistant.messages[0]['content'])
        assistant.reset()
        self.assertNotIn('Ada', assistant.messages[0]['content'])
        self.assertIsNone(assistant.speaker_name)

    def test_spoken_enrollment_persists_and_rejects_overwrite(self):
        samples = [np.ones(16000, np.float32)] * 3
        profile_id = self.service.enroll_samples('Ada', samples, samples)
        self.service.reload_profiles()
        self.assertEqual(self.service.profile_named('Ada')['id'], profile_id)
        self.assertTrue(self.service.verify_claim('Ada', self.audio))
        with self.assertRaises(ValueError):
            self.service.enroll_samples('Ada', samples, samples)
        self.assertEqual(len(self.service.status()['profiles']), 1)

    def test_mixed_enrollment_samples_are_not_saved(self):
        vectors = iter([np.array([1., 0.]), np.array([0., 1.]), np.array([1., 0.])])
        self.service._embedding = lambda _: next(vectors)
        samples = [np.ones(16000, np.float32)] * 3
        with self.assertRaises(ValueError):
            self.service.enroll_samples('Ada', samples, samples)
        self.assertFalse(self.service.profile_file.exists())

    def test_update_preserves_id_and_rolls_back_on_disk_failure(self):
        samples = [np.ones(16000, np.float32)] * 3
        profile_id = self.service.enroll_samples('Ada', samples, samples)
        original = self.service._profiles[profile_id]
        self.service._embedding = lambda _: np.array([0.9, 0.1]) / np.linalg.norm([0.9, 0.1])
        with patch.object(self.service, '_save_profiles', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.service.enroll_samples('Ada', samples, samples, update=True)
        self.assertIs(self.service._profiles[profile_id], original)
        self.assertEqual(self.service.enroll_samples('Ada', samples, samples, update=True), profile_id)
        self.service.reload_profiles()
        self.assertGreater(self.service._profiles[profile_id]['wake'][1], 0)

    def test_update_requires_existing_verified_identity(self):
        samples = [np.ones(16000, np.float32)] * 3
        self.service.enroll_samples('Ada', samples, samples)
        self.service.end_session()
        with self.assertRaises(ValueError):
            self.service.enroll_samples('Ada', samples, samples, update=True)

    def test_greeted_person_is_not_sent_to_profile_dialog_on_short_command(self):
        self.profiles()
        session = self.service._session
        self.service._recognize('wake', self.audio, session)
        self.service._recognize('command', np.full(4800, 1000, np.int16), session)
        self.assertEqual(self.service.session_name(), 'Ada')
        self.assertIsNone(self.service.confirmed_name())
        self.assertFalse(self.service.should_offer_identification())
        self.service.end_session()
        self.assertIsNone(self.service.session_name())

    def test_unmatched_command_does_not_erase_greeting_identity(self):
        self.profiles()
        session = self.service._session
        self.service._recognize('wake', self.audio, session)
        self.service._embedding = lambda _: np.array([-1., 0.])
        self.service._recognize('command', self.audio, session)
        self.assertEqual(self.service.session_name(), 'Ada')
        self.assertFalse(self.service.should_offer_identification())

    def test_conflict_clears_personalization_without_forcing_enrollment(self):
        self.profiles()
        session = self.service._session
        self.service._recognize('wake', self.audio, session)
        self.service._embedding = lambda _: np.array([0., 1.])
        self.service._recognize('command', self.audio, session)
        self.assertIsNone(self.service.session_name())
        self.assertFalse(self.service.should_offer_identification())

    def test_unknown_person_prompt_requires_completed_sufficient_sample(self):
        self.profiles()
        session = self.service._session
        self.assertFalse(self.service.should_offer_identification())
        self.service._recognize('command', np.zeros(32000, np.int16), session)
        self.assertFalse(self.service.should_offer_identification())
        self.service._embedding = lambda _: np.array([-1., 0.])
        self.service._recognize('command', self.audio, session)
        self.assertTrue(self.service.should_offer_identification())
        self.service.last_error = 'model failed'
        self.assertFalse(self.service.should_offer_identification())

    def test_pending_command_result_never_opens_profile_dialog(self):
        self.profiles()
        entered, release = threading.Event(), threading.Event()
        def embedding(_):
            entered.set()
            release.wait(2)
            return np.array([-1., 0.])
        self.service._embedding = embedding
        self.service._submit('command', self.audio)
        self.assertTrue(entered.wait(1))
        self.assertFalse(self.service.should_offer_identification())
        release.set()
        self.service._future.result(2)
        self.assertTrue(self.service.should_offer_identification())

    def test_invalid_database_is_safe(self):
        self.service.profile_file.write_text('[]')
        self.service.reload_profiles()
        self.assertEqual(self.service.status()['profiles'], [])
        self.assertTrue(self.service.status()['error'])


if __name__ == '__main__':
    unittest.main()
