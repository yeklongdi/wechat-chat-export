"""合成好友、群聊和分片，验证直接导出及歧义选择的实际边界。"""
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

import chat_catalog as catalog
import export_wechat as target


OWNER = "wxid_owner_account"
FRIEND = "wxid_friend"
GROUP = "12345@chatroom"
OTHER = "wxid_other"


def make_shard(names, messages):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE Name2Id(user_name TEXT)")
    con.executemany("INSERT INTO Name2Id VALUES(?)", [(name,) for name in names])
    for username, rows in messages.items():
        table = catalog.message_table(username)
        con.execute(f'CREATE TABLE "{table}"(local_id INTEGER,server_id INTEGER,create_time INTEGER,local_type INTEGER,real_sender_id INTEGER,message_content BLOB)')
        for local_id, server_id, when, sender, content in rows:
            con.execute(f'INSERT INTO "{table}" VALUES(?,?,?,?,?,?)',
                        (local_id, server_id, when, 1, names.index(sender) + 1, content))
    return con


def test_catalog_reads_only_names_and_table_metadata():
    contacts = {
        FRIEND: {"remark": "朋友备注", "nick_name": "朋友昵称", "alias": "friend-alias"},
        GROUP: {"nick_name": "项目讨论群"},
        "wxid_without_messages": {"remark": "没有记录的联系人"},
    }
    con = make_shard([OWNER, FRIEND, GROUP], {
        FRIEND: [(1, 1, 150, FRIEND, "禁止在检索会话时读取")], GROUP: [],
    })

    def metadata_only(action, table, column, *_unused):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_READ and column == "message_content" else sqlite3.SQLITE_OK

    con.set_authorizer(metadata_only)
    try:
        chats = catalog.build_catalog(contacts, catalog.shard_usernames(con), catalog.message_tables(con))
        assert {chat["username"] for chat in chats} == {FRIEND, GROUP}
        assert catalog.resolve_chats(chats, ["朋友备注"])[0]["username"] == FRIEND
        assert catalog.resolve_chats(chats, ["朋友昵称", "friend-alias"])[0]["username"] == FRIEND
        assert catalog.resolve_chats(chats, ["项目讨论群"])[0]["type"] == "group"
        assert len(catalog.search_chats(chats, "讨论")) == 1
        with pytest.raises(sqlite3.DatabaseError):
            target.selected_rows(con, 100, 200, FRIEND)
    finally:
        con.close()


def test_duplicate_names_require_id_and_partial_names_only_suggest():
    contacts = {FRIEND: {"remark": "小张"}, OTHER: {"remark": "小张"}}
    chats = catalog.build_catalog(contacts, set(), {catalog.message_table(name).lower() for name in contacts})
    with pytest.raises(catalog.ChatSelectionError) as failure:
        catalog.resolve_chats(chats, ["小张"])
    assert {chat["username"] for chat in failure.value.candidates} == {FRIEND, OTHER}
    assert catalog.resolve_chats(chats, [FRIEND])[0]["username"] == FRIEND
    with pytest.raises(catalog.ChatSelectionError):
        catalog.resolve_chats(chats, ["小"])


def test_table_lookup_is_parameterized_for_user_input():
    con = make_shard([OWNER, FRIEND], {FRIEND: [(1, 1, 100, FRIEND, "应保留的记录")]})
    try:
        assert target.selected_rows(con, 0, 200, '"; DROP TABLE Name2Id; --') == []
        assert target.selected_rows(con, 0, 200, FRIEND)[0]["message_content"] == "应保留的记录"
    finally:
        con.close()


@pytest.fixture
def account(tmp_path, monkeypatch):
    storage = tmp_path / "xwechat_files" / (OWNER + "_abcd") / "db_storage"
    databases = {}
    contact_con = sqlite3.connect(":memory:")
    contact_con.execute("CREATE TABLE contact(username TEXT,alias TEXT,nick_name TEXT,remark TEXT)")
    contact_con.executemany("INSERT INTO contact VALUES(?,?,?,?)", [
        (OWNER, "", "本人昵称", ""), (FRIEND, "friend-alias", "好友昵称", "朋友备注"),
        (GROUP, "", "项目讨论群", ""), (OTHER, "", "其他朋友", ""),
    ])
    databases["contact/contact.db"] = contact_con.serialize()
    contact_con.close()
    shards = [
        make_shard([OWNER, FRIEND, GROUP, OTHER], {
            GROUP: [(1, 11, 100, OWNER, "群内本人第一行\n第二行"),
                    (2, 12, 199, FRIEND, "群内好友的完整正文"),
                    (3, 13, 200, FRIEND, "结束边界以外")],
            FRIEND: [(1, 11, 125, FRIEND, "好友私聊内容")],
            OTHER: [(1, 14, 150, OTHER, "未选择会话的私密内容")],
        }),
        # 第二分片的 rowid=1 是好友；不能沿用第一分片 rowid=1 的本人身份。
        make_shard([FRIEND, GROUP, OWNER, OTHER], {
            GROUP: [(8, 12, 199, FRIEND, "群内好友的完整正文"),
                    (9, 15, 160, OWNER, "另一分片的本人发言")],
        }),
    ]
    for index, con in enumerate(shards):
        databases[f"message/message_{index}.db"] = con.serialize()
        con.close()

    encrypted, plaintext, keys = {}, {}, {}
    for index, (relative, plain) in enumerate(databases.items(), 1):
        path = storage / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = bytes([index]) * 16 + bytes(target.PAGE - 16)
        path.write_bytes(data)
        encrypted[str(path)] = data
        plaintext[data[:16].hex()] = plain
        keys[data[:16].hex()] = bytes([index]) * 32

    scan_result = {salt: key.hex() for salt, key in keys.items()}
    tool = SimpleNamespace(auto_detect_db_dir=lambda: str(storage))

    def scan(directory, _unused):
        entries, salts = tool.collect_db_files(directory)
        assert len(entries) == len(salts) == 3
        assert tool._save_results() is None
        return scan_result

    tool._scan_memory_raw_key = scan
    monkeypatch.setattr(target, "load_key_tool", lambda: tool)
    monkeypatch.setattr(target, "read_snapshot", lambda path: encrypted[path])

    def decrypt(data, key):
        salt = data[:16].hex()
        assert key == keys[salt]
        return plaintext[salt]

    monkeypatch.setattr(target, "decrypt_snapshot", decrypt)
    return SimpleNamespace(storage=storage, output=tmp_path / "results", keys=scan_result)


@pytest.mark.skipif(sys.platform != "win32", reason="完整实时入口针对 Windows")
def test_direct_group_and_friend_export_with_independent_sender_maps(account):
    result = target.export(100, 200, account.output, chats=["项目讨论群", "朋友备注"])
    assert result["status"] == "complete" and result["chat_count"] == 2
    assert result["messages"] == 4
    group, friend = [json.loads(Path(item["json_file"]).read_text(encoding="utf-8")) for item in result["exports"]]
    assert [entry["sender"] for entry in group["messages"]] == ["我", "我", "朋友备注"]
    assert [entry["content"] for entry in group["messages"]] == ["群内本人第一行\n第二行", "另一分片的本人发言", "群内好友的完整正文"]
    assert group["metadata"]["chat_username"] == GROUP
    assert group["metadata"]["chat_type"] == "group"
    assert friend["messages"][0]["content"] == "好友私聊内容"
    assert friend["messages"][0]["sender_username"] == FRIEND
    assert "未选择会话的私密内容" not in json.dumps([group, friend], ensure_ascii=False)
    assert "结束边界以外" not in json.dumps([group, friend], ensure_ascii=False)
    assert not account.keys
    assert len(list(account.output.rglob("*.txt"))) == 2
    assert not list(account.output.rglob("*.db"))
    assert "会话：项目讨论群" in Path(result["exports"][0]["text_file"]).read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="完整实时入口针对 Windows")
def test_list_and_unknown_selection_do_not_read_bodies_or_write_files(account, monkeypatch):
    def forbidden(*_args):
        pytest.fail("只检索会话时不应查询消息正文")

    monkeypatch.setattr(target, "selected_rows", forbidden)
    result = target.export(100, 200, account.output, list_only=True, search="讨论")
    assert result["chats"] == [{"name": "项目讨论群", "username": GROUP, "type": "group"}]
    assert result["message_bodies_read"] is False
    assert result["files_written"] is False
    assert not account.output.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="完整实时入口针对 Windows")
def test_ambiguous_selection_stops_before_body_query_or_output(account, monkeypatch):
    original = target.read_contacts

    def duplicate_names(con):
        contacts = original(con)
        contacts[OTHER]["remark"] = "朋友备注"
        return contacts

    monkeypatch.setattr(target, "read_contacts", duplicate_names)
    monkeypatch.setattr(target, "selected_rows", lambda *_args: pytest.fail("歧义未解决前不能查询正文"))
    with pytest.raises(catalog.ChatSelectionError) as failure:
        target.export(100, 200, account.output, chats=["朋友备注"])
    assert len(failure.value.candidates) == 2
    assert not account.output.exists()
    assert not account.keys


@pytest.mark.skipif(sys.platform != "win32", reason="完整实时入口针对 Windows")
def test_missing_contact_material_fails_without_output(account):
    account.keys.pop((bytes([1]) * 16).hex())
    with pytest.raises(RuntimeError, match="contact.db 缺少"):
        target.export(100, 200, account.output, chats=[FRIEND])
    assert not account.output.exists()
    assert not account.keys


def test_duplicate_server_ids_are_scoped_to_conversation():
    base = {"timestamp": 100, "local_id": 1, "source_database": "message_0.db", "server_id": "7"}
    messages = [{**base, "chat_username": FRIEND}, {**base, "chat_username": GROUP},
                {**base, "chat_username": GROUP, "source_database": "message_1.db"}]
    assert len(target.deduplicate_messages(messages)) == 2


def test_direct_cli_and_all_history():
    args, since, until = target.parse_args(["--chat", "项目讨论群", "--chat", "朋友备注", "--all-history"])
    assert args.chat == ["项目讨论群", "朋友备注"] and since == 0 and until > since
    args, _, _ = target.parse_args(["--list-chats", "讨论"])
    assert args.list_chats == "讨论"
    args, _, _ = target.parse_args(["--list-chats"])
    assert args.list_chats == ""


@pytest.mark.parametrize("arguments", [
    ["--chat", " "], ["--chat", "朋友备注", "--list-chats"],
    ["--all-history", "--minutes", "60"], ["--list-chats", "--minutes", "15"],
    ["--all-history", "--end", "2026-01-15T10:00:00"],
])
def test_conflicting_direct_parameters_fail_before_reading(arguments):
    with pytest.raises(SystemExit) as failure:
        target.parse_args(arguments)
    assert failure.value.code == 2
