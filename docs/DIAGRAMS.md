# 処理フロー・設計図（Mermaid）

現在の waiwai-oracle の全体像を3つの視点で図解する。
（2026-06-11 時点: Dify廃止・Qdrant + FastAPI 自前RAGスタック移行後）

## ① 全体像（コンテナ構成・運用視点）

```mermaid
flowchart LR
    subgraph FRONT["フロントエンド（薄いクライアント・2モード）"]
        CLI["chat_cli.py<br>（CLI・動作確認用）"]
        BOT["botコンテナ<br>moimoichan_Discordbot"]
    end

    subgraph COMPOSE["docker compose"]
        API["apiコンテナ<br>FastAPI src/api.py<br>:8000"]
        QD[("qdrantコンテナ<br>ベクトルDB :6333<br>data/qdrant/")]
        ORACLE["oracleコンテナ<br>バッチ実行用<br>（crawler〜indexer）"]
    end

    subgraph EXT["外部API"]
        OAI["OpenAI<br>embedding"]
        ORT["OpenRouter<br>Gemini / Kimi / DeepSeek"]
    end

    SQLITE[("SQLite<br>data/messages.db")]

    CLI -- "POST /chat" --> API
    BOT -- "POST /chat" --> API
    API --> QD
    API --> OAI & ORT
    ORACLE --> SQLITE
    ORACLE --> QD
    ENV[".env<br>APIキー類"] -.-> API & ORACLE
```

**ポイント**: フロントは2つともAPIを呼ぶだけ。RAGの頭脳はすべて `api` コンテナ側に
あるので、フロントを増やしても（Web UIなど）本体は無変更でよい。

## ② 取り込みパイプライン（Phase 0〜4・バッチ）

```mermaid
flowchart TB
    DISCORD["Discord API"] -->|"Phase 1: crawler.py<br>全メッセージ取得"| MSG[("messagesテーブル<br>36,128件")]
    MSG -->|"Phase 2: chunker.py<br>時間ギャップ60分で会話単位に分割<br>ノイズ除去・短文吸収"| CHUNK[("chunk_indexテーブル<br>8,364チャンク<br>context_text=NULL")]
    CHUNK -->|"Phase 2.5: contextualizer.py<br>DeepSeekが各チャンクに<br>1〜2文の文脈説明を付与"| CTX[("chunk_index<br>context_text付き")]
    CTX -->|"Phase 4: indexer.py"| EMB["Embedder<br>『context + chunk』を<br>text-embedding-3-smallでベクトル化<br>（8,000トークン超は切り詰め）"]
    EMB -->|"uuid5(chunk_id)を点IDに<br>upsert（再実行=上書きで冪等）"| QDRANT[("Qdrant<br>payload: guild_id, channel_name,<br>chunk_text, context_text, timestamp")]
    CTX -.->|"Phase 3: exporter.py<br>（旧Dify用・いまは任意）"| TXT["output/*.txt"]
```

**ポイント**: 各フェーズは独立したスクリプトで、途中失敗しても再実行すれば
続きから動く（status列で管理）。

## ③ 回答フロー（質問1回あたりの処理）

```mermaid
sequenceDiagram
    participant U as ユーザー（CLI/Discord）
    participant A as FastAPI /chat
    participant E as RagEngine
    participant G as Gemini 2.5 Flash<br>(OpenRouter)
    participant O as OpenAI embedding
    participant Q as Qdrant
    participant K as Kimi K2<br>(OpenRouter)

    U->>A: guild_id + 質問
    A->>E: answer()
    E->>G: ① クエリ書き換え<br>（現在日時JSTを注入、temp 0.2）
    G-->>E: 検索用クエリ<br>（失敗時は元の質問で続行）
    E->>O: ② クエリをベクトル化
    O-->>E: 1536次元ベクトル
    E->>Q: ③ 類似検索<br>guild_idフィルタ必須・top_k=10
    Q-->>E: チャンク10件（記憶の断片）
    E->>K: ④ わいわいちゃんプロンプト<br>＋記憶の断片＋元の質問（temp 0.7）
    K-->>E: 回答（<think>タグは除去）
    E-->>A: answer + rewritten_query + sources
    A-->>U: 回答表示（25〜37秒）
```

**ポイント**:

- ③の **guild_idフィルタが必須**なのがマルチテナントの肝。別サーバーのデータは構造的に見えない
- ①が失敗しても止まらず元の質問で検索続行（フォールバック設計）
- 所要時間の大半は④のKimi K2の生成。高速化するならここのモデル変更が効く
