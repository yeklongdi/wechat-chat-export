"""仅用合成页和合成消息验证认证、会话范围、时间边界和正文保真。"""
import hashlib
import hmac
import json
import sqlite3
import struct
import xml.etree.ElementTree as ET

from Crypto.Cipher import AES
import pytest

import export_wechat as target


def encrypted_fixture():
    key = bytes(range(32))
    salt = bytes(range(16))
    mac_key = hashlib.pbkdf2_hmac("sha512", key, bytes(value ^ 0x3A for value in salt), 2, 32)
    pages = []
    expected = bytearray(2 * target.PAGE)
    expected[:16] = b"SQLite format 3\x00"
    for number in (1, 2):
        start = 16 if number == 1 else 0
        plain = bytearray([number] * (target.PAGE - target.RESERVE - start))
        if number == 1:
            plain[:8] = b"\x10\x00\x02\x02\x50\x40\x20\x20"
        iv = bytes([number + 5]) * 16
        encrypted = AES.new(key, AES.MODE_CBC, iv).encrypt(bytes(plain))
        prefix = salt if number == 1 else b""
        without_mac = prefix + encrypted + iv
        mac = hmac.new(mac_key, without_mac[start:] + struct.pack("<I", number), hashlib.sha512).digest()
        pages.append(without_mac + mac)
        offset = (number - 1) * target.PAGE
        expected[offset + start:offset + target.PAGE - target.RESERVE] = plain
    expected[18:20] = b"\x01\x01"
    return b"".join(pages), key, bytes(expected)


def test_authenticate_every_page():
    encrypted, key, expected = encrypted_fixture()
    assert target.decrypt_snapshot(encrypted, key) == expected
    corrupt = bytearray(encrypted)
    corrupt[target.PAGE + 100] ^= 1
    with pytest.raises(ValueError, match="第 2 页认证失败"):
        target.decrypt_snapshot(bytes(corrupt), key)
    with pytest.raises(ValueError, match="认证失败"):
        target.decrypt_snapshot(encrypted, b"x" * 32)


def message_database():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE Name2Id(user_name TEXT)")
    con.execute("INSERT INTO Name2Id VALUES('wxid_test')")
    for table in (target.TARGET_TABLE, "Msg_" + "f" * 32):
        con.execute(f'CREATE TABLE "{table}"(local_id INTEGER,server_id INTEGER,create_time INTEGER,local_type INTEGER,real_sender_id INTEGER,message_content BLOB)')
    for index, timestamp in enumerate((99, 100, 199, 200), 1):
        con.execute(f'INSERT INTO "{target.TARGET_TABLE}" VALUES(?,?,?,?,?,?)', (index, index, timestamp, 1, 1, "完整第一行\n完整第二行"))
    con.execute('INSERT INTO "Msg_ffffffffffffffffffffffffffffffff" VALUES(9,9,150,1,1,"不在授权会话中的正文")')
    return con


def test_target_and_half_open_time_window():
    con = message_database()
    try:
        selected = target.selected_rows(con, 100, 200)
    finally:
        con.close()
    assert [row["create_time"] for row in selected] == [100, 199]
    rendered = [target.format_message(row, "wxid_test", "synthetic.db") for row in selected]
    assert all(row["sender"] == "我" for row in rendered)
    assert all(row["content"] == "完整第一行\n完整第二行" for row in rendered)
    assert "不在授权会话中的正文" not in json.dumps(rendered, ensure_ascii=False)


def test_millisecond_timestamps():
    con = message_database()
    con.execute(f'DELETE FROM "{target.TARGET_TABLE}"')
    base = 1_790_000_000
    for index, timestamp in enumerate((base * 1000, (base + 59) * 1000, (base + 60) * 1000), 1):
        con.execute(f'INSERT INTO "{target.TARGET_TABLE}" VALUES(?,?,?,?,?,?)', (index, index, timestamp, 1, 1, "毫秒时间戳"))
    try:
        selected = target.selected_rows(con, base, base + 60)
    finally:
        con.close()
    assert [row["create_time"] for row in selected] == [base, base + 59]


def test_utf8_roundtrip_and_empty_report(tmp_path):
    folder = tmp_path / "导出"
    meta = {"range_start_inclusive": "2026-10-22T16:00:00+08:00", "range_end_exclusive": "2026-10-22T17:00:00+08:00"}
    txt, structured = target.write_exports(folder, meta, [])
    assert json.loads(structured.read_text(encoding="utf-8"))["messages"] == []
    assert "未找到" in txt.read_text(encoding="utf-8")


def forwarded_payload(declared="2"):
    record = (
        f'<recordinfo><datalist count="{declared}">'
        '<dataitem datatype="1"><sourcename>测试发言人</sourcename><srcMsgCreateTime>1792659600</srcMsgCreateTime>'
        '<datadesc>全文第一行\n全文第二行</datadesc><refermsgitem><displayname>引用发言人</displayname>'
        '<type>1</type><content>完整引用内容</content></refermsgitem></dataitem>'
        '<dataitem datatype="8"><sourcename>测试发言人</sourcename><datatitle>测试附件.pdf</datatitle>'
        '<datasize>1234</datasize><cdndatakey>仅用于合成测试的材料</cdndatakey></dataitem>'
        '</datalist></recordinfo>'
    )
    outer = ET.Element('msg')
    app = ET.SubElement(outer, 'appmsg')
    ET.SubElement(app, 'recorditem').text = record
    payload = ET.tostring(outer, encoding='unicode')
    return payload.replace('<appmsg>', '<?xml version="1.0"?><appmsg>')


def test_expand_all_forwarded_content_without_transport_fields(tmp_path):
    records = target.parse_forwarded_records(forwarded_payload())
    assert len(records) == 2
    assert records[0]['content'] == '全文第一行\n全文第二行'
    assert records[0]['reference']['content'] == '完整引用内容'
    assert records[1]['content'] == '[文件] 测试附件.pdf'
    assert records[1]['file_size_bytes'] == 1234
    assert 'cdndatakey' not in json.dumps(records)
    item = {'time': '2026-10-22T17:00:00+08:00', 'app_message': {'kind': 'chat_history', 'thumb_url': '合成预览串'}, 'source_content': forwarded_payload()}
    item = target.expand_forwarded_message(item)
    assert item['forwarded_message_count'] == 2
    assert 'source_content' not in item
    assert 'thumb_url' not in item['app_message']
    meta = {'range_start_inclusive': '16:00', 'range_end_exclusive': '17:00'}
    txt, structured = target.write_exports(tmp_path / '展开', meta, [item])
    assert '全文第一行\n全文第二行' in txt.read_text(encoding='utf-8')
    assert len(json.loads(structured.read_text(encoding='utf-8'))['messages'][0]['forwarded_messages']) == 2


def test_forwarded_count_mismatch_fails_explicitly():
    with pytest.raises(ValueError, match='条数'):
        target.parse_forwarded_records(forwarded_payload('3'))
