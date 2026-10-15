"""Compliance FSM: the default behaviour and the three evaluation variants
(skip_pa_warning, sustained_confirmation_ratio, compliance_aware_approach).

The real node is driven on a simulated clock: frames arrive at 5 Hz (as the
CCTV pipeline in simulation), the FSM ticks at 10 Hz. Timings are the
evaluation's (evaluation/config/eval_base.yaml).
"""

import json

import pytest

rclpy = pytest.importorskip('rclpy')
from rclpy.parameter import Parameter  # noqa: E402
from std_msgs.msg import String  # noqa: E402
from vision_msgs.msg import Detection2D, Detection2DArray, ObjectHypothesisWithPose  # noqa: E402

from yoru_core.compliance_fsm_node import ComplianceFsmNode  # noqa: E402

EVAL = {'monitor_confirm_duration': 5.0, 'pa_warning_duration': 3.0,
        'approach_timeout': 90.0, 'direct_warning_repeats': 3,
        'direct_warning_interval': 8.0, 'direct_warning_duration': 30.0,
        'logging_duration': 2.0, 'cooldown_duration': 60.0,
        'compliance_clear_duration': 10.0, 'target_lost_timeout': 8.0}
FRAMES = ['/compliance/cctv1/tracked']
BOX = (320.0, 240.0, 80.0, 200.0)


@pytest.fixture(scope='module', autouse=True)
def ros():
    rclpy.init()
    yield
    rclpy.shutdown()


def detection(track, box, cls='person'):
    det = Detection2D()
    det.id = track
    det.bbox.center.position.x, det.bbox.center.position.y = box[0], box[1]
    det.bbox.size_x, det.bbox.size_y = box[2], box[3]
    hyp = ObjectHypothesisWithPose()
    hyp.hypothesis.class_id = cls
    hyp.hypothesis.score = 0.9
    det.results.append(hyp)
    return det


class Sim:
    """The node on a simulated clock. confirm(t) / persons(t) say whether the
    frame at t holds a confirmed person and who is in view."""

    def __init__(self, **params):
        overrides = [Parameter(k, value=v) for k, v in {**EVAL, **params}.items()]
        self.node = ComplianceFsmNode(parameter_overrides=overrides)
        self.t = 0.0
        self.node.now_s = lambda: self.t
        self.node.state_since = 0.0
        self.events, self.pa = [], []
        publish = self.node.publish_fsm_state

        def record(previous, new, reason, track, room, **extra):
            self.events.append({'t': round(self.t, 2), 'previous': previous,
                                'new': new, 'reason': reason,
                                'stage_reached': self.node.stage_reached, **extra})
            publish(previous, new, reason, track, room, **extra)
        self.node.publish_fsm_state = record
        self.node.pa_pub.publish = self.pa.append
        self.with_frames = bool([t for t in self.node.param('frame_topics') if t])

    def run(self, until, confirm, persons=lambda t: [('c1_1', BOX)]):
        for k in range(int(round(until * 10)) + 1):
            self.t = round(k * 0.1, 1)
            if k % 2 == 0:                                   # a 5 Hz frame
                if self.with_frames:
                    frame = Detection2DArray()
                    frame.detections = [detection(i, b) for i, b in persons(self.t)]
                    self.node.frame_callback(frame, 0)
                if confirm(self.t):
                    event = Detection2DArray()
                    event.detections = [detection('c1_1', BOX)]
                    self.node.events_callback(event, 0)
                    meta = String()
                    meta.data = json.dumps({'status': 'confirmed', 'track_id': 'c1_1',
                                            'room': 'room_a', 'event_class': 'cigarette'})
                    self.node.metadata_callback(meta)
            self.node.tick()
        return self

    def transitions(self):
        return [(e['t'], e['new'], e['reason']) for e in self.events
                if e['reason'] != 'cooldown_end']

    def outcome(self):
        done = [e for e in self.events if e['new'] == 'MONITORING' and 'outcome' in e]
        return done[0] if done else None

    def close(self):
        self.node.destroy_node()


def between(start, stop):
    return lambda t: start <= t < stop


@pytest.fixture
def sim():
    made = []

    def make(**params):
        made.append(Sim(**params))
        return made[-1]
    yield make
    for s in made:
        s.close()


# ------------------------------------------------------------- defaults

def test_variants_default_off(sim):
    node = sim().node
    assert node.skip_pa is False
    assert node.sustained_ratio == 0.0
    assert node.compliance_aware == ''
    assert node.variants_active is False


def test_default_s1_five_seconds_after_a_single_confirmed_frame(sim):
    s = sim().run(20, lambda t: t == 10.0)
    assert s.transitions()[0] == (15.0, 'PA_WARNING', 'confirmed')
    assert len(s.pa) == 1


def test_default_person_who_stops_in_s1_is_reported_target_lost(sim):
    # Scenario H as implemented: stops 1 s into S1, stays in view
    s = sim().run(40, between(10, 16))
    assert s.transitions()[:2] == [(15.0, 'PA_WARNING', 'confirmed'),
                                   (18.0, 'APPROACH', 'pa_expired')]
    out = s.outcome()
    assert (out['outcome'], out['stage_reached']) == ('target_lost', 'S2')
    assert out['t'] == pytest.approx(15.8 + 8.0, abs=0.11)


# ------------------------------------------------------- skip_pa_warning

def test_skip_pa_warning_goes_straight_to_approach(sim):
    s = sim(skip_pa_warning=True).run(30, between(10, 40))
    first = s.events[0]
    assert (first['t'], first['previous'], first['new'], first['reason']) == \
        (15.0, 'MONITORING', 'APPROACH', 'confirmed')
    assert first['stage_reached'] == 'S2'
    assert s.pa == []                       # no PA warning is played


# --------------------------------------------- sustained_confirmation_ratio

def test_sustained_ratio_needs_frame_topics(sim):
    with pytest.raises(ValueError):
        sim(sustained_confirmation_ratio=0.6)


@pytest.mark.parametrize('pattern, escalates', [
    (lambda i: True, True),                 # every frame confirmed
    (lambda i: i % 5 != 4, True),           # 80 %
    (lambda i: i % 5 < 3, True),            # 60 %: exactly at the threshold
    (lambda i: i % 2 == 0, False),          # 50 %
    (lambda i: i % 5 == 0, False),          # 20 %: noise-like, scattered
])
def test_sustained_ratio_threshold(sim, pattern, escalates):
    def confirm(t):
        return t >= 10.0 and pattern(int(round((t - 10.0) / 0.2)))
    s = sim(sustained_confirmation_ratio=0.6, frame_topics=FRAMES).run(40, confirm)
    s1 = [e for e in s.transitions() if e[1] == 'PA_WARNING']
    assert bool(s1) == escalates
    if escalates:   # sustained from the start: no extra delay
        assert s1[0][0] == pytest.approx(15.0, abs=0.11)


def test_sustained_ratio_single_frame_never_escalates(sim):
    s = sim(sustained_confirmation_ratio=0.6, frame_topics=FRAMES).run(30, lambda t: t == 10.0)
    assert s.transitions() == []


def test_missed_frames_count_against_the_sustained_rule(sim):
    # the person is missed by the detector in every other frame; confirmed
    # in every frame where seen: 50 % of frames -> no escalation
    s = sim(sustained_confirmation_ratio=0.6, frame_topics=FRAMES).run(
        40, lambda t: t >= 10 and round(t / 0.2) % 2 == 0,
        persons=lambda t: [('c1_1', BOX)] if round(t / 0.2) % 2 == 0 else [])
    assert s.transitions() == []


def test_sustained_ratio_zero_is_the_default_rule(sim):
    s = sim(sustained_confirmation_ratio=0.0, frame_topics=FRAMES).run(20, lambda t: t == 10.0)
    assert s.transitions()[0] == (15.0, 'PA_WARNING', 'confirmed')


# ---------------------------------------- compliance_aware_approach: hold_s1

def test_hold_s1_person_who_stops_in_s1_ends_complied_without_approach(sim):
    s = sim(compliance_aware_approach='hold_s1', frame_topics=FRAMES).run(40, between(10, 16))
    states = [e[1] for e in s.transitions()]
    assert 'APPROACH' not in states
    hold = [e for e in s.events if e['reason'] == 'compliance_hold']
    assert hold and hold[0]['t'] == 18.0
    out = s.outcome()
    assert (out['outcome'], out['stage_reached'], out['presence']) == ('complied', 'S1', True)
    assert out['t'] == pytest.approx(15.8 + 10.0, abs=0.11)


def test_hold_s1_person_who_leaves_in_s1_ends_target_lost(sim):
    s = sim(compliance_aware_approach='hold_s1', frame_topics=FRAMES).run(
        40, between(10, 16), persons=lambda t: [('c1_1', BOX)] if t < 16.4 else [])
    out = s.outcome()
    assert (out['outcome'], out['stage_reached'], out['presence']) == ('target_lost', 'S1', False)


def test_hold_s1_sustained_violation_is_approached_as_before(sim):
    s = sim(compliance_aware_approach='hold_s1', frame_topics=FRAMES).run(25, between(10, 60))
    assert s.transitions()[:2] == [(15.0, 'PA_WARNING', 'confirmed'),
                                   (18.0, 'APPROACH', 'pa_expired')]


def test_hold_s1_released_when_evidence_returns(sim):
    s = sim(compliance_aware_approach='hold_s1', frame_topics=FRAMES).run(
        30, lambda t: 10 <= t < 16 or t >= 20)
    assert (20.0, 'APPROACH', 'hold_released') in s.transitions()


# ------------------------------------ compliance_aware_approach: reset_first

def test_reset_first_person_who_stops_in_s2_ends_complied(sim):
    s = sim(compliance_aware_approach='reset_first', frame_topics=FRAMES).run(40, between(10, 19))
    assert any(e['reason'] == 'target_lost_deferred' for e in s.events)
    out = s.outcome()
    assert (out['outcome'], out['stage_reached'], out['presence']) == ('complied', 'S2', True)
    assert out['t'] == pytest.approx(18.8 + 10.0, abs=0.11)


def test_reset_first_person_who_leaves_in_s2_is_still_target_lost(sim):
    # Scenario C: walks out of view during the approach
    s = sim(compliance_aware_approach='reset_first', frame_topics=FRAMES).run(
        40, between(10, 19), persons=lambda t: [('c1_1', BOX)] if t < 19.2 else [])
    out = s.outcome()
    assert (out['outcome'], out['stage_reached'], out['presence']) == ('target_lost', 'S2', False)
    assert out['t'] == pytest.approx(18.8 + 8.0, abs=0.11)


def test_reset_first_matches_a_moved_person_by_box_overlap(sim):
    # the tracker gave the person a new ID, but the box still overlaps
    moved = (330.0, 240.0, 80.0, 200.0)
    s = sim(compliance_aware_approach='reset_first', frame_topics=FRAMES).run(
        40, between(10, 19), persons=lambda t: [('c1_1', BOX)] if t < 19 else [('c1_7', moved)])
    assert s.outcome()['outcome'] == 'complied'


def test_reset_first_without_frames_behaves_as_default(sim):
    s = sim(compliance_aware_approach='reset_first').run(40, between(10, 19))
    out = s.outcome()
    assert (out['outcome'], out['stage_reached']) == ('target_lost', 'S2')
    assert out['t'] == pytest.approx(18.8 + 8.0, abs=0.11)


def test_both_modes_person_who_stops_in_s1(sim):
    s = sim(compliance_aware_approach='both', frame_topics=FRAMES).run(40, between(10, 16))
    out = s.outcome()
    assert (out['outcome'], out['stage_reached']) == ('complied', 'S1')


def test_invalid_variant_values_are_refused(sim):
    with pytest.raises(ValueError):
        sim(compliance_aware_approach='always')
    with pytest.raises(ValueError):
        sim(frame_topics=['/a', '/b'])      # one events topic, two frame topics
