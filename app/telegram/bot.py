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
from app.firebase_sync import firebase_attach_device, firebase_detach
from app.models import Device, SmsMessage, UserAttachment
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


async def _get_attached_device_id(session, telegram_user_id: int) -> str | None:
    result = await session.execute(
        select(UserAttachment).where(
            UserAttachment.telegram_user_id == telegram_user_id
        )
    )
    row = result.scalar_one_or_none()
    return row.device_id if row else None


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _authorized(user.id if user else None):
        await _deny(update)
        return
    await update.effective_message.reply_text(
        "👋 SMS Monitor ready.\n\n"
        "Commands:\n"
        "/a <device_id> — attach ONE device (Firebase sync if configured)\n"
        "/a — show currently attached device\n"
        "/a off — detach\n"
        "/latest [n] — last n SMS (attached device only)\n"
        "/search <text> — search (attached device only)\n"
        "/from <sender> — filter by sender\n"
        "/devices — list all devices in DB\n"
        "/adddevice <id> [label] — add device to DB\n"
        "/stats — counts\n"
        "/help — this help"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_a(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Attach a single device: /a <device_id> — not the full device list."""
    user = update.effective_user
    if not _authorized(user.id if user else None):
        await _deny(update)
        return
    assert user is not None

    # /a  or  /a off
    if not context.args:
        async with SessionLocal() as session:
            attached = await _get_attached_device_id(session, user.id)
            if not attached:
                await update.effective_message.reply_text(
                    "No device attached.\n"
                    "Usage: /a <device_id>\n"
                    "Example: /a my-pixel"
                )
                return
            result = await session.execute(
                select(Device).where(Device.device_id == attached)
            )
            device = result.scalar_one_or_none()
            sms_count = await session.scalar(
                select(func.count())
                .select_from(SmsMessage)
                .where(SmsMessage.device_id == attached)
            ) or 0
        label = device.label if device else attached
        fb = "yes" if get_settings().firebase_enabled else "no"
        await update.effective_message.reply_text(
            f"📎 Attached device (only this one):\n"
            f"• id: {attached}\n"
            f"• label: {label}\n"
            f"• sms_count: {sms_count}\n"
            f"• firebase: {fb}\n\n"
            f"/a off — detach\n"
            f"/latest — SMS for this device only"
        )
        return

    arg0 = context.args[0].strip()
    if arg0.lower() in {"off", "detach", "none", "clear"}:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserAttachment).where(
                    UserAttachment.telegram_user_id == user.id
                )
            )
            row = result.scalar_one_or_none()
            if row:
                await session.delete(row)
                await session.commit()
        try:
            await firebase_detach()
        except Exception:
            pass
        await update.effective_message.reply_text("🔌 Detached. No device selected.")
        return

    device_id = arg0
    label = " ".join(context.args[1:]).strip() or device_id
    now = datetime.now(timezone.utc)

    async with SessionLocal() as session:
        # Ensure device exists in DB
        result = await session.execute(
            select(Device).where(Device.device_id == device_id)
        )
        device = result.scalar_one_or_none()
        if device is None:
            device = Device(device_id=device_id, label=label, last_seen_at=now)
            session.add(device)
        else:
            if label != device_id:
                device.label = label
            device.last_seen_at = now

        # Attach only this device for the user (replace previous)
        att = await session.execute(
            select(UserAttachment).where(
                UserAttachment.telegram_user_id == user.id
            )
        )
        attachment = att.scalar_one_or_none()
        if attachment is None:
            attachment = UserAttachment(
                telegram_user_id=user.id,
                device_id=device_id,
                attached_at=now,
            )
            session.add(attachment)
        else:
            attachment.device_id = device_id
            attachment.attached_at = now

        await session.commit()
        await session.refresh(device)

        sms_count = await session.scalar(
            select(func.count())
            .select_from(SmsMessage)
            .where(SmsMessage.device_id == device_id)
        ) or 0

        recent = await session.execute(
            select(SmsMessage)
            .where(SmsMessage.device_id == device_id)
            .order_by(SmsMessage.received_at.desc())
            .limit(3)
        )
        recent_rows = list(recent.scalars().all())

    fb_ok = False
    fb_err = ""
    if get_settings().firebase_enabled:
        try:
            await firebase_attach_device(
                device_id,
                label=device.label,
                telegram_user_id=user.id,
            )
            fb_ok = True
        except Exception as exc:
            fb_err = str(exc)[:120]

    lines = [
        f"✅ Attached ONLY this device (not all):",
        f"• id: {device_id}",
        f"• label: {device.label}",
        f"• sms_in_db: {sms_count}",
    ]
    if get_settings().firebase_enabled:
        lines.append(f"• firebase: {'attached OK' if fb_ok else f'failed ({fb_err})'}")
    else:
        lines.append("• firebase: not configured (set FIREBASE_RTDB_URL in .env)")

    if recent_rows:
        lines.append("\nLast SMS for this device:")
        for m in recent_rows:
            when = m.received_at.strftime("%m-%d %H:%M")
            lines.append(f"  [{when}] {m.sender}: {m.body[:80]}")
    else:
        lines.append("\nNo SMS yet for this device.")

    lines.append("\n/latest — sirf is device ke SMS")
    await update.effective_message.reply_text("\n".join(lines))


async def cmd_latest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _authorized(user.id if user else None):
        await _deny(update)
        return
    assert user is not None

    limit = 5
    if context.args:
        try:
            limit = max(1, min(20, int(context.args[0])))
        except ValueError:
            pass

    async with SessionLocal() as session:
        attached = await _get_attached_device_id(session, user.id)
        stmt = select(SmsMessage)
        if attached:
            stmt = stmt.where(SmsMessage.device_id == attached)
        result = await session.execute(
            stmt.order_by(SmsMessage.received_at.desc()).limit(limit)
        )
        rows = list(result.scalars().all())

    if not rows:
        if attached:
            await update.effective_message.reply_text(
                f"No SMS for attached device `{attached}` yet."
            )
        else:
            await update.effective_message.reply_text(
                "No SMS stored yet.\nPehle /a <device_id> se device attach karo."
            )
        return

    header = f"Device filter: `{attached}`\n\n" if attached else ""
    chunks = []
    for msg in rows:
        when = msg.received_at.strftime("%Y-%m-%d %H:%M")
        chunks.append(
            f"#{msg.id} [{when}] `{msg.device_id}`\n"
            f"From: `{msg.sender}`\n"
            f"{_escape_md(msg.body[:500])}"
        )
    text = header + "\n\n—\n\n".join(chunks)
    try:
        await update.effective_message.reply_text(text, parse_mode="MarkdownV2")
    except Exception:
        plain_header = f"Device filter: {attached}\n\n" if attached else ""
        plain = plain_header + "\n\n---\n\n".join(
            f"#{m.id} [{m.received_at}] {m.device_id}\nFrom: {m.sender}\n{m.body[:500]}"
            for m in rows
        )
        await update.effective_message.reply_text(plain)


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _authorized(user.id if user else None):
        await _deny(update)
        return
    assert user is not None
    if not context.args:
        await update.effective_message.reply_text("Usage: /search <text>")
        return

    query = " ".join(context.args)
    async with SessionLocal() as session:
        attached = await _get_attached_device_id(session, user.id)
        stmt = select(SmsMessage).where(SmsMessage.body.ilike(f"%{query}%"))
        if attached:
            stmt = stmt.where(SmsMessage.device_id == attached)
        result = await session.execute(
            stmt.order_by(SmsMessage.received_at.desc()).limit(10)
        )
        rows = list(result.scalars().all())

    if not rows:
        scope = f" on `{attached}`" if attached else ""
        await update.effective_message.reply_text(f"No matches for '{query}'{scope}.")
        return

    lines = [
        f"#{m.id} [{m.device_id}] {m.sender}: {m.body[:120].replace(chr(10), ' ')}"
        for m in rows
    ]
    await update.effective_message.reply_text("\n".join(lines))


async def cmd_from(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _authorized(user.id if user else None):
        await _deny(update)
        return
    assert user is not None
    if not context.args:
        await update.effective_message.reply_text("Usage: /from <sender>")
        return

    sender = context.args[0]
    async with SessionLocal() as session:
        attached = await _get_attached_device_id(session, user.id)
        stmt = select(SmsMessage).where(SmsMessage.sender == sender)
        if attached:
            stmt = stmt.where(SmsMessage.device_id == attached)
        result = await session.execute(
            stmt.order_by(SmsMessage.received_at.desc()).limit(10)
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
    assert user is not None

    async with SessionLocal() as session:
        attached = await _get_attached_device_id(session, user.id)
        result = await session.execute(
            select(Device).order_by(Device.last_seen_at.desc())
        )
        devices = list(result.scalars().all())

    if not devices:
        await update.effective_message.reply_text(
            "No devices in DB yet.\n"
            "Add: /adddevice my-phone\n"
            "Or attach: /a my-phone"
        )
        return

    now = datetime.now(timezone.utc)
    lines = ["All devices in DB (use /a <id> to attach ONE):"]
    for d in devices:
        last = d.last_seen_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        mins = int((now - last).total_seconds() // 60)
        mark = " 👈 attached" if attached and d.device_id == attached else ""
        label = d.label or d.device_id
        lines.append(f"• {d.device_id} ({label}) — {mins}m ago{mark}")
    await update.effective_message.reply_text("\n".join(lines))


async def cmd_adddevice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _authorized(user.id if user else None):
        await _deny(update)
        return
    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /adddevice <device_id> [label]\n"
            "Example: /adddevice my-pixel Papa Phone\n\n"
            "Sirf ek device dekhna/attach karna ho to: /a my-pixel"
        )
        return

    device_id = context.args[0].strip()
    label = " ".join(context.args[1:]).strip() or device_id

    async with SessionLocal() as session:
        result = await session.execute(
            select(Device).where(Device.device_id == device_id)
        )
        device = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if device is None:
            device = Device(device_id=device_id, label=label, last_seen_at=now)
            session.add(device)
            created = True
        else:
            device.label = label
            device.last_seen_at = now
            created = False
        await session.commit()

    action = "added" if created else "updated"
    await update.effective_message.reply_text(
        f"✅ Device {action}: {device_id} ({label})\n"
        f"Attach karo: /a {device_id}"
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _authorized(user.id if user else None):
        await _deny(update)
        return
    assert user is not None

    async with SessionLocal() as session:
        attached = await _get_attached_device_id(session, user.id)
        sms_count = await session.scalar(select(func.count()).select_from(SmsMessage)) or 0
        device_count = await session.scalar(select(func.count()).select_from(Device)) or 0
        attached_sms = 0
        if attached:
            attached_sms = await session.scalar(
                select(func.count())
                .select_from(SmsMessage)
                .where(SmsMessage.device_id == attached)
            ) or 0

    text = f"📊 Stats\nSMS stored: {sms_count}\nDevices: {device_count}"
    if attached:
        text += f"\nAttached: {attached} ({attached_sms} SMS)"
    else:
        text += "\nAttached: none — use /a <device_id>"
    await update.effective_message.reply_text(text)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _authorized(user.id if user else None):
        await _deny(update)
        return
    await update.effective_message.reply_text("Use /help for commands. Attach: /a <device_id>")


def build_application() -> Application:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("a", cmd_a))
    app.add_handler(CommandHandler("latest", cmd_latest))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("from", cmd_from))
    app.add_handler(CommandHandler("devices", cmd_devices))
    app.add_handler(CommandHandler("adddevice", cmd_adddevice))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app
