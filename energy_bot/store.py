"""被授权用户名单的持久化存储。

授权可按用户 ID 或用户名（@username）任一方式记录：
- 按 ID 授权后，该用户无论是否改用户名都有效；
- 按用户名授权后，该用户发消息时凭 username 命中（适用于还不知道对方 ID 的场景）。
数据落盘到 JSON 文件，进程重启后仍然有效。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class AuthStore:
    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._ids: set[int] = set()
        self._usernames: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._ids = {int(x) for x in data.get("ids", [])}
            self._usernames = {str(u).lower() for u in data.get("usernames", [])}
        except Exception:  # noqa: BLE001
            logger.exception("读取授权名单失败：%s", self._path)

    def _save(self) -> None:
        payload = {"ids": sorted(self._ids), "usernames": sorted(self._usernames)}
        # 原子写：先写临时文件再替换，避免崩溃/断电时把名单写坏。
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def import_legacy(self, legacy_path: str | Path) -> int:
        """一次性把旧的全局授权文件合并进来，合并后将其改名归档。返回新增条数。"""
        legacy_path = Path(legacy_path)
        if not legacy_path.exists() or legacy_path.resolve() == self._path.resolve():
            return 0
        try:
            data = json.loads(legacy_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.exception("读取旧授权文件失败：%s", legacy_path)
            return 0
        before = len(self._ids) + len(self._usernames)
        self._ids |= {int(x) for x in data.get("ids", [])}
        self._usernames |= {str(u).lower() for u in data.get("usernames", [])}
        added = len(self._ids) + len(self._usernames) - before
        self._save()
        try:
            legacy_path.rename(legacy_path.with_suffix(legacy_path.suffix + ".migrated"))
        except OSError:
            logger.warning("旧授权文件归档失败：%s", legacy_path)
        if added:
            logger.info("已从 %s 迁移 %d 条授权", legacy_path.name, added)
        return added

    @staticmethod
    def _norm(username: str) -> str:
        return username.lstrip("@").lower()

    def is_authorized(self, user_id: int | None, username: str | None) -> bool:
        if user_id is not None and user_id in self._ids:
            return True
        if username and self._norm(username) in self._usernames:
            return True
        return False

    def add(self, user_id: int | None = None, username: str | None = None) -> None:
        if user_id is not None:
            self._ids.add(int(user_id))
        if username:
            self._usernames.add(self._norm(username))
        self._save()

    def remove(self, user_id: int | None = None, username: str | None = None) -> bool:
        removed = False
        if user_id is not None and int(user_id) in self._ids:
            self._ids.discard(int(user_id))
            removed = True
        if username:
            u = self._norm(username)
            if u in self._usernames:
                self._usernames.discard(u)
                removed = True
        if removed:
            self._save()
        return removed

    def snapshot(self) -> tuple[list[int], list[str]]:
        return sorted(self._ids), sorted(self._usernames)
