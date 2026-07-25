"""多机器人托管：主 bot + N 个克隆 bot 跑在同一进程内。

每个 bot 都是独立的 Telegram 机器人（独立 token），拥有各自的：
- trxfee API（api_key / api_secret）—— 各自扣费
- 充值地址（接口识别不到，需自定义）
- 管理员 ID（该 bot 的「作者」）

主 bot 额外拥有「克隆 / 克隆列表 / 删除克隆」管理能力（仅主作者）。
克隆配置持久化到 clones.json，进程重启后自动重新拉起。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from . import handlers
from .store import AuthStore
from .trxfee import TrxFeeClient

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent

_CALLBACK_PATTERN = r"^(send:|cancel$|clone_confirm$|clone_cancel$)"


def build_app(
    *,
    token: str,
    api_key: str,
    api_secret: str,
    base_url: str,
    recharge_addr: str,
    admin_id: int,
    is_main: bool,
    manager: "CloneManager | None" = None,
) -> Application:
    """按一套机器人配置组装一个 Application（主/克隆通用）。"""
    app = Application.builder().token(token).build()
    bot_id = token.split(":", 1)[0]
    auth_store = AuthStore(DATA_DIR / f"authorized_{bot_id}.json")
    if is_main:
        # 旧版用单一全局 authorized.json，拆成按-bot 文件后做一次性迁移。
        auth_store.import_legacy(DATA_DIR / "authorized.json")
    app.bot_data.update(
        {
            "author_id": int(admin_id),
            "recharge_addr": recharge_addr,
            "base_url": base_url,
            "client": TrxFeeClient(api_key, api_secret, base_url),
            "auth_store": auth_store,
            "is_main": is_main,
            "manager": manager,
        }
    )
    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CallbackQueryHandler(handlers.on_callback, pattern=_CALLBACK_PATTERN))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text))
    return app


class CloneManager:
    def __init__(self, clones_path: str | Path, base_url: str):
        self._path = Path(clones_path)
        self._base_url = base_url
        self._configs: dict[str, dict[str, Any]] = {}
        self._apps: dict[str, Application] = {}
        self._load()

    # ---- 持久化 ----
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            rows = json.loads(self._path.read_text(encoding="utf-8"))
            for cfg in rows:
                self._configs[str(cfg["token"]).split(":", 1)[0]] = cfg
        except Exception:  # noqa: BLE001
            logger.exception("读取克隆配置失败：%s", self._path)

    def _save(self) -> None:
        self._path.write_text(
            json.dumps(list(self._configs.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---- 查询 ----
    def list(self) -> list[dict[str, Any]]:
        return list(self._configs.values())

    def resolve(self, key: str) -> str | None:
        """按 bot_id 或 @username 找到对应 bot_id。"""
        key = key.lstrip("@").lower()
        if key in self._configs:
            return key
        for bot_id, cfg in self._configs.items():
            if str(cfg.get("username", "")).lower() == key:
                return bot_id
        return None

    # ---- 生命周期 ----
    async def _start_app(self, cfg: dict[str, Any]) -> Application:
        app = build_app(
            token=cfg["token"],
            api_key=cfg["api_key"],
            api_secret=cfg["api_secret"],
            base_url=self._base_url,
            recharge_addr=cfg["recharge_addr"],
            admin_id=int(cfg["admin_id"]),
            is_main=False,
            manager=self,
        )
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=["message", "callback_query"])
        self._apps[str(cfg["token"]).split(":", 1)[0]] = app
        logger.info("克隆 bot 已启动：@%s (admin=%s)", cfg.get("username"), cfg.get("admin_id"))
        return app

    async def start_all(self) -> None:
        for cfg in list(self._configs.values()):
            try:
                await self._start_app(cfg)
            except Exception:  # noqa: BLE001
                logger.exception("克隆 bot 启动失败：%s", cfg.get("username"))

    async def stop_all(self) -> None:
        for bot_id, app in list(self._apps.items()):
            await self._stop_app(app)
            self._apps.pop(bot_id, None)

    @staticmethod
    async def _stop_app(app: Application) -> None:
        try:
            if app.updater and app.updater.running:
                await app.updater.stop()
            if app.running:
                await app.stop()
            await app.shutdown()
        except Exception:  # noqa: BLE001
            logger.exception("停止克隆 bot 出错")

    async def add_clone(self, cfg: dict[str, Any]) -> dict[str, Any]:
        bot_id = str(cfg["token"]).split(":", 1)[0]
        if bot_id in self._configs:
            raise ValueError("该机器人已存在（token 重复）")
        self._configs[bot_id] = cfg
        self._save()
        await self._start_app(cfg)
        return cfg

    async def remove_clone(self, key: str) -> dict[str, Any] | None:
        bot_id = self.resolve(key)
        if not bot_id:
            return None
        cfg = self._configs.pop(bot_id, None)
        self._save()
        app = self._apps.pop(bot_id, None)
        if app:
            await self._stop_app(app)
        return cfg
