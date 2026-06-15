"""ドキュメント内の .py ファイル参照が実際に存在するか確認するスクリプト。

使い方:
    python3 scripts/check_docs.py

exit(0): 問題なし / exit(1): 存在しない参照あり（コミットをブロック）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# プロジェクトルート（このスクリプトの親ディレクトリ）
ROOT = Path(__file__).parent.parent

# チェック対象ドキュメント（歴史的記録 OPEN_ISSUES.md 等は誤検知防止のため除外）
TARGET_DOCS = [
    ROOT / "CLAUDE.md",
    ROOT / "docs" / "ARCHITECTURE.md",
]

# ファイル探索ディレクトリ（優先順）
SEARCH_DIRS = [".", "src", "src/collectors", "src/rag", "src/admin", "moimoichan_Discordbot", "scripts", "tests"]

# 外部ライブラリ・ツール名として使われる既知の除外ワード（プロジェクトファイルではない）
EXCLUDED_NAMES = {"discord"}  # discord.py = ライブラリ名

# パターン1: バッククォート記法  例: `crawler.py` / `src/formatter.py`
BACKTICK_RE = re.compile(r"`([a-zA-Z_][a-zA-Z0-9_/]*)\.py`")

# パターン2: ディレクトリツリー行  例: ├── crawler.py / │   └── base.py
# ├=U+251C, └=U+2514, │=U+2502, ─=U+2500
TREE_RE = re.compile(r"[│├└─\s]+([a-zA-Z_][a-zA-Z0-9_/]*)\.py")


def extract_py_refs(doc_path: Path) -> list[tuple[str, int]]:
    """ドキュメントから .py ファイル名参照を (name, line_no) のリストで返す。"""
    refs: list[tuple[str, int]] = []
    text = doc_path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in BACKTICK_RE.finditer(line):
            refs.append((m.group(1), lineno))
        for m in TREE_RE.finditer(line):
            refs.append((m.group(1), lineno))
    return refs


def find_py_file(name: str) -> bool:
    """name に / が含まれる場合はルートおよび src/ 以下でパス解決。
    含まない場合は SEARCH_DIRS 順に探索する。"""
    if "/" in name:
        return (ROOT / f"{name}.py").exists() or (ROOT / "src" / f"{name}.py").exists()
    for d in SEARCH_DIRS:
        if (ROOT / d / f"{name}.py").exists():
            return True
    return False


def main() -> int:
    errors: list[str] = []

    for doc in TARGET_DOCS:
        if not doc.exists():
            continue
        rel = doc.relative_to(ROOT)
        seen: set[str] = set()
        for name, lineno in extract_py_refs(doc):
            if name in seen:
                continue
            seen.add(name)
            if name in EXCLUDED_NAMES:
                continue
            if not find_py_file(name):
                errors.append(
                    f"[エラー] {rel} (行{lineno}) に '{name}.py' という名前が書かれていますが、"
                    f"ファイルが見つかりません。\n"
                    f"         → ファイルを削除・改名したなら、ドキュメントの記述も更新してください。"
                )

    if errors:
        for msg in errors:
            print(msg)
        print(f"\nチェック完了: {len(errors)}件の問題が見つかりました。コミットをブロックします。")
        return 1

    print(f"チェック完了: 問題なし（対象: {', '.join(str(d.relative_to(ROOT)) for d in TARGET_DOCS if d.exists())}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
