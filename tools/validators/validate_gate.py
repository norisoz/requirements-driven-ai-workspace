#!/usr/bin/env python3
"""Deterministic subset of an IPA-inspired requirements phase gate.

This validator cannot authenticate humans or establish the semantic truth of a requirement.
Do not set `externally_verified` through an LLM or an untrusted file writer.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:
    raise SystemExit("ERROR: jsonschema is required. Install only according to workspace policy.") from exc

ROOT = Path(__file__).resolve().parents[1]
SEVERITIES_BLOCKING = {'CRITICAL', 'MAJOR'}


def _load_local_module(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_tailoring_mod = _load_local_module('resolve_tailoring', 'scripts/resolve_tailoring.py')
_markdown_mod = _load_local_module('render_markdown', 'scripts/render_markdown.py')


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def snapshot_digest(artifact: dict) -> str:
    keys = (
        'artifact_id', 'project_id', 'phase_id', 'version', 'content',
        'field_states', 'source_refs', 'related_artifact_ids', 'issues', 'review',
    )
    return hashlib.sha256(canonical_bytes({k: artifact.get(k) for k in keys})).hexdigest()


def validate_schema(instance: dict, schema: dict, prefix: str) -> list[str]:
    Draft202012Validator.check_schema(schema)
    return [
        f'{prefix} {"/".join(map(str, e.absolute_path))}: {e.message}'
        for e in sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: str(e.path))
    ]


def validate(
    project: dict,
    artifact: dict,
    sources: dict,
    artifact_dir: Path | None = None,
    markdown_text: str | None = None,
) -> dict:
    findings = []

    def add(code: str, message: str) -> None:
        findings.append({'code': code, 'message': message})

    for e in validate_schema(project, load_json(ROOT / 'shared/schemas/project.schema.json'), 'project'):
        add('INVALID_PROJECT_SCHEMA', e)
    for e in validate_schema(artifact, load_json(ROOT / 'shared/schemas/artifact.schema.json'), 'artifact'):
        add('INVALID_ARTIFACT_SCHEMA', e)

    phase_id = artifact.get('phase_id')
    definitions = load_json(ROOT / 'shared/phase_definitions.json')
    phase_definitions = {p['phase_id']: p for p in definitions}
    if phase_id not in phase_definitions:
        add('UNKNOWN_PHASE', f'{phase_id} is not in the phase catalog')
        return {'decision': 'BLOCKED', 'findings': findings, 'digest': snapshot_digest(artifact)}

    # Tailoring resolution (T01-T08)
    tailoring_res = _tailoring_mod.resolve_tailoring(project, phase_id, definitions)
    for tf in tailoring_res['findings']:
        add(tf['code'], tf['message'])
    required_fields = set(tailoring_res['required_fields'])

    # Phase schema validation (for LIGHT level, adjust schema required list to tailored required fields)
    phase_schema = copy.deepcopy(load_json(ROOT / f'shared/schemas/phases/{phase_id}.schema.json'))
    if tailoring_res['effective_level'] == 'LIGHT':
        phase_schema['required'] = list(tailoring_res['required_fields'])
    for e in validate_schema(artifact.get('content', {}), phase_schema, 'content'):
        add('INVALID_PHASE_SCHEMA', e)

    if project.get('project_id') != artifact.get('project_id'):
        add('PROJECT_ID_MISMATCH', 'Project id and artifact project_id differ')

    definition = phase_definitions[phase_id]
    content = artifact.get('content', {})
    attributes = project.get('attributes', {})
    provenance_map = project.get('attribute_provenance', {})
    field_states = artifact.get('field_states', {})

    for fld in definition['fields']:
        field_id = fld['field_id']
        req_type = fld['requirement']

        if req_type == 'CONDITIONAL':
            attribute_id = fld['when']['attribute']
            applicable = attributes.get(attribute_id, None)
            if applicable is None:
                add('CONDITION_UNKNOWN', f'{field_id} needs confirmed applicability of {attribute_id}')
                continue
            provenance = provenance_map.get(attribute_id, 'UNSET')
            if provenance not in ('HUMAN', 'VERIFIED_SOURCE'):
                add('UNCONFIRMED_APPLICABILITY', f'{attribute_id} is {applicable} without human or verified-source confirmation')
            if applicable is False and field_id not in required_fields:
                continue
        elif field_id not in required_fields:
            continue

        value_state = field_states.get(field_id, 'UNKNOWN')
        if value_state != 'CONFIRMED':
            add('FIELD_NOT_CONFIRMED', f'{field_id} must be CONFIRMED, got {value_state}')
        value = content.get(field_id, None)
        if value is None or value == '' or value == []:
            add('REQUIRED_MISSING', f'{field_id} is required but absent/empty')

    source_index = sources.get('sources', [])
    source_ids = {s.get('id') for s in source_index}
    if not artifact.get('source_refs'):
        add('NO_SOURCE_REFS', 'Record at least a user declaration or a retrieved reference')
    for ref in artifact.get('source_refs', []):
        if ref not in source_ids:
            add('SOURCE_MISSING', f'{ref} is absent from source_index.json')

    for issue in artifact.get('issues', []):
        iid = issue.get('issue_id')
        sev = issue.get('severity')
        st = issue.get('status')
        itype = issue.get('issue_type')
        fid = issue.get('field_id')

        if st == 'OPEN' and sev in SEVERITIES_BLOCKING:
            add('BLOCKING_ISSUE', f'{iid} is unresolved')
        if st == 'OPEN' and itype == 'MISSING_INFO':
            add('UNRESOLVED_MISSING_INFO', f'{iid} has unresolved missing information')
            missing_meta = [k for k in ('owner', 'due_date', 'escalation_target') if not issue.get(k)]
            if missing_meta:
                add('INCOMPLETE_BLOCKED_RECORD', f'{iid} lacks {", ".join(missing_meta)}')
            if fid and field_states.get(fid) == 'CONFIRMED':
                add('FIELD_STATE_ISSUE_CONFLICT', f'{fid} is CONFIRMED while OPEN MISSING_INFO issue {iid} exists')
        if st == 'ACCEPTED_RISK' and sev in SEVERITIES_BLOCKING and not issue.get('resolution_ref'):
            add('UNAUTHORIZED_RISK_ACCEPTANCE', f'{iid} lacks human risk acceptance evidence')

    # Minimum reference-presence check
    refs = artifact.get('related_artifact_ids', [])
    if refs and artifact_dir and artifact_dir.exists():
        artifact_ids = set()
        for f in artifact_dir.glob('*.json'):
            try:
                found = load_json(f)
                if isinstance(found, dict):
                    artifact_ids.add(found.get('artifact_id'))
            except Exception:
                pass
        for ref in refs:
            if ref not in artifact_ids:
                add('RELATED_ARTIFACT_MISSING', f'{ref} is absent from local artifact registry')

    # Optional Markdown consistency check
    if markdown_text is not None:
        md_findings = _markdown_mod.verify_markdown(
            artifact, markdown_text, definitions, list(required_fields)
        )
        for mf in md_findings:
            add(mf['code'], mf['message'])

    # Minimal sequential gate: prior stage must be APPROVED
    idx = int(phase_id[-2:])
    if idx > 1 and project.get('phase_status', {}).get(f'P{idx - 1:02d}') != 'APPROVED':
        add('PREVIOUS_GATE_NOT_APPROVED', f'P{idx - 1:02d} is not APPROVED')

    ready = len(findings) == 0
    review = artifact.get('review', {})
    if ready and not (
        review.get('semantic_status') == 'PASSED'
        and bool(review.get('reviewer_id'))
        and review.get('review_version') == artifact.get('version')
    ):
        add('HUMAN_REVIEW_INCOMPLETE', 'A version-matched human semantic review is required')
        ready = False

    if ready and tailoring_res['requires_cross_functional_review'] and review.get('cross_functional_reviewed') is not True:
        add('T06_CROSS_FUNCTIONAL_REVIEW_REQUIRED', 'ENHANCED tailoring requires cross_functional_reviewed=true')
        ready = False

    # 3-tier human approval check (A-1)
    approval = artifact.get('approval', {})
    digest = snapshot_digest(artifact)
    channel = approval.get('channel')
    if channel is None:
        channel = 'EXTERNAL_SYSTEM' if approval.get('externally_verified') is True else 'NONE'

    requires_external = (
        (attributes.get('requires_formal_approval') is True and tailoring_res['requires_external_approval_on_formal'])
        or tailoring_res['effective_level'] == 'ENHANCED'
    )

    base_approved = (
        approval.get('decision') == 'APPROVED'
        and bool(approval.get('approver_id'))
        and bool(approval.get('approval_id'))
        and approval.get('content_sha256') == digest
    )

    approval_valid = False
    if channel == 'EXTERNAL_SYSTEM':
        approval_valid = base_approved and approval.get('externally_verified') is True
    elif channel == 'INTERACTIVE_HUMAN':
        if approval.get('externally_verified') is True:
            add('INVALID_APPROVAL', 'INTERACTIVE_HUMAN channel cannot claim externally_verified=true')
        elif requires_external and approval.get('decision') == 'APPROVED':
            add('EXTERNAL_APPROVAL_REQUIRED', 'Formal or ENHANCED gate requires EXTERNAL_SYSTEM approval')
        else:
            approval_valid = base_approved and approval.get('externally_verified') is False
    elif channel == 'PRE_OUTPUT_ORAL':
        if approval.get('decision') == 'APPROVED':
            add('PRE_OUTPUT_ORAL_NOT_FINAL', 'PRE_OUTPUT_ORAL is pre-output confirmation and cannot finalize APPROVED gate')
    else:
        approval_valid = base_approved and approval.get('externally_verified') is True

    if approval_valid and artifact.get('status') != 'APPROVED':
        add('STATUS_APPROVAL_MISMATCH', 'A valid approval requires artifact status APPROVED')
    if artifact.get('status') == 'APPROVED' and not approval_valid:
        add('STATUS_APPROVAL_MISMATCH', 'Artifact marked APPROVED without valid approval')
    if approval.get('decision') == 'APPROVED' and not approval_valid:
        add('INVALID_APPROVAL', 'Approved state requires valid channel attestation and matching snapshot digest')

    if len(findings) > 0:
        decision = 'BLOCKED'
    elif approval_valid:
        decision = 'PASS'
    else:
        decision = 'READY_FOR_REVIEW'

    note = 'PASS means deterministic checks met; it does not prove semantic truth.'
    if decision == 'PASS' and channel == 'INTERACTIVE_HUMAN':
        note = 'PASS via INTERACTIVE_HUMAN channel (externally_verified=false; not backed by an external identity/approval system).'

    return {
        'phase_id': phase_id,
        'tailoring_level': tailoring_res['effective_level'],
        'decision': decision,
        'findings': findings,
        'digest': digest,
        'note': note,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Requirements agent phase gate validator')
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--artifact', required=True, type=Path)
    parser.add_argument('--source-index', default=ROOT / 'sources/source_index.json', type=Path)
    parser.add_argument('--artifact-dir', default=ROOT / 'artifacts', type=Path)
    parser.add_argument('--markdown', default=None, type=Path, help='Optional Markdown file to verify against JSON')
    parser.add_argument('--show-digest', action='store_true')
    args = parser.parse_args()
    project = load_json(args.project)
    artifact = load_json(args.artifact)
    sources = load_json(args.source_index)
    md_text = args.markdown.read_text(encoding='utf-8') if args.markdown else None
    result = validate(project, artifact, sources, args.artifact_dir, md_text)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['decision'] == 'BLOCKED':
        raise SystemExit(2)
    if result['decision'] == 'READY_FOR_REVIEW':
        raise SystemExit(3)


if __name__ == '__main__':
    main()
