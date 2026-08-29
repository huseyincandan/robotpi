window.addEventListener(
    "load",
    () => {

        const speakerVolume = document.getElementById(
            "speakerVolume"
        );

        const speakerVolumeValue = document.getElementById(
            "speakerVolumeValue"
        );

        function showSpeakerVolume(value) {

            const volume = Math.max(
                0,
                Math.min(
                    100,
                    Number(value)
                )
            );

            if (speakerVolume) {
                speakerVolume.value = String(volume);
            }

            if (speakerVolumeValue) {
                speakerVolumeValue.textContent = volume + "%";
            }
        }

        async function loadSpeakerVolume() {

            const response = await fetch(
                "/speaker-volume"
            );

            const data = await response.json();

            showSpeakerVolume(
                data.volume
            );
        }

        async function setSpeakerVolume(value) {

            showSpeakerVolume(
                value
            );

            const response = await fetch(
                "/speaker-volume?volume=" + encodeURIComponent(value),
                {
                    method: "POST"
                }
            );

            const data = await response.json();

            showSpeakerVolume(
                data.volume
            );
        }

        loadSpeakerVolume()
            .catch((error) => console.warn(
                "Speaker volume not available",
                error
            ));

        if (speakerVolume) {
            speakerVolume.addEventListener(
                "change",
                () => setSpeakerVolume(
                    speakerVolume.value
                )
            );
        }

        const connectButton = document.getElementById(
            "connectButton"
        );

        if (connectButton) {
            connectButton.addEventListener(
                "click",
                () => {
                    if (typeof toggleWebRTC !== "function") {
                        setStatus("Kamera kontrolu yuklenemedi");
                        return;
                    }

                    toggleWebRTC();
                }
            );
        }

        const wanderButton = document.getElementById(
            "wanderButton"
        );

        let wandering = false;

        function showWanderState(value) {

            wandering = Boolean(value);

            if (wanderButton) {
                wanderButton.textContent = wandering
                    ? "Gezinmeyi Durdur"
                    : "Gezinmeyi Başlat";
            }
        }

        async function loadWanderState() {

            const response = await fetch(
                "/wander/status"
            );

            const data = await response.json();

            showWanderState(
                data.wandering
            );
        }

        async function toggleWander() {

            const response = await fetch(
                wandering
                    ? "/wander/stop"
                    : "/wander/start",
                {
                    method: "POST"
                }
            );

            const data = await response.json();

            showWanderState(
                data.wandering
            );

            setStatus(
                data.message || (data.wandering ? "Gezinme başladı" : "Gezinme durdu")
            );
        }

        loadWanderState()
            .catch((error) => console.warn(
                "Wander status not available",
                error
            ));

        if (wanderButton) {
            wanderButton.addEventListener(
                "click",
                () => toggleWander()
                    .catch((error) => {
                        console.warn(
                            "Wander toggle failed",
                            error
                        );
                        setStatus("Gezinme kontrol edilemedi");
                    })
            );
        }

        const lidarCalibrateButton = document.getElementById(
            "lidarCalibrateButton"
        );

        const nav2Button = document.getElementById(
            "nav2Button"
        );

        const exploreButton = document.getElementById(
            "exploreButton"
        );

        let nav2Running = false;
        let exploreRunning = false;

        function showNav2State(state) {

            nav2Running = Boolean(state && state.nav2_running);
            exploreRunning = Boolean(state && state.explore_running);

            if (nav2Button) {
                nav2Button.textContent = nav2Running
                    ? "Nav2 Durdur"
                    : "Nav2 Baslat";
            }

            if (exploreButton) {
                exploreButton.textContent = exploreRunning
                    ? "Kesfi Durdur"
                    : "Kesfi Baslat";
            }
        }

        async function loadNav2State() {

            const response = await fetch(
                "/nav2/status"
            );

            const data = await response.json();
            showNav2State(data || {});
        }

        async function toggleNav2() {

            const response = await fetch(
                nav2Running
                    ? "/nav2/stop"
                    : "/nav2/start",
                {
                    method: "POST"
                }
            );

            const data = await response.json();
            showNav2State(data || {});

            if (data && data.status === "ERROR") {
                setStatus(data.message || "Nav2 kontrol edilemedi");
                return;
            }

            setStatus(
                data && data.message
                    ? data.message
                    : (nav2Running ? "Nav2 calisiyor" : "Nav2 durdu")
            );
        }

        async function toggleExplore() {

            const response = await fetch(
                exploreRunning
                    ? "/explore/stop"
                    : "/explore/start",
                {
                    method: "POST"
                }
            );

            const data = await response.json();
            showNav2State(data || {});

            if (data && data.status === "ERROR") {
                setStatus(data.message || "Kesif kontrol edilemedi");
                return;
            }

            setStatus(
                data && data.message
                    ? data.message
                    : (exploreRunning ? "Kesif calisiyor" : "Kesif durdu")
            );
        }

        loadNav2State()
            .catch((error) => console.warn(
                "Nav2 status not available",
                error
            ));

        if (nav2Button) {
            nav2Button.addEventListener(
                "click",
                () => toggleNav2()
                    .catch((error) => {
                        console.warn(
                            "Nav2 toggle failed",
                            error
                        );
                        setStatus("Nav2 kontrol edilemedi");
                    })
            );
        }

        if (exploreButton) {
            exploreButton.addEventListener(
                "click",
                () => toggleExplore()
                    .catch((error) => {
                        console.warn(
                            "Explore toggle failed",
                            error
                        );
                        setStatus("Kesif kontrol edilemedi");
                    })
            );
        }

        async function calibrateLidar() {

            setStatus("Lidar kalibrasyon baslatildi...");

            const response = await fetch(
                "/lidar/calibrate",
                {
                    method: "POST"
                }
            );

            if (!response.ok) {
                setStatus("Lidar kalibrasyon basarisiz oldu");
                return;
            }

            const data = await response.json();

            if (data && data.status === "OK") {
                const offset = data.applied_offset_deg;
                if (typeof offset === "number") {
                    setStatus("Lidar kalibrasyon tamamlandi (offset: " + offset.toFixed(2) + " deg)");
                } else {
                    setStatus("Lidar kalibrasyon tamamlandi");
                }
            } else {
                setStatus("Lidar kalibrasyon sonucu: " + (data && data.message ? data.message : "beklenmeyen"));
            }
        }

        if (lidarCalibrateButton) {
            lidarCalibrateButton.addEventListener(
                "click",
                () => calibrateLidar()
                    .catch((error) => {
                        console.warn(
                            "Lidar calibration failed",
                            error
                        );
                        setStatus("Lidar kalibrasyon calistirilamadi");
                    })
            );
        }

        const imuCalibrateButton = document.getElementById(
            "imuCalibrateButton"
        );

        async function calibrateImu() {

            setStatus("Jiroskop kalibrasyonu icin robotu sabit tutun...");

            const response = await fetch(
                "/imu/calibrate",
                {
                    method: "POST"
                }
            );

            if (!response.ok) {
                setStatus("Jiroskop kalibrasyonu basarisiz oldu");
                return;
            }

            const data = await response.json();

            if (data && data.status === "OK") {
                const bias = data.gyro_bias_z;
                setStatus(
                    typeof bias === "number"
                        ? "Jiroskop kalibrasyonu tamamlandi (bias: " + bias.toFixed(2) + " derece/s)"
                        : "Jiroskop kalibrasyonu tamamlandi"
                );
            } else {
                setStatus("Jiroskop kalibrasyon sonucu: " + (data && data.message ? data.message : "beklenmeyen"));
            }
        }

        if (imuCalibrateButton) {
            imuCalibrateButton.addEventListener(
                "click",
                () => calibrateImu()
                    .catch((error) => {
                        console.warn(
                            "IMU calibration failed",
                            error
                        );
                        setStatus("Jiroskop kalibrasyonu calistirilamadi");
                    })
            );
        }

        const batteryInfo = document.getElementById(
            "batteryInfo"
        );

        async function loadBatteryStatus() {

            const response = await fetch(
                "/battery/status"
            );

            if (!batteryInfo) {
                return;
            }

            if (!response.ok) {
                batteryInfo.textContent = "Pil: -";
                batteryInfo.classList.remove("battery-low");
                return;
            }

            const data = await response.json();

            if (data && data.status === "OK") {
                batteryInfo.textContent = (
                    "Pil: " + data.bus_voltage.toFixed(2) + "V / "
                    + data.battery_percent + "% / "
                    + data.current_ma.toFixed(0) + "mA"
                );
                batteryInfo.classList.toggle("battery-low", Boolean(data.low_voltage));
            } else {
                batteryInfo.textContent = "Pil: -";
                batteryInfo.classList.remove("battery-low");
            }
        }

        loadBatteryStatus()
            .catch((error) => console.warn(
                "Battery status not available",
                error
            ));

        const mapButton = document.getElementById(
            "mapButton"
        );

        const mapSection = document.getElementById(
            "mapSection"
        );

        const mapImage = document.getElementById(
            "mapImage"
        );

        const mapOverlay = document.getElementById(
            "mapOverlay"
        );

        const mapStatus = document.getElementById(
            "mapStatus"
        );

        const mapMeta = document.getElementById(
            "mapMeta"
        );

        const mapRefreshButton = document.getElementById(
            "mapRefreshButton"
        );

        const mapResetButton = document.getElementById(
            "mapResetButton"
        );

        let mapVisible = false;

        function formatMapTimestamp(value) {

            if (!value) {
                return "-";
            }

            const date = new Date(value);

            if (Number.isNaN(date.getTime())) {
                return value;
            }

            return date.toLocaleString("tr-TR", {
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit"
            });
        }

        function setMapVisible(visible) {

            mapVisible = Boolean(visible);

            if (mapSection) {
                mapSection.classList.toggle(
                    "hidden",
                    !mapVisible
                );
            }

            if (mapButton) {
                mapButton.textContent = mapVisible
                    ? "Haritayi Gizle"
                    : "Harita";
            }
        }

        async function refreshMapHealth() {

            if (!mapStatus) {
                return;
            }

            try {
                const response = await fetch(
                    "/map/health",
                    {
                        method: "GET",
                        cache: "no-store"
                    }
                );

                if (!response.ok) {
                    mapStatus.textContent = "Harita servisi durumu okunamadi.";
                    return;
                }

                const data = await response.json();

                const latestMtime = Number(data.latest_mtime);
                const mapAgeSeconds = Number.isFinite(latestMtime)
                    ? (Date.now() / 1000.0) - latestMtime
                    : null;

                if (mapMeta) {
                    if (data.latest_exists && data.latest_updated_at) {
                        mapMeta.textContent = "Son guncelleme: " + formatMapTimestamp(data.latest_updated_at);

                    } else {
                        mapMeta.textContent = "Son guncelleme: -";
                    }
                }

                if (data.lidar_ready === false) {
                    mapStatus.textContent = "LIDAR verisi zayif; harita seyrek gorunebilir.";
                    return;
                }

                if (data.latest_exists && mapAgeSeconds !== null && mapAgeSeconds > 2.5) {
                    mapStatus.textContent = "Harita degismedi (robot sabitse bu normal).";
                    return;
                }

                if (data.lidar_status && data.lidar_status !== "unknown") {
                    mapStatus.textContent = "LIDAR: " + data.lidar_status + ". Harita guncel.";
                    return;
                }

                mapStatus.textContent = data.latest_exists
                    ? "Harita yuklu."
                    : "Harita henuz olusmadi.";

            } catch (error) {
                console.warn(
                    "Map health check failed",
                    error
                );

                mapStatus.textContent = "Harita servisine ulasilamadi.";

                if (mapMeta) {
                    mapMeta.textContent = "Son guncelleme: -";
                }
            }
        }

        async function loadMapImage() {

            if (!mapImage || !mapStatus) {
                return;
            }

            mapStatus.textContent = "Harita yukleniyor...";

            const url = "/map/latest?ts=" + Date.now();

            const response = await fetch(url, {
                method: "GET",
                cache: "no-store"
            });

            if (!response.ok) {
                mapImage.removeAttribute("src");
                clearMapOverlay();
                mapStatus.textContent = "Harita bulunamadi. Harita olusturduktan sonra tekrar deneyin.";
                return;
            }

            await new Promise((resolve, reject) => {
                mapImage.onload = () => resolve();
                mapImage.onerror = () => reject(new Error("map_image_load_failed"));
                mapImage.src = url;
            });

            await drawRobotOverlay();
            mapStatus.textContent = "Guncel harita gosteriliyor.";
        }

        function clearMapOverlay() {

            if (!mapOverlay) {
                return;
            }

            const context = mapOverlay.getContext("2d");
            if (!context) {
                return;
            }

            mapOverlay.width = 1;
            mapOverlay.height = 1;
            context.clearRect(0, 0, 1, 1);
        }

        async function drawRobotOverlay() {

            if (!mapOverlay || !mapImage || !mapImage.naturalWidth || !mapImage.naturalHeight) {
                return;
            }

            let pose;
            let meta;

            try {
                const [poseResponse, metaResponse] = await Promise.all([
                    fetch("/map/pose", { cache: "no-store" }),
                    fetch("/map/meta", { cache: "no-store" })
                ]);

                if (!poseResponse.ok || !metaResponse.ok) {
                    clearMapOverlay();
                    if (mapStatus) {
                        mapStatus.textContent = "Harita var ama robot marker verisi henuz hazir degil.";
                    }
                    return;
                }

                pose = await poseResponse.json();
                meta = await metaResponse.json();

            } catch (error) {
                clearMapOverlay();
                return;
            }

            const width = Number(meta && meta.width);
            const height = Number(meta && meta.height);
            const resolution = Number(meta && meta.resolution);
            const originX = Number(meta && meta.origin && meta.origin.x);
            const originY = Number(meta && meta.origin && meta.origin.y);
            const poseX = Number(pose && pose.x);
            const poseY = Number(pose && pose.y);
            const yaw = Number(pose && pose.yaw_rad);

            if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 1 || height <= 1) {
                clearMapOverlay();
                return;
            }

            if (!Number.isFinite(resolution) || resolution <= 0) {
                clearMapOverlay();
                return;
            }

            if (!Number.isFinite(poseX) || !Number.isFinite(poseY) || !Number.isFinite(yaw)) {
                clearMapOverlay();
                return;
            }

            const mapX = (poseX - originX) / resolution;
            const mapY = (poseY - originY) / resolution;
            const pixelX = mapX;
            const pixelY = (height - 1) - mapY;

            if (!Number.isFinite(pixelX) || !Number.isFinite(pixelY)) {
                clearMapOverlay();
                return;
            }

            mapOverlay.width = mapImage.naturalWidth;
            mapOverlay.height = mapImage.naturalHeight;

            // #mapImage uses object-fit: contain, so when the box aspect ratio
            // (e.g. clipped by max-height) differs from the image's own aspect
            // ratio, the visible content is letterboxed inside the box. The
            // overlay must match that visible content rect, not the raw box,
            // otherwise the marker position/angle drift from the real map.
            const boxWidth = mapImage.clientWidth;
            const boxHeight = mapImage.clientHeight;
            const contentAspect = mapImage.naturalWidth / mapImage.naturalHeight;
            const boxAspect = boxWidth / boxHeight;

            let contentWidth = boxWidth;
            let contentHeight = boxHeight;
            let offsetLeft = 0;
            let offsetTop = 0;

            if (boxAspect > contentAspect) {
                contentWidth = boxHeight * contentAspect;
                offsetLeft = (boxWidth - contentWidth) / 2;
            } else {
                contentHeight = boxWidth / contentAspect;
                offsetTop = (boxHeight - contentHeight) / 2;
            }

            mapOverlay.style.width = contentWidth + "px";
            mapOverlay.style.height = contentHeight + "px";
            mapOverlay.style.left = offsetLeft + "px";
            mapOverlay.style.top = offsetTop + "px";

            const context = mapOverlay.getContext("2d");
            if (!context) {
                return;
            }

            context.clearRect(0, 0, mapOverlay.width, mapOverlay.height);

            const scaleX = mapOverlay.width / width;
            const scaleY = mapOverlay.height / height;
            const rawX = pixelX * scaleX;
            const rawY = pixelY * scaleY;

            const radius = Math.max(5, Math.round(Math.min(mapOverlay.width, mapOverlay.height) * 0.015));
            const margin = radius + 2;
            const x = Math.max(margin, Math.min(mapOverlay.width - margin, rawX));
            const y = Math.max(margin, Math.min(mapOverlay.height - margin, rawY));
            const arrowLength = radius * 3;
            const tipX = x + Math.cos(yaw) * arrowLength;
            const tipY = y - Math.sin(yaw) * arrowLength;

            context.strokeStyle = "rgba(0,0,0,0.65)";
            context.lineWidth = Math.max(2, Math.round(radius * 0.65));
            context.beginPath();
            context.moveTo(x, y);
            context.lineTo(tipX, tipY);
            context.stroke();

            context.strokeStyle = "#ff3b30";
            context.lineWidth = Math.max(2, Math.round(radius * 0.4));
            context.beginPath();
            context.moveTo(x, y);
            context.lineTo(tipX, tipY);
            context.stroke();

            context.fillStyle = "#ff3b30";
            context.beginPath();
            context.arc(x, y, radius, 0, Math.PI * 2);
            context.fill();

            context.strokeStyle = "#fff";
            context.lineWidth = Math.max(1, Math.round(radius * 0.25));
            context.beginPath();
            context.arc(x, y, radius, 0, Math.PI * 2);
            context.stroke();
        }

        if (mapButton) {
            mapButton.addEventListener(
                "click",
                () => {
                    const nextVisible = !mapVisible;
                    setMapVisible(nextVisible);

                    if (nextVisible) {
                        Promise.all([
                            refreshMapHealth(),
                            loadMapImage()
                        ])
                            .catch((error) => {
                                console.warn(
                                    "Map load failed",
                                    error
                                );

                                if (mapStatus) {
                                    mapStatus.textContent = "Harita yuklenemedi.";
                                }
                            });
                    }
                }
            );
        }

        if (mapRefreshButton) {
            mapRefreshButton.addEventListener(
                "click",
                () => Promise.all([
                    refreshMapHealth(),
                    loadMapImage()
                ])
                    .catch((error) => {
                        console.warn(
                            "Map refresh failed",
                            error
                        );

                        if (mapStatus) {
                            mapStatus.textContent = "Harita yenilenemedi.";
                        }
                    })
            );
        }

        if (mapResetButton) {
            mapResetButton.addEventListener(
                "click",
                async () => {
                    if (mapStatus) {
                        mapStatus.textContent = "Harita sifirlaniyor...";
                    }

                    try {
                        const response = await fetch(
                            "/map/reset",
                            {
                                method: "POST"
                            }
                        );

                        if (!response.ok) {
                            if (mapStatus) {
                                mapStatus.textContent = "Harita sifirlama basarisiz oldu.";
                            }
                            return;
                        }

                        await refreshMapHealth();
                        await loadMapImage();

                        if (mapStatus) {
                            mapStatus.textContent = "Harita sifirlandi.";
                        }

                    } catch (error) {
                        console.warn(
                            "Map reset failed",
                            error
                        );

                        if (mapStatus) {
                            mapStatus.textContent = "Harita sifirlanamadi.";
                        }
                    }
                }
            );
        }

    }
);