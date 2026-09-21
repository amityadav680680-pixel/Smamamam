import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import router as api_router
from app.config import get_settings
from app.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path("data").mkdir(parents=True, exist_ok=True)
    await init_db()
    logger.info("Database ready")

    settings = get_settings()
    if settings.telegram_bot_token and settings.allowed_user_ids:
        from app.telegram.bot import build_application

        tg_app = build_application()
        await tg_app.initialize()
        await tg_app.start()
        if tg_app.updater:
            await tg_app.updater.start_polling(drop_pending_updates=True)
        app.state.tg_app = tg_app
        logger.info("Telegram bot polling started")
    else:
        logger.warning(
            "Telegram bot not started "
            "(set TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_IDS)"
        )
        app.state.tg_app = None

    yield

    tg_app = getattr(app.state, "tg_app", None)
    if tg_app is not None:
        if tg_app.updater:
            await tg_app.updater.stop()
        await tg_app.stop()
        await tg_app.shutdown()
        logger.info("Telegram bot stopped")


def create_app() -> FastAPI:
    application = FastAPI(
        title="Remote SMS Monitor",
        description=(
            "Personal SMS monitor: Android forwarder posts to webhook; "
            "view and search via Telegram. Use only on devices you own "
            "and are authorized to monitor."
        ),
        version=__version__,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router)
    return application


app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
