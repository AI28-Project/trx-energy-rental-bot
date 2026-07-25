"""应用装配与启动。

主 bot 由 .env 配置；克隆 bot 由 clones.json 配置，二者跑在同一进程内。
访问控制：每个 bot 的「作者」=其管理员 ID，作者可运行时授权其他用户（名单按
bot 持久化）。主 bot 作者额外可「克隆 / 删除克隆」。非授权用户一律静默。
"""

from __future__ import annotations

import asyncio
import logging
import signal

from telegram.ext import Application

from .config import load_config
from .manager import DATA_DIR, CloneManager, build_app

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def build_main_app() -> tuple[Application, CloneManager]:
    config = load_config()
    manager = CloneManager(DATA_DIR / "clones.json", config.base_url)
    main_app = build_app(
        token=config.bot_token,
        api_key=config.api_key,
        api_secret=config.api_secret,
        base_url=config.base_url,
        recharge_addr=config.recharge_addr,
        admin_id=config.author_id,
        is_main=True,
        manager=manager,
    )
    logger.info("主 bot 已装配，作者 ID=%s", config.author_id)
    return main_app, manager


async def _run(main_app: Application, manager: CloneManager) -> None:
    await main_app.initialize()
    await main_app.start()
    await main_app.updater.start_polling(allowed_updates=["message", "callback_query"])
    await manager.start_all()
    logger.info("启动完成：主 bot + %d 个克隆 bot，开始轮询 …", len(manager.list()))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass

    await stop.wait()
    logger.info("收到停止信号，正在关闭 …")
    await manager.stop_all()
    if main_app.updater and main_app.updater.running:
        await main_app.updater.stop()
    if main_app.running:
        await main_app.stop()
    await main_app.shutdown()


def main() -> None:
    main_app, manager = build_main_app()
    asyncio.run(_run(main_app, manager))


if __name__ == "__main__":
    main()
