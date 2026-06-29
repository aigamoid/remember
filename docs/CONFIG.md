# 設定ファイル仕様

## config.yml

```yaml
guild_id: 123456789          # 手動スクリプト（crawler.py等）の対象サーバーID
                             # 通常運用はワーカーがジョブのguild_idで動くため未使用

crawl:
  exclude_channels:          # 除外チャンネル名リスト（手動クロール時のみ有効）
    - bot-log
    - spam
  exclude_channel_ids:       # IDでの除外（名前変更に強い）
    - 987654321
  download_attachments: false        # true にするとクロール時に添付ファイルをローカルDL
  attachment_dir: "data/attachments" # DL先（download_attachments: true 時のみ使用）

chunk:
  time_gap_minutes: 60       # N分以上の間隔があればチャンク境界（会話スレッド単位）
  max_chunk_messages: 30     # 1チャンクに含める最大メッセージ数
  min_content_length: 10     # これ未満の文字数メッセージはスキップ
  short_reply_max_chars: 10  # これ以下の短文は直前チャンクに吸収（疑似reply_to）
  timezone_offset: 9         # タイムスタンプ表示のUTCオフセット（JST=9）

openai:
  api_key: ""              # 空なら環境変数 OPENAI_API_KEY を使用
  base_url: ""             # 空=OpenAIデフォルト / OpenRouter: https://openrouter.ai/api/v1

contextualizer:
  model: "gpt-4.1-nano"   # context_text 生成モデル
  preceding_messages: 10  # 直前のメッセージ参照数
  max_retries: 3          # API エラー時のリトライ回数
  retry_delay: 1.0        # リトライ間隔（秒）
  concurrency: 10         # 同時実行数（--concurrency 引数で上書き可）

qdrant:
  url: "http://localhost:6333"   # Qdrant接続先。コンテナ内では環境変数 QDRANT_URL が優先
  collection: "waiwai_chunks"    # コレクション名（全guild共有・payloadのguild_idで分離）

embedding:
  model: "text-embedding-3-small"  # OpenAI embeddingモデル（indexer.py / RAG検索で使用）
  dimensions: 1536                 # ベクトル次元数（コレクション作成時に固定される）
  batch_size: 100                  # 1回のembedding APIに渡すチャンク数

rag:
  rewriter_model: "google/gemini-2.5-flash"   # Query Rewriter（OpenRouter経由）
  answer_model: "deepseek/deepseek-v3.2"      # 回答生成LLM（OpenRouter経由・OI-16でKimi K2から変更）
  rewriter_max_tokens: 256                    # 書き換え出力の上限（過大なtoken要求で残高不足になるのを防ぐ）
  rewriter_max_query_chars: 60                # #64: 書き換え結果がこの字数を超え [NO_SEARCH] でなければ
                                              # 応答文混入とみなし元クエリで検索（非破壊フォールバック・既定60）
  answer_max_tokens: 1500                     # 回答出力の上限（OI-16: completionの暴走を防ぐ安全弁）
  top_k: 5                                    # 回答に渡すチャンク数（OI-16で10→5に削減・リランク/recency有効時は精選後の件数）
  history_max_turns: 5                        # マルチターン会話で渡す直近やり取りの上限ペア数（OI-10）
                                              # 0で無効（1問1答に戻す）。大きいほど文脈を保てるがprompt tokenが増える
  history_max_chars: 4000                      # 履歴の合計文字数バジェット（回答LLM向け・超過分は古い方から落とす）
                                              # 長い回答が積み重なってtokenが膨張するのを防ぐ安全弁（0で無制限）
  rewriter_history_max_turns: 2               # Query Rewriterに渡す履歴のペア数（指示語解決には少数で十分）
  rewriter_history_max_chars: 1000            # 同・文字数バジェット。履歴はrewriterにも乗るため別途絞ってtoken二重計上を抑制
  guild_name: "わいわい"                       # プロンプト用サーバー名のデフォルト
                                              # （Bot経由のリクエストでは実サーバー名が優先される）
  debug_trace: false                          # OI-21: 質問/ヒットチャンク/回答を chat_trace に保存（デバッグ用）
                                              # 既定OFF。質問・回答本文を残すため本番はプライバシー上 false 運用が前提
  memory_enabled: false                       # OI-24: 明示メモリ機能（既定OFF）
                                              # 「覚えておいて」検知→LLM抽出→memories保存（書き込み）と
                                              # guildの教わった事実を回答プロンプトへ全件注入（読み取り）を有効化。
                                              # ※項目追加時は各環境の実config.ymlも更新すること（既定OFFで無効化される）
  search_gate: true                           # OI-23: 検索ゲート（既定ON）
                                              # 挨拶・雑談・ゲーム・一般質問など過去ログ参照が不要な入力を
                                              # Query Rewriter が [NO_SEARCH] と判定したら、埋め込み・検索・
                                              # リランクをスキップして素の雑談として回答する（コスト/レイテンシ削減）。
                                              # 誤スキップを避けるため判定は「迷ったら検索」に倒している。
                                              # false にすると常に検索する（従来動作）。
  auto_memory:                                # #56 案C: 会話から記憶を自動抽出して育てる（mem0方式・既定OFF）
    enabled: false                            # true で有効化。worker が取り込み後に許可chの最近チャンクから
                                              # 永続事実を抽出し ADD/UPDATE/DELETE 候補を memories に pending 投入する。
                                              # **承認するまで回答に出ない**（admin /memories で人が承認）。DELETEはsoft-deleteのみ。
                                              # 回答への注入自体は memory_enabled も true である必要がある（二重ガード）。
    max_chunks: 30                            # 1回の抽出で見る最近チャンク数（許可ch限定）
    max_tokens: 800                           # 突合LLMの出力上限。JSON配列が途中で切れると抽出0件になるため広めに取る
  mimic_enabled: false                        # #49: 「真似っこ」モード（/oracle mimic）を有効化（既定OFF）
                                              # 対象メンバーの口調・性格を真似て回答する（channel単位・本人保護あり）
  mimic:                                      # #49: 真似っこの調整（mimic_enabled=true のときだけ効く）
    sample_limit: 300                         # 人格カード生成時に対象者の発言を最大何件まで使うか
    min_sample_count: 30                      # これ未満は confidence=low（特徴が薄ければ開始を断ることもある）
    require_optin: false                      # MVPは false。公開/課金前は true（本人の事前同意を必須化）にする
  hybrid:                                     # #54: ハイブリッド検索（dense + BM25 sparse を RRF融合・日本語はSudachiPyで分割）
    enabled: false                            # true で有効化。本番ONは実データA/Bで効果実証してから（要: 全チャンク再インデックス）
    prefetch_k: 30                            # 各レーン(dense/sparse)で融合前に取る候補数
  reranker:                                   # OI-9: 検索結果のリランキング（任意・既定オフ）
    enabled: false                            # true で有効化（要 .env の JINA_API_KEY）
    provider: "jina"                          # 現状 jina のみ対応
    model: "jina-reranker-v2-base-multilingual"
    top_n: 30                                 # リランク前に dense で取る候補数（→ top_k 件に精選）
  recency:                                    # #55: 時間減衰で検索を時系列に強くする（過去ログのみ・既定オフ）
    enabled: false                            # true で有効化。本番ONは実データA/Bで効果実証してから
    half_life_days: 30                        # 半減期(日)。この日数経過でスコア寄与が半減。小さいほど新しい話を優先
    recent_half_life_days: 7                  # 「最近」系クエリ検出時の短い半減期（時系列依存質問で減衰を強める）
    score_floor: 0.1                          # 減衰係数の下限（古くても高関連チャンクを完全には捨てない・0で床なし）
    candidate_k: 30                           # 減衰で再ランクする前に取る候補数（→ top_k 件に精選）
    recent_boost: true                        # 「最近」系キーワード検出で recent_half_life_days に切り替える

pricing:                              # usage_log のコスト推定に使う単価（USD/100万トークン）
  "google/gemini-2.5-flash": {input: 0.30, output: 2.50}
  "deepseek/deepseek-v3.2":  {input: 0.27, output: 0.40}  # OI-16で採用（Kimi K2比 約1/3）
  "gpt-4.1-nano":            {input: 0.10, output: 0.40}  # contextualizer
  "text-embedding-3-small":  {input: 0.02, output: 0.0}
  "jina-reranker-v2-base-multilingual": {input: 0.02, output: 0.0}  # ※概算・要更新

worker:
  poll_interval_seconds: 10  # ingest_jobs キューの確認間隔（秒）
  sync_interval_hours: 24    # 定期syncの間隔（最後の取り込み完了からの経過時間）
```

> `pricing` は推定コスト算出用（`src/usage.py`）。価格は変動するので最新値に各自で更新する。
> 掲載が無いモデルはコスト0で計上される（トークン数の記録は残る）。

> Dify / Ollama 関連のセクションは廃止した（2026-06-11）。
> 旧設定は git 履歴と `dify/waiwai-oracle.yml`（移行元プロンプトの記録）を参照。

> `rag.recency`（#55）は検索ヒット（過去ログチャンク）に anchor_timestamp ベースの半減期減衰を
> 掛けて時系列に強くする。永続事実（memories）は `memory_provider` 経由で別注入され検索を通らないため
> 構造的に減衰対象外。案A（ハイブリッド #54）の RRF 融合スコアの上に乗算で重ねる設計で、enabled が
> true でも検索の並べ替えが変わるだけ（再インデックス不要）。本番ONは `scripts/eval_recency.py` で
> 実データA/B（時系列で平均ageが下がる／話題でヒット率が落ちない）を確認してから。半減期は要チューニング。

> `rag.hybrid`（#54）は dense ベクトル検索と BM25 sparse 検索を RRF（Reciprocal Rank Fusion）で
> 融合し、固有名詞・専門用語の取りこぼしを減らす。日本語は SudachiPy で分割する（`src/sparse.py`）。
> **ON にするには全チャンクの再インデックスが必要**（`scripts/migrate_hybrid_reindex.py`）。
> recency（#55）は hybrid の融合スコアの上に乗算で重ねる設計。

> **注意（config ドリフト・#44）:** `config.yml.example` は一部の既定値が実運用とずれている場合がある
> （例: `answer_model` が旧 Kimi K2 のまま等）。本ドキュメントは OI-16 以降の現行値を正とする。
> example の同期は #44 で別途対応する（コード扱いのため PR 経由）。

## .env

```env
DISCORD_TOKEN=your-discord-bot-token
OPENAI_API_KEY=your-openai-api-key   # contextualizer.py / embedding で使用（openai.api_key が空の場合）
POSTGRES_PASSWORD=oracle             # composeのpostgresサービスのパスワード
DATABASE_URL=postgresql://oracle:oracle@localhost:5432/oracle  # ホストから手動スクリプトを実行する場合
# OPENROUTER_API_KEY=...             # RAG用LLM（config.yml の openai.api_key が空の場合）
# ORACLE_API_URL=http://localhost:8000  # Bot → APIサーバ接続先（composeでは自動設定）
# ORACLE_API_TOKEN=...                  # Bot→API 共有シークレット（設定すると /chat・/remember が認証必須・OI-45）
# QDRANT_URL=http://qdrant:6333         # Qdrant接続先オーバーライド（composeでは自動設定）
# TEST_DATABASE_URL=...                 # pytest用DB接続先（デフォルト: localhost:5432/oracle_test）
ADMIN_PASSWORD=change-me              # 管理ポータル（src/admin）のログインパスワード（未設定だとログイン不可）
# ADMIN_SESSION_SECRET=...             # セッション署名鍵（任意・未設定なら ADMIN_PASSWORD から導出）
```

> コンテナ内の `DATABASE_URL` は docker-compose.yml の `environment` で
> `postgres` サービス向きに上書きされるため、.env の値はホスト実行時のみ使われる。

## 分離ルール

| 種別 | ファイル | Gitコミット |
|---|---|---|
| 動作パラメータ | config.yml | ✅ OK |
| APIキー・トークン・接続文字列 | .env | ❌ 必ずgitignore |

## Docker環境での読み込み

- `config.yml` → コンテナ内 `/app/config.yml` にマウント
- `.env` → `docker-compose.yml` の `env_file` で読み込み
