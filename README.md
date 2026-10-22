# 微信聊天导出 Skill

面向 Codex 的 Windows 微信 4.x 导出技能：按时间范围读取**文件传输助手**，将普通消息及合并转发中的原始对话保存为 TXT、JSON 和验证报告。

适合先把需要整理的好友或群聊消息合并转发到文件传输助手，再交给 Codex、全文搜索或其他分析软件读取。当前不会直接按好友或群名读取原会话。

## 安装到 Codex

在 PowerShell 中运行：

```powershell
git clone https://github.com/yeklongdi/wechat-chat-export.git (Join-Path $env:USERPROFILE '.codex\skills\wechat-chat-export')
```

如设置了 `CODEX_HOME`，将仓库放到其 `skills/wechat-chat-export` 子目录。随后在能够加载该目录技能的 Codex 会话中使用：

```text
使用 $wechat-chat-export，导出文件传输助手最近 60 分钟的记录，
展开所有合并转发，生成 TXT 和 JSON。
```

## 命令行使用

需要 Windows、已登录的微信 4.x，以及带有 `sqlite3.deserialize` 的 Python 3.11 或更新版本。实时流程已在微信 **4.1.6.46 / Python 3.12** 上验证；其他微信版本需要以实际运行结果为准。

```powershell
$taskSkillRoot = Join-Path $env:USERPROFILE '.codex\skills\wechat-chat-export'
& (Join-Path $taskSkillRoot 'scripts\setup.ps1') -WithTests

$taskPython = Join-Path $env:LOCALAPPDATA 'wechat-chat-export\venv\Scripts\python.exe'
$taskExporter = Join-Path $taskSkillRoot 'scripts\export_wechat.py'

# 最近 60 分钟，缺省输出到 Documents/WeChat Exports
& $taskPython -B $taskExporter --minutes 60

# 明确时段，结束时刻不含；示例日期仅说明参数格式
& $taskPython -B $taskExporter --start '2026-01-15T09:00:00+08:00' --end '2026-01-15T10:00:00+08:00'
```

可使用 `--output-root` 指定输出目录；多账号环境使用 `--db-dir` 指向已明确选择的本人账号 `db_storage`。详见 [运行说明](references/operation.md)。

## 输出与实际限制

- `聊天记录.txt`：展开的原始发言人、时间、完整正文和引用，便于直接阅读。
- `聊天记录.json`：外层消息和结构化的 `forwarded_messages`，便于程序分析。
- `验证报告.json`：计数、正文回读检查、文件大小和 SHA-256。

筛选按**消息进入文件传输助手的时间**执行，合并转发内原始对话可以来自更早日期。图片、视频、语音和文件保留消息位置及可解析信息，当前不复制媒体或附件本体。

导出过程对源数据库只读，密钥和明文数据库在进程内处理。输出是明文资料，保存在单独的新目录；Windows 下为新目录限定当前用户和 SYSTEM 的访问权限。脚本处理本机现存资料，不能据此声称恢复了手机上未同步或已删除的记录。

## 开发与来源

```powershell
& (Join-Path $taskSkillRoot 'scripts\setup.ps1') -WithTests
```

测试使用合成数据库、消息与 XML，覆盖页认证、WAL 事务、时间边界、转发展开、引用和正文保真。测试不需要个人聊天数据。

关键模块已随仓库打包，并记录了来源版本，不需要在运行时克隆其他代码仓库。项目采用 MIT 许可；第三方代码及改动详见 [第三方说明](THIRD_PARTY.md) 和 [许可证目录](licenses)。
