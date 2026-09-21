import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import get_settings
from app.database import SessionLocal
from app.models import Device, SmsMessage
from app.telegram.notify import _escape_md

logger = logging.getLogger(__name__)


def _authorized(user_id: int | None) -> bool:
    settings = get_settings()
    if not settings.allowed_user_ids:
        return False
    return user_id is not None and user_id in settings.allowed_user_ids


async def _deny(update: Update) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "⛔ Unauthorized. Add your Telegram user ID to TELEGRAM_ALLOWED_USER_IDS."
        )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _authorized(user.id if user else None):
        await _deny(update)
        return
    await update.effective_message.reply_text(
        "👋 SMS Monitor ready.\n\n"
        "Commands:\n"
        "/latest [n] — last n SMS (default 5)\n"
        "/search <text> — search message body\n"
        "/from <sender> — filter by sender\n"
        "/devices — list linked devices\n"
        "/stats — counts\n"
        "/help — this help"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_latest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _authorized(user.id if user else None):
        await _deny(update)
        return

    limit = 5
    if context.args:
        try:
            limit = max(1, min(20, int(context.args[0])))
        except ValueError:
            pass

    async with SessionLocal() as session:
        result = await session.execute(
            select(SmsMessage)
            .order_by(SmsMessage.received_at.desc())
            .limit(limit)
        )
        rows = list(result.scalars().all())

    if not rows:
        await update.effective_message.reply_text("No SMS stored yet.")
        return

    chunks = []
    for msg in rows:
        when = msg.received_at.strftime("%Y-%m-%d %H:%M")
        chunks.append(
            f"#{msg.id} [{when}] `{msg.device_id}`\n"
            f"From: `{msg.sender}`\n"
            f"{_escape_md(msg.body[:500])}"
        )
    text = "\n\n—\n\n".join(chunks)
    try:
        await update.effective_message.reply_text(text, parse_mode="MarkdownV2")
    except Exception:
        plain = "\n\n---\n\n".join(
            f"#{m.id} [{m.received_at}] {m.device_id}\nFrom: {m.sender}\n{m.body[:500]}"
            for m in rows
        )
        await update.effective_message.reply_text(plain)


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _authorized(user.id if user else None):
        await _deny(update)
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /search <text>")
        return

    query = " ".join(context.args)
    async with SessionLocal() as session:
        result = await session.execute(
            select(SmsMessage)
            .where(SmsMessage.body.ilike(f"%{query}%"))
            .order_by(SmsMessage.received_at.desc())
            .limit(10)
        )
        rows = list(result.scalars().all())

    if not rows:
        await update.effective_message.reply_text(f"No matches for '{query}'.")
        return

    lines = [
        f"#{m.id} {m.sender}: {m.body[:120].replace(chr(10), ' ')}" for m in rows
    ]
    await update.effective_message.reply_text("\n".join(lines))


async def cmd_from(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _authorized(user.id if user else None):
        await _deny(update)
        return
    if not context.args:
        await update.effective_message.reply_text("Usage: /from <sender>")
        return

    sender = context.args[0]
    async with SessionLocal() as session:
        result = await session.execute(
            select(SmsMessage)
            .where(SmsMessage.sender == sender)
            .order_by(SmsMessage.received_at.desc())
            .limit(10)
        )
        rows = list(result.scalars().all())

    if not rows:
        await update.effective_message.reply_text(f"No SMS from {sender}.")
        return

    lines = [
        f"#{m.id} [{m.received_at.strftime('%m-%d %H:%M')}] {m.body[:140]}"
        for m in rows
    ]
    await update.effective_message.reply_text("\n".join(lines))


async def cmd_devices(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _authorized(user.id if user else None):
        await _deny(update)
        return

    async with SessionLocal() as session:
        result = await session.execute(
            select(Device).order_by(Device.last_seen_at.desc())
        )
        devices = list(result.scalars().all())

    if not devices:
        await update.effective_message.reply_text("No devices registered yet.")
        return

    now = datetime.now(timezone.utc)
    lines = []
    for d in devices:
        last = d.last_seen_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age = now - last
        mins = int(age.total_seconds() // 60)
        lines.append(f"• {d.device_id} — last seen {mins}m ago")
    await update.effective_message.reply_text("Devices:\n" + "\n".join(lines))


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _authorized(user.id if user else None):
        await _deny(update)
        return

    async with SessionLocal() as session:
        sms_count = await session.scalar(select(func.count()).select_from(SmsMessage)) or 0
        device_count = await session.scalar(select(func.count()).select_from(Device)) or 0

    await update.effective_message.reply_text(
        f"📊 Stats\nSMS stored: {sms_count}\nDevices: {device_count}"
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _authorized(user.id if user else None):
        await _deny(update)
        return
    await update.effective_message.reply_text("Use /help for commands.")


def build_application() -> Application:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("latest", cmd_latest))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("from", cmd_from))
    app.add_handler(CommandHandler("devices", cmd_devices))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app
