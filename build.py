# -*- coding: utf-8 -*-
import os
import subprocess
import shutil
import sys
import time


def clean_previous_builds(exe_name):
    """清理之前的构建文件"""
    print("🧹 正在清理旧的构建文件...")

    # 需要清理的目录
    dirs_to_remove = ["build", "dist"]
    # 需要清理的文件
    files_to_remove = [f"{exe_name}.spec"]

    # 1. 清理目录
    for d in dirs_to_remove:
        if os.path.exists(d):
            try:
                shutil.rmtree(d)
                print(f"   - 已删除目录: {d}")
            except Exception as e:
                print(f"   ❌ 无法删除目录 {d}: {e}")

    # 2. 清理文件
    for f in files_to_remove:
        if os.path.exists(f):
            try:
                os.remove(f)
                print(f"   - 已删除文件: {f}")
            except Exception as e:
                print(f"   ❌ 无法删除文件 {f}: {e}")

    # 稍微暂停一下，确保文件系统释放锁（Windows下有时需要）
    time.sleep(1)
    print("✅ 清理完成，准备开始打包...\n")


def build():
    # 1. 定义文件名
    script_file = "claude_config_switcher.py"  # 你的主代码文件
    exe_name = "ThriftCCSwitch"

    # 2. 检查主文件是否存在
    if not os.path.exists(script_file):
        print(f"错误: 找不到文件 {script_file}")
        return

    # --- [新增] 执行清理操作 ---
    clean_previous_builds(exe_name)
    # -----------------------

    print("🚀 正在开始打包...")

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
        if os.path.exists(dist_path):
            os.startfile(dist_path)

    except subprocess.CalledProcessError:
        print("\n❌ 打包失败，请检查上方错误信息。")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")


if __name__ == "__main__":
    build()