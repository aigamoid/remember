# DEVLOG

Phase ごとの作業記録・設計判断ログ。

---

## 2026-03-21 — チャンキング戦略の調査・方針検討

### 背景

Phase 3（--clean 再アップロード）完了後、チャンク品質の問題が発覚。

### 判明した問題

- セパレータ `\n\n` ＝ メッセージ結合文字 `\n\n` が一致するため **1メッセージ = 1チャンク**
- Dify の分割ロジックは「セパレータで先に分割 → max_tokens で切り詰め」であり、結合ではない
- `max_tokens: 1000` 設定が事実上無効
- 雑談チャンネル単体で 11,305 チャンク（平均 27〜61 文字）→ 検索精度が出ない

### chunker.py の迷走はなかった

- chunker の仕様変更コミットは一度もなし
- 問題は uploader.py がチャンクを使わず messagesテーブルを直接連結している設計上の特性による

### チャンキング戦略の比較調査

| 方式 | APIコスト | 実装難度 | 品質 |
|---|---|---|---|
| 時間ギャップ方式（N時間で区切り） | なし | 低 | △（トピック変化を拾えない） |
| セマンティックチャンキング | embedding ~27,000回 | 中 | ◎ |
| Agentic Chunking | LLM呼び出し多数 | 高 | ◎（コスト最高） |

### 方針（検討中）

- **セマンティックチャンキング** を採用予定
- Dify 側には非対応 → Python 側（uploader.py or 新モジュール）で事前分割
- embedding モデル: OpenAI `text-embedding-3-small`（既存流用）
- 閾値・最小/最大チャンクサイズは実装時に調整
- 実装後は `--clean` で全チャンネル再アップロード

### 残課題

- `👋_ようこそ` の 409 CONFLICT 未解消（Dify UI から手動削除 → `--retry-errors`）

---

## 2026-03-17 — Phase 3 uploader 実装・トラブルシューティング

### 主な変更

| # | ファイル | 内容 |
|---|---|---|
| 1 | `src/formatter.py` | format_message_line + 制御文字除去 |
| 2 | `src/db.py` | upload_state テーブル + 管理関数 |
| 3 | `src/uploader.py` | Dify Knowledge API アップロードロジック |
| 4 | `uploader.py` | エントリポイント（--retry-errors / --clean） |
| 5 | `tests/test_uploader.py` | ユニットテスト 15件 |

### Embedding モデル変更: Ollama bge-m3 → OpenAI text-embedding-3-small

- **原因**: Dify Ollama プラグイン v0.1.2 の ThreadPoolExecutor が並行 embed リクエストを送信するバグ（Issue langgenius/dify-official-plugins#2746）
- **試した対策**: ドキュメント分割・クールダウン・リトライ → すべて無効
- **解決**: OpenAI text-embedding-3-small に切り替えで根本解決

### 意味があった修正のみ残した

| 修正 | 意味 |
|---|---|
| `_wait_for_indexing` で batch ID 使用 | API仕様に合致（document.id は不正） |
| `mark_channel_error` に document_id パラメータ追加 | エラー時も dataset_id 保持 |
| `_create_dataset` 失敗時の UnboundLocalError 修正 | 変数スコープのバグ修正 |
| `_strip_control_chars` 追加（formatter.py） | \x1b/\x1f がJSON破壊するバグ修正 |

### 効果がなかった修正（リバート済み）

- ドキュメント分割（_MAX_MESSAGES_PER_DOC）
- クールダウン（_COOLDOWN）
- リトライロジック（_upload_one_with_retry）

### 実行結果

- 31/32 チャンネル成功（OpenAI text-embedding-3-small）
- 1件エラー: `👋_ようこそ`（409 CONFLICT、前回テスト残存と名前衝突）

---

## 2026-03-15 — Phase 0〜2 実装

- Phase 0: dry_run.py（メッセージ数確認、36,128件 / 39チャンネル）
- Phase 1: crawler.py（Discord → SQLite、7チャンネル除外設定）
- Phase 2: chunker.py（スライディングウィンドウ、前後2件、25,358チャンク生成）
- Dify インストール（Windows 5090機、Tailscale IP: 100.88.176.117）
