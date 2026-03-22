# アーキテクチャ

## ディレクトリ構成

```
waiwai-oracle/
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
│   └── exporter.py        # chunk_index → output/*.txt 出力
├── dry_run.py             # メッセージ数カウントのみ（取得なし）
├── crawler.py             # Phase 1 エントリポイント
├── chunker.py             # Phase 2 エントリポイント
├── contextualizer.py      # Phase 2.5 エントリポイント
├── exporter.py            # Phase 3 エントリポイント
├── config.yml.example
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── data/                  # Dockerボリュームマウント先（.gitignore）
    └── messages.db
```

## データフロー

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
db.py                        # chunk_index.context_text を更新
    ↓
exporter.py                  # chunk_index を読んで output/*.txt に出力
    ↓
output/{safe_name}_{channel_id[:8]}_{YYYYMMDD}.txt  # Dify へブラウザから手動アップロード
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

### 冪等性
- chunker: chunk_id は anchor_msg_id（チャンク先頭メッセージID）の MD5。INSERT OR REPLACE により再実行で chunk_text が更新される。チャンキング方式変更時は `python chunker.py --clean` で全削除してから再生成する。
- exporter: 実行のたびに output/ を上書き生成する。状態管理なし。

### 各ファイルの責務上限
1ファイル100行以内を目安とする。超える場合は分割を検討すること。

### 設定と機密情報の分離
- 動作パラメータ → `config.yml`（Gitにコミットしてよい）
- APIキー・トークン類 → `.env`（必ずGitignore）
