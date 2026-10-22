"""将 skill 自带模块加入测试路径；不访问微信或个人导出文件。"""
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "vendor"))
