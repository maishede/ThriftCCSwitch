import sys
import os
import json
import subprocess
import winreg
import ctypes
import hashlib
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QDialog, QFormLayout, QLineEdit, QMessageBox, QFrame,
                             QProgressDialog)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont

# --- 全局配置 ---
APP_NAME = "ThriftCCSwitch"
APPDATA = os.getenv('APPDATA')
USER_PROFILE = os.path.expanduser('~')
APP_DIR = os.path.join(APPDATA, '.ThriftCCSwitch')
DATA_FILE = os.path.join(APP_DIR, 'nodes.json')
CURRENT_STATE_FILE = os.path.join(APP_DIR, 'current_state.json')

CLAUDE_DIR = os.path.join(USER_PROFILE, '.claude')
CLAUDE_SETTINGS_FILE = os.path.join(CLAUDE_DIR, 'settings.json')

if not os.path.exists(APP_DIR):
    os.makedirs(APP_DIR)


# --- 核心修复：应用配置线程 ---

class ApplierThread(QThread):
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, node_data, force_update=False):
        super().__init__()
        self.node_data = node_data
        self.force_update = force_update

    def run(self):
        try:
            # 1. 检查哈希去重
            current_hash = self.get_config_hash(self.node_data)
            last_hash = self.load_last_hash()

            if not self.force_update and current_hash == last_hash:
                # 即使哈希没变，为了保险起见，也更新一下当前进程的 os.environ
                # 这样可以防止用户手动改了环境后软件没感知
                self.update_process_env()
                self.finished_signal.emit(True, "当前配置已是最新 (进程环境已同步)。")
                return

            # 2. 准备变量
            env_vars = {
                'ANTHROPIC_AUTH_TOKEN': self.node_data.get('api_key', ''),
                'ANTHROPIC_BASE_URL': self.node_data.get('base_url', 'https://open.bigmodel.cn/api/anthropic'),
                'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1'
            }

            # 3. 修改注册表 (永久生效)
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Environment', 0, winreg.KEY_ALL_ACCESS)
                for name, value in env_vars.items():
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
                winreg.CloseKey(key)

                # 广播消息
                ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0, 1000, 0)
            except Exception as e:
                raise Exception(f"注册表写入失败: {e}")

            # 4. 【关键修复】同步更新当前 Python 进程的环境变量
            # 这样后续 spawn 的 PowerShell 子进程才会继承最新的值
            for name, value in env_vars.items():
                os.environ[name] = value

            # 5. 修改 settings.json
            self.update_json_config()

            # 6. 保存状态
            self.save_current_state(current_hash)

            self.finished_signal.emit(True, "配置应用成功！\n(注册表与当前进程环境均已更新)")

        except Exception as e:
            self.finished_signal.emit(False, str(e))

    def update_process_env(self):
        """辅助方法：仅更新当前进程内存中的环境"""
        os.environ['ANTHROPIC_AUTH_TOKEN'] = self.node_data.get('api_key', '')
        os.environ['ANTHROPIC_BASE_URL'] = self.node_data.get('base_url', 'https://open.bigmodel.cn/api/anthropic')
        os.environ['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'

    def update_json_config(self):
        if not os.path.exists(CLAUDE_DIR):
            os.makedirs(CLAUDE_DIR)

        settings_content = {}
        if os.path.exists(CLAUDE_SETTINGS_FILE):
            try:
                with open(CLAUDE_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    settings_content = json.load(f)
            except:
                settings_content = {}

        if "env" not in settings_content:
            settings_content["env"] = {}

        settings_content["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = self.node_data.get('haiku_model', 'glm-4.5-air')
        settings_content["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] = self.node_data.get('sonnet_model', 'glm-4.7')
        settings_content["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] = self.node_data.get('opus_model', 'glm-4.7')

        with open(CLAUDE_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings_content, f, indent=4)

    def get_config_hash(self, data):
        s = json.dumps(data, sort_keys=True)
        return hashlib.md5(s.encode('utf-8')).hexdigest()

    def load_last_hash(self):
        if not os.path.exists(CURRENT_STATE_FILE):
            return ""
        try:
            with open(CURRENT_STATE_FILE, 'r') as f:
                data = json.load(f)
                return data.get('hash', "")
        except:
            return ""

    def save_current_state(self, hash_val):
        with open(CURRENT_STATE_FILE, 'w') as f:
            json.dump({'hash': hash_val, 'name': self.node_data.get('name')}, f)


# --- ConfigManager 和 LoadingDialog 保持不变 ---
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


class LoadingDialog(QProgressDialog):
    def __init__(self, parent=None):
        super().__init__("正在配置环境...", None, 0, 0, parent)
        self.setWindowTitle("处理中")
        self.setWindowModality(Qt.WindowModal)
        self.setCancelButton(None)
        self.setRange(0, 0)
        self.setStyleSheet("QProgressBar {border: 1px solid grey; border-radius: 5px; text-align: center;}")


# --- NodeEditorDialog 保持不变 (略) ---
class NodeEditorDialog(QDialog):
    def __init__(self, parent=None, node_data=None):
        super().__init__(parent)
        self.setWindowTitle("配置节点编辑器")
        self.setMinimumWidth(450)
        self.setStyleSheet("""
                    QDialog {
                        background-color: #ffffff;
                    }
                    QLabel {
                        color: #333333;
                        font-size: 13px;
                    }
                    QLineEdit {
                        background-color: #ffffff;
                        color: #333333;
                        border: 1px solid #cccccc;
                        border-radius: 4px;
                        padding: 6px;
                        font-size: 13px;
                    }
                    QLineEdit:focus {
                        border: 1px solid #3498db;
                    }
                """)
        self.node_data = node_data or {}
        layout = QFormLayout()
        self.name_edit = QLineEdit(self.node_data.get('name', '默认配置'))
        self.key_edit = QLineEdit(self.node_data.get('api_key', ''))
        self.key_edit.setPlaceholderText("your_zhipu_api_key")
        self.key_edit.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.url_edit = QLineEdit(self.node_data.get('base_url', 'https://open.bigmodel.cn/api/anthropic'))
        self.haiku_edit = QLineEdit(self.node_data.get('haiku_model', 'glm-4.5-air'))
        self.sonnet_edit = QLineEdit(self.node_data.get('sonnet_model', 'glm-4.7'))
        self.opus_edit = QLineEdit(self.node_data.get('opus_model', 'glm-4.7'))
        layout.addRow("节点名称:", self.name_edit)
        layout.addRow("API Key:", self.key_edit)
        layout.addRow("Base URL:", self.url_edit)
        layout.addRow("Haiku Model:", self.haiku_edit)
        layout.addRow("Sonnet Model:", self.sonnet_edit)
        layout.addRow("Opus Model:", self.opus_edit)
        btn_box = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(save_btn)
        btn_box.addWidget(cancel_btn)
        layout.addRow(btn_box)
        self.setLayout(layout)

    def get_data(self):
        return {
            'name': self.name_edit.text(), 'api_key': self.key_edit.text(), 'base_url': self.url_edit.text(),
            'haiku_model': self.haiku_edit.text(), 'sonnet_model': self.sonnet_edit.text(),
            'opus_model': self.opus_edit.text()
        }


# --- NodeWidget 保持不变 (略) ---
class NodeWidget(QFrame):
    def __init__(self, node_data, parent_window, index):
        super().__init__()
        self.node_data = node_data
        self.parent_window = parent_window
        self.index = index
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "NodeWidget { background-color: #fff; border: 1px solid #ddd; border-radius: 6px; margin-bottom: 8px; }")
        main_layout = QHBoxLayout()
        info_layout = QVBoxLayout()
        title = QLabel(node_data.get('name', '未命名'))
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        key_vis = node_data.get('api_key', '')
        if len(key_vis) > 8: key_vis = key_vis[:4] + "****" + key_vis[-4:]
        details = QLabel(f"Key: {key_vis} | Model: {node_data.get('sonnet_model')}")
        details.setStyleSheet("color: #666; font-size: 11px;")
        info_layout.addWidget(title)
        info_layout.addWidget(details)
        main_layout.addLayout(info_layout)
        btn_layout = QHBoxLayout()
        self.apply_btn = QPushButton("应用")
        self.apply_btn.setStyleSheet("background-color: #27ae60; color: white; border-radius: 4px; padding: 5px;")
        self.apply_btn.setFixedSize(60, 30)
        self.apply_btn.clicked.connect(self.on_apply_click)
        edit_btn = QPushButton("修改")
        edit_btn.setFixedSize(50, 30)
        edit_btn.clicked.connect(self.edit_node)
        del_btn = QPushButton("删除")
        del_btn.setStyleSheet("background-color: #e74c3c; color: white; border-radius: 4px;")
        del_btn.setFixedSize(50, 30)
        del_btn.clicked.connect(self.delete_node)
        btn_layout.addWidget(self.apply_btn)
        btn_layout.addWidget(edit_btn)
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

    def delete_node(self):
        if QMessageBox.question(self, "确认", "删除此节点？", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.parent_window.delete_node(self.index)


# --- MainWindow 修复 view_env ---

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(650, 550)

        self.nodes = ConfigManager.load_nodes()
        self.worker = None
        self.loading_dialog = None

        self.init_ui()

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
                f"QPushButton {{ background-color: {color}; color: white; border-radius: 5px; padding: 0 15px; }} QPushButton:hover {{ opacity: 0.9; }}")
            btn.clicked.connect(func)
            return btn

        top_bar.addWidget(create_top_btn("＋ 添加新配置", self.add_node, "#2980b9"))
        top_bar.addStretch()
        top_bar.addWidget(create_top_btn("查看环境变量", self.view_env, "#8e44ad"))
        top_bar.addWidget(create_top_btn("打开配置文件夹", self.view_config_folder, "#f39c12"))
        main_layout.addLayout(top_bar)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("border: none; background: transparent;")
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignTop)
        self.scroll_area.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll_area)

        self.refresh_list()

    def refresh_list(self):
        for i in range(self.scroll_layout.count()):
            item = self.scroll_layout.itemAt(i)
            if item.widget(): item.widget().deleteLater()

        if not self.nodes:
            self.scroll_layout.addWidget(QLabel("暂无配置"))
        else:
            for idx, node in enumerate(self.nodes):
                self.scroll_layout.addWidget(NodeWidget(node, self, idx))

    def add_node(self):
        dialog = NodeEditorDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.nodes.append(dialog.get_data())
            ConfigManager.save_nodes(self.nodes)
            self.refresh_list()

    def update_node(self, index, new_data):
        self.nodes[index] = new_data
        ConfigManager.save_nodes(self.nodes)
        self.refresh_list()

    def delete_node(self, index):
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
        if success:
            if "无需重复" not in message: QMessageBox.information(self, "成功", message)
        else:
            QMessageBox.critical(self, "错误", message)

    def view_env(self):
        # 优化后的查看命令：同时显示当前进程视角和系统注册表视角，方便排查
        ps_script = """
        Write-Host '==========================================' -ForegroundColor Cyan
        Write-Host '   当前查看器进程视角 (Process View)' -ForegroundColor Cyan
        Write-Host '==========================================' -ForegroundColor Cyan
        Get-ChildItem Env:ANTHROPIC*
        Get-ChildItem Env:CLAUDE*

        Write-Host ''
        Write-Host '==========================================' -ForegroundColor Green
        Write-Host '   Windows 注册表视角 (Registry View)' -ForegroundColor Green
        Write-Host '==========================================' -ForegroundColor Green
        $keys = @('ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC')
        foreach ($k in $keys) {
            $val = [System.Environment]::GetEnvironmentVariable($k, 'User')
            Write-Host "$k = $val"
        }

        Write-Host ''
        Read-Host '按回车键关闭...'
        """

        # 将多行脚本转为单行 Base64 编码，避免特殊字符问题 (更稳健的方式)
        # 这里简单起见，使用 -Command 和分号拼接，但为了显示效果，我们构造一个临时文件也行
        # 或者直接传递清晰的 Command

        cmd = f'powershell -NoProfile -Command "& {{ {ps_script} }}"'

        try:
            # 传入当前更新过的 os.environ，确保"进程视角"是新的
            subprocess.Popen(cmd, creationflags=16, env=os.environ)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法打开PowerShell: {e}")

    def view_config_folder(self):
        if not os.path.exists(CLAUDE_DIR): os.makedirs(CLAUDE_DIR)
        os.startfile(CLAUDE_DIR)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 9))
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
