import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from aiortc.mediastreams import MediaStreamError
from services import webrtc


class CameraLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.camera_patch = patch.object(webrtc, "camera", None)
        self.camera_patch.start()
        self.addCleanup(self.camera_patch.stop)

    def test_opens_picamera_with_bgr_compatible_format_and_reuses_it(self):
        device = MagicMock()
        module = MagicMock()
        module.Picamera2.return_value = device
        with patch.object(webrtc.site, "addsitedir") as addsite:
            with patch.dict("sys.modules", {"picamera2": module}):
                self.assertIs(webrtc.get_camera(), device)
                self.assertIs(webrtc.get_camera(), device)
        addsite.assert_called_once_with("/usr/lib/python3/dist-packages")
        module.Picamera2.assert_called_once_with()
        device.create_video_configuration.assert_called_once_with(
            main={"size": (320, 240), "format": "RGB888"},
            controls={"FrameRate": 15},
            buffer_count=2,
            queue=False
        )
        device.start.assert_called_once_with()
        webrtc.close_camera()
        device.stop.assert_called_once_with()
        device.close.assert_called_once_with()
        self.assertIsNone(webrtc.camera)

    def test_start_failure_closes_device_and_propagates_error(self):
        module = MagicMock()
        device = module.Picamera2.return_value
        device.start.side_effect = RuntimeError("sensor failed")
        with patch.object(webrtc.site, "addsitedir"):
            with patch.dict("sys.modules", {"picamera2": module}):
                with self.assertRaisesRegex(RuntimeError, "sensor failed"):
                    webrtc.get_camera()
        device.close.assert_called_once_with()
        self.assertIsNone(webrtc.camera)

    def test_close_releases_device_even_if_stop_fails(self):
        device = MagicMock()
        device.stop.side_effect = RuntimeError("stop failed")
        webrtc.camera = device
        with self.assertRaisesRegex(RuntimeError, "stop failed"):
            webrtc.close_camera()
        device.close.assert_called_once_with()
        self.assertIsNone(webrtc.camera)


class CameraTrackTests(unittest.IsolatedAsyncioTestCase):
    def make_camera(self, frames, timestamps):
        camera = MagicMock()
        request = camera.captured_request.return_value.__enter__.return_value
        request.make_array.side_effect = frames
        request.get_metadata.side_effect = [
            {"SensorTimestamp": timestamp} for timestamp in timestamps
        ]
        return camera

    async def test_rotates_pixels_counterclockwise_and_preserves_bgr_colors(self):
        frame = np.array([
            [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
            [[10, 11, 12], [13, 14, 15], [16, 17, 18]]
        ], dtype=np.uint8)
        camera = self.make_camera([frame], [1_000_000_000])
        with patch.dict(webrtc.CAMERA, {"ROTATION_CCW_DEGREES": 90}):
            track = webrtc.CameraTrack(camera)
        video = await track.recv()
        np.testing.assert_array_equal(
            video.to_ndarray(format="bgr24"),
            np.rot90(frame)
        )
        self.assertEqual((video.width, video.height), (2, 3))
        self.assertEqual(video.pts, 0)
        self.assertEqual(track.frame_count, 1)
        track.stop()

    async def test_timestamps_follow_sensor_not_default_30fps_clock(self):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        camera = self.make_camera(
            [frame, frame, frame],
            [1_000_000_000, 1_066_666_667, 1_200_000_000]
        )
        track = webrtc.CameraTrack(camera)
        videos = [await track.recv() for _ in range(3)]
        self.assertEqual([video.pts for video in videos], [0, 6000, 18000])
        self.assertTrue(all(video.time_base.denominator == 90000 for video in videos))
        track.stop()

    async def test_read_failure_ends_track_without_recursive_retry(self):
        camera = MagicMock()
        camera.captured_request.side_effect = RuntimeError("disconnected")
        track = webrtc.CameraTrack(camera)
        with self.assertRaises(MediaStreamError):
            await track.recv()
        self.assertEqual(track.readyState, "ended")
        with self.assertRaises(MediaStreamError):
            await track.recv()
        camera.captured_request.assert_called_once_with()

    async def test_close_sessions_releases_camera(self):
        camera = MagicMock()
        with patch.object(webrtc, "camera", camera):
            await webrtc.close_existing_sessions()
            camera.stop.assert_called_once_with()
            camera.close.assert_called_once_with()
            self.assertIsNone(webrtc.camera)

    def test_rejects_invalid_rotation(self):
        with patch.dict(webrtc.CAMERA, {"ROTATION_CCW_DEGREES": 45}):
            with self.assertRaisesRegex(ValueError, "ROTATION_CCW_DEGREES"):
                webrtc.CameraTrack(MagicMock())


if __name__ == "__main__":
    unittest.main()
