"""验证可复用参数、正文保真和最终产物，而非访问真实微信。"""
from datetime import datetime
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
import export_wechat as target


def test_explicit_range_is_independent_of_host_timezone():
    args, start, end = target.parse_args([
        '--start', '2026-01-15T09:00:00', '--end', '2026-01-15T10:00:00+08:00',
        '--output-root', 'test-output',
    ])
    assert end - start == 3600
    assert datetime.fromtimestamp(start, target.SHANGHAI).hour == 9
    assert args.output_root == Path('test-output')


@pytest.mark.parametrize('args', [
    ['--minutes', '0'], ['--minutes', '-1'], ['--end', '2026-01-15T10:00:00'],
    ['--minutes', '60', '--end', '2026-01-15T10:00:00'],
    ['--start', '2026-01-15T10:00:00', '--end', '2026-01-15T09:00:00'],
    ['--start', 'invalid'],
])
def test_invalid_parameters_fail_before_live_access(args):
    with pytest.raises(SystemExit) as failure:
        target.parse_args(args)
    assert failure.value.code == 2


def test_minutes_can_be_configured():
    _, start, end = target.parse_args(['--minutes', '15'])
    assert end - start == 15 * 60


def test_cdata_keeps_user_xml_declaration():
    body = '<?xml version="1.0"?><example>用户粘贴的 XML</example>'
    record = '<recordinfo><datalist count="1"><dataitem datatype="1"><sourcename>示例用户</sourcename><datadesc><![CDATA[' + body + ']]></datadesc></dataitem></datalist></recordinfo>'
    outer = ET.Element('msg')
    ET.SubElement(outer, 'recorditem').text = record
    assert target.parse_forwarded_records(ET.tostring(outer, encoding='unicode'))[0]['content'] == body


def test_export_validation_reads_complete_unicode_and_reference(tmp_path):
    entry = {'time': '2026-01-15T09:10:00+08:00', 'sender': '示例用户', 'type': '文字', 'content': '第一行😀\n第二行完整正文', 'reference': {'sender': '示例朋友', 'content': '完整引用'}}
    message = {'time': '2026-01-15T09:20:00+08:00', 'forwarded_messages': [entry], 'forwarded_message_count': 1}
    metadata = {'message_count': 1, 'forwarded_message_count': 1, 'range_start_inclusive': '09:00', 'range_end_exclusive': '10:00'}
    txt, structured = target.write_exports(tmp_path / 'export', metadata, [message])
    report = target.validate_exports(txt, structured)
    assert report['status'] == 'passed'
    assert report['forwarded_message_count'] == 1
    assert len(report['text_sha256']) == 64
    txt.write_text('缺少完整内容', encoding='utf-8')
    with pytest.raises(ValueError, match='完整正文'):
        target.validate_exports(txt, structured)


def test_existing_output_directory_is_not_overwritten(tmp_path):
    folder = tmp_path / 'existing'
    folder.mkdir()
    sentinel = folder / 'keep.txt'
    sentinel.write_text('原有文件', encoding='utf-8')
    with pytest.raises(FileExistsError):
        target.private_output_folder(folder)
    assert sentinel.read_text(encoding='utf-8') == '原有文件'


def test_media_metadata_does_not_include_transport_xml():
    row = {'local_type': 3, 'create_time': 1, 'sender_username': 'wxid_example', 'local_id': 1, 'server_id': 1, 'message_content': '<msg><img aeskey="synthetic-only"/></msg>'}
    message = target.format_message(row, 'wxid_example', 'synthetic.db')
    assert message['content'] == '[图片]'
    assert message['media_exported'] is False
    assert 'synthetic-only' not in json.dumps(message)
