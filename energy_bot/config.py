"""运行配置：从环境变量 / .env 读取，启动前做必要校验。"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    author_id: int
    api_key: str
    api_secret: str
    base_url: str
    recharge_addr: str


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少必填环境变量 {name}，请参考 .env.example 配置 .env")
    return value


def load_config() -> Config:
    return Config(
        bot_token=_require("BOT_TOKEN"),
        author_id=int(_require("AUTHOR_ID")),
        api_key=_require("TRXFEE_API_KEY"),
        api_secret=_require("TRXFEE_API_SECRET"),
        base_url=os.getenv("TRXFEE_BASE_URL", "https://trxfee.io/v1").strip().rstrip("/"),
        recharge_addr=os.getenv("RECHARGE_ADDR", "").strip(),
    )
