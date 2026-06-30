"""Stripe 課金連携（OI-14 D）。

usage/trace と同じ流儀: コアはこのモジュールに集約し、キー未設定なら enabled()=False で
グレースフルに無効化する。Stripe SDK 呼び出しは StripeError を捕捉し、課金の失敗が
回答機能（/chat）へ波及しないようにする。

担当:
- create_checkout_session: /oracle upgrade の Checkout URL を発行（重複サブスク防止つき）
- create_portal_session: /oracle billing の Customer Portal URL を発行
- handle_event: Stripe Webhook を署名検証し guild_plans を自動更新

設計の要点（MAGI レビューで確定）:
- **source of truth は Stripe の subscription オブジェクト**。Webhook ペイロードの metadata を
  鵜呑みにせず、subscription の price_id から plan を確定する（誤昇格・metadata 改ざん対策）。
- **冪等性・順不同**は src/db.update_guild_subscription の period_end/status ガードで吸収。
- **ACK 方針**: 署名不正は WebhookSignatureError(→API 400)、一時障害（DB・Stripe取得・guild未着地）は
  WebhookRetryableError(→API 5xx で Stripe 再送)、設定ミス（未知 price 等）は正常終了(→200)。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from src import db

try:  # stripe は本番(api)コンテナのみ。未インストールでも import は通す。
    import stripe
except ImportError:  # pragma: no cover - 実環境では requirements で入る
    stripe = None  # type: ignore

logger = logging.getLogger(__name__)


# ---- 例外（API 層が HTTP ステータスへ写像する）----

class BillingError(Exception):
    """課金処理の一般エラー（Checkout/Portal 生成失敗など）。"""


class BillingDisabledError(BillingError):
    """Stripe キー未設定で課金機能が無効。"""


class AlreadySubscribedError(BillingError):
    """既に有効なサブスクがあるため Checkout を発行しない（Portal へ誘導）。"""


class UnknownPlanError(BillingError):
    """plan_key が存在しない／stripe_price_id 未設定。"""


class WebhookSignatureError(BillingError):
    """Webhook 署名検証に失敗（→ 400）。"""


class WebhookRetryableError(BillingError):
    """一時障害で処理できず、Stripe に再送させたい（→ 5xx）。"""


# ---- 設定 ----

def _secret_key() -> str | None:
    return os.environ.get("STRIPE_SECRET_KEY")


def _webhook_secret() -> str | None:
    return os.environ.get("STRIPE_WEBHOOK_SECRET")


def enabled() -> bool:
    """Stripe SDK が入っていてシークレットキーが設定済みなら True。"""
    return stripe is not None and bool(_secret_key())


def _ensure_enabled() -> None:
    if not enabled():
        raise BillingDisabledError("Stripe is not configured")
    stripe.api_key = _secret_key()


def _ts_to_iso(ts: int | None) -> str | None:
    """Stripe の Unix 秒を ISO8601(UTC) 文字列へ（current_period_end は TEXT 列）。"""
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


def _map_status(stripe_status: str) -> str:
    """Stripe の subscription.status を内部 status(active|past_due|canceled) へ写像。"""
    if stripe_status in ("active", "trialing"):
        return "active"
    if stripe_status in ("canceled", "incomplete_expired"):
        return "canceled"
    # past_due / unpaid / incomplete / paused など未払い・未確定はまとめて past_due 扱い。
    return "past_due"


# ---- Checkout / Portal ----

def create_checkout_session(
    conn,
    guild_id: str,
    plan_key: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """サブスク申込の Stripe Checkout Session を作り、その URL を返す。

    重複サブスク防止: 既に active/trialing/past_due の subscription を持つ guild は
    AlreadySubscribedError（Bot/API が Portal へ誘導）。同時押下は Idempotency-Key で吸収。
    """
    _ensure_enabled()
    plan = db.get_plan_def(conn, plan_key)
    if plan is None or not plan.get("stripe_price_id"):
        raise UnknownPlanError(f"plan {plan_key} has no stripe_price_id")

    billing = db.get_guild_billing(conn, guild_id)
    if (
        billing
        and billing.get("stripe_subscription_id")
        and billing.get("status") in ("active", "past_due")
    ):
        raise AlreadySubscribedError(
            "guild already has an active subscription; use the customer portal"
        )

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": plan["stripe_price_id"], "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=str(guild_id),
            metadata={"guild_id": str(guild_id), "plan_key": plan_key},
            # subscription 自体にも guild_id を載せる（subscription.* イベントの
            # guild 逆引きが checkout 着地前でも効くようにする fallback）。
            subscription_data={"metadata": {"guild_id": str(guild_id),
                                            "plan_key": plan_key}},
            # 二連打・同時押下を Stripe 側で吸収（同一セッションを返す。約24h有効）。
            idempotency_key=f"upgrade:{guild_id}:{plan_key}",
        )
    except stripe.error.StripeError as e:  # type: ignore[union-attr]
        logger.warning("stripe checkout create failed: %s", e)
        raise BillingError("failed to create checkout session") from e
    return session.url


def create_portal_session(stripe_customer_id: str, return_url: str) -> str:
    """解約・カード変更用の Stripe Customer Portal Session URL を返す。"""
    _ensure_enabled()
    if not stripe_customer_id:
        raise BillingError("no stripe_customer_id for this guild")
    try:
        session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=return_url,
        )
    except stripe.error.StripeError as e:  # type: ignore[union-attr]
        logger.warning("stripe portal create failed: %s", e)
        raise BillingError("failed to create portal session") from e
    return session.url


# ---- Webhook ----

def _retrieve_subscription(subscription_id: str):
    """Stripe から subscription を取得（取得失敗は再送させたいので Retryable）。"""
    try:
        return stripe.Subscription.retrieve(subscription_id)
    except stripe.error.StripeError as e:  # type: ignore[union-attr]
        logger.warning("stripe subscription retrieve failed: %s", e)
        raise WebhookRetryableError("subscription retrieve failed") from e


def _sub_price_id(sub) -> str | None:
    try:
        return sub["items"]["data"][0]["price"]["id"]
    except (KeyError, IndexError, TypeError):
        return None


def _sub_period_end(sub) -> int | None:
    """subscription の current_period_end(Unix秒) を取り出す。

    Stripe は 2025 の API バージョンで top-level の current_period_end を
    subscription items 配下へ移したため、両方を見て取れた方を使う。
    """
    top = sub.get("current_period_end")
    if top:
        return top
    try:
        return sub["items"]["data"][0].get("current_period_end")
    except (KeyError, IndexError, TypeError):
        return None


def _apply_subscription(conn, guild_id: str, sub) -> dict:
    """subscription オブジェクトを source of truth として guild_plans を更新する。

    price_id → plan を確定（未知 price なら plan を変えずログのみ＝設定ミスは再送で直らない）。
    """
    price_id = _sub_price_id(sub)
    plan = db.get_plan_by_price_id(conn, price_id) if price_id else None
    status = _map_status(sub.get("status", ""))
    period_end = _ts_to_iso(_sub_period_end(sub))
    customer_id = sub.get("customer")
    sub_id = sub.get("id")

    if plan is None:
        logger.warning(
            "unknown stripe price_id=%s for guild=%s; plan not changed",
            price_id, guild_id,
        )
        return {"handled": True, "reason": "unknown_price"}

    updated = db.update_guild_subscription(
        conn,
        guild_id,
        plan_key=plan["plan_key"],
        status=status,
        stripe_customer_id=customer_id,
        stripe_subscription_id=sub_id,
        current_period_end=period_end,
    )
    return {"handled": True, "updated": updated, "plan_key": plan["plan_key"]}


def _guild_id_for_subscription(conn, sub) -> str | None:
    """subscription イベントから guild を特定（逆引き→metadata fallback）。"""
    sub_id = sub.get("id")
    existing = db.get_guild_by_subscription(conn, sub_id) if sub_id else None
    if existing:
        return existing["guild_id"]
    meta = sub.get("metadata") or {}
    return meta.get("guild_id")


def handle_event(conn, payload: bytes, sig_header: str) -> dict:
    """Stripe Webhook を署名検証し、guild_plans を自動更新する。

    例外で API のステータスを制御する（ACK 方針）:
      - WebhookSignatureError → 400（署名不正・改ざん）
      - WebhookRetryableError → 5xx（一時障害・guild 未着地。Stripe が再送）
      - 正常／設定ミス → dict を返す（200）
    """
    _ensure_enabled()
    secret = _webhook_secret()
    if not secret:
        raise BillingDisabledError("STRIPE_WEBHOOK_SECRET not set")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except stripe.error.SignatureVerificationError as e:  # type: ignore[union-attr]
        raise WebhookSignatureError("invalid signature") from e
    except ValueError as e:  # 不正な payload
        raise WebhookSignatureError("invalid payload") from e

    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        guild_id = (obj.get("metadata") or {}).get("guild_id") \
            or obj.get("client_reference_id")
        sub_id = obj.get("subscription")
        if not guild_id or not sub_id:
            logger.warning("checkout.session.completed missing guild_id/subscription")
            return {"handled": True, "reason": "missing_ids"}
        # 完了時も active を直決めせず、subscription を取得して実 status を反映。
        sub = _retrieve_subscription(sub_id)
        return _apply_subscription(conn, guild_id, sub)

    if etype == "customer.subscription.updated":
        guild_id = _guild_id_for_subscription(conn, obj)
        if not guild_id:
            # checkout 着地前の先着など。再送で後から解決させる。
            raise WebhookRetryableError("guild not yet linked to subscription")
        return _apply_subscription(conn, guild_id, obj)

    if etype == "customer.subscription.deleted":
        guild_id = _guild_id_for_subscription(conn, obj)
        if not guild_id:
            logger.info("subscription.deleted for unknown subscription; ignoring")
            return {"handled": True, "reason": "unknown_subscription"}
        db.update_guild_subscription(
            conn, guild_id, plan_key="free", status="canceled",
            current_period_end=_ts_to_iso(_sub_period_end(obj)),
        )
        return {"handled": True, "plan_key": "free"}

    if etype == "invoice.payment_failed":
        sub_id = obj.get("subscription")
        existing = db.get_guild_by_subscription(conn, sub_id) if sub_id else None
        if existing:
            # plan_key は維持（MVP は回答継続）。status のみ past_due に。
            db.update_guild_subscription(
                conn, existing["guild_id"], plan_key=existing["plan_key"],
                status="past_due",
            )
        return {"handled": True, "reason": "payment_failed"}

    return {"handled": False, "type": etype}
