"""Phase 3 tests: simulated human response model.

Run:  PYTHONPATH=src/yoru_core:$PYTHONPATH python3 -m pytest src/yoru_core/test -q
"""

import json

import pytest
import rclpy
from rclpy.parameter import Parameter

from yoru_core.human_actor_node import DEFAULT_STARTS
from yoru_core.scenario_model import (CameraModel, DetectionNoise, flat_to_triples,
                                      scenario_layout)
from yoru_core.scenario_publisher_node import ScenarioPublisherNode, box_iou

CCTV1 = CameraModel((5.8, 0.0, 2.5, 0.0, 0.55, 3.14159), 1.3)


# ----------------------------------------------------------- camera model

@pytest.mark.parametrize('position, yolo_box', [
    # YOLOv8n person boxes measured on rendered cctv1 frames of the
    # plugin-driven actor (evidence/phase3/projection_check.txt)
    ((3.0, 0.3), (358, 243, 78, 225)),
    ((2.21, -1.18), (191, 187, 67, 171)),
])
def test_projection_matches_rendered_yolo_boxes(position, yolo_box):
    projected = CCTV1.person_bbox(*position)
    assert abs(projected[0] - yolo_box[0]) < 10          # same column
    assert box_iou(projected, yolo_box) > 0.5             # same person


def test_default_start_positions_are_fully_visible_and_safe():
    for x, y, _ in flat_to_triples(DEFAULT_STARTS):
        box = CCTV1.person_bbox(x, y)
        assert box is not None, (x, y)
        assert 20 < box[0] - box[2] / 2 and box[0] + box[2] / 2 < 620
        assert ((x - 1.8) ** 2 + y ** 2) ** 0.5 >= 1.2   # clear of the camera spot


def test_out_of_view_positions():
    assert not CCTV1.visible(5.5, -3.6)   # exit corner used for target loss
    assert not CCTV1.visible(8.0, 6.0)    # parked outside the building


# ---------------------------------------------------------------- layout

def test_layout_is_seeded_and_has_one_violator():
    starts = flat_to_triples(DEFAULT_STARTS)
    actors = ['person_1', 'person_2', 'person_3']
    for seed in range(50):
        a = scenario_layout(seed, 3, starts, actors)
        assert a == scenario_layout(seed, 3, starts, actors)
        assert sum(p['role'] == 'violator' for p in a) == 1
        assert len({(p['x'], p['y']) for p in a}) == 3
    violators = {next(p['actor'] for p in scenario_layout(s, 3, starts, actors)
                      if p['role'] == 'violator') for s in range(50)}
    assert violators == set(actors)      # every actor gets to be the violator
    spots = {(scenario_layout(s, 1, starts, actors)[0]['x']) for s in range(50)}
    assert len(spots) > 3                # start position really varies with seed


def test_no_violator_option():
    layout = scenario_layout(1, 2, flat_to_triples(DEFAULT_STARTS),
                             ['person_1', 'person_2'], violator_present=False)
    assert all(p['role'] == 'bystander' for p in layout)


# ----------------------------------------------------------------- noise

def test_zero_noise_is_identity():
    n = DetectionNoise(7)
    assert n.score(0.78) == 0.78
    assert n.box(1, 2, 3, 4) == (1, 2, 3, 4)
    assert not any(n.dropped() for _ in range(1000))


def test_noise_is_seeded_and_has_requested_statistics():
    a = DetectionNoise(3, score_sigma=0.05, dropout_prob=0.2, bbox_px=4.0)
    b = DetectionNoise(3, score_sigma=0.05, dropout_prob=0.2, bbox_px=4.0)
    seq_a = [(a.dropped(), a.score(0.78), a.box(100, 100, 20, 10)) for _ in range(5000)]
    seq_b = [(b.dropped(), b.score(0.78), b.box(100, 100, 20, 10)) for _ in range(5000)]
    assert seq_a == seq_b
    drop_rate = sum(d for d, _, _ in seq_a) / len(seq_a)
    assert 0.18 < drop_rate < 0.22
    scores = [s for _, s, _ in seq_a]
    mean = sum(scores) / len(scores)
    sd = (sum((s - mean) ** 2 for s in scores) / len(scores)) ** 0.5
    assert abs(mean - 0.78) < 0.005 and abs(sd - 0.05) < 0.005


# ---------------------------------------- scenario publisher: compliance

@pytest.fixture(scope='module')
def ros():
    rclpy.init()
    yield
    rclpy.shutdown()


def world_node(stage, scenario='smoking', delay=5.0):
    node = ScenarioPublisherNode.__new__(ScenarioPublisherNode)
    ScenarioPublisherNode.__init__(node)
    node.set_parameters([Parameter('mode', value='world')])
    node.mode = 'world'
    node.scenario = scenario
    node.init_world()
    node.set_parameters([Parameter('comply_stage', value=stage),
                         Parameter('comply_delay_s', value=delay)])
    node.published = []
    node.gt_pub.publish = lambda m: node.published.append(json.loads(m.data))
    return node


@pytest.mark.parametrize('stage, warnings, triggers_on', [
    ('S1', ['S1', 'S3', 'S3', 'S3'], 0),
    ('S3_first', ['S1', 'S3', 'S3', 'S3'], 1),
    ('S3_last', ['S1', 'S3', 'S3', 'S3'], 3),
    ('none', ['S1', 'S3', 'S3', 'S3'], None),
])
def test_comply_stage_reacts_to_the_right_warning(ros, stage, warnings, triggers_on):
    node = world_node(stage)
    try:
        for i, kind in enumerate(warnings):
            node.warning_heard(kind)
            triggered = node.comply_time is not None
            assert triggered == (triggers_on is not None and i >= triggers_on), (stage, i)
        if triggers_on is not None:
            trig = [e for e in node.published if e['event'] == 'comply_trigger']
            assert len(trig) == 1 and trig[0]['comply_stage'] == stage
    finally:
        node.destroy_node()


# Phase B (2026-11-19): with the FSM variant skip_pa_warning no PA warning is
# played, so the warnings heard are only the direct ones (S3).
NO_PA = ['S3', 'S3', 'S3']
WITH_PA = ['S1', 'S3', 'S3', 'S3']


def set_fallback(node, value):
    node.set_parameters([Parameter('comply_s1_fallback', value=value)])


def test_s1_person_never_complies_without_pa_by_default(ros):
    """The gap Phase B closes: default behaviour, no PA warning heard."""
    node = world_node('S1', delay=1.0)
    try:
        assert node.get_parameter('comply_s1_fallback').value == ''
        for kind in NO_PA:
            node.warning_heard(kind)
        assert node.comply_time is None
        assert not [e for e in node.published if e['event'] == 'comply_trigger']
    finally:
        node.destroy_node()


def test_first_heard_complies_after_first_direct_warning_without_pa(ros):
    node = world_node('S1', delay=1.0)
    try:
        set_fallback(node, 'first_heard')
        node.warning_heard('S3')
        assert node.comply_time is not None
        assert abs(node.comply_time - (node.now_s() + 1.0)) < 0.05   # same delay
        first = node.comply_time
        node.warning_heard('S3')
        node.warning_heard('S3')
        assert node.comply_time == first                            # only once
        trig = [e for e in node.published if e['event'] == 'comply_trigger']
        assert len(trig) == 1
        assert trig[0]['warning'] == 'S3' and trig[0]['direct_count'] == 1
        assert trig[0]['comply_stage'] == 'S1' and trig[0]['s1_fallback'] is True
        assert trig[0]['comply_s1_fallback'] == 'first_heard'         # recorded in truth
    finally:
        node.destroy_node()


@pytest.mark.parametrize('stage, triggers_on', [
    ('S1', 0), ('S3_first', 1), ('S3_last', 3), ('none', None)])
def test_first_heard_changes_nothing_when_the_pa_warning_plays(ros, stage, triggers_on):
    """Same trigger as the default for every comply_stage when S1 is heard."""
    node = world_node(stage)
    try:
        set_fallback(node, 'first_heard')
        for i, kind in enumerate(WITH_PA):
            node.warning_heard(kind)
            assert (node.comply_time is not None) == \
                (triggers_on is not None and i >= triggers_on), (stage, i)
        trig = [e for e in node.published if e['event'] == 'comply_trigger']
        assert all(e['s1_fallback'] is False for e in trig)
    finally:
        node.destroy_node()


@pytest.mark.parametrize('stage, triggers_on', [
    ('S3_first', 0), ('S3_last', 2), ('none', None)])
def test_first_heard_leaves_other_stages_alone_without_pa(ros, stage, triggers_on):
    node = world_node(stage)
    try:
        set_fallback(node, 'first_heard')
        for i, kind in enumerate(NO_PA):
            node.warning_heard(kind)
            assert (node.comply_time is not None) == \
                (triggers_on is not None and i >= triggers_on), (stage, i)
    finally:
        node.destroy_node()


def test_first_heard_confounder_never_complies(ros):
    node = world_node('S1', scenario='phone')
    try:
        set_fallback(node, 'first_heard')
        for kind in NO_PA:
            node.warning_heard(kind)
        assert node.comply_time is None
    finally:
        node.destroy_node()


@pytest.mark.parametrize('value, ok', [
    ('', True), ('first_heard', True), ('first-heard', False), ('S3', False)])
def test_unknown_comply_s1_fallback_is_refused(value, ok):
    from yoru_core.scenario_publisher_node import check_comply_s1_fallback
    if ok:
        check_comply_s1_fallback(value)
    else:
        with pytest.raises(ValueError):
            check_comply_s1_fallback(value)


def test_confounder_never_complies(ros):
    node = world_node('S1', scenario='phone')
    try:
        node.warning_heard('S1')
        assert node.comply_time is None and not node.is_violation()
    finally:
        node.destroy_node()


def test_brief_device_is_shorter_than_persistence_window(ros):
    node = world_node('none', scenario='brief_device')
    try:
        node.start_time, node.start_delay = 0.0, 10.0
        period = node.get_parameter('brief_device_period').value
        on = [t / 100.0 for t in range(1000, 1000 + int(period * 100))
              if node.device_active(t / 100.0)]
        assert 0.25 <= len(on) / 100.0 <= 0.35        # 0.3 s per period
        assert len(on) / 100.0 < 5 / 5.0             # < 5 YOLO frames at 5 Hz
    finally:
        node.destroy_node()


def test_injections_by_scenario(ros):
    from vision_msgs.msg import BoundingBox2D
    box = BoundingBox2D()
    box.center.position.x, box.center.position.y = 300.0, 240.0
    box.size_x, box.size_y = 60.0, 200.0
    expected = {
        'smoking': {'cigarette', 'hand_mouth_gesture', 'smoke_vapour'},
        'vaping': {'vape_device', 'hand_mouth_gesture'},
        'phone': {'mobile_phone'}, 'pen': {'pen'}, 'straw': {'straw'},
        'c7_conflict': {'cigarette', 'mobile_phone'}, 'walking': set(),
    }
    for scenario, classes in expected.items():
        node = world_node('none', scenario=scenario)
        try:
            got = node.injections(box)
            assert {c for c, *_ in got} == classes, scenario
            if scenario == 'c7_conflict':
                cig = next(s for c, s, *_ in got if c == 'cigarette')
                assert cig < 0.75   # below the C7 override: C7 decides
        finally:
            node.destroy_node()


def test_legacy_modes_untouched(ros):
    """Default construction (mode auto) must not create world-mode state."""
    node = ScenarioPublisherNode()
    try:
        assert node.mode == 'auto'
        assert not hasattr(node, 'noise') and not hasattr(node, 'camera')
        assert not node.has_parameter('comply_stage')
    finally:
        node.destroy_node()



# ----------------------------------------- FSM instrumentation (Phase 4)

def test_outcome_event_reports_the_stage_reached(ros):
    """The final transition must carry the escalation's stage (e.g. S3),
    not the S0 the FSM resets to."""
    from yoru_core.compliance_fsm_node import ComplianceFsmNode
    node = ComplianceFsmNode()
    events = []
    node.fsm_state_pub.publish = lambda m: events.append(json.loads(m.data))
    try:
        node.target_track, node.stage_reached, node.state = 'c1_1000', 'S3', 'DIRECT_WARNING'
        node.finish_escalation('complied')
        assert events[-1]['new_state'] == 'MONITORING'
        assert events[-1]['reason'] == 'complied'
        assert events[-1]['stage_reached'] == 'S3'
        assert node.stage_reached == 'S0'          # FSM behaviour unchanged
    finally:
        node.destroy_node()
