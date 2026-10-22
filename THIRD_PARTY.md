# 第三方代码来源

本仓库保留了下列 MIT 许可代码。顶层 `LICENSE` 适用于本项目新增部分，原始版权及许可全文分别保存在 `licenses/`。

| 本仓库文件 | 来源与版本 | 处理 |
|---|---|---|
| `scripts/vendor/wcdb_key_tool_windows.py` | [TANGandXUE/wcdb-key-tool](https://github.com/TANGandXUE/wcdb-key-tool/tree/79f1b5b92e12c66aa281b4a60a3c478b5f547dfa)，`wcdb_key_tool_windows.py` | 原样保留；主流程仅调用只读扫描，并替换结果写出回调 |
| `scripts/vendor/appmsg.py` | [freanocank/wechat-decrypt](https://github.com/freanocank/wechat-decrypt/tree/f0b3f9f95dda2d954ee3dbe1d139fb1944a5ecfd)，`appmsg.py` | 原样保留 |
| `scripts/vendor/crypto_backend.py` | 同上，`scripts/common/crypto_backend.py` | 原样保留 |
| `scripts/vendor/wal_snapshot.py` | 同上，`scripts/common/wal_snapshot.py` | 原样保留 |
| `scripts/vendor/message.py` | 同上，`message.py` | 移除 `db` 导入和三个依赖数据库的发送方检测函数，保留解码、类型及系统消息解析 |
| `tests/test_wal_snapshot.py` | 同上，`tests/test_wal_snapshot.py` | 取不依赖原项目解密入口的合成 WAL 与 SQLite 快照测试，并加入来源注释 |

原始版权声明：

- `wcdb-key-tool`：Copyright (c) 2025 CloudDreamAI / TANGandXUE；见 `licenses/wcdb-key-tool-MIT.txt`。
- `wechat-decrypt`：Copyright (c) 2026 cocofeng；见 `licenses/wechat-decrypt-MIT.txt`。

这些来源是实现依据，不构成微信或腾讯对本项目的认可，也不表示它们保证了所有后续客户端版本的兼容性。
