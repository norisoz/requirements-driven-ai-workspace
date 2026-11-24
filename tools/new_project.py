#!/usr/bin/env python3
"""依頼ごとに v2/projects/<案件名>/ をインスタンス化・検索・再開資料取り込みする補助スクリプト。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path

IGNORED_INBOX_NAMES = {"README.md", ".gitkeep", ".DS_Store"}


def get_v2_root() -> Path:
    return Path(__file__).resolve().parent.parent


def validate_safe_name(name: str, label: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError(f"{label} が空です。")
    if "/" in cleaned or "\\" in cleaned or ".." in cleaned or cleaned in {".", "_template"}:
        raise ValueError(f"{label} に使用できない文字または予約名が含まれています: {name}")
    return cleaned


def replace_placeholders(text: str, mapping: dict[str, str]) -> str:
    for key, value in mapping.items():
        text = text.replace(key, value)
    return text


def list_available_tasks(tasks_dir: Path) -> list[str]:
    if not tasks_dir.is_dir():
        return []
    return sorted(p.name for p in tasks_dir.iterdir() if p.is_dir() and not p.name.startswith("."))


def list_inbox_items(inbox_dir: Path) -> list[Path]:
    if not inbox_dir.is_dir():
        return []
    return sorted(
        p
        for p in inbox_dir.iterdir()
        if p.name not in IGNORED_INBOX_NAMES and not p.name.startswith(".")
    )


def unique_destination(dest_dir: Path, name: str) -> Path:
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path_obj = Path(name)
    if path_obj.suffix:
        new_name = f"{path_obj.stem}_{stamp}{path_obj.suffix}"
    else:
        new_name = f"{name}_{stamp}"
    candidate = dest_dir / new_name
    counter = 1
    while candidate.exists():
        if path_obj.suffix:
            candidate = dest_dir / f"{path_obj.stem}_{stamp}_{counter}{path_obj.suffix}"
        else:
            candidate = dest_dir / f"{name}_{stamp}_{counter}"
        counter += 1
    return candidate


def transfer_inbox_items(inbox_dir: Path, target_inputs_dir: Path, mode: str) -> list[str]:
    """mode: 'move' | 'copy' | 'none'"""
    if mode == "none":
        return []
    target_inputs_dir.mkdir(parents=True, exist_ok=True)
    transferred: list[str] = []
    for item in list_inbox_items(inbox_dir):
        dest = unique_destination(target_inputs_dir, item.name)
        if mode == "move":
            shutil.move(str(item), str(dest))
        elif mode == "copy":
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
        transferred.append(dest.name)
    return transferred


def create_project(
    name: str,
    task: str,
    user: str,
    summary: str = "",
    keywords: list[str] | None = None,
    inbox_mode: str = "none",
) -> tuple[Path, list[str]]:
    v2_root = get_v2_root()
    tasks_dir = v2_root / "tasks"
    template_dir = v2_root / "projects" / "_template"
    projects_dir = v2_root / "projects"
    inbox_dir = v2_root / "inputs"

    safe_name = validate_safe_name(name, "案件名")
    safe_user = validate_safe_name(user, "ユーザー名")

    available_tasks = list_available_tasks(tasks_dir)
    if task not in available_tasks:
        raise ValueError(
            f"指定されたタスク '{task}' が見つかりません。利用可能なタスク: {', '.join(available_tasks)}"
        )

    if not template_dir.is_dir():
        raise FileNotFoundError(f"案件テンプレートが見つかりません: {template_dir}")

    target_dir = projects_dir / safe_name
    if target_dir.exists():
        raise FileExistsError(f"同名の案件フォルダが既に存在します: {target_dir}")

    shutil.copytree(template_dir, target_dir)

    transferred = transfer_inbox_items(inbox_dir, target_dir / "inputs", inbox_mode)

    today = dt.date.today().isoformat()
    project_id = "PRJ-" + re.sub(r"[^A-Za-z0-9_-]+", "-", safe_name).strip("-")[:32].upper()
    if project_id == "PRJ-":
        project_id = f"PRJ-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}"

    imported_summary = ", ".join(transferred) if transferred else "（未配置）"
    mapping = {
        "{{PROJECT_NAME}}": safe_name,
        "{{TASK_NAME}}": task,
        "{{USER_NAME}}": safe_user,
        "{{CREATED_DATE}}": today,
        "{{IMPORTED_FILES}}": imported_summary,
    }

    # project.json の初期化
    project_json_path = target_dir / "project.json"
    project_data = json.loads(project_json_path.read_text(encoding="utf-8"))
    project_data["project_id"] = project_id
    project_data["project_name"] = safe_name
    project_data["task_type"] = task
    project_data["owner"] = safe_user
    project_data["created_at"] = today
    project_data["updated_at"] = today
    project_data["summary"] = summary
    project_data["keywords"] = keywords or []
    project_data.setdefault("input_policy", {})["imported_files"] = transferred
    project_json_path.write_text(
        json.dumps(project_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # prompt_snapshot.md へ開始時点のタスクプロンプトを埋め込む
    snapshot_path = target_dir / "prompt_snapshot.md"
    task_prompt_path = tasks_dir / task / "prompt.md"
    task_prompt_body = task_prompt_path.read_text(encoding="utf-8") if task_prompt_path.is_file() else ""
    snapshot_header = replace_placeholders(snapshot_path.read_text(encoding="utf-8"), mapping)
    marker = "## 開始時点のタスクプロンプト控え"
    if marker in snapshot_header:
        snapshot_header = snapshot_header.split(marker)[0].rstrip() + f"\n\n{marker}\n\n"
    snapshot_path.write_text(snapshot_header + task_prompt_body, encoding="utf-8")

    # 透明性レポート（試験運用）の初期化
    report_path = target_dir / "reports" / "transparency_report.md"
    if report_path.is_file():
        report_text = replace_placeholders(report_path.read_text(encoding="utf-8"), mapping)
        report_path.write_text(report_text, encoding="utf-8")

    return target_dir, transferred


def attach_inputs_to_project(project_name: str, inbox_mode: str = "move") -> tuple[Path, list[str]]:
    v2_root = get_v2_root()
    projects_dir = v2_root / "projects"
    inbox_dir = v2_root / "inputs"

    safe_name = validate_safe_name(project_name, "既存案件名")
    target_dir = projects_dir / safe_name
    if not target_dir.is_dir():
        raise FileNotFoundError(f"指定された既存案件が見つかりません: {target_dir}")

    transferred = transfer_inbox_items(inbox_dir, target_dir / "inputs", inbox_mode)
    if not transferred:
        return target_dir, []

    today = dt.date.today().isoformat()
    now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    project_json_path = target_dir / "project.json"
    if project_json_path.is_file():
        project_data = json.loads(project_json_path.read_text(encoding="utf-8"))
        project_data["updated_at"] = today
        policy = project_data.setdefault("input_policy", {})
        existing_files = policy.get("imported_files", [])
        policy["imported_files"] = existing_files + transferred
        project_json_path.write_text(
            json.dumps(project_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    report_path = target_dir / "reports" / "transparency_report.md"
    if report_path.is_file():
        addition = (
            f"\n---\n\n### 再開・追加資料取り込み記録（{now_str}）\n"
            f"- 取り込み方式: {'移動（v2/inputs/ を空化）' if inbox_mode == 'move' else 'コピー'}\n"
            f"- 追加ファイル: {', '.join(transferred)}\n"
        )
        with report_path.open("a", encoding="utf-8") as fh:
            fh.write(addition)

    return target_dir, transferred


def search_projects(query: str = "") -> list[dict[str, object]]:
    v2_root = get_v2_root()
    projects_dir = v2_root / "projects"
    if not projects_dir.is_dir():
        return []

    q = query.strip().lower()
    results: list[dict[str, object]] = []
    for entry in sorted(projects_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name == "_template":
            continue
        pjson = entry / "project.json"
        meta: dict[str, object] = {
            "folder": entry.name,
            "project_name": entry.name,
            "task_type": "",
            "owner": "",
            "updated_at": "",
            "summary": "",
            "keywords": [],
            "imported_files": [],
        }
        if pjson.is_file():
            try:
                data = json.loads(pjson.read_text(encoding="utf-8"))
                meta["project_name"] = data.get("project_name", entry.name)
                meta["task_type"] = data.get("task_type", "")
                meta["owner"] = data.get("owner", "")
                meta["updated_at"] = data.get("updated_at", data.get("created_at", ""))
                meta["summary"] = data.get("summary", "")
                meta["keywords"] = data.get("keywords", [])
                meta["imported_files"] = data.get("input_policy", {}).get("imported_files", [])
            except Exception:
                pass

        if q:
            haystack = " ".join(
                [
                    str(meta["folder"]),
                    str(meta["project_name"]),
                    str(meta["task_type"]),
                    str(meta["owner"]),
                    str(meta["summary"]),
                    " ".join(str(k) for k in meta["keywords"]),  # type: ignore[union-attr]
                    " ".join(str(f) for f in meta["imported_files"]),  # type: ignore[union-attr]
                ]
            ).lower()
            if q not in haystack:
                continue
        results.append(meta)

    results.sort(key=lambda r: str(r.get("updated_at", "")), reverse=True)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="v2/projects/ の新規案件作成、既存案件検索、および v2/inputs/ からの資料移動を行います。"
    )
    parser.add_argument("--name", help="新規案件フォルダ名（例: 20261124_脆弱性調査）")
    parser.add_argument("--task", help="タスクフォルダ名（例: 07_vuln_triage）")
    parser.add_argument("--user", default="default_user", help="担当者名")
    parser.add_argument("--summary", default="", help="案件のひとこと要約（曖昧検索用）")
    parser.add_argument("--keywords", default="", help="検索キーワード（カンマ区切り）")
    parser.add_argument("--attach", help="既存案件フォルダ名（v2/inputs/ の資料を追加取り込み）")
    parser.add_argument("--list", action="store_true", help="既存案件の一覧・検索を表示")
    parser.add_argument("--query", default="", help="--list 時の部分一致検索語句")

    transfer_group = parser.add_mutually_exclusive_group()
    transfer_group.add_argument(
        "--move-inputs",
        action="store_true",
        help="v2/inputs/ 内の資料を案件の inputs/ へ移動し、v2/inputs/ を空に戻す",
    )
    transfer_group.add_argument(
        "--copy-inputs",
        action="store_true",
        help="v2/inputs/ 内の資料を案件の inputs/ へコピーする（元ファイルを残す）",
    )

    args = parser.parse_args(argv)

    try:
        if args.list:
            items = search_projects(args.query)
            if not items:
                print("該当する既存案件はありません。")
                return 0
            for item in items:
                print(
                    f"- {item['folder']} | task={item['task_type']} | updated={item['updated_at']} "
                    f"| summary={item['summary']} | keywords={item['keywords']}"
                )
            return 0

        if args.attach:
            mode = "copy" if args.copy_inputs else "move"
            target_dir, transferred = attach_inputs_to_project(args.attach, inbox_mode=mode)
            if not transferred:
                print(f"INFO: v2/inputs/ に移動対象の資料はありませんでした（対象案件: {target_dir}）。")
            else:
                print(f"OK: 既存案件へ資料を取り込みました: {target_dir / 'inputs'}")
                print(f"  - 取り込み方式: {mode}")
                print(f"  - 対象ファイル: {', '.join(transferred)}")
            return 0

        if not args.name or not args.task:
            parser.error("新規作成には --name と --task が必要です（検索は --list、再開取り込みは --attach）。")

        mode = "move" if args.move_inputs else ("copy" if args.copy_inputs else "none")
        kw_list = [k.strip() for k in args.keywords.split(",") if k.strip()] if args.keywords else []
        created_dir, transferred = create_project(
            name=args.name,
            task=args.task,
            user=args.user,
            summary=args.summary,
            keywords=kw_list,
            inbox_mode=mode,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"OK: 案件フォルダを作成しました: {created_dir}")
    print(f"  - 案件設定: {created_dir / 'project.json'}")
    print(f"  - 入力資料フォルダ: {created_dir / 'inputs'}")
    if transferred:
        print(f"  - 取り込み資料（{mode}）: {', '.join(transferred)}")
    print(f"  - プロンプト控え: {created_dir / 'prompt_snapshot.md'}")
    print(f"  - 透明性レポート（試験運用）: {created_dir / 'reports' / 'transparency_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
