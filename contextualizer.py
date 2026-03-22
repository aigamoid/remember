#!/usr/bin/env python3
"""
contextualizer.py - 各チャンクに LLM 生成の文脈説明を付与する（Phase 2.5）

実行方法:
    python contextualizer.py              # context_text が NULL のチャンクのみ処理
    python contextualizer.py --clean      # context_text + error_message を NULL 化して全件再処理
    python contextualizer.py --dry-run    # API コールなし・処理対象件数と推定コストを表示
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.config import load_config
from src.contextualizer import run_contextualizer
from src.db import fetch_chunks_for_context, init_db, log_run


def _do_clean(conn) -> None:
    cur = conn.execute(
        "UPDATE chunk_index SET context_text = NULL, error_message = NULL"
    )
    conn.commit()
    print(f"  --clean: {cur.rowcount:,} 件をリセットしました")


def _do_dry_run(conn, cfg: dict) -> None:
    chunks = fetch_chunks_for_context(conn)
    count = len(chunks)
    if count == 0:
        print("  処理対象: 0 件（全チャンクに context_text 付与済み）")
        return

    # 推定コスト計算（gpt-4.1-nano: input $0.10/M・output $0.40/M）
    # 注意: 日本語の場合 1 token ≈ 1〜2 文字程度（英語より多くなる）→ 実際は 1.5〜2x 高くなる場合あり
    avg_chunk_chars = sum(len(c[3]) for c in chunks) / count
    preceding_chars_est = 300  # 直前10件の想定文字数
    prompt_template_chars = 400
    input_chars_per_call = avg_chunk_chars + preceding_chars_est + prompt_template_chars
    output_chars_per_call = 150  # context_text 最大100文字+余裕

    chars_per_token = 2.0  # 日本語混在を考慮した保守的な推定
    input_tokens_total = count * input_chars_per_call / chars_per_token
    output_tokens_total = count * output_chars_per_call / chars_per_token

    model = cfg.get("contextualizer", {}).get("model", "gpt-4.1-nano")
    input_cost = input_tokens_total / 1_000_000 * 0.10
    output_cost = output_tokens_total / 1_000_000 * 0.40
    total_cost = input_cost + output_cost

    print(f"  処理対象: {count:,} 件")
    print(f"  モデル: {model}")
    print(f"  推定入力トークン: {input_tokens_total:,.0f}")
    print(f"  推定出力トークン: {output_tokens_total:,.0f}")
    print(f"  推定コスト: ${total_cost:.2f}（Batch API 利用で約半額）")


def main() -> None:
    parser = argparse.ArgumentParser(description="Contextual Retrieval 実行")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--clean", action="store_true", help="context_text を全リセットして再処理")
    mode.add_argument("--dry-run", action="store_true", help="処理対象件数と推定コストを表示して終了")
    args = parser.parse_args()

    load_dotenv()
    cfg = load_config()

    db_path = Path("data/messages.db")
    conn = init_db(db_path)
    print(f"DB: {db_path}")

    if args.clean:
        _do_clean(conn)

    if args.dry_run:
        _do_dry_run(conn, cfg)
        conn.close()
        return

    import uuid
    run_id = str(uuid.uuid4())

    try:
        done = run_contextualizer(conn, cfg)
        log_run(conn, run_id, "contextualize", "success", f"完了: {done:,} 件")
        conn.commit()
        print(f"\n完了: {done:,} チャンクに context_text を付与しました")
    except Exception as e:
        log_run(conn, run_id, "contextualize", "error", str(e))
        conn.commit()
        print(f"\nエラーが発生しました: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
