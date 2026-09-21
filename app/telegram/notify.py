import logging

from app.config import get_settings
from app.models import SmsMessage

logger = logging.getLogger(__name__)


def format_sms(msg: SmsMessage) -> str:
    when = msg.received_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    return (
        f"📩 *New SMS*\n"
        f"Device: `{msg.device_id}`\n"
        f"From: `{msg.sender}`\n"
        f"Time: `{when}`\n\n"
        f"{_escape_md(msg.body)}"
    )


def _escape_md(text: str) -> str:
    specials = "_*[]()~`>#+-=|{}.!"
    out = []
    for ch in text:
        if ch in specials:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


async def notify_new_sms(msg: SmsMessage) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.allowed_user_ids:
        return

    try:
        from telegram import Bot
        from telegram.constants import ParseMode
    except ImportError:
        logger.warning("python-telegram-bot not installed; skip push")
        return

    bot = Bot(token=settings.telegram_bot_token)
    text = format_sms(msg)
    for user_id in settings.allowed_user_ids:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            # Fallback without markdown if escaping fails
            try:
                plain = (
                    f"New SMS\n"
                    f"Device: {msg.device_id}\n"
                    f"From: {msg.sender}\n"
                    f"Time: {msg.received_at}\n\n"
                    f"{msg.body}"
                )
                await bot.send_message(chat_id=user_id, text=plain)
            except Exception as exc:
                logger.exception("Failed to notify user %s: %s", user_id, exc)
