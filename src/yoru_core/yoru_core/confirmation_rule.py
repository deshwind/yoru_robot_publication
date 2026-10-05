"""C1-C7 decision rule shared by event_confirmation_node and offline analysis.

Pure functions (no ROS) so the online node, unit tests and the offline
sensitivity analysis (evaluation/) all apply exactly the same arithmetic:

  C = w_D*D + w_P*P + w_T*T + w_S*S
  confirmed  if C >= confirm_at AND C1 AND C2 AND C4 AND fp_risk != 'high'
  uncertain  if not confirmed and C >= uncertain_at
  rejected   otherwise
"""

# Dissertation weights: device, proximity, persistence, support
DEFAULT_WEIGHTS = {'w_D': 0.4, 'w_P': 0.3, 'w_T': 0.2, 'w_S': 0.1}
DEFAULT_CONFIRM_CONFIDENCE = 0.6
DEFAULT_UNCERTAIN_CONFIDENCE = 0.4


def composite_confidence(device, proximity, persistence, support,
                         weights=DEFAULT_WEIGHTS):
    # Summed in the original order so default weights give bit-identical floats
    return (weights['w_D'] * device + weights['w_P'] * proximity
            + weights['w_T'] * persistence + weights['w_S'] * support)


def is_confirmed(confidence, c1, c2, c4, fp_risk,
                 confirm_at=DEFAULT_CONFIRM_CONFIDENCE):
    return (confidence >= confirm_at and c1 and c2 and c4
            and fp_risk != 'high')


def decision_status(confirmed, confidence,
                    uncertain_at=DEFAULT_UNCERTAIN_CONFIDENCE):
    return ('confirmed' if confirmed
            else 'uncertain' if confidence >= uncertain_at
            else 'rejected')
