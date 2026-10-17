import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from config import WAKE, SPEECH
from services.wake import _wait_for_wake_word, _acknowledge_wake


class MusicWakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_wake_acknowledgement_is_audible_also_for_music_flow(self):
        speech = MagicMock()
        with patch.dict(SPEECH, {'WAKE_RESPONSE_PAUSE': 0}):
            await _acknowledge_wake(speech)
        speech.say_local.assert_called_once_with(SPEECH['WAKE_RESPONSE'])

    async def test_wake_greets_matching_profile_by_name(self):
        speech, identity = MagicMock(), MagicMock()
        identity.status.side_effect = [
            {'busy': True, 'wake_match': None},
            {'busy': False, 'wake_match': {'name': 'Hüseyin'}}]
        with patch.dict(SPEECH, {'WAKE_RESPONSE_PAUSE': 0}):
            await _acknowledge_wake(speech, identity)
        speech.say_local.assert_called_once_with('Efendim, Hüseyin?')

    async def test_unknown_voice_keeps_generic_greeting(self):
        speech, identity = MagicMock(), MagicMock()
        identity.status.return_value = {'busy': False, 'wake_match': None}
        with patch.dict(SPEECH, {'WAKE_RESPONSE_PAUSE': 0}):
            await _acknowledge_wake(speech, identity)
        speech.say_local.assert_called_once_with(SPEECH['WAKE_RESPONSE'])

    async def listen(self, scores, consecutive=None, music_playing=True):
        listener = MagicMock()
        listener.listen_once = AsyncMock(side_effect=[({'hey_jarvis': score}, {}) for score in scores])
        music = MagicMock()
        music.is_playing.return_value = music_playing
        with patch.dict(WAKE, {'MUSIC_CONSECUTIVE_DETECTIONS': consecutive or WAKE['MUSIC_CONSECUTIVE_DETECTIONS'], 'CONSECUTIVE_DETECTIONS': consecutive or WAKE['CONSECUTIVE_DETECTIONS'], 'LOG_SCORE_INTERVAL_SECONDS': 0}):
            with patch('services.wake.SpeechService.is_speaking', return_value=False):
                score, _ = await _wait_for_wake_word(listener, music, 0)
        return score, listener.listen_once.await_count

    async def test_wake_requires_two_strong_frames_with_and_without_music(self):
        for playing in (True, False):
            score, count = await self.listen([0.36, 0.37], music_playing=playing)
            self.assertEqual(score, 0.37)
            self.assertEqual(count, 2)

    async def test_music_threshold_is_lower_than_normal(self):
        self.assertLess(WAKE['MUSIC_THRESHOLD'], WAKE['THRESHOLD'])
        _, music_count = await self.listen([0.32, 0.33, 0.40, 0.45], music_playing=True)
        _, normal_count = await self.listen([0.32, 0.33, 0.40, 0.45], music_playing=False)
        self.assertEqual(music_count, 2)
        self.assertEqual(normal_count, 3)

    async def test_strong_single_scores_are_accepted(self):
        for peak in (0.642, 0.772):
            score, count = await self.listen([peak], music_playing=False)
            self.assertEqual(score, peak)
            self.assertEqual(count, 1)
        _, count = await self.listen([0.52], music_playing=True)
        self.assertEqual(count, 1)

    async def test_short_peak_with_weaker_neighbor_is_accepted(self):
        for scores in ([0.39, 0.23], [0.23, 0.39]):
            score, count = await self.listen(scores, music_playing=False)
            self.assertEqual(score, 0.39)
            self.assertEqual(count, 2)

    async def test_weak_scores_alone_are_not_enough(self):
        _, count = await self.listen([0.22, 0.23, 0.24, 0.4], music_playing=False)
        self.assertEqual(count, 4)

    async def test_observed_tv_scores_do_not_trigger(self):
        score, count = await self.listen([0.28297, 0.01, 0.48173, 0.01, 0.36, 0.37])
        self.assertEqual(score, 0.37)
        self.assertEqual(count, 6)

    async def test_isolated_high_spike_does_not_trigger(self):
        _, count = await self.listen([0.48, 0.1, 0.36, 0.37])
        self.assertEqual(count, 4)

    async def test_consecutive_hit_count_resets_after_low_score(self):
        _, count = await self.listen([0.36, 0.10, 0.36, 0.37], consecutive=2)
        self.assertEqual(count, 4)


if __name__ == '__main__':
    unittest.main()
