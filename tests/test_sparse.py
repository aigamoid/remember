"""src/sparse.py のテスト。SudachiPy を入れずに済むよう splitter を注入する。"""

from __future__ import annotations

from src.sparse import SparseEncoder


def _ws_encoder() -> SparseEncoder:
    """空白区切りの簡易 splitter を注入した SparseEncoder（テスト用）。"""
    return SparseEncoder(splitter=lambda t: t.split())


class TestEncode:
    def test_empty_text_returns_empty(self):
        enc = _ws_encoder()
        assert enc.encode("") == ([], [])
        assert enc.encode("   ") == ([], [])

    def test_distinct_terms_get_distinct_ids(self):
        enc = _ws_encoder()
        indices, values = enc.encode("かにじる ケーキ")
        assert len(indices) == 2
        assert len(set(indices)) == 2  # 別語は別ID
        assert all(v == 1.0 for v in values)

    def test_term_frequency_counted(self):
        enc = _ws_encoder()
        indices, values = enc.encode("ケーキ ケーキ プリン")
        # ケーキ=2回, プリン=1回 → 2次元
        assert len(indices) == 2
        idx_to_val = dict(zip(indices, values))
        assert sorted(idx_to_val.values()) == [1.0, 2.0]

    def test_same_token_same_id_stable(self):
        # 別インスタンスでも同語は同ID（プロセス非依存の安定ハッシュ）
        e1, e2 = _ws_encoder(), _ws_encoder()
        (i1, _), (i2, _) = e1.encode("かにじる"), e2.encode("かにじる")
        assert i1 == i2

    def test_term_id_is_stable_known_value(self):
        # zlib.crc32 ベースなので値が固定される（回帰防止）
        import zlib

        expected = zlib.crc32("かにじる".encode("utf-8")) & 0x7FFFFFFF
        assert SparseEncoder._term_id("かにじる") == expected


class TestEncodeMany:
    def test_encode_many_matches_encode(self):
        enc = _ws_encoder()
        texts = ["ケーキ", "", "プリン プリン"]
        out = enc.encode_many(texts)
        assert out[0] == enc.encode("ケーキ")
        assert out[1] == ([], [])
        assert out[2] == enc.encode("プリン プリン")
