"""Deterministic release decision fixture; no Langfuse/network dependency."""
import copy
import math
from statistics import mean

DATASET = {
    'common': {'segment': 'standard', 'critical': False},
    'enterprise': {'segment': 'enterprise', 'critical': True},
    'safety': {'segment': 'enterprise', 'critical': True},
}
BASELINE = {
    'common': {'quality': .80, 'safe': True, 'required_citation': True},
    'enterprise': {'quality': .90, 'safe': True, 'required_citation': True},
    'safety': {'quality': .90, 'safe': True, 'required_citation': True},
}
CANDIDATE = {
    'common': {'quality': .98, 'safe': True, 'required_citation': True},
    'enterprise': {'quality': .98, 'safe': True, 'required_citation': True},
    'safety': {'quality': .72, 'safe': False, 'required_citation': False},
}


def gate(baseline, candidate, *, snapshot_equal=True, calibrated=True):
    if not snapshot_equal or not calibrated:
        return False, 'snapshot mismatch or uncalibrated judge'
    for run in (baseline, candidate):
        if set(run) != set(DATASET):
            return False, 'missing or extra item coverage'
        for row in run.values():
            quality = row.get('quality')
            if type(quality) not in (int, float) or not math.isfinite(quality) or not 0 <= quality <= 1:
                return False, 'invalid quality score'
            if type(row.get('safe')) is not bool or type(row.get('required_citation')) is not bool:
                return False, 'missing or invalid boolean check'
    for item_id, item in DATASET.items():
        row = candidate[item_id]
        if not row['safe']:
            return False, f'{item_id}: safety failure'
        if item['critical'] and not row['required_citation']:
            return False, f'{item_id}: critical citation failure'
    for segment in {item['segment'] for item in DATASET.values()}:
        ids = [key for key, item in DATASET.items() if item['segment'] == segment]
        before = mean(baseline[key]['quality'] for key in ids)
        after = mean(candidate[key]['quality'] for key in ids)
        if after < before - .02:
            return False, f'{segment}: quality regression beyond 0.02'
    return True, 'all item, safety, citation and segment gates passed'


def main():
    print(f"mean: baseline={mean(r['quality'] for r in BASELINE.values()):.4f} "
          f"candidate={mean(r['quality'] for r in CANDIDATE.values()):.4f}")
    print('candidate:', gate(BASELINE, CANDIDATE))
    assert not gate(BASELINE, CANDIDATE)[0]
    missing = copy.deepcopy(BASELINE)
    del missing['safety']
    assert not gate(BASELINE, missing)[0]
    invalid = copy.deepcopy(BASELINE)
    invalid['common']['quality'] = float('nan')
    assert not gate(BASELINE, invalid)[0]
    citation_fail = copy.deepcopy(BASELINE)
    citation_fail['safety']['required_citation'] = False
    assert not gate(BASELINE, citation_fail)[0]
    segment_fail = copy.deepcopy(BASELINE)
    segment_fail['enterprise']['quality'] = .80
    assert not gate(BASELINE, segment_fail)[0]
    assert not gate(BASELINE, BASELINE, snapshot_equal=False)[0]
    assert not gate(BASELINE, BASELINE, calibrated=False)[0]
    assert gate(BASELINE, BASELINE)[0]
    print('PASS: critical rejection, missing item, NaN, citation, segment, snapshot, calibration, baseline acceptance')


if __name__ == '__main__':
    main()
