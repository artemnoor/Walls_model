from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import List, Tuple

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)


@dataclass
class FollowConfig:
    color_tolerance: int = 28
    step_px: int = 2
    max_steps: int = 1200
    local_search_radius: int = 4
    max_miss_streak: int = 4
    min_score: float = 0.52


def decode_image_from_data_url(data_url: str) -> np.ndarray:
    prefix = "base64,"
    if prefix not in data_url:
        raise ValueError("Unsupported image format")
    b64 = data_url.split(prefix, 1)[1]
    image_bytes = base64.b64decode(b64)
    image_np = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(image_np, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image")
    return img


def clamp_rect(x: int, y: int, w: int, h: int, W: int, H: int) -> Tuple[int, int, int, int]:
    x = max(0, min(x, W - 1))
    y = max(0, min(y, H - 1))
    w = max(2, min(w, W - x))
    h = max(2, min(h, H - y))
    return x, y, w, h


def pca_direction(points: np.ndarray) -> np.ndarray:
    if len(points) < 2:
        return np.array([1.0, 0.0], dtype=np.float32)
    pts = points.astype(np.float32)
    mean = np.mean(pts, axis=0)
    centered = pts - mean
    cov = centered.T @ centered
    vals, vecs = np.linalg.eigh(cov)
    v = vecs[:, np.argmax(vals)]
    v = v / (np.linalg.norm(v) + 1e-8)
    return v


def score_pose(
    hsv: np.ndarray,
    edges: np.ndarray,
    template_mask: np.ndarray,
    template_edges: np.ndarray,
    target_hsv: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    color_tolerance: int,
) -> float:
    patch_hsv = hsv[y : y + h, x : x + w]
    patch_edges = edges[y : y + h, x : x + w]

    if patch_hsv.shape[:2] != template_mask.shape[:2]:
        return -1.0

    color_dist = np.sqrt(np.sum((patch_hsv.astype(np.float32) - target_hsv) ** 2, axis=2))
    color_ok = (color_dist <= color_tolerance).astype(np.uint8)

    mask_pixels = np.maximum(1, int(template_mask.sum()))
    color_overlap = (color_ok * template_mask).sum() / mask_pixels

    edge_overlap = 0.0
    edge_pixels = int(template_edges.sum())
    if edge_pixels > 0:
        edge_overlap = ((patch_edges > 0).astype(np.uint8) * template_edges).sum() / edge_pixels

    local_thickness = float(color_ok.sum()) / (w * h)
    template_thickness = float(template_mask.sum()) / (w * h)
    thickness_score = 1.0 - min(1.0, abs(local_thickness - template_thickness) * 2.0)

    return float(0.55 * color_overlap + 0.25 * edge_overlap + 0.20 * thickness_score)


def select_best_local_pose(
    hsv: np.ndarray,
    edges: np.ndarray,
    template_mask: np.ndarray,
    template_edges: np.ndarray,
    target_hsv: np.ndarray,
    expected_xy: Tuple[int, int],
    w: int,
    h: int,
    cfg: FollowConfig,
):
    H, W = hsv.shape[:2]
    ex, ey = expected_xy
    best = (ex, ey, -1.0)

    for dy in range(-cfg.local_search_radius, cfg.local_search_radius + 1):
        for dx in range(-cfg.local_search_radius, cfg.local_search_radius + 1):
            nx, ny = ex + dx, ey + dy
            if nx < 0 or ny < 0 or nx + w >= W or ny + h >= H:
                continue
            s = score_pose(
                hsv,
                edges,
                template_mask,
                template_edges,
                target_hsv,
                nx,
                ny,
                w,
                h,
                cfg.color_tolerance,
            )
            if s > best[2]:
                best = (nx, ny, s)

    return best


def follow_direction(
    hsv: np.ndarray,
    edges: np.ndarray,
    template_mask: np.ndarray,
    template_edges: np.ndarray,
    target_hsv: np.ndarray,
    start_xy: Tuple[int, int],
    size_wh: Tuple[int, int],
    direction: np.ndarray,
    cfg: FollowConfig,
) -> List[Tuple[int, int, float]]:
    H, W = hsv.shape[:2]
    w, h = size_wh
    x, y = start_xy
    dx, dy = direction

    results: List[Tuple[int, int, float]] = []
    miss_streak = 0

    for _ in range(cfg.max_steps):
        expected_x = int(round(x + dx * cfg.step_px))
        expected_y = int(round(y + dy * cfg.step_px))

        if expected_x < 0 or expected_y < 0 or expected_x + w >= W or expected_y + h >= H:
            break

        bx, by, score = select_best_local_pose(
            hsv,
            edges,
            template_mask,
            template_edges,
            target_hsv,
            (expected_x, expected_y),
            w,
            h,
            cfg,
        )

        if score >= cfg.min_score:
            x, y = bx, by
            results.append((x, y, score))
            miss_streak = 0
        else:
            miss_streak += 1
            x, y = expected_x, expected_y
            if miss_streak > cfg.max_miss_streak:
                break

    return results


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/api/follow")
def api_follow():
    payload = request.get_json(force=True)
    img_data = payload["imageData"]
    roi = payload["roi"]
    picked_color = payload["pickedColor"]

    cfg = FollowConfig(
        color_tolerance=int(payload.get("colorTolerance", 28)),
        step_px=max(1, int(payload.get("stepPx", 2))),
        min_score=float(payload.get("minScore", 0.52)),
    )

    bgr = decode_image_from_data_url(img_data)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160)

    H, W = bgr.shape[:2]
    x, y, w, h = clamp_rect(int(roi["x"]), int(roi["y"]), int(roi["w"]), int(roi["h"]), W, H)

    template_hsv = hsv[y : y + h, x : x + w]
    target_hsv = np.array(picked_color, dtype=np.float32)

    dist = np.sqrt(np.sum((template_hsv.astype(np.float32) - target_hsv) ** 2, axis=2))
    template_mask = (dist <= cfg.color_tolerance).astype(np.uint8)

    if template_mask.sum() < max(10, int(0.02 * w * h)):
        return jsonify({"error": "В эталоне слишком мало пикселей выбранного цвета."}), 400

    template_edges = ((edges[y : y + h, x : x + w] > 0).astype(np.uint8) * template_mask).astype(np.uint8)

    ys, xs = np.where(template_mask > 0)
    points = np.column_stack([xs, ys])
    direction = pca_direction(points)

    start = (x, y)
    forward = follow_direction(
        hsv,
        edges,
        template_mask,
        template_edges,
        target_hsv,
        start,
        (w, h),
        direction,
        cfg,
    )
    backward = follow_direction(
        hsv,
        edges,
        template_mask,
        template_edges,
        target_hsv,
        start,
        (w, h),
        -direction,
        cfg,
    )

    track = list(reversed(backward)) + [(x, y, 1.0)] + forward
    boxes = [{"x": int(px), "y": int(py), "w": int(w), "h": int(h), "score": float(sc)} for px, py, sc in track]

    centers = [{"x": int(px + w / 2), "y": int(py + h / 2)} for px, py, _ in track]

    return jsonify(
        {
            "trajectoryType": "line (PCA-guided)",
            "templateThickness": float(template_mask.sum()) / float(w * h),
            "boxes": boxes,
            "centers": centers,
            "stats": {
                "count": len(track),
                "forward": len(forward),
                "backward": len(backward),
                "colorTolerance": cfg.color_tolerance,
                "stepPx": cfg.step_px,
                "minScore": cfg.min_score,
            },
        }
    )


if __name__ == "__main__":
    app.run(debug=True)
