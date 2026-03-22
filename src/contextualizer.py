"""Contextual Retrieval: 各チャンクにLLM生成の文脈説明を付与する（Phase 2.5）。"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone

from src.db import fetch_chunks_for_context, update_chunk_context
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
    conn: sqlite3.Connection,
    anchor_msg_id: str,
    channel_id: str,
    n: int = 10,
    tz_offset: int = 9,
) -> tuple[str, str]:
    """anchor_msg_id より前の同チャンネルメッセージ N 件をテキスト化して返す。

    戻り値: (preceding_text, anchor_timestamp_jst)
    """
    anchor_row = conn.execute(
        "SELECT timestamp FROM messages WHERE id = ?",
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
        WHERE channel_id = ?
          AND (timestamp < ? OR (timestamp = ? AND id < ?))
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
        """,
        (channel_id, anchor_ts, anchor_ts, anchor_msg_id, n),
    ).fetchall()

    tz = timezone(timedelta(hours=tz_offset))
    anchor_dt = datetime.fromisoformat(anchor_ts).astimezone(tz)
    anchor_timestamp_jst = anchor_dt.strftime("%Y-%m-%d %H:%M")

    if not rows:
        return ("（直前の会話なし）", anchor_timestamp_jst)

    lines = [
        format_message_line(author, content, ts, bool(has_att), tz_offset)
        for author, content, ts, has_att in reversed(rows)
    ]
    return ("\n".join(lines), anchor_timestamp_jst)


def generate_context(
    channel_name: str,
    anchor_timestamp: str,
    preceding_text: str,
    chunk_text: str,
    client,
    model: str,
) -> str:
    """OpenAI API を呼び出して context_text を生成する。"""
    prompt = _SYSTEM_PROMPT.format(
        channel_name=channel_name,
        anchor_timestamp=anchor_timestamp,
        preceding_messages=preceding_text,
        chunk_text=chunk_text,
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.0,
    )
    return response.choices[0].message.content.strip()


def run_contextualizer(conn: sqlite3.Connection, cfg: dict) -> int:
    """context_text が NULL の全チャンクに文脈説明を付与する。生成件数を返す。"""
    import openai

    ctx_cfg = cfg.get("contextualizer", {})
    model: str = ctx_cfg.get("model", "gpt-4.1-nano")
    preceding_n: int = ctx_cfg.get("preceding_messages", 10)
    max_retries: int = ctx_cfg.get("max_retries", 3)
    retry_delay: float = float(ctx_cfg.get("retry_delay", 1.0))
    tz_offset: int = cfg.get("chunk", {}).get("timezone_offset", 9)

    openai_cfg = cfg.get("openai", {})
    api_key: str | None = openai_cfg.get("api_key") or None
    client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()

    chunks = fetch_chunks_for_context(conn)
    total = len(chunks)
    print(f"  context_text が NULL のチャンク: {total:,} 件")

    done = 0
    commit_interval = 50

    for chunk_id, anchor_msg_id, channel_id, chunk_text in chunks:
        channel_name_row = conn.execute(
            "SELECT channel_name FROM messages WHERE channel_id = ? LIMIT 1",
            (channel_id,),
        ).fetchone()
        channel_name = channel_name_row[0] if channel_name_row else channel_id

        preceding_text, anchor_timestamp = _get_preceding_messages(
            conn, anchor_msg_id, channel_id, preceding_n, tz_offset
        )

        context_text: str | None = None
        for attempt in range(1, max_retries + 1):
            try:
                context_text = generate_context(
                    channel_name=channel_name,
                    anchor_timestamp=anchor_timestamp,
                    preceding_text=preceding_text,
                    chunk_text=chunk_text,
                    client=client,
                    model=model,
                )
                break
            except openai.AuthenticationError as e:
                # 認証エラーは全件失敗するため即座に停止
                raise RuntimeError(f"OpenAI 認証エラー（APIキーを確認してください）: {e}") from e
            except openai.NotFoundError as e:
                # モデル不存在も即座に停止
                raise RuntimeError(f"モデルが見つかりません（model 設定を確認してください）: {e}") from e
            except Exception as e:
                if attempt == max_retries:
                    error_msg = f"[attempt {attempt}] {type(e).__name__}: {e}"
                    conn.execute(
                        "UPDATE chunk_index SET error_message = ? WHERE chunk_id = ?",
                        (error_msg, chunk_id),
                    )
                    print(f"  ERROR chunk_id={chunk_id}: {error_msg}")
                    break
                time.sleep(retry_delay)

        if context_text is not None:
            update_chunk_context(conn, chunk_id, context_text)
            done += 1

        if done % commit_interval == 0 and done > 0:
            conn.commit()
            print(f"  {done:,} / {total:,} 件処理済み")

    conn.commit()
    print(f"  完了: {done:,} 件に context_text を付与")
    return done
