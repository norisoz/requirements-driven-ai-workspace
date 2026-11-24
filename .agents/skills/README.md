# Antigravity 標準スキル置き場（`v2/.agents/skills/`）

本フォルダは Antigravity が自動認識するワークスペース共通のスキル置き場です。

## 1. コア工程スキル（原則変更しない・管理者のみ管理）
以下の6スキルは要求管理の基本工程を構成するコアスキルです。一般利用者は編集しないでください。

- `mission-intake`（工程1：目的・ミッション確認）
- `stakeholder-elicitation`（工程2〜3：関係者分析・要求獲得）
- `requirements-analysis`（工程4〜5：要求分析・仕様化）
- `model-traceability`（工程6：モデル化・紐付け）
- `validation-baseline`（工程7〜8：品質レビュー・基準版確定）
- `realization-lifecycle`（工程9〜12：実現引継ぎ・運用・変更・廃止）

## 2. チーム共通の拡張スキル（随時追加・更新可）
- `skill-curator`：SNSのTips・添削画像・レビュー指摘から新規スキルを作成し、反映先タスクと適用工程を人間承認のうえ更新するメタスキル
- `slide-anti-patterns`：AI生成スライドで避けるべきアンチパターン集と改善ルール（`01_slides` の作成・レビュー工程で使用）

## 3. 個人独自スキルの置き場
チーム全体ではなく自分専用で試したいスキルは、リポジトリ内ではなく各ユーザーPCの Antigravity 標準グローバルパスへ配置してください。
- 配置先：`~/.gemini/config/skills/<スキル名>/SKILL.md`
