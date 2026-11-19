"""Runner support for the FSM design variants (Phase C preparation, 2026-11-19).

Run:  python3 -m pytest evaluation/tests -q
"""

import csv
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import run_batch as rb  # noqa: E402

# Start-up lines printed by real runs on 2026-11-19 (launch logs):
# reproduction run repro_wsl/A/0 (no variant) and the Phase B check run (skip PA)
LINE_NO_VARIANT = ('FSM variants: skip_pa_warning=False, sustained_confirmation_ratio=0, '
                   'compliance_aware_approach=off, frame_topics=0')
LINE_SKIP_PA = ('FSM variants: skip_pa_warning=True, sustained_confirmation_ratio=0, '
                'compliance_aware_approach=off, frame_topics=0')


# ------------------------------------------------------------ settings

def test_no_variant_is_empty():
    v = rb.variant_settings()
    assert v == {'fsm': {}, 'human': {}, 'tag': ''}


def test_skip_pa_sets_the_phase_b_human_rule():
    v = rb.variant_settings(skip_pa=True)
    assert v['fsm'] == {'skip_pa_warning': True}
    assert v['human'] == {'comply_s1_fallback': 'first_heard'}
    assert v['tag'] == 'skip_pa'


@pytest.mark.parametrize('kwargs, fsm, tag', [
    ({'sustained_ratio': 0.6},
     {'sustained_confirmation_ratio': 0.6, 'frame_topics': rb.FRAME_TOPICS}, 'sustained0.6'),
    ({'compliance_aware': 'hold_s1'},
     {'compliance_aware_approach': 'hold_s1', 'frame_topics': rb.FRAME_TOPICS}, 'aware_hold_s1'),
    ({'compliance_aware': 'both'},
     {'compliance_aware_approach': 'both', 'frame_topics': rb.FRAME_TOPICS}, 'aware_both'),
])
def test_frame_based_variants_get_the_frame_topics(kwargs, fsm, tag):
    v = rb.variant_settings(**kwargs)
    assert v['fsm'] == fsm and v['human'] == {} and v['tag'] == tag


def test_combined_variants_tag_in_fixed_order():
    v = rb.variant_settings(skip_pa=True, sustained_ratio=0.6, compliance_aware='reset_first')
    assert v['tag'] == 'skip_pa_sustained0.6_aware_reset_first'
    assert v['fsm']['frame_topics'] == ['/compliance/cctv1/tracked', '/compliance/cctv2/tracked']


@pytest.mark.parametrize('kwargs', [
    {'sustained_ratio': 1.5}, {'sustained_ratio': -0.2}, {'compliance_aware': 'hold'}])
def test_invalid_variants_are_refused(kwargs):
    with pytest.raises(ValueError):
        rb.variant_settings(**kwargs)


# ------------------------------------------------------------ overlay

def overlay_for(scenario_id, variant, tmp_path):
    scenario = rb.load_scenarios(scenario_id)[0]
    return rb.build_overlay(scenario, 3, str(tmp_path), variant)


def test_overlay_without_variant_is_unchanged(tmp_path):
    scenario = rb.load_scenarios('H')[0]
    assert rb.build_overlay(scenario, 3, str(tmp_path)) == \
        rb.build_overlay(scenario, 3, str(tmp_path), rb.variant_settings())


def test_overlay_with_skip_pa_keeps_scenario_and_base_values(tmp_path):
    o = overlay_for('H', rb.variant_settings(skip_pa=True), tmp_path)
    fsm = o['compliance_fsm_node']['ros__parameters']
    pub = o['scenario_publisher_node']['ros__parameters']
    assert fsm['skip_pa_warning'] is True
    assert fsm['monitor_confirm_duration'] == 5.0          # eval_base value kept
    assert pub['comply_s1_fallback'] == 'first_heard'
    assert pub['comply_stage'] == 'S1' and pub['comply_delay_s'] == 1.0   # scenario H kept
    assert pub['seed'] == 3 and pub['scenario_id'] == 'H_s3'               # per-run kept
    assert o['yolo_cctv1']['ros__parameters']['torch_threads'] == 2


def test_overlay_with_compliance_aware_has_frame_topics(tmp_path):
    o = overlay_for('C', rb.variant_settings(compliance_aware='hold_s1'), tmp_path)
    fsm = o['compliance_fsm_node']['ros__parameters']
    assert fsm['compliance_aware_approach'] == 'hold_s1'
    assert fsm['frame_topics'] == rb.FRAME_TOPICS
    assert 'comply_s1_fallback' not in o['scenario_publisher_node']['ros__parameters']


# --------------------------------------------- the configuration guard

def test_expected_lines_match_what_real_runs_printed():
    assert rb.expected_log_lines(rb.variant_settings())[0] == LINE_NO_VARIANT
    assert rb.expected_log_lines(rb.variant_settings(skip_pa=True))[0] == LINE_SKIP_PA


def test_expected_lines_for_frame_based_variants():
    lines = rb.expected_log_lines(rb.variant_settings(sustained_ratio=0.6, compliance_aware='both'))
    assert lines[0] == ('FSM variants: skip_pa_warning=False, sustained_confirmation_ratio=0.6, '
                        'compliance_aware_approach=both, frame_topics=2')
    assert lines[1] == 'comply_s1_fallback=off'


def write_log(tmp_path, fsm_line, human_fallback, seed=3):
    path = tmp_path / 'launch.log'
    path.write_text(
        '[scenario_publisher_node-11] [INFO] [1.0] [scenario_publisher_node]: Scenario publisher: '
        'mode=world, scenario=smoking, device appears after 30s -> /x\n'
        '[scenario_publisher_node-11] [INFO] [1.0] [scenario_publisher_node]: Human model: '
        f'comply_stage=S1, comply_delay_s=1, comply_s1_fallback={human_fallback}\n'
        f'[human_actor_node-12] [INFO] [1.0] [human_actor_node]: Human actor node: seed={seed}, x\n'
        f'[compliance_fsm_node-20] [INFO] [1.0] [compliance_fsm_node]: {fsm_line}\n')
    return str(path)


def test_guard_accepts_a_run_that_reports_its_variant(tmp_path):
    log = write_log(tmp_path, LINE_SKIP_PA, 'first_heard')
    assert rb.config_applied(log, 3, variant=rb.variant_settings(skip_pa=True))


@pytest.mark.parametrize('fsm_line, fallback', [
    (LINE_NO_VARIANT, 'first_heard'),   # FSM did not get skip_pa_warning
    (LINE_SKIP_PA, 'off'),              # human model did not get the Phase B rule
])
def test_guard_refuses_a_run_that_did_not_get_its_variant(tmp_path, fsm_line, fallback):
    log = write_log(tmp_path, fsm_line, fallback)
    assert not rb.config_applied(log, 3, variant=rb.variant_settings(skip_pa=True))


def test_guard_refuses_a_variant_in_a_baseline_run(tmp_path):
    log = write_log(tmp_path, LINE_SKIP_PA, 'first_heard')
    assert not rb.config_applied(log, 3, variant=rb.variant_settings())


def test_guard_without_variant_is_the_old_check(tmp_path):
    log = write_log(tmp_path, LINE_SKIP_PA, 'first_heard')
    assert rb.config_applied(log, 3)          # variant=None: not checked (old behaviour)
    assert not rb.config_applied(log, 4)      # wrong seed still refused


# ------------------------------------------------------------ manifest

def test_new_manifest_gets_the_variant_column(tmp_path):
    fields = rb.manifest_fieldnames(str(tmp_path / 'new.csv'), 'skip_pa')
    assert fields[-1] == 'variant' and fields == rb.MANIFEST_FIELDS


def test_old_manifest_keeps_its_header_for_baseline_runs(tmp_path):
    old = tmp_path / 'old.csv'
    with open(old, 'w', newline='') as f:
        csv.writer(f).writerow(rb.MANIFEST_FIELDS[:-1])   # header before 'variant'
    assert rb.manifest_fieldnames(str(old), '') == rb.MANIFEST_FIELDS[:-1]


def test_old_manifest_refuses_variant_runs(tmp_path):
    old = tmp_path / 'old.csv'
    with open(old, 'w', newline='') as f:
        csv.writer(f).writerow(rb.MANIFEST_FIELDS[:-1])
    with pytest.raises(ValueError, match='own --manifest'):
        rb.manifest_fieldnames(str(old), 'skip_pa')


def test_the_committed_baseline_manifest_is_an_old_manifest():
    path = os.path.join(rb.EVAL, 'data', 'manifest.csv')
    with pytest.raises(ValueError):
        rb.manifest_fieldnames(path, 'aware_hold_s1')
