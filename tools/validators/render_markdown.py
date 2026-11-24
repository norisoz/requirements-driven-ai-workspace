#!/usr/bin/env python3
"""Render human-readable Markdown from a JSON artifact (Single Source of Truth)
and verify consistency between JSON and Markdown.
"""
import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_SECTIONS = [
    '## 1. メタデータ',
    '## 2. 工程固有の内容',
    '## 3. 出典（source_refs）',
    '## 4. 関連成果物（related_artifact_ids）',
    '## 5. 確認状態（field_states）',
    '## 6. 問題管理（issues）',
    '## 7. 検証結果（review / gate）',
    '## 8. 承認情報（approval）',
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def _fmt_scalar(val: Any) -> str:
    if val is None or val == '':
        return 'なし'
    return str(val)


def _escape_cell(val: Any) -> str:
    return _fmt_scalar(val).replace('|', '\\|').replace('\n', ' ')


def render_markdown(artifact: dict, definitions: list[dict] | None = None) -> str:
    if definitions is None:
        definitions = load_json(ROOT / 'shared/phase_definitions.json')

    phase_id = artifact.get('phase_id', '')
    phase_def = next((p for p in definitions if p['phase_id'] == phase_id), None)
    phase_name = phase_def['name'] if phase_def else '不明工程'

    content = artifact.get('content', {})
    field_states = artifact.get('field_states', {})
    source_refs = artifact.get('source_refs', [])
    related_ids = artifact.get('related_artifact_ids', [])
    issues = artifact.get('issues', [])
    review = artifact.get('review', {})
    approval = artifact.get('approval', {})

    # 2. 工程固有の内容
    content_lines: list[str] = []
    if phase_def:
        fields = phase_def['fields']
    else:
        fields = [{'field_id': k, 'requirement': 'UNKNOWN'} for k in content.keys()]

    for fld in fields:
        fid = fld['field_id']
        val = content.get(fid)
        state = field_states.get(fid, 'UNKNOWN')
        content_lines.append(f'### `{fid}`（状態: `{state}`）')
        if isinstance(val, list):
            if val:
                for item in val:
                    content_lines.append(f'- {item}')
            else:
                content_lines.append('- （未入力）')
        elif val is None or val == '':
            if state == 'NOT_APPLICABLE':
                content_lines.append('- （該当なし：適用条件により非該当）')
            else:
                content_lines.append('- （未入力）')
        else:
            content_lines.append(f'- {val}')
        content_lines.append('')
    content_section = '\n'.join(content_lines).rstrip()

    # 3. 出典
    if source_refs:
        source_refs_section = '\n'.join(f'- `{ref}`' for ref in source_refs)
    else:
        source_refs_section = '- なし（理由: 出典未登録）'

    # 4. 関連成果物
    if related_ids:
        related_section = '\n'.join(f'- `{rid}`' for rid in related_ids)
    else:
        related_section = '- なし（理由: 関連成果物なし／初期工程）'

    # 5. 確認状態テーブル
    state_rows: list[str] = []
    seen_fields = set()
    for fld in fields:
        fid = fld['field_id']
        seen_fields.add(fid)
        state = field_states.get(fid, 'UNKNOWN')
        state_rows.append(f'| `{fid}` | {fld.get("requirement", "-")} | `{state}` |')
    for fid, state in field_states.items():
        if fid not in seen_fields:
            state_rows.append(f'| `{fid}` | EXTRA | `{state}` |')
    field_states_table = '\n'.join(state_rows) if state_rows else '| - | - | - |'

    # 6. 問題管理テーブル
    if issues:
        issue_rows = []
        for iss in issues:
            issue_rows.append(
                '| '
                + ' | '.join([
                    f'`{_escape_cell(iss.get("issue_id"))}`',
                    _escape_cell(iss.get('issue_type') or 'OTHER'),
                    _escape_cell(iss.get('field_id')),
                    _escape_cell(iss.get('severity')),
                    _escape_cell(iss.get('status')),
                    _escape_cell(iss.get('description')),
                    _escape_cell(iss.get('owner')),
                    _escape_cell(iss.get('escalation_target')),
                    _escape_cell(iss.get('due_date')),
                    _escape_cell(iss.get('resolution_ref')),
                ])
                + ' |'
            )
        issues_table = '\n'.join(issue_rows)
    else:
        issues_table = '| なし | - | - | - | - | 未解決の問題なし | - | - | - | - |'

    template_path = ROOT / 'shared/templates/artifact_markdown_template.md'
    template = template_path.read_text(encoding='utf-8')
    replacements = {
        '{{phase_id}}': _fmt_scalar(phase_id),
        '{{phase_name}}': phase_name,
        '{{artifact_id}}': _fmt_scalar(artifact.get('artifact_id')),
        '{{project_id}}': _fmt_scalar(artifact.get('project_id')),
        '{{version}}': _fmt_scalar(artifact.get('version')),
        '{{status}}': _fmt_scalar(artifact.get('status')),
        '{{supersedes_version}}': _fmt_scalar(artifact.get('supersedes_version')),
        '{{content_section}}': content_section,
        '{{source_refs_section}}': source_refs_section,
        '{{related_artifact_ids_section}}': related_section,
        '{{field_states_table}}': field_states_table,
        '{{issues_table}}': issues_table,
        '{{semantic_status}}': _fmt_scalar(review.get('semantic_status')),
        '{{reviewer_id}}': _fmt_scalar(review.get('reviewer_id')),
        '{{review_version}}': _fmt_scalar(review.get('review_version')),
        '{{approval_decision}}': _fmt_scalar(approval.get('decision')),
        '{{approval_channel}}': _fmt_scalar(approval.get('channel') or 'NONE'),
        '{{approver_id}}': _fmt_scalar(approval.get('approver_id')),
        '{{approval_id}}': _fmt_scalar(approval.get('approval_id')),
        '{{content_sha256}}': _fmt_scalar(approval.get('content_sha256')),
        '{{externally_verified}}': str(bool(approval.get('externally_verified', False))).lower(),
    }
    rendered = template
    for k, v in replacements.items():
        rendered = rendered.replace(k, v)
    return rendered


def verify_markdown(
    artifact: dict,
    markdown_text: str,
    definitions: list[dict] | None = None,
    required_fields: list[str] | None = None,
) -> list[dict[str, str]]:
    if definitions is None:
        definitions = load_json(ROOT / 'shared/phase_definitions.json')

    findings: list[dict[str, str]] = []

    def add(code: str, message: str) -> None:
        findings.append({'code': code, 'message': message})

    for sec in REQUIRED_SECTIONS:
        if sec not in markdown_text:
            add('MD_SECTION_MISSING', f'Required section "{sec}" is missing in Markdown')

    for key in ('artifact_id', 'project_id', 'phase_id', 'version', 'status'):
        val = str(artifact.get(key, ''))
        if val and val not in markdown_text:
            add('MD_METADATA_MISMATCH', f'{key}="{val}" not found in Markdown')

    phase_def = next((p for p in definitions if p['phase_id'] == artifact.get('phase_id')), None)
    if required_fields is None and phase_def:
        required_fields = [f['field_id'] for f in phase_def['fields'] if f['requirement'] == 'REQUIRED']

    content = artifact.get('content', {})
    for fid in (required_fields or []):
        if fid not in markdown_text:
            add('MD_FIELD_MISSING', f'Required field "{fid}" is not shown in Markdown')
        val = content.get(fid)
        if isinstance(val, str) and val and val not in markdown_text:
            add('MD_CONTENT_MISMATCH', f'Value of "{fid}" is missing or mismatched in Markdown')
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item and item not in markdown_text:
                    add('MD_CONTENT_MISMATCH', f'List item of "{fid}" is missing in Markdown: {item}')

    for ref in artifact.get('source_refs', []):
        if ref not in markdown_text:
            add('MD_SOURCE_MISMATCH', f'source_ref "{ref}" is missing in Markdown')

    for rid in artifact.get('related_artifact_ids', []):
        if rid not in markdown_text:
            add('MD_RELATED_MISMATCH', f'related_artifact_id "{rid}" is missing in Markdown')

    field_states = artifact.get('field_states', {})
    for fid, st in field_states.items():
        if fid not in markdown_text or st not in markdown_text:
            add('MD_FIELD_STATE_MISMATCH', f'field_state {fid}={st} is not reflected in Markdown')

    for iss in artifact.get('issues', []):
        iid = iss.get('issue_id', '')
        if iid and iid not in markdown_text:
            add('MD_ISSUE_MISMATCH', f'issue_id "{iid}" is missing in Markdown')
        fid = iss.get('field_id')
        if (
            iss.get('status') == 'OPEN'
            and iss.get('issue_type') == 'MISSING_INFO'
            and fid
            and field_states.get(fid) == 'CONFIRMED'
        ):
            add(
                'FIELD_STATE_ISSUE_CONFLICT',
                f'field "{fid}" is CONFIRMED but has OPEN MISSING_INFO issue "{iid}"',
            )

    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description='Render or verify Markdown artifact from JSON SSoT')
    parser.add_argument('--artifact', required=True, type=Path, help='Path to JSON artifact')
    parser.add_argument('--output', type=Path, help='Output Markdown path (used with --render)')
    parser.add_argument('--markdown', type=Path, help='Existing Markdown path (used with --verify)')
    parser.add_argument('--render', action='store_true', help='Render Markdown from JSON')
    parser.add_argument('--verify', action='store_true', help='Verify JSON <-> Markdown consistency')
    args = parser.parse_args()

    artifact = load_json(args.artifact)
    definitions = load_json(ROOT / 'shared/phase_definitions.json')

    if args.render:
        md = render_markdown(artifact, definitions)
        out_path = args.output or args.artifact.with_suffix('.md')
        out_path.write_text(md, encoding='utf-8')
        print(json.dumps({'action': 'rendered', 'output': str(out_path)}, ensure_ascii=False))

    if args.verify or not args.render:
        md_path = args.markdown or args.output or args.artifact.with_suffix('.md')
        if not md_path.exists():
            print(json.dumps({'valid': False, 'findings': [{'code': 'MD_FILE_MISSING', 'message': str(md_path)}]}, ensure_ascii=False, indent=2))
            raise SystemExit(2)
        findings = verify_markdown(artifact, md_path.read_text(encoding='utf-8'), definitions)
        print(json.dumps({'valid': len(findings) == 0, 'findings': findings}, ensure_ascii=False, indent=2))
        if findings:
            raise SystemExit(2)


if __name__ == '__main__':
    main()
