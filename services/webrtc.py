import asyncio
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

#################################################
# KAMERA
#################################################

camera = None


def get_camera():
    global camera

    if camera is not None:
        return camera

    device = cv2.VideoCapture(
        0,
        cv2.CAP_V4L2
    )

    if not device.isOpened():
        print(
            "CAMERA NOT AVAILABLE"
        )

        device.release()

        return None

    fourcc = CAMERA.get(
        "FOURCC"
    )

    if fourcc:
        device.set(
            cv2.CAP_PROP_FOURCC,
            cv2.VideoWriter_fourcc(*fourcc)
        )

    device.set(
        cv2.CAP_PROP_FRAME_WIDTH,
        CAMERA["WIDTH"]
    )

    device.set(
        cv2.CAP_PROP_FRAME_HEIGHT,
        CAMERA["HEIGHT"]
    )

    device.set(
        cv2.CAP_PROP_FPS,
        CAMERA["FPS"]
    )

    device.set(
        cv2.CAP_PROP_BUFFERSIZE,
        CAMERA["BUFFER_SIZE"]
    )

    camera = device

    print(
        "CAMERA OPEN:",
        camera.isOpened(),
        int(camera.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        int(camera.get(cv2.CAP_PROP_FPS)),
        fourcc
    )

    return camera

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

    async def recv(self):

        pts, time_base = (
            await self.next_timestamp()
        )

        success, frame = (
            self.camera.read()
        )

        if not success:
            print(
                "CAMERA READ FAILED"
            )

            await asyncio.sleep(
                0.05
            )

            return await self.recv()

        self.frame_count += 1

        video_frame = (
            av.VideoFrame.from_ndarray(
                frame,
                format="bgr24"
            )
        )

        video_frame.pts = pts
        video_frame.time_base = (
            time_base
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

    camera_device = get_camera()

    if camera_device:
        pc.addTrack(
            CameraTrack(
                camera_device
            )
        )

        print("VIDEO TRACK ADDED")

    else:
        print("VIDEO TRACK SKIPPED")

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