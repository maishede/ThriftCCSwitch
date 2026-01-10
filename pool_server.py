"""
ThriftCCSwitch Proxy Pool Server

Simple HTTP forwarding service for Anthropic-compatible endpoints.
No litellm dependency - just straightforward request forwarding.
"""

import os
import sys
import json
import httpx
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
import uvicorn

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
target_config = None


def load_pool_config():
    """Load proxy pool config"""
    if not POOL_CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config file not found: {POOL_CONFIG_FILE}")
    with open(POOL_CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_target_config():
    """Load target config"""
    if not POOL_TARGET_FILE.exists():
        raise FileNotFoundError(f"Target config file not found: {POOL_TARGET_FILE}")
    with open(POOL_TARGET_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def update_target():
    """Update target from config file"""
    global target_config
    target_config = load_target_config()


# Create FastAPI app
app = FastAPI(title="ThriftCCSwitch Pool")


@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    global target_config
    print("=" * 50)
    print("[INFO] ThriftCCSwitch Proxy Pool Server starting...")
    print("=" * 50)

    try:
        pool_config = load_pool_config()
        print(f"[INFO] Load config: {POOL_CONFIG_FILE}")
        print(f"   Port: {pool_config.get('port')}")
        print(f"   Key: {pool_config.get('key')}")

        update_target()
        print(f"[OK] Target loaded: {target_config.get('base_url')}")

        print("=" * 50)
        print("[OK] Proxy pool server ready")
        print("=" * 50)

    except Exception as e:
        print(f"[ERROR] Startup failed: {e}")
        raise


@app.get("/__/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "target": target_config.get('base_url') if target_config else None
    }


@app.post("/__/reload")
async def reload_config():
    """Reload config endpoint"""
    try:
        print("\n" + "=" * 50)
        print("[INFO] Received reload request...")
        print("=" * 50)

        update_target()

        print("[OK] Config reloaded")
        print(f"   New target: {target_config.get('base_url')}")
        print("=" * 50 + "\n")

        return {
            "status": "ok",
            "message": "Config reloaded successfully",
            "target": target_config.get('base_url')
        }

    except Exception as e:
        print(f"[ERROR] Reload failed: {e}")
        raise


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_request(request: Request, path: str):
    """Proxy all requests to target server"""
    if not target_config:
        return Response(content="Target not configured", status_code=503)

    # Build target URL
    target_url = target_config.get('base_url', '').rstrip('/')
    url = f"{target_url}/{path.lstrip('/')}"
    if request.url.query:
        url += f"?{request.url.query}"

    # Get request body
    body = await request.body()

    # Build headers - remove auth headers and use target API key
    headers = {}
    for key, value in request.headers.items():
        # Skip auth-related headers
        if key.lower() in ['host', 'x-api-key', 'authorization']:
            continue
        # Copy other headers
        headers[key] = value

    # Add target API key
    api_key = target_config.get('api_key', '')
    headers['x-api-key'] = api_key

    # Forward request
    async with httpx.AsyncClient(verify=False, timeout=120.0) as client:
        try:
            response = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=body
            )

            # Return response (filter out hop-by-hop headers)
            response_headers = {}
            for key, value in response.headers.items():
                if key.lower() not in ['content-encoding', 'transfer-encoding', 'connection']:
                    response_headers[key] = value

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=response_headers
            )

        except httpx.HTTPError as e:
            return Response(content=f"Proxy error: {str(e)}", status_code=502)


# Main entry point
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8899, help='Port to listen on')
    args = parser.parse_args()

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        log_level="warning"
    )
