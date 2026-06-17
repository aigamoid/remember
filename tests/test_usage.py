"""src/usage.py のコスト算出テスト（純関数・DB不要）"""

from __future__ import annotations

from src.usage import compute_cost

PRICING = {
    "m1": {"input": 1.0, "output": 2.0},
    "emb": {"input": 0.02, "output": 0.0},
}


class TestComputeCost:
    def test_known_model_input_and_output(self):
        # (1,000,000*1.0 + 1,000,000*2.0) / 1e6 = 3.0
        assert compute_cost(PRICING, "m1", 1_000_000, 1_000_000) == 3.0

    def test_embedding_only_input(self):
        # (1,000,000*0.02 + 0) / 1e6 = 0.02
        assert compute_cost(PRICING, "emb", 1_000_000, 0) == 0.02

    def test_unknown_model_is_zero(self):
        assert compute_cost(PRICING, "unknown", 1000, 1000) == 0.0

    def test_none_model_is_zero(self):
        assert compute_cost(PRICING, None, 1000, 1000) == 0.0

    def test_missing_output_price_treated_as_zero(self):
        assert compute_cost({"m": {"input": 1.0}}, "m", 1_000_000, 9999) == 1.0

    def test_empty_pricing_is_zero(self):
        assert compute_cost({}, "m1", 100, 100) == 0.0
