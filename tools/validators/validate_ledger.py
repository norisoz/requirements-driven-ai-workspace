#!/usr/bin/env python3
"""Validate requirements ledger (SSoT) and render traceability matrix Markdown.

Based on IPA Handbook Section 2.6 (Table 9), Section 6.8, Section 11.2-11.4 (Tables 40-41),
and Section 16.1 (avoiding duplicate management).
"""
import argparse
import json
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:
    raise SystemExit("ERROR: jsonschema is required. Install only according to workspace policy.") from exc

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def validate_ledger(ledger: dict, sources: dict | None = None) -> dict:
    schema = load_json(ROOT / 'shared/schemas/requirements_ledger.schema.json')
    Draft202012Validator.check_schema(schema)
    findings: list[dict[str, str]] = []

    def add(code: str, message: str) -> None:
        findings.append({'code': code, 'message': message})

    for e in sorted(Draft202012Validator(schema).iter_errors(ledger), key=lambda err: str(err.path)):
        add('INVALID_LEDGER_SCHEMA', f'{"/".join(map(str, e.absolute_path))}: {e.message}')

    items = ledger.get('items', [])
    ids = [it.get('requirement_id') for it in items if isinstance(it, dict)]
    seen = set()
    for rid in ids:
        if rid in seen:
            add('DUPLICATE_REQUIREMENT_ID', f'Duplicate requirement_id: {rid}')
        seen.add(rid)

    source_ids = None
    if sources is not None:
        source_ids = {s.get('id') for s in sources.get('sources', [])}

    for it in items:
        if not isinstance(it, dict):
            continue
        rid = it.get('requirement_id', '')
        sref = it.get('source_ref')
        if source_ids is not None and sref and sref not in source_ids:
            add('LEDGER_SOURCE_MISSING', f'{rid} references missing source {sref}')
        rel = it.get('related_ids') or {}
        for ref_group in ('parent_requirements', 'child_specifications', 'dependencies'):
            for target_id in rel.get(ref_group, []):
                if target_id not in seen:
                    add('ORPHAN_TRACE_LINK', f'{rid}.{ref_group} references unknown id "{target_id}"')

    return {'valid': len(findings) == 0, 'item_count': len(items), 'findings': findings}


def render_traceability_matrix(ledger: dict) -> str:
    lines = [
        f'# トレーサビリティマトリクス（{ledger.get("ledger_id", "")} v{ledger.get("version", "")}）',
        '',
        '> 本表は要求管理台帳（正本 JSON）から自動生成したビューです（ハンドブック表41準拠）。',
        '',
        '| 要求ID | 種別(3層) | 要求/要件名 | 発生源 | 関連要件 | 関連データ | 関連機能 | 検証方法 | 運用ログ | 状態 |',
        '|---|---|---|---|---|---|---|---|---|---|',
    ]
    items = ledger.get('items', [])
    if not items:
        lines.append('| なし | - | 登録済み要求なし | - | - | - | - | - | - | - |')
    else:
        for it in items:
            rel = it.get('related_ids') or {}
            row = [
                f'`{it.get("requirement_id", "")}`',
                it.get('record_kind', '-'),
                str(it.get('title', '')).replace('|', '\\|'),
                f'`{it.get("source_ref", "-")}`',
                ', '.join(rel.get('child_specifications', [])) or '-',
                ', '.join(rel.get('data_items', [])) or '-',
                ', '.join(rel.get('functions', [])) or '-',
                str(it.get('verification_method', '-')).replace('|', '\\|'),
                ', '.join(rel.get('operation_logs', [])) or '-',
                it.get('status', '-'),
            ]
            lines.append('| ' + ' | '.join(row) + ' |')
    return '\n'.join(lines) + '\n'


def main() -> None:
    parser = argparse.ArgumentParser(description='Validate requirements ledger and render traceability matrix')
    parser.add_argument('--ledger', required=True, type=Path)
    parser.add_argument('--source-index', default=None, type=Path)
    parser.add_argument('--render-matrix', action='store_true')
    parser.add_argument('--output', default=None, type=Path)
    args = parser.parse_args()

    ledger = load_json(args.ledger)
    sources = load_json(args.source_index) if args.source_index else None
    result = validate_ledger(ledger, sources)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.render_matrix:
        md = render_traceability_matrix(ledger)
        if args.output:
            args.output.write_text(md, encoding='utf-8')
        else:
            print('\n' + md)

    if not result['valid']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
