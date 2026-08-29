let pc = null;
let starting = false;
let localStream = null;

function resetWebRTC() {

    if (localStream) {
        localStream.getTracks()
            .forEach((track) => track.stop());

        localStream = null;
    }

    if (pc) {
        pc.close();
        pc = null;
    }

    const video = document.getElementById(
        "remoteVideo"
    );

    const audio = document.getElementById(
        "remoteAudio"
    );

    if (video) {
        video.srcObject = null;
    }

    if (audio) {
        audio.srcObject = null;
    }

    starting = false;
    updateWebRTCButton(false);
}

function updateWebRTCButton(connected) {

    const connectButton = document.getElementById(
        "connectButton"
    );

    if (!connectButton) {
        return;
    }

    connectButton.textContent = connected
        ? "Kamerayı Durdur"
        : "Kamerayı Başlat";
}

function stopWebRTC() {

    setStatus("Kamera durduruldu");
    resetWebRTC();
}

function applyRemoteAudioVolume() {

    const audio = document.getElementById(
        "remoteAudio"
    );

    const volume = document.getElementById(
        "remoteAudioVolume"
    );

    const valueLabel = document.getElementById(
        "remoteAudioVolumeValue"
    );

    if (!audio || !volume) {
        return;
    }

    const value = Math.max(
        0,
        Math.min(
            100,
            Number(volume.value)
        )
    );

    audio.muted = value === 0;
    audio.volume = value / 100;

    if (valueLabel) {
        valueLabel.textContent = value + "%";
    }
}

window.addEventListener(
    "load",
    () => {
        const volume = document.getElementById(
            "remoteAudioVolume"
        );

        if (volume) {
            volume.addEventListener(
                "input",
                applyRemoteAudioVolume
            );
            applyRemoteAudioVolume();
        }
    }
);

function toggleWebRTC() {

    if (pc || starting) {
        stopWebRTC();
        return;
    }

    startWebRTC()
        .catch((error) => {
            console.error(
                "WebRTC start failed",
                error
            );
            setStatus("Kamera baslatilamadi");
            resetWebRTC();
        });
}

function describeMicrophoneError(error) {

    if (!window.isSecureContext) {
        return "Mikrofon icin HTTPS gerekli";
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        return "Mikrofon icin Chrome'da HTTPS veya izinli origin gerekli";
    }

    if (error.name === "NotAllowedError") {
        return "Mikrofon izni verilmedi";
    }

    if (error.name === "NotFoundError") {
        return "Mikrofon bulunamadi";
    }

    if (error.name === "NotReadableError") {
        return "Mikrofon baska uygulama tarafindan kullaniliyor";
    }

    return "Mikrofon acilamadi: " + error.name;
}

async function startWebRTC() {

    if (starting) {
        console.log("Already starting...");
        return;
    }

    if (
        pc &&
        [
            "closed",
            "disconnected",
            "failed"
        ].includes(pc.connectionState)
    ) {
        resetWebRTC();
    }

    if (pc) {
        console.log("Already connected...");
        return;
    }

    starting = true;
    updateWebRTCButton(false);

    setStatus("WebRTC baslatiliyor");

    let microphoneStatus = "Mikrofon acik";

    console.log("Creating PeerConnection");

    pc = new RTCPeerConnection();

    pc.onconnectionstatechange = () => {

        if (!pc) {
            return;
        }

        console.log(
            "WEBRTC STATE:",
            pc.connectionState
        );

        if (
            [
                "closed",
                "disconnected",
                "failed"
            ].includes(pc.connectionState)
        ) {
            setStatus("WebRTC koptu");
            resetWebRTC();
        }
    };

    const remoteVideoStream =
        new MediaStream();

    const remoteAudioStream =
        new MediaStream();

    const video =
        document.getElementById(
            "remoteVideo"
        );

    const audio =
        document.getElementById(
            "remoteAudio"
        );

    video.srcObject =
        remoteVideoStream;

    audio.srcObject =
        remoteAudioStream;
    applyRemoteAudioVolume();

    pc.ontrack =
        (event) => {

            console.log(
                "TRACK:",
                event.track.kind
            );

            if (event.track.kind === "video") {
                remoteVideoStream.addTrack(
                    event.track
                );

                video.play()
                    .then(() =>
                        console.log(
                            "VIDEO PLAYING"
                        )
                    )
                    .catch(console.error);
            }

            if (event.track.kind === "audio") {
                const receiver = pc.getReceivers()
                    .find((item) => item.track === event.track);

                if (
                    receiver &&
                    "jitterBufferTarget" in receiver
                ) {
                    receiver.jitterBufferTarget = 0.05;
                }

                remoteAudioStream.addTrack(
                    event.track
                );

                audio.play()
                    .then(() =>
                        console.log(
                            "AUDIO PLAYING"
                        )
                    )
                    .catch(console.error);
            }
        };

    try {
        localStream =
            await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                },
                video: false
            });

        localStream.getAudioTracks()
            .forEach((track) => {
                pc.addTrack(
                    track,
                    localStream
                );
            });

        console.log(
            "Local microphone added",
            localStream.getAudioTracks()
                .map((track) => track.label)
        );

        setStatus("Mikrofon acik");

    } catch (error) {
        console.warn(
            "Microphone not available",
            error
        );

        microphoneStatus = describeMicrophoneError(error);

        setStatus(
            microphoneStatus
        );

        pc.addTransceiver(
            "audio",
            {
                direction:
                    "recvonly"
            }
        );
    }

    console.log(
        "Adding video transceiver"
    );

    pc.addTransceiver(
        "video",
        {
            direction:
                "recvonly"
        }
    );

    console.log(
        "Creating offer"
    );

    const offer =
        await pc.createOffer();

    console.log(
        "Setting local description"
    );

    await pc.setLocalDescription(
        offer
    );

    console.log(
        "Sending offer"
    );

    const response =
        await fetch(
            "/offer",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body:
                    JSON.stringify({
                        sdp:
                            offer.sdp,
                        type:
                            offer.type
                    })
            }
        );

    const answer =
        await response.json();

    console.log(
        "Setting remote description"
    );

    await pc.setRemoteDescription(
        answer
    );

    console.log(
        "WebRTC connected"
    );

    if (microphoneStatus === "Mikrofon acik") {
        setStatus("WebRTC baglandi");
    } else {
        setStatus(microphoneStatus);
    }

    starting = false;
    updateWebRTCButton(true);
}