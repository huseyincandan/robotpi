"""Validate near-field sonar observations before projecting them into costmaps."""

import math


def mapping_range_m(payload, maximum_cm):
    if payload.get("status") != "OK" or not payload.get("stable"):
        return None
    try:
        confidence = float(payload.get("confidence", 0))
        centimeters = float(payload.get("distance_cm"))
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(confidence) or confidence < 0.7:
        return None
    if not math.isfinite(centimeters) or not 2.0 <= centimeters <= maximum_cm:
        return None
    return centimeters / 100.0
