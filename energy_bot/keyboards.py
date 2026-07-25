"""内联键盘：仅保留发送能量的二次确认按钮。"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def clone_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ 确认克隆", callback_data="clone_confirm"),
                InlineKeyboardButton("✖️ 取消", callback_data="clone_cancel"),
            ]
        ]
    )


def confirm_kb(count: int, address: str) -> InlineKeyboardMarkup:
    """确认/取消按钮。callback_data 直接带上笔数与地址（base58 不含冒号）。"""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ 确认发送", callback_data=f"send:{count}:{address}"),
                InlineKeyboardButton("✖️ 取消", callback_data="cancel"),
            ]
        ]
    )
