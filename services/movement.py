import re
import math
import time
import unicodedata
import statistics

from config import LIDAR
from config import MOVEMENT


class MovementService:

	def __init__(self, motor, lidar=None):

		self.motor = motor
		self.lidar = lidar

	def execute(self, text):

		command = self._parse(text)
		print(
			"MOVEMENT:",
			command,
			flush=True
		)

		if command["action"] == "stop":
			self.motor.stop()
			return "Tamam, durdum."

		if command["action"] == "forward":
			moved = self._drive_for(
				0,
				MOVEMENT["DRIVE_SPEED"],
				command["duration"]
			)

			if not moved:
				return self._forward_blocked_message()

			return "Tamam, ileri gittim."

		if command["action"] == "backward":
			self._drive_for(
				0,
				-MOVEMENT["DRIVE_SPEED"],
				command["duration"]
			)
			return "Tamam, geri gittim."

		if command["action"] == "right":
			self._drive_for(
				MOVEMENT["TURN_SPEED"],
				0,
				command["duration"]
			)
			return "Tamam, sağa döndüm."

		if command["action"] == "left":
			self._drive_for(
				-MOVEMENT["TURN_SPEED"],
				0,
				command["duration"]
			)
			return "Tamam, sola döndüm."

		return "Hareket komutunu anlayamadım."

	def _drive_for(self, x, y, duration):

		try:
			end_time = time.monotonic() + duration

			while time.monotonic() < end_time:
				if not self.motor.drive(x, y):
					return False

				time.sleep(
					MOVEMENT["SAFETY_CHECK_INTERVAL_SECONDS"]
				)

				if y > 0 and self.motor.blocked:
					return False

			if y > 0 and self.motor.blocked:
				return False

			return True

		finally:
			self.motor.stop()

	def _forward_blocked_message(self):

		if self.motor.last_block_reason == "imu":
			return "Hareket sensörü takılma algıladı, durdum."

		if self.motor.last_block_reason == "obstacle":
			return "Engel var, durdum."

		return "Güvenlik için durdum."

	def calibrate_lidar_mount(self):

		if not self.lidar:
			return {
				"status": "ERROR",
				"message": "LIDAR servisi yok"
			}

		if not self.lidar.is_ready():
			return {
				"status": "ERROR",
				"message": "LIDAR hazir degil"
			}

		self.motor.stop()

		settle_seconds = float(
			MOVEMENT.get(
				"LIDAR_CALIBRATION_SETTLE_SECONDS",
				0.35
			)
		)
		time.sleep(max(0.0, settle_seconds))

		profile_before = self._capture_lidar_profile()

		if not profile_before:
			return {
				"status": "ERROR",
				"message": "Kalibrasyon icin yeterli lidar profili alinamadi"
			}

		probe_speed = float(
			MOVEMENT.get(
				"LIDAR_CALIBRATION_FORWARD_SPEED",
				26
			)
		)
		probe_seconds = float(
			MOVEMENT.get(
				"LIDAR_CALIBRATION_FORWARD_SECONDS",
				0.65
			)
		)
		back_seconds = float(
			MOVEMENT.get(
				"LIDAR_CALIBRATION_BACK_SECONDS",
				0.7
			)
		)

		cycles = int(
			MOVEMENT.get(
				"LIDAR_CALIBRATION_CYCLES",
				4
			)
		)
		cycles = max(1, min(8, cycles))
		min_valid_cycles = int(
			MOVEMENT.get(
				"LIDAR_CALIBRATION_MIN_VALID_CYCLES",
				2
			)
		)
		min_valid_cycles = max(1, min(cycles, min_valid_cycles))
		trim_degrees = float(
			MOVEMENT.get(
				"LIDAR_CALIBRATION_TRIM_DEGREES",
				22.0
			)
		)
		min_strong_delta_cm = float(
			MOVEMENT.get(
				"LIDAR_CALIBRATION_MIN_STRONG_DELTA_CM",
				8.0
			)
		)
		max_angle_spread_deg = float(
			MOVEMENT.get(
				"LIDAR_CALIBRATION_MAX_ANGLE_SPREAD_DEG",
				28.0
			)
		)

		estimates = []
		cycle_results = []

		for cycle_index in range(cycles):
			moved_forward = self._drive_for(
				0,
				probe_speed,
				probe_seconds
			)

			time.sleep(max(0.0, settle_seconds * 0.75))
			profile_after = self._capture_lidar_profile()

			self._drive_for(
				0,
				-probe_speed,
				back_seconds
			)
			self.motor.stop()

			if not moved_forward or not profile_after:
				cycle_results.append({
					"cycle": cycle_index + 1,
					"ok": False,
					"reason": "probe_failed"
				})
				time.sleep(max(0.0, settle_seconds))
				profile_before = self._capture_lidar_profile() or profile_before
				continue

			estimate = self._estimate_front_angle_from_motion(
				profile_before,
				profile_after
			)

			if not estimate:
				cycle_results.append({
					"cycle": cycle_index + 1,
					"ok": False,
					"reason": "low_delta"
				})
				time.sleep(max(0.0, settle_seconds))
				profile_before = self._capture_lidar_profile() or profile_after
				continue

			front_angle = float(estimate["front_angle_deg"])
			best_delta = float(estimate["best_delta_cm"])

			if abs(best_delta) < max(0.5, min_strong_delta_cm):
				cycle_results.append({
					"cycle": cycle_index + 1,
					"ok": False,
					"reason": "delta_too_small",
					"best_delta_cm": round(best_delta, 2)
				})
				time.sleep(max(0.0, settle_seconds))
				profile_before = self._capture_lidar_profile() or profile_after
				continue
			weight = max(1.0, abs(best_delta))

			estimates.append({
				"angle": front_angle,
				"delta": best_delta,
				"weight": weight
			})
			cycle_results.append({
				"cycle": cycle_index + 1,
				"ok": True,
				"front_angle_deg": round(front_angle, 2),
				"best_delta_cm": round(best_delta, 2)
			})

			time.sleep(max(0.0, settle_seconds))
			profile_before = self._capture_lidar_profile() or profile_after

		if len(estimates) < min_valid_cycles:
			return {
				"status": "ERROR",
				"message": "Aci tahmini icin yeterli gecerli probe alinamadi",
				"cycles_total": cycles,
				"cycles_used": len(estimates),
				"cycle_results": cycle_results
			}

		consensus_angle = self._weighted_circular_mean(
			[(item["angle"], item["weight"]) for item in estimates]
		)

		filtered = []

		for item in estimates:
			distance = self._circular_distance_deg(
				item["angle"],
				consensus_angle
			)

			if distance <= trim_degrees:
				filtered.append(item)

		if len(filtered) >= min_valid_cycles:
			estimates = filtered

		angles = [item["angle"] for item in estimates]
		max_spread = 0.0

		for angle_a in angles:
			for angle_b in angles:
				max_spread = max(
					max_spread,
					self._circular_distance_deg(angle_a, angle_b)
				)

		if max_spread > max_angle_spread_deg:
			return {
				"status": "ERROR",
				"message": "Kalibrasyon acisi kararsiz, tekrar deneyin",
				"cycles_total": cycles,
				"cycles_used": len(estimates),
				"max_spread_deg": round(max_spread, 2),
				"cycle_results": cycle_results
			}

		target_front = self._weighted_circular_mean(
			[(item["angle"], item["weight"]) for item in estimates]
		)
		best_delta = min(item["delta"] for item in estimates)

		current_offset = float(self.lidar.get_angle_offset_deg())
		new_offset = self._normalize_degrees(
			current_offset - target_front
		)
		applied = float(
			self.lidar.set_angle_offset_deg(new_offset)
		)

		return {
			"status": "OK",
			"message": "LIDAR aci ofseti guncellendi",
			"estimated_front_angle_deg": round(target_front, 2),
			"best_delta_cm": round(float(best_delta), 2),
			"current_offset_deg": round(current_offset, 2),
			"applied_offset_deg": round(applied, 2),
			"cycles_total": cycles,
			"cycles_used": len(estimates),
			"max_spread_deg": round(max_spread, 2),
			"cycle_results": cycle_results
		}

	def _weighted_circular_mean(self, angle_weight_pairs):

		total_x = 0.0
		total_y = 0.0

		for angle_deg, weight in angle_weight_pairs:
			rad = math.radians(float(angle_deg))
			w = max(0.0001, float(weight))
			total_x += math.cos(rad) * w
			total_y += math.sin(rad) * w

		if abs(total_x) < 1e-9 and abs(total_y) < 1e-9:
			return float(angle_weight_pairs[0][0])

		angle = math.degrees(math.atan2(total_y, total_x))
		return angle % 360.0

	def _circular_distance_deg(self, a_deg, b_deg):

		diff = (float(a_deg) - float(b_deg) + 540.0) % 360.0 - 180.0
		return abs(diff)

	def _capture_lidar_profile(self):

		samples = int(
			MOVEMENT.get(
				"LIDAR_CALIBRATION_SAMPLES",
				6
			)
		)
		samples = max(2, samples)
		gap = float(
			MOVEMENT.get(
				"LIDAR_CALIBRATION_SAMPLE_GAP_SECONDS",
				0.07
			)
		)
		bin_size = float(
			MOVEMENT.get(
				"LIDAR_CALIBRATION_BIN_DEGREES",
				12
			)
		)
		bin_size = max(4.0, min(30.0, bin_size))

		bucket_values = {}

		for _ in range(samples):
			points = self.lidar.get_scan_points() or []

			for angle, distance_cm in points:
				if distance_cm < LIDAR["MIN_VALID_CM"] or distance_cm > LIDAR["MAX_VALID_CM"]:
					continue

				bin_index = int(angle / bin_size)
				center_angle = (bin_index * bin_size) + (bin_size / 2.0)
				key = round(center_angle % 360.0, 2)

				current = bucket_values.get(key)

				if current is None:
					bucket_values[key] = [distance_cm]
				else:
					current.append(distance_cm)

			time.sleep(max(0.0, gap))

		profile = {}

		for angle_key, values in bucket_values.items():
			if len(values) >= max(2, samples // 2):
				profile[angle_key] = float(statistics.median(values))

		return profile

	def _estimate_front_angle_from_motion(self, profile_before, profile_after):

		min_change_cm = float(
			MOVEMENT.get(
				"LIDAR_CALIBRATION_MIN_DELTA_CM",
				3.0
			)
		)
		max_change_cm = float(
			MOVEMENT.get(
				"LIDAR_CALIBRATION_MAX_DELTA_CM",
				60.0
			)
		)
		bin_size = float(
			MOVEMENT.get(
				"LIDAR_CALIBRATION_BIN_DEGREES",
				12
			)
		)
		bin_size = max(4.0, min(30.0, bin_size))

		deltas = {}

		for angle_key, before_cm in profile_before.items():
			after_cm = profile_after.get(angle_key)

			if after_cm is None:
				continue

			deltas[round(float(angle_key), 2)] = float(after_cm) - float(before_cm)

		if len(deltas) < 8:
			return None

		# implausibly large jumps are single-bin reflection artifacts, not real forward motion
		candidates = [
			(angle, delta) for angle, delta in deltas.items()
			if -abs(max_change_cm) <= delta <= -abs(min_change_cm)
		]

		candidates.sort(key=lambda item: item[1])

		for angle, delta in candidates:
			left = deltas.get(round((angle - bin_size) % 360.0, 2))
			right = deltas.get(round((angle + bin_size) % 360.0, 2))
			neighbors = [d for d in (left, right) if d is not None]

			# require at least one neighboring bin to also show a real decrease (spatial coherence)
			if not neighbors or all(d > -abs(min_change_cm) * 0.5 for d in neighbors):
				continue

			return {
				"front_angle_deg": angle,
				"best_delta_cm": delta
			}

		return None

	def _normalize_degrees(self, value):

		normalized = float(value) % 360.0

		if normalized > 180.0:
			normalized -= 360.0

		return normalized

	def _parse(self, text):

		normalized = self._normalize(text)

		if self._contains_any(normalized, ["dur", "durdur", "fren"]):
			return {
				"action": "stop",
				"duration": 0
			}

		distance = self._distance_meters(normalized)
		drive_duration = self._drive_duration(distance, normalized)
		turn_duration = self._turn_duration(normalized)

		if self._contains_any(normalized, ["geri", "arkaya"]):
			return {
				"action": "backward",
				"duration": drive_duration
			}

		if self._contains_any(normalized, ["ileri", "ilerle", "öne", "one"]):
			return {
				"action": "forward",
				"duration": drive_duration
			}

		if self._contains_any(normalized, ["sağa", "saga", "sağ", "sag"]):
			return {
				"action": "right",
				"duration": turn_duration
			}

		if self._contains_any(normalized, ["sola", "sol"]):
			return {
				"action": "left",
				"duration": turn_duration
			}

		return {
			"action": "unknown",
			"duration": 0
		}

	def _drive_duration(self, distance, normalized):

		if distance:
			return min(
				MOVEMENT["MAX_MOVE_SECONDS"],
				max(
					MOVEMENT["MIN_MOVE_SECONDS"],
					distance * MOVEMENT["SECONDS_PER_METER"]
				)
			)

		if self._contains_any(normalized, ["biraz", "azıcık", "azicik", "kısa", "kisa"]):
			return MOVEMENT["NUDGE_SECONDS"]

		return MOVEMENT["DEFAULT_MOVE_SECONDS"]

	def _turn_duration(self, normalized):

		match = re.search(
			r"(\d+)\s*derece",
			normalized
		)

		if match:
			degrees = int(
				match.group(1)
			)
			return min(
				MOVEMENT["MAX_TURN_SECONDS"],
				max(
					MOVEMENT["MIN_TURN_SECONDS"],
					degrees / 90 * MOVEMENT["TURN_90_SECONDS"]
				)
			)

		if self._contains_any(normalized, ["biraz", "azıcık", "azicik", "kısa", "kisa"]):
			return MOVEMENT["NUDGE_SECONDS"]

		return MOVEMENT["TURN_90_SECONDS"]

	def _time_value_seconds(self, value, unit):

		if unit in ["dakika", "dk"]:
			return value * 60

		return value

	def _distance_meters(self, normalized):

		if "yarım metre" in normalized or "yarim metre" in normalized:
			return 0.5

		if "yarım santim" in normalized or "yarim santim" in normalized:
			return 0.005

		word_distance = self._word_distance_meters(normalized)

		if word_distance is not None:
			return word_distance

		match = re.search(
			r"(\d+(?:[\.,]\d+)?)\s*(metre|m)\b",
			normalized
		)

		if match:
			return float(
				match.group(1).replace(
					",",
					"."
				)
			)

		match = re.search(
			r"(\d+(?:[\.,]\d+)?)\s*(santim|santimetre|cm)\b",
			normalized
		)

		if match:
			return float(
				match.group(1).replace(
					",",
					"."
				)
			) / 100

		return None

	def _word_distance_meters(self, normalized):

		match = re.search(
			r"\b([a-zçğıöşü ]+?)\s*(metre|m|santim|santimetre|cm)\b",
			normalized
		)

		if not match:
			return None

		value = self._number_words_value(
			match.group(1).strip()
		)

		if value is None:
			return None

		unit = match.group(2)

		if unit in ["santim", "santimetre", "cm"]:
			return value / 100

		return value

		return None

	def _number_words_value(self, text):

		text = text.strip()

		if not text:
			return None

		if text == "yarim" or text == "bucuk":
			return 0.5

		words = text.split()
		value = 0
		pending_half = False
		units = {
			"sifir": 0,
			"bir": 1,
			"iki": 2,
			"uc": 3,
			"dort": 4,
			"bes": 5,
			"alti": 6,
			"yedi": 7,
			"sekiz": 8,
			"dokuz": 9
		}
		tens = {
			"on": 10,
			"yirmi": 20,
			"otuz": 30,
			"kirk": 40,
			"elli": 50,
			"altmis": 60,
			"yetmis": 70,
			"seksen": 80,
			"doksan": 90
		}

		for word in words:
			if word in tens:
				value += tens[word]
				continue

			if word in units:
				value += units[word]
				continue

			if word == "yuz":
				value = max(value, 1) * 100
				continue

			if word == "bucuk":
				pending_half = True
				continue

			return None

		if pending_half:
			value += 0.5

		return float(value)

	def _normalize(self, text):

		text = unicodedata.normalize(
			"NFKD",
			text.lower()
		)
		text = "".join(
			character
			for character in text
			if not unicodedata.combining(character)
		)

		return re.sub(
			r"\s+",
			" ",
			text
		).strip()

	def _contains_any(self, text, words):

		return any(
			word in text
			for word in words
		)

