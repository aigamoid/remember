"""Contextual Retrieval: 各チャンクにLLM生成の文脈説明を付与する（Phase 2.5）。"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import psycopg

from src.db import fetch_chunks_for_context, fetch_mention_map, update_chunk_context
from src.formatter import format_message_line

_SYSTEM_PROMPT = """\
あなたはDiscordサーバーのチャットログを分析しています。
以下の「対象チャンク」が検索で見つかりやすくなるよう、
このチャンクの話題・文脈を1〜2文（100文字以内）で簡潔に説明してください。

チャンネル名: {channel_name}
対象チャンクの開始時刻: {anchor_timestamp}

[直前の会話（時系列順・同チャンネル内）]:
{preceding_messages}

[対象チャンク]:
{chunk_text}

注意:
- 推測・補完は禁止。直前の会話から確認できる情報のみ使うこと
- 情報が不足している場合は「不明」と記載してよい
- 説明文のみ出力（ラベル・引用符・注釈不要）"""


def _get_preceding_messages(
    conn: psycopg.Connection,
    anchor_msg_id: str,
    channel_id: str,
    n: int = 10,
    tz_offset: int = 9,
    mention_map: dict[str, str] | None = None,
) -> tuple[str, str]:
    """anchor_msg_id より前の同チャンネルメッセージ N 件をテキスト化して返す。

    戻り値: (preceding_text, anchor_timestamp_jst)
    """
    anchor_row = conn.execute(
        "SELECT timestamp FROM messages WHERE id = %s",
        (anchor_msg_id,),
    ).fetchone()
    if anchor_row is None:
        return ("（直前の会話なし）", "不明")

    anchor_ts = anchor_row[0]

    # (timestamp, id) で tie-break: 同秒のメッセージを正確に除外
    rows = conn.execute(
        """
        SELECT author_name, content, timestamp, has_attachment
        FROM messages
        WHERE channel_id = %s
          AND (timestamp < %s OR (timestamp = %s AND id < %s))
        ORDER BY timestamp DESC, id DESC
        LIMIT %s
        """,
        (channel_id, anchor_ts, anchor_ts, anchor_msg_id, n),
    ).fetchall()

    tz = timezone(timedelta(hours=tz_offset))
    anchor_dt = datetime.fromisoformat(anchor_ts).astimezone(tz)
    anchor_timestamp_jst = anchor_dt.strftime("%Y-%m-%d %H:%M")

    if not rows:
        return ("（直前の会話なし）", anchor_timestamp_jst)

    lines = [
        format_message_line(author, content, ts, bool(has_att), tz_offset, mention_map)
        for author, content, ts, has_att in reversed(rows)
    ]
    return ("\n".join(lines), anchor_timestamp_jst)


async def generate_context(
    channel_name: str,
    anchor_timestamp: str,
    preceding_text: str,
    chunk_text: str,
    client,
    model: str,
) -> str:
    """OpenAI 互換 API を呼び出して context_text を生成する。"""
    prompt = _SYSTEM_PROMPT.format(
        channel_name=channel_name,
        anchor_timestamp=anchor_timestamp,
        preceding_messages=preceding_text,
        chunk_text=chunk_text,
    )
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.0,
    )
    return response.choices[0].message.content.strip()


async def _run_async(
    conn: psycopg.Connection, cfg: dict, guild_id: str | None = None
) -> int:
    """非同期で全チャンクを並列処理する。生成件数を返す。"""
    import openai

    ctx_cfg = cfg.get("contextualizer", {})
    model: str = ctx_cfg.get("model", "gpt-4.1-nano")
    preceding_n: int = ctx_cfg.get("preceding_messages", 10)
    max_retries: int = ctx_cfg.get("max_retries", 3)
    retry_delay: float = float(ctx_cfg.get("retry_delay", 1.0))
    concurrency: int = ctx_cfg.get("concurrency", 10)
    tz_offset: int = cfg.get("chunk", {}).get("timezone_offset", 9)

    openai_cfg = cfg.get("openai", {})
    base_url: str | None = openai_cfg.get("base_url") or None
    # base_url がOpenRouter等の場合、OPENAI_API_KEY への暗黙フォールバックを防ぐ
    api_key: str | None = (
        openai_cfg.get("api_key")
        or (os.environ.get("OPENROUTER_API_KEY") if base_url else None)
        or None
    )
    client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)

    chunks = fetch_chunks_for_context(conn, guild_id)
    total = len(chunks)
    print(f"  context_text が NULL のチャンク: {total:,} 件")

    if total == 0:
        return 0

    # channel_id → channel_name の事前キャッシュ（ループ内 N 回クエリを削減）
    channel_names: dict[str, str] = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT DISTINCT channel_id, channel_name FROM messages"
        ).fetchall()
    }

    # <@ID> → 表示名 の対応表（preceding_messages の解決用・OI-18）
    mention_map = fetch_mention_map(conn, guild_id)

    semaphore = asyncio.Semaphore(concurrency)
    abort_event = asyncio.Event()
    fatal_errors: list[RuntimeError] = []
    completed = 0

    async def process_chunk(
        chunk_id: str,
        anchor_msg_id: str,
        channel_id: str,
        chunk_text: str,
    ) -> bool | None:
        """処理結果: True=成功 / False=エラー記録済み / None=abort でスキップ"""
        nonlocal completed

        if abort_event.is_set():
            return None

        async with semaphore:
            if abort_event.is_set():
                return None

            channel_name = channel_names.get(channel_id, channel_id)
            preceding_text, anchor_timestamp = _get_preceding_messages(
                conn, anchor_msg_id, channel_id, preceding_n, tz_offset, mention_map
            )

            for attempt in range(1, max_retries + 1):
                try:
                    ctx = await generate_context(
                        channel_name=channel_name,
                        anchor_timestamp=anchor_timestamp,
                        preceding_text=preceding_text,
                        chunk_text=chunk_text,
                        client=client,
                        model=model,
                    )
                    update_chunk_context(conn, chunk_id, ctx)
                    completed += 1
                    if completed % 100 == 0:
                        print(f"  {completed:,} / {total:,} 件処理済み")
                    return True
                except openai.AuthenticationError as e:
                    abort_event.set()
                    fatal_errors.append(
                        RuntimeError(f"OpenAI 認証エラー（APIキーを確認してください）: {e}")
                    )
                    return None
                except openai.NotFoundError as e:
                    abort_event.set()
                    fatal_errors.append(
                        RuntimeError(f"モデルが見つかりません（model 設定を確認してください）: {e}")
                    )
                    return None
                except Exception as e:
                    if attempt == max_retries:
                        error_msg = f"[attempt {attempt}] {type(e).__name__}: {e}"
                        conn.execute(
                            "UPDATE chunk_index SET error_message = %s WHERE chunk_id = %s",
                            (error_msg, chunk_id),
                        )
                        print(f"  ERROR chunk_id={chunk_id[:8]}…: {error_msg}")
                        return False
                    await asyncio.sleep(retry_delay)

            return False  # ここには通常到達しない

    tasks = [
        process_chunk(chunk_id, anchor_msg_id, channel_id, chunk_text)
        for chunk_id, anchor_msg_id, channel_id, chunk_text in chunks
    ]

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        conn.commit()  # 成功・エラー記録ともに確実に保存

    # process_chunk から漏れた予期しない例外（将来の変更含む）を raise
    for r in results:
        if isinstance(r, Exception):
            raise r

    if fatal_errors:
        raise fatal_errors[0]

    done = sum(1 for r in results if r is True)
    errs = sum(1 for r in results if r is False)
    skipped = sum(1 for r in results if r is None)
    print(f"  完了: {done:,} 件 / エラー: {errs:,} 件 / スキップ: {skipped:,} 件")
    return done


def run_contextualizer(
    conn: psycopg.Connection, cfg: dict, guild_id: str | None = None
) -> int:
    """context_text が NULL のチャンクに文脈説明を付与する（同期ラッパー）。生成件数を返す。

    guild_id を指定すると、そのサーバーのチャンクだけを処理する（ワーカーが使用）。
    """
    return asyncio.run(_run_async(conn, cfg, guild_id))
