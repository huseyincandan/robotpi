import asyncio
import site
import cv2
import av
from fractions import Fraction

from config import AUDIO
from config import CAMERA

from aiortc import (
    AudioStreamTrack,
    RTCPeerConnection,
    RTCSessionDescription,
    VideoStreamTrack
)
from aiortc.mediastreams import MediaStreamError

pcs = set()
audio_players = set()
audio_recorders = set()
speaker_active_until = 0.0


async def close_existing_sessions():

    for microphone in list(audio_players):
        microphone.stop()
        audio_players.discard(
            microphone
        )

    for process in list(audio_recorders):
        audio_recorders.discard(
            process
        )

        if process.stdin:
            process.stdin.close()

        if process.returncode is None:
            process.terminate()

            try:
                await asyncio.wait_for(
                    process.wait(),
                    timeout=1
                )

            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

    for peer in list(pcs):
        await peer.close()
        pcs.discard(
            peer
        )

    await asyncio.to_thread(close_camera)

#################################################
# KAMERA
#################################################

camera = None


def get_camera():
    global camera

    if camera is not None:
        return camera

    # libcamera's native bindings are supplied by Raspberry Pi OS, not PyPI.
    site.addsitedir("/usr/lib/python3/dist-packages")
    from picamera2 import Picamera2

    device = Picamera2()
    try:
        device.configure(
            device.create_video_configuration(
                main={
                    "size": (CAMERA["WIDTH"], CAMERA["HEIGHT"]),
                    # Picamera2 RGB888 arrays have BGR byte order for OpenCV.
                    "format": "RGB888"
                },
                controls={"FrameRate": CAMERA["FPS"]},
                buffer_count=2,
                queue=False
            )
        )
        device.start()
    except Exception:
        device.close()
        raise

    camera = device

    print(
        "PI CAMERA OPEN:",
        CAMERA["WIDTH"],
        CAMERA["HEIGHT"],
        CAMERA["FPS"],
        "rotation CCW:",
        CAMERA["ROTATION_CCW_DEGREES"]
    )

    return camera


def close_camera():
    global camera

    device = camera
    camera = None
    if device is not None:
        try:
            device.stop()
        finally:
            device.close()

#################################################
# VIDEO TRACK
#################################################

class CameraTrack(VideoStreamTrack):

    def __init__(
        self,
        camera
    ):
        super().__init__()

        self.camera = camera
        self.frame_count = 0
        self.first_sensor_timestamp = None
        rotation = CAMERA["ROTATION_CCW_DEGREES"]
        rotations = {
            0: None,
            90: cv2.ROTATE_90_COUNTERCLOCKWISE,
            180: cv2.ROTATE_180,
            270: cv2.ROTATE_90_CLOCKWISE
        }
        if rotation not in rotations:
            raise ValueError("CAMERA.ROTATION_CCW_DEGREES must be 0, 90, 180 or 270")
        self.rotation = rotations[rotation]

    def capture_frame(self):
        with self.camera.captured_request() as request:
            return (
                request.make_array("main"),
                request.get_metadata()["SensorTimestamp"]
            )

    async def recv(self):
        if self.readyState != "live":
            raise MediaStreamError

        try:
            frame, sensor_timestamp = await asyncio.to_thread(self.capture_frame)
        except RuntimeError as exc:
            print("PI CAMERA READ FAILED:", exc, flush=True)
            self.stop()
            raise MediaStreamError from exc

        if self.rotation is not None:
            frame = cv2.rotate(frame, self.rotation)

        if self.first_sensor_timestamp is None:
            self.first_sensor_timestamp = sensor_timestamp

        pts = (sensor_timestamp - self.first_sensor_timestamp) * 90000 // 1_000_000_000

        self.frame_count += 1

        video_frame = (
            av.VideoFrame.from_ndarray(
                frame,
                format="bgr24"
            )
        )

        video_frame.pts = pts
        video_frame.time_base = (
            Fraction(1, 90000)
        )

        return video_frame


#################################################
# LOW LATENCY AUDIO TRACK
#################################################

class LiveMicrophoneTrack(AudioStreamTrack):

    def __init__(self):
        super().__init__()

        self.process = None
        self.reader_task = None
        self.queue = asyncio.Queue(
            maxsize=1
        )
        self.sample_rate = int(
            AUDIO["SAMPLE_RATE"]
        )
        self.channels = int(
            AUDIO["CHANNELS"]
        )
        self.samples = int(
            AUDIO["MICROPHONE_FRAME_SAMPLES"]
        )
        self.bytes_per_sample = 2
        self.pts = 0

    async def _ensure_process(self):

        if self.process:
            return

        self.process = await asyncio.create_subprocess_exec(
            "arecord",
            "--quiet",
            "--file-type",
            "raw",
            "--device",
            AUDIO["MICROPHONE_DEVICE"],
            "--format",
            "S16_LE",
            "--rate",
            AUDIO["SAMPLE_RATE"],
            "--channels",
            AUDIO["CHANNELS"],
            "--buffer-size",
            AUDIO["MICROPHONE_BUFFER_SIZE"],
            "--period-size",
            AUDIO["MICROPHONE_PERIOD_SIZE"],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )

        self.reader_task = asyncio.create_task(
            self._read_latest_frames()
        )

    def _push_latest_frame(
        self,
        data
    ):

        while not self.queue.empty():
            try:
                self.queue.get_nowait()

            except asyncio.QueueEmpty:
                break

        try:
            self.queue.put_nowait(
                data
            )

        except asyncio.QueueFull:
            pass

    async def _read_latest_frames(self):

        byte_count = (
            self.samples *
            self.channels *
            self.bytes_per_sample
        )

        try:
            while self.readyState == "live":
                data = await self.process.stdout.readexactly(
                    byte_count
                )

                self._push_latest_frame(
                    data
                )

        except Exception:
            self._push_latest_frame(
                None
            )

    async def recv(self):

        await self._ensure_process()

        data = await self.queue.get()

        if data is None:
            raise MediaStreamError

        if (
            AUDIO.get(
                "MUTE_ROBOT_MIC_WHILE_SPEAKER_ACTIVE",
                True
            ) and
            asyncio.get_running_loop().time() < speaker_active_until
        ):
            data = bytes(
                len(data)
            )

        frame = av.AudioFrame(
            format="s16",
            layout="mono",
            samples=self.samples
        )

        frame.planes[0].update(
            data
        )

        frame.sample_rate = self.sample_rate
        frame.pts = self.pts
        frame.time_base = Fraction(
            1,
            self.sample_rate
        )

        self.pts += self.samples

        return frame

    def stop(self):

        super().stop()

        if self.reader_task:
            self.reader_task.cancel()

        if self.process and self.process.returncode is None:
            self.process.terminate()


#################################################
# WEBRTC
#################################################

async def create_answer(
    offer_sdp,
    offer_type
):

    await close_existing_sessions()

    camera_device = await asyncio.to_thread(get_camera)

    pc = RTCPeerConnection()
    microphone = None
    closed = False

    pcs.add(pc)

    print(
        "Peer count:",
        len(pcs)
    )

    async def cleanup_peer():
        nonlocal closed

        if closed:
            return

        closed = True

        if microphone:
            microphone.stop()

            audio_players.discard(
                microphone
            )

        pcs.discard(
            pc
        )

        if not pcs:
            await asyncio.to_thread(close_camera)

        print(
            "Peer count:",
            len(pcs)
        )

    @pc.on(
        "connectionstatechange"
    )
    async def on_state():

        print(
            "WEBRTC STATE:",
            pc.connectionState
        )

        if (
            pc.connectionState
            in
            [
                "failed",
                "closed",
                "disconnected"
            ]
        ):

            await pc.close()
            await cleanup_peer()

    @pc.on("iceconnectionstatechange")
    async def on_ice():

        print(
            "ICE STATE:",
            pc.iceConnectionState
        )

    @pc.on("track")
    def on_track(track):

        print(
            "REMOTE TRACK:",
            track.kind
        )

        if (
            track.kind == "audio" and
            AUDIO.get("ENABLED", True) and
            AUDIO.get(
                "PLAY_BROWSER_AUDIO_ON_ROBOT",
                False
            )
        ):
            asyncio.create_task(
                play_remote_audio(
                    track
                )
            )

        elif track.kind == "audio":
            print(
                "REMOTE AUDIO PLAYBACK DISABLED"
            )

    #################################################
    # VIDEO
    #################################################

    pc.addTrack(
        CameraTrack(
            camera_device
        )
    )

    print("VIDEO TRACK ADDED")

    if AUDIO.get("ENABLED", True):
        try:
            microphone = LiveMicrophoneTrack()

            audio_players.add(
                microphone
            )

            pc.addTrack(
                microphone
            )

            print(
                "AUDIO TRACK ADDED"
            )

        except Exception as exc:
            print(
                "AUDIO INPUT FAILED:",
                exc
            )

    else:
        print(
            "AUDIO TRACK SKIPPED (AUDIO.ENABLED=False)"
        )

    #################################################
    # SDP
    #################################################

    offer = RTCSessionDescription(
        sdp=offer_sdp,
        type=offer_type
    )

    await pc.setRemoteDescription(
        offer
    )

    answer = (
        await pc.createAnswer()
    )

    await pc.setLocalDescription(
        answer
    )

    print(
        "ANSWER CREATED"
    )

    return {
        "sdp":
            pc.localDescription.sdp,
        "type":
            pc.localDescription.type
    }


async def play_remote_audio(
    track
):

    global speaker_active_until

    process = None
    resampler = av.AudioResampler(
        format="s16",
        layout="mono",
        rate=int(AUDIO["SAMPLE_RATE"])
    )

    try:
        process = await asyncio.create_subprocess_exec(
            "aplay",
            "--quiet",
            "--file-type",
            "raw",
            "--device",
            AUDIO["SPEAKER_DEVICE"],
            "--format",
            "S16_LE",
            "--rate",
            AUDIO["SAMPLE_RATE"],
            "--channels",
            AUDIO["CHANNELS"],
            "--buffer-size",
            AUDIO["SPEAKER_BUFFER_SIZE"],
            "--period-size",
            AUDIO["SPEAKER_PERIOD_SIZE"],
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )

        audio_recorders.add(
            process
        )

        print(
            "REMOTE AUDIO STARTED"
        )

        while track.readyState == "live":
            frame = await track.recv()

            audio_frames = resampler.resample(frame)

            if not audio_frames:
                continue

            for audio_frame in audio_frames:
                audio_data = audio_frame.to_ndarray()

                if (
                    AUDIO.get(
                        "MUTE_ROBOT_MIC_WHILE_SPEAKER_ACTIVE",
                        True
                    ) and
                    float(abs(audio_data).mean()) >= AUDIO.get(
                        "REMOTE_AUDIO_ECHO_GUARD_LEVEL",
                        300
                    )
                ):
                    speaker_active_until = (
                        asyncio.get_running_loop().time() +
                        AUDIO.get(
                            "REMOTE_AUDIO_ECHO_GUARD_HOLD_SECONDS",
                            0.25
                        )
                    )

                process.stdin.write(
                    audio_data.tobytes()
                )

            await process.stdin.drain()

    except MediaStreamError:
        pass

    except Exception as exc:
        print(
            "AUDIO OUTPUT FAILED:",
            exc
        )

    finally:
        if process:
            audio_recorders.discard(
                process
            )

            if process.stdin:
                process.stdin.close()

                try:
                    await process.stdin.wait_closed()

                except Exception:
                    pass

            if process.returncode is None:
                process.terminate()

                try:
                    await asyncio.wait_for(
                        process.wait(),
                        timeout=1
                    )

                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

            print("REMOTE AUDIO STOPPED")