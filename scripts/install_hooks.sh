#!/bin/sh
# .git/hooks/pre-commit を設置するスクリプト
# 使い方: sh scripts/install_hooks.sh

HOOK=".git/hooks/pre-commit"

if [ -f "$HOOK" ]; then
    echo "警告: $HOOK が既に存在します。上書きしません。"
    echo "      手動でマージする場合は以下を既存hookに追記してください:"
    echo "        python3 scripts/check_docs.py"
    exit 1
fi

printf '#!/bin/sh\n# ドキュメント参照チェック（waiwai-oracle）\npython3 scripts/check_docs.py\n' > "$HOOK"
chmod +x "$HOOK"
echo "完了: $HOOK を設置しました。コミット時に自動でドキュメントチェックが走ります。"
