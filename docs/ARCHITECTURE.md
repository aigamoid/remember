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
│   ├── config.py          # config.yml / .env ロード
│   ├── models.py          # dataclass定義（RawMessage, Chunk等）
│   ├── db.py              # SQLite操作
│   ├── formatter.py       # メッセージ→テキスト変換（共通）
│   ├── collectors/
│   │   ├── base.py        # MessageCollector ABC
│   │   └── text_channel.py # TextChannelCollector実装
│   ├── chunker.py         # チャンク生成ロジック
│   └── uploader.py        # Dify Knowledge API呼び出し
├── dry_run.py             # メッセージ数カウントのみ（取得なし）
├── chunker.py             # Phase 2 エントリポイント
├── uploader.py            # Phase 3 エントリポイント
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
uploader.py                  # チャンネルごとに messages を連結
    ↓
Dify Knowledge API           # ナレッジベース作成 → ドキュメントアップロード
    ↓
db.py                        # upload_state に dataset_id/document_id 保存
```

> **Note:** Phase 2 の chunker.py（スライディングウィンドウ）は chunk_index テーブルに保存するが、
> Phase 3 ではチャンキングを Dify に委ねるため、uploader は messages テーブルから直接読む。

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
- chunker: chunk_id は anchor_msg_id + ウィンドウサイズから MD5 生成。再実行時は既存をスキップ。
- uploader: upload_state.status が 'indexed' のチャンネルをスキップ。dataset_id が既存ならナレッジベース作成もスキップ。

### 各ファイルの責務上限
1ファイル100行以内を目安とする。超える場合は分割を検討すること。

### 設定と機密情報の分離
- 動作パラメータ → `config.yml`（Gitにコミットしてよい）
- APIキー・トークン類 → `.env`（必ずGitignore）
