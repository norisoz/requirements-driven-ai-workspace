#!/usr/bin/env python3
"""Read phase definitions and tailoring rules to emit deterministic top-N questions.

AI can use this output to ask naturally, but cannot override applicability or tailoring rules.
"""
import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_tailoring_module():
    spec = importlib.util.spec_from_file_location('resolve_tailoring', ROOT / 'scripts/resolve_tailoring.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_tailoring_mod = _load_tailoring_module()


def next_questions(project, artifact, definitions, maximum=3):
    phase_id = artifact.get('phase_id')
    p = next((x for x in definitions if x['phase_id'] == phase_id), None)
    if p is None:
        raise ValueError('unknown phase')

    tailoring_res = _tailoring_mod.resolve_tailoring(project, phase_id, definitions)
    required_set = set(tailoring_res['required_fields'])

    questions = []
    attributes = project.get('attributes', {})
    provenance = project.get('attribute_provenance', {})
    states = artifact.get('field_states', {})
    content = artifact.get('content', {})
    issues = artifact.get('issues', [])

    # Track fields already recorded as OPEN MISSING_INFO so we do not repeat the same question.
    blocked_missing_fields = set()
    for iss in issues:
        if iss.get('status') == 'OPEN' and iss.get('issue_type') == 'MISSING_INFO':
            fid = iss.get('field_id')
            if fid:
                blocked_missing_fields.add(fid)

    # Priority -1 (P01 only): Confirm final deliverable specification before content questions.
    deliverable = project.get('deliverable')
    if phase_id == 'P01' and isinstance(deliverable, dict):
        if not deliverable.get('deliverable_type'):
            questions.append({
                'priority': -1,
                'field_id': 'deliverable_type',
                'question': '想定している最終成果物の種類を選んでください（スライド／スライドの骨子／提案書／仕様書／設計書／社内通知文書／規程・方針書／調査レポート等）。',
                'reason': '最終成果物の種類が未確定',
            })
        if not deliverable.get('output_format'):
            questions.append({
                'priority': -1,
                'field_id': 'output_format',
                'question': '希望する成果物のファイル形式を選んでください（md / txt / docx〔Word〕 / pptx〔PowerPoint〕 / xlsx〔Excel〕 / pdf 等）。',
                'reason': '成果物の出力形式が未確定',
            })
        if not deliverable.get('maturity_level'):
            questions.append({
                'priority': -1,
                'field_id': 'maturity_level',
                'question': '今回作成する成果物に求める厳密さ（想定レビュー段階）を選んでください（叩き台／上長レビュー用／他部レビュー用／最終成果物）。',
                'reason': '成果物の厳密さ・レビュー段階が未確定',
            })

    # Priority 0: Tailoring blockers (risk_level UNKNOWN / work_type-attribute mismatch / reevaluation).
    for f in tailoring_res['findings']:
        code = f['code']
        if code in ('T01_RISK_UNKNOWN', 'T01_RISK_UNCONFIRMED'):
            questions.append({
                'priority': 0,
                'field_id': 'risk_level',
                'question': '本案件のリスクレベル（LOW / MEDIUM / HIGH）を判断するため、影響範囲、機密情報・法令義務の有無、誤り時の影響と判断根拠・確認者を教えてください。',
                'reason': f['message'],
            })
        elif code == 'T02_ATTRIBUTE_MISMATCH':
            questions.append({
                'priority': 0,
                'field_id': 'work_type_attribute_consistency',
                'question': f'業務種別と適用属性に不整合があります（{f["message"]}）。どちらが正しいか教えてください。',
                'reason': '業務種別と属性の不整合（T02）',
            })
        elif code == 'T08_REEVALUATION_REQUIRED':
            questions.append({
                'priority': 0,
                'field_id': 'tailoring_reevaluation',
                'question': 'リスクレベル変更に伴う関連工程の再評価結果を確認してください。',
                'reason': f['message'],
            })

    # Priority 1: Conditional applicability unknown or unconfirmed.
    for f in p['fields']:
        fid = f['field_id']
        if f['requirement'] != 'CONDITIONAL':
            continue
        attr = f['when']['attribute']
        if attributes.get(attr, None) is None or provenance.get(attr) not in ('HUMAN', 'VERIFIED_SOURCE'):
            questions.append({
                'priority': 1,
                'field_id': attr,
                'question': f'「{attr}」は今回の作業に適用されますか？該当/非該当とその根拠を教えてください。',
                'reason': f'{fid}の適用条件が未確定',
            })

    # Priority 2: Blocking OPEN issues (without repeating already-recorded complete MISSING_INFO blocks).
    for i in issues:
        if i.get('status') != 'OPEN':
            continue
        iid = i.get('issue_id')
        if i.get('issue_type') == 'MISSING_INFO':
            missing_meta = [
                k for k in ('owner', 'escalation_target', 'due_date') if not i.get(k)
            ]
            if missing_meta:
                questions.append({
                    'priority': 2,
                    'field_id': f'{iid}_metadata',
                    'question': f'保留中の情報不足「{i.get("description") or iid}」について、未設定の {", ".join(missing_meta)} を教えてください。',
                    'reason': 'BLOCKED記録の必須メタデータ未設定',
                })
            continue
        if i.get('severity') in ('CRITICAL', 'MAJOR'):
            questions.append({
                'priority': 2,
                'field_id': iid,
                'question': f'未解決の重大な問題「{i.get("description") or iid}」の判断・解決方針を教えてください。',
                'reason': '重大な未解決事項',
            })

    # Priority 3 & 4: Required (by tailoring level) and active conditional fields.
    for f in p['fields']:
        fid = f['field_id']
        typ = f['requirement']
        if fid in blocked_missing_fields:
            continue
        is_active_required = fid in required_set
        is_active_conditional = (
            typ == 'CONDITIONAL' and attributes.get(f['when']['attribute']) is True
        )
        if not (is_active_required or is_active_conditional):
            continue
        value = content.get(fid, None)
        state = states.get(fid, 'UNKNOWN')
        if value in (None, '', []) or state != 'CONFIRMED':
            questions.append({
                'priority': 3 if value in (None, '', []) else 4,
                'field_id': fid,
                'question': f['question'],
                'reason': '必須項目未入力' if value in (None, '', []) else f'現在の確認状態: {state}',
            })

    seen = set()
    result = []
    for q in sorted(questions, key=lambda x: (x['priority'], x['field_id'])):
        if q['field_id'] not in seen:
            result.append(q)
            seen.add(q['field_id'])
        if len(result) >= maximum:
            break
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', type=Path, required=True)
    ap.add_argument('--artifact', type=Path, required=True)
    ap.add_argument('--max', type=int, default=3)
    args = ap.parse_args()
    project = json.loads(args.project.read_text(encoding='utf-8'))
    artifact = json.loads(args.artifact.read_text(encoding='utf-8'))
    defs = json.loads((ROOT / 'shared/phase_definitions.json').read_text(encoding='utf-8'))
    print(
        json.dumps(
            {
                'phase_id': artifact['phase_id'],
                'questions': next_questions(project, artifact, defs, max(1, args.max)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
