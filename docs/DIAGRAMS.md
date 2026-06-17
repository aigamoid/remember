# 処理フロー・設計図（Mermaid）

現在の waiwai-oracle の全体像を4つの視点で図解する。
（2026-06-11 時点: SaaS化ステップ2「マルチテナント自動取り込み」反映後）

## ① 全体像（コンテナ構成・運用視点）

```mermaid
flowchart LR
    subgraph FRONT["フロントエンド（薄いクライアント・2モード）"]
        CLI["chat_cli.py<br>（CLI・動作確認用）"]
        BOT["botコンテナ<br>moimoichan_Discordbot<br>/oracleコマンド"]
    end

    subgraph COMPOSE["docker compose"]
        API["apiコンテナ<br>FastAPI src/api.py<br>:8000"]
        WORKER["workerコンテナ<br>worker.py<br>取り込みジョブ処理・定期sync"]
        QD[("qdrantコンテナ<br>ベクトルDB :6333<br>data/qdrant/")]
        PG[("postgresコンテナ<br>:5432 data/postgres/<br>messages / chunk_index /<br>guilds / ingest_jobs")]
        ORACLE["oracleコンテナ<br>手動バッチ実行用<br>（crawler〜indexer）"]
    end

    subgraph EXT["外部API"]
        DISCORD["Discord API"]
        OAI["OpenAI<br>embedding"]
        ORT["OpenRouter<br>Gemini / Kimi / DeepSeek"]
    end

    CLI -- "POST /chat" --> API
    BOT -- "POST /chat" --> API
    BOT -- "ジョブ投入・許可設定" --> PG
    WORKER -- "ジョブ取得・結果記録" --> PG
    WORKER -- "差分クロール" --> DISCORD
    WORKER --> OAI & ORT
    WORKER --> QD
    API --> QD
    API --> OAI & ORT
    ORACLE --> PG
    ENV[".env<br>APIキー類"] -.-> API & WORKER & ORACLE & BOT
```

**ポイント**: Bot は「ジョブを予約する係」、worker は「実際に取り込む係」に分業。
重い処理（クロール・LLM・embedding）はすべて worker に隔離され、Bot の応答は止まらない。

## ② サーバー導入から質問できるまで（自動取り込みフロー）

```mermaid
sequenceDiagram
    participant Admin as サーバー管理者
    participant B as Bot（bot.py）
    participant PG as Postgres<br>(ingest_jobs)
    participant W as worker.py
    participant D as Discord API
    participant Q as Qdrant

    Note over Admin,B: Botをサーバーに招待
    B->>PG: guilds に登録（on_guild_join）
    B-->>Admin: 「/oracle allow で読んでいい<br>チャンネルを教えてね」

    Admin->>B: /oracle allow #雑談
    B->>PG: allowed_channels 追加 + ingestジョブ投入
    B-->>Admin: ✅ 取り込みを始めるね（ephemeral）

    W->>PG: ジョブを claim（FOR UPDATE SKIP LOCKED）
    W->>D: 許可チャンネルだけ差分クロール（REST）
    W->>W: チャンク化 → context付与 → embedding
    W->>Q: upsert（payload に guild_id）
    W->>PG: ジョブ完了（result に件数）

    Admin->>B: /oracle status
    B-->>Admin: 取り込み済み件数・最新ジョブ状態

    Note over W,PG: 以降は24時間ごとに自動で差分sync<br>（/oracle sync で即時実行も可）
```

**ポイント**: 招待しただけでは何も読まない（opt-in）。`/oracle deny` で許可を取り消すと
該当チャンネルのデータが Qdrant / Postgres から削除され、Bot をサーバーから外すと
サーバー全体のデータが削除される（purgeジョブ）。

## ③ 取り込みパイプライン（ワーカー内部・ジョブ1件の処理）

```mermaid
flowchart TB
    JOB["ingestジョブ<br>（/oracle allow・sync・定期スケジューラが投入）"]
    JOB --> CRAWL["① crawl<br>allowed_channels のみ<br>crawl_state の続きから差分取得"]
    CRAWL --> MSG[("messages<br>guild_id付き")]
    MSG --> CHUNK["② chunk<br>時間ギャップ60分で会話単位に分割<br>ノイズ除去・短文吸収"]
    CHUNK --> CI[("chunk_index<br>本文が変わったチャンクだけ<br>context_text=NULL / status=pending に戻る")]
    CI --> CTX["③ contextualize<br>context_text が NULL のチャンクだけ<br>LLMで1〜2文の文脈説明を付与"]
    CTX --> EMB["④ index<br>『context + chunk』を embedding<br>（8,000トークン超は切り詰め）"]
    EMB --> QD[("Qdrant<br>uuid5(chunk_id)で上書きupsert")]
    QD --> DONE["ジョブ完了<br>result: crawled=N chunks=N contexts=N indexed=N"]
```

**ポイント**: 各段階が冪等なので、途中で失敗しても次のジョブで続きから処理される。
差分syncでは「新着分＋伸びた末尾チャンク」だけが再処理され、APIコストが最小になる。

## ④ 回答フロー（質問1回あたりの処理）

```mermaid
sequenceDiagram
    participant U as ユーザー（CLI/Discord）
    participant A as FastAPI /chat
    participant E as RagEngine
    participant G as Gemini 2.5 Flash<br>(OpenRouter)
    participant O as OpenAI embedding
    participant Q as Qdrant
    participant K as Kimi K2<br>(OpenRouter)

    U->>A: guild_id + guild_name + 質問
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
- guild_name は Bot がリクエストに載せるので、どのサーバーでも「そのサーバーの名前」で答える
- ①が失敗しても止まらず元の質問で検索続行（フォールバック設計）
- 所要時間の大半は④のKimi K2の生成。高速化するならここのモデル変更が効く
