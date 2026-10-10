#!/usr/bin/env python3
"""Teker degisimi sonrasi hareket testi ve kalibrasyonu.

Referans olcum: lidar tarama eslestirme (ICP, robot dururken oncesi/sonrasi).
Karsilastirilanlar: enkoder tikleri, IMU gyro entegrasyonu, ultrasonik.
Motor surer; calisan app (127.0.0.1:5000) gerekir. Alan temizligi onaylanmadan
hareket yapmaz (--confirm-clear-area). --static-only sadece sensorleri okur.
"""
import argparse
import json
import math
import signal
import statistics
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:5000"
SCAN_FILE = ROOT / "output" / "maps" / "live_scan.json"
STRAIGHT_PERCENT = 27.45   # default 70/255 PWM
TURN_PERCENT = 31.4        # default 80 PWM
TURN_FINE_PERCENT = 28.2   # default 72 PWM (son 20 derece)
TURN_ALL_AROUND_MIN_CM = 25.0
STRAIGHT_MARGIN_CM = 35.0


def http(method, path, timeout=2.0):
    req = urllib.request.Request(
        BASE + path, method=method, data=b"" if method == "POST" else None
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def stop_motor():
    last = None
    for _ in range(5):
        try:
            reply = http("POST", "/motor/stop")
            if reply.get("status") == "OK":
                return True
            last = reply
        except Exception as exc:
            last = exc
        time.sleep(0.05)
    raise RuntimeError(f"MOTOR STOP DOGRULANAMADI: {last!r}")


class Sampler(threading.Thread):
    """/imu/motion'i tarar; TELEM (~10 Hz) her yeni orneginde gyro'yu entegre eder."""

    def __init__(self):
        super().__init__(daemon=True)
        self.lock = threading.Lock()
        self.halt = False
        self.bias = 0.0
        self.angle = 0.0
        self.rate = 0.0
        self.rl = None
        self.rr = None
        self.rx = None
        self.prev_g = None
        self.prev_rx = None
        self.count = 0
        self.gyro_raw = []

    def run(self):
        while not self.halt:
            try:
                d = http("GET", "/imu/motion", 1.0)
            except Exception:
                time.sleep(0.02)
                continue
            rx = d.get("telemetry_received_at")
            if d.get("status") != "OK" or d.get("enc_rl") is None or rx is None:
                time.sleep(0.02)
                continue
            with self.lock:
                if rx == self.rx:
                    pass
                else:
                    g = float(d["gyro_z_dps"]) - self.bias
                    if self.prev_g is not None:
                        dt = min(rx - self.prev_rx, 0.5)
                        self.angle += 0.5 * (g + self.prev_g) * dt
                    self.prev_g, self.prev_rx = g, rx
                    self.rate = g
                    self.rl, self.rr, self.rx = int(d["enc_rl"]), int(d["enc_rr"]), rx
                    self.count += 1
                    self.gyro_raw.append(float(d["gyro_z_dps"]))
            time.sleep(0.005)

    def snap(self):
        with self.lock:
            return {
                "angle": self.angle, "rate": self.rate, "rl": self.rl,
                "rr": self.rr, "age": (time.monotonic() - self.rx) if self.rx else 99.0,
            }


def read_scan_file():
    for _ in range(8):
        try:
            return json.loads(SCAN_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            time.sleep(0.05)
    return None


def collect_scans(count, timeout=8.0):
    scans, last = [], 0.0
    t_end = time.monotonic() + timeout
    while len(scans) < count and time.monotonic() < t_end:
        data = read_scan_file()
        if data and 0 <= time.time() - data.get("updated_at", 0) < 0.7 and data.get("updated_at", 0) > last:
            last = data["updated_at"]
            scans.append(data["scan_points"])
        time.sleep(0.05)
    if len(scans) < count:
        raise RuntimeError("Lidar taramasi guncellenmiyor")
    return scans


def combine_scans(scans):
    by_angle = {}
    for pts in scans:
        for angle, dist in pts:
            by_angle.setdefault(round(float(angle)), []).append(float(dist))
    out = []
    for angle, vals in by_angle.items():
        if len(vals) >= max(1, len(scans) // 2):
            out.append((float(angle), float(np.median(vals))))
    return out


def to_xy(points):
    arr = np.array(points, dtype=float)
    ang = np.radians(arr[:, 0])
    rng = arr[:, 1] / 100.0
    return np.column_stack([rng * np.cos(ang), rng * np.sin(ang)])


def sector_min(points, center_deg, half_deg):
    best = None
    for angle, dist in points:
        diff = (angle - center_deg + 540.0) % 360.0 - 180.0
        if abs(diff) <= half_deg and (best is None or dist < best):
            best = dist
    return best


def target_normals(pts, k=6):
    tree = cKDTree(pts)
    _, idx = tree.query(pts, k=k)
    nrm = np.zeros_like(pts)
    for i in range(len(pts)):
        q = pts[idx[i]]
        q = q - q.mean(axis=0)
        _, vec = np.linalg.eigh(q.T @ q)
        nrm[i] = vec[:, 0]
    return tree, nrm


def icp_once(src, dst, tree, nrm, init, iters=45):
    tx, ty, th = init
    for it in range(iters):
        c, s = math.cos(th), math.sin(th)
        p = src @ np.array([[c, s], [-s, c]]) + np.array([tx, ty])
        dist, idx = tree.query(p)
        mask = dist < max(0.08, 0.5 * 0.85 ** it)
        if mask.sum() < 30:
            return None
        n, q, pm = nrm[idx[mask]], dst[idx[mask]], p[mask]
        r = np.einsum("ij,ij->i", n, pm - q)
        keep = np.argsort(np.abs(r))[: int(0.85 * len(r))]
        n, pm, r = n[keep], pm[keep], r[keep]
        a = np.column_stack([n[:, 0], n[:, 1], -n[:, 0] * pm[:, 1] + n[:, 1] * pm[:, 0]])
        sol = np.linalg.lstsq(a, -r, rcond=None)[0]
        dtx, dty, dth = sol
        c2, s2 = math.cos(dth), math.sin(dth)
        tx, ty = c2 * tx - s2 * ty + dtx, s2 * tx + c2 * ty + dty
        th += dth
    c, s = math.cos(th), math.sin(th)
    p = src @ np.array([[c, s], [-s, c]]) + np.array([tx, ty])
    dist, idx = tree.query(p)
    r = np.einsum("ij,ij->i", nrm[idx], p - dst[idx])
    good = (np.abs(r) < 0.03) & (dist < 0.1)
    if good.sum() < 30:
        return None
    return {
        "x": tx, "y": ty, "yaw_deg": math.degrees(th),
        "rmse": float(np.sqrt(np.mean(r[good] ** 2))),
        "inlier_fraction": float(good.mean()),
    }


def icp(pre_pts, post_pts, yaw_guess_deg=0.0, x_guess=0.0, wide=False):
    """post -> pre cercevesi; x,y,yaw = robotun ilk poza gore son pozu."""
    dst, src = to_xy(pre_pts), to_xy(post_pts)
    tree, nrm = target_normals(dst)
    yaw_offsets = (-12, -8, -4, 0, 4, 8, 12) if wide else (-6, -3, 0, 3, 6)
    best = None
    for dy in yaw_offsets:
        for gx in {0.0, x_guess}:
            res = icp_once(src, dst, tree, nrm, (gx, 0.0, math.radians(yaw_guess_deg + dy)))
            if res is None:
                continue
            score = res["inlier_fraction"] - 5.0 * res["rmse"]
            if best is None or score > best[0]:
                best = (score, res)
    return best[1] if best else None


def wait_stationary(sampler, min_s=1.0):
    time.sleep(min_s)
    prev = sampler.snap()
    for _ in range(20):
        time.sleep(0.3)
        cur = sampler.snap()
        if (cur["rl"], cur["rr"]) == (prev["rl"], prev["rr"]) and abs(cur["rate"]) < 1.5:
            return cur
        prev = cur
    raise RuntimeError("Robot durmadi / enkoder sabitlenmedi")


def drive_cmd(x, y):
    return http("GET", f"/drive?x={x:.3f}&y={y:.3f}&source=manual", timeout=2.0)


def ultrasonic_cm():
    try:
        vals = []
        for _ in range(3):
            r = http("GET", "/ultrasonic/readings", 1.5)
            if r.get("distance_cm") is not None:
                vals.append(float(r["distance_cm"]))
            time.sleep(0.1)
        return statistics.median(vals) if vals else None
    except Exception:
        return None


def static_pose_scan(sampler):
    state = wait_stationary(sampler)
    pts = combine_scans(collect_scans(5))
    return state, pts


def run_straight(sampler, direction, target_ticks, max_s, est_tpm=13000.0):
    stop_motor()
    state0, pre = static_pose_scan(sampler)
    est_cm = target_ticks / est_tpm * 100.0
    center = 0.0 if direction > 0 else 180.0
    clearance = sector_min(pre, center, 25.0)
    if clearance is None or clearance < est_cm + STRAIGHT_MARGIN_CM:
        return {"kind": "straight", "direction": direction, "skipped": f"yetersiz bos alan ({clearance} cm)"}
    us_before = ultrasonic_cm()
    y = STRAIGHT_PERCENT * direction
    reason, t0 = "target", time.monotonic()
    try:
        while True:
            live = read_scan_file()
            if not live or not 0 <= time.time() - live.get("updated_at", 0) < 0.7:
                reason = "lidar_stale"
                break
            clearance_now = sector_min(live["scan_points"], center, 30.0)
            if clearance_now is None or clearance_now < 40.0:
                reason = "clearance_abort"
                break
            if sampler.snap()["age"] > 0.3:
                reason = "telemetry_stale"
                break
            reply = drive_cmd(0.0, y)
            if reply.get("status") != "OK":
                reason = f"blocked:{reply.get('reason')}"
                break
            s = sampler.snap()
            if s["age"] > 0.5:
                reason = "telemetry_stale"
                break
            travel = (abs(s["rl"] - state0["rl"]) + abs(s["rr"] - state0["rr"])) / 2
            if travel >= target_ticks:
                break
            if abs(s["angle"] - state0["angle"]) > 8:
                reason = "yaw_abort"
                break
            live = read_scan_file()
            if live:
                c = sector_min(live["scan_points"], center, 25.0)
                if c is not None and c < 30.0:
                    reason = f"clearance_abort({c:.0f}cm)"
                    break
            if time.monotonic() - t0 > max_s:
                reason = "timeout"
                break
            time.sleep(0.04)
    finally:
        stop_motor()
    drive_s = time.monotonic() - t0
    state1, post = static_pose_scan(sampler)
    us_after = ultrasonic_cm()
    d_rl, d_rr = state1["rl"] - state0["rl"], state1["rr"] - state0["rr"]
    imu = state1["angle"] - state0["angle"]
    res = icp(pre, post, yaw_guess_deg=imu, x_guess=direction * target_ticks / est_tpm)
    return {
        "kind": "straight", "direction": direction, "stop_reason": reason,
        "drive_s": round(drive_s, 2), "d_rl": d_rl, "d_rr": d_rr,
        "imu_deg": round(imu, 2), "icp": res,
        "front_before_cm": sector_min(pre, 0.0, 10.0), "front_after_cm": sector_min(post, 0.0, 10.0),
        "us_before_cm": us_before, "us_after_cm": us_after,
    }


def run_turn(sampler, target_deg, cmd_sign):
    stop_motor()
    state0, pre = static_pose_scan(sampler)
    around = min(d for _, d in pre)
    if around < TURN_ALL_AROUND_MIN_CM:
        return {"kind": "turn", "target": target_deg, "skipped": f"cevrede cisim {around:.0f} cm"}, cmd_sign
    tsign = 1 if target_deg > 0 else -1
    goal = abs(target_deg)
    reason, t0, flipped = "target", time.monotonic(), False
    try:
        while True:
            live = read_scan_file()
            if not live or not 0 <= time.time() - live.get("updated_at", 0) < 0.7:
                reason = "lidar_stale"
                break
            if not live.get("scan_points") or min(d for _, d in live["scan_points"]) < TURN_ALL_AROUND_MIN_CM:
                reason = "clearance_abort"
                break
            s = sampler.snap()
            progress = (s["angle"] - state0["angle"]) * tsign
            rate = s["rate"] * tsign
            if s["age"] > 0.5:
                reason = "telemetry_stale"
                break
            if progress + max(rate, 0.0) * 0.12 >= goal:
                break
            elapsed = time.monotonic() - t0
            if elapsed > 1.0 and progress < -3.0:
                reason, flipped = "wrong_direction", True
                break
            if elapsed > 2.0 and progress < 3.0:
                reason = "no_rotation"
                break
            if progress > goal + 25 or elapsed > goal / 20.0 + 4.0:
                reason = "limit"
                break
            percent = TURN_FINE_PERCENT if goal - progress < 20 else TURN_PERCENT
            reply = drive_cmd(percent * tsign * cmd_sign, 0.0)
            if reply.get("status") != "OK":
                reason = f"blocked:{reply.get('reason')}"
                break
            time.sleep(0.04)
    finally:
        stop_motor()
    drive_s = time.monotonic() - t0
    if flipped:
        cmd_sign = -cmd_sign
    state1, post = static_pose_scan(sampler)
    d_rl, d_rr = state1["rl"] - state0["rl"], state1["rr"] - state0["rr"]
    imu = state1["angle"] - state0["angle"]
    res = icp(pre, post, yaw_guess_deg=imu, wide=True)
    return {
        "kind": "turn", "target": target_deg, "stop_reason": reason, "drive_s": round(drive_s, 2),
        "d_rl": d_rl, "d_rr": d_rr, "imu_deg": round(imu, 2), "icp": res,
        "mean_rate_dps": round(imu / drive_s, 1) if drive_s else None,
    }, cmd_sign


def preflight(sampler):
    info = {}
    motor = http("GET", "/motor/status")
    info["motor"] = {k: motor.get(k) for k in ("power_fault", "sensor_fault", "blocked")}
    if motor.get("power_fault") or motor.get("sensor_fault"):
        raise RuntimeError(f"Motor hata kilidi: {info['motor']}")
    info["battery"] = http("GET", "/battery/status")
    stop_motor()
    time.sleep(5.0)
    raw = list(sampler.gyro_raw[-40:])
    info["gyro_static_mean_dps"] = round(statistics.mean(raw), 3)
    info["gyro_static_std_dps"] = round(statistics.pstdev(raw), 3)
    sampler.bias = statistics.mean(raw)
    n0, rl0, rr0 = sampler.count, sampler.snap()["rl"], sampler.snap()["rr"]
    time.sleep(3.0)
    s = sampler.snap()
    info["telemetry_hz"] = round((sampler.count - n0) / 3.0, 1)
    info["encoder_static_drift"] = [s["rl"] - rl0, s["rr"] - rr0]
    scans = collect_scans(6)
    ref = combine_scans(scans[:1])
    poses = []
    for pts in scans[1:]:
        r = icp(ref, combine_scans([pts]), 0.0)
        if r:
            poses.append(r)
    info["lidar_static"] = {
        "x_std_mm": round(statistics.pstdev([p["x"] for p in poses]) * 1000, 2),
        "y_std_mm": round(statistics.pstdev([p["y"] for p in poses]) * 1000, 2),
        "yaw_std_deg": round(statistics.pstdev([p["yaw_deg"] for p in poses]), 4),
        "rmse_mm": round(statistics.mean([p["rmse"] for p in poses]) * 1000, 2),
    } if len(poses) >= 3 else None
    pts = combine_scans(scans)
    info["clearance_cm"] = {
        "front": sector_min(pts, 0, 25), "left": sector_min(pts, 90, 25),
        "back": sector_min(pts, 180, 25), "right": sector_min(pts, 270, 25),
        "min_all": min(d for _, d in pts),
    }
    info["ultrasonic_cm"] = ultrasonic_cm()
    return info


def mean_std(values):
    values = [v for v in values if v is not None]
    if not values:
        return None, None
    return statistics.mean(values), (statistics.pstdev(values) if len(values) > 1 else 0.0)


def analyze(results, cfg_tpm, cfg_w):
    out = {}
    ok_st = [
        r for r in results
        if r["kind"] == "straight" and r.get("icp") and r.get("stop_reason") == "target"
        and r["icp"]["inlier_fraction"] > 0.85 and abs(r["icp"]["x"]) > 0.05
        and abs(r["icp"]["yaw_deg"] - r["imu_deg"]) < 6.0
    ]
    for r in ok_st:
        x, th = r["icp"]["x"], math.radians(r["icp"]["yaw_deg"])
        r["tpm_overall"] = (abs(r["d_rl"]) + abs(r["d_rr"])) / 2 / abs(x)
        dist_l, dist_r = x - th * cfg_w / 2, x + th * cfg_w / 2
        r["tpm_l"], r["tpm_r"] = r["d_rl"] / dist_l, r["d_rr"] / dist_r
        if r["us_before_cm"] is not None and r["us_after_cm"] is not None:
            r["us_ratio"] = -(r["us_after_cm"] - r["us_before_cm"]) / 100.0 / x
        else:
            r["us_ratio"] = None
        r["lidar_front_ratio"] = (
            -(r["front_after_cm"] - r["front_before_cm"]) / 100.0 / x
            if r["front_before_cm"] and r["front_after_cm"] else None
        )
        r["mount_yaw_deg"] = math.degrees(math.atan2(r["icp"]["y"], x)) if x > 0 else math.degrees(math.atan2(-r["icp"]["y"], -x))
    out["straight_valid"] = len(ok_st)
    for name in ("tpm_overall", "tpm_l", "tpm_r"):
        out[name] = mean_std([r[name] for r in ok_st])
    for label, d in (("fwd", 1), ("rev", -1)):
        out[f"tpm_overall_{label}"] = mean_std([r["tpm_overall"] for r in ok_st if r["direction"] == d])
    out["us_ratio"] = mean_std([r["us_ratio"] for r in ok_st])
    out["lidar_front_ratio"] = mean_std([r["lidar_front_ratio"] for r in ok_st])
    out["mount_yaw_deg"] = mean_std([r["mount_yaw_deg"] for r in ok_st])
    out["straight_yaw_lidar_deg"] = mean_std([r["icp"]["yaw_deg"] for r in ok_st])
    out["straight_yaw_imu_deg"] = mean_std([r["imu_deg"] for r in ok_st])
    out["speed_mps"] = mean_std([abs(r["icp"]["x"]) / r["drive_s"] for r in ok_st])

    tpm = out["tpm_overall"][0] or cfg_tpm
    ok_tn = [
        r for r in results
        if r["kind"] == "turn" and r.get("icp") and r.get("stop_reason") == "target"
        and r["icp"]["inlier_fraction"] > 0.80 and abs(r["icp"]["yaw_deg"]) > 20
        and abs(r["icp"]["yaw_deg"] - r["imu_deg"]) < 12.0
    ]
    for r in ok_tn:
        th = math.radians(r["icp"]["yaw_deg"])
        r["w_eff"] = (r["d_rr"] - r["d_rl"]) / (tpm * th)
        r["imu_scale"] = r["imu_deg"] / r["icp"]["yaw_deg"]
        r["enc_yaw_cfg_deg"] = math.degrees((r["d_rr"] - r["d_rl"]) / (cfg_tpm * cfg_w))
        r["rl_over_rr"] = abs(r["d_rl"]) / abs(r["d_rr"]) if r["d_rr"] else None
    out["turn_valid"] = len(ok_tn)
    out["w_eff"] = mean_std([r["w_eff"] for r in ok_tn])
    out["w_eff_ccw"] = mean_std([r["w_eff"] for r in ok_tn if r["icp"]["yaw_deg"] > 0])
    out["w_eff_cw"] = mean_std([r["w_eff"] for r in ok_tn if r["icp"]["yaw_deg"] < 0])
    out["imu_scale"] = mean_std([r["imu_scale"] for r in ok_tn])
    out["rl_over_rr_turn"] = mean_std([r["rl_over_rr"] for r in ok_tn])
    out["turn_rate_dps"] = mean_std([abs(r["mean_rate_dps"]) for r in ok_tn if r.get("mean_rate_dps")])
    out["enc_yaw_cfg_ratio"] = mean_std([r["enc_yaw_cfg_deg"] / r["icp"]["yaw_deg"] for r in ok_tn])
    out["recommended"] = {
        "ROS2_ENCODER_TICKS_PER_METER": round(out["tpm_overall"][0], 0) if out["tpm_overall"][0] else None,
        "ROS2_ENCODER_TRACK_WIDTH_M": round(out["w_eff"][0], 4) if out["w_eff"][0] else None,
        "config_ticks_per_meter": cfg_tpm, "config_track_width_m": cfg_w,
    }
    return out


def print_report(results, analysis, pre):
    print("\n=== PREFLIGHT ===")
    print(json.dumps(pre, indent=1, ensure_ascii=False))
    print("\n=== DUZ SURUS ===")
    print("yon  neden        sure  dRL/dRR        lidar x(m) y(mm) yaw   imu     tik/m   US-oran")
    for r in results:
        if r["kind"] != "straight":
            continue
        if "skipped" in r:
            print(f"{r['direction']:+d}  ATLANDI: {r['skipped']}")
            continue
        i = r.get("icp") or {}
        print(
            f"{r['direction']:+d}  {r['stop_reason']:<12} {r['drive_s']:>4} {r['d_rl']:>6}/{r['d_rr']:<6} "
            f"{i.get('x', float('nan')):+.3f} {i.get('y', float('nan')) * 1000:+6.1f} {i.get('yaw_deg', float('nan')):+5.2f} "
            f"{r['imu_deg']:+6.2f} {r.get('tpm_overall', float('nan')):8.0f} {r.get('us_ratio') or float('nan'):.2f}"
        )
    print("\n=== DONUS ===")
    print("hedef neden        sure  dRL/dRR        lidar yaw  imu     W_eff   imu/lidar  hiz")
    for r in results:
        if r["kind"] != "turn":
            continue
        if "skipped" in r:
            print(f"{r['target']:+.0f} ATLANDI: {r['skipped']}")
            continue
        i = r.get("icp") or {}
        print(
            f"{r['target']:+4.0f} {r['stop_reason']:<12} {r['drive_s']:>4} {r['d_rl']:>6}/{r['d_rr']:<6} "
            f"{i.get('yaw_deg', float('nan')):+8.2f} {r['imu_deg']:+7.2f} {r.get('w_eff', float('nan')):.4f} "
            f"{r.get('imu_scale', float('nan')):.3f}  {r.get('mean_rate_dps')}"
        )
    print("\n=== OZET ===")
    for k, v in analysis.items():
        print(f"{k}: {v}")


def main():
    global TURN_PERCENT, TURN_FINE_PERCENT, STRAIGHT_PERCENT
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm-clear-area", action="store_true",
                    help="Robotun cevresinin bos oldugunu onayla; yoksa hareket yok")
    ap.add_argument("--static-only", action="store_true")
    ap.add_argument("--straight-ticks", type=int, default=4000)
    ap.add_argument("--straight-pairs", type=int, default=3)
    ap.add_argument("--turns", default="90,-90,90,-90,45,-45")
    ap.add_argument("--turn-percent", type=float, default=TURN_PERCENT)
    ap.add_argument("--turn-fine-percent", type=float, default=TURN_FINE_PERCENT)
    ap.add_argument(
        "--fixed-pwm", type=int, default=None,
        help="Sabit PWM ile kalibrasyon (1..155); ör. 150. Düz ve dönüş gücünü aynı PWM yüzdesine alır.",
    )
    args = ap.parse_args()
    if args.fixed_pwm is not None:
        if not 1 <= args.fixed_pwm <= 155:
            ap.error("--fixed-pwm 1..155 arasında olmalı")
        fixed_percent = args.fixed_pwm / 255.0 * 100.0
        STRAIGHT_PERCENT = fixed_percent
        TURN_PERCENT = fixed_percent
        TURN_FINE_PERCENT = fixed_percent
        from config import MOTOR
        turn_ceiling_pwm = round(float(MOTOR.get("MAX_TURN_PERCENT", 100.0)) * 2.55)
        if args.fixed_pwm > turn_ceiling_pwm:
            print(
                f"UYARI: duz hareket {args.fixed_pwm} PWM ister; mevcut Pi donus siniri "
                f"donusu yaklasik {turn_ceiling_pwm} PWM ile keser. Bu test iki hareketin "
                "ayni PWM'de oldugunu varsayamaz."
            )
    if args.fixed_pwm is None:
        TURN_PERCENT, TURN_FINE_PERCENT = args.turn_percent, args.turn_fine_percent

    from config import MAP
    cfg_tpm = float(MAP.get("ROS2_ENCODER_TICKS_PER_METER"))
    cfg_w = float(MAP.get("ROS2_ENCODER_TRACK_WIDTH_M"))

    sampler = Sampler()
    sampler.start()
    results, pre, analysis = [], {}, {}

    def on_signal(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_signal)
    try:
        time.sleep(1.0)
        pre = preflight(sampler)
        if args.static_only or not args.confirm_clear_area:
            print(json.dumps(pre, indent=1, ensure_ascii=False))
            if not args.static_only:
                print("Hareket icin --confirm-clear-area gerekli.")
            return
        for _ in range(args.straight_pairs):
            for direction in (1, -1):
                res = run_straight(sampler, direction, args.straight_ticks, max_s=12.0)
                results.append(res)
                if "stop_reason" in res and res["stop_reason"] != "target":
                    print("Duz surus durdu:", res["stop_reason"])
                    return
        cmd_sign = 1
        for target in [float(t) for t in args.turns.split(",") if t.strip()]:
            res, cmd_sign = run_turn(sampler, target, cmd_sign)
            results.append(res)
            if res.get("stop_reason") == "wrong_direction":
                res2, cmd_sign = run_turn(sampler, target, cmd_sign)
                results.append(res2)
            elif res.get("stop_reason") not in (None, "target"):
                return
        analysis = analyze(results, cfg_tpm, cfg_w)
        print_report(results, analysis, pre)
    finally:
        try:
            stop_motor()
        except Exception as exc:
            print("!!! STOP HATASI:", exc, file=sys.stderr)
        sampler.halt = True
        if results:
            out_dir = ROOT / "logs" / f"motion-calibration-{datetime.now():%Y-%m-%d}"
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"{datetime.now():%H%M%S}.json"
            path.write_text(json.dumps(
                {"preflight": pre, "results": results, "analysis": analysis},
                indent=1, default=str, ensure_ascii=False,
            ))
            print("Kaydedildi:", path)


if __name__ == "__main__":
    main()
