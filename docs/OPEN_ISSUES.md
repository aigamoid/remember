# 未解決事項・確定設計決定（インデックス）

> **運用方針（2026-06-22 移行）:**
> **アクティブな課題（未解決事項・TODO）は GitHub Issues で管理する**（採番は `#NN`）。
> `gh issue list` / `gh issue view <#NN>` で参照、起票・進捗・クローズも GitHub Issues 上で行う。
> 独自の `OI-XX` 採番は **OI-54 で凍結**（手動採番の番号衝突を避けるため）。
> このファイルは以下の3つのみを保持する:
> 1. **OI-XX → #NN インデックス表**（コードに残る旧 `OI-XX` 参照の道標）
> 2. **確定設計決定・見送り判断**（CLAUDE.md が参照する決定事項）
> 3. **完了アーカイブ**（完了済みOIの1行記録。詳細は `docs/DEVLOG.md` と git 履歴）
>
> 移行の経緯: 旧ファイルは 1024行・OI 54件まで肥大化し、手動採番 `OI-44` が
> 2系統で衝突していた（codex-fugu 安全性レビューとコードレビュー指摘の重複起票）。
> GitHub Issues 中心のハイブリッド管理へ移行（CLAUDE.md「Git運用ルール」参照）。

---

## 1. アクティブIssue インデックス表（OI-XX → #NN）

コード内・コミット・DEVLOG に残る旧 `OI-XX` 参照は、下表の GitHub Issue を指す。

| 旧OI | GitHub Issue | 内容 | 優先度 |
|---|---|---|---|
| OI-3 | [#34](https://github.com/aigamoid/waiwai-oracle/issues/34) | ThreadCollector 未実装（スレッド取得） | P3 |
| OI-13 | [#35](https://github.com/aigamoid/waiwai-oracle/issues/35) | 取り込み完了のDiscord通知が無い | P2 |
| OI-14 | [#32](https://github.com/aigamoid/waiwai-oracle/issues/32) | 収益化・パブリック化ロードマップ（**epic**） | P1 |
| OI-19 | [#36](https://github.com/aigamoid/waiwai-oracle/issues/36) | worker の `Event loop is closed` 警告（無害・既知） | P3 |
| OI-26 | [#37](https://github.com/aigamoid/waiwai-oracle/issues/37) | CDデプロイ完了をDiscordに通知する | P2 |
| OI-28〜43 | [#33](https://github.com/aigamoid/waiwai-oracle/issues/33) | 魅力強化（リテンション）アイデア群（**epic**） | — |
| OI-44 | [#31](https://github.com/aigamoid/waiwai-oracle/issues/31) | Bot退出/purge時の削除範囲が不完全 | P0 |
| OI-46 | [#39](https://github.com/aigamoid/waiwai-oracle/issues/39) | /remember が quota 管理外でコスト発生・記憶汚染 | P1 |
| OI-47 | [#40](https://github.com/aigamoid/waiwai-oracle/issues/40) | 明示メモリの安全弁が薄い | P1 |
| OI-48 | [#41](https://github.com/aigamoid/waiwai-oracle/issues/41) | 公開/課金前の同意ログが未実装 | P1 |
| OI-49 | [#42](https://github.com/aigamoid/waiwai-oracle/issues/42) | CD後のヘルスチェックがAPIのみ | P2 |
| OI-50 | [#43](https://github.com/aigamoid/waiwai-oracle/issues/43) | 正式な schema migration が無い | P2 |
| OI-51 | [#44](https://github.com/aigamoid/waiwai-oracle/issues/44) | config.yml と example の運用ドリフト | P2 |
| OI-52 | [#45](https://github.com/aigamoid/waiwai-oracle/issues/45) | GitFlow の main 不整合・リリースフロー未整備 | P2 |
| OI-53 | [#46](https://github.com/aigamoid/waiwai-oracle/issues/46) | テストの非決定的な揺らぎ | P2 |
| OI-54 | [#47](https://github.com/aigamoid/waiwai-oracle/issues/47) | 既知の軽微なランタイム/依存ドリフト | P3 |

**重複統合の記録:** 旧 OI-45〜49 は「codex-fugu 安全性レビュー版」と「コードレビュー指摘版」に
同一内容が2件ずつ存在していた（OI-44 も同様）。同一指摘のため上表の各 Issue に**統合**した
（統合理由は各 Issue 本文に明記）。移行の冪等記録は [`oi_migration.tsv`](oi_migration.tsv)。

---

## 2. 確定設計決定・見送り判断

過去フェーズで確定し、**今後のプラン立案で「抜け」と誤指摘しないために残す**決定事項。

### Dify メタデータフィルタは使用しない（OI-6・2026-03-15 決定）
- **理由:** Dify セルフホスト版の自動メタデータフィルタにバグ多数（GitHub #16564, #29556 等）で実用に耐えない。
- **代替策:** タイムスタンプ・投稿者名を `chunk_text` 本文に直接埋め込む
  （`[YYYY-MM-DD HH:MM] 投稿者名: メッセージ内容`・JST変換済み）。これで時系列クエリに LLM が回答できる。
- ※Dify 自体は廃止済み（自前 RAG へ移行）だが、メタデータを本文に埋める設計はそのまま継承している。

### リランカー本番有効化は見送り（OI-9 Phase 1・2026-06-19）
- リランカーは実装済みだが、実データ A/B で改善が確認できず **既定 OFF を維持**。
- スパース(BM25)ハイブリッド（OI-9 Phase 2）も**見送り中**。

### 回答LLMに Discord ツール（function calling）は当面持たせない（OI-17・2026-06-16）
- コスト増（LLM往復×巨大context）・レイテンシ増・プロンプトインジェクション（公開マルチテナントで特に危険）・
  スコープ拡大（汎用アシスタント化）のため見送り。欲しい効果の大半はツール無しで実現済み（OI-18 等）。
- エージェント的ツールは OI-14（公開/収益化）・コスト最適化が片付いた後、まず**読み取り限定**で再検討。

---

## 3. 完了アーカイブ

完了済みOI（詳細は `docs/DEVLOG.md` と各 feature ブランチの git 履歴）。

| OI | 内容 | 完了 |
|---|---|---|
| OI-1 | dry_run.py 実行 | 2026-03-15 |
| OI-2 | Dify インストール | 2026-03-15 |
| OI-4 | Discord Message Content Intent 確認 | 2026-03-15 |
| OI-5 | Dify Knowledge API のチャンク数上限確認 | 2026-03-16 |
| OI-7 | チャンク品質問題 | 2026-03-21 |
| OI-8 | 👋_ようこそ の 409 CONFLICT | 2026-03-21 |
| OI-9 | 検索品質リランカー（Phase 1 実装・本番はOFF維持＝上記2参照） | 2026-06-17 |
| OI-10 | 会話履歴（マルチターン）対応 | 2026-06-17 |
| OI-11 | SaaS化ステップ2（マルチテナント自動取り込み） | 2026-06-11 |
| OI-12 | マルチテナント取り込みの実機E2E | 2026-06-15 |
| OI-15 | 回答LLMシステムプロンプト見直し（れみちゃんリブランド） | 2026-06-17 |
| OI-16 | 回答1メッセージのコスト最適化（top_k=5/DeepSeek V3.2・約1/6〜1/7に・残レバーは #32/#33 へ） | 2026-06-16 |
| OI-18 | 回答中の `<@ID>` メンションを表示名に解決 | 2026-06-16 |
| OI-20 | 回答LLMが現在日時を知らず過去ログを誤認する問題 | 2026-06-17 |
| OI-21 | 回答のデバッグトレース | 2026-06-19 |
| OI-22 | 回答LLMに「いま話しかけている人」の名前を渡す | 2026-06-19 |
| OI-23 | 検索ゲート（不要ならベクトル検索スキップ） | 2026-06-19 |
| OI-24 | 明示メモリ機能（「覚えておいて」） | PR #27 |
| OI-25 | 全チャンネル一括許可コマンド `/oracle allowall` | 2026-06-20 |
| OI-27 | オンボーディング `/oracle help` | 2026-06-21 |
| OI-45 | /chat・/remember の Bot→API 共有シークレット認証（#38 / PR #50） | ✅ 完了 (2026-06-24) |
