#!/usr/bin/env python3
"""Summarize obstacle and range costmap layers around the stationary robot."""

import math
import time

import rclpy
from geometry_msgs.msg import PolygonStamped
from nav2_msgs.msg import Costmap
from nav2_msgs.srv import GetCostmap
from rclpy.node import Node


def point_in_polygon(x, y, polygon):
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


class CostmapLayerDiagnostic(Node):
    def __init__(self):
        super().__init__("robotpi_costmap_layer_diagnostic")
        self.footprint = None
        self.create_subscription(
            PolygonStamped,
            "/local_costmap/published_footprint",
            self.on_footprint,
            10,
        )
        self.layers = {
            "obstacle": self.create_client(
                GetCostmap, "/local_costmap/get_obstacle_layer"
            ),
            "range": self.create_client(
                GetCostmap, "/local_costmap/get_range_layer"
            ),
        }

    def on_footprint(self, msg):
        self.footprint = msg

    def summarize(self, label, cm):
        fp = self.footprint
        if fp is None:
            print(f"{label}: ERROR footprint not received")
            return
        if cm.header.frame_id != fp.header.frame_id:
            print(
                f"{label}: ERROR frame mismatch costmap={cm.header.frame_id} "
                f"footprint={fp.header.frame_id}"
            )
            return

        meta = cm.metadata
        res = float(meta.resolution)
        width, height = int(meta.size_x), int(meta.size_y)
        data = cm.data
        polygon = [(p.x, p.y) for p in fp.polygon.points]
        if res <= 0 or len(data) != width * height or len(polygon) < 3:
            print(f"{label}: ERROR invalid costmap data")
            return

        ox, oy = float(meta.origin.position.x), float(meta.origin.position.y)
        cx = sum(x for x, _ in polygon) / len(polygon)
        cy = sum(y for _, y in polygon) / len(polygon)
        min_x, max_x = cx - 0.30, cx + 0.30
        min_y, max_y = cy - 0.30, cy + 0.30
        i0 = max(0, int((min_x - ox) / res))
        i1 = min(width - 1, int((max_x - ox) / res))
        j0 = max(0, int((min_y - oy) / res))
        j1 = min(height - 1, int((max_y - oy) / res))
        footprint_values = []
        nearby_values = []
        for j in range(j0, j1 + 1):
            wy = oy + (j + 0.5) * res
            for i in range(i0, i1 + 1):
                wx = ox + (i + 0.5) * res
                raw = int(data[j * width + i])
                value = raw if raw >= 0 else raw + 256
                if point_in_polygon(wx, wy, polygon):
                    footprint_values.append(value)
                elif math.hypot(wx - cx, wy - cy) <= 0.30:
                    nearby_values.append(value)

        def stats(values):
            known = [v for v in values if v != 255]
            return {
                "cells": len(values),
                "nonzero": sum(v != 0 and v != 255 for v in values),
                "lethal_254": sum(v == 254 for v in values),
                "inscribed_253": sum(v == 253 for v in values),
                "unknown_255": sum(v == 255 for v in values),
                "max_known": max(known, default=0),
            }

        print(
            {
                "layer": label,
                "frame": cm.header.frame_id,
                "center_m": [round(cx, 3), round(cy, 3)],
                "footprint": stats(footprint_values),
                "nearby_0.30m": stats(nearby_values),
            }
        )

    def query_layer(self, label, client):
        if not client.wait_for_service(timeout_sec=3.0):
            print(f"{label}: ERROR service unavailable")
            return
        future = client.call_async(GetCostmap.Request())
        deadline = time.monotonic() + 5.0
        while rclpy.ok() and not future.done() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
        if not future.done():
            print(f"{label}: ERROR service timed out")
            return
        try:
            response = future.result()
        except Exception as exc:  # noqa: BLE001 - report DDS/service errors
            print(f"{label}: ERROR {exc}")
            return
        self.summarize(label, response.map)


def main():
    rclpy.init()
    node = CostmapLayerDiagnostic()
    try:
        deadline = time.monotonic() + 5.0
        while rclpy.ok() and node.footprint is None and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
        if node.footprint is None:
            print("ERROR: timed out waiting for published footprint")
            return 2
        for label, client in node.layers.items():
            node.query_layer(label, client)
        return 0
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
