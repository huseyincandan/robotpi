#!/usr/bin/env python3
"""Report lethal/inflated cost cells under and immediately around the robot."""

import math
import time

import rclpy
from geometry_msgs.msg import PolygonStamped
from nav2_msgs.msg import Costmap
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


class CostmapDiagnostic(Node):
    def __init__(self):
        super().__init__("robotpi_costmap_diagnostic")
        self.costmap = None
        self.footprint = None
        self.create_subscription(
            Costmap, "/local_costmap/costmap_raw", self._on_costmap, 10
        )
        self.create_subscription(
            PolygonStamped,
            "/local_costmap/published_footprint",
            self._on_footprint,
            10,
        )

    def _on_costmap(self, msg):
        self.costmap = msg

    def _on_footprint(self, msg):
        self.footprint = msg

    def report(self):
        if self.costmap is None or self.footprint is None:
            print(
                "ERROR: timed out waiting for local costmap/footprint; "
                f"costmap={self.costmap is not None} "
                f"footprint={self.footprint is not None}"
            )
            return 2

        cm = self.costmap
        meta = cm.metadata
        poly_msg = self.footprint
        poly = [(p.x, p.y) for p in poly_msg.polygon.points]
        if cm.header.frame_id != poly_msg.header.frame_id:
            print(
                "ERROR: frame mismatch: "
                f"costmap={cm.header.frame_id} "
                f"footprint={poly_msg.header.frame_id}"
            )
            return 2

        resolution = float(meta.resolution)
        width = int(meta.size_x)
        height = int(meta.size_y)
        origin_x = float(meta.origin.position.x)
        origin_y = float(meta.origin.position.y)
        if resolution <= 0 or len(cm.data) != width * height:
            print(
                "ERROR: invalid costmap dimensions: "
                f"{width}x{height} res={resolution} data={len(cm.data)}"
            )
            return 2

        under = []
        near = []
        center_x = sum(x for x, _ in poly) / len(poly)
        center_y = sum(y for _, y in poly) / len(poly)
        for iy in range(height):
            y = origin_y + (iy + 0.5) * resolution
            for ix in range(width):
                x = origin_x + (ix + 0.5) * resolution
                cost = int(cm.data[iy * width + ix])
                if cost in (0, 255):
                    continue
                if point_in_polygon(x, y, poly):
                    under.append(cost)
                elif math.hypot(x - center_x, y - center_y) <= 0.30:
                    near.append(cost)

        def summary(values):
            return {
                "cells": len(values),
                "lethal_253_plus": sum(v >= 253 for v in values),
                "high_200_plus": sum(v >= 200 for v in values),
                "max_cost": max(values, default=0),
            }

        print(
            {
                "frame": cm.header.frame_id,
                "size": [width, height],
                "resolution_m": resolution,
                "footprint_center_m": [round(center_x, 3), round(center_y, 3)],
                "footprint_costs": summary(under),
                "nearby_costs_within_0.30m": summary(near),
            }
        )
        return 0


def main():
    rclpy.init()
    node = CostmapDiagnostic()
    deadline = time.monotonic() + 8.0
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.2)
            if node.costmap is not None and node.footprint is not None:
                break
        return node.report()
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
