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
│   ├── main.py            # CLIエントリポイント（引数解析のみ）
│   ├── config.py          # config.yml / .env ロード
│   ├── models.py          # dataclass定義（RawMessage, Chunk等）
│   ├── db.py              # SQLite操作
│   ├── collectors/
│   │   ├── base.py        # MessageCollector ABC
│   │   └── text_channel.py # TextChannelCollector実装
│   ├── chunker.py         # チャンク生成ロジック
│   └── uploader.py        # Dify Knowledge API呼び出し
├── dry_run.py             # メッセージ数カウントのみ（取得なし）
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
collectors/text_channel.py   # TextChannelCollector
    ↓
db.py                        # messages テーブルに保存
    ↓
chunker.py                   # スライディングウィンドウ（前後2件）
    ↓
db.py                        # chunk_index テーブルに保存
    ↓
uploader.py                  # Dify Knowledge API にPOST
    ↓
db.py                        # chunk_index.dify_doc_id, status 更新
```

## 設計方針

### Collector抽象化
`collectors/base.py` に `MessageCollector` ABCを定義する。
現在は `TextChannelCollector` のみ実装。スレッド対応は将来 `ThreadCollector` を追加するだけでよい構造にしておく。

```python
class MessageCollector(ABC):
    @abstractmethod
    async def collect(self) -> AsyncIterator[RawMessage]:
        pass
```

### 冪等性
chunk_idはanchor_msg_idとウィンドウサイズからMD5で生成する。
再実行時はchunk_index.statusが'indexed'のものをスキップする。

### 各ファイルの責務上限
1ファイル100行以内を目安とする。超える場合は分割を検討すること。

### 設定と機密情報の分離
- 動作パラメータ → `config.yml`（Gitにコミットしてよい）
- APIキー・トークン類 → `.env`（必ずGitignore）
