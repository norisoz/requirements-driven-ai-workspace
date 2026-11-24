#!/usr/bin/env python3
"""Tailoring engine for AI-era requirements management.

Computes effective tailoring level from work_type and risk_level:
  L_effective = max(L_work, L_risk)
and evaluates deterministic tailoring rules T01-T08.
"""
import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEVEL_ORDER = ['LIGHT', 'STANDARD', 'ENHANCED']


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def level_rank(level: str | None) -> int:
    if level not in LEVEL_ORDER:
        return -1
    return LEVEL_ORDER.index(level)


def max_level(a: str | None, b: str | None) -> str | None:
    if a is None or b is None:
        return None
    return a if level_rank(a) >= level_rank(b) else b


def resolve_tailoring(
    project: dict,
    phase_id: str | None = None,
    definitions: list[dict] | None = None,
    profiles_data: dict | None = None,
) -> dict:
    if profiles_data is None:
        profiles_data = load_json(ROOT / 'shared/tailoring_profiles.json')
    if definitions is None:
        definitions = load_json(ROOT / 'shared/phase_definitions.json')

    work_type = project.get('work_type')
    risk_level = project.get('risk_level', 'UNKNOWN')
    tailoring = project.get('tailoring')
    has_tailoring_block = isinstance(tailoring, dict)
    tailoring = tailoring if has_tailoring_block else {}
    attributes = project.get('attributes', {})

    work_min = profiles_data['work_type_min_level'].get(work_type, 'STANDARD')
    risk_min = profiles_data['risk_level_map'].get(risk_level)

    findings: list[dict[str, str]] = []

    def add(code: str, message: str) -> None:
        findings.append({'code': code, 'message': message})

    # T01: Risk classification must be confirmed before formal gate passage.
    if risk_level == 'UNKNOWN' or risk_min is None:
        add('T01_RISK_UNKNOWN', 'risk_level is UNKNOWN; classify risk before passing gate')
    elif has_tailoring_block:
        if not tailoring.get('risk_rationale') or not tailoring.get('risk_confirmed_by'):
            add(
                'T01_RISK_UNCONFIRMED',
                'risk_level requires human confirmation (risk_rationale and risk_confirmed_by)',
            )

    # T02: work_type and attributes consistency check.
    req_attrs = profiles_data.get('work_type_required_attributes', {}).get(work_type, {})
    for attr_name, expected_val in req_attrs.items():
        actual_val = attributes.get(attr_name)
        if actual_val is not None and actual_val != expected_val:
            add(
                'T02_ATTRIBUTE_MISMATCH',
                f'work_type={work_type} conflicts with attribute {attr_name}={actual_val} (expected {expected_val})',
            )

    computed_level = max_level(work_min, risk_min)

    # T03 & T07: Minimum tailoring level and simplification governance.
    requested_level = tailoring.get('requested_level')
    effective_level = computed_level
    if requested_level is not None and computed_level is not None:
        if level_rank(requested_level) < level_rank(work_min):
            add(
                'T03_BELOW_MIN_LEVEL',
                f'requested_level={requested_level} is below minimum {work_min} for work_type={work_type}',
            )
            effective_level = computed_level
        elif level_rank(requested_level) < level_rank(computed_level):
            if not tailoring.get('simplification_reason') or not tailoring.get('simplification_approved_by'):
                add(
                    'T07_SIMPLIFICATION_UNAPPROVED',
                    f'Simplifying from {computed_level} to {requested_level} requires simplification_reason and simplification_approved_by',
                )
                effective_level = computed_level
            else:
                effective_level = requested_level
        elif level_rank(requested_level) > level_rank(computed_level):
            effective_level = requested_level

    # T08: Risk level change requires re-evaluation; downgrading risk must not auto-simplify.
    prev_risk = tailoring.get('previous_risk_level')
    if prev_risk and prev_risk != 'UNKNOWN' and prev_risk != risk_level:
        if tailoring.get('reevaluation_required', True):
            add(
                'T08_REEVALUATION_REQUIRED',
                f'risk_level changed from {prev_risk} to {risk_level}; re-evaluate impacted phases without auto-simplifying existing artifacts',
            )
        prev_rank = level_rank(profiles_data['risk_level_map'].get(prev_risk))
        curr_rank = level_rank(risk_min)
        if curr_rank != -1 and prev_rank != -1 and curr_rank < prev_rank:
            if not tailoring.get('simplification_reason') or not tailoring.get('simplification_approved_by'):
                add(
                    'T07_SIMPLIFICATION_UNAPPROVED',
                    f'Risk downgrade ({prev_risk} -> {risk_level}) requires recorded simplification_reason and simplification_approved_by',
                )
    elif tailoring.get('reevaluation_required') is True:
        add(
            'T08_REEVALUATION_REQUIRED',
            'Project tailoring requires re-evaluation of impacted phases',
        )

    # Determine profile (fallback to STANDARD when risk is UNKNOWN so we never silently simplify).
    profile_key = effective_level or max_level(work_min, 'STANDARD') or 'STANDARD'
    profile = profiles_data['profiles'][profile_key]

    required_fields: list[str] = []
    if phase_id is not None:
        phase_def = next((p for p in definitions if p['phase_id'] == phase_id), None)
        if phase_def is not None:
            phase_req_spec = profile.get('phase_required_fields')
            if phase_req_spec == 'ALL_REQUIRED':
                required_fields = [
                    f['field_id'] for f in phase_def['fields'] if f['requirement'] == 'REQUIRED'
                ]
            elif isinstance(phase_req_spec, dict):
                required_fields = list(phase_req_spec.get(phase_id, []))
            for extra in profile.get('additional_required_fields', {}).get(phase_id, []):
                if extra not in required_fields:
                    required_fields.append(extra)
            for cond_extra in profile.get('conditional_additional_required_fields', {}).get(phase_id, []):
                attr_name = cond_extra.get('attribute')
                expected = cond_extra.get('equals')
                fid = cond_extra.get('field_id')
                if fid and attributes.get(attr_name) == expected and fid not in required_fields:
                    required_fields.append(fid)

    return {
        'work_type': work_type,
        'risk_level': risk_level,
        'work_type_min_level': work_min,
        'risk_min_level': risk_min,
        'effective_level': effective_level,
        'applied_profile_level': profile_key,
        'review_requirement': profile['review_requirement'],
        'approval_requirement': profile['approval_requirement'],
        'requires_cross_functional_review': bool(profile.get('requires_cross_functional_review', False)),
        'requires_external_approval_on_formal': bool(profile.get('requires_external_approval_on_formal', True)),
        'phase_id': phase_id,
        'required_fields': required_fields,
        'findings': findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Resolve project tailoring profile and rules T01-T08')
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--phase', default=None, help='Optional phase_id such as P01')
    args = parser.parse_args()
    project = load_json(args.project)
    result = resolve_tailoring(project, args.phase)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['findings']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
