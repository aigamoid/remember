# DEVLOG

Phase ごとの作業記録・設計判断ログ。

---

## 2026-03-23 — `/wrap-up` スラッシュコマンド設計・実装

### 変更内容

| # | ファイル | 内容 |
|---|---|---|
| 1 | `~/.claude/commands/wrap-up.md` | セッション終了処理コマンド新規作成 |
| 2 | `~/.claude/plans/snazzy-nibbling-milner.md` | 実装プランの作成・修正（DEVLOG不在時の確認フロー追加） |

### 実施内容

- セッション終了時に毎回打っていた「ObsidianとDEVLOGに記録・ドキュメント更新」を `/wrap-up` コマンドに自動化
- Claude Code のカスタムスラッシュコマンド仕様を調査（`~/.claude/commands/` 配下に `.md` ファイルを置く形式）
- 現行ワークフローを調査しコマンド内容を設計

### 決定事項

- コマンドは `~/.claude/commands/wrap-up.md`（グローバル配置）とし全プロジェクトで使用可能にする
- `docs/DEVLOG.md` が存在しない場合はユーザーに作成確認を取る（サイレントスキップしない）
- git push はコマンド内に含めない（人間が手動で実施するプロジェクトルールに準拠）

### 次のステップ

- 実際に `/wrap-up` を使い続けてフィードバックがあれば `~/.claude/commands/wrap-up.md` を随時改善する

---

## 2026-03-23 — Dify SaaS移行調査・断念

### 実施内容

- セルフホスト版 Dify → SaaS版への移行手順を検討
- Dify ナレッジベースには UI エクスポート機能がないことを確認
- セルフホスト版 API（`GET /datasets/{id}/documents`・`GET /datasets/{id}/documents/{id}/segments`）でチャンクを全取得 → JSON保存するエクスポートスクリプト案を設計
- SaaS版で「Failed to invoke text embedding」エラー発生 → 原因：SaaS版は embedding モデルの API キー（OpenAI等）をユーザーが持ち込む必要がある（Model Provider 設定が未設定）
- 今セッションは解決に至らず、SaaS移行を一旦保留

### 決定事項

- **Dify SaaS移行は保留**（embedding 設定問題が解消できず）
- セルフホスト版 Dify を引き続き使用する
- ナレッジベースのエクスポートには API を使う方針（`dify_export.py` は未実装のまま）

### 次のステップ

- SaaS移行を再開する場合: Dify SaaS の Model Provider に OpenAI API キーを登録してから再試行
- またはセルフホスト版のまま運用継続

---

## 2026-03-23 — Dify フロー：現在日時注入

### 変更内容

- `dify/waiwai-oracle.yml` 追加（フローのバージョン管理開始）
- Dify ワークフローに Code ノードを追加（Start → Code → Query Rewriter → Knowledge Retrieval → LLM → Answer）

### Code ノード実装

```python
def main():
    from datetime import datetime, timezone, timedelta
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    return {"current_datetime": now.strftime("%Y-%m-%d %H:%M JST")}
```

**ハマりポイント**: Dify の Code ノードは `def main():` 内に書く必要がある（`return` をトップレベルに書くと `SyntaxError: 'return' outside function`）

### 目的

チャンクテキストに埋め込まれたタイムスタンプを活用し、「最近の話題」「一年前」などの相対時間クエリに対応する。
Query Rewriter と LLM の両プロンプトに `{{#code_node_id.current_datetime#}}` を埋め込んで使用。

---

## 2026-03-22 — Phase 3 再設計完了・RAGチャットボット動作確認

### 主な変更（uploader廃止 → exporter + チャンキング改善）

| # | ファイル | 内容 |
|---|---|---|
| 1 | `src/uploader.py` / `uploader.py` / `tests/test_uploader.py` | 削除（Dify API廃止） |
| 2 | `src/exporter.py` / `exporter.py` / `tests/test_exporter.py` | 新規追加（output/*.txt出力） |
| 3 | `src/chunker.py` | 時間ギャップ方式に全面書き換え（スライディングウィンドウ廃止） |
| 4 | `src/chunker.py` | `_is_noise` 追加・短文吸収ロジック実装 |
| 5 | `chunker.py` | `--clean` オプション追加 |
| 6 | `src/db.py` | `fetch_chunks_by_channel` 追加・INSERT OR REPLACE に変更 |

### チャンキング設計の変更

- **廃止**: スライディングウィンドウ（前後2件）
- **採用**: 時間ギャップ方式（`time_gap_minutes: 60`）
- **追加フィルター**:
  - `_is_noise`: URLのみ・@here/@everyone・空白のみを除去
  - 短文吸収: 10文字以下 + ギャップ60分未満 → 直前チャンクに吸収（疑似reply_to）
  - `@here/@everyone` は短文でも除去
- **結果**: 9,301チャンク → 8,364チャンク（1行チャンク 39% → 37.4%）

### Difyアップロード方式の変更

- **廃止**: Dify Knowledge API 経由の自動アップロード
- **採用**: `exporter.py` で output/*.txt を出力 → ブラウザから手動アップロード
- **理由**: API経由より直感的でエラー内容がわかりやすい
- **Dify設定**: セグメント識別子 `\n\n---\n\n`

### 実行結果

- output/ に 30ファイル / 3.1MB 出力
- Dify にアップロード完了
- **チャットボット動作確認 ✅**

### 3エージェントレビュー記録

- Codex・Aider による複数回レビュー → 短文吸収ロジックの `prev_ts` 更新問題・max_chunk_messages超過問題・空白のみ除去漏れ を指摘・修正済み
- 全テスト 93/93 PASS

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
