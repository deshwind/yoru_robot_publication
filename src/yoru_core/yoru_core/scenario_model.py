"""Simulated human response model: pure helpers (no ROS).

Shared by human_actor_node (moves the Gazebo actors) and
scenario_publisher_node (injects detections) so both use one seeded layout,
one camera model and one noise model.

  CameraModel     pinhole projection of a Gazebo camera (pose + hfov)
  scenario_layout seeded choice of start positions and of the violator
  DetectionNoise  seeded confidence jitter, frame dropout and bbox jitter
"""

import math
import random


class CameraModel:
    """Gazebo camera: x forward, y left, z up; pose = (x, y, z, roll, pitch, yaw)
    in the world, as in the <model><pose> of the world file."""

    def __init__(self, pose, hfov, width=640, height=480):
        x, y, z, roll, pitch, yaw = pose
        self.position = (x, y, z)
        self.width, self.height = width, height
        self.fx = (width / 2.0) / math.tan(hfov / 2.0)
        cr, sr = math.cos(roll), math.sin(roll)
        cp, sp = math.cos(pitch), math.sin(pitch)
        cy, sy = math.cos(yaw), math.sin(yaw)
        # Columns of R = Rz(yaw) Ry(pitch) Rx(roll): camera axes in the world
        self.forward = (cy * cp, sy * cp, -sp)
        self.left = (cy * sp * sr - sy * cr, sy * sp * sr + cy * cr, cp * sr)
        self.up = (cy * sp * cr + sy * sr, sy * sp * cr - cy * sr, cp * cr)

    def project(self, point):
        """World point -> (u, v) pixels, or None if behind the camera."""
        d = [p - c for p, c in zip(point, self.position)]
        xc = sum(a * b for a, b in zip(d, self.forward))
        if xc <= 0.05:
            return None
        yc = sum(a * b for a, b in zip(d, self.left))
        zc = sum(a * b for a, b in zip(d, self.up))
        return (self.width / 2.0 - self.fx * yc / xc,
                self.height / 2.0 - self.fx * zc / xc)

    def person_bbox(self, x, y, height=1.75, width=0.5):
        """Projected (cx, cy, w, h) of a standing person, or None if any
        part needed for detection is outside the image."""
        feet = self.project((x, y, 0.0))
        head = self.project((x, y, height))
        if feet is None or head is None:
            return None
        side = self.project((x + 0.0, y + width / 2.0, height / 2.0))
        mid = self.project((x, y, height / 2.0))
        half_w = abs(side[0] - mid[0]) if side and mid else 10.0
        top, bottom = min(head[1], feet[1]), max(head[1], feet[1])
        cx = (head[0] + feet[0]) / 2.0
        if cx < 0 or cx > self.width or top < 0 or bottom > self.height:
            return None
        return (cx, (top + bottom) / 2.0, max(2.0 * half_w, 1.0), bottom - top)

    def visible(self, x, y, height=1.75):
        return self.person_bbox(x, y, height) is not None


def scenario_layout(seed, n_persons, start_positions, actor_names,
                    violator_present=True):
    """Seeded assignment of actors to distinct start positions.

    start_positions: list of (x, y, yaw); actor_names: available actors.
    Returns [{'actor', 'x', 'y', 'yaw', 'role'}] with exactly one
    'violator' (if violator_present) and the rest 'bystander'.
    """
    if n_persons > min(len(start_positions), len(actor_names)):
        raise ValueError('more persons than start positions or actors')
    rng = random.Random(seed)
    spots = rng.sample(list(start_positions), n_persons)
    violator = rng.randrange(n_persons) if violator_present else -1
    return [{'actor': actor_names[i], 'x': spot[0], 'y': spot[1], 'yaw': spot[2],
             'role': 'violator' if i == violator else 'bystander'}
            for i, spot in enumerate(spots)]


class DetectionNoise:
    """Seeded detector noise for injected (specialist-model) detections."""

    def __init__(self, seed, score_sigma=0.0, dropout_prob=0.0, bbox_px=0.0):
        # Separate stream from the layout so changing noise settings never
        # changes which actor is the violator for the same seed
        self.rng = random.Random(f'noise-{seed}')
        self.score_sigma = score_sigma
        self.dropout_prob = dropout_prob
        self.bbox_px = bbox_px

    def dropped(self):
        return self.dropout_prob > 0.0 and self.rng.random() < self.dropout_prob

    def score(self, value):
        if self.score_sigma <= 0.0:
            return value
        return min(0.99, max(0.01, self.rng.gauss(value, self.score_sigma)))

    def box(self, cx, cy, w, h):
        if self.bbox_px <= 0.0:
            return cx, cy, w, h
        g = self.rng.gauss
        return (cx + g(0.0, self.bbox_px), cy + g(0.0, self.bbox_px),
                max(2.0, w + g(0.0, self.bbox_px)), max(2.0, h + g(0.0, self.bbox_px)))


def flat_to_triples(flat):
    """[x0, y0, yaw0, x1, ...] -> [(x0, y0, yaw0), ...]"""
    return [tuple(flat[i:i + 3]) for i in range(0, len(flat) - 2, 3)]
