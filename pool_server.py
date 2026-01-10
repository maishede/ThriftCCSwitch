"""
ThriftCCSwitch Proxy Pool Server

Proxy service with dynamic target switching based on litellm.
Supports hot reload via internal /reload endpoint.
"""

import os
import sys
import json
import yaml
import uvicorn
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from typing import Optional, Dict, Any

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Config file paths
CONFIG_DIR = Path(os.path.expandvars(r'%APPDATA%\.ThriftCCSwitch'))
POOL_CONFIG_FILE = CONFIG_DIR / 'pool_config.json'
POOL_TARGET_FILE = CONFIG_DIR / 'pool_target.json'

# Global variables
current_target: Optional[Dict[str, Any]] = None
litellm_initialized = False


def load_pool_config() -> Dict[str, Any]:
    """Load proxy pool config"""
    if not POOL_CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config file not found: {POOL_CONFIG_FILE}")

    with open(POOL_CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_target_config() -> Dict[str, Any]:
    """Load target config"""
    if not POOL_TARGET_FILE.exists():
        raise FileNotFoundError(f"Target config file not found: {POOL_TARGET_FILE}")

    with open(POOL_TARGET_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def generate_litellm_config(target: Dict[str, Any]) -> Dict[str, Any]:
    """Generate litellm config from target"""
    api_key = target.get('api_key', '')
    base_url = target.get('base_url', '')
    models = []

    # Build model mapping list
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

    # Add wildcard model mapping
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
    """Initialize litellm proxy"""
    global current_target, litellm_initialized

    try:
        # Load target config
        target = load_target_config()
        current_target = target

        # Generate litellm config
        config = generate_litellm_config(target)

        # Save config file
        config_file = CONFIG_DIR / 'litellm_pool_config.yaml'
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True)

        # Import and initialize litellm
        from litellm.proxy.proxy_server import initialize
        await initialize(config=str(config_file))
        litellm_initialized = True

        print(f"[OK] Proxy pool initialized")
        print(f"   Target: {target.get('base_url')}")
        print(f"   Models: {[m.get('model_name') for m in config.get('model_list', [])]}")

    except Exception as e:
        print(f"[ERROR] Proxy pool initialization failed: {e}")
        raise


async def reload_proxy():
    """Reload litellm proxy with new config"""
    global current_target, litellm_initialized

    try:
        # Load target config
        target = load_target_config()
        current_target = target

        # Generate litellm config
        config = generate_litellm_config(target)

        # Save config file
        config_file = CONFIG_DIR / 'litellm_pool_config.yaml'
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True)

        # Reload litellm config
        from litellm.proxy.proxy_server import ProxyConfig
        from litellm.proxy.cli.utils import load_config
        import litellm
        litellm.set_verbose = False

        # Create new config
        proxy_config = load_config(config=str(config_file))

        # Update router config
        from litellm.proxy.proxy_server import save_worker_config
        save_worker_config(config=str(config_file), model_list=config.get('model_list', []))

        print(f"[OK] Proxy pool reloaded")
        print(f"   Target: {target.get('base_url')}")

    except Exception as e:
        print(f"[ERROR] Proxy pool reload failed: {e}")
        raise


# Import litellm app first
from litellm.proxy.proxy_server import app as litellm_app, initialize

# Add custom endpoints to litellm app
@litellm_app.get("/__/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "target": current_target.get('base_url') if current_target else None,
        "initialized": litellm_initialized
    }


@litellm_app.post("/__/reload")
async def reload_config():
    """Reload config endpoint (internal)"""
    try:
        print("\n" + "=" * 50)
        print("[INFO] Received reload request...")
        print("=" * 50)

        await reload_proxy()

        print("[OK] Config reloaded")
        print("=" * 50 + "\n")

        return {
            "status": "ok",
            "message": "Config reloaded successfully",
            "target": current_target.get('base_url') if current_target else None
        }

    except Exception as e:
        print(f"[ERROR] Reload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Startup event
@litellm_app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    print("=" * 50)
    print("[INFO] ThriftCCSwitch Proxy Pool Server starting...")
    print("=" * 50)

    try:
        pool_config = load_pool_config()
        print(f"[INFO] Load config: {POOL_CONFIG_FILE}")
        print(f"   Port: {pool_config.get('port')}")
        print(f"   Key: {pool_config.get('key')}")

        await initialize_proxy()

        print("=" * 50)
        print("[OK] Proxy pool server ready")
        print("=" * 50)

    except Exception as e:
        print(f"[ERROR] Startup failed: {e}")
        raise


# Main entry point
if __name__ == "__main__":
    # Get port from command line args
    port = 8899
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"[WARN] Invalid port number: {sys.argv[1]}, using default port 8899")

    # Run server
    uvicorn.run(
        litellm_app,
        host="127.0.0.1",
        port=port,
        log_level="warning"
    )
