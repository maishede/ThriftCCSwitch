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

    # --- 执行清理操作 ---
    clean_previous_builds(exe_name)
    # -----------------------

    print("🚀 正在开始打包...")
    print("📦 说明：代理池服务器功能已集成到主程序中")

    # 3. 排除不需要的模块列表
    # 注意：不再排除 fastapi、uvicorn、httpx，因为代理池功能需要这些依赖
    excluded_modules = [
        # litellm 相关（不需要）
        "litellm", "yaml",

        # 数据科学包（主程序不需要）
        "numpy", "pandas", "scipy", "matplotlib",
        "sklearn", "skimage", "statsmodels",

        # 深度学习框架（主程序不需要）
        "torch", "torchvision", "torchaudio",
        "tensorflow", "keras",

        # 开发工具（主程序不需要）
        "IPython", "jedi", "parso", "prompt_toolkit",

        # 其他不需要的包
        "datasets", "tokenizers", "transformers",
        "PIL", "cv2", "openpyxl", "botocore", "fsspec",
    ]

    # 4. 组装命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "-F",  # 单文件
        "-w",  # 无窗口模式
        "--clean",  # 清理缓存
        "--noconfirm",  # 不询问覆盖
        "--name", exe_name,
    ]

    # 添加所有排除模块
    for module in excluded_modules:
        cmd.extend(["--exclude-module", module])

    # 添加脚本文件
    cmd.append(script_file)

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
        print("\n💡 提示：")
        print("   - 直接运行 exe 启动 GUI 模式")
        print("   - 使用 --pool-server --port 8899 启动代理池服务器模式")
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
