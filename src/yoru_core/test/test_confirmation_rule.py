"""Phase 1 regression test: parameterised weights reproduce V2 decisions.

1. Pure-rule checks against the hand-computed simulation scenarios.
2. Node equivalence: the live EventConfirmationNode with default parameters
   and a frozen copy of the original V2 callback are fed identical random
   frame sequences; every published metadata string and every confirmed
   track must match exactly.

Run:  python3 -m pytest src/yoru_core/test -q   (with ROS 2 sourced)
"""

import os
import random
import sys

import pytest
import rclpy
from rclpy.parameter import Parameter
from vision_msgs.msg import Detection2D, Detection2DArray, ObjectHypothesisWithPose

from yoru_core import confirmation_rule as rule
from yoru_core.event_confirmation_node import EventConfirmationNode

sys.path.insert(0, os.path.dirname(__file__))
from reference_event_confirmation_v2 import ReferenceV2  # noqa: E402


# ------------------------------------------------------------- pure rule

def test_default_weights_are_the_dissertation_weights():
    assert rule.DEFAULT_WEIGHTS == {'w_D': 0.4, 'w_P': 0.3, 'w_T': 0.2, 'w_S': 0.1}
    assert rule.DEFAULT_CONFIRM_CONFIDENCE == 0.6
    assert rule.DEFAULT_UNCERTAIN_CONFIDENCE == 0.4


@pytest.mark.parametrize('support, expected', [
    (0.5, 0.802),   # Scenario A: smoking (hand_mouth 0.2 + smoke 0.3)
    (0.2, 0.772),   # Scenario A-V: vaping (hand_mouth only)
    (0.0, 0.752),   # Scenario C: cigarette, no support injected
])
def test_scenario_composites(support, expected):
    # scenario_publisher: D=0.78, device in mouth region -> P=0.8, T=1 at C4
    c = rule.composite_confidence(0.78, 0.8, 1.0, support)
    assert round(c, 3) == expected
    assert rule.is_confirmed(c, True, True, True, 'low')


def test_composite_bit_identical_to_v2_expression():
    rng = random.Random(0)
    for _ in range(10000):
        d, p, t, s = (rng.random() for _ in range(4))
        assert rule.composite_confidence(d, p, t, s) == \
            0.4 * d + 0.3 * p + 0.2 * t + 0.1 * s


@pytest.mark.parametrize('c1, c2, c4, risk, expected', [
    (True, True, True, 'low', True),
    (True, True, True, 'overridden', True),
    (True, True, True, 'high', False),
    (False, True, True, 'low', False),
    (True, False, True, 'low', False),
    (True, True, False, 'low', False),
])
def test_hard_gates(c1, c2, c4, risk, expected):
    assert rule.is_confirmed(0.9, c1, c2, c4, risk) is expected


def test_threshold_and_uncertain_band():
    assert rule.is_confirmed(0.6, True, True, True, 'low')
    assert not rule.is_confirmed(0.5999, True, True, True, 'low')
    assert rule.decision_status(False, 0.4) == 'uncertain'
    assert rule.decision_status(False, 0.3999) == 'rejected'
    assert rule.decision_status(True, 0.1) == 'confirmed'


# ------------------------------------------------------- node equivalence

class Capture:
    def __init__(self):
        self.msgs = []

    def publish(self, msg):
        self.msgs.append(msg)


@pytest.fixture(scope='module')
def ros():
    rclpy.init()
    yield
    rclpy.shutdown()


def make_node():
    node = EventConfirmationNode()
    node.confirmed_pub = Capture()
    node.metadata_pub = Capture()
    return node


def det(cls, score, cx, cy, w, h, track_id=''):
    d = Detection2D()
    d.id = track_id
    d.bbox.center.position.x = float(cx)
    d.bbox.center.position.y = float(cy)
    d.bbox.size_x = float(w)
    d.bbox.size_y = float(h)
    hyp = ObjectHypothesisWithPose()
    hyp.hypothesis.class_id = cls
    hyp.hypothesis.score = float(score)
    d.results.append(hyp)
    return d


def random_frame(rng, track_pool, phone_holder=None):
    """A frame mixing persons, devices at/away from mouths, support,
    confounders and malformed detections - biased so that every decision
    branch (confirmed, uncertain, rejected, override, vape hint) occurs.
    phone_holder: a track that keeps a phone at its mouth in most frames."""
    frame = Detection2DArray()
    persons = []
    if phone_holder and rng.random() < 0.9:
        frame.detections.append(det('person', 0.9, 200, 240, 60, 150, phone_holder))
        frame.detections.append(det('mobile_phone', rng.uniform(0.4, 0.9),
                                    200, 190, 20, 12))
    for track_id in rng.sample(track_pool, rng.randint(0, len(track_pool))):
        w, h = rng.uniform(40, 120), rng.uniform(100, 260)
        cx, cy = rng.uniform(60, 580), rng.uniform(130, 350)
        persons.append((cx, cy, w, h))
        frame.detections.append(det('person', rng.uniform(0.55, 0.99),
                                    cx, cy, w, h, track_id))
    for cx, cy, w, h in persons:
        mouth = (cx + rng.uniform(-10, 10), cy - h / 2 + rng.uniform(0.05, 0.5) * h)
        if rng.random() < 0.85:
            frame.detections.append(det(
                rng.choice(('cigarette', 'vape_device')), rng.uniform(0.5, 0.95),
                mouth[0], mouth[1], rng.uniform(8, 60), rng.uniform(6, 40)))
        if rng.random() < 0.5:
            frame.detections.append(det(
                rng.choice(('smoke_vapour', 'hand_mouth_gesture', 'hand_face')),
                rng.uniform(0.3, 0.9), mouth[0] + rng.uniform(-40, 40),
                mouth[1] + rng.uniform(-40, 40), rng.uniform(20, 80),
                rng.uniform(20, 60)))
        if rng.random() < 0.25:
            frame.detections.append(det(
                rng.choice(('pen', 'mobile_phone', 'straw')),
                rng.uniform(0.4, 0.9), mouth[0], mouth[1], 20, 12))
    if rng.random() < 0.2:  # stray device somewhere in the image
        frame.detections.append(det('cigarette', rng.uniform(0.5, 0.95),
                                    rng.uniform(0, 640), rng.uniform(0, 480), 20, 10))
    if rng.random() < 0.1:  # detection without results is skipped
        frame.detections.append(Detection2D())
    rng.shuffle(frame.detections)
    return frame


@pytest.mark.parametrize('seed', range(40))
def test_node_defaults_reproduce_v2_decisions(ros, seed):
    rng = random.Random(seed)
    node, ref = make_node(), ReferenceV2()
    track_pool = ['c1_1000', 'c1_1001', 'c1_1002', '']  # '' = untracked
    phone_holder = 'c1_2000' if seed % 4 == 0 else None
    try:
        for _ in range(150):
            frame = random_frame(rng, track_pool, phone_holder)
            n_meta, n_conf = len(node.metadata_pub.msgs), len(node.confirmed_pub.msgs)
            node.tracked_callback(frame)
            ref_confirmed, ref_meta = ref.tracked_callback(frame)

            node_meta = [m.data for m in node.metadata_pub.msgs[n_meta:]]
            assert node_meta == ref_meta
            new_conf = node.confirmed_pub.msgs[n_conf:]
            node_confirmed = [d.id for m in new_conf for d in m.detections]
            assert node_confirmed == ref_confirmed
            assert node.persistence == ref.persistence
    finally:
        node.destroy_node()


def test_decision_branches_are_covered(ros):
    """Guard against a vacuous equivalence test: the random frames must
    actually produce every status the rule can emit."""
    seen = set()
    for seed in range(40):
        rng, ref = random.Random(seed), ReferenceV2()
        for _ in range(150):
            _, meta = ref.tracked_callback(random_frame(
                rng, ['c1_1000', 'c1_1001', 'c1_1002', ''],
                'c1_2000' if seed % 4 == 0 else None))
            for m in meta:
                seen.add(m.split('"status": "')[1].split('"')[0])
                if '"overridden"' in m:
                    seen.add('overridden')
    assert {'confirmed', 'uncertain', 'possible_vape', 'overridden'} <= seen


def scenario_a_frame():
    """Scenario A as injected by scenario_publisher_node (sim geometry)."""
    frame = Detection2DArray()
    px, py, pw, ph = 320.0, 240.0, 60.0, 150.0
    mx, my = px, py - ph / 2 + 0.18 * ph
    frame.detections = [
        det('person', 0.92, px, py, pw, ph, 'c1_1000'),
        det('cigarette', 0.78, mx + 8, my, 22, 12),
        det('hand_mouth_gesture', 0.7, mx, my, 50, 40),
        det('smoke_vapour', 0.6, mx + 25, my - 30, 60, 50),
    ]
    return frame


def test_scenario_a_confirms_on_fifth_frame_at_0802(ros):
    node = make_node()
    try:
        for _ in range(5):
            node.tracked_callback(scenario_a_frame())
        last = node.metadata_pub.msgs[-1].data
        assert '"status": "confirmed"' in last and '"confidence": 0.802' in last
        assert len(node.confirmed_pub.msgs) == 1  # frames 1-4 were uncertain
    finally:
        node.destroy_node()


def test_weight_parameters_take_effect(ros):
    node = make_node()
    try:
        node.set_parameters([Parameter('w_D', value=0.25), Parameter('w_P', value=0.25),
                             Parameter('w_T', value=0.25), Parameter('w_S', value=0.25)])
        for _ in range(5):
            node.tracked_callback(scenario_a_frame())
        # balanced: 0.25 * (0.78 + 0.8 + 1.0 + 0.5) = 0.77
        assert '"confidence": 0.77' in node.metadata_pub.msgs[-1].data
        node.set_parameters([Parameter('confirm_confidence', value=0.8)])
        node.tracked_callback(scenario_a_frame())
        assert '"status": "uncertain"' in node.metadata_pub.msgs[-1].data
    finally:
        node.destroy_node()


# ------------------------------------------------ Phase 2 debug records

@pytest.mark.parametrize('seed', range(10))
def test_debug_records_allow_exact_offline_replay(ros, seed):
    """Every person in every frame gets a debug record (rejected included),
    and the logged D/P/T/S + gates reproduce the online decision exactly."""
    import json
    rng = random.Random(seed)
    node = make_node()
    node.debug_pub = Capture()
    try:
        for _ in range(150):
            frame = random_frame(rng, ['c1_1000', 'c1_1001', 'c1_1002', ''],
                                 'c1_2000' if seed % 2 == 0 else None)
            n_persons = sum(1 for d in frame.detections if d.results
                            and d.results[0].hypothesis.class_id == 'person')
            before = len(node.debug_pub.msgs)
            node.tracked_callback(frame)
            records = [json.loads(m.data) for m in node.debug_pub.msgs[before:]]
            assert len(records) == n_persons
            for r in records:
                c = rule.composite_confidence(r['D'], r['P'], r['T'], r['S'],
                                              r['weights'])
                assert c == r['C']
                confirmed = rule.is_confirmed(c, r['C1'], r['C2'], r['C4'],
                                              r['C7_fp_risk'], r['confirm_confidence'])
                assert rule.decision_status(confirmed, c,
                                            r['uncertain_confidence']) == r['decision']
        decisions = {json.loads(m.data)['decision'] for m in node.debug_pub.msgs}
        assert 'rejected' in decisions  # rejected frames are now observable
    finally:
        node.destroy_node()
