import sys
import os
import json
import subprocess
import winreg
import ctypes
import hashlib
import copy
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


# --- [新增] 工具类：用于统一计算哈希 ---
class Utils:
    @staticmethod
    def get_config_hash(data):
        """计算配置字典的MD5哈希，用于比对配置是否一致"""
        # 仅取关键字段参与计算，避免UI相关字段干扰
        clean_data = {k: data.get(k) for k in [
            'api_key', 'base_url', 'haiku_model', 'sonnet_model', 'opus_model'
        ]}
        s = json.dumps(clean_data, sort_keys=True)
        return hashlib.md5(s.encode('utf-8')).hexdigest()


# --- 核心修复：应用配置线程 ---

class ApplierThread(QThread):
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, node_data, force_update=False):
        super().__init__()
        self.node_data = node_data
        self.force_update = force_update

    def run(self):
        try:
            # 1. 检查哈希去重 [修改：使用Utils类]
            current_hash = Utils.get_config_hash(self.node_data)
            last_hash = self.load_last_hash()

            if not self.force_update and current_hash == last_hash:
                self.update_process_env()
                self.finished_signal.emit(True, "当前配置已是最新 (无需重复应用)。")
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

                ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0, 1000, 0)
            except Exception as e:
                raise Exception(f"注册表写入失败: {e}")

            # 4. 同步更新当前 Python 进程的环境变量
            for name, value in env_vars.items():
                os.environ[name] = value

            # 5. 修改 settings.json
            self.update_json_config()

            # 6. 保存状态
            self.save_current_state(current_hash)

            self.finished_signal.emit(True, "配置应用成功！")

        except Exception as e:
            self.finished_signal.emit(False, str(e))

    def update_process_env(self):
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


# --- ConfigManager 和 LoadingDialog ---
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


# --- NodeEditorDialog ---
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


# --- NodeWidget [修改：增加高亮样式逻辑] ---
# --- NodeWidget [已修复：布局防抖动 + 修改按钮美化] ---
class NodeWidget(QFrame):
    def __init__(self, node_data, parent_window, index, is_active=False):
        super().__init__()
        self.node_data = node_data
        self.parent_window = parent_window
        self.index = index
        self.setFrameShape(QFrame.StyledPanel)

        # 1. 样式定义：激活状态 vs 普通状态
        # 为了防止边框宽度变化(1px->2px)导致微小的抖动，我们在普通状态下也设置2px边框，但是颜色设为浅灰色或透明
        if is_active:
            # 激活：浅绿背景，绿色粗边框
            bg_color = "#f0fdf4"
            border_style = "2px solid #2ecc71"
            title_color = "#27ae60"
            prefix = "✅ "  # 仅加一个短图标，不加长文字，防止换行
        else:
            # 普通：白色背景，灰色细边框 (设为2px但颜色浅，保持占位一致)
            bg_color = "#ffffff"
            border_style = "2px solid #e0e0e0"
            title_color = "#333333"
            prefix = ""

        self.setStyleSheet(f"""
            NodeWidget {{
                background-color: {bg_color};
                border: {border_style};
                border-radius: 8px;
                margin-bottom: 8px;
            }}
            QLabel {{ border: none; background: transparent; }}
        """)

        # 2. 布局初始化
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(15, 12, 15, 12)  # 增加一点内边距，更美观
        main_layout.setSpacing(10)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        # 标题部分
        name_text = f"{prefix}{node_data.get('name', '未命名')}"
        title = QLabel(name_text)
        # 字体稍微加大加粗
        title.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {title_color};")

        # 详情部分
        key_vis = node_data.get('api_key', '')
        if len(key_vis) > 8: key_vis = key_vis[:4] + "****" + key_vis[-4:]
        details_text = f"Key: {key_vis}  |  Model: {node_data.get('sonnet_model', '-')}"
        details = QLabel(details_text)
        details.setStyleSheet("color: #7f8c8d; font-size: 11px;")

        info_layout.addWidget(title)
        info_layout.addWidget(details)
        main_layout.addLayout(info_layout, stretch=1)  # stretch=1 让文字部分占据剩余空间

        # 3. 按钮组
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        # 通用按钮样式函数
        def get_btn_style(color, hover_color):
            return f"""
                QPushButton {{
                    background-color: {color};
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 12px;
                }}
                QPushButton:hover {{ background-color: {hover_color}; }}
                QPushButton:pressed {{ background-color: {color}; opacity: 0.8; }}
                QPushButton:disabled {{ background-color: #bdc3c7; color: #fff; }}
            """

        # [应用] 按钮 (绿色)
        self.apply_btn = QPushButton("应用")
        self.apply_btn.setFixedSize(60, 32)
        if is_active:
            self.apply_btn.setText("当前")
            self.apply_btn.setEnabled(False)
            self.apply_btn.setStyleSheet(get_btn_style("#bdc3c7", "#bdc3c7"))  # 灰色
        else:
            self.apply_btn.setStyleSheet(get_btn_style("#27ae60", "#2ecc71"))
        self.apply_btn.clicked.connect(self.on_apply_click)

        # [修改] 按钮 (橙色 - 新增样式)
        edit_btn = QPushButton("修改")
        edit_btn.setFixedSize(50, 32)
        edit_btn.setStyleSheet(get_btn_style("#f39c12", "#f1c40f"))
        edit_btn.clicked.connect(self.edit_node)

        # [复制] 按钮 (蓝色)
        copy_btn = QPushButton("复制")
        copy_btn.setFixedSize(50, 32)
        copy_btn.setStyleSheet(get_btn_style("#3498db", "#5dade2"))
        copy_btn.clicked.connect(self.copy_node)

        # [删除] 按钮 (红色)
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
        if QMessageBox.question(self, "确认", "删除此节点？", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.parent_window.delete_node(self.index)


# --- MainWindow ---

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

    # [新增] 读取当前激活的配置Hash
    def get_active_hash(self):
        if not os.path.exists(CURRENT_STATE_FILE):
            return ""
        try:
            with open(CURRENT_STATE_FILE, 'r') as f:
                data = json.load(f)
                return data.get('hash', "")
        except:
            return ""

    # [修改] 刷新列表时比对Hash
    def refresh_list(self):
        for i in range(self.scroll_layout.count()):
            item = self.scroll_layout.itemAt(i)
            if item.widget(): item.widget().deleteLater()

        active_hash = self.get_active_hash()

        if not self.nodes:
            self.scroll_layout.addWidget(QLabel("暂无配置"))
        else:
            for idx, node in enumerate(self.nodes):
                # 计算当前节点Hash
                node_hash = Utils.get_config_hash(node)
                is_active = (node_hash == active_hash and active_hash != "")

                # 传入 is_active 参数
                self.scroll_layout.addWidget(NodeWidget(node, self, idx, is_active))

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

    def duplicate_node(self, index):
        new_data = copy.deepcopy(self.nodes[index])
        original_name = new_data.get('name', '未命名')
        new_data['name'] = f"{original_name} [backup]"
        self.nodes.insert(index + 1, new_data)
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

        # [修改] 无论成功失败，都刷新列表以更新“当前启用”的状态显示
        self.refresh_list()

        if success:
            if "无需重复" not in message: QMessageBox.information(self, "成功", message)
        else:
            QMessageBox.critical(self, "错误", message)

    def view_env(self):
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

        cmd = f'powershell -NoProfile -Command "& {{ {ps_script} }}"'

        try:
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