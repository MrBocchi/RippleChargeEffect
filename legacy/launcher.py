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
        # ACLineStatus: 0 = 未接通电源(未充电), 1 = 已接通电源(充电中)
        if self.last_status == 0 and current_status == 1:
            if self.test_process is None or self.test_process.poll() is not None:
                self.test_process = self.start_main_process()
                if hasattr(self, 'btn_test'):
                    self.btn_test.setEnabled(False)
                    self.btn_test.setText(self.t("ui.btn_test", "测试") + "...")
                    self.btn_force_stop.setEnabled(True)
                
                if not hasattr(self, 'check_process_timer'):
                    self.check_process_timer = QTimer(self)
                    self.check_process_timer.timeout.connect(self.check_test_process)
                self.check_process_timer.start(500)
                
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
                    
            except Exception:
                pass

    def run_test(self):
        # 如果已经有测试进程在运行，则不额外拉起
        if self.test_process is not None and self.test_process.poll() is None:
            return
            
        # 先自动保存当前配置以确保 main.py 读到最新状态 （如果不希望保存直接测原状态，可以注释这行）
        self.save_config()
        
        self.btn_test.setEnabled(False)
        self.btn_test.setText(self.t("ui.btn_test", "测试") + "...")
        self.btn_force_stop.setEnabled(True)
        
        # 拉起 main.py
        self.test_process = self.start_main_process()
        
        # 增加一个独立定时器来监控测试进程何时结束
        if hasattr(self, 'check_process_timer'):
            self.check_process_timer.stop()
        else:
            self.check_process_timer = QTimer(self)
            self.check_process_timer.timeout.connect(self.check_test_process)
        self.check_process_timer.start(500)

    def force_stop(self):
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
                
        except Exception as e:
            QMessageBox.critical(self, self.t("ui.msg_title", "提示"), f"Error: {str(e)}")

    def toggle_startup_action(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            app_startup_name = "ChargeEffect" # 在这里修改开机启动项的名称
            
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
                winreg.QueryValueEx(key, "ChargeEffect")
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
        if hasattr(sys, 'frozen'):
            # Only support "main.exe" in same dir
            cwd = os.path.dirname(sys.executable)
            target_exe = os.path.join(cwd, "main.exe")
            if os.path.exists(target_exe):
                return subprocess.Popen([target_exe], cwd=cwd)
        else:
             # Development fallback
             cwd = os.path.dirname(os.path.abspath(__file__))
             return subprocess.Popen([sys.executable, "main.py"], cwd=cwd)




def check_dependencies():
    required_files = [
        os.path.join("assets", "app.ico"),
        os.path.join("assets", "tray_b.ico"),
        # tray_w.ico is also used in apply_tray_icon so we should check it too based on user request "tray_b(_w).ico"
        os.path.join("assets", "tray_w.ico"), 
        "config.json",
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

check_dependencies()

if __name__ == '__main__':
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
    
    window = ConfigWindow()
    # 启动应用后默认不执行 window.show()，以此实现开启后最小化存在于托盘
    
    sys.exit(app.exec_())
