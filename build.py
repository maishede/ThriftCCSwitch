# -*- coding: utf-8 -*-
import os
import subprocess
import shutil
import sys


def build():
    # 1. 定义文件名
    script_file = "claude_config_switcher.py"  # 你的主代码文件
    exe_name = "ThriftCCSwitch"

    # 2. 检查主文件是否存在
    if not os.path.exists(script_file):
        print(f"错误: 找不到文件 {script_file}")
        return

    print("正在开始打包...")

    # 3. 组装命令 (等同于在命令行输入)
    # 使用 sys.executable 确保调用的是当前环境的 Python
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "-F",  # 单文件
        "-w",  # 无窗口模式
        "--clean",  # 清理缓存
        "--noconfirm",  # 不询问覆盖
        "--name", exe_name,
        script_file
    ]

    try:
        # 执行命令
        subprocess.check_call(cmd)

        print("\n" + "=" * 30)
        print("✅ 打包成功！")

        # 获取 dist 路径
        dist_path = os.path.join(os.getcwd(), "dist")
        exe_path = os.path.join(dist_path, f"{exe_name}.exe")
        print(f"文件位置: {exe_path}")
        print("=" * 30)

        # 尝试自动打开文件夹
        os.startfile(dist_path)

    except subprocess.CalledProcessError:
        print("\n❌ 打包失败，请检查上方错误信息。")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")


if __name__ == "__main__":
    build()