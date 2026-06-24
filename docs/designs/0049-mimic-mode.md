# 設計書: 真似っこモード（mimic mode・#49）

> **状態**: 確定版（2026-06-23）。3者レビュー: Claude Code=PASS / Codex=要修正→反映済 /
> Aider=今回限り省略（人間合意・ローカルルールの例外として記録）。
> **元 plan**: GitHub Issue #49 のコメント（codex-fugu 作成）。本書はそれに人間の決定と
> Codex レビュー指摘（P0〜P2）を反映した確定版。
> **整合させた確定設計決定**: OI-17（function calling 当面不使用）/ OI-16（top_k=5・DeepSeek V3.2 コスト最適化）。
> **採番**: 新規参照は `#NN`。コード内の既存 `OI-XX` は書き換えない。

---

## 0. 確定した設計判断（人間決定・2026-06-23）

| 項目 | 決定 | 備考 |
|---|---|---|
| 対象/権限 | 管理者が誰でも真似OK・本人 opt-out で除外 | 宣言で「本人ではなくモノマネ」を明示。公開前に opt-in 必須化（Phase 2）。 |
| deny時カード | `personas` は guild 資産として保持 | ch 削除（`purge_channel`）では消さない。`purge_guild`・Bot退出でのみ削除。 |
| MVP範囲 | フル（Discord `/oracle mimic` まで） | 管理者限定なので事故は小さい。 |
| スコープ | channel 単位・guild fallback しない | `scope=channel` のとき意図せぬ全体適用を防ぐ（Codex P1）。 |
| channel_id 正典 | `ChatRequest.channel_id` を新設 | 旧 `user="channel_id:user_id"` 埋め込みは段階廃止（Codex/Claude P0）。 |
| profile_model | `answer_model` 流用 | 新モデル追加なし。 |
| センシティブ属性 | プロンプト禁止＋保存前 denylist 検査 | プロンプト依存のみにしない（Codex P1）。 |

---

## 1. 全体アーキテクチャ

```
[開始] /oracle mimic @user （管理者限定）
  → Bot OracleGroup.mimic → OracleClient.mimic_start → POST /mimic/start
  → consent チェック（optout なら開始拒否）
  → db.fetch_member_messages → RagEngine.build_persona_card（LLM1回・usage記録）
  → card を denylist 検査 → db.upsert_persona_card + db.set_mimic_state（channel単位）
  → 宣言文（deterministic 生成）を返す

[opt-out] /oracle mimic optout （★本人・一般メンバーも実行可）
  → POST /mimic/optout → db.set_persona_consent(optout) ＋ 既存カードあれば無効化
  → 以後その人は /mimic/start で開始拒否

[回答] on_message → POST /chat (guild_id, channel_id, query, history, speaker)
  → RagEngine.answer → MimicProvider(guild_id, channel_id)（channel行のみ・fallbackなし）
  → 人格カードを {mimic_section} に注入 → 既存どおり rewrite→検索→回答
  （mimic 無し or disabled なら {mimic_section} は空文字でブロック消滅＝従来のれみちゃん）

[解除] /oracle mimic off → POST /mimic/stop → db.clear_mimic_state → 「れみに戻るね〜」
```

**原則**: 新 RAG 経路を作らない／既定 OFF（`rag.mimic_enabled`）／API が状態の正典／
function calling は使わない（OI-17）。

---

## 2. opt-out 機構（★当初 plan に無い確定追加要素）

「管理者が誰でも真似OK・本人 opt-out で除外」を選んだため、以下を追加する。

- **誰が opt-out できるか**: 本人（一般メンバー）が自分を外せる。`/oracle mimic optout` は
  `OracleGroup`（管理者限定）とは別に**一般メンバーも実行可**にする（`/oracle help` と同様に
  コマンド単位で権限を緩める）。管理者による代行 opt-out も可。
- **保存先**: `personas.consent`（`'unknown'|'optin'|'optout'`）。カード未生成の人も opt-out
  できるよう、`set_persona_consent()` は personas 行が無ければ **consent だけの行を先に作る**
  （`card` は空 JSON・`sample_count=0`）。
- **強制点**: `POST /mimic/start` の入口で `consent == 'optout'` なら `started=false` ＋
  理由文を返す（コスト 0・カード生成もしない）。
- opt-out した人が再び許可したい場合は将来 `/oracle mimic optin`（Phase 2）。MVP では
  optout のみ実装。

---

## 3. 新規 DB テーブル DDL（`src/db.py` の init_schema に `CREATE TABLE IF NOT EXISTS` 追記）

```sql
-- 生成した人格カード（#49）。guild+author 単位＝「サーバー全体でのその人の傾向」。
-- ★guild 資産として保持し、purge_channel では削除しない（人間決定）。
CREATE TABLE IF NOT EXISTS personas (
    guild_id     TEXT NOT NULL,
    author_id    TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    card         JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {nicknames,personality,likes,speech_style,catchphrases,confidence}
    sample_count INTEGER NOT NULL DEFAULT 0,
    consent      TEXT NOT NULL DEFAULT 'unknown',     -- 'unknown'|'optin'|'optout'
    created_by   TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT,
    PRIMARY KEY (guild_id, author_id)
);
CREATE INDEX IF NOT EXISTS idx_personas_guild ON personas (guild_id);

-- 「いま誰を真似中か」。channel 単位（scope=channel 確定なので channel_id は常に実値）。
CREATE TABLE IF NOT EXISTS mimic_state (
    guild_id   TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    author_id  TEXT NOT NULL,
    started_by TEXT,
    started_at TEXT NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);
CREATE INDEX IF NOT EXISTS idx_mimic_state_guild ON mimic_state (guild_id);

-- カード生成用の対象者発言取得を速くする。
CREATE INDEX IF NOT EXISTS idx_messages_guild_author_timestamp
    ON messages (guild_id, author_id, timestamp DESC);
```

### 削除整合（Codex P0・#31/OI-44 の教訓）
- `purge_channel`（`/oracle deny`）: **`personas` は触らない**（guild 資産）。
  `mimic_state` は**その channel の行だけ削除**（真似中だった ch が消えるため）。
- `purge_guild`（Bot退出・guild purge）: `personas`・`mimic_state` を**guild 単位で全削除**。
- `tests/conftest.py` の `_TRUNCATE` に `personas, mimic_state` を追加（テスト分離に必須）。

---

## 4. 新規/変更ファイルと関数（シグネチャ案）

### src/db.py
```python
def fetch_member_messages(conn, guild_id, author_id, limit=300) -> list[dict]
def resolve_member_name(conn, guild_id, author_id) -> str | None
def upsert_persona_card(conn, guild_id, author_id, display_name, card, sample_count, created_by=None) -> None
def fetch_persona_card(conn, guild_id, author_id) -> dict | None
def set_persona_consent(conn, guild_id, author_id, consent) -> None   # 行が無ければ consent だけ先に作る
def get_persona_consent(conn, guild_id, author_id) -> str             # 'unknown' if 行なし
def delete_persona_card(conn, guild_id, author_id) -> bool
def set_mimic_state(conn, guild_id, channel_id, author_id, started_by=None) -> None
def get_active_mimic(conn, guild_id, channel_id) -> dict | None       # channel 行のみ・fallback なし
def clear_mimic_state(conn, guild_id, channel_id) -> bool
```
- `purge_channel_data` / `purge_guild_data` に上記の削除整合を実装。

### src/mimic.py（新規・src/memory.py を踏襲）
```python
class MimicProvider:
    def __init__(self, dsn: str | None = None) -> None: ...
    def __call__(self, guild_id: str, channel_id: str) -> dict | None:
        # get_active_mimic(channel) → fetch_persona_card を結合。
        # 接続失敗・該当なしは None（mimic 無しで回答継続）。
```

### src/rag/prompts.py
- `ANSWER_SYSTEM_PROMPT` に `{mimic_section}` を追加（差し込み位置=`{speaker_section}` 直後・
  キャラクター特性ブロックの前。れみちゃん基本人格を一時上書きする役割）。
- 追加: `PERSONA_EXTRACT_PROMPT` / `MIMIC_SECTION` /
  `build_mimic_section(card, display_name)` / `build_mimic_declaration(card, display_name)` /
  `SENSITIVE_DENYLIST`（センシティブ属性語の検査用）。

### src/rag/engine.py
- `__init__(..., mimic_provider=None)`、`self.mimic_enabled = bool(rag_cfg.get("mimic_enabled", False))`。
- `answer(..., channel_id: str | None = None)` を追加（CLI/テストは未指定で従来動作）。
- memories と同じ「あれば注入・無ければ空文字」パターンで `{mimic_section}` を注入。
- `build_persona_card(guild_id, display_name, samples, user_id=None) -> dict | None`
  （LLM1回・usage `kind='mimic_profile'`・JSON 崩れ/素材不足/denylist 検査で除去後空なら None）。

### src/api.py
- `build_engine`: `rag.mimic_enabled` ON 時のみ `MimicProvider()` を渡す（二重ガード）。
- `ChatRequest.channel_id: Optional[str]` を新設 → `/chat` で `engine.answer(channel_id=...)`。
  **旧 `user="channel_id:user_id"` 経路は段階廃止**（移行期は新フィールド優先・無ければ user から分解）。
- `POST /mimic/start {guild_id,target_id,target_name?,channel_id,user?}`
  → `{started, declaration?, reason?, sample_count}`（consent=optout/素材不足は started=false）。
- `POST /mimic/stop {guild_id,channel_id}` → `{stopped}`。
- `POST /mimic/optout {guild_id,target_id,user?}` → `{ok}`。
- DB 障害でも例外を投げず false を返す既存流儀に合わせる。

### moimoichan_Discordbot/
- `bot.py OracleGroup`: `mimic`（manage_guild 限定）/ `mimic off` / `mimic optout`（★一般可）。
- `on_message` の `oracle.chat(...)` に `channel_id=str(message.channel.id)` を渡す。
- `store.py` / `oracle_client.py`: `mimic_start` / `mimic_stop` / `mimic_optout` 追加。
- `_HELP` に追記（`tests/test_bot_help.py` 更新）。

### config（config.yml / config.yml.example 両方・OI-51 ドリフト注意）
```yaml
rag:
  mimic_enabled: false   # #49 既定OFF
  mimic:
    sample_limit: 300
    min_sample_count: 30   # 未満は confidence=low（極端に少なければ開始拒否）
    require_optin: false   # MVP=false（公開前は true）
```

---

## 5. プロンプト設計

### 5.1 人格カード生成（PERSONA_EXTRACT_PROMPT・LLM1回・出力 JSON のみ）
```json
{"nicknames":["..."],"personality":"...","likes":["..."],"speech_style":"...","catchphrases":["..."],"confidence":"high|medium|low"}
```
- 観察できる発言傾向のみ。**センシティブ属性（政治・宗教・健康・性的指向・人種・国籍・家庭事情等）は
  推測も記載も禁止**。誇張・揶揄・貶めない。発言が乏しければ `confidence: low` で空欄を埋めない。
- temperature 低め（≈0.2）。`extract_memory` と同じ堅牢 JSON パース。
- **保存前 denylist 検査**: 生成 JSON の各値を `SENSITIVE_DENYLIST` で走査し、該当語を含む
  項目は除去（除去後に実質空なら開始失敗扱い）。プロンプト依存にしない（Codex P1）。

### 5.2 回答時の人格ブロック（MIMIC_SECTION・`{mimic_section}` 注入）
- 「いま {display_name} さんになりきって話す（**本人ではなくモノマネ**）」を宣言し、card の
  personality/likes/speech_style/catchphrases で口調・性格を上書き。
- 優先順位を明記: 末尾「れみちゃんに忠実に」より mimic を優先。ただし
  **安全規定（攻撃的表現拒否）と RAG の「作り話しない」は維持**。
- なりすまし防止: 本人として同意・約束・個人情報開示をしない・からかわない。

### 5.3 宣言文（build_mimic_declaration・deterministic）
- LLM を追加で回さずカードから整形（コスト・失敗点削減）。
- 例: 「{display_name}さんの模倣をはじめるね。{nicknames}って呼ばれてて、性格は{personality}、
  好きなのは{likes}、話し方は{speech_style}…っぽい感じ！ `/oracle mimic off` で戻せるよ〜」
- `confidence: low` は「発言が少なくて自信ないけど〜」を前置き。

---

## 6. コスト試算（OI-16 整合）
`answer_model: deepseek/deepseek-v3.2`（input $0.23 / output $0.34 per 1M）。
- カード生成（開始時1回のみ）: 入力〜15k＋出力〜600 → 約 **$0.0037/回**。`personas` 保存で再 mimic は生成0。
- 回答時追加: `{mimic_section}` 約300〜500 tokens を system に乗せるだけ → 約 **$0.0001/回**。
- 検索/top_k/embedding 回数は増やさない＝OI-16 を崩さない。宣言文は deterministic で追加 LLM 不要。

---

## 7. 段階的実装ステップ（MVP=Phase 1）
1. DDL 2件＋index＋CRUD（consent/mimic_state 含む）＋purge 整合（personas は guild 資産）／
   conftest `_TRUNCATE` 追加。
2. prompts: `{mimic_section}`＋定数＋builder＋`SENSITIVE_DENYLIST`。
3. `src/mimic.py` MimicProvider（channel のみ・fallback なし）。
4. engine 配線・`answer(channel_id)`・`build_persona_card`（denylist 検査込み）。
5. api: 二重ガード・`ChatRequest.channel_id`・`/mimic/start|stop|optout`。
6. Bot: `/oracle mimic` / `mimic off` / `mimic optout`（一般可）・on_message channel_id・`_HELP`。
7. docs/config 更新（config.yml と example 両方）。

**Phase 2（安全強化）**: opt-in 必須化・同意ログ（#41/OI-48）連携・本人カード削除導線・
rate limit・ポータルで mimic 状態確認。

---

## 8. テスト方針（tests/ の流儀）
- **test_rag.py**（FakeLLM/FakeEmbedder/in-memory Qdrant）: 有効時 `{mimic_section}` 注入／
  disabled・0件でブロック消滅（プレースホルダ残存なし）／provider 例外でも回答継続／
  `build_persona_card` の JSON パース・崩れ/denylist 除去で None／builder ユニット。
- **test_api.py**（FakeEngine+TestClient）: `/chat` が channel_id 素通し（**FakeEngine の
  `answer` シグネチャ追従**・Codex P2）／`/mimic/start` の optout・素材不足で started=false・
  成功で宣言文／`/mimic/stop`／`/mimic/optout`。
- **test_db.py**（実Postgres）: `fetch_member_messages` の guild 絞り込み・空 content 除外・limit／
  personas/mimic_state の upsert・consent 先行作成・clear／**purge_channel で personas が残り
  mimic_state の該当 ch だけ消える**／purge_guild で両方消える。
- **test_store.py / test_bot_help.py**: Store ラッパー・`OracleGroup` に mimic 登録＋`_HELP` 反映。
- **CLI 追従**（Codex P2）: `src/cli.py` / `chat_cli.py` の payload に channel_id 互換を持たせる。
- **CI 注意**: `engine.answer()` のシグネチャ変更があるため、古い feature ブランチは
  develop へマージ前に `git merge develop`＋ローカル `pytest`（semantic conflict 回避）。

---

## 9. レビュー反映チェックリスト
- [x] channel_id 正典を `ChatRequest.channel_id` に確定（旧 user 埋め込み段階廃止）— Codex/Claude P0
- [x] purge 整合: personas=guild 資産・mimic_state=ch 単位削除を明文化 — Codex P0
- [x] consent 強制点を `/mimic/start` 入口に確定・opt-out 経路を新設 — Codex P0
- [x] センシティブ属性: 保存前 denylist 検査を追加 — Codex P1
- [x] scope=channel の guild fallback を無効化 — Codex P1
- [x] 変更波及（FakeEngine シグネチャ・cli.py payload・conftest）を明記 — Codex P2
- [ ] Aider レビュー（3者目）: 今回限り省略（人間合意）
