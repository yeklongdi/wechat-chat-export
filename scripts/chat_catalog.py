"""只用联系人和表名元数据建立会话目录，不读取消息正文。"""
from __future__ import annotations

import hashlib
import re
import sqlite3


FILEHELPER = "filehelper"


def message_table(username: str) -> str:
    return "Msg_" + hashlib.md5(username.encode("utf-8")).hexdigest()


def display_name(username: str, contacts: dict[str, dict]) -> str:
    if username == FILEHELPER:
        return "文件传输助手"
    contact = contacts.get(username, {})
    return next((contact.get(key) for key in ("remark", "nick_name", "alias") if contact.get(key)), username)


def read_contacts(con: sqlite3.Connection) -> dict[str, dict]:
    exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND lower(name)='contact'").fetchone()
    if not exists:
        raise ValueError("联系人库缺少 contact 表，需适配后再按名称选择会话")
    columns = {row[1].lower() for row in con.execute('PRAGMA table_info("contact")')}
    if "username" not in columns:
        raise ValueError("联系人表缺少 username 字段")
    fields = [name for name in ("username", "alias", "nick_name", "remark") if name in columns]
    contacts = {}
    for raw in con.execute("SELECT " + ",".join('"' + name + '"' for name in fields) + ' FROM "contact"'):
        contact = {name: str(value or "").strip() for name, value in zip(fields, raw)}
        username = contact.pop("username")
        if username:
            contacts[username] = contact
    return contacts


def message_tables(con: sqlite3.Connection) -> set[str]:
    return {row[0].lower() for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if re.fullmatch(r"Msg_[0-9a-f]{32}", row[0], re.IGNORECASE)}


def shard_usernames(con: sqlite3.Connection) -> set[str]:
    exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND lower(name)='name2id'").fetchone()
    if not exists:
        return set()
    return {str(row[0]) for row in con.execute('SELECT user_name FROM Name2Id') if row[0]}


def build_catalog(contacts: dict[str, dict], usernames: set[str], tables: set[str]) -> list[dict]:
    catalog = []
    for username in sorted(set(contacts) | usernames | {FILEHELPER}):
        if message_table(username).lower() not in tables:
            continue
        catalog.append({
            "name": display_name(username, contacts), "username": username,
            "type": "group" if username.endswith("@chatroom") else "private",
            "aliases": [value for value in contacts.get(username, {}).values() if value],
        })
    return sorted(catalog, key=lambda chat: (chat["name"].casefold(), chat["username"]))


def public_chat(chat: dict) -> dict:
    return {key: chat[key] for key in ("name", "username", "type")}


def search_chats(catalog: list[dict], keyword: str) -> list[dict]:
    query = keyword.casefold().strip()
    return [chat for chat in catalog if any(query in value.casefold()
            for value in [chat["username"], chat["name"], *chat["aliases"]])]


class ChatSelectionError(ValueError):
    def __init__(self, selector: str, candidates: list[dict]):
        reason = "匹配到多个会话" if len(candidates) > 1 else "名称未完全匹配，请从候选中选择" if candidates else "未找到名称完全一致且在本机有消息表的会话"
        super().__init__(f"{reason}：{selector}；请使用 --list-chats 搜索，再用 --chat 传入准确会话 ID")
        self.selector = selector
        self.candidates = [public_chat(chat) for chat in candidates]


def resolve_chats(catalog: list[dict], selectors: list[str]) -> list[dict]:
    selected = {}
    for selector in selectors:
        # 精确 ID 优先；备注或昵称重名时不能静默选中其中一个。
        matches = [chat for chat in catalog if chat["username"] == selector]
        if not matches:
            query = selector.casefold().strip()
            matches = [chat for chat in catalog if query and query in
                       {value.casefold() for value in [chat["name"], *chat["aliases"]]}]
        if len(matches) != 1:
            raise ChatSelectionError(selector, matches or search_chats(catalog, selector))
        selected[matches[0]["username"]] = matches[0]
    return list(selected.values())
