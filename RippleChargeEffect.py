import sys
import os
import json
import ctypes
import subprocess
import ast
import winreg
import traceback
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QComboBox, QCheckBox,
                             QPushButton, QTabWidget, QSystemTrayIcon, QMenu, QAction,
                             QMessageBox, QScrollArea, QFormLayout, QGridLayout, QSizePolicy)
from PyQt5.QtGui import QIcon, QDesktopServices
from PyQt5.QtCore import QTimer, Qt, QUrl
import multiprocessing

class ProcessWrapper:
    def __init__(self, target, args=(), kwargs={}):
        self.start_event = multiprocessing.Event() # 用于通知进程开始动画
        self.process = multiprocessing.Process(
            target=target, 
            args=(self.start_event, *args), 
            kwargs=kwargs, 
            daemon=True
        )
        self.process.start()

    def trigger(self):
        self.start_event.set()

    def poll(self):
        if self.process.is_alive():
            return None
        return self.process.exitcode

    def kill(self):
        self.process.terminate()
        self.process.join()

class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_byte),
        ("BatteryFlag", ctypes.c_byte),
        ("BatteryLifePercent", ctypes.c_byte),
        ("SystemStatusFlag", ctypes.c_byte),
        ("BatteryLifeTime", ctypes.c_ulong),
        ("BatteryFullLifeTime", ctypes.c_ulong),
    ]

def get_ac_line_status():
    status = SYSTEM_POWER_STATUS()
    if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return status.ACLineStatus
    return 255

class ConfigWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.i18n = {}
        self.current_lang = "zh-CN"
        self.current_icon = 2
        self.init_language()

        self.setWindowTitle(self.t("ui.title", "充电动画配置"))
        window_size = (450, 480)
        self.resize(*window_size)  # 设置窗口大小
        self.setMinimumSize(*window_size)  # 设置窗口的最小尺寸
        self.setWindowIcon(QIcon(os.path.join("assets", "app.ico")))
        
        # 托盘图标设置
        self.tray_icon = QSystemTrayIcon(self)
        self.apply_tray_icon()
        self.tray_icon.activated.connect(self.on_tray_activated)
        
        self.build_tray_menu()
        self.tray_icon.show()
        
        self.is_modified = False
        self.main_vbox = QVBoxLayout()
        
        central_widget = QWidget()
        central_widget.setLayout(self.main_vbox)
        self.setCentralWidget(central_widget)
        
        # 建立界面
        self.build_ui()
        
        # 电量监控 (1秒检查一次)
        self.last_status = get_ac_line_status()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_power)
        self.timer.start(1000)
        
        self.test_process = None

        self.prepare_cache()

    def prepare_cache(self):
        """预创建一个等待信号的动画进程"""
        if hasattr(self, 'cached_process') and self.cached_process:
            if self.cached_process.poll() is None:
                return # 已经有缓存了
        self.cached_process = self.start_main_process()

    def init_language(self):
        try:
            with open("config.json", "r", encoding='utf-8') as f:
                cfg = json.load(f)
                self.current_lang = cfg.get("language", "zh-CN")
                self.current_icon = cfg.get("tray_icon_color", 2)
        except:
            pass
        self.load_i18n(self.current_lang)

    def apply_tray_icon(self):
        icon_map = {
            0: "app.ico",
            1: "tray_b.ico",
            2: "tray_w.ico"
        }
        icon_name = icon_map.get(self.current_icon, "app.ico")
        icon_path = os.path.join("assets", icon_name)
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            self.tray_icon.setIcon(QIcon("app.ico"))

    def load_i18n(self, lang):
        self.i18n = {}
        # 先尝试加载英文作为 fallback 底层
        en_p = os.path.join("languages", "en.json")
        if os.path.exists(en_p):
            try:
                with open(en_p, "r", encoding='utf-8') as f:
                    self.i18n.update(json.load(f))
            except:
                pass
                
        # 覆盖加载所选语言
        if lang != "en":
            p = os.path.join("languages", f"{lang}.json")
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding='utf-8') as f:
                        self.i18n.update(json.load(f))
                except:
                    pass

    def t(self, key, default=None):
        return self.i18n.get(key, default if default is not None else key)

    def build_tray_menu(self):
        tray_menu = QMenu()
        action_config = QAction(self.t("ui.tray_config", "配置"), self)
        action_config.triggered.connect(self.show_window)
        
        action_about = QAction(self.t("ui.tray_about", "关于"), self)
        action_about.triggered.connect(self.open_about)
        
        action_exit = QAction(self.t("ui.tray_exit", "退出"), self)
        action_exit.triggered.connect(self.quit_app)
        
        tray_menu.addAction(action_config)
        tray_menu.addAction(action_about)
        tray_menu.addAction(action_exit)
        self.tray_icon.setContextMenu(tray_menu)

    def open_about(self):
        QDesktopServices.openUrl(QUrl("https://github.com/MrBocchi/RippleChargeEffect"))

    def check_power(self):
        current_status = get_ac_line_status()
        # ACLineStatus: 0 = 未接通, 1 = 已接通
        if self.last_status == 0 and current_status == 1:
            # 只有当当前没有测试进程在运行时才触发
            if self.test_process is None or self.test_process.poll() is not None:
                # 核心：确保使用的是 cached_process
                if hasattr(self, 'cached_process') and self.cached_process and self.cached_process.poll() is None:
                    self.cached_process.trigger()
                    self.test_process = self.cached_process
                    self.cached_process = None
                    # 触发后立即后台预热下一个，不阻塞当前显示
                    QTimer.singleShot(100, self.prepare_cache)
                    
                    # UI反馈
                    if hasattr(self, 'btn_test'):
                        self.btn_test.setEnabled(False)
                        self.btn_test.setText(self.t("ui.btn_test", "测试") + "...")
                        self.btn_force_stop.setEnabled(True)
                    
                    if not hasattr(self, 'check_process_timer'):
                        self.check_process_timer = QTimer(self)
                        self.check_process_timer.timeout.connect(self.check_test_process)
                    self.check_process_timer.start(500)
                else:
                    # 万一缓存进程挂了或还没建好，走兜底逻辑（虽然会慢一点点）
                    self.prepare_cache()
                    # 递归调用一次，尝试唤醒刚建好的缓存
                    QTimer.singleShot(200, self.check_power) 
                    
        self.last_status = current_status

    def on_tray_activated(self, reason):
        # 左键点击托盘打开配置界面
        if reason == QSystemTrayIcon.Trigger:
            self.show_window()

    def show_window(self):
        try:
            with open("config.json", "r", encoding='utf-8') as f:
                config_dict = json.load(f)
            self.update_ui_from_dict(config_dict)
        except Exception:
            pass
        self.is_modified = False
        if hasattr(self, 'btn_save'):
            self.btn_save.setEnabled(False)
            
        if hasattr(self, 'test_process') and self.test_process is not None and self.test_process.poll() is None:
            if hasattr(self, 'btn_test'):
                self.btn_test.setEnabled(False)
                self.btn_test.setText(self.t("ui.btn_test", "测试") + "...")
                self.btn_force_stop.setEnabled(True)
        else:
            if hasattr(self, 'btn_test'):
                self.btn_test.setEnabled(True)
                self.btn_test.setText(self.t("ui.btn_test", "测试"))
                self.btn_force_stop.setEnabled(False)

        if self.isMinimized():
            self.showNormal()

        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        # 关闭配置窗口时只隐藏，并且去除所有通知
        event.ignore()
        self.hide()

    def quit_app(self):
        self.tray_icon.hide()
        QApplication.quit()

    def on_changed(self, *args, **kwargs):
        self.is_modified = True
        if hasattr(self, 'btn_save'):
            self.btn_save.setEnabled(True)

    def build_ui(self):
        try:
            with open("config.json", "r", encoding='utf-8') as f:
                config = json.load(f)
        except Exception:
            config = {}
            
        self.tabs = QTabWidget()
        main_tab = QWidget()
        # 由于 GridLayout 的行会平均拉伸导致空隙过大，将其包裹在一个 VBox 中向顶部挤压
        main_layout_wrapper = QVBoxLayout(main_tab)
        main_layout_wrapper.setAlignment(Qt.AlignTop) # 使其内容紧贴顶部，防止被过度拉伸
        
        main_grid_widget = QWidget()
        main_layout = QGridLayout(main_grid_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setColumnStretch(1, 1)
        
        main_layout_wrapper.addWidget(main_grid_widget)
        
        self.ui_storage = {'__main__': {}}
        
        # 第一项新增语言下拉选项
        self.lang_cb = QComboBox()
        # 扫描 language 文件夹以动态生成语言列表
        lang_dir = "languages"
        discovered_langs = []
        if os.path.exists(lang_dir):
            for file in os.listdir(lang_dir):
                if file.endswith(".json"):
                    lang_code = file[:-5]
                    discovered_langs.append(lang_code)
                    
        # 强制将 zh-CN 和 en 提取出来置顶
        display_langs = []
        if "zh-CN" in discovered_langs:
            discovered_langs.remove("zh-CN")
            display_langs.append("简体中文 (zh-CN)")
        else:
            display_langs.append("简体中文 (zh-CN)")
            
        if "en" in discovered_langs:
            discovered_langs.remove("en")
            display_langs.append("English (en)")
        else:
            display_langs.append("English (en)")
            
        # 添加核心语言
        self.lang_cb.addItem(display_langs[0], "zh-CN")
        self.lang_cb.addItem(display_langs[1], "en")
        
        # 添加其他发现的语言
        for code in discovered_langs:
            self.lang_cb.addItem(code, code)
            
        idx = self.lang_cb.findData(self.current_lang)
        if idx >= 0: self.lang_cb.setCurrentIndex(idx)
        self.lang_cb.currentIndexChanged.connect(self.on_changed)
        main_layout.addWidget(QLabel(self.t("language", "语言/Language")), 0, 0)
        main_layout.addWidget(self.lang_cb, 0, 1, 1, 3)

        # 第二项: 开机启动设置 - 仅在frozen(打包)状态下显示
        current_row = 1
        if hasattr(sys, 'frozen'):
            startup_container = QWidget()
            startup_layout = QHBoxLayout(startup_container)
            startup_layout.setContentsMargins(0, 0, 0, 0)
            
            self.startup_cb = QCheckBox(self.t("startup", "开机启动"))
            self.startup_cb.setChecked(self.is_startup_enabled())
            
            self.btn_startup_confirm = QPushButton(self.t("ui.btn_confirm", "确认"))
            self.btn_startup_confirm.setEnabled(False) # Default disabled
            self.btn_startup_confirm.clicked.connect(self.toggle_startup_action)
            self.btn_startup_confirm.setFixedWidth(80) 
            
            # Enable confirm button when checkbox toggled
            self.startup_cb.toggled.connect(lambda: self.btn_startup_confirm.setEnabled(True))
            
            startup_layout.addWidget(self.startup_cb)
            startup_layout.addWidget(self.btn_startup_confirm)
            startup_layout.addStretch() 

            main_layout.addWidget(QLabel(self.t("system_startup", "启动项")), current_row, 0)
            main_layout.addWidget(startup_container, current_row, 1, 1, 3)
            current_row += 1

        
        # 第三项(或第二项): 托盘图标修改
        self.icon_cb = QComboBox()
        self.icon_cb.addItem(self.t("icon.default", "默认"), 0)
        self.icon_cb.addItem(self.t("icon.black", "黑色"), 1)
        self.icon_cb.addItem(self.t("icon.white", "白色"), 2)
        i_idx = self.icon_cb.findData(self.current_icon)
        if i_idx >= 0: self.icon_cb.setCurrentIndex(i_idx)
        self.icon_cb.currentIndexChanged.connect(self.on_changed)
        
        main_layout.addWidget(QLabel(self.t("tray_icon_color", "托盘图标颜色")), current_row, 0)
        main_layout.addWidget(self.icon_cb, current_row, 1, 1, 3)
        current_row += 1
        
        # 隐藏的字段
        excluded_keys = ["x", "y", "bg_darkness", "language", "tray_icon_color", "y_offset", "charge_direction"]
        
        # 定义特定顺序：首先ring，然后line，随后处理其他（除window外），使插入tabs时有序。
        # 由于我们稍后插入"基本配置"到第0个（最左面），tabs.addTab的顺序自然决定次级页面顺序
        # preferred_order = ["ring", "line"]
        # ordered_keys = preferred_order + [k for k in config.keys() if k not in preferred_order]
        ordered_keys = [k for k in config.keys()]

        # 用集合去重
        seen_keys = set()
        
        for k in ordered_keys:
            if k not in config or k in seen_keys:
                continue
            seen_keys.add(k)
            v = config[k]
            
            if k in excluded_keys:
                continue
            if isinstance(v, dict) and k != "window":
                tab = QWidget()
                # 去除内间距，使得内容紧凑些
                layout = QFormLayout(tab)
                self.ui_storage[k] = {}
                
                if k == "line":
                    cd_val = config.get("charge_direction", 5)
                    self.create_input("charge_direction", cd_val, layout, self.ui_storage['__main__'])
                
                # 特别处理 particle：确保 particle_enabled 排在最前面
                # if k == "particle" and "particle_enabled" in v:
                #     self.create_input("particle.particle_enabled", v["particle_enabled"], layout, self.ui_storage[k])
                    
                for sub_k, sub_v in v.items():
                    if sub_k in excluded_keys:
                        continue
                    # 刚才处理过了，跳过
                    # if k == "particle" and sub_k == "particle_enabled":
                    #     continue

                    self.create_input(f"{k}.{sub_k}", sub_v, layout, self.ui_storage[k])
                
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setWidget(tab)
                self.tabs.addTab(scroll, self.t(k, k))
            elif k == "window":
                # using current_row dynamically if it was set; otherwise fetch from layout
                # however main_layout is used. We need to know the current row index.
                # Since we added variable rows above, let's rely on standard grid behavior but we need an index.
                # Actually, main_layout.rowCount() gets the next free row index.
                curr_row = main_layout.rowCount()
                
                # width
                lbl_w = QLabel(self.t("window.width", "窗口宽度"))
                le_w = QLineEdit(str(v.get("width", 3456)))
                le_w.textChanged.connect(self.on_changed)
                self.ui_storage['__main__']["window.width"] = ('int', le_w)
                
                # height
                lbl_h = QLabel(self.t("window.height", "窗口高度"))
                le_h = QLineEdit(str(v.get("height", 2160)))
                le_h.textChanged.connect(self.on_changed)
                self.ui_storage['__main__']["window.height"] = ('int', le_h)
                
                main_layout.addWidget(lbl_w, curr_row, 0)
                main_layout.addWidget(le_w, curr_row, 1)
                main_layout.addWidget(lbl_h, curr_row + 1, 0)
                main_layout.addWidget(le_h, curr_row + 1, 1)
                
                # 当前分辨率与保存默认按钮
                btn_curr_res = QPushButton(self.t("ui.btn_curr_res", "当前分辨率"))
                btn_curr_res.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)
                btn_curr_res.setFixedWidth(80)
                btn_curr_res.clicked.connect(self.set_current_resolution)
                main_layout.addWidget(btn_curr_res, curr_row, 2, 2, 1)
                
                btn_save_res_def = QPushButton(self.t("ui.btn_save_res_def", "保存为默认"))
                btn_save_res_def.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)
                btn_save_res_def.setFixedWidth(80)
                btn_save_res_def.clicked.connect(self.save_resolution_to_default)
                main_layout.addWidget(btn_save_res_def, curr_row, 3, 2, 1)
                
                # 添加 window 下除了 width, height 或被排除字段之外的其他可能残留项（兼容性防漏）
                for sub_k, sub_v in v.items():
                    if sub_k in excluded_keys or sub_k in ["width", "height"]:
                        continue
                    self.create_input(f"window.{sub_k}", sub_v, main_layout, self.ui_storage['__main__'])

            else:
                self.create_input(k, v, main_layout, self.ui_storage['__main__'])
            
        scroll_main = QScrollArea()
        scroll_main.setWidgetResizable(True)
        scroll_main.setWidget(main_tab)
        self.tabs.insertTab(0, scroll_main, self.t("ui.basic_config", "基本配置"))
        self.tabs.setCurrentIndex(0) # 默认选中”基本配置“页面
        
        self.main_vbox.addWidget(self.tabs)
        
        self.btn_layout_widget = QWidget()
        main_btn_layout = QVBoxLayout(self.btn_layout_widget)
        main_btn_layout.setContentsMargins(0, 0, 0, 0)
        
        row1_layout = QHBoxLayout()
        row2_layout = QHBoxLayout()
        
        self.btn_restore = QPushButton(self.t("ui.btn_restore", "恢复默认"))
        self.btn_test = QPushButton(self.t("ui.btn_test", "测试"))
        self.btn_force_stop = QPushButton(self.t("ui.btn_force_stop", "强行停止"))
        
        self.btn_save = QPushButton(self.t("ui.btn_save", "保存"))
        self.btn_cancel = QPushButton(self.t("ui.btn_cancel", "取消"))
        self.btn_confirm = QPushButton(self.t("ui.btn_confirm", "确认"))
        
        # 默认按钮状态
        self.btn_save.setEnabled(False)
        self.btn_force_stop.setEnabled(False)
        
        self.btn_restore.clicked.connect(self.restore_default)
        self.btn_test.clicked.connect(self.run_test)
        self.btn_force_stop.clicked.connect(self.force_stop)
        self.btn_save.clicked.connect(self.save_config)
        self.btn_cancel.clicked.connect(self.cancel_action)
        self.btn_confirm.clicked.connect(self.confirm_action)
        
        row1_layout.addWidget(self.btn_restore)
        row1_layout.addWidget(self.btn_test)
        row1_layout.addWidget(self.btn_force_stop)
        
        row2_layout.addWidget(self.btn_save)
        row2_layout.addWidget(self.btn_cancel)
        row2_layout.addWidget(self.btn_confirm)
        
        main_btn_layout.addLayout(row1_layout)
        main_btn_layout.addLayout(row2_layout)
        
        self.main_vbox.addWidget(self.btn_layout_widget)

    def create_input(self, full_key, value, parent_layout, ui_storage):
        display_text = self.t(full_key, full_key.split('.')[-1])
        
        def add_to_layout(widget):
            if isinstance(parent_layout, QFormLayout):
                parent_layout.addRow(QLabel(display_text), widget)
            elif isinstance(parent_layout, QGridLayout):
                row = parent_layout.rowCount()
                parent_layout.addWidget(QLabel(display_text), row, 0)
                parent_layout.addWidget(widget, row, 1, 1, 3)
                
        if isinstance(value, bool):
            cb = QCheckBox()
            cb.setChecked(value)
            cb.stateChanged.connect(self.on_changed)
            add_to_layout(cb)
            ui_storage[full_key] = ('bool', cb)
        elif full_key == "charge_direction":
            cb = QComboBox()
            cb.addItem(self.t("dir.Left-L", "1=Left-L"), 1)
            cb.addItem(self.t("dir.Right-L", "2=Right-L"), 2)
            cb.addItem(self.t("dir.Bottom", "3=Bottom"), 3)
            cb.addItem(self.t("dir.Top", "4=Top"), 4)
            cb.addItem(self.t("dir.Left", "5=Left"), 5)
            cb.addItem(self.t("dir.Right", "6=Right"), 6)
            idx = cb.findData(value)
            if idx >= 0:
                cb.setCurrentIndex(idx)
            cb.currentIndexChanged.connect(self.on_changed)
            add_to_layout(cb)
            ui_storage[full_key] = ('combo_charge', cb)
        elif isinstance(value, list):
            le = QLineEdit(str(value))
            le.textChanged.connect(self.on_changed)
            add_to_layout(le)
            ui_storage[full_key] = ('list', le)
        elif isinstance(value, int):
            le = QLineEdit(str(value))
            le.textChanged.connect(self.on_changed)
            add_to_layout(le)
            ui_storage[full_key] = ('int', le)
        elif isinstance(value, float):
            le = QLineEdit(str(value))
            le.textChanged.connect(self.on_changed)
            add_to_layout(le)
            ui_storage[full_key] = ('float', le)
        else:
            le = QLineEdit(str(value))
            le.textChanged.connect(self.on_changed)
            add_to_layout(le)
            ui_storage[full_key] = ('str', le)

    def extract_value(self, v_type, widget):
        if v_type == 'bool': return widget.isChecked()
        elif v_type == 'combo_charge': return widget.currentData()
        elif v_type == 'list':
            text = widget.text()
            try: return ast.literal_eval(text)
            except: return text
        elif v_type == 'int':
            try: return int(widget.text())
            except: return 0
        elif v_type == 'float':
            try: return float(widget.text())
            except: return 0.0
        else:
            return widget.text()

    def set_value(self, v_type, widget, val):
        widget.blockSignals(True)
        if v_type == 'bool': widget.setChecked(bool(val))
        elif v_type == 'combo_charge':
            idx = widget.findData(val)
            if idx >= 0: widget.setCurrentIndex(idx)
        else:
            widget.setText(str(val))
        widget.blockSignals(False)

    def update_ui_from_dict(self, config_dict):
        new_lang = config_dict.get("language")
        if new_lang:
            idx = self.lang_cb.findData(new_lang)
            if idx >= 0:
                self.lang_cb.blockSignals(True)
                self.lang_cb.setCurrentIndex(idx)
                self.lang_cb.blockSignals(False)
                
        new_icon = config_dict.get("tray_icon_color")
        if new_icon:
            i_idx = self.icon_cb.findData(new_icon)
            if i_idx >= 0:
                self.icon_cb.blockSignals(True)
                self.icon_cb.setCurrentIndex(i_idx)
                self.icon_cb.blockSignals(False)

        for full_key, (v_type, widget) in self.ui_storage['__main__'].items():
            if full_key.startswith("window."):
                val = config_dict.get("window", {}).get(full_key.split(".")[1])
            else:
                val = config_dict.get(full_key)
            if val is not None: self.set_value(v_type, widget, val)
                
        for section in self.ui_storage:
            if section == '__main__': continue
            sec_dict = config_dict.get(section, {})
            for full_key, (v_type, widget) in self.ui_storage[section].items():
                sub_k = full_key.split('.')[-1]
                val = sec_dict.get(sub_k)
                if val is not None:
                    self.set_value(v_type, widget, val)

    def set_current_resolution(self):
        screen = QApplication.primaryScreen()
        size = screen.size()
        ratio = screen.devicePixelRatio()
        w = int(size.width() * ratio)
        h = int(size.height() * ratio)
        
        # fallback for strict physical resolution
        try:
            hdc = ctypes.windll.user32.GetDC(0)
            real_w = ctypes.windll.gdi32.GetDeviceCaps(hdc, 8) # HORZRES
            real_h = ctypes.windll.gdi32.GetDeviceCaps(hdc, 10) # VERTRES
            ctypes.windll.user32.ReleaseDC(0, hdc)
            if real_w > 0 and real_h > 0:
                w, h = real_w, real_h
        except:
            pass

        le_w = self.ui_storage['__main__'].get("window.width")
        le_h = self.ui_storage['__main__'].get("window.height")
        if le_w and le_h:
            le_w[1].setText(str(w))
            le_h[1].setText(str(h))
            self.on_changed()

    def save_resolution_to_default(self):
        reply = QMessageBox.question(self, self.t("ui.msg_title", "提示"),
                                     self.t("ui.msg_confirm_save_res", "确认要将当前界面中的分辨率保存至默认配置中吗？"),
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            le_w = self.ui_storage['__main__'].get("window.width")
            le_h = self.ui_storage['__main__'].get("window.height")
            if not le_w or not le_h: return
            w = self.extract_value('int', le_w[1])
            h = self.extract_value('int', le_h[1])
            
            try:
                if os.path.exists("config-default.json"):
                    with open("config-default.json", "r", encoding='utf-8') as f:
                        default_cfg = json.load(f)
                else:
                    default_cfg = {}
                if "window" not in default_cfg:
                    default_cfg["window"] = {}
                default_cfg["window"]["width"] = w
                default_cfg["window"]["height"] = h
                with open("config-default.json", "w", encoding='utf-8') as f:
                    json.dump(default_cfg, f, indent=4, ensure_ascii=False)
                QMessageBox.information(self, self.t("ui.msg_title", "提示"), self.t("ui.msg_save_res_success", "成功保存默认分辨率。"))
            except Exception as e:
                QMessageBox.critical(self, self.t("ui.msg_title", "提示"), f"Error: {str(e)}")

    def restore_default(self):
        if not os.path.exists("config-default.json"):
            return
        # 二次确认弹窗
        reply = QMessageBox.question(self, self.t("ui.msg_title", "提示"), 
                                     self.t("ui.msg_confirm_restore", "确认要恢复到默认配置并覆盖当前设置吗？"),
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                with open("config-default.json", "r", encoding='utf-8') as f:
                    default_cfg = json.load(f)
                
                # 保留当前的语言设置
                # default_cfg["language"] = self.lang_cb.currentData()
                
                self.update_ui_from_dict(default_cfg)
                with open("config.json", "w", encoding='utf-8') as f:
                    json.dump(default_cfg, f, indent=4, ensure_ascii=False)
                self.is_modified = False
                self.btn_save.setEnabled(False)
                
                # 恢复默认后，如果托盘图标变更则实时应用
                target_icon = default_cfg.get("tray_icon_color", 2)
                if self.current_icon != target_icon:
                    self.current_icon = target_icon
                    self.apply_tray_icon()
                
                # 恢复默认后，如果语言变更则实时刷新UI布局
                target_lang = default_cfg.get("language", "zh-CN")
                if self.current_lang != target_lang:
                    self.current_lang = target_lang
                    self.load_i18n(self.current_lang)
                    self.setWindowTitle(self.t("ui.title", "充电动画配置"))
                    self.build_tray_menu()
                    
                    self.tabs.deleteLater()
                    self.btn_layout_widget.deleteLater()
                    self.build_ui()
                
                if hasattr(self, 'cached_process') and self.cached_process:
                    try:
                        self.cached_process.kill()
                    except:
                        pass
                    self.cached_process = None
                self.prepare_cache()

            except Exception:
                pass

    def run_test(self):
        if self.test_process is not None and self.test_process.poll() is None:
            return
            
        # 如果配置已修改，测试前先保存（会自动重启缓存），否则直接用现有缓存
        if self.is_modified:
            self.save_config()
        
        if hasattr(self, 'cached_process') and self.cached_process:
            self.btn_test.setEnabled(False)
            self.btn_test.setText(self.t("ui.btn_test", "测试") + "...")
            self.btn_force_stop.setEnabled(True)
            
            self.cached_process.trigger() # 唤醒
            self.test_process = self.cached_process
            self.cached_process = None
            self.prepare_cache() # 预加载下一个
            
            if not hasattr(self, 'check_process_timer'):
                self.check_process_timer = QTimer(self)
                self.check_process_timer.timeout.connect(self.check_test_process)
            self.check_process_timer.start(500)

    def force_stop(self):
        if self.test_process is not None:
            self.test_process.kill()
            self.test_process = None

        if self.test_process is not None and self.test_process.poll() is None:
            try:
                self.test_process.kill()
            except Exception:
                pass
            self.test_process = None
        
        if hasattr(self, 'btn_test'):
            self.btn_test.setEnabled(True)
            self.btn_test.setText(self.t("ui.btn_test", "测试"))
            self.btn_force_stop.setEnabled(False)
            
        if hasattr(self, 'check_process_timer'):
            self.check_process_timer.stop()

    def check_test_process(self):
        if self.test_process and self.test_process.poll() is not None:
            # 进程已结束
            if hasattr(self, 'btn_test'):
                self.btn_test.setEnabled(True)
                self.btn_test.setText(self.t("ui.btn_test", "测试"))
                self.btn_force_stop.setEnabled(False)
            self.check_process_timer.stop()
            self.test_process = None

    def cancel_action(self):
        # 取消即不做额外处理退出(隐藏)
        self.hide()

    def confirm_action(self):
        # 确认即保存+取消
        if self.is_modified:
            self.save_config()
        self.hide()

    def save_config(self):
        try:
            with open("config.json", "r", encoding='utf-8') as f:
                config = json.load(f)
        except Exception:
            config = {}
            
        config["language"] = self.lang_cb.currentData()
        config["tray_icon_color"] = self.icon_cb.currentData()
            
        for full_key, (v_type, widget) in self.ui_storage['__main__'].items():
            val = self.extract_value(v_type, widget)
            if full_key.startswith("window."):
                if "window" not in config: config["window"] = {}
                config["window"][full_key.split(".")[1]] = val
            else:
                config[full_key] = val
                
        for section in self.ui_storage:
            if section == '__main__': continue
            if section not in config: config[section] = {}
            for full_key, (v_type, widget) in self.ui_storage[section].items():
                val = self.extract_value(v_type, widget)
                sub_k = full_key.split('.')[-1]
                config[section][sub_k] = val
                
        try:
            with open("config.json", "w", encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            
            # 去除所有成功提示弹窗
            self.is_modified = False
            self.btn_save.setEnabled(False)
            
            # 修改了托盘图标则实时应用
            if self.current_icon != config.get("tray_icon_color"):
                self.current_icon = config.get("tray_icon_color")
                self.apply_tray_icon()
            
            # 若修改了语言，则实时刷新UI布局
            if self.current_lang != config.get("language"):
                self.current_lang = config.get("language")
                self.load_i18n(self.current_lang)
                self.setWindowTitle(self.t("ui.title", "充电动画配置"))
                self.build_tray_menu()
                
                self.tabs.deleteLater()
                self.btn_layout_widget.deleteLater()
                self.build_ui()

            if hasattr(self, 'cached_process') and self.cached_process:
                try:
                    self.cached_process.kill()
                except:
                    pass
                self.cached_process = None
            self.prepare_cache()
                
        except Exception as e:
            QMessageBox.critical(self, self.t("ui.msg_title", "提示"), f"Error: {str(e)}")

    def toggle_startup_action(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            app_startup_name = "RippleChargeEffect" # 在这里修改开机启动项的名称
            
            if self.startup_cb.isChecked():
                # Add/Update registry
                # Check if running as exe or script
                if hasattr(sys, 'frozen'):
                    exe_path = sys.executable
                    winreg.SetValueEx(key, app_startup_name, 0, winreg.REG_SZ, f'"{exe_path}"')
                else:
                    # Not frozen, ignore based on requirements.
                    # "如果项目不是编译成exe运行的，则不添加至开机自启"
                    pass
                
            else:
                # Remove from registry
                try:
                    winreg.DeleteValue(key, app_startup_name)
                    # Also try to clean up old key if exists
                    try: winreg.DeleteValue(key, "ChargeEffectLauncher")
                    except: pass
                except WindowsError:
                    pass
            winreg.CloseKey(key)
            
            # Disable button after action
            if hasattr(self, 'btn_startup_confirm'):
                self.btn_startup_confirm.setEnabled(False)
                
        except Exception as e:
            QMessageBox.critical(self, self.t("ui.msg_title", "提示"), f"Error setting startup: {str(e)}")

    def is_startup_enabled(self):
        # 如果不是打包环境，直接返回False，即不可选
        if not hasattr(sys, 'frozen'):
            return False
            
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
            # Try new name first, then fallback to old name for compatibility check
            try:
                winreg.QueryValueEx(key, "RippleChargeEffect")
                winreg.CloseKey(key)
                return True
            except WindowsError:
                try:
                    winreg.QueryValueEx(key, "ChargeEffectLauncher")
                    winreg.CloseKey(key)
                    # If old key exists, we consider it enabled, next toggle will fix name
                    return True
                except WindowsError:
                    winreg.CloseKey(key)
                    return False
        except WindowsError:
            return False



    def start_main_process(self):
        # if hasattr(sys, 'frozen'):
        #     # Only support "main.exe" in same dir
        #     cwd = os.path.dirname(sys.executable)
        #     target_exe = os.path.join(cwd, "main.exe")
        #     if os.path.exists(target_exe):
        #         return subprocess.Popen([target_exe], cwd=cwd)
        # else:
        #      # Development fallback
        #      cwd = os.path.dirname(os.path.abspath(__file__))
        #      return subprocess.Popen([sys.executable, "main.py"], cwd=cwd)

        return ProcessWrapper(target=main)



def check_dependencies():
    required_files = [
        os.path.join("assets", "app.ico"),
        os.path.join("assets", "tray_b.ico"),
        os.path.join("assets", "tray_w.ico"), 
        # "config.json",
        "config-default.json",
        os.path.join("languages", "zh-CN.json"),
        os.path.join("languages", "en.json")
    ]
    
    missing = []
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for f in required_files:
        if not os.path.exists(os.path.join(f)):
            missing.append(f)
            
    if missing:
        # Create a hidden root window to show the message box if QApplication is not yet running
        # actually for simple message box check we can use ctypes
        msg = "缺少依赖文件:\n" + "\n".join(missing)
        ctypes.windll.user32.MessageBoxW(0, msg, "错误", 0x10)
        sys.exit(1)





import sys
import os
import json
import time
import ctypes
import ctypes.wintypes
import numpy as np
import psutil
import shutil

# Suppress debug logs internally from ModernGL
os.environ['VG_GL_PROFILE'] = 'core' 

import pygame
import pygame.freetype
import moderngl
import mss

# --- Constants & Defaults ---
DEFAULT_CONFIG = {
    "window": {
        "width": 1920,
        "height": 1200,
        "x": "center",
        "y": "center"
    },
    "color": [90, 255, 120],
    "alpha": 0.85,
    "bg_darkness": 0.2,
    "charge_direction": "1"
}

def load_config():
    """ Load or create configuration definition file. """
    cfg_path = os.path.join("config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=4)
    return DEFAULT_CONFIG

def main(start_event):
    config = load_config()

    # Opt-in for Dpi Awarness mode to avoid auto-scaling stretching by Windows
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
    except Exception:
        pass

    # Stop pygame/SDL from attempting to minimize when losing focus or clicking away
    os.environ["SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS"] = "0"
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

    # Only initialize necessary subsystems to bypass mixer/joystick cold start penalties
    pygame.display.init()
    pygame.freetype.init()

    # Determine render resolution
    win_w = config["window"]["width"]
    win_h = config["window"]["height"]

    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)

    # Prevent Hardware Fullscreen Exclusive Mode which causes black screen flickering
    if win_w >= screen_w and win_h >= screen_h:
        win_w = screen_w
        win_h = screen_h - 1  # Reduce height by 1px to bypass Windows exclusive mode

    win_x = config["window"]["x"]
    win_y = config["window"]["y"]

    if win_x == "center":
        win_x = (screen_w - win_w) // 2
    else:
        win_x = int(win_x)
        
    if win_y == "center":
        win_y = (screen_h - win_h) // 2
    else:
        win_y = int(win_y)

    # Pre-configure pygame container window properties
    os.environ['SDL_VIDEO_WINDOW_POS'] = f"{win_x},{win_y}"
    
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
    
    # Hidden init via pygame window position allows us to prep the window before it flashes on screen
    os.environ['SDL_VIDEO_WINDOW_POS'] = f"{win_x},{win_y}"
    
    screen = pygame.display.set_mode((win_w, win_h), pygame.OPENGL | pygame.DOUBLEBUF | pygame.NOFRAME | pygame.HIDDEN)

    # Windows API calls to shape window visibility
    # For global mouse hooking we'll need ctypes struct definitions if click_exit is enabled
    if sys.platform == "win32":
        hwnd = pygame.display.get_wm_info()["window"]
        
        # Set HWND_TOPMOST without modifying sizes explicitly, and DO NOT invoke SWP_SHOWWINDOW yet.
        # 0x0001=SWP_NOSIZE, 0x0002=SWP_NOMOVE, 0x0010=SWP_NOACTIVATE
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)

        # Apply Layered and Click-through Mouse-Pass properties
        ex_style = user32.GetWindowLongW(hwnd, -20)
        
        # Try a safer layering flag: WS_EX_TOOLWINDOW | WS_EX_APPWINDOW
        # 0x00080000 = WS_EX_LAYERED
        # 0x00000020 = WS_EX_TRANSPARENT
        # 0x00000080 = WS_EX_TOOLWINDOW
        user32.SetWindowLongW(hwnd, -20, ex_style | 0x00000080 | 0x00000020 | 0x00080000)
        
        # Make the window perfectly opaque initially to the layering engine, 
        # so OpenGL purely controls the alpha via `rgba` fragments.
        # But wait! A known issue on Windows + PyGame + Layered window is black screen
        # if LWA_ALPHA is used with OpenGL buffer flipping on certain drivers. 
        # We must use LWA_COLORKEY instead or remove LWA_ALPHA and let DWM composite it!
        # Actually in Python/SDL2, OpenGL requires ALPHAFORMAT to blend cleanly:
        # We can bypass SetLayeredWindowAttributes and rely entirely on SDL's transparency if possible,
        # but for true mouse-pass we keep it but with full 255.
        user32.SetLayeredWindowAttributes(hwnd, 0, 255, 0x00000002) 

        # Very Important Flag for real-time visual refraction: WDA_EXCLUDEFROMCAPTURE
        # Completely omits this active window from capture pipelines, allowing MSS to fetch pure desktop pixels behind it dynamically
        try:
            # Note: WDA_EXCLUDEFROMCAPTURE = 0x00000011
            user32.SetWindowDisplayAffinity(hwnd, 0x00000011)
        except Exception as e:
            print("Warning: WDA_EXCLUDEFROMCAPTURE flag binding failed.", e)

    # Setup OpenGL Context
    ctx = moderngl.create_context()

    # Load custom shader
    shader_path = os.path.path.join("shader.glsl") if not os.path.exists("shader.glsl") else "shader.glsl"
    with open(shader_path, "r", encoding="utf-8") as f:
        fragment_shader = f.read()

    prog = ctx.program(
        vertex_shader="""
            #version 330 core
            in vec2 in_vert;
            out vec2 uvs;
            void main() {
                gl_Position = vec4(in_vert, 0.0, 1.0);
                // Translating mathematical coordinates to image coordinates
                uvs = vec2(in_vert.x * 0.5 + 0.5, 0.5 - in_vert.y * 0.5); 
            }
        """,
        fragment_shader=fragment_shader
    )

    vertices = np.array([
        -1.0, -1.0,
         1.0, -1.0,
        -1.0,  1.0,
         1.0,  1.0,
    ], dtype="f4")

    vbo = ctx.buffer(vertices.tobytes())
    vao = ctx.vertex_array(prog, [(vbo, '2f', 'in_vert')])

    # Allocate graphic layers for capturing frame
    tex_bg = ctx.texture((win_w, win_h), 4)
    tex_bg.swizzle = 'BGRA' # MSS yields native BGRA buffers instead of RGBA.
    tex_bg.use(0)
    prog['tex_bg'].value = 0

    # Allocate text font rendering buffer
    tex_text = ctx.texture((800, 800), 4)
    tex_text.use(1)
    prog['tex_text'].value = 1

    # Inject static parameters to shader
    prog['resolution'].value = (win_w, win_h)
    
    color_val = config["color"]
    # Handle Hex color string like "#5AFF78"
    if isinstance(color_val, str) and color_val.startswith("#"):
        hex_color = color_val.lstrip("#")
        color = [int(hex_color[i:i+2], 16) for i in (0, 2, 4)]
    else:
        color = color_val
        
    prog['overlay_color'].value = (color[0]/255.0, color[1]/255.0, color[2]/255.0)
    prog['alpha'].value = float(config["alpha"])
    # 旧有的 bg_darkness 效果设为 0 (保留变量不报错)
    prog['bg_darkness'].value = float(config["bg_darkness"])
    # 注入新的全屏压暗配置
    prog['bg_darkness_new'].value = float(config["bg_darkness_new"])
    
    ring_cfg = config.get("ring", {})
    prog['ripple_distortion'].value = float(ring_cfg.get("ripple_distortion", 0.08))
    prog['ripple_speed'].value = float(ring_cfg.get("ripple_speed", 1.0))
    prog['ring_scale'].value = float(ring_cfg.get("ring_scale", 1.0))
    prog['inner_radius'].value = float(ring_cfg.get("inner_radius", 0.15))
    prog['outer_radius'].value = float(ring_cfg.get("outer_radius", 0.40))
    
    particle_cfg = config.get("particle", {})
    prog['particle_density'].value = float(particle_cfg.get("particle_density", 60.0))
    prog['particle_speed'].value = float(particle_cfg.get("particle_speed", 0.04))
    prog['particle_enabled'].value = 1.0 if particle_cfg.get("particle_enabled", True) else 0.0
    prog['particle_wave_ratio'].value = float(particle_cfg.get("particle_wave_ratio", 3.0))
    prog['particle_radius_offset'].value = float(particle_cfg.get("particle_radius_offset", 0.02))
    prog['particle_brightness'].value = float(particle_cfg.get("particle_brightness", 3.5))

    line_cfg = config.get("line", {})
    prog['line_thickness'].value = float(line_cfg.get("line_thickness", 0.03))
    prog['l_shape_y_offset'].value = float(line_cfg.get("l_shape_y_offset", 0.35))
    prog['l_shape_curve_radius'].value = float(line_cfg.get("l_shape_curve_radius", 0.12))
    
    prog['global_fade'].value = 0.0 # 初始为 0.0 等待背景完全载入后渐显

    # 读取生命周期设定
    display_duration = float(config.get("display_duration", 5.0))
    auto_exit = bool(config.get("auto_exit", True))
    click_exit = bool(config.get("click_exit", True))
    fade_duration = float(config.get("fade_duration", 1.0))

    dir_val = config.get("charge_direction", 5)
    try:
        dir_mapped = int(dir_val)
    except:
        # Fallback to older string config format if integer wasn't properly used
        dirs_str = {"left": 5, "right": 6, "bottom": 3, "top": 4, "left-l": 1, "right-l": 2}
        dir_mapped = dirs_str.get(str(dir_val).lower(), 5)
    prog['direction'].value = dir_mapped

    # Setup text configuration
    text_cfg = config.get("text", {
        "font_name": "Arial", "size_large": 100, "size_small": 45,
        "color": [255, 255, 255], "decimal_increase_per_sec": 2.0
    })
    
    font_name = text_cfg.get("font_name", "Arial")
    size_large = text_cfg.get("size_large", 100)
    size_small = text_cfg.get("size_small", 45)
    
    text_color_val = text_cfg.get("color", [255, 255, 255])
    if isinstance(text_color_val, str) and text_color_val.startswith("#"):
        hex_color_tc = text_color_val.lstrip("#")
        text_color = tuple([int(hex_color_tc[i:i+2], 16) for i in (0, 2, 4)])
    else:
        text_color = tuple(text_color_val)
        
    text_alpha = text_cfg.get("alpha", 0.9) * 255
    decimal_speed = text_cfg.get("decimal_increase_per_sec", 2.0)
    
    # 动态分辨率倍率计算（以 3456 分辨率为基准 1.0 的参照比）
    # 当 window.height 降低时，不仅圆环本身（依赖于 ring_scale 和 resolution.y 已经同步变小），
    # 它的文字基准也会等比缩小，避免在 1080p 显示器上文字显得过大突出来。
    auto_scale_ratio = win_h / 2160.0
    
    # 获取基础的 text_scale 并应用乘法自动缩放
    base_text_scale = text_cfg.get("text_scale", 1.3)
    prog['text_scale'].value = float(base_text_scale * auto_scale_ratio)

    # 图标大小也同样支持自动缩放以对应不同屏幕（图标不用了）
    # png_size = int(text_cfg.get("png_size", 80) * auto_scale_ratio)
    png_size = int(text_cfg.get("png_size", 80))

    font_large = None
    font_small = None
    
    # Fast path: bypass Windows SysFont directory scanning latency for common fonts
    common_fonts = {
        "arial": r"C:/Windows/Fonts/arial.ttf",
        "tahoma": r"C:/Windows/Fonts/tahoma.ttf",
        "segoe ui": r"C:/Windows/Fonts/segoeui.ttf",
        "microsoft yahei": r"C:/Windows/Fonts/msyh.ttc"
    }
    
    fast_path = common_fonts.get(str(font_name).lower())
    if fast_path and os.path.exists(fast_path):
        try:
            font_large = pygame.freetype.Font(fast_path, size_large)
            font_large.strong = True
            font_small = pygame.freetype.Font(fast_path, size_small)
            font_small.strong = True
        except Exception:
            pass

    if not font_large:
        font_large = pygame.freetype.SysFont(font_name, size_large, bold=True)
        if not font_large:
            font_large = pygame.freetype.SysFont(None, size_large, bold=True)
            
        font_small = pygame.freetype.SysFont(font_name, size_small, bold=True)
        if not font_small:
            font_small = pygame.freetype.SysFont(None, size_small, bold=True)

    # Load Image Icon 
    img_path = os.path.join("assets", "lightning.png")
    try:
        lightning_img = pygame.image.load(img_path).convert_alpha()
        lightning_img = pygame.transform.smoothscale(lightning_img, (png_size, png_size))
        # Colorize the white/black image to match text_color if needed
        # Or just keep the native color. We will tint it to text_color:
        lightning_tinted = lightning_img.copy()
        lightning_tinted.fill((*text_color, text_alpha), special_flags=pygame.BLEND_RGBA_MULT)
    except Exception as e:
        print("Fallback: could not load lightning.png", e)
        lightning_tinted = None

    start_event.wait() # 阻塞在这里，直到 GUI 发送 trigger 信号

# --- 强行夺取前台权限 ---
    try:
        # WS_EX_TOPMOST(0x8) | WS_EX_TOOLWINDOW(0x80) | WS_EX_LAYERED(0x80000) | WS_EX_TRANSPARENT(0x20)
        h_bridge = user32.CreateWindowExW(0x800A8, "Static", "ZBridge", 0x80000000, 0, 0, 1, 1, 0, 0, 0, 0)
        user32.SetLayeredWindowAttributes(h_bridge, 0, 0, 0x02) # 完全透明
        
        # 核心 Hack：模拟按下 Alt 键 (VK_MENU = 0x12) 来绕过 Windows 的 SetForegroundWindow 限制
        user32.keybd_event(0x12, 0, 0, 0) # Alt Down
        user32.ShowWindow(h_bridge, 5)   # SW_SHOW (必须激活以获取真正的 Z-Order 权重)
        user32.SetForegroundWindow(h_bridge)
        user32.keybd_event(0x12, 0, 2, 0) # Alt Up
    except Exception:
        pass
# ----------------------

    sct = mss.mss()
    monitor = {"top": win_y, "left": win_x, "width": win_w, "height": win_h}
    
    # 预先抓取一次背景缓存并填入显存，防止出现应用启动第一眼直接是初始化的黑屏
    try:
        sct_init_img = sct.grab(monitor)
        tex_bg.write(sct_init_img.bgra)
    except Exception as e:
        print("Failed to pre-grab background:", e)

    clock = pygame.time.Clock()
    t0 = time.time()
    last_batt_time = 0
    current_percent = -1
    charge_start_time = 0
    last_text_drawn = ""
    last_bg_cap_time = 0
    
    # 维护生命周期的状态机
    lifecycle_state = "FADE_IN"
    state_start_time = 0.0
    
    # 异步检测全局鼠标点击的基础设置
    mouse_clicked_flags = [False]
    def get_async_keystate():
        if sys.platform == "win32":
            # VK_LBUTTON (0x01) and VK_RBUTTON (0x02) and VK_MBUTTON (0x04)
            return (ctypes.windll.user32.GetAsyncKeyState(1) & 0x8000) != 0 or \
                   (ctypes.windll.user32.GetAsyncKeyState(2) & 0x8000) != 0 or \
                   (ctypes.windll.user32.GetAsyncKeyState(4) & 0x8000) != 0
        return False

    running = True
    while running:
        # If application receives closure event or ESC key
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                # 触发提前退出
                if lifecycle_state != "FADE_OUT":
                    lifecycle_state = "FADE_OUT"
                    state_start_time = t

        t = time.time() - t0
        
        # 持续监控全局鼠标点击，不受鼠标是否在无头窗口内的限制（因为是透明穿透）
        if click_exit and lifecycle_state in ["FADE_IN", "DISPLAY"]:
            if get_async_keystate():
                lifecycle_state = "FADE_OUT"
                # 计算提前开始衰减时的时间轴（如果还在FADE_IN阶段，让它从对应的亮度值反向渐隐）
                current_fade = prog['global_fade'].value
                state_start_time = t - (1.0 - current_fade) * fade_duration
        
        # Check battery metric roughly every 1.5 seconds to save overhead CPU cost
        if time.time() - last_batt_time > 1.5:
            last_batt_time = time.time()
            battery = psutil.sensors_battery()
            new_percent = battery.percent if battery else 100
            if new_percent != current_percent:
                current_percent = new_percent
                charge_start_time = time.time()
                
        # Repaint text dynamically each frame if fake decimals are used (< 100)
        # Even if it's 100%, we draw it once when it updates. So we handle text painting:
        need_paint = False
        display_integer = current_percent
        display_decimal_str = ""
        
        if current_percent < 100:
            need_paint = True
            elapsed_charging = time.time() - charge_start_time
            # Calculate decimal value (0-99), speed is how much it increases per second
            dec_val = int(elapsed_charging * decimal_speed) % 100
            display_decimal_str = f".{dec_val:02d}%"
        else:
            # 100% logic: just draw once when it switches
            # Or draw every frame, 800x800 surface clear and render is very fast
            display_decimal_str = "%"
            need_paint = True

        if need_paint:
            current_text_state = f"{display_integer}_{display_decimal_str}"
            if current_text_state != last_text_drawn:
                last_text_drawn = current_text_state
                text_surf = pygame.Surface((800, 800), pygame.SRCALPHA)
                text_surf.fill((0, 0, 0, 0))
                
                str_large = str(display_integer)
                str_small = display_decimal_str
                
                w_large = font_large.get_rect(str_large).width
                w_small = font_small.get_rect(str_small).width
                
                # Setup horizontal spacing between integer and decimal percentage
                gap_between_text = 8 # add slight spacing
                total_w = w_large + w_small + gap_between_text
                
                # 提取用户通过配置设定的全体文字向上/向下偏移量
                y_offset = text_cfg.get("y_offset", -20)
                
                # Draw line 1: Value + Decimal/Percent
                x_start = (800 - total_w) // 2
                # Vertically center by offsetting slightly up for the thunderbolt, 加上新的偏移量
                y_base = 400 - (size_large // 2) + y_offset
                
                font_large.render_to(text_surf, (x_start, y_base), str_large, fgcolor=(*text_color, text_alpha))
                # Align small text to the baseline
                h_large = font_large.get_rect(str_large).height
                h_small = font_small.get_rect(str_small).height
                y_small = y_base + (h_large - h_small)
                font_small.render_to(text_surf, (x_start + w_large + gap_between_text, y_small), str_small, fgcolor=(*text_color, text_alpha))
            
                # Draw line 2: SVG Icon (or fallback)
                icon_gap_top = 22 # significantly larger than gap_between_text but moderate
                if lightning_tinted:
                    t_w, t_h = lightning_tinted.get_size()
                    t_x = (800 - t_w) // 2
                    t_y = y_base + h_large + icon_gap_top
                    text_surf.blit(lightning_tinted, (t_x, t_y))
                else:
                    thunder_str = "⚡"
                    t_rect = font_small.get_rect(thunder_str)
                    t_x = (800 - t_rect.width) // 2
                    t_y = y_base + h_large + icon_gap_top
                    font_small.render_to(text_surf, (t_x, t_y), thunder_str, fgcolor=(*text_color, text_alpha))
                
                raw_data = pygame.image.tostring(text_surf, "RGBA", False)
                tex_text.write(raw_data)

        # 限频抓取底层屏幕实时动态 (最高 30 FPS)
        if t - last_bg_cap_time > (1.0 / 30.0):
            last_bg_cap_time = t
            try:
                sct_img = sct.grab(monitor)
                tex_bg.write(sct_img.bgra)
            except Exception as e:
                pass # Screen geometry capture bounds error bypass protection

        # 生命期与渐隐状态机逻辑
        global_fade_val = 1.0
        
        if lifecycle_state == "FADE_IN":
            elapsed = t - state_start_time
            if elapsed < fade_duration:
                global_fade_val = elapsed / fade_duration
            else:
                global_fade_val = 1.0
                lifecycle_state = "DISPLAY"
                state_start_time = t
        elif lifecycle_state == "DISPLAY":
            global_fade_val = 1.0
            if auto_exit:
                elapsed = t - state_start_time
                if elapsed >= display_duration:
                    lifecycle_state = "FADE_OUT"
                    state_start_time = t
        elif lifecycle_state == "FADE_OUT":
            elapsed = t - state_start_time
            if elapsed < fade_duration:
                global_fade_val = 1.0 - (elapsed / fade_duration)
            else:
                global_fade_val = 0.0
                running = False # 动画最终完成，结束主循环
                
        prog['global_fade'].value = max(0.0, min(1.0, global_fade_val))

        prog['time'].value = t

        ctx.clear(0.0, 0.0, 0.0, 0.0)
        
        # Draw frame natively onto GUI
        tex_bg.use(0)
        tex_text.use(1)
        vao.render(moderngl.TRIANGLE_STRIP)

        pygame.display.flip()
        
        # After the first successful render loop, make the window visible.
        # Then reveal the window without taking focus from the user's active app.
        if sys.platform == "win32" and user32.IsWindowVisible(hwnd) == 0:
            user32.ShowWindow(hwnd, 8) 
            # user32.SetForegroundWindow(hwnd)
            # user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0040 | 0x0010 | 0x0002 | 0x0001)

# --- 强行夺取前台权限 ---
            # 增量代码：此时进程已拥有权限，调用此函数刷新主窗口的 Z-Order 且不触发黑屏闪烁
            user32.BringWindowToTop(hwnd)
            # 桥接窗口使命完成，销毁之
            if 'h_bridge' in locals():
                user32.DestroyWindow(h_bridge)
# ----------------------

        # Cap logic loop max efficiency. High frame rate enhances liquid smooth feel.
        clock.tick(60) 

    pygame.quit()

def check_dependencies_2():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    required_files = [
        # "config.json",
        "shader.glsl",
        os.path.join("assets", "lightning.png")
    ]
    
    missing = []
    
    for f in required_files:
        # if not os.path.exists(os.path.join(base_dir, f)):
        if not os.path.exists(os.path.join(f)):
            missing.append(f)
            
    if missing:
        msg = "缺少依赖文件:\n" + "\n".join(missing)
        try:
            ctypes.windll.user32.MessageBoxW(0, msg, "错误", 0x10)
        except:
            print(msg)
        sys.exit(1)

def check_first_run():
    # config.json handling
    config_default_path = os.path.join("config-default.json")
    config_path = os.path.join("config.json")
    
    should_copy_default = False
    
    if not os.path.exists(config_path):
        if os.path.exists(config_default_path):
            should_copy_default = True
    # elif os.path.exists(config_default_path):
    #     # Check for missing keys
    #     try:
    #         with open(config_default_path, "r", encoding="utf-8") as f:
    #             default_cfg = json.load(f)
    #         with open(config_path, "r", encoding="utf-8") as f:
    #             current_cfg = json.load(f)
            
    #         def check_keys(def_c, cur_c):
    #             for k, v in def_c.items():
    #                 if k not in cur_c:
    #                     return True
    #                 if isinstance(v, dict) and isinstance(cur_c[k], dict):
    #                      if check_keys(v, cur_c[k]):
    #                          return True
    #             return False

    #         if check_keys(default_cfg, current_cfg):
    #             should_copy_default = True
                
    #     except Exception:
    #          # If cant parse, assume broken
    #          should_copy_default = True

    def save_current_screen_resolution_to_default():
        # 确保 QApplication 存在
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        screen = QApplication.primaryScreen()
        if screen is None:
            return

        size = screen.size()
        ratio = screen.devicePixelRatio()
        w = int(size.width() * ratio)
        h = int(size.height() * ratio)

        # Windows 严格物理分辨率 fallback
        try:
            hdc = ctypes.windll.user32.GetDC(0)
            real_w = ctypes.windll.gdi32.GetDeviceCaps(hdc, 8)   # HORZRES
            real_h = ctypes.windll.gdi32.GetDeviceCaps(hdc, 10)  # VERTRES
            ctypes.windll.user32.ReleaseDC(0, hdc)
            if real_w > 0 and real_h > 0:
                w, h = real_w, real_h
        except:
            pass

        config_path = "config-default.json"

        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                default_cfg = json.load(f)
        else:
            default_cfg = {}

        default_cfg.setdefault("window", {})
        default_cfg["window"]["width"] = w
        default_cfg["window"]["height"] = h

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_cfg, f, indent=4, ensure_ascii=False)

    if should_copy_default and os.path.exists(config_default_path):
        try:
            save_current_screen_resolution_to_default()
            import shutil
            shutil.copy2(config_default_path, config_path)
            app.setWindowIcon(QIcon(os.path.join("assets", "app.ico")))
            QMessageBox.information(None, "初始化成功！/ Initialization successful!", "可以从右下角托盘处打开配置界面。此提示只会出现一次。\nThe configuration interface can be opened from the tray in the lower right corner. This tip will only appear once.")
        except Exception as e:
            msg = f"无法重置配置文件: {e}"
            try:
                ctypes.windll.user32.MessageBoxW(0, msg, "错误", 0x10)
            except:
                print(msg)



check_dependencies()
check_dependencies_2()

if __name__ == '__main__':
    multiprocessing.freeze_support()
    # 单例运行检查
    mutex_name = "Global\\ChargeEffectLauncherMyAppMutex"
    mutex = ctypes.windll.kernel32.CreateMutexW(None, True, mutex_name)
    if ctypes.windll.kernel32.GetLastError() == 183: # ERROR_ALREADY_EXISTS
        # 0x40: MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(0, "已经在运行咯，请从右下角托盘处打开配置！\nIt's already up and running! Please open the configuration from the system tray in the bottom-right corner!", "重复运行 / Duplicate Run", 0x40)
        sys.exit(0)

    # 启用高DPI缩放防模糊
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False) # 关键：确保关闭窗口时不退出应用
    
    check_first_run()

    window = ConfigWindow()
    # 启动应用后默认不执行 window.show()，以此实现开启后最小化存在于托盘
    
    sys.exit(app.exec_())
