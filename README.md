# ThriftCCSwitch

Claude Code 配置切换工具，支持快速切换不同的 API 配置节点，并内置本地代理生成功能。

## 功能特性

- **配置管理**：添加、编辑、复制、删除多个 API 配置节点
- **一键切换**：快速应用不同配置到系统环境变量
- **本地代理**：一键生成 OpenAI 格式转 Anthropic 格式的本地代理服务
- **环境变量查看**：快速查看当前环境变量状态
- **自动同步**：启动时自动同步上次使用的配置

## 安装

```bash
pip install -r requirements.txt
```

## 运行

```bash
python claude_config_switcher.py
```

## 打包

```bash
python build.py
```

打包后的 exe 文件位于 `dist` 目录。

## 配置说明

### 普通配置

直接配置 Anthropic API 的信息：

| 配置项 | 说明 | 示例 |
|--------|------|------|
| 节点名称 | 配置的显示名称 | 智谱 API |
| API Key | Anthropic API 密钥 | sk-xxxxx |
| Base URL | API 基础地址 | https://open.bigmodel.cn/api/anthropic |
| Haiku Model | 快速模型 | glm-4.5-air |
| Sonnet Model | 均衡模型 | glm-4.7 |
| Opus Model | 强力模型 | glm-4.7 |

### 本地代理

将 OpenAI 格式的 API 转换为 Anthropic 格式：

| 配置项 | 说明 |
|--------|------|
| 监听端口 | 本地代理服务监听的端口 |
| 局域网访问 | 是否允许 0.0.0.0 访问 |
| 目标 URL | OpenAI 格式的 API 地址 |
| API Key | 目标 API 的密钥 |
| 模型映射 | 将 Anthropic 模型名映射到目标模型 |

代理启动后，配置 `base_url` 为 `http://127.0.0.1:端口` 即可使用。

## 文件位置

配置文件存储位置：`%APPDATA%\.ThriftCCSwitch\`

- `nodes.json` - 节点配置
- `current_state.json` - 当前激活的配置
- `proxies\` - 本地代理文件目录

## 注意事项

- 切换配置后，**需要重新打开终端**才能使环境变量生效
- 主窗口关闭时会自动终止所有正在运行的代理进程
- 确保已安装 Python 3.8+

## 依赖

- PyQt5 - 图形界面
- psutil - 进程管理
- litellm - 代理服务（仅本地代理功能需要）