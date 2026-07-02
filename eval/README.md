# 検索A/B評価用 golden セット（#54）

`scripts/eval_retrieval.py` で **dense（改修前）と hybrid（改修後・#54）の検索精度を比較**するための
「正解つき質問リスト（golden セット）」を置く場所。A/B の採点基準になる。

## なぜ「意味系 + 固有名詞」を混ぜるか

- **固有名詞系**: 人名・ID・製品名など**完全一致**が効く質問。語彙レーン（BM25 sparse）の効果が出る
  → hybrid が dense の取りこぼしを救えるかを見る。
- **意味系**: 言い換え・ふわっとした質問。**dense（意味検索）が活きる**側面
  → hybrid（RRF融合）が dense の強みを**壊していない**か（悪化しないか）を見る。
- **時系列系**: 「最初に話したのは」「最近の」など時間が絡む質問。

固有名詞で「勝つ」＋意味で「負けない」の両方を確認できて、はじめて本番ON（`rag.hybrid.enabled: true`）の
判断ができる。known-item 自動評価（コーパス内語をクエリ化）は固有名詞に有利な偏りがあるため、
本番判定にはこの手作り golden を使う。

## フォーマット

```json
[
  {
    "category": "固有名詞",          // 集計の区分（固有名詞 / 意味 / 時系列 など任意）
    "question": "moltbookって停止されてた？",  // 実際に投げる質問
    "expect_any": ["Offense", "停止"], // 取得チャンクにこのどれかが含まれれば正解
    "note": "任意メモ"
  }
]
```

- `expect_any` は**正解チャンクに必ず出てくる目印の語**を入れる（チャンク本文 chunk_text / context_text を対象に部分一致で判定）。
- `category` を付けるとカテゴリ別ヒット率が出る（未指定は「（未分類）」に集約）。

## 実行

```sh
# Qdrant 稼働 + 対象 guild が hybrid 移行（sparse付与）済みであること
python scripts/eval_retrieval.py <guild_id> eval/golden.example.json
```

dense / hybrid のカテゴリ別 recall@k と latency p95 が出力される。

## 運用メモ

- `golden.example.json` は**ローカル dev guild の内容に紐づくサンプル**（そのまま動く）。
- **本番「わいわい」で評価する際は、実サーバーの実際の話題に基づいて作り直す**こと
  （`golden_waiwai.json` 等を別途用意）。質問は実在の話題から、`expect_any` は実在の語から取る。
- 一度作れば 案B（recency #55）・案C のA/Bや、プロンプト/モデル変更時の回帰チェックにも再利用できる。

## 案B（recency 時間減衰 #55）のA/B

案A（ハイブリッド）マージ後の**積み上げ評価**。`scripts/eval_recency.py` で
**hybrid（ベースライン）と hybrid+recency** を比較する（dense 比較は eval_retrieval.py の役割）。

```sh
# 既定の半減期で採点
python scripts/eval_recency.py <guild_id> eval/golden_recency.example.json
# 半減期を変えてチューニング（例: 7日）
python scripts/eval_recency.py <guild_id> eval/golden_recency.example.json 7
```

- golden は **時系列(最近)系**（「最近」「直近」など）と **話題(不変)系** を混ぜる
  （`golden_recency.example.json` 参照）。
- 見る指標: 時系列系で **top_k の平均age（日）が下がる**（新しめの話が上位に来る）／
  話題系で **ヒット率が baseline を下回らない**／latency 増が許容内。
- recency は検索の並べ替えだけを変える（再インデックス不要）。**本番ONは config.yml の
  `rag.recency.enabled: true`**。半減期は実データで要チューニング。
