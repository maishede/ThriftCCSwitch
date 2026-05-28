# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/claude-code) when working with code in this repository.

## Project Overview

**ThriftCCSwitch** is a Windows desktop application for managing multiple Claude Code API configurations. Built with PyQt5, it allows quick switching between different API endpoints/keys and includes a local proxy server for dynamic API routing.

## Common Development Commands

### Running the Application
```bash
python claude_config_switcher.py
```

### Building the Executable
```bash
python build.py
```
The build script (`build.py`) automatically cleans previous builds, uses PyInstaller with exclusions for litellm/proxy components (since `pool_server.py` runs independently), and opens the `dist/` folder when complete.

### Installing Dependencies
```bash
pip install -r requirements.txt
```

### Running the Proxy Pool Server (Standalone)
```bash
python pool_server.py --port 8899
```

## Architecture

### Main Application (`claude_config_switcher.py`)

**Core Classes:**
- `MainWindow` - Primary PyQt5 GUI window managing node list and proxy pool controls
- `ConfigManager` - JSON-based storage for API configuration nodes
- `PoolConfig` - Manages proxy pool state, port, and API key configuration
- `ApplierThread` - Background thread for applying configurations to Windows environment variables
- `NodeWidget` - UI component displaying individual configuration nodes
- `ProxyCreatorDialog` / `NodeEditorDialog` - Dialogs for creating/editing configurations

**Key Configuration Paths:**
- `%APPDATA%\.ThriftCCSwitch\nodes.json` - Stored API configurations
- `%APPDATA%\.ThriftCCSwitch\current_state.json` - Currently active configuration
- `%APPDATA%\.ThriftCCSwitch\pool_config.json` - Proxy pool settings
- `%APPDATA%\.ThriftCCSwitch\pool_target.json` - Proxy pool target configuration
- `%APPDATA%\.ThriftCCSwitch\proxies\` - Local proxy script directory
- `~\.claude\settings.json` - Claude Code settings (model mappings)

**Environment Variables Managed:**
- `ANTHROPIC_AUTH_TOKEN` - API key
- `ANTHROPIC_BASE_URL` - API endpoint
- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` - Set to '1'
- `HTTP_PROXY` / `HTTPS_PROXY` - Optional proxy configuration
- `ANTHROPIC_MODEL` - Default model override (optional, from node's `default_model`)
- `CLAUDE_CODE_SUBAGENT_MODEL` - Sub-agent model (optional, from node's `subagent_model`)
- `CLAUDE_CODE_EFFORT_LEVEL` - Reasoning effort level (default: `max`)
- `API_TIMEOUT_MS` - API request timeout in ms (default: `600000` = 10 min)

**Node Data Structure:**
- `name` - Display name
- `api_key` - API key
- `base_url` - API endpoint URL
- `haiku_model` / `sonnet_model` / `opus_model` - Model name mappings per tier
- `default_model` - Override model for all tiers (optional)
- `subagent_model` - Sub-agent model name (optional)
- `effort_level` - Reasoning effort: auto/low/medium/high/xhigh/max (default: max)
- `api_timeout` - Timeout in milliseconds (default: 600000)
- `http_proxy` - Proxy address (optional)
- `proxy_path` - Path to proxy startup script (for proxy-generated nodes)

### Proxy Pool Server (`pool_server.py`)

Independent FastAPI server that:
- Forwards HTTP requests to a target API endpoint (timeout: 600s)
- Maps Anthropic model names to target platform models
- Provides `/__/health` and `/__/reload` endpoints
- Runs as background process without console window

**Model Mapping in Proxy Pool:**
- `claude-haiku-4-20250514` → target's haiku_model
- `claude-sonnet-4-20250514` → target's sonnet_model
- `claude-opus-4-20250514` → target's opus_model

### Operating Modes

**Normal Mode:** Config writes directly to Windows registry environment variables. Requires terminal restart to take effect.

**Proxy Pool Mode:** Environment variables point to local proxy server (`http://127.0.0.1:PORT`). Switching configs updates proxy target via `/__/reload` endpoint without changing environment variables - no terminal restart needed. In pool mode, `ANTHROPIC_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL` are NOT set (proxy handles model mapping); only `CLAUDE_CODE_EFFORT_LEVEL` and `API_TIMEOUT_MS` are written.

## Data Flow

1. **Apply Configuration:**
   - `ApplierThread` runs in background
   - If pool enabled: updates `pool_target.json`, calls `/__/reload`
   - If pool disabled: writes to Windows registry via `winreg`, broadcasts environment change
   - Updates `~/.claude/settings.json` with model mappings and extended env vars
   - Cleans stale extended env vars from registry and os.environ if empty
   - Saves hash to `current_state.json`

2. **Proxy Pool Toggle:**
   - Start: Launches `pool_server.py` as hidden subprocess, points env vars to proxy
   - Stop: Terminates pool process, restores env vars from current node config

3. **Startup Sync:**
   - On launch, reads `current_state.json` and restores env vars to active config for current process

## Build Configuration

The `build.py` script excludes litellm/proxy dependencies from the main executable since `pool_server.py` requires them separately. Excluded modules include: `litellm`, `fastapi`, `uvicorn`, `httpx`, `yaml`, and data science/ML frameworks.

## Git Workflow

From README:
1. Create dev branch from main: `git checkout -b dev/{version}`
2. Develop on branch, then merge back to main
3. Tag on main: `git tag v{version}`
4. Push code and tags

Current development branch: `dev/v0.0.2`
