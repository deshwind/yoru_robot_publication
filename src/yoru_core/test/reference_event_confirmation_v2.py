"""Frozen copy of the V2 decision logic (Yoru_bot_V2 a7a7715).

EventConfirmationNode.tracked_callback exactly as it was before the weights
became ROS parameters, with ROS publishing replaced by return values. Used
only by the regression test: do not edit.
"""

import json

from yoru_core.event_confirmation_node import (
    CONFOUNDER_CLASSES, DEVICE_CLASSES, SUPPORT_WEIGHTS, bbox_iou,
    in_mouth_region)

V2_PARAMS = {
    'person_confidence': 0.7,
    'device_confidence': 0.6,
    'proximity_iou': 0.05,
    'persistence_frames': 5,
    'confirm_confidence': 0.6,
    'uncertain_confidence': 0.4,
    'room_id': '',
    'confounder_override_confidence': 0.75,
    'vape_hint': True,
}


class ReferenceV2:

    def __init__(self, params=None):
        self.params = dict(V2_PARAMS, **(params or {}))
        self.persistence_required = int(self.params['persistence_frames'])
        self.persistence = {}
        self.phone_persistence = {}

    def tracked_callback(self, msg):
        """Returns (confirmed track IDs, metadata JSON strings) for a frame."""
        p = self.params
        person_conf_min = p['person_confidence']
        device_conf_min = p['device_confidence']
        proximity_iou_min = p['proximity_iou']
        confirm_at = p['confirm_confidence']
        uncertain_at = p['uncertain_confidence']
        published_meta = []

        persons, devices, supports, confounders = [], [], [], []
        for det in msg.detections:
            if not det.results:
                continue
            cls = det.results[0].hypothesis.class_id
            if cls == 'person':
                persons.append(det)
            elif cls in DEVICE_CLASSES:
                devices.append(det)
            elif cls in SUPPORT_WEIGHTS:
                supports.append(det)
            elif cls in CONFOUNDER_CLASSES:
                confounders.append(det)

        confirmed = []
        seen_tracks = set()

        for person in persons:
            track_id = person.id or 'untracked'
            seen_tracks.add(track_id)
            c1 = person.results[0].hypothesis.score > person_conf_min

            best_device, best_prox = None, 0.0
            for dev in devices:
                if dev.results[0].hypothesis.score <= device_conf_min:
                    continue
                iou_val = bbox_iou(person.bbox, dev.bbox)
                near_mouth = in_mouth_region(person.bbox, dev.bbox)
                if iou_val > proximity_iou_min or near_mouth:
                    prox = max(min(iou_val / 0.3, 1.0), 0.8 if near_mouth else 0.0)
                    if prox > best_prox:
                        best_device, best_prox = dev, prox
            c2 = best_device is not None
            c3 = best_prox > 0.0

            if c1 and c2 and c3:
                self.persistence[track_id] = self.persistence.get(track_id, 0) + 1
            else:
                self.persistence[track_id] = max(
                    0, self.persistence.get(track_id, 0) - 1)
            frames = self.persistence[track_id]
            c4 = frames >= self.persistence_required
            persistence_score = min(frames / float(self.persistence_required), 1.0)

            support_score = 0.0
            for sup in supports:
                if in_mouth_region(person.bbox, sup.bbox, region_fraction=0.6) or \
                        bbox_iou(person.bbox, sup.bbox) > 0.02:
                    support_score += SUPPORT_WEIGHTS[sup.results[0].hypothesis.class_id]
            support_score = min(support_score, 1.0)

            fp_risk = 'low'
            phone_at_mouth = False
            for con in confounders:
                if in_mouth_region(person.bbox, con.bbox):
                    fp_risk = 'high'
                    if con.results[0].hypothesis.class_id == 'mobile_phone':
                        phone_at_mouth = True
                    break

            device_score = best_device.results[0].hypothesis.score if c2 else 0.0
            confidence = (0.4 * device_score + 0.3 * best_prox
                          + 0.2 * persistence_score + 0.1 * support_score)

            override_at = p['confounder_override_confidence']
            if fp_risk == 'high' and c2 and device_score >= override_at:
                fp_risk = 'overridden'

            is_confirmed = (confidence >= confirm_at and c1 and c2 and c4
                            and fp_risk != 'high')

            if p['vape_hint'] and c1 \
                    and phone_at_mouth and not is_confirmed:
                self.phone_persistence[track_id] = \
                    self.phone_persistence.get(track_id, 0) + 1
            else:
                self.phone_persistence[track_id] = 0
            if self.phone_persistence.get(track_id, 0) \
                    >= self.persistence_required:
                published_meta.append(json.dumps({
                    'track_id': track_id,
                    'room': p['room_id'],
                    'status': 'possible_vape',
                    'confidence': None,
                    'event_class': 'possible_vape',
                }))
            status = ('confirmed' if is_confirmed
                      else 'uncertain' if confidence >= uncertain_at
                      else 'rejected')

            if is_confirmed:
                confirmed.append(person.id)

            if status != 'rejected':
                published_meta.append(json.dumps({
                    'track_id': track_id,
                    'room': p['room_id'],
                    'status': status,
                    'confidence': round(confidence, 3),
                    'event_class': (best_device.results[0].hypothesis.class_id
                                    if c2 else None),
                    'criteria': {
                        'C1_person': c1, 'C2_device': c2, 'C3_proximity': c3,
                        'C4_persistence': c4, 'C5_support': round(support_score, 2),
                        'C6_track': track_id != 'untracked',
                        'C7_fp_risk': fp_risk,
                    },
                    'scores': {
                        'device': round(device_score, 3),
                        'proximity': round(best_prox, 3),
                        'persistence': round(persistence_score, 3),
                        'support': round(support_score, 3),
                    },
                }))

        for stale in [t for t in self.persistence if t not in seen_tracks]:
            del self.persistence[stale]
        for stale in [t for t in self.phone_persistence
                      if t not in seen_tracks]:
            del self.phone_persistence[stale]

        return confirmed, published_meta
