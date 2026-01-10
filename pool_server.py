"""
ThriftCCSwitch 代理池服务器

支持动态切换转发目标的代理服务，基于 litellm 实现。
通过内部 /reload 端点支持配置热重载。
"""

import os
import json
import yaml
import uvicorn
import secrets
from pathlib import Path
from fastapi import FastAPI, HTTPException
from typing import Optional, Dict, Any

# 配置文件路径
CONFIG_DIR = Path(os.path.expandvars(r'%APPDATA%\.ThriftCCSwitch'))
POOL_CONFIG_FILE = CONFIG_DIR / 'pool_config.json'
POOL_TARGET_FILE = CONFIG_DIR / 'pool_target.json'

# FastAPI 应用
app = FastAPI(title="ThriftCCSwitch Pool")

# 全局变量
litellm_app = None
current_target: Optional[Dict[str, Any]] = None


def load_pool_config() -> Dict[str, Any]:
    """加载代理池配置"""
    if not POOL_CONFIG_FILE.exists():
        raise FileNotFoundError(f"配置文件不存在: {POOL_CONFIG_FILE}")

    with open(POOL_CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_target_config() -> Dict[str, Any]:
    """加载目标配置"""
    if not POOL_TARGET_FILE.exists():
        raise FileNotFoundError(f"目标配置文件不存在: {POOL_TARGET_FILE}")

    with open(POOL_TARGET_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def generate_litellm_config(target: Dict[str, Any]) -> Dict[str, Any]:
    """根据目标配置生成 litellm 配置"""
    api_key = target.get('api_key', '')
    base_url = target.get('base_url', '')
    models = []

    # 构建模型映射列表
    for model_type in ['haiku_model', 'sonnet_model', 'opus_model']:
        model_name = target.get(model_type, '')
        if model_name:
            models.append({
                "model_name": model_name,
                "litellm_params": {
                    "model": f"openai/{model_name}",
                    "api_key": api_key,
                    "api_base": base_url
                }
            })

    # 添加通配符模型映射
    if models:
        models.append({
            "model_name": "*",
            "litellm_params": {
                "model": "openai/*",
                "api_key": api_key,
                "api_base": base_url
            }
        })

    return {"model_list": models}


async def initialize_proxy():
    """初始化 litellm 代理"""
    global litellm_app, current_target

    try:
        # 加载目标配置
        target = load_target_config()
        current_target = target

        # 生成 litellm 配置
        config = generate_litellm_config(target)

        # 保存配置文件
        config_file = CONFIG_DIR / 'litellm_pool_config.yaml'
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True)

        # 导入并初始化 litellm
        from litellm.proxy.proxy_server import initialize
        await initialize(config=str(config_file))

        print(f"✅ 代理池初始化成功")
        print(f"   目标: {target.get('base_url')}")
        print(f"   模型: {[m.get('model_name') for m in config.get('model_list', [])]}")

    except Exception as e:
        print(f"❌ 代理池初始化失败: {e}")
        raise


@app.on_event("startup")
async def startup_event():
    """服务启动时初始化"""
    print("=" * 50)
    print("🚀 ThriftCCSwitch 代理池服务器启动中...")
    print("=" * 50)

    try:
        pool_config = load_pool_config()
        print(f"📋 加载配置: {POOL_CONFIG_FILE}")
        print(f"   端口: {pool_config.get('port')}")
        print(f"   Key: {pool_config.get('key')}")

        await initialize_proxy()

        print("=" * 50)
        print("✅ 代理池服务已就绪")
        print("=" * 50)

    except Exception as e:
        print(f"❌ 启动失败: {e}")
        raise


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "ok",
        "target": current_target.get('base_url') if current_target else None
    }


@app.post("/reload")
async def reload_config():
    """重载配置端点（内部调用）"""
    try:
        print("\n" + "=" * 50)
        print("🔄 收到重载请求...")
        print("=" * 50)

        await initialize_proxy()

        print("✅ 配置重载完成")
        print("=" * 50 + "\n")

        return {
            "status": "ok",
            "message": "配置重载成功",
            "target": current_target.get('base_url') if current_target else None
        }

    except Exception as e:
        print(f"❌ 重载失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 主程序入口
if __name__ == "__main__":
    import sys

    # 从命令行参数获取端口
    port = 8899
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"⚠️ 无效的端口号: {sys.argv[1]}，使用默认端口 8899")

    # 运行服务器
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning"
    )
