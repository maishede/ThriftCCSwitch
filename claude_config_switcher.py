import sys
import os
import json
import subprocess
import winreg
import ctypes
import hashlib
import copy
import shutil
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QDialog, QFormLayout, QLineEdit, QMessageBox, QFrame,
                             QProgressDialog, QSpinBox, QCheckBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QCloseEvent

# --- 全局配置 ---
APP_NAME = "ThriftCCSwitch"
APPDATA = os.getenv('APPDATA')
USER_PROFILE = os.path.expanduser('~')

# 标准的 Anthropic 模型名（用于代理池模式）
STANDARD_ANTHROPIC_MODELS = {
    'haiku': 'claude-haiku-4-20250514',
    'sonnet': 'claude-sonnet-4-20250514',
    'opus': 'claude-opus-4-20250514'
}

# 1. 确保配置目录结构清晰
APP_DIR = os.path.join(APPDATA, '.ThriftCCSwitch')
DATA_FILE = os.path.join(APP_DIR, 'nodes.json')
CURRENT_STATE_FILE = os.path.join(APP_DIR, 'current_state.json')
# 2. 专门的代理脚本存放目录
PROXIES_DIR = os.path.join(APP_DIR, 'proxies')

CLAUDE_DIR = os.path.join(USER_PROFILE, '.claude')
CLAUDE_SETTINGS_FILE = os.path.join(CLAUDE_DIR, 'settings.json')

# 初始化目录
if not os.path.exists(APP_DIR): os.makedirs(APP_DIR)
if not os.path.exists(PROXIES_DIR): os.makedirs(PROXIES_DIR)
if not os.path.exists(CLAUDE_DIR): os.makedirs(CLAUDE_DIR)


# --- 工具类 ---
class Utils:
    @staticmethod
    def get_config_hash(data):
        """计算配置字典的MD5哈希"""
        clean_data = {k: data.get(k) for k in [
            'api_key', 'base_url', 'haiku_model', 'sonnet_model', 'opus_model', 'http_proxy'
        ]}
        s = json.dumps(clean_data, sort_keys=True)
        return hashlib.md5(s.encode('utf-8')).hexdigest()


# --- 代理池配置管理 ---
class PoolConfig:
    """代理池配置管理类"""

    CONFIG_FILE = os.path.join(APP_DIR, 'pool_config.json')
    TARGET_FILE = os.path.join(APP_DIR, 'pool_target.json')
    DEFAULT_PORT = 8899

    @staticmethod
    def get_config():
        """获取代理池配置，如果不存在则创建默认配置"""
        if os.path.exists(PoolConfig.CONFIG_FILE):
            with open(PoolConfig.CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            # 创建默认配置
            config = {
                'enabled': False,
                'port': PoolConfig.DEFAULT_PORT,
                'key': PoolConfig._generate_key()
            }
            PoolConfig.save_config(config)
            return config

    @staticmethod
    def save_config(config):
        """保存代理池配置"""
        with open(PoolConfig.CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _generate_key():
        """生成代理池key"""
        import secrets
        return f"sk-pool-{secrets.token_hex(8)}"

    @staticmethod
    def is_enabled():
        """检查代理池是否启用"""
        config = PoolConfig.get_config()
        return config.get('enabled', False)

    @staticmethod
    def set_enabled(enabled: bool):
        """设置代理池启用状态"""
        config = PoolConfig.get_config()
        config['enabled'] = enabled
        PoolConfig.save_config(config)

    @staticmethod
    def get_port():
        """获取代理池端口"""
        config = PoolConfig.get_config()
        return config.get('port', PoolConfig.DEFAULT_PORT)

    @staticmethod
    def set_port(port: int):
        """设置代理池端口"""
        config = PoolConfig.get_config()
        config['port'] = port
        PoolConfig.save_config(config)

    @staticmethod
    def get_key():
        """获取代理池key"""
        config = PoolConfig.get_config()
        return config.get('key', '')

    @staticmethod
    def get_pool_url():
        """获取代理池URL"""
        return f"http://127.0.0.1:{PoolConfig.get_port()}"

    @staticmethod
    def save_target(node_data):
        """保存目标节点配置"""
        target = {
            'api_key': node_data.get('api_key', ''),
            'base_url': node_data.get('base_url', ''),
            'haiku_model': node_data.get('haiku_model', ''),
            'sonnet_model': node_data.get('sonnet_model', ''),
            'opus_model': node_data.get('opus_model', '')
        }
        with open(PoolConfig.TARGET_FILE, 'w', encoding='utf-8') as f:
            json.dump(target, f, indent=2, ensure_ascii=False)

    @staticmethod
    def reload_pool():
        """触发代理池重载"""
        import requests
        try:
            url = f"{PoolConfig.get_pool_url()}/__/reload"
            requests.post(url, timeout=5)
            return True
        except Exception as e:
            print(f"重载代理池失败: {e}")
            return False


# --- 核心线程：应用配置 ---
class ApplierThread(QThread):
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, node_data, force_update=False):
        super().__init__()
        self.node_data = node_data
        self.force_update = force_update

    def run(self):
        try:
            current_hash = Utils.get_config_hash(self.node_data)
            last_hash = self.load_last_hash()

            # 检查代理池状态
            self.pool_mode = PoolConfig.is_enabled()

            if self.pool_mode:
                # 代理池模式：更新代理池目标
                if not self.force_update and current_hash == last_hash:
                    self.finished_signal.emit(True, "当前配置已是最新 (无需重复应用)。")
                    return

                # 保存目标配置
                PoolConfig.save_target(self.node_data)

                # 触发代理池重载
                if PoolConfig.reload_pool():
                    # 更新状态和配置文件（使用标准模型名）
                    self.update_json_config()
                    self.save_current_state(current_hash)
                    self.finished_signal.emit(True, "代理池目标已更新！")
                else:
                    self.finished_signal.emit(False, "代理池重载失败，请检查代理池是否正常运行。")
            else:
                # 普通模式：直接修改环境变量
                if not self.force_update and current_hash == last_hash:
                    self.update_process_env()
                    self.finished_signal.emit(True, "当前配置已是最新 (无需重复应用)。")
                    return

                env_vars = {
                    'ANTHROPIC_AUTH_TOKEN': self.node_data.get('api_key', ''),
                    'ANTHROPIC_BASE_URL': self.node_data.get('base_url', 'https://open.bigmodel.cn/api/anthropic'),
                    'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1'
                }

                # 添加代理环境变量
                http_proxy = self.node_data.get('http_proxy', '')
                if http_proxy:
                    env_vars['HTTP_PROXY'] = http_proxy
                    env_vars['HTTPS_PROXY'] = http_proxy

                try:
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Environment', 0, winreg.KEY_ALL_ACCESS)
                    for name, value in env_vars.items():
                        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
                    winreg.CloseKey(key)
                    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0, 1000, 0)
                except Exception as e:
                    raise Exception(f"注册表写入失败: {e}")

                # 更新当前进程
                for name, value in env_vars.items():
                    os.environ[name] = value

                self.update_json_config()
                self.save_current_state(current_hash)
                self.finished_signal.emit(True, "配置应用成功！")

        except Exception as e:
            self.finished_signal.emit(False, str(e))

    def update_process_env(self):
        os.environ['ANTHROPIC_AUTH_TOKEN'] = self.node_data.get('api_key', '')
        os.environ['ANTHROPIC_BASE_URL'] = self.node_data.get('base_url', 'https://open.bigmodel.cn/api/anthropic')
        os.environ['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'

        # 设置代理环境变量
        http_proxy = self.node_data.get('http_proxy', '')
        if http_proxy:
            os.environ['HTTP_PROXY'] = http_proxy
            os.environ['HTTPS_PROXY'] = http_proxy
        else:
            # 清除代理环境变量
            os.environ.pop('HTTP_PROXY', None)
            os.environ.pop('HTTPS_PROXY', None)

    def update_json_config(self):
        if not os.path.exists(CLAUDE_DIR): os.makedirs(CLAUDE_DIR)
        settings_content = {}
        if os.path.exists(CLAUDE_SETTINGS_FILE):
            try:
                with open(CLAUDE_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    settings_content = json.load(f)
            except:
                pass

        if "env" not in settings_content: settings_content["env"] = {}

        # 代理池模式下使用标准 Anthropic 模型名，否则使用节点配置的模型名
        if hasattr(self, 'pool_mode') and self.pool_mode:
            settings_content["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = STANDARD_ANTHROPIC_MODELS['haiku']
            settings_content["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] = STANDARD_ANTHROPIC_MODELS['sonnet']
            settings_content["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] = STANDARD_ANTHROPIC_MODELS['opus']
        else:
            settings_content["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = self.node_data.get('haiku_model', '')
            settings_content["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] = self.node_data.get('sonnet_model', '')
            settings_content["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] = self.node_data.get('opus_model', '')

        with open(CLAUDE_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_content, f, indent=4)

    def load_last_hash(self):
        if not os.path.exists(CURRENT_STATE_FILE): return ""
        try:
            with open(CURRENT_STATE_FILE, 'r') as f:
                return json.load(f).get('hash', "")
        except:
            return ""

    def save_current_state(self, hash_val):
        with open(CURRENT_STATE_FILE, 'w') as f:
            json.dump({'hash': hash_val, 'name': self.node_data.get('name')}, f)


# --- 配置管理 ---
class ConfigManager:
    @staticmethod
    def load_nodes():
        if not os.path.exists(DATA_FILE): return []
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []

    @staticmethod
    def save_nodes(nodes):
        with open(DATA_FILE, 'w', encoding='utf-8') as f: json.dump(nodes, f, indent=4, ensure_ascii=False)


# --- UI组件 ---
class LoadingDialog(QProgressDialog):
    def __init__(self, parent=None):
        super().__init__("正在配置环境...", None, 0, 0, parent)
        self.setWindowTitle("处理中")
        self.setWindowModality(Qt.WindowModal)
        self.setCancelButton(None)
        self.setRange(0, 0)
        self.setStyleSheet("QProgressBar {border: 1px solid grey; border-radius: 5px; text-align: center;}")


# --- 代理生成器弹窗 ---
class ProxyCreatorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建 OpenAI 转 Anthropic 本地代理")
        self.setMinimumWidth(500)
        self.setStyleSheet("""
            QDialog { background-color: #ffffff; }
            QLabel { font-size: 13px; color: #333; }
            QLineEdit, QSpinBox {
                padding: 6px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px;
            }
            QCheckBox { font-size: 13px; padding: 5px; }
        """)

        layout = QVBoxLayout()
        form_layout = QFormLayout()

        # 1. 端口设置
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8888)  # fafafafa

        # 2. 局域网访问开关
        self.lan_check = QCheckBox("允许局域网访问 (0.0.0.0)")
        self.lan_check.setChecked(False)

        # 3. 目标服务器设置
        self.target_url_edit = QLineEdit("https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.target_url_edit.setPlaceholderText("例如: https://dashscope.aliyuncs.com/compatible-mode/v1")

        self.target_key_edit = QLineEdit()
        self.target_key_edit.setPlaceholderText("sk-xxxxxxxxxxxxxxxx")
        self.target_key_edit.setEchoMode(QLineEdit.PasswordEchoOnEdit)

        # 4. 模型映射设置
        self.haiku_edit = QLineEdit()
        self.haiku_edit.setPlaceholderText("快又好的模型例如: glm-4.5-air")

        self.sonnet_edit = QLineEdit()
        self.sonnet_edit.setPlaceholderText("牛逼的模型例如: glm-4.7")

        self.opus_edit = QLineEdit()
        self.opus_edit.setPlaceholderText("牛逼的模型例如: glm-4.7")

        # 5. HTTP代理配置
        self.use_proxy_check = QCheckBox("使用HTTP代理")
        self.use_proxy_check.setChecked(False)
        self.use_proxy_check.stateChanged.connect(self.on_proxy_check_changed)

        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("例如: http://127.0.0.1:7890")
        self.proxy_edit.setVisible(False)

        form_layout.addRow("监听端口:", self.port_spin)
        form_layout.addRow("", self.lan_check)
        form_layout.addRow("目标 URL:", self.target_url_edit)
        form_layout.addRow("API Key:", self.target_key_edit)
        form_layout.addRow("Haiku 映射:", self.haiku_edit)
        form_layout.addRow("Sonnet 映射:", self.sonnet_edit)
        form_layout.addRow("Opus 映射:", self.opus_edit)
        form_layout.addRow("", self.use_proxy_check)
        form_layout.addRow("代理地址:", self.proxy_edit)

        layout.addLayout(form_layout)

        # 按钮
        btn_box = QHBoxLayout()
        create_btn = QPushButton("生成代理并添加节点")
        create_btn.setStyleSheet(
            "background-color: #27ae60; color: white; padding: 8px; border-radius: 4px; font-weight: bold;")
        create_btn.clicked.connect(self.generate_proxy)

        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("padding: 8px;")
        cancel_btn.clicked.connect(self.reject)

        btn_box.addWidget(create_btn)
        btn_box.addWidget(cancel_btn)
        layout.addLayout(btn_box)

        self.setLayout(layout)
        self.node_data = None

    def on_proxy_check_changed(self, state):
        """代理checkbox状态改变时显示/隐藏代理输入框"""
        self.proxy_edit.setVisible(state == Qt.Checked)
        if state == Qt.Checked:
            self.proxy_edit.setFocus()

    def generate_proxy(self):
        port = self.port_spin.value()
        base_url = self.target_url_edit.text().strip()
        api_key = self.target_key_edit.text().strip()

        m_haiku = self.haiku_edit.text().strip()
        m_sonnet = self.sonnet_edit.text().strip()
        m_opus = self.opus_edit.text().strip()

        host_ip = "0.0.0.0" if self.lan_check.isChecked() else "127.0.0.1"

        if not base_url or not api_key:
            QMessageBox.warning(self, "缺少信息", "请填写目标 URL 和 API Key。")
            return

        # 1. 准备目录
        proxy_folder = os.path.join(PROXIES_DIR, f"proxy_{port}")
        if not os.path.exists(proxy_folder):
            os.makedirs(proxy_folder)

        # 2. 生成 Python 脚本 (server.py)
        models_to_config = list(set([m for m in [m_haiku, m_sonnet, m_opus] if m]))

        script_content = f"""
import os
import uvicorn
import yaml
from litellm.proxy.proxy_server import initialize, app as litellm_app
from fastapi import FastAPI

# --- 自动生成的配置 ---
TARGET_API_KEY = "{api_key}"
TARGET_BASE_URL = "{base_url}"
PORT = {port}
HOST = "{host_ip}"
CONFIG_FILE = "litellm_config.yaml"

os.environ["DASHSCOPE_API_KEY"] = TARGET_API_KEY 
os.environ["OPENAI_API_KEY"] = TARGET_API_KEY

target_models = {json.dumps(models_to_config)}
model_list_config = []

for m in target_models:
    model_list_config.append({{
        "model_name": m,
        "litellm_params": {{
            "model": "openai/" + m,
            "api_key": TARGET_API_KEY,
            "api_base": TARGET_BASE_URL
        }}
    }})

model_list_config.append({{
    "model_name": "*",
    "litellm_params": {{
        "model": "openai/*", 
        "api_key": TARGET_API_KEY,
        "api_base": TARGET_BASE_URL
    }}
}})

config_data = {{
    "model_list": model_list_config
}}

app = FastAPI()

async def start_proxy():
    print(f"🚀 代理服务启动中...")
    print(f"📝 配置文件路径: {{os.path.abspath(CONFIG_FILE)}}")
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f)

    print(f"🔗 转发目标: {{TARGET_BASE_URL}}")
    print(f"📡 本地监听: http://{{HOST}}:{{PORT}}")

    await initialize(config=CONFIG_FILE)

app.mount("/", litellm_app)

if __name__ == "__main__":
    @app.on_event("startup")
    async def startup_event():
        await start_proxy()

    uvicorn.run(app, host=HOST, port=PORT)
"""
        try:
            with open(os.path.join(proxy_folder, "server.py"), "w", encoding="utf-8") as f:
                f.write(script_content)

            # 3. 生成启动脚本 (start.bat)
            current_python = sys.executable
            bat_content = f"""@echo off
cd /d "%~dp0"
title ThriftCCSwitch Proxy (Port {port})
echo 正在启动本地代理...
echo 目录: %CD%
echo.
"{current_python}" server.py
pause
"""
            bat_path = os.path.join(proxy_folder, "start_proxy.bat")
            with open(bat_path, "w", encoding="gbk") as f:
                f.write(bat_content)

            # 获取代理配置
            proxy_value = self.proxy_edit.text().strip() if self.use_proxy_check.isChecked() else ''

            self.node_data = {
                'name': f"本地代理 [Port {port}]",
                'api_key': "sk-litellm-proxy",
                'base_url': f"http://127.0.0.1:{port}",
                'haiku_model': m_haiku,
                'sonnet_model': m_sonnet,
                'opus_model': m_opus,
                'http_proxy': proxy_value,
                'proxy_path': bat_path
            }

            QMessageBox.information(self, "生成成功",
                                    f"代理文件已生成！\n位置: {proxy_folder}\n\n注意：使用前请点击新节点上的【运行代理】按钮。")
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "生成失败", str(e))


class NodeEditorDialog(QDialog):
    def __init__(self, parent=None, node_data=None):
        super().__init__(parent)
        self.setWindowTitle("配置节点编辑器")
        self.setMinimumWidth(450)
        self.setStyleSheet("""
            QDialog { background-color: #ffffff; }
            QLabel { color: #333333; font-size: 13px; }
            QLineEdit {
                background-color: #ffffff; color: #333333;
                border: 1px solid #cccccc; border-radius: 4px;
                padding: 6px; font-size: 13px;
            }
            QLineEdit:focus { border: 1px solid #3498db; }
            QCheckBox { font-size: 13px; padding: 5px; }
        """)
        self.node_data = node_data or {}
        layout = QFormLayout()
        self.name_edit = QLineEdit(self.node_data.get('name', '默认配置'))
        self.key_edit = QLineEdit(self.node_data.get('api_key', ''))
        self.key_edit.setPlaceholderText("sk-...")
        self.key_edit.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.url_edit = QLineEdit(self.node_data.get('base_url', 'https://open.bigmodel.cn/api/anthropic'))
        self.haiku_edit = QLineEdit(self.node_data.get('haiku_model', 'glm-4.5-air'))
        self.sonnet_edit = QLineEdit(self.node_data.get('sonnet_model', 'glm-4.7'))
        self.opus_edit = QLineEdit(self.node_data.get('opus_model', 'glm-4.7'))

        # 代理配置
        self.use_proxy_check = QCheckBox("使用HTTP代理")
        self.use_proxy_check.setChecked(bool(self.node_data.get('http_proxy', '')))
        self.use_proxy_check.stateChanged.connect(self.on_proxy_check_changed)

        self.proxy_edit = QLineEdit(self.node_data.get('http_proxy', ''))
        self.proxy_edit.setPlaceholderText("例如: http://127.0.0.1:7890")
        # 初始显示状态
        self.proxy_edit.setVisible(self.use_proxy_check.isChecked())

        layout.addRow("节点名称:", self.name_edit)
        layout.addRow("API Key:", self.key_edit)
        layout.addRow("Base URL:", self.url_edit)
        layout.addRow("Haiku Model:", self.haiku_edit)
        layout.addRow("Sonnet Model:", self.sonnet_edit)
        layout.addRow("Opus Model:", self.opus_edit)
        layout.addRow("", self.use_proxy_check)
        layout.addRow("代理地址:", self.proxy_edit)

        btn_box = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(save_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)
        self.setLayout(layout)

    def on_proxy_check_changed(self, state):
        """代理checkbox状态改变时显示/隐藏代理输入框"""
        self.proxy_edit.setVisible(state == Qt.Checked)
        if state == Qt.Checked:
            self.proxy_edit.setFocus()

    def get_data(self):
        proxy_value = self.proxy_edit.text().strip() if self.use_proxy_check.isChecked() else ''
        return {
            'name': self.name_edit.text(), 'api_key': self.key_edit.text(), 'base_url': self.url_edit.text(),
            'haiku_model': self.haiku_edit.text(), 'sonnet_model': self.sonnet_edit.text(),
            'opus_model': self.opus_edit.text(), 'http_proxy': proxy_value,
            'proxy_path': self.node_data.get('proxy_path', '')
        }


class NodeWidget(QFrame):
    def __init__(self, node_data, parent_window, index, is_active=False):
        super().__init__()
        self.node_data = node_data
        self.parent_window = parent_window
        self.index = index
        self.setFrameShape(QFrame.StyledPanel)

        if is_active:
            bg_color = "#f0fdf4"
            border_style = "2px solid #2ecc71"
            title_color = "#27ae60"
            prefix = "✅ "
        else:
            bg_color = "#ffffff"
            border_style = "2px solid #e0e0e0"
            title_color = "#333333"
            prefix = ""

        self.setStyleSheet(f"""
            NodeWidget {{ background-color: {bg_color}; border: {border_style}; border-radius: 8px; margin-bottom: 8px; }}
            QLabel {{ border: none; background: transparent; }}
        """)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(15, 12, 15, 12)
        main_layout.setSpacing(10)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        name_text = f"{prefix}{node_data.get('name', '未命名')}"
        title = QLabel(name_text)
        title.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {title_color};")

        key_vis = node_data.get('api_key', '')
        if len(key_vis) > 8: key_vis = key_vis[:4] + "****" + key_vis[-4:]

        model_raw = node_data.get('sonnet_model') or "(默认)"
        url_raw = node_data.get('base_url') or ""

        if len(model_raw) > 10:
            model_vis = model_raw[:10] + "..."
        else:
            model_vis = model_raw

        if len(url_raw) > 15:
            url_vis = url_raw[:15] + "..."
        else:
            url_vis = url_raw

        details_text = f"Key: {key_vis}  |  Model: {model_vis}  |  URL: {url_vis}"
        details = QLabel(details_text)
        details.setStyleSheet("color: #7f8c8d; font-size: 11px;")

        info_layout.addWidget(title)
        info_layout.addWidget(details)
        main_layout.addLayout(info_layout, stretch=1)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        def get_btn_style(color, hover_color):
            return f"""
                QPushButton {{ background-color: {color}; color: white; border: none; border-radius: 4px; font-weight: bold; font-size: 12px; }}
                QPushButton:hover {{ background-color: {hover_color}; }}
                QPushButton:disabled {{ background-color: #bdc3c7; color: #fff; }}
            """

        proxy_path = node_data.get('proxy_path', '')
        if proxy_path and os.path.exists(proxy_path):
            run_proxy_btn = QPushButton("🚀 运行代理")
            run_proxy_btn.setFixedSize(80, 32)
            run_proxy_btn.setStyleSheet(get_btn_style("#8e44ad", "#9b59b6"))
            # 托管进程启动
            run_proxy_btn.clicked.connect(lambda: self.run_proxy_script(proxy_path))
            btn_layout.addWidget(run_proxy_btn)

        self.apply_btn = QPushButton("应用")
        self.apply_btn.setFixedSize(60, 32)
        if is_active:
            self.apply_btn.setText("当前")
            self.apply_btn.setEnabled(False)
            self.apply_btn.setStyleSheet(get_btn_style("#bdc3c7", "#bdc3c7"))
        else:
            self.apply_btn.setStyleSheet(get_btn_style("#27ae60", "#2ecc71"))
        self.apply_btn.clicked.connect(self.on_apply_click)

        edit_btn = QPushButton("修改")
        edit_btn.setFixedSize(50, 32)
        edit_btn.setStyleSheet(get_btn_style("#f39c12", "#f1c40f"))
        edit_btn.clicked.connect(self.edit_node)

        copy_btn = QPushButton("复制")
        copy_btn.setFixedSize(50, 32)
        copy_btn.setStyleSheet(get_btn_style("#3498db", "#5dade2"))
        copy_btn.clicked.connect(self.copy_node)

        del_btn = QPushButton("删除")
        del_btn.setFixedSize(50, 32)
        del_btn.setStyleSheet(get_btn_style("#e74c3c", "#ec7063"))
        del_btn.clicked.connect(self.delete_node)

        btn_layout.addWidget(self.apply_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(copy_btn)
        btn_layout.addWidget(del_btn)

        main_layout.addLayout(btn_layout)
        self.setLayout(main_layout)

    def on_apply_click(self):
        self.apply_btn.setEnabled(False)
        self.parent_window.apply_config(self.node_data, self.apply_btn)

    def edit_node(self):
        dialog = NodeEditorDialog(self, self.node_data)
        if dialog.exec_() == QDialog.Accepted:
            self.parent_window.update_node(self.index, dialog.get_data())

    def copy_node(self):
        self.parent_window.duplicate_node(self.index)

    def delete_node(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("确认")
        msg_box.setText("确定要删除此节点吗？")
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.setDefaultButton(QMessageBox.No)

        msg_box.setStyleSheet("""
            QMessageBox { background-color: #ffffff; }
            QLabel { color: #333333; font-size: 13px; }
            QPushButton {
                background-color: #3498db;
                color: white;
                border-radius: 4px;
                padding: 5px 15px;
                min-width: 60px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #2980b9; }
        """)

        if msg_box.exec_() == QMessageBox.Yes:
            self.parent_window.delete_node(self.index)

    def run_proxy_script(self, path):
        try:
            # 从路径解析端口号
            port = self.node_data.get('base_url', '').split(':')[-1].split('/')[0]
            window_title = f"ThriftCCSwitch Proxy (Port {port})"
            # 启动并托管
            p = subprocess.Popen([path], creationflags=subprocess.CREATE_NEW_CONSOLE)
            self.parent_window.register_proxy_process(p, port, window_title)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法启动代理脚本: {e}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(780, 600)

        self.nodes = ConfigManager.load_nodes()
        self.worker = None
        self.loading_dialog = None

        self.proxy_processes = []  # 存储 (Popen对象, 端口号, 窗口标题) 元组

        self.init_ui()

        # [核心修复] 启动时同步环境变量
        self.sync_env_on_startup()

    # [核心修复] 同步环境变量逻辑
    def sync_env_on_startup(self):
        try:
            # 1. 获取当前状态Hash
            active_hash = self.get_active_hash()
            if not active_hash:
                return

            # 2. 找到对应节点
            target_node = None
            for node in self.nodes:
                if Utils.get_config_hash(node) == active_hash:
                    target_node = node
                    break

            # 3. 如果找到了，强制写入当前进程的os.environ
            if target_node:
                env_vars = {
                    'ANTHROPIC_AUTH_TOKEN': target_node.get('api_key', ''),
                    'ANTHROPIC_BASE_URL': target_node.get('base_url', 'https://open.bigmodel.cn/api/anthropic'),
                    'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1'
                }
                for name, value in env_vars.items():
                    os.environ[name] = value

                # 设置代理环境变量
                http_proxy = target_node.get('http_proxy', '')
                if http_proxy:
                    os.environ['HTTP_PROXY'] = http_proxy
                    os.environ['HTTPS_PROXY'] = http_proxy
                else:
                    os.environ.pop('HTTP_PROXY', None)
                    os.environ.pop('HTTPS_PROXY', None)

                # 可选：打印日志或状态栏提示
                # print("Startup: Environment variables synced from active config.")
        except Exception as e:
            print(f"Sync Env Error: {e}")

    def register_proxy_process(self, process, port, window_title):
        self.proxy_processes.append((process, port, window_title))

    def closeEvent(self, event: QCloseEvent):
        # 如果代理池已启用，先恢复环境变量为当前节点配置
        # 防止下次用户打开终端时环境变量指向已关闭的代理池
        if PoolConfig.is_enabled():
            self.restore_env_from_current_node()

        # 终止所有代理进程（包括代理池）
        if self.proxy_processes:
            self.kill_all_proxy_processes()

        # 强制终止代理池进程（通过端口查找）
        self.kill_pool_by_port()

        # 重置代理池状态
        if PoolConfig.is_enabled():
            PoolConfig.set_enabled(False)

        # 强制退出Python进程
        import sys
        sys.exit(0)

    def kill_pool_by_port(self):
        """通过端口查找并终止代理池进程"""
        try:
            import subprocess
            port = PoolConfig.get_port()
            # 使用netstat查找监听该端口的进程
            result = subprocess.run(
                f'netstat -ano | findstr ":{port}" | findstr "LISTENING"',
                shell=True,
                capture_output=True,
                text=True
            )
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            try:
                                subprocess.run(f'taskkill /F /PID {pid}', shell=True, capture_output=True)
                            except:
                                pass
        except Exception as e:
            print(f"通过端口终止代理池失败: {e}")

    def kill_all_proxy_processes(self):
        """终止所有代理进程及其子进程"""
        count = 0
        for p, port, window_title in self.proxy_processes:
            if p.poll() is None:  # 进程还在运行
                try:
                    # 方法1: 使用 psutil 递归终止子进程
                    try:
                        import psutil
                        parent = psutil.Process(p.pid)
                        # 递归终止所有子进程
                        for child in parent.children(recursive=True):
                            try:
                                child.terminate()
                                count += 1
                            except psutil.NoSuchProcess:
                                pass
                        # 终止父进程
                        parent.terminate()
                        count += 1
                    except ImportError:
                        # 如果没有 psutil，使用 taskkill 按窗口标题终止
                        self.kill_by_window_title(window_title)
                        count += 1
                    except psutil.NoSuchProcess:
                        pass
                except Exception as e:
                    print(f"终止代理进程失败: {e}")

        if count > 0:
            print(f"已清理 {count} 个代理进程。")

    def kill_by_window_title(self, window_title):
        """通过窗口标题终止进程（备用方法）"""
        try:
            # 使用 taskkill 按窗口标题查找并终止进程
            # 需要转义特殊字符
            cmd = f'taskkill /FI "WINDOWTITLE eq {window_title}*" /F /T 2>nul'
            subprocess.run(cmd, shell=True, capture_output=True)
        except Exception as e:
            print(f"按窗口标题终止进程失败: {e}")

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        central_widget.setStyleSheet("background-color: #f5f5f5;")
        main_layout = QVBoxLayout(central_widget)

        top_bar = QHBoxLayout()

        def create_top_btn(text, func, color="#3498db"):
            btn = QPushButton(text)
            btn.setMinimumHeight(40)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {color}; color: white; border-radius: 5px; padding: 0 15px; font-weight: bold; }} QPushButton:hover {{ opacity: 0.9; }}")
            btn.clicked.connect(func)
            return btn

        top_bar.addWidget(create_top_btn("＋ 普通配置", self.add_node, "#2980b9"))
        top_bar.addWidget(create_top_btn("🛠️ 新建本地代理", self.create_proxy_node, "#8e44ad"))

        top_bar.addStretch()

        top_bar.addWidget(create_top_btn("查看环境变量", self.view_env, "#7f8c8d"))
        top_bar.addWidget(create_top_btn("📂 Claude目录", self.open_claude_folder, "#2c3e50"))
        top_bar.addWidget(create_top_btn("Switch目录", self.view_config_folder, "#f39c12"))

        main_layout.addLayout(top_bar)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("border: none; background: transparent;")
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignTop)
        self.scroll_area.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll_area)

        # --- 底部状态栏（代理池控制）---
        self.pool_status_bar = QWidget()
        self.pool_status_bar.setStyleSheet("background-color: #e8e8e8; border-top: 1px solid #ccc;")
        pool_bar_layout = QHBoxLayout(self.pool_status_bar)
        pool_bar_layout.setContentsMargins(15, 8, 15, 8)

        # 状态标签
        self.pool_status_label = QLabel("代理池: 已关闭")
        self.pool_status_label.setStyleSheet("font-size: 13px; color: #666; font-weight: bold;")
        pool_bar_layout.addWidget(self.pool_status_label)

        pool_bar_layout.addStretch()

        # 端口配置
        port_label = QLabel("端口:")
        port_label.setStyleSheet("font-size: 13px; color: #555;")
        pool_bar_layout.addWidget(port_label)

        self.pool_port_spin = QSpinBox()
        self.pool_port_spin.setRange(1, 65535)
        self.pool_port_spin.setValue(PoolConfig.get_port())
        self.pool_port_spin.setMinimumWidth(80)
        self.pool_port_spin.setStyleSheet("padding: 4px;")
        self.pool_port_spin.valueChanged.connect(self.on_pool_port_changed)
        pool_bar_layout.addWidget(self.pool_port_spin)

        pool_bar_layout.addSpacing(20)

        # 开关按钮
        self.pool_toggle_btn = QPushButton("开启代理池")
        self.pool_toggle_btn.setFixedSize(110, 32)
        self.pool_toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
        """)
        self.pool_toggle_btn.clicked.connect(self.toggle_pool)
        pool_bar_layout.addWidget(self.pool_toggle_btn)

        # 更新初始状态
        self.update_pool_status_ui()

        main_layout.addWidget(self.pool_status_bar)

        self.refresh_list()

    def get_active_hash(self):
        if not os.path.exists(CURRENT_STATE_FILE): return ""
        try:
            with open(CURRENT_STATE_FILE, 'r') as f:
                return json.load(f).get('hash', "")
        except:
            return ""

    def refresh_list(self):
        # 使用 takeAt 立即移除并删除所有 widget，避免 deleteLater 的异步问题
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        active_hash = self.get_active_hash()

        if not self.nodes:
            self.scroll_layout.addWidget(QLabel("暂无配置"))
        else:
            for idx, node in enumerate(self.nodes):
                node_hash = Utils.get_config_hash(node)
                is_active = (node_hash == active_hash and active_hash != "")
                self.scroll_layout.addWidget(NodeWidget(node, self, idx, is_active))

    def add_node(self):
        dialog = NodeEditorDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.nodes.append(dialog.get_data())
            ConfigManager.save_nodes(self.nodes)
            self.refresh_list()

    def create_proxy_node(self):
        dialog = ProxyCreatorDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            new_node = dialog.node_data
            if new_node:
                self.nodes.append(new_node)
                ConfigManager.save_nodes(self.nodes)
                self.refresh_list()

    def update_node(self, index, new_data):
        old_data = self.nodes[index]
        self.nodes[index] = new_data
        ConfigManager.save_nodes(self.nodes)
        self.refresh_list()

        # 检查是否需要同步到代理池
        if self._should_sync_to_pool(new_data):
            try:
                # 更新代理池目标配置
                PoolConfig.save_target(new_data)

                # 触发代理池热重载
                if PoolConfig.reload_pool():
                    # 静默更新，不弹窗，但可以在状态栏显示
                    print(f"[INFO] 节点配置已同步到代理池: {new_data.get('name')}")
                else:
                    QMessageBox.warning(self, "代理池同步失败",
                        f"节点配置已保存，但同步到代理池失败。\n\n"
                        f"请检查代理池是否正常运行。")
            except Exception as e:
                QMessageBox.warning(self, "代理池同步失败",
                    f"节点配置已保存，但同步到代理池时出错：\n{e}")

    def duplicate_node(self, index):
        new_data = copy.deepcopy(self.nodes[index])
        original_name = new_data.get('name', '未命名')
        new_data['name'] = f"{original_name} [backup]"
        self.nodes.insert(index + 1, new_data)
        ConfigManager.save_nodes(self.nodes)
        self.refresh_list()

    def delete_node(self, index):
        node_to_delete = self.nodes[index]

        # 检查是否是当前激活节点
        active_hash = self.get_active_hash()
        node_hash = Utils.get_config_hash(node_to_delete)

        if active_hash == node_hash:
            # 如果代理池开启，阻止删除
            if PoolConfig.is_enabled():
                QMessageBox.warning(self, "无法删除",
                    f"无法删除当前激活的节点「{node_to_delete.get('name')}」。\n\n"
                    f"请先关闭代理池或切换到其他节点后再删除。")
                return

            # 代理池未开启，允许删除但警告
            reply = QMessageBox.question(self, "确认删除",
                f"「{node_to_delete.get('name')}」是当前激活的节点。\n\n"
                f"删除后需要重新应用其他节点，否则环境变量可能指向不存在的配置。\n\n"
                f"确定要删除吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No)

            if reply == QMessageBox.No:
                return

        # 执行删除
        del self.nodes[index]
        ConfigManager.save_nodes(self.nodes)
        self.refresh_list()

    def apply_config(self, node_data, source_btn):
        self.loading_dialog = LoadingDialog(self)
        self.loading_dialog.show()
        self.worker = ApplierThread(node_data)
        self.worker.finished_signal.connect(lambda s, m: self.on_apply_finished(s, m, source_btn))
        self.worker.start()

    def on_apply_finished(self, success, message, source_btn):
        if self.loading_dialog: self.loading_dialog.close()
        if source_btn: source_btn.setEnabled(True)
        self.refresh_list()
        if success:
            if "无需重复" not in message:
                msg = f"{message}\n\n提示：重新打开终端后环境变量生效"
                QMessageBox.information(self, "成功", msg)
        else:
            QMessageBox.critical(self, "错误", message)

    def view_env(self):
        ps_script = """
        $manual_cmd = "Get-ChildItem Env:ANTHROPIC*"
        Write-Host '=====================================================' -ForegroundColor Yellow
        Write-Host '   手动验证命令 (可复制):' -ForegroundColor Yellow
        Write-Host "   $manual_cmd" -ForegroundColor White
        Write-Host '=====================================================' -ForegroundColor Yellow
        Write-Host ''

        Write-Host '--- [1] 当前进程视角 (Process View) ---' -ForegroundColor Cyan
        Write-Host '说明: 这是当前软件和由它启动的子程序能看到的变量' -ForegroundColor DarkGray
        Get-ChildItem Env:ANTHROPIC*
        Get-ChildItem Env:CLAUDE*

        Write-Host ''
        Write-Host '--- [2] 注册表永久视角 (Registry View) ---' -ForegroundColor Green
        Write-Host '说明: 这是新开CMD/PowerShell或重启Claude后生效的变量' -ForegroundColor DarkGray
        $keys = @('ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC')
        foreach ($k in $keys) {
            $val = [System.Environment]::GetEnvironmentVariable($k, 'User')
            if ($val) { Write-Host "$k = $val" } else { Write-Host "$k = (未设置)" -ForegroundColor DarkGray }
        }

        Write-Host ''
        Read-Host '按回车键关闭...'
        """
        cmd = f'powershell -NoProfile -Command "& {{ {ps_script} }}"'
        try:
            subprocess.Popen(cmd, creationflags=16, env=os.environ)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开PowerShell: {e}")

    def view_config_folder(self):
        if not os.path.exists(APP_DIR): os.makedirs(APP_DIR)
        os.startfile(APP_DIR)

    def open_claude_folder(self):
        if not os.path.exists(CLAUDE_DIR): os.makedirs(CLAUDE_DIR)
        os.startfile(CLAUDE_DIR)

    # --- 代理池相关方法 ---

    def update_pool_status_ui(self):
        """更新代理池状态UI"""
        # 检查端口是否真的在监听
        port = PoolConfig.get_port()
        is_running = self.check_pool_running(port)

        # 更新状态显示
        if is_running:
            self.pool_status_label.setText("代理池: 运行中 ✓")
            self.pool_status_label.setStyleSheet("font-size: 13px; color: #27ae60; font-weight: bold;")
            self.pool_toggle_btn.setText("关闭代理池")
            self.pool_toggle_btn.setStyleSheet("""
                QPushButton {
                    background-color: #e74c3c;
                    color: white;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #c0392b;
                }
            """)
            self.pool_port_spin.setEnabled(False)
            # 确保配置文件状态正确
            if not PoolConfig.is_enabled():
                PoolConfig.set_enabled(True)
        else:
            self.pool_status_label.setText("代理池: 已关闭")
            self.pool_status_label.setStyleSheet("font-size: 13px; color: #666; font-weight: bold;")
            self.pool_toggle_btn.setText("开启代理池")
            self.pool_toggle_btn.setStyleSheet("""
                QPushButton {
                    background-color: #27ae60;
                    color: white;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #2ecc71;
                }
            """)
            self.pool_port_spin.setEnabled(True)
            # 确保配置文件状态正确
            if PoolConfig.is_enabled():
                PoolConfig.set_enabled(False)

    def check_pool_running(self, port):
        """检查代理池端口是否在监听"""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            return result == 0
        except:
            return False

    def on_pool_port_changed(self, port):
        """端口配置变化"""
        PoolConfig.set_port(port)

    def toggle_pool(self):
        """切换代理池状态"""
        # 防抖：检查是否正在操作中
        if hasattr(self, '_pool_operating') and self._pool_operating:
            return

        if PoolConfig.is_enabled():
            self.stop_pool()
        else:
            self.start_pool()

    def start_pool(self):
        """启动代理池"""
        # 防抖：设置操作中标志
        self._pool_operating = True

        try:
            # 获取当前激活的节点
            active_hash = self.get_active_hash()
            if not active_hash:
                QMessageBox.warning(self, "提示", "请先应用一个配置节点后再开启代理池。")
                return

            # 找到激活的节点
            current_node = None
            for node in self.nodes:
                if Utils.get_config_hash(node) == active_hash:
                    current_node = node
                    break

            if not current_node:
                QMessageBox.warning(self, "提示", "找不到当前激活的节点，请先应用一个配置。")
                return

            # 保存目标配置
            PoolConfig.save_target(current_node)

            # 启动代理池服务
            port = PoolConfig.get_port()
            server_script = os.path.join(os.path.dirname(__file__), 'pool_server.py')

            # 生成启动脚本
            pool_dir = os.path.join(PROXIES_DIR, 'pool')
            if not os.path.exists(pool_dir):
                os.makedirs(pool_dir)

            bat_content = f"""@echo off
cd /d "{os.path.dirname(__file__)}"
"{sys.executable}" "{server_script}" --port {port} 2> error.log
"""
            bat_path = os.path.join(pool_dir, 'start_pool.bat')
            with open(bat_path, 'w', encoding='gbk') as f:
                f.write(bat_content)

            # 使用 subprocess 启动，隐藏窗口（后台运行）
            p = subprocess.Popen(
                ['cmd', '/c', bat_path],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            # 注册代理池进程
            self.register_proxy_process(p, port, "ThriftCCSwitch-Pool")

            # 等待服务启动
            import time
            time.sleep(3)

            # 检查进程是否还在运行
            if p.poll() is not None:
                # 读取错误日志
                error_log = os.path.join(pool_dir, 'error.log')
                error_msg = ""
                if os.path.exists(error_log):
                    try:
                        with open(error_log, 'r', encoding='utf-8') as f:
                            error_msg = f.read()
                    except:
                        pass

                QMessageBox.warning(self, "启动失败",
                    f"代理池服务启动后立即退出。\n\n"
                    f"可能原因：\n"
                    f"1. 缺少依赖（运行: pip install -r requirements.txt）\n"
                    f"2. 端口 {port} 被占用\n"
                    f"3. 配置文件错误\n\n"
                    f"错误信息：\n{error_msg if error_msg else '(无法读取错误日志)'}"
                )
                PoolConfig.set_enabled(False)
                self.update_pool_status_ui()
                return

            # 设置代理池为启用状态
            PoolConfig.set_enabled(True)

            # 应用代理池配置到环境变量
            self.apply_pool_config_to_env(current_node)

            # 更新 settings.json 为标准模型名
            self.update_pool_settings_json()

            self.update_pool_status_ui()

            QMessageBox.information(self, "成功",
                f"代理池已启动（后台运行）！\n\n"
                f"端口: {port}\n"
                f"地址: http://127.0.0.1:{port}\n"
                f"Key: {PoolConfig.get_key()}\n\n"
                f"环境变量已指向代理池。"
            )

        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动代理池失败: {e}")
        finally:
            # 清除操作中标志
            self._pool_operating = False

    def stop_pool(self):
        """停止代理池"""
        # 防抖：设置操作中标志
        self._pool_operating = True

        try:
            # 终止代理池进程
            self.kill_pool_process()

            # 设置代理池为禁用状态
            PoolConfig.set_enabled(False)

            # 恢复环境变量为当前节点
            self.restore_env_from_current_node()

            self.update_pool_status_ui()

            QMessageBox.information(self, "提示", "代理池已关闭，环境变量已恢复为当前节点配置。")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"关闭代理池失败: {e}")
        finally:
            # 清除操作中标志
            self._pool_operating = False

    def apply_pool_config_to_env(self, node_data):
        """将代理池配置应用到环境变量"""
        try:
            env_vars = {
                'ANTHROPIC_AUTH_TOKEN': PoolConfig.get_key(),
                'ANTHROPIC_BASE_URL': PoolConfig.get_pool_url(),
                'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1'
            }

            # 写入注册表
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Environment', 0, winreg.KEY_ALL_ACCESS)
            for name, value in env_vars.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            winreg.CloseKey(key)
            ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0, 1000, 0)

            # 更新当前进程环境变量
            for name, value in env_vars.items():
                os.environ[name] = value

        except Exception as e:
            raise Exception(f"环境变量设置失败: {e}")

    def update_pool_settings_json(self):
        """更新 settings.json 为标准 Anthropic 模型名（代理池模式）"""
        try:
            if not os.path.exists(CLAUDE_DIR):
                os.makedirs(CLAUDE_DIR)

            settings_content = {}
            if os.path.exists(CLAUDE_SETTINGS_FILE):
                try:
                    with open(CLAUDE_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                        settings_content = json.load(f)
                except:
                    pass

            if "env" not in settings_content:
                settings_content["env"] = {}

            # 使用标准 Anthropic 模型名
            settings_content["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = STANDARD_ANTHROPIC_MODELS['haiku']
            settings_content["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] = STANDARD_ANTHROPIC_MODELS['sonnet']
            settings_content["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] = STANDARD_ANTHROPIC_MODELS['opus']

            with open(CLAUDE_SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(settings_content, f, indent=4)

        except Exception as e:
            print(f"更新 settings.json 失败: {e}")

    def restore_env_from_current_node(self):
        """从当前节点恢复环境变量"""
        try:
            active_hash = self.get_active_hash()
            if not active_hash:
                return

            # 找到激活的节点
            current_node = None
            for node in self.nodes:
                if Utils.get_config_hash(node) == active_hash:
                    current_node = node
                    break

            if not current_node:
                return

            # 恢复节点配置到环境变量
            env_vars = {
                'ANTHROPIC_AUTH_TOKEN': current_node.get('api_key', ''),
                'ANTHROPIC_BASE_URL': current_node.get('base_url', ''),
                'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1'
            }

            # 写入注册表
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Environment', 0, winreg.KEY_ALL_ACCESS)
            for name, value in env_vars.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            winreg.CloseKey(key)
            ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0, 1000, 0)

            # 更新当前进程环境变量
            for name, value in env_vars.items():
                os.environ[name] = value

        except Exception as e:
            print(f"恢复环境变量失败: {e}")

    def _should_sync_to_pool(self, node_data):
        """判断是否需要同步到代理池"""
        if not PoolConfig.is_enabled():
            return False

        # 获取当前激活节点的 hash
        active_hash = self.get_active_hash()
        if not active_hash:
            return False

        # 计算当前节点的 hash
        current_hash = Utils.get_config_hash(node_data)

        # 如果是同一个节点，需要同步
        return active_hash == current_hash

    def kill_pool_process(self):
        """终止代理池进程"""
        for i, (p, port, title) in enumerate(self.proxy_processes[:]):
            if "Pool" in title and p.poll() is None:
                try:
                    import psutil
                    parent = psutil.Process(p.pid)
                    for child in parent.children(recursive=True):
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    parent.terminate()
                    self.proxy_processes.remove((p, port, title))
                except Exception as e:
                    print(f"终止代理池进程失败: {e}")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 9))
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
