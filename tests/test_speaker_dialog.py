import unittest
from unittest.mock import Mock, AsyncMock
import numpy as np
from services.speaker_dialog import SpeakerDialog, parse_name, profile_request, is_cancel


class NameTests(unittest.TestCase):
    def test_explicit_profile_requests(self):
        for text in ('Ses profilimi oluştur', 'Ses profilimi kaydet', 'Ses profili oluşturmak istiyorum'):
            self.assertEqual(profile_request(text), 'create')
        for text in ('Ses profilimi güncelle', 'Ses profilimi güncellemek istiyorum', 'Ses profilimi yeniden kaydet'):
            self.assertEqual(profile_request(text), 'update')
        for text in ('Ses profili nedir?', 'Ses profilimi güncelleme', 'Ses profilimi oluşturmak istemiyorum', 'Müzik aç'):
            self.assertIsNone(profile_request(text))

    def test_turkish_capital_i_cancel_never_becomes_name(self):
        for text in ('iptal', 'İptal.', 'İPTAL!', 'İptal et', 'İpter', 'Vazgeçtim'):
            self.assertTrue(is_cancel(text))
            self.assertIsNone(parse_name(text))
        self.assertFalse(is_cancel('İlter'))
        self.assertFalse(is_cancel('iptal etme'))

    def test_name(self):
        self.assertEqual(parse_name('Benim adım Hüseyin.'), 'Hüseyin')
        self.assertIsNone(parse_name('iptal'))
        self.assertIsNone(parse_name('bir iki üç dört beş altı'))


class DialogTests(unittest.IsolatedAsyncioTestCase):
    def dialog(self, responses):
        identity = Mock()
        identity.profile_named.return_value = None
        identity.prepare_sample.side_effect = lambda audio, phase: audio
        stt = Mock(on_recorded=Mock())
        dialog = SpeakerDialog(identity, stt, Mock())
        audio = np.ones(16000, np.float32)
        dialog.listen = AsyncMock(side_effect=[(text, audio if text else None) for text in responses])
        dialog.say = AsyncMock()
        return dialog, identity, stt

    async def test_real_listen_cancels_before_audio_file_or_name_confirmation(self):
        from unittest.mock import patch
        identity, stt, speech = Mock(), Mock(), Mock()
        stt.listen.return_value = 'İptal.'
        dialog = SpeakerDialog(identity, stt, speech)
        dialog.say = AsyncMock()
        with patch('services.speaker_dialog.load_audio') as audio:
            self.assertIsNone(await dialog.run())
        audio.assert_not_called()
        identity.enroll_samples.assert_not_called()
        self.assertFalse(any('Adını ' in str(call) for call in dialog.say.call_args_list))

    async def test_new_profile_collects_all_samples(self):
        dialog, identity, stt = self.dialog(['Ada', 'evet', 'evet'] + ['ses'] * 6)
        callback = stt.on_recorded
        self.assertEqual(await dialog.run(), 'Ada')
        args = identity.enroll_samples.call_args.args
        self.assertEqual(args[0], 'Ada')
        self.assertEqual(len(args[1]), 3)
        self.assertEqual(len(args[2]), 3)
        self.assertIs(stt.on_recorded, callback)

    async def test_existing_profile_verified_without_enrollment(self):
        dialog, identity, _ = self.dialog(['Ada', 'evet', 'Uzun bir cümle'])
        identity.profile_named.return_value = {'id': 'a', 'name': 'Ada'}
        identity.verify_claim.return_value = True
        self.assertEqual(await dialog.run(), 'Ada')
        identity.enroll_samples.assert_not_called()

    async def test_update_verifies_then_collects_samples(self):
        dialog, identity, _ = self.dialog(['Ada', 'evet', 'cümle', 'evet'] + ['ses'] * 6)
        identity.profile_named.return_value = {'id': 'a', 'name': 'Ada'}
        identity.verify_claim.return_value = True
        self.assertEqual(await dialog.run(mode='update'), 'Ada')
        self.assertEqual(identity.enroll_samples.call_args.kwargs, {'update': True})

    async def test_failed_verification_never_updates(self):
        dialog, identity, _ = self.dialog(['Ada', 'evet', 'cümle'])
        identity.profile_named.return_value = {'id': 'a', 'name': 'Ada'}
        identity.verify_claim.return_value = False
        self.assertIsNone(await dialog.run(mode='update'))
        identity.enroll_samples.assert_not_called()

    async def test_cancel_update_keeps_old_profile(self):
        dialog, identity, _ = self.dialog(['Ada', 'evet', 'cümle', 'evet', 'ses', None])
        identity.profile_named.return_value = {'id': 'a', 'name': 'Ada'}
        identity.verify_claim.return_value = True
        self.assertIsNone(await dialog.run(mode='update'))
        identity.enroll_samples.assert_not_called()

    async def test_existing_mismatch_does_not_overwrite(self):
        dialog, identity, _ = self.dialog(['Ada', 'evet', 'cümle', 'hayır'])
        identity.profile_named.return_value = {'id': 'a', 'name': 'Ada'}
        identity.verify_claim.return_value = False
        self.assertIsNone(await dialog.run())
        identity.enroll_samples.assert_not_called()

    async def test_cancel_partial_enrollment_saves_nothing(self):
        dialog, identity, _ = self.dialog(['Ada', 'evet', 'evet', 'ses', None])
        self.assertIsNone(await dialog.run())
        identity.enroll_samples.assert_not_called()

    async def test_rejected_name_is_asked_again_then_correct_name_saved(self):
        dialog, identity, _ = self.dialog(['Yanlış', 'hayır', 'Ada', 'evet', 'evet'] + ['ses'] * 6)
        self.assertEqual(await dialog.run(), 'Ada')
        self.assertEqual(identity.enroll_samples.call_args.args[0], 'Ada')
        self.assertIn('tekrar', dialog.listen.call_args_list[2].args[0])

    async def test_name_not_confirmed_saves_nothing(self):
        dialog, identity, _ = self.dialog(['Yanlış', 'hayır', None])
        self.assertIsNone(await dialog.run())
        identity.enroll_samples.assert_not_called()
