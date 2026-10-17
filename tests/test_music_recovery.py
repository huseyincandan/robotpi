import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import wave

from config import MUSIC, RADIO
from services.music import MusicService
from services.music_player import AttachedPlayer, ipc_request


class ProcessIdentityTests(unittest.TestCase):
    def test_reused_pid_is_not_signalled(self):
        with patch('services.music_player.process_info', side_effect=[('S', 'old', ['mpv']), ('S', 'new', ['other'])]):
            player = AttachedPlayer(123)
            with patch('services.music_player.os.kill') as kill:
                player.terminate()
                kill.assert_not_called()


@unittest.skipUnless(shutil.which('mpv'), 'requires installed mpv')
class MusicRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.config = patch.dict(MUSIC, {
            'IPC_SOCKET': str(self.directory / 'player.sock'),
            'STATE_FILE': str(self.directory / 'state.json'),
            'LOG_FILE': str(self.directory / 'mpv.log'),
            'AUDIO_DEVICE': 'auto',
            'PLAYER_ARGS': ['--ao=null', '--loop-file=inf'],
        })
        self.config.start()
        self.addCleanup(self.config.stop)
        radio = patch.dict(RADIO, {'CONNECT_CHECK_SECONDS': 0.1})
        radio.start()
        self.addCleanup(radio.stop)
        volume = patch('services.music.get_speaker_volume', return_value=35)
        volume.start()
        self.addCleanup(volume.stop)
        self.wav = self.directory / 'silence.wav'
        with wave.open(str(self.wav), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b'\0\0' * 16000)
        self.first = MusicService()
        self.first.playlist_urls = [str(self.wav), str(self.directory / 'second.wav')]
        shutil.copyfile(self.wav, self.first.playlist_urls[1])
        self.first.playlist_names = ['First station', 'Second station']
        self.first._start_player([str(self.wav)])
        self.addCleanup(self.first.stop)

    def test_new_service_reattaches_without_restarting_player_and_can_control_it(self):
        pid = self.first.process.pid
        self.first.set_volume(42)
        self.assertTrue(self.first.pause())
        second = MusicService()
        self.addCleanup(second.stop)
        self.assertEqual(second.process.pid, pid)
        self.assertTrue(second.is_playing())
        self.assertEqual(second.volume, 42)
        self.assertEqual(second.playlist_names, ['First station', 'Second station'])
        self.assertTrue(ipc_request(second.ipc_path, ['get_property', 'pause']))
        self.assertTrue(second.resume())
        self.assertFalse(ipc_request(second.ipc_path, ['get_property', 'pause']))
        self.assertTrue(second.stop())
        self.assertFalse(second.is_playing())
        self.assertFalse(second.state_file.exists())
        self.assertFalse(second.ipc_path.exists())

    def test_playlist_survives_restart_and_next_previous_still_work(self):
        second = MusicService()
        self.addCleanup(second.stop)
        self.assertTrue(second.next())
        self.assertEqual(second.playlist_index, 1)
        third = MusicService()
        self.addCleanup(third.stop)
        self.assertEqual(third.playlist_index, 1)
        self.assertTrue(third.previous())
        self.assertEqual(third.playlist_index, 0)
        state = json.loads(third.state_file.read_text())
        self.assertEqual(state['playlist_index'], 0)

    def test_corrupt_state_does_not_hide_live_player(self):
        self.first.state_file.write_text('broken json')
        second = MusicService()
        self.addCleanup(second.stop)
        self.assertTrue(second.is_playing())
        self.assertEqual(second.process.pid, self.first.process.pid)
        self.assertEqual(second.playlist_urls, [str(self.wav)])

    def test_dead_pid_in_state_is_not_treated_as_playing(self):
        self.first.stop()
        self.first.state_file.write_text(json.dumps({'pid': 99999999, 'playlist_urls': [str(self.wav)]}))
        second = MusicService()
        self.assertFalse(second.is_playing())


if __name__ == '__main__':
    unittest.main()
