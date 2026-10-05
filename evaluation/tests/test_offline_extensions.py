"""Tests for offline_extensions.py and the outcome-vs-truth columns.

Run (ROS 2 sourced): PYTHONPATH=src/yoru_core:$PYTHONPATH python3 -m pytest evaluation/tests -q
"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import offline_extensions as ox  # noqa: E402
from extract_metrics import outcome_vs_truth  # noqa: E402


def frames(**cols):
    base = dict(D=[0.7], P=[0.8], T=[1.0], S=[0.0], C1=[True], C2=[True], C4=[True],
                fp_raw=['high'])
    base.update(cols)
    return pd.DataFrame(base)


# ------------------------------------------------- deployment thresholds

def test_c7_blocks_at_baseline_but_not_at_deployment_values():
    f = frames()                      # cigarette D = 0.70 + phone at the mouth
    _, fp, conf, _ = ox.decide(f, ox.BASELINE_DEVICE, ox.BASELINE_OVERRIDE)
    assert fp[0] == 'high' and not conf[0]
    _, fp, conf, _ = ox.decide(f, ox.DEPLOY_DEVICE, ox.DEPLOY_OVERRIDE)
    assert fp[0] == 'overridden' and conf[0]


def test_c7_is_inert_whenever_override_le_device_confidence():
    rng = np.random.default_rng(0)
    n = 20000
    f = frames(D=rng.uniform(0, 1, n), P=rng.uniform(0, 1, n), T=rng.uniform(0, 1, n),
               S=rng.uniform(0, 0.6, n), C1=rng.random(n) < 0.8, C2=rng.random(n) < 0.8,
               C4=rng.random(n) < 0.8, fp_raw=rng.choice(['low', 'high'], n))
    _, fp, _, _ = ox.decide(f, 0.3, 0.3)
    c2 = f['C2'].to_numpy() & (f['D'].to_numpy() > 0.3)
    assert not ((fp == 'high') & c2).any()          # nothing confirmable is ever blocked


# -------------------------------------------------- sustained rule

def counter_from(times):
    ts = np.array(times)
    return lambda t0, t1: float(((ts > t0) & (ts <= t1)).sum())


GRID = list(np.round(np.arange(0.0, 30.0, 0.2), 3))       # 5 Hz YOLO frames


def test_baseline_rule_is_first_confirmed_frame_plus_5s():
    assert ox.escalation_times([10.0], counter_from(GRID), -math.inf, math.inf, False) == 15.0


@pytest.mark.parametrize('share, escalates', [(1.0, True), (0.8, True), (0.6, True),
                                              (0.5, False), (0.16, False)])
def test_sustained_rule_threshold(share, escalates):
    window = [t for t in GRID if t >= 10.0]
    step = max(1, round(1 / share))
    conf = window[::step] if share < 1 else window
    if share == 0.8:
        conf = [t for i, t in enumerate(window) if i % 5 != 4]
    if share == 0.6:
        conf = [t for i, t in enumerate(window) if i % 5 < 3]
    t = ox.escalation_times(conf, counter_from(GRID), -math.inf, math.inf, True)
    assert np.isfinite(t) == escalates
    if escalates:
        assert t == pytest.approx(15.0, abs=0.11)    # sustained from the start: no extra delay


def test_sustained_rule_single_frame_never_escalates():
    assert np.isnan(ox.escalation_times([10.0], counter_from(GRID), -math.inf, math.inf, True))


def test_missing_frames_count_against_the_sustained_rule():
    # person not detected in half of the frames: confirmed in every frame where seen
    seen = [t for i, t in enumerate(GRID) if t >= 10.0 and i % 2 == 0]
    assert np.isnan(ox.escalation_times(seen, counter_from(GRID), -math.inf, math.inf, True))


# ------------------------------------------- seeded noise replay vs node

def test_noise_replay_matches_the_real_scenario_publisher():
    rclpy = pytest.importorskip('rclpy')
    from rclpy.parameter import Parameter
    from vision_msgs.msg import Detection2D, Detection2DArray, ObjectHypothesisWithPose
    from yoru_core.scenario_publisher_node import ScenarioPublisherNode

    rclpy.init()
    try:
        node = ScenarioPublisherNode()
        node.mode, node.scenario = 'world', 'c7_conflict'
        node.set_parameters([Parameter('seed', value=11)])
        node.init_world()
        node.set_parameters([Parameter('conf_jitter_sigma', value=0.05),
                             Parameter('dropout_prob', value=0.1),
                             Parameter('bbox_jitter_px', value=3.0)])
        from yoru_core.scenario_model import DetectionNoise
        node.noise = DetectionNoise(11, 0.05, 0.1, 3.0)
        node.violator = 'person_1'
        node.model_poses = {'person_1': (3.0, 0.3)}
        node.start_time, node.start_delay = 0.0, 0.0
        box = node.camera.person_bbox(3.0, 0.3)
        published = []
        node.det_pub.publish = published.append
        for _ in range(200):
            msg = Detection2DArray()
            d = Detection2D()
            d.bbox.center.position.x, d.bbox.center.position.y = box[0], box[1]
            d.bbox.size_x, d.bbox.size_y = box[2], box[3]
            h = ObjectHypothesisWithPose()
            h.hypothesis.class_id, h.hypothesis.score = 'person', 0.9
            d.results.append(h)
            msg.detections.append(d)
            node.world_frame(msg)
        injected = [next((x.results[0].hypothesis.score for x in m.detections
                          if x.results[0].hypothesis.class_id == 'cigarette'), None)
                    for m in published]
        node.destroy_node()
    finally:
        rclpy.shutdown()
    run = {'seed': 11, 'sigma': 0.05, 'dropout': 0.1, 'bbox_px': 3.0, 'device_score': 0.78,
           'c7_device_score': 0.70, 'scenario_type': 'c7_conflict',
           'heartbeats': json.dumps([[1.0, {'violator_matched': 200,
                                            'dropped': injected.count(None)}]])}
    seq, dropout_ok = ox.replay_scores(run)
    assert dropout_ok
    assert [s[1] if s else None for s in seq] == injected     # bit-exact, in order


# --------------------------------------------------- outcome vs truth

@pytest.mark.parametrize('outcome, truth, expected', [
    ('complied', 'true_compliance', 'compliance_correctly_recognised'),
    ('complied', 'departure', 'departure_recorded_as_compliance'),
    ('target_lost', 'true_compliance', 'compliance_recorded_as_target_lost'),
    ('target_lost', 'departure', 'departure_correctly_recorded_as_target_lost'),
    ('logged', 'continued_violation', 'continued_violation_correctly_logged'),
    ('safety_stop', 'continued_violation', 'interrupted_safety_stop'),
    ('none', 'true_compliance', 'missed_violation'),
    ('none', 'no_violation', 'correct_no_intervention'),
    ('complied', 'no_violation', 'false_intervention'),
])
def test_outcome_vs_truth(outcome, truth, expected):
    assert outcome_vs_truth(outcome, truth) == expected
