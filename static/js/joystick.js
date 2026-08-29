let driveSocket = null;
let joystickActive = false;
let joystickRect = null;
const pressedKeys = new Set();

const keyDirections = {
	ArrowUp: [0, 1],
	ArrowDown: [0, -1],
	ArrowLeft: [-1, 0],
	ArrowRight: [1, 0]
};

function connectDriveSocket() {

	if (
		driveSocket
		&& driveSocket.readyState === WebSocket.OPEN
	) {
		return;
	}

	const protocol =
		window.location.protocol === "https:"
			? "wss"
			: "ws";

	driveSocket = new WebSocket(
		`${protocol}://${window.location.host}/ws/drive`
	);

	driveSocket.onopen = () => {
		setStatus("Joystick baglandi");
	};

	driveSocket.onclose = () => {
		setStatus("Joystick kapandi");
		setTimeout(
			connectDriveSocket,
			1000
		);
	};
}

function setStatus(message) {

	const status = document.getElementById(
		"status"
	);

	if (status) {
		status.textContent = message;
	}
}

function sendDrive(x, y) {

	if (
		!driveSocket
		|| driveSocket.readyState !== WebSocket.OPEN
	) {
		return;
	}

	driveSocket.send(
		JSON.stringify({
			// omega isareti S3'un kendi joystick'iyle (omega=-dx) eslesecek sekilde cevrilir
			x: -x,
			y
		})
	);
}

function moveStick(x, y) {

	const joystick = document.getElementById(
		"joystick"
	);

	const stick = document.getElementById(
		"stick"
	);

	if (!joystick || !stick) {
		return;
	}

	const rect = joystick.getBoundingClientRect();
	const stickTravel = (
		rect.width
		- stick.offsetWidth
	) / 2;

	stick.style.transform =
		`translate(${x * stickTravel}px, ${-y * stickTravel}px)`;
}

function updateKeyboardDrive() {

	let x = 0;
	let y = 0;

	pressedKeys.forEach((key) => {
		const direction = keyDirections[key];

		if (!direction) {
			return;
		}

		x += direction[0];
		y += direction[1];
	});

	const length = Math.hypot(
		x,
		y
	);

	if (length > 1) {
		x /= length;
		y /= length;
	}

	moveStick(
		x,
		y
	);

	sendDrive(
		x * 100,
		y * 100
	);
}

function isEditableTarget(target) {

	return (
		target &&
		[
			"INPUT",
			"TEXTAREA",
			"SELECT"
		].includes(target.tagName)
	);
}

function updateStick(clientX, clientY) {

	const joystick = document.getElementById(
		"joystick"
	);

	const stick = document.getElementById(
		"stick"
	);

	if (!joystick || !stick || !joystickRect) {
		return;
	}

	const centerX = joystickRect.left + joystickRect.width / 2;
	const centerY = joystickRect.top + joystickRect.height / 2;
	const radius = joystickRect.width / 2;
	const stickTravel = (
		joystickRect.width
		- stick.offsetWidth
	) / 2;

	let x = (clientX - centerX) / radius;
	let y = (centerY - clientY) / radius;

	const length = Math.hypot(
		x,
		y
	);

	if (length > 1) {
		x /= length;
		y /= length;
	}

	stick.style.transform =
		`translate(${x * stickTravel}px, ${-y * stickTravel}px)`;

	sendDrive(
		x * 100,
		y * 100
	);
}

function stopStick() {

	joystickActive = false;

	const stick = document.getElementById(
		"stick"
	);

	if (stick) {
		moveStick(
			0,
			0
		);
	}

	sendDrive(
		0,
		0
	);
}

window.addEventListener(
	"load",
	() => {

		connectDriveSocket();

		const joystick = document.getElementById(
			"joystick"
		);

		if (!joystick) {
			return;
		}

		joystick.addEventListener(
			"pointerdown",
			(event) => {
				joystickActive = true;
				joystickRect = joystick.getBoundingClientRect();
				joystick.setPointerCapture(
					event.pointerId
				);
				updateStick(
					event.clientX,
					event.clientY
				);
			}
		);

		joystick.addEventListener(
			"pointermove",
			(event) => {
				if (!joystickActive) {
					return;
				}

				updateStick(
					event.clientX,
					event.clientY
				);
			}
		);

		joystick.addEventListener(
			"pointerup",
			stopStick
		);

		joystick.addEventListener(
			"pointercancel",
			stopStick
		);

		window.addEventListener(
			"keydown",
			(event) => {
				if (
					isEditableTarget(event.target) ||
					!(event.key in keyDirections)
				) {
					return;
				}

				event.preventDefault();

				if (pressedKeys.has(event.key)) {
					return;
				}

				pressedKeys.add(event.key);
				updateKeyboardDrive();
			}
		);

		window.addEventListener(
			"keyup",
			(event) => {
				if (!(event.key in keyDirections)) {
					return;
				}

				event.preventDefault();
				pressedKeys.delete(event.key);
				updateKeyboardDrive();
			}
		);

		window.addEventListener(
			"blur",
			() => {
				pressedKeys.clear();
				updateKeyboardDrive();
			}
		);
	}
);
