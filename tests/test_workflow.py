"""在临时合成数据上验证完整导出链路及多账号选择边界。"""
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest
import export_wechat as target

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='完整实时入口针对 Windows')


def test_complete_export_keeps_only_authorized_window(tmp_path, monkeypatch):
    storage = tmp_path / 'xwechat_files' / 'wxid_example_abcd' / 'db_storage'
    messages = storage / 'message'
    messages.mkdir(parents=True)
    encrypted = b'0123456789abcdef' + bytes(target.PAGE - 16)
    (messages / 'message_0.db').write_bytes(encrypted)

    con = sqlite3.connect(':memory:')
    con.execute('CREATE TABLE Name2Id(user_name TEXT)')
    con.execute("INSERT INTO Name2Id VALUES('wxid_example')")
    con.execute(f'CREATE TABLE "{target.TARGET_TABLE}"(local_id INTEGER,server_id INTEGER,create_time INTEGER,local_type INTEGER,real_sender_id INTEGER,message_content BLOB)')
    for index, time, text in [(1, 99, '窗口以外'), (2, 100, '应导出的完整正文\n保留第二行'), (3, 200, '结束边界以外')]:
        con.execute(f'INSERT INTO "{target.TARGET_TABLE}" VALUES(?,?,?,?,?,?)', (index, index, time, 1, 1, text))
    con.execute('CREATE TABLE unrelated_private_conversation(content TEXT)')
    con.execute("INSERT INTO unrelated_private_conversation VALUES('其他会话资料')")
    plaintext = con.serialize()
    con.close()

    tool = SimpleNamespace(auto_detect_db_dir=lambda: str(storage))

    def scan(directory, unused_output):
        assert directory == str(storage.resolve())
        entries, salts = tool.collect_db_files(directory)
        assert len(entries) == len(salts) == 1
        assert tool._save_results({}, {}, {}, '', 'must-not-write.json') is None
        return {encrypted[:16].hex(): bytes(range(32)).hex()}

    tool._scan_memory_raw_key = scan
    monkeypatch.setattr(target, 'load_key_tool', lambda: tool)
    monkeypatch.setattr(target, 'read_snapshot', lambda path: encrypted)

    def decrypt(data, key):
        assert data == encrypted and key == bytes(range(32))
        return plaintext

    monkeypatch.setattr(target, 'decrypt_snapshot', decrypt)
    result = target.export(100, 200, tmp_path / 'results')
    assert result['status'] == 'complete'
    assert result['messages'] == 1
    data = json.loads(Path(result['json_file']).read_text(encoding='utf-8'))
    assert data['messages'][0]['content'] == '应导出的完整正文\n保留第二行'
    assert data['messages'][0]['sender'] == '我'
    assert '窗口以外' not in json.dumps(data, ensure_ascii=False)
    assert '其他会话资料' not in json.dumps(data, ensure_ascii=False)
    assert data['metadata']['keys_saved'] is False
    output = Path(result['json_file']).parent
    assert sorted(path.suffix for path in output.iterdir()) == ['.json', '.json', '.txt']
    assert not list(output.rglob('*.db'))


def test_multiple_accounts_require_explicit_selection(tmp_path, monkeypatch):
    parent = tmp_path / 'xwechat_files'
    first = parent / 'first_account' / 'db_storage'
    first.mkdir(parents=True)
    (parent / 'second_account' / 'db_storage').mkdir(parents=True)
    tool = SimpleNamespace(auto_detect_db_dir=lambda: str(first))
    monkeypatch.setattr(target, 'load_key_tool', lambda: tool)
    with pytest.raises(RuntimeError, match='多个账号'):
        target.export(100, 200, tmp_path / 'results')
    assert not (tmp_path / 'results').exists()


def test_bundled_reader_loads_without_reading_live_data():
    tool = target.load_key_tool()
    assert callable(tool._scan_memory_raw_key)
    assert callable(tool.auto_detect_db_dir)
