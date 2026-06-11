# アーキテクチャ

## ディレクトリ構成

```
waiwai-oracle/
├── README.md
├── CLAUDE.md
├── docs/
│   ├── ARCHITECTURE.md   (このファイル)
│   ├── SCHEMA.md
│   ├── CONFIG.md
│   └── OPEN_ISSUES.md
├── src/
│   ├── config.py          # config.yml ロード
│   ├── models.py          # dataclass定義（RawMessage, Chunk等）
│   ├── db.py              # SQLite操作
│   ├── formatter.py       # メッセージ→テキスト変換（共通）
│   ├── collectors/
│   │   ├── base.py        # MessageCollector ABC
│   │   └── text_channel.py # TextChannelCollector実装
│   ├── chunker.py         # チャンク生成ロジック（時間ギャップ方式）
│   ├── contextualizer.py  # LLMによる context_text 付与ロジック（Phase 2.5）
│   ├── exporter.py        # chunk_index → output/*.txt 出力（旧Dify用・任意）
│   ├── embedder.py        # OpenAI Embedding APIラッパー
│   ├── vectorstore.py     # Qdrant操作（guild_idマルチテナント前提）
│   ├── indexer.py         # チャンク → embedding → Qdrant 登録（Phase 4）
│   ├── rag/
│   │   ├── prompts.py     # Query Rewriter・わいわいちゃんプロンプト（Difyから移植）
│   │   ├── llm.py         # OpenRouterチャットLLMラッパー
│   │   └── engine.py      # RAG回答エンジン（書き換え→検索→生成）
│   ├── api.py             # FastAPI APIサーバ（POST /chat, GET /health）
│   └── cli.py             # CLIチャットロジック（/chat クライアント）
├── moimoichan_Discordbot/
│   ├── bot.py             # Discord Bot エントリポイント
│   ├── oracle_client.py   # RAG APIクライアント
│   └── Dockerfile
├── dry_run.py             # メッセージ数カウントのみ（取得なし）
├── crawler.py             # Phase 1 エントリポイント
├── chunker.py             # Phase 2 エントリポイント
├── contextualizer.py      # Phase 2.5 エントリポイント
├── exporter.py            # Phase 3 エントリポイント（旧Dify用・任意）
├── indexer.py             # Phase 4 エントリポイント
├── chat_cli.py            # CLIフロントエンド（動作確認用）
├── config.yml.example
├── .env.example
├── Dockerfile
├── docker-compose.yml     # oracle / qdrant / api / bot の4サービス
└── data/                  # Dockerボリュームマウント先（.gitignore）
    ├── messages.db
    └── qdrant/            # Qdrant永続化データ
```

## データフロー

### 取り込みパイプライン（バッチ）

```
Discord API
    ↓
crawler.py → collectors/text_channel.py   # TextChannelCollector
    ↓
db.py                        # messages テーブルに保存
    ↓
chunker.py                   # 時間ギャップ方式でチャンク生成
    ↓
db.py                        # chunk_index テーブルに保存（context_text=NULL）
    ↓
contextualizer.py            # LLMで context_text を生成・付与（Phase 2.5）
    ↓
indexer.py                   # context_text + chunk_text を embedding して Qdrant に登録
    ↓
Qdrant（payload に guild_id / channel_name / chunk_text / context_text 等）
```

### 回答フロー（オンライン）

フロントエンドは2モード（どちらも同じAPIを呼ぶ薄いクライアント）:
- Discord Bot: `moimoichan_Discordbot/bot.py` → `oracle_client.py`
- CLI（動作確認用）: `chat_cli.py` → `src/cli.py`

```
Discord ユーザー（@メンション） or CLI入力
    ↓ POST /chat {guild_id, query}
src/api.py（FastAPI）
    ↓
src/rag/engine.py
    1. Query Rewriter（Gemini 2.5 Flash・現在日時注入）
    2. embedding → Qdrant 検索（guild_id フィルタ必須・top_k=10）
    3. 回答生成（Kimi K2・わいわいちゃんプロンプト）
    ↓
回答 JSON → Bot が Discord に返信
```

## 設計方針

### Collector抽象化
`collectors/base.py` に `MessageCollector` ABCを定義する。
現在は `TextChannelCollector` のみ実装。スレッド対応は将来 `ThreadCollector` を追加するだけでよい構造にしておく。

```python
class MessageCollector(ABC):
    @abstractmethod
    async def collect(self, conn: sqlite3.Connection, run_id: str) -> int:
        """メッセージを収集して DB に保存し、収集件数を返す。"""
        ...
```

### マルチテナント前提（SaaS化に向けて）
- Qdrant の全ポイントは payload に `guild_id` を持ち、検索時は必ず guild_id でフィルタする
- これにより他の Discord サーバーのデータが回答に混ざることを構造的に防ぐ
- 現状は単一テナント（config.yml の guild_id）。複数サーバー対応は次フェーズ

### 冪等性
- chunker: chunk_id は anchor_msg_id（チャンク先頭メッセージID）の MD5。INSERT OR REPLACE により再実行で chunk_text が更新される。チャンキング方式変更時は `python chunker.py --clean` で全削除してから再生成する。
- indexer: chunk_id から決定的に UUID を生成して Qdrant の点IDにするため、再実行は上書きになる。`--clean` でコレクション削除 + status リセット、`--all` で全件再登録。
- exporter: 実行のたびに output/ を上書き生成する。状態管理なし。

### 各ファイルの責務上限
1ファイル100行以内を目安とする。超える場合は分割を検討すること。

### 設定と機密情報の分離
- 動作パラメータ → `config.yml`（Gitにコミットしてよい）
- APIキー・トークン類 → `.env`（必ずGitignore）
