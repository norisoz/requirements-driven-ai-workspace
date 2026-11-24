# {{phase_id}} {{phase_name}} — 成果物（{{artifact_id}} v{{version}}）

> 本MarkdownファイルはJSON成果物（正本）から生成・検証される人間向けビューです。直接編集せず、JSON正本を更新して再生成してください。

## 1. メタデータ
- **成果物ID**: `{{artifact_id}}`
- **プロジェクトID**: `{{project_id}}`
- **工程ID**: `{{phase_id}}`
- **版**: `{{version}}`
- **状態**: `{{status}}`
- **旧版参照（supersedes_version）**: `{{supersedes_version}}`

## 2. 工程固有の内容
{{content_section}}

## 3. 出典（source_refs）
{{source_refs_section}}

## 4. 関連成果物（related_artifact_ids）
{{related_artifact_ids_section}}

## 5. 確認状態（field_states）
| 項目ID | 必須区分 | 確認状態 |
|---|---|---|
{{field_states_table}}

## 6. 問題管理（issues）
| 問題ID | 区分 | 対象項目 | 重大度 | 状態 | 説明 | 担当者 | 確認先 | 期限 | 解決根拠 |
|---|---|---|---|---|---|---|---|---|---|
{{issues_table}}

## 7. 検証結果（review / gate）
- **意味検証状態（semantic_status）**: `{{semantic_status}}`
- **レビュアーID**: `{{reviewer_id}}`
- **レビュー対象版**: `{{review_version}}`
- **スキーマ・ゲート検証**: 別途 `scripts/validate_gate.py` の生出力で確認すること

## 8. 承認情報（approval）
- **承認判定（decision）**: `{{approval_decision}}`
- **承認チャネル（channel）**: `{{approval_channel}}`
- **承認者ID**: `{{approver_id}}`
- **承認記録ID**: `{{approval_id}}`
- **承認対象ハッシュ（content_sha256）**: `{{content_sha256}}`
- **外部システム本人認証済み（externally_verified）**: `{{externally_verified}}`
