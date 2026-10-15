"""Bound persistent drive commands using independently observed body motion."""

import math


class MotionProgressGuard:
    def __init__(self, window_seconds=3.0, min_translation_m=0.025,
                 min_rotation_rad=0.12, release_translation_m=0.06,
                 release_rotation_rad=0.35):
        self.window_seconds = window_seconds
        self.min_translation_m = min_translation_m
        self.min_rotation_rad = min_rotation_rad
        self.release_translation_m = release_translation_m
        self.release_rotation_rad = release_rotation_rad
        self.mode = None
        self.started_at = None
        self.start_pose = None
        self.observation_kind = None
        self.blocked_mode = None
        self.blocked_pose = None
        self.blocked_kind = None

    @staticmethod
    def command_mode(x, y):
        if abs(y) >= 10:
            return "forward" if y > 0 else "backward"
        if abs(x) >= 10:
            return "left" if x < 0 else "right"
        return None

    @staticmethod
    def _distance(a, b):
        return math.hypot(b[0] - a[0], b[1] - a[1])

    @staticmethod
    def _yaw_distance(a, b):
        return abs(math.atan2(math.sin(b[2] - a[2]), math.cos(b[2] - a[2])))

    @staticmethod
    def _scan_change(a, b):
        paired = [(left, right) for left, right in zip(a, b)
                  if left is not None and right is not None]
        changes = sorted((abs(right - left) for left, right in paired), reverse=True)
        # One narrow sector can jump when a single ray hits a chair leg.
        return changes[1] if len(changes) >= 2 else 0.0

    @staticmethod
    def _scan_translation_change(a, b):
        # The four observations are front, back, left, right. Translation
        # toward a wall makes the front distance shorter and the rear longer
        # (or vice versa). A single-sector jump is not proof of escape.
        if any(value is None for value in (a[0], a[1], b[0], b[1])):
            return 0.0
        front_delta = b[0] - a[0]
        back_delta = b[1] - a[1]
        if front_delta * back_delta >= 0:
            return 0.0
        return min(abs(front_delta), abs(back_delta))

    def update(self, x, y, pose, now, kind="pose"):
        """Return True once when a sustained command makes no body progress."""
        mode = self.command_mode(x, y)
        if pose is None or mode is None:
            self.mode = None
            self.start_pose = None
            return False

        if (self.blocked_mode and mode != self.blocked_mode
                and self.blocked_pose and kind == self.blocked_kind):
            if kind == "pose":
                escaped = (self._distance(self.blocked_pose, pose)
                           >= self.release_translation_m)
                # A verified body rotation changes the forward corridor even
                # when a tight space prevents a 6 cm straight retreat.
                if self.blocked_mode in {"forward", "backward"}:
                    escaped = (escaped or self._yaw_distance(self.blocked_pose, pose)
                               >= self.release_rotation_rad)
            else:
                escaped = self._scan_translation_change(self.blocked_pose, pose) >= 0.06
                if self.blocked_mode in {"forward", "backward"}:
                    escaped = escaped or self._scan_change(self.blocked_pose, pose) >= 0.15
            if escaped:
                self.blocked_mode = None
                self.blocked_pose = None
                self.blocked_kind = None

        if mode != self.mode or kind != self.observation_kind or self.start_pose is None:
            self.mode = mode
            self.observation_kind = kind
            self.started_at = now
            self.start_pose = pose
            return False

        if kind == "pose":
            progress = (self._distance(self.start_pose, pose)
                        if mode in {"forward", "backward"}
                        else self._yaw_distance(self.start_pose, pose))
            threshold = (self.min_translation_m if mode in {"forward", "backward"}
                         else self.min_rotation_rad)
        else:
            if mode in {"forward", "backward"}:
                progress = self._scan_translation_change(self.start_pose, pose)
                threshold = 0.03
            else:
                progress = self._scan_change(self.start_pose, pose)
                threshold = 0.06
        if progress >= threshold:
            self.started_at = now
            self.start_pose = pose
            return False

        if now - self.started_at < self.window_seconds:
            return False

        self.started_at = now
        self.start_pose = pose
        self.blocked_mode = mode
        self.blocked_pose = pose
        self.blocked_kind = kind
        return True

    def blocked(self, x, y):
        return self.blocked_mode is not None and self.command_mode(x, y) == self.blocked_mode

    def block(self, x, y, pose, kind="pose"):
        self.blocked_mode = self.command_mode(x, y)
        self.blocked_pose = pose
        self.blocked_kind = kind
