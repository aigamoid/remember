"""テキストを BM25 用の sparse ベクトルに変換する。src/indexer.py / src/rag/engine.py から使用。

ハイブリッド検索（dense + 語彙一致）の語彙レーンを担う（#54）。日本語を SudachiPy で
形態素分割し、各語を**安定ハッシュ**で次元IDに、値を TF（出現回数）とする sparse ベクトルを作る。
IDF は Qdrant 側の Modifier.IDF が付与するため、ここでは掛けない（実質 TF×IDF の語彙レーン）。

安定ハッシュに zlib.crc32 を使う理由: Python 組み込みの hash() はプロセス毎にソルトされ、
インデックス時と検索時で同じ語が別IDになり一致しなくなるため使えない。

テスト容易性のため、分割関数（splitter）を注入できる。未指定なら SudachiPy を遅延ロードする
（Embedder が OpenAI クライアントを遅延ロードするのと同じ思想）。
"""

from __future__ import annotations

import zlib
from collections import Counter
from typing import Callable


class SparseEncoder:
    """テキスト → (indices, values) の sparse ベクトルに変換する callable 風クラス。"""

    # 語彙レーンのノイズになりやすい品詞は捨てる（SudachiPy 使用時のみ）。
    _DROP_POS = {"助詞", "助動詞", "補助記号", "空白", "記号", "接続詞"}

    def __init__(self, splitter: Callable[[str], list[str]] | None = None) -> None:
        # splitter: text -> 語のリスト。未指定なら SudachiPy 形態素解析を使う。
        self._splitter = splitter

    def _get_splitter(self) -> Callable[[str], list[str]]:
        if self._splitter is None:
            self._splitter = self._build_sudachi_splitter()
        return self._splitter

    def _build_sudachi_splitter(self) -> Callable[[str], list[str]]:
        from sudachipy import dictionary
        from sudachipy import tokenizer as sudachi_tokenizer

        tok = dictionary.Dictionary().create()
        mode = sudachi_tokenizer.Tokenizer.SplitMode.C  # 最も粗い＝固有名詞をまとめやすい
        drop = self._DROP_POS

        def split(text: str) -> list[str]:
            out: list[str] = []
            for m in tok.tokenize(text, mode):
                if m.part_of_speech()[0] in drop:
                    continue
                # normalized_form で表記ゆれ（送り仮名・全半角等）を吸収する。
                w = m.normalized_form().strip().lower()
                if w:
                    out.append(w)
            return out

        return split

    @staticmethod
    def _term_id(token: str) -> int:
        """語を 31bit の安定した次元IDに変換する（プロセス間で不変）。

        注: 31bit 空間へのハッシュなので、語彙が非常に大きくなると別語が同一IDに衝突して
        誤一致しうる（誕生日のパラドックス的に数万語規模から無視できない確率になる）。
        現状の guild あたりの語彙規模では実用上問題ない想定。将来コーパスが巨大化したら
        ビット幅拡張や fastembed Bm25（語彙管理つき）への差し替えを検討する（#57 Codex 指摘）。
        """
        return zlib.crc32(token.encode("utf-8")) & 0x7FFFFFFF

    def encode(self, text: str) -> tuple[list[int], list[float]]:
        """1テキストを (indices, values) に変換する。語が無ければ ([], [])。"""
        if not text or not text.strip():
            return [], []
        tokens = self._get_splitter()(text)
        if not tokens:
            return [], []
        counts = Counter(self._term_id(t) for t in tokens)
        indices = list(counts.keys())
        values = [float(v) for v in counts.values()]
        return indices, values

    def encode_many(self, texts: list[str]) -> list[tuple[list[int], list[float]]]:
        """複数テキストをまとめて変換する（indexer 用）。"""
        return [self.encode(t) for t in texts]
