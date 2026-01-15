from __future__ import annotations
import os
import sys
import time
import json
import sqlite3
import threading
import traceback
import subprocess
import webbrowser
import math
from datetime import datetime, date, timedelta
import calendar
from typing import Optional, Tuple, List
import numpy as np
from PIL import Image, ImageTk, ImageDraw, ImageFont
import cv2
import tkinter as tk
from tkinter import messagebox, colorchooser, Menu
from collections import Counter
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="google.protobuf.symbol_database") # Suppress protobuf deprecation warning
import customtkinter as ctk
from customtkinter import CTkImage
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.text import Annotation
from matplotlib.ticker import MaxNLocator
import matplotlib.patheffects as patheffects
from matplotlib.colors import to_rgb
from matplotlib import patches
import mediapipe as mp
from appdirs import user_data_dir
import queue

# Constants
APP_NAME = "ScreenGuardian"
DATA_DIR = user_data_dir(APP_NAME)
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
DB_FILE = os.path.join(DATA_DIR, "data.db")
CALIB_FILE = os.path.join(DATA_DIR, "calibration.json")
LOG_FILE = os.path.join(DATA_DIR, "screenguardian.log")
VIDEO_ASPECT = (4, 3)
CALIB_PREVIEW_W, CALIB_PREVIEW_H = 640, 480 # preview size
REAL_CARD_WIDTH_CM = 8.56
REAL_CARD_HEIGHT_CM = 5.398
REAL_CARD_ASPECT = REAL_CARD_WIDTH_CM / REAL_CARD_HEIGHT_CM # Calibration card aspect ratio
ASSUMED_CALIB_DISTANCE_CM = 70 # Estimated distance based on card relative size
TWENTY_TWENTY_SEC = 1200
SUPPORT_EMAIL = "screenguardian.info@gmail.com"
DOCS_URL = "https://e9dc0f3d.sg-web-docs.pages.dev"
BUY_COFFEE_URL = "https://www.buymeacoffee.com/"
LEFT_EYE_IDX = [33, 133, 160, 159, 158]
RIGHT_EYE_IDX = [362, 263, 387, 386, 385]
NOSE_IDX = 1
SAVE_INTERVAL_SEC = 15
DASHBOARD_MIN_HEIGHT = 260  # Minimum dashboard height
DASHBOARD_WINDOW_RATIO = 1 / 3  # Dashboard takes up one-third of window at most
TOP_MAX_HEIGHT_RATIO = 0.66  # Upper widgets occupy 2/3 of window height at most
GRAPH_REFRESH_SEC = 60
GRAPH_COLOR_SCREEN = "#1f77b4"
GRAPH_COLOR_POSTURE = "#ff7f0e"  
GRAPH_COLOR_DISTANCE = "#2ca02c" 
GRAPH_COLOR_ALERTS = "#d62728" 
GRAPH_COLOR_NAIL = "#9467bd"  
GRAPH_COLOR_FACE = "#8c564b" 
MOUTH_IDX = [13, 14, 78, 308, 311, 312]  # Rough mouth landmarks
FINGERTIP_IDX = [4, 8, 12, 16, 20]  # Fingertip landmark indexes
NAIL_BITING_THRESH = 20
NAIL_BITING_DURATION = 5  # Seconds for sustained detection
NAIL_BITING_DEPTH_THRESH = 0.1 
NAIL_CONTACT_MARGIN = 4 
FACE_TOUCH_MARGIN = 6  # Margin inside face box for touch detection
FACE_TOUCH_DURATION = 3 
FACE_TOUCH_COOLDOWN = 60
TARGET_FRAME_FPS = 24
VIDEO_PROCESS_EVERY = 2
STATS_PROCESS_EVERY = 2
MAX_PINNED_GRAPHS = 3

# Utilities
def append_log_line(line: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} {line}\n")
    except Exception:
        pass
def log_exc():
    append_log_line("EXC: " + traceback.format_exc())
def load_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        log_exc()
    return default if default is not None else {}
def save_json(path, obj):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)
    except Exception:
        log_exc()
def notify_os(title: str, message: str):
    try:
        if sys.platform == "darwin":
            subprocess.Popen(['osascript','-e', 'display notification "{}" with title "{}"'.format(message, title)])
            return
        if sys.platform.startswith("linux"):
            import shutil
            if shutil.which("notify-send"):
                subprocess.Popen(['notify-send', title, message])
                return
        if sys.platform.startswith("win"):
            ps = '''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$txt = $xml.GetElementsByTagName("text")
$txt.Item(0).AppendChild($xml.CreateTextNode("{0}")) | Out-Null
$txt.Item(1).AppendChild($xml.CreateTextNode("{1}")) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("ScreenGuardian")
$notifier.Show($toast)
            '''.format(title, message)
            subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    except Exception:
        log_exc()
def clamp(v, a, b): return max(a, min(b, v))
def format_time_dynamic(seconds: int) -> str:
    if seconds < 3600: # Minutes and seconds
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}m {secs}s"
    else: # Hours and minutes
        mins = seconds // 60
        hours = mins // 60
        mins = mins % 60
        return f"{hours}h {mins}m"
def get_camera_cap():
    index_env = os.getenv("SG_CAMERA_INDEX")
    backend_env = os.getenv("SG_CAMERA_BACKEND")
    try:
        indices = [int(index_env)] if index_env is not None else list(range(5))
    except Exception:
        indices = list(range(5))

    backend_names = []
    if backend_env:
        backend_names.append(backend_env.strip())
    if sys.platform == "darwin":
        backend_names.extend(["CAP_AVFOUNDATION", "CAP_ANY"])
    elif sys.platform.startswith("win"):
        backend_names.extend(["CAP_MSMF", "CAP_DSHOW", "CAP_ANY"])
    else:
        backend_names.extend(["CAP_V4L2", "CAP_ANY"])

    def _backend_value(name: str):
        return getattr(cv2, name, None)

    tried = []
    for backend_name in backend_names:
        backend_flag = _backend_value(backend_name)
        for idx in indices:
            tried.append(f"{backend_name}:{idx}")
            cap = None
            try:
                cap = cv2.VideoCapture(idx) if backend_flag is None else cv2.VideoCapture(idx, backend_flag)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    append_log_line(f"Camera opened idx={idx} backend={backend_name}")
                    return cap
            except Exception:
                log_exc()
            finally:
                if cap is not None and not cap.isOpened():
                    try:
                        cap.release()
                    except Exception:
                        pass
    append_log_line(f"Camera open failed. Tried: {', '.join(tried)}")
    return None
# DB
conn = None
cursor = None
try:
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS alerts (timestamp TEXT, message TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS screen_time (date TEXT PRIMARY KEY, duration_sec INTEGER NOT NULL DEFAULT 0)')
    cursor.execute('CREATE TABLE IF NOT EXISTS posture_time (date TEXT PRIMARY KEY, seconds INTEGER NOT NULL DEFAULT 0)')
    cursor.execute('CREATE TABLE IF NOT EXISTS distance_log (date TEXT PRIMARY KEY, avg_distance_cm REAL, count INTEGER)')
    cursor.execute('CREATE TABLE IF NOT EXISTS screen_hourly (date_hour TEXT PRIMARY KEY, duration_sec INTEGER)')
    cursor.execute('CREATE TABLE IF NOT EXISTS posture_hourly (date_hour TEXT PRIMARY KEY, seconds INTEGER)')
    cursor.execute('CREATE TABLE IF NOT EXISTS distance_hourly (date_hour TEXT PRIMARY KEY, sum_distance_cm REAL, count INTEGER)')
    try:
        cursor.execute("ALTER TABLE distance_log ADD COLUMN count INTEGER")
    except sqlite3.OperationalError:
        pass # already exists
    def _rebuild_table(table, create_sql, columns, select_sql_tpl):
        try:
            info = cursor.execute(f"PRAGMA table_info({table})").fetchall()
            if not info:
                cursor.execute(f"CREATE TABLE IF NOT EXISTS {table} ({create_sql})")
                return
            pk_cols = [col for col in info if col[5] != 0]
            duplicates = cursor.execute(
                f"SELECT COUNT(*) FROM (SELECT date FROM {table} GROUP BY date HAVING COUNT(*)>1)"
            ).fetchone()[0]
            if pk_cols and duplicates == 0:
                return
            tmp = f"{table}_tmp"
            cursor.execute(f"DROP TABLE IF EXISTS {tmp}")
            cursor.execute(f"CREATE TABLE {tmp} ({create_sql})")
            col_list = ", ".join(columns)
            select_sql = select_sql_tpl.format(table=table, columns=col_list)
            cursor.execute(f"INSERT INTO {tmp} ({col_list}) {select_sql}")
            cursor.execute(f"DROP TABLE {table}")
            cursor.execute(f"ALTER TABLE {tmp} RENAME TO {table}")
        except Exception:
            log_exc()
    _rebuild_table(
        "screen_time",
        "date TEXT PRIMARY KEY, duration_sec INTEGER NOT NULL DEFAULT 0",
        ["date", "duration_sec"],
        "SELECT date, COALESCE(MAX(duration_sec), 0) FROM {table} GROUP BY date"
    )
    _rebuild_table(
        "posture_time",
        "date TEXT PRIMARY KEY, seconds INTEGER NOT NULL DEFAULT 0",
        ["date", "seconds"],
        "SELECT date, COALESCE(MAX(seconds), 0) FROM {table} GROUP BY date"
    )
    _rebuild_table(
        "distance_log",
        "date TEXT PRIMARY KEY, avg_distance_cm REAL, count INTEGER",
        ["date", "avg_distance_cm", "count"],
        "SELECT date, avg_distance_cm, COALESCE(count, 0) FROM {table} WHERE rowid IN (SELECT MAX(rowid) FROM {table} GROUP BY date)"
    )
    conn.commit()
except Exception:
    log_exc()
    conn = None; cursor = None
# Main App
class ScreenGuardianApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ScreenGuardian")
        self.geometry("1280x820")
        ctk.set_appearance_mode("System")
        self.accent_color = "#a58c64"
        cfg = load_json(CONFIG_FILE, {})
        self.accent_color = cfg.get("accent_color", self.accent_color)
        self.delay_seconds = int(cfg.get("delay_seconds", 6))
        self.display_mode = cfg.get("display_mode", "Both")
        self.unit = cfg.get("unit", "cm")
        self.min_distance_cm = float(cfg.get("min_distance_cm", 50.8))
        self.theme_mode = cfg.get("theme_mode", "System")
        self.enable_posture = bool(cfg.get("enable_posture", True))
        self.enable_distance = bool(cfg.get("enable_distance", True))
        self.enable_twenty = bool(cfg.get("enable_twenty", True))
        self.enable_nail_biting = bool(cfg.get("enable_nail_biting", True))
        self.enable_face_touch = bool(cfg.get("enable_face_touch", True))
        self.performance_mode = bool(cfg.get("performance_mode", False))
        self.posture_vert_thresh = float(cfg.get("posture_vert_thresh", 0.70))
        self.posture_eye_tilt_thresh = float(cfg.get("posture_eye_tilt_thresh", 0.08))
        self.posture_neck_thresh = float(cfg.get("posture_neck_thresh", 0.55))
        self.posture_depth_thresh = float(cfg.get("posture_depth_thresh", 1.22))
        self.active_alert_appear_seconds = float(cfg.get("active_alert_appear_seconds", 1.0))
        self.calib = load_json(CALIB_FILE, {})
        self.focal_length = float(self.calib.get("focal_length", 700))
        self.real_ipd_cm = float(self.calib.get("real_ipd_cm", 6.3))
        self.default_period = cfg.get("default_period", "Week")
        self.current_period = self.default_period
        self.current_chart_type = "Bar"
        self.current_view_start = None
        self.first_run = cfg.get("first_run", True)
        self.running = True
        self.frame_lock = threading.Lock()
        self.latest_pil = None
        self.display_draw_w = 800
        self.display_draw_h = int(self.display_draw_w * VIDEO_ASPECT[1] / VIDEO_ASPECT[0])
        self.last_face_box = None
        self.last_eyes = []
        self._shoulder_history = []
        self._smoothed_shoulder_mid = None
        self.distances_buffer = []
        self._smoothed_distance_cm = None
        self._depth_baseline = None
        self.visible_start = None
        self.visible_seconds = 0
        self.slouch_session_start = None
        self.slouch_accum_seconds = 0
        self.active_alerts = set()
        self.active_lock = threading.Lock()
        self._partial_missing_count = 0
        self._fully_missing_count = 0
        self.posture_reasons = set()
        self.last_save_time = time.time()
        self.saved_visible_seconds = 0
        self.saved_slouch_seconds = 0
        self.today_screen_sec = 0
        self.today_posture_sec = 0
        self.today_avg_cm = None
        self.today_distance_count = 0
        self.yesterday_screen_sec = 0
        self.yesterday_posture_sec = 0
        self.yesterday_avg_cm = None
        self.today_posture_alerts = 0
        self.today_distance_alerts = 0
        self.today_face_touch_alerts = 0
        self.video_process_every = 3 if self.performance_mode else VIDEO_PROCESS_EVERY
        self.session_posture_alerts = 0
        self.session_distance_alerts = 0
        self.session_face_touch_alerts = 0
        self.data_erase_state = {"armed": False}
        self.alert_panel_visible = False
        self.alert_panel = None
        self.alert_log_btn = None
        self.calendar_selected_date = None
        self.calendar_year = None
        self.calendar_month = None
        self._head_turn_start = None
        self._head_turn_duration = 0
        self._head_rot_start = None
        self._horizontal_offset_history = []
        self._eye_tilt_history = []
        self.today_horizontal_offset_avg = 0
        self.today_eye_tilt_avg = 0
        self.today_head_turn_time = 0
        self.today_posture_score = 0
        self.today_session_count = 0
        self._session_start = None
        self._session_count = 0
        self.pinned_graphs = cfg.get("pinned_graphs", ["Screen Time", "Average Distance"])
        self.pinned_graphs = list(dict.fromkeys(self.pinned_graphs))[:MAX_PINNED_GRAPHS]
        self.pinned_canvases = []
        self._stats_period_stack = []
        self._suppress_period_callback = False
        self._suppress_type_callback = False
        self._back_btn_grid_kwargs = None
        self._back_btn_visible = False
        self._layout_resize_active = False
        self._last_video_layout_height = None
        self._last_dashboard_height = None
        self.video_base_w = self.display_draw_w
        self.video_base_h = self.display_draw_h
        self._pending_layout_height = None
        self._layout_sync_job = None
        self.last_hour = None
        self.pending_hour_visible_seconds = 0
        self.pending_hour_slouch_seconds = 0
        self.pending_hour_distance_sum = 0.0
        self.pending_hour_distance_count = 0
        self.pending_distance_sum = 0.0
        self.pending_distance_count = 0
        self.distance_sum_total = 0.0
        self.distance_count_total = 0
        self._prev_total_visible = 0
        self._prev_total_slouch = 0
        self._nail_biting_start = None
        self._nail_biting_detected = False
        self._face_touch_start = None
        self._face_touch_detected = False
        self._face_touch_active_since = None
        self._last_detected_shoulders = None
        self._last_mouth_box = None
        self.last_hand_landmarks = None
        self.frame_queue = queue.Queue(maxsize=1)
        if cursor:
            try:
                today_str = date.today().isoformat()
                yest_str = (date.today() - timedelta(days=1)).isoformat()
                cursor.execute("SELECT duration_sec FROM screen_time WHERE date = ?", (today_str,))
                res = cursor.fetchone()
                self.today_screen_sec = res[0] if res else 0
                cursor.execute("SELECT seconds FROM posture_time WHERE date = ?", (today_str,))
                res = cursor.fetchone()
                self.today_posture_sec = res[0] if res else 0
                cursor.execute("SELECT avg_distance_cm, count FROM distance_log WHERE date = ?", (today_str,))
                res = cursor.fetchone()
                if res:
                    self.today_avg_cm = res[0] if res[0] is not None else None
                    self.today_distance_count = res[1] or 0
                cursor.execute("SELECT duration_sec FROM screen_time WHERE date = ?", (yest_str,))
                res = cursor.fetchone()
                self.yesterday_screen_sec = res[0] if res else 0
                cursor.execute("SELECT seconds FROM posture_time WHERE date = ?", (yest_str,))
                res = cursor.fetchone()
                self.yesterday_posture_sec = res[0] if res else 0
                cursor.execute("SELECT avg_distance_cm FROM distance_log WHERE date = ?", (yest_str,))
                res = cursor.fetchone()
                self.yesterday_avg_cm = res[0] if res else None
                cursor.execute("SELECT count(*) FROM alerts WHERE timestamp LIKE ? AND message LIKE '%Bad Posture%'", (today_str + '%',))
                self.today_posture_alerts = cursor.fetchone()[0]
                cursor.execute("SELECT count(*) FROM alerts WHERE timestamp LIKE ? AND message LIKE '%Distance%'", (today_str + '%',))
                self.today_distance_alerts = cursor.fetchone()[0]
                cursor.execute("SELECT count(*) FROM alerts WHERE timestamp LIKE ? AND message LIKE '%Face Touch%'", (today_str + '%',))
                self.today_face_touch_alerts = cursor.fetchone()[0]
            except Exception:
                log_exc()
        base_avg = self.today_avg_cm if self.today_avg_cm is not None else 0.0
        self.distance_sum_total = base_avg * max(self.today_distance_count, 0)
        self.distance_count_total = max(self.today_distance_count, 0)
        self._prev_total_visible = self.visible_seconds
        self._prev_total_slouch = self.slouch_accum_seconds
        self._build_ui()
        self._apply_accent_theme()
        self._update_feedback()  # Initial update
        if self.first_run:
            self._first_run_setup()
        self.after(200, self._poll_latest_frame)
        self.video_thread = threading.Thread(target=self._video_worker, daemon=True)
        self.video_thread.start()
        self.stats_thread = threading.Thread(target=self._stats_worker, daemon=True)
        self.stats_thread.start()
        self.after(GRAPH_REFRESH_SEC * 1000, self._refresh_pinned_graphs)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Configure>", self._on_window_resize)
    def _first_run_setup(self):
        try:
            message = (
                "Welcome to ScreenGuardian\n\n"
                "Privacy First: ScreenGuardian keeps all processing local. No data is ever transmitted, and all metrics are stored only on your device. If you ever feel the need to erase all data, use the PANIC DATA ERASE Button in Settings to wipe all data (screen time, alert counts, etc.).\n\n"
                "Data Control: The panic button opens a dedicated window explaining what will be wiped and requires a second confirmation before anything is deleted, so you stay in charge.\n\n"
                "Power Consumption: Running this app increases power usage. If on a laptop, connecting to power is generally reccomended.\n\n"
                "Would you like to start guided calibration now?"
            )
            res = messagebox.askyesno("First Time Setup", message)
            if res:
                self._guided_calibration_prompt()
            cfg = load_json(CONFIG_FILE, {})
            cfg["first_run"] = False
            save_json(CONFIG_FILE, cfg)
            self.first_run = False
        except Exception:
            log_exc()
    # UI Building
    def _build_ui(self):
        try:
            self.grid_rowconfigure(0, weight=1)
            self.grid_columnconfigure(0, weight=0, minsize=260)
            self.grid_columnconfigure(1, weight=1)
            self.sidebar_outer = ctk.CTkFrame(self, width=260, corner_radius=8)
            self.sidebar_outer.grid(row=0, column=0, sticky="nswe", padx=(12,6), pady=12)
            self.sidebar = ctk.CTkScrollableFrame(self.sidebar_outer, corner_radius=6)
            self.sidebar.pack(fill="both", expand=True, padx=8, pady=8)
            title_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent", corner_radius=0)
            title_frame.pack(fill="x", padx=8, pady=(6,4))
            ctk.CTkLabel(title_frame, text="Settings", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w")
            content_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent", corner_radius=0)
            content_frame.pack(fill="both", expand=True, padx=8, pady=(0,8))
            self.calib_btn = ctk.CTkButton(content_frame, text="Full Calibration", fg_color=self.accent_color, command=self._guided_calibration_prompt)
            self.calib_btn.pack(fill="x", pady=(0,8))
            row = ctk.CTkFrame(content_frame, fg_color="transparent")
            row.pack(fill="x", pady=(4,2))
            ctk.CTkLabel(row, text="Delay (s)").pack(side="left", anchor="w")
            self.info_delay = ctk.CTkButton(row, text="i", width=28, height=24, fg_color=self.accent_color, command=lambda: messagebox.showinfo("Delay (s)", "Seconds to wait after detection before sending a notification. Increase to reduce sensitivity."))
            self.info_delay.pack(side="right")
            self.delay_slider = ctk.CTkSlider(content_frame, from_=3, to=180, command=self._set_delay)
            self.delay_slider.set(self.delay_seconds); self.delay_slider.pack(fill="x", pady=(4,2))
            self.delay_value = ctk.CTkLabel(content_frame, text=f"{self.delay_seconds} s"); self.delay_value.pack(anchor="e")
            row2 = ctk.CTkFrame(content_frame, fg_color="transparent"); row2.pack(fill="x", pady=(8,2))
            ctk.CTkLabel(row2, text="Minimum Distance").pack(side="left", anchor="w")
            self.info_min = ctk.CTkButton(row2, text="i", width=28, height=24, fg_color=self.accent_color, command=lambda: messagebox.showinfo("Minimum Distance", "Minimum recommended face-to-screen distance. Alerts trigger when closer."))
            self.info_min.pack(side="right")
            if self.unit == "cm":
                self.min_distance_slider = ctk.CTkSlider(content_frame, from_=30, to=120, command=self._set_min_distance_from_slider)
                self.min_distance_slider.set(self.min_distance_cm); self.min_distance_slider.pack(fill="x", pady=(4,2))
                self.min_distance_value = ctk.CTkLabel(content_frame, text=f"{int(self.min_distance_cm)} cm")
            else:
                self.min_distance_slider = ctk.CTkSlider(content_frame, from_=12, to=48, command=self._set_min_distance_from_slider)
                self.min_distance_slider.set(round(self.min_distance_cm / 2.54,1)); self.min_distance_slider.pack(fill="x", pady=(4,2))
                self.min_distance_value = ctk.CTkLabel(content_frame, text=f"{round(self.min_distance_cm / 2.54,1)} in")
            self.min_distance_value.pack(anchor="e")
            ctk.CTkLabel(content_frame, text="Alerts").pack(anchor="w", pady=(8,2))
            self.posture_switch = ctk.CTkSwitch(content_frame, text="Posture Alerts", command=self._toggle_posture)
            self.posture_switch.pack(anchor="w", pady=(2,2))
            (self.posture_switch.select() if self.enable_posture else self.posture_switch.deselect())
            self.distance_switch = ctk.CTkSwitch(content_frame, text="Distance Alerts", command=self._toggle_distance)
            self.distance_switch.pack(anchor="w", pady=(2,2))
            (self.distance_switch.select() if self.enable_distance else self.distance_switch.deselect())
            self.nail_biting_switch = ctk.CTkSwitch(content_frame, text="Nail Biting Alerts", command=self._toggle_nail_biting)
            self.nail_biting_switch.pack(anchor="w", pady=(2,2))
            (self.nail_biting_switch.select() if self.enable_nail_biting else self.nail_biting_switch.deselect())
            self.face_touch_switch = ctk.CTkSwitch(content_frame, text="Face Touch Alerts", command=self._toggle_face_touch)
            self.face_touch_switch.pack(anchor="w", pady=(2,2))
            (self.face_touch_switch.select() if self.enable_face_touch else self.face_touch_switch.deselect())
            self.twenty_switch = ctk.CTkSwitch(content_frame, text="20-20-20 Reminder", command=self._toggle_twenty)
            self.twenty_switch.pack(anchor="w", pady=(2,8))
            (self.twenty_switch.select() if self.enable_twenty else self.twenty_switch.deselect())
            self.performance_switch = ctk.CTkSwitch(content_frame, text="Resource Saver", command=self._toggle_performance_mode)
            self.performance_switch.pack(anchor="w", pady=(2,8))
            (self.performance_switch.select() if self.performance_mode else self.performance_switch.deselect())
            ctk.CTkLabel(content_frame, text="Accent Color").pack(anchor="w", pady=(4,2))
            self.color_btn = ctk.CTkButton(content_frame, text="Pick Color", fg_color=self.accent_color, command=self._pick_accent_color)
            self.color_btn.pack(fill="x", pady=(2,8))
            ctk.CTkLabel(content_frame, text="Theme").pack(anchor="w", pady=(0,0))
            self.theme_option = ctk.CTkOptionMenu(content_frame, values=["System","Light","Dark"], command=self._set_theme)
            self.theme_option.set(self.theme_mode); self.theme_option.pack(fill="x", pady=(6,8))
            ctk.CTkLabel(content_frame, text="Display Mode").pack(anchor="w", pady=(0,0))
            self.mode_option = ctk.CTkOptionMenu(content_frame, values=["Video","Landmarks","Both"], command=self._set_mode)
            self.mode_option.set(self.display_mode); self.mode_option.pack(fill="x", pady=(6,8))
            ctk.CTkLabel(content_frame, text="Units").pack(anchor="w", pady=(0,0))
            self.unit_option = ctk.CTkOptionMenu(content_frame, values=["cm","in"], command=self._set_unit)
            self.unit_option.set(self.unit); self.unit_option.pack(fill="x", pady=(6,8))
            ctk.CTkLabel(content_frame, text="Default Graph Period").pack(anchor="w", pady=(0,0))
            self.period_option = ctk.CTkOptionMenu(content_frame, values=["Day","Week","Month"], command=self._set_period)
            self.period_option.set(self.default_period); self.period_option.pack(fill="x", pady=(6,8))
            self.docs_btn = ctk.CTkButton(content_frame, text="Documentation", fg_color=self.accent_color, command=lambda: webbrowser.open(DOCS_URL))
            self.docs_btn.pack(fill="x", pady=(8,4))
            self.support_btn = ctk.CTkButton(content_frame, text="Contact Support", fg_color=self.accent_color, command=self._contact_support)
            self.support_btn.pack(fill="x", pady=(4,4))
            self.coffee_btn = ctk.CTkButton(content_frame, text="Buy me a coffee", fg_color=self.accent_color, command=lambda: webbrowser.open(BUY_COFFEE_URL))
            self.coffee_btn.pack(fill="x", pady=(4,12))
            self.panic_btn = ctk.CTkButton(
                content_frame,
                text="PANIC: Erase All Data",
                fg_color="#b00020",
                hover_color="#7a0015",
                font=ctk.CTkFont(size=15, weight="bold"),
                height=48,
                command=self._open_data_erase_window
            )
            self.panic_btn.pack(fill="x", pady=(0,12))
            self.main = ctk.CTkFrame(self, corner_radius=8)
            self.main.grid(row=0, column=1, sticky="nsew", padx=(6,12), pady=12)
            self.main.grid_rowconfigure(0, weight=0) # Widget sizing begins here
            self.main.grid_rowconfigure(1, weight=1) 
            self.main.grid_rowconfigure(2, weight=0) 
            self.main.grid_columnconfigure(0, weight=3)
            self.main.grid_columnconfigure(1, weight=1)
            self.toolbar = ctk.CTkFrame(self.main, corner_radius=0)
            self.toolbar.grid(row=0, column=0, columnspan=2, sticky="we", pady=(6,2), padx=8)
            self.toggle_btn = ctk.CTkButton(self.toolbar, text="<< Hide Settings", width=140, fg_color=self.accent_color, command=self._toggle_sidebar)
            self.toggle_btn.pack(side="left", padx=(6,6), pady=6)
            self.stats_btn = ctk.CTkButton(self.toolbar, text="View Statistics", width=140, fg_color=self.accent_color, command=self._open_stats_window)
            self.stats_btn.pack(side="left", padx=(6,6), pady=6)
            self.alert_log_btn = ctk.CTkButton(self.toolbar, text="Alert Log", width=140, fg_color=self.accent_color, command=self._toggle_alert_panel)
            self.alert_log_btn.pack(side="right", padx=(6,6), pady=6)
            self.video_container = ctk.CTkFrame(self.main, corner_radius=6)
            self.video_container.grid(row=1, column=0, sticky="nsew", padx=(8,4), pady=8)
            self.video_container.grid_rowconfigure(0, weight=1)
            self.video_container.grid_columnconfigure(0, weight=1)
            self.video_container.grid_propagate(False)
            self.video_outer = ctk.CTkFrame(self.video_container, corner_radius=6)
            self.video_outer.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
            self.video_outer.grid_propagate(False)
            self.video_outer.bind("<Configure>", self._on_video_outer_resize)
            self.video_label = ctk.CTkLabel(self.video_outer, text="", width=self.display_draw_w, height=self.display_draw_h)
            self.video_label.place(relx=0.5, rely=0.5, anchor="center")
            self.right_frame = ctk.CTkFrame(self.main, corner_radius=6)
            self.right_frame.grid(row=1, column=1, sticky="nsew", padx=(4,8), pady=8)
            self.right_frame.grid_rowconfigure(0, weight=0)
            self.right_frame.grid_rowconfigure(1, weight=0)
            self.right_frame.grid_rowconfigure(2, weight=1)
            self.right_frame.grid_columnconfigure(0, weight=1)
            self.right_frame.grid_propagate(False)
            ctk.CTkLabel(self.right_frame, text="Session Statistics", font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, sticky="w", padx=8, pady=(8,4))
            self.stats_card = ctk.CTkFrame(self.right_frame, corner_radius=6)
            self.stats_card.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0,6))
            self.stats_card.grid_rowconfigure(0, weight=0)
            self.stats_card.grid_columnconfigure(0, weight=1)
            self.stats_card.grid_propagate(True)
            self.distance_label = ctk.CTkLabel(self.stats_card, text="Screen Distance: N/A", anchor="w"); self.distance_label.pack(fill="x", padx=8, pady=1)
            self.avg_distance_label = ctk.CTkLabel(self.stats_card, text="Average Distance (session): N/A", anchor="w"); self.avg_distance_label.pack(fill="x", padx=8, pady=1)
            self.screen_time_label = ctk.CTkLabel(self.stats_card, text="Screen Time: 0s", anchor="w"); self.screen_time_label.pack(fill="x", padx=8, pady=1)
            self.time_bad_posture_label = ctk.CTkLabel(self.stats_card, text="Time with Bad Posture (session): 0s", anchor="w"); self.time_bad_posture_label.pack(fill="x", padx=8, pady=1)
            self.session_posture_alerts_label = ctk.CTkLabel(self.stats_card, text=f"Session Posture Alerts: {self.session_posture_alerts}", anchor="w"); self.session_posture_alerts_label.pack(fill="x", padx=8, pady=1)
            self.session_distance_alerts_label = ctk.CTkLabel(self.stats_card, text=f"Session Distance Alerts: {self.session_distance_alerts}", anchor="w"); self.session_distance_alerts_label.pack(fill="x", padx=8, pady=1)
            self.session_face_touch_alerts_label = ctk.CTkLabel(self.stats_card, text=f"Session Face Touch Alerts: {self.session_face_touch_alerts}", anchor="w"); self.session_face_touch_alerts_label.pack(fill="x", padx=8, pady=1)
            self.active_card = ctk.CTkFrame(self.right_frame, corner_radius=6)
            self.active_card.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0,6))
            self.active_card.grid_rowconfigure(0, weight=1)
            self.active_card.grid_columnconfigure(0, weight=1)
            self.active_card.grid_propagate(True)
            ctk.CTkLabel(self.active_card, text="Active Alerts", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=8, pady=(6,4))
            self.active_list = ctk.CTkTextbox(self.active_card, wrap="word", state="disabled")
            self.active_list.pack(fill="both", expand=True, padx=8, pady=(0,8))
            self.dashboard_card = ctk.CTkFrame(self.main, corner_radius=6, height=DASHBOARD_MIN_HEIGHT)
            self.dashboard_card.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=8, pady=(0,8))
            self.dashboard_card.grid_rowconfigure(0, weight=0)
            self.dashboard_card.grid_rowconfigure(1, weight=1)
            self.dashboard_card.grid_columnconfigure(0, weight=1)
            self.dashboard_card.grid_propagate(False)
            header_frame = ctk.CTkFrame(self.dashboard_card, fg_color="transparent")
            header_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(6,4))
            header_frame.grid_columnconfigure(0, weight=1)
            header_frame.grid_columnconfigure(1, weight=0)
            ctk.CTkLabel(header_frame, text="Dashboard", font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, sticky="w")
            self.pin_button = ctk.CTkButton(header_frame, text="Pin Graph", fg_color=self.accent_color, command=self._show_pin_menu, width=120)
            self.pin_button.grid(row=0, column=1, sticky="e")
            self.dashboard_inner = ctk.CTkScrollableFrame(self.dashboard_card, corner_radius=6)
            self.dashboard_inner.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0,8))
            self.feedback_frame = ctk.CTkFrame(self.dashboard_inner, fg_color="transparent")
            self.feedback_frame.pack(fill="x", padx=0, pady=0)
            self.pinned_graph_frame = ctk.CTkFrame(self.dashboard_inner, fg_color="transparent")
            self.pinned_graph_frame.pack(fill="x", expand=False)
            self.pinned_graph_frame.grid_rowconfigure(0, weight=1)
            for col in range(MAX_PINNED_GRAPHS):
                self.pinned_graph_frame.grid_columnconfigure(col, weight=1, uniform="pinned", minsize=1)
            self._load_pinned_graphs()
            self._build_alert_panel()
            self._update_feedback()
            self._apply_video_height_constraints(self.display_draw_h)
        except Exception:
            log_exc()
            raise
    def _show_pin_menu(self):
        try:
            menu = Menu(self, tearoff=0)
            graphs = ["Screen Time", "Posture Alerts", "Average Distance", "Distance Alerts", "Nail Biting Alerts", "Face Touch Alerts"]
            for g in graphs:
                if g not in self.pinned_graphs:
                    menu.add_command(label=f"Pin {g}", command=lambda name=g: self._pin_graph(name))
            if self.pinned_graphs:
                menu.add_separator()
                for g in self.pinned_graphs:
                    menu.add_command(label=f"Unpin {g}", command=lambda name=g: self._unpin_graph(name))
            menu.tk_popup(self.pin_button.winfo_rootx(), self.pin_button.winfo_rooty() + self.pin_button.winfo_height())
        except Exception:
            log_exc()
    def _pin_graph(self, name):
        try:
            if name in self.pinned_graphs:
                return
            if len(self.pinned_graphs) >= MAX_PINNED_GRAPHS:
                messagebox.showinfo("Pinned Graphs", f"You can pin up to {MAX_PINNED_GRAPHS} graphs.")
                return
            self.pinned_graphs.append(name)
            self._reload_pinned_graphs()
        except Exception:
            log_exc()
    def _unpin_graph(self, name):
        try:
            if name in self.pinned_graphs:
                self.pinned_graphs.remove(name)
                self._reload_pinned_graphs()
        except Exception:
            log_exc()
    def _reload_pinned_graphs(self):
        try:
            for child in self.pinned_graph_frame.winfo_children():
                child.destroy()
            self.pinned_canvases = []
            self._load_pinned_graphs()
        except Exception:
            log_exc()
    def _load_pinned_graphs(self):
        try:
            n = len(self.pinned_graphs)
            if n == 0:
                return
            for col in range(MAX_PINNED_GRAPHS):
                self.pinned_graph_frame.grid_columnconfigure(col, weight=1, uniform="pinned", minsize=1)
            for i, graph_name in enumerate(self.pinned_graphs):
                fig, ax = plt.subplots(figsize=(3.2, 1.8)) 
                canvas = FigureCanvasTkAgg(fig, master=self.pinned_graph_frame)
                canvas.get_tk_widget().grid(row=0, column=i, sticky="nsew", padx=2, pady=2)
                self.pinned_canvases.append(canvas)
                if graph_name == "Screen Time":
                    self._draw_screen_chart(fig, ax, canvas, self.default_period, is_pinned=True)
                elif graph_name == "Posture Alerts":
                    self._draw_posture_alerts_chart(fig, ax, canvas, self.default_period, is_pinned=True)
                elif graph_name == "Average Distance":
                    self._draw_distance_chart(fig, ax, canvas, self.default_period, is_pinned=True)
                elif graph_name == "Distance Alerts":
                    self._draw_distance_notifications_chart(fig, ax, canvas, self.default_period, is_pinned=True)
                elif graph_name == "Nail Biting Alerts":
                    self._draw_nail_biting_chart(fig, ax, canvas, self.default_period, is_pinned=True)
                elif graph_name == "Face Touch Alerts":
                    self._draw_face_touch_chart(fig, ax, canvas, self.default_period, is_pinned=True)
        except Exception:
            log_exc()
    def _refresh_pinned_graphs(self):
        try:
            self._reload_pinned_graphs()
            self.after(GRAPH_REFRESH_SEC * 1000, self._refresh_pinned_graphs)
        except Exception:
            log_exc()
    def _apply_video_height_constraints(self, requested_height: int) -> int:
        try:
            if getattr(self, "_layout_resize_active", False):
                fallback = getattr(self, "_last_video_layout_height", None)
                return fallback if fallback is not None else max(120, int(requested_height))
            if not hasattr(self, "main"):
                return max(120, int(requested_height))
            requested_height = max(120, int(requested_height))
            window_height = self.winfo_height()
            main_height = self.main.winfo_height()
            toolbar_height = self.toolbar.winfo_height() if hasattr(self, "toolbar") else 0
            if window_height <= 1:
                window_height = max(main_height, requested_height + DASHBOARD_MIN_HEIGHT + toolbar_height + 120)
            if main_height <= 1:
                main_height = window_height
            min_total = toolbar_height + requested_height + DASHBOARD_MIN_HEIGHT
            if window_height < min_total:
                window_height = min_total
            dashboard_target = max(DASHBOARD_MIN_HEIGHT, int(window_height * DASHBOARD_WINDOW_RATIO))
            max_dashboard = max(window_height - toolbar_height - 120, DASHBOARD_MIN_HEIGHT)
            dashboard_height = min(dashboard_target, max_dashboard)
            available_for_top = max(window_height - toolbar_height - dashboard_height, 120)
            max_top_height = int(window_height * TOP_MAX_HEIGHT_RATIO)
            if max_top_height <= 0:
                max_top_height = available_for_top
            final_height = min(requested_height, max_top_height, available_for_top)
            final_height = max(120, final_height)
            self._layout_resize_active = True
            try:
                def _to_int(value):
                    try:
                        return int(float(value))
                    except Exception:
                        return 0
                if getattr(self, "_last_video_layout_height", None) != final_height:
                    self.main.grid_rowconfigure(1, weight=1, minsize=final_height)
                    if hasattr(self, "video_container"):
                        current = _to_int(self.video_container.cget("height"))
                        if current != final_height:
                            self.video_container.configure(height=final_height)
                    if hasattr(self, "video_outer"):
                        current = _to_int(self.video_outer.cget("height"))
                        if current != final_height:
                            self.video_outer.configure(height=final_height)
                    if hasattr(self, "right_frame"):
                        current = _to_int(self.right_frame.cget("height"))
                        if current != final_height:
                            self.right_frame.configure(height=final_height)
                    self._last_video_layout_height = final_height
                if getattr(self, "_last_dashboard_height", None) != dashboard_height:
                    self.main.grid_rowconfigure(2, weight=0, minsize=dashboard_height)
                    if hasattr(self, "dashboard_card"):
                        current = _to_int(self.dashboard_card.cget("height"))
                        if current != dashboard_height:
                            self.dashboard_card.configure(height=dashboard_height)
                    self._last_dashboard_height = dashboard_height
            finally:
                self._layout_resize_active = False
            return final_height
        except Exception:
            log_exc()
            return max(120, int(requested_height))
    # UI helpers
    def _contrast_for_accent(self) -> str:
        try:
            ac = self.accent_color.lstrip("#")
            r,g,b = int(ac[0:2],16), int(ac[2:4],16), int(ac[4:6],16)
            luminance = (0.299*r + 0.587*g + 0.114*b)/255.0
            return "#FFFFFF" if luminance < 0.6 else "#000000"
        except Exception:
            return "#FFFFFF"
    def _darken_hex(self, hex_color, factor=0.8):
        try:
            hex_color = hex_color.lstrip('#')
            r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
            r, g, b = int(r * factor), int(g * factor), int(b * factor)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color
    def _brighten_hex(self, hex_color, factor=1.2):
        try:
            hex_color = hex_color.lstrip('#')
            r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
            r, g, b = min(255, int(r * factor)), min(255, int(g * factor)), min(255, int(b * factor))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color
    def _apply_accent_theme(self, window=None):
        try:
            contrast = self._contrast_for_accent()
            gray_handle = "#808080"
            darker = self._darken_hex(self.accent_color)
            brighter = self._brighten_hex(self.accent_color)
            neutral_gray = "#4a4a4a" if ctk.get_appearance_mode().lower() == 'dark' else "#d3d3d3"
            target = window or self
            for widget in target.winfo_children():
                if isinstance(widget, ctk.CTkButton):
                    widget.configure(fg_color=self.accent_color, hover_color=darker, text_color=contrast)
                elif isinstance(widget, ctk.CTkSlider):
                    widget.configure(progress_color=self.accent_color, button_color=gray_handle, button_hover_color=brighter)
                elif isinstance(widget, ctk.CTkSwitch):
                    widget.configure(progress_color=self.accent_color, button_color=gray_handle, button_hover_color=brighter)
                elif isinstance(widget, ctk.CTkOptionMenu):
                    widget.configure(fg_color=self.accent_color, button_color=self.accent_color, button_hover_color=darker, text_color=contrast, dropdown_fg_color=self.accent_color, dropdown_hover_color=darker, dropdown_text_color=contrast)
                elif isinstance(widget, ctk.CTkTabview):
                    widget.configure(segmented_button_fg_color=neutral_gray, segmented_button_selected_color=self.accent_color, segmented_button_selected_hover_color=darker)
                if hasattr(widget, "winfo_children"):
                    self._apply_accent_theme(widget)
            if hasattr(self, "calendar_buttons"):
                self._update_calendar_highlight()
        except Exception:
            log_exc()
    def _unsaved_visible_seconds(self) -> int:
        try:
            now = time.time()
            current_visible = self.visible_seconds + (int(now - self.visible_start) if self.visible_start else 0)
            return max(0, current_visible - self.saved_visible_seconds)
        except Exception:
            log_exc()
            return 0
    def _unsaved_slouch_seconds(self) -> int:
        try:
            now = time.time()
            current_slouch = self.slouch_accum_seconds + (int(now - self.slouch_session_start) if self.slouch_session_start else 0)
            return max(0, current_slouch - self.saved_slouch_seconds)
        except Exception:
            log_exc()
            return 0
    def _unsaved_distance_sum_count(self) -> tuple:
        try:
            return max(0.0, self.pending_distance_sum), max(0, self.pending_distance_count)
        except Exception:
            log_exc()
            return (0.0, 0)
    def _get_period_metrics(self, period):
        try:
            curr_start, curr_end, prev_start, prev_end = self._compute_period_ranges(period, use_view_start=False)
            today = date.today()
            unsaved_visible = self._unsaved_visible_seconds()
            unsaved_posture = self._unsaved_slouch_seconds()
            pending_distance_sum, pending_distance_count = self._unsaved_distance_sum_count()
            curr_screen = self._aggregate_screen_time(curr_start, curr_end)
            prev_screen = self._aggregate_screen_time(prev_start, prev_end)
            curr_posture = self._aggregate_posture_time(curr_start, curr_end)
            prev_posture = self._aggregate_posture_time(prev_start, prev_end)
            curr_sum, curr_count = self._aggregate_distance_sum_count(curr_start, curr_end)
            prev_sum, prev_count = self._aggregate_distance_sum_count(prev_start, prev_end)
            if curr_start <= today <= curr_end:
                curr_screen += unsaved_visible
                curr_posture += unsaved_posture
                curr_sum += pending_distance_sum
                curr_count += pending_distance_count
            curr_avg_cm = (curr_sum / curr_count) if curr_count > 0 else None
            prev_avg_cm = (prev_sum / prev_count) if prev_count > 0 else None
            if period == "Day":
                timeframe = "day"
                prev_timeframe = "yesterday"
                curr_timeframe = "today"
            elif period == "Week":
                timeframe = "week"
                prev_timeframe = "last week"
                curr_timeframe = "this week"
            elif period == "Month":
                timeframe = "month"
                prev_timeframe = "last month"
                curr_timeframe = "this month"
            elif period == "Year":
                timeframe = "year"
                prev_timeframe = "last year"
                curr_timeframe = "this year"
            else:
                timeframe = ""
                prev_timeframe = ""
                curr_timeframe = ""
            curr_screen = max(0, float(curr_screen or 0))
            prev_screen = max(0, float(prev_screen or 0))
            curr_posture = max(0, float(curr_posture or 0))
            prev_posture = max(0, float(prev_posture or 0))
            curr_posture = min(curr_posture, curr_screen)
            prev_posture = min(prev_posture, prev_screen)
            curr_range = (curr_start, curr_end)
            prev_range = (prev_start, prev_end)
            return curr_screen, prev_screen, curr_posture, prev_posture, curr_avg_cm, prev_avg_cm, timeframe, prev_timeframe, curr_timeframe, curr_range, prev_range
        except Exception:
            log_exc()
            return 0, 0, 0, 0, None, None, "", "", ""
    def _aggregate_screen_time(self, start, end):
        try:
            if cursor:
                cursor.execute("SELECT SUM(duration_sec) FROM screen_time WHERE date BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))
                res = cursor.fetchone()[0]
                return res if res else 0
            return 0
        except Exception:
            log_exc()
            return 0
    def _aggregate_posture_time(self, start, end):
        try:
            if cursor:
                cursor.execute("SELECT SUM(seconds) FROM posture_time WHERE date BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))
                res = cursor.fetchone()[0]
                return res if res else 0
            return 0
        except Exception:
            log_exc()
            return 0
    def _aggregate_distance_sum_count(self, start, end):
        try:
            if cursor:
                cursor.execute("SELECT avg_distance_cm, count FROM distance_log WHERE date BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))
                rows = cursor.fetchall()
                total_sum = 0.0
                total_count = 0
                for avg, cnt in rows:
                    avg_val = avg if avg is not None else 0.0
                    cnt_val = cnt if cnt is not None else 0
                    total_sum += avg_val * cnt_val
                    total_count += cnt_val
                return total_sum, total_count
            return (0.0, 0)
        except Exception:
            log_exc()
            return (0.0, 0)
    def _aggregate_avg_distance(self, start, end):
        try:
            total_sum, total_count = self._aggregate_distance_sum_count(start, end)
            return (total_sum / total_count) if total_count > 0 else None
        except Exception:
            log_exc()
            return None
    def _compute_period_ranges(self, period, use_view_start=False):
        try:
            today = date.today()
            reference = self.current_view_start if use_view_start and self.current_view_start else today
            if period == "Day":
                curr_start = reference
                curr_end = reference
                prev_start = reference - timedelta(days=1)
                prev_end = prev_start
            elif period == "Week":
                if use_view_start and self.current_view_start:
                    curr_start = self.current_view_start
                else:
                    curr_start = reference - timedelta(days=reference.weekday())
                curr_end = curr_start + timedelta(days=6)
                prev_end = curr_start - timedelta(days=1)
                prev_start = prev_end - timedelta(days=6)
            elif period == "Month":
                if use_view_start and self.current_view_start:
                    ref_month = self.current_view_start
                else:
                    ref_month = reference
                curr_start = ref_month.replace(day=1)
                next_month = (curr_start.replace(day=28) + timedelta(days=4)).replace(day=1)
                curr_end = next_month - timedelta(days=1)
                prev_end = curr_start - timedelta(days=1)
                prev_start = prev_end.replace(day=1)
            elif period == "Year":
                if use_view_start and self.current_view_start:
                    ref_year = self.current_view_start
                else:
                    ref_year = reference
                curr_start = ref_year.replace(month=1, day=1)
                curr_end = curr_start.replace(month=12, day=31)
                prev_end = curr_start - timedelta(days=1)
                prev_start = prev_end.replace(month=1, day=1)
            else:
                curr_start = reference
                curr_end = reference
                prev_start = reference - timedelta(days=1)
                prev_end = prev_start
            return curr_start, curr_end, prev_start, prev_end
        except Exception:
            log_exc()
            today = date.today()
            return today, today, today - timedelta(days=1), today - timedelta(days=1)
    def _update_feedback(self):
        try:
            for widget in self.feedback_frame.winfo_children():
                widget.destroy()
            curr_screen, prev_screen, curr_posture, prev_posture, curr_avg_cm, prev_avg_cm, timeframe, prev_timeframe, curr_timeframe, curr_range, prev_range = self._get_period_metrics(self.default_period)
            def fmt_duration(seconds):
                try:
                    seconds = max(0, int(round(seconds)))
                    if seconds < 60:
                        return f"{seconds}s"
                    mins, secs = divmod(seconds, 60)
                    if seconds < 3600:
                        return f"{mins}m" if secs == 0 else f"{mins}m {secs}s"
                    hours, mins = divmod(mins, 60)
                    if mins == 0:
                        return f"{hours}h"
                    return f"{hours}h {mins}m"
                except Exception:
                    log_exc()
                    return "0s"
            def fmt_distance(cm_value):
                try:
                    if cm_value is None or cm_value <= 0:
                        return "0"
                    if self.unit == "in":
                        return f"{round(cm_value / 2.54, 1)} in"
                    return f"{round(cm_value, 1)} cm"
                except Exception:
                    log_exc()
                    return "0"
            def fmt_pct(pct):
                try:
                    pct = float(pct)
                    abs_pct = abs(pct)
                    if abs_pct > 500:
                        return "over 500%"
                    if abs_pct >= 100 or abs_pct == int(abs_pct):
                        return f"{int(abs_pct)}%"
                    return f"{abs_pct:.1f}%"
                except Exception:
                    log_exc()
                    return "0%"
            entries = []
            def pct_text_and_direction(curr_val, prev_val, higher_is_better=True):
                pct = ((curr_val / prev_val) - 1) * 100
                abs_pct = abs(pct)
                pct_text = "over 500%" if abs_pct > 500 else f"{abs_pct:.0f}%"
                if pct > 0:
                    direction = "increase" if higher_is_better else "increase"
                elif pct < 0:
                    direction = "decrease" if higher_is_better else "decrease"
                else:
                    direction = "change"
                return pct_text, direction, pct
            period_suffix = f" {curr_timeframe}" if curr_timeframe else ""
            # Screen time
            curr_screen = max(0, curr_screen or 0)
            prev_screen = max(0, prev_screen or 0)
            curr_screen_text = fmt_duration(curr_screen)
            prev_screen_text = fmt_duration(prev_screen)
            if prev_screen > 0 and curr_screen > 0:
                pct_text, direction, pct_val = pct_text_and_direction(curr_screen, prev_screen)
                color = "red" if pct_val > 0 else "green" if pct_val < 0 else "gray"
                entries.append((f"{pct_text} {direction} in screen time from {prev_screen_text} to {curr_screen_text}{period_suffix}", color))
            elif curr_screen > 0:
                entries.append((f"Screen time{period_suffix} is {curr_screen_text} (no prior data).", "gray"))
            elif prev_screen > 0:
                entries.append((f"No screen time recorded{period_suffix} (previously {prev_screen_text}).", "gray"))
            else:
                entries.append(("No screen time recorded yet.", "gray"))
            # Bad posture time
            curr_posture = max(0, curr_posture or 0)
            prev_posture = max(0, prev_posture or 0)
            curr_posture_text = fmt_duration(curr_posture)
            prev_posture_text = fmt_duration(prev_posture)
            if prev_posture > 0 and curr_posture > 0:
                pct_text, direction, pct_val = pct_text_and_direction(curr_posture, prev_posture)
                color = "red" if pct_val > 0 else "green" if pct_val < 0 else "gray"
                entries.append((f"{pct_text} {direction} in bad posture time from {prev_posture_text} to {curr_posture_text}{period_suffix}", color))
            elif curr_posture > 0:
                entries.append((f"Bad posture time{period_suffix} is {curr_posture_text} (no prior data).", "gray"))
            elif prev_posture > 0:
                entries.append((f"No bad posture recorded{period_suffix} (previously {prev_posture_text}).", "gray"))
            else:
                entries.append(("No posture data recorded yet.", "gray"))
            # Average distance
            curr_avg = curr_avg_cm if curr_avg_cm is not None and curr_avg_cm > 0 else None
            prev_avg = prev_avg_cm if prev_avg_cm is not None and prev_avg_cm > 0 else None
            if curr_avg is not None and prev_avg is not None:
                pct_text, direction, pct_val = pct_text_and_direction(curr_avg, prev_avg)
                color = "green" if pct_val > 0 else "red" if pct_val < 0 else "gray"
                entries.append((f"{pct_text} {direction} in average distance from {fmt_distance(prev_avg)} to {fmt_distance(curr_avg)}{period_suffix}", color))
            elif curr_avg is not None:
                entries.append((f"Average distance{period_suffix} is {fmt_distance(curr_avg)} (no prior data).", "gray"))
            elif prev_avg is not None:
                entries.append((f"No average distance measured{period_suffix} (previously {fmt_distance(prev_avg)}).", "gray"))
            else:
                entries.append(("No distance data recorded yet.", "gray"))
            for txt, col in entries:
                lbl = ctk.CTkLabel(self.feedback_frame, text=txt, anchor="w", text_color=col)
                lbl.pack(fill="x", padx=0, pady=0)
        except Exception:
            log_exc()
    # callbacks
    def _set_delay(self, val):
        try:
            self.delay_seconds = int(float(val))
            self.delay_value.configure(text=f"{self.delay_seconds} s")
            cfg = load_json(CONFIG_FILE, {}); cfg["delay_seconds"] = self.delay_seconds; save_json(CONFIG_FILE, cfg)
        except Exception:
            log_exc()
    def _cm_from_display_value(self, display_val):
        return float(display_val) if self.unit=="cm" else float(display_val) * 2.54
    def _set_min_distance_from_slider(self, val):
        try:
            display_val = float(val)
            cm = self._cm_from_display_value(display_val)
            self.min_distance_cm = float(cm)
            if self.unit == "cm":
                self.min_distance_value.configure(text=f"{int(round(display_val))} cm")
            else:
                self.min_distance_value.configure(text=f"{round(display_val,1)} in")
            cfg = load_json(CONFIG_FILE, {}); cfg["min_distance_cm"] = self.min_distance_cm; save_json(CONFIG_FILE, cfg)
        except Exception:
            log_exc()
    def _toggle_posture(self):
        try:
            self.enable_posture = bool(self.posture_switch.get())
            cfg = load_json(CONFIG_FILE, {}); cfg["enable_posture"] = self.enable_posture; save_json(CONFIG_FILE, cfg)
            self._reload_pinned_graphs()
        except Exception:
            log_exc()
    def _toggle_distance(self):
        try:
            self.enable_distance = bool(self.distance_switch.get())
            cfg = load_json(CONFIG_FILE, {}); cfg["enable_distance"] = self.enable_distance; save_json(CONFIG_FILE, cfg)
            self._reload_pinned_graphs()
        except Exception:
            log_exc()
    def _toggle_nail_biting(self):
        try:
            self.enable_nail_biting = bool(self.nail_biting_switch.get())
            cfg = load_json(CONFIG_FILE, {}); cfg["enable_nail_biting"] = self.enable_nail_biting; save_json(CONFIG_FILE, cfg)
        except Exception:
            log_exc()
    def _toggle_face_touch(self):
        try:
            self.enable_face_touch = bool(self.face_touch_switch.get())
            cfg = load_json(CONFIG_FILE, {}); cfg["enable_face_touch"] = self.enable_face_touch; save_json(CONFIG_FILE, cfg)
            if not self.enable_face_touch:
                self._face_touch_detected = False
                self._face_touch_start = None
                self._face_touch_active_since = None
                with self.active_lock:
                    if "Face Touch Detected" in self.active_alerts:
                        self.active_alerts.discard("Face Touch Detected")
                        self._refresh_active_alerts()
        except Exception:
            log_exc()
    def _toggle_performance_mode(self):
        try:
            desired = bool(self.performance_switch.get())
            if desired and not self.performance_mode:
                res = messagebox.askyesno(
                    "Resource Saver",
                    "Resource Saver reduces CPU/GPU usage by processing fewer frames and may skip some landmark passes in Video mode. Detection accuracy and responsiveness may decrease.\n\nContinue?",
                    parent=self,
                )
                if not res:
                    self.performance_switch.deselect()
                    return
            self.performance_mode = desired
            self.video_process_every = 3 if self.performance_mode else VIDEO_PROCESS_EVERY
            cfg = load_json(CONFIG_FILE, {}); cfg["performance_mode"] = self.performance_mode; save_json(CONFIG_FILE, cfg)
        except Exception:
            log_exc()
    def _open_data_erase_window(self):
        try:
            if hasattr(self, "data_erase_win") and self.data_erase_win.winfo_exists():
                self.data_erase_win.lift()
                return
            self.data_erase_state["armed"] = False
            self.data_erase_win = ctk.CTkToplevel(self)
            self.data_erase_win.title("Panic Data Erase")
            self.data_erase_win.geometry("720x520")
            container = ctk.CTkFrame(self.data_erase_win, corner_radius=12)
            container.pack(fill="both", expand=True, padx=16, pady=16)
            ctk.CTkLabel(container, text="Panic Data Erase", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=12, pady=(12,8))
            info_box = ctk.CTkTextbox(container, wrap="word", height=260)
            info_box.pack(fill="both", expand=True, padx=12, pady=(0,12))
            info_text = (
                "The Panic Data Erase tool gives you complete control over your information.\n\n"
                "What it will remove:\n"
                " • All alert history (posture, distance, nail biting, face touching).\n"
                " • Screen-time, posture-time, and distance metrics (daily and hourly).\n"
                " • Any cached rolling statistics used for the dashboard.\n\n"
                "What it keeps:\n"
                " • Your application preferences (theme, units, accent color).\n"
                " • Calibration data, so you can continue using ScreenGuardian immediately.\n\n"
                "How to use it:\n"
                " 1. Arm the panic button. This unlocks the final confirmation for 30 seconds.\n"
                " 2. Read the summary of what will be erased.\n"
                " 3. Press the second confirmation. A safety prompt will appear before anything is deleted.\n\n"
                "You can run the erase at any time—the operation is instant and cannot be undone."
            )
            info_box.insert("end", info_text)
            info_box.configure(state="disabled")
            self.data_erase_message = ctk.CTkLabel(container, text="Ready to arm the panic button.", anchor="w")
            self.data_erase_message.pack(fill="x", padx=12, pady=(0,12))
            controls = ctk.CTkFrame(container, fg_color="transparent")
            controls.pack(fill="x", padx=12, pady=(0,12))
            self.arm_data_button = ctk.CTkButton(
                controls,
                text="Arm Panic Button",
                fg_color="#c43c00",
                hover_color="#8c2a00",
                command=self._arm_data_erase
            )
            self.arm_data_button.pack(side="left", padx=(0,12))
            self.confirm_data_button = ctk.CTkButton(
                controls,
                text="Confirm & Erase",
                fg_color="#660000",
                hover_color="#440000",
                state="disabled",
                command=self._confirm_data_erase
            )
            self.confirm_data_button.pack(side="left")
            self._apply_accent_theme(self.data_erase_win)
        except Exception:
            log_exc()
    def _arm_data_erase(self):
        try:
            self.data_erase_state["armed"] = True
            self.arm_data_button.configure(text="Armed (30s)", state="disabled")
            self.confirm_data_button.configure(state="normal", fg_color="#b00020", hover_color="#7a0015")
            self.data_erase_message.configure(text="Panic button armed. Review the details above, then press Confirm & Erase to proceed.")
            self.after(30000, self._disarm_data_erase)
        except Exception:
            log_exc()
    def _disarm_data_erase(self):
        try:
            if not self.data_erase_state.get("armed"):
                return
            self.data_erase_state["armed"] = False
            self.arm_data_button.configure(text="Arm Panic Button", state="normal")
            self.confirm_data_button.configure(state="disabled", fg_color="#660000", hover_color="#440000")
            self.data_erase_message.configure(text="Panic button disarmed. Arm it again when you are ready.")
        except Exception:
            log_exc()
    def _confirm_data_erase(self):
        try:
            if not self.data_erase_state.get("armed"):
                self.data_erase_message.configure(text="Please arm the panic button first.")
                return
            if not messagebox.askyesno("Confirm Data Erase", "This will permanently delete all saved metrics and alerts. Calibration and preferences will remain. Continue?", parent=self.data_erase_win):
                return
            self._execute_data_erase()
        except Exception:
            log_exc()
    def _execute_data_erase(self):
        try:
            if cursor:
                tables = [
                    "alerts",
                    "screen_time",
                    "posture_time",
                    "distance_log",
                    "screen_hourly",
                    "posture_hourly",
                    "distance_hourly"
                ]
                for table in tables:
                    cursor.execute(f"DELETE FROM {table}")
                conn.commit()
            self.today_screen_sec = 0
            self.today_posture_sec = 0
            self.today_avg_cm = None
            self.today_distance_count = 0
            self.today_posture_alerts = 0
            self.today_distance_alerts = 0
            self.today_face_touch_alerts = 0
            self.session_posture_alerts = 0
            self.session_distance_alerts = 0
            self.session_face_touch_alerts = 0
            self.visible_seconds = 0
            self.slouch_accum_seconds = 0
            self.saved_visible_seconds = 0
            self.saved_slouch_seconds = 0
            self.pending_hour_visible_seconds = 0
            self.pending_hour_slouch_seconds = 0
            self.pending_hour_distance_sum = 0.0
            self.pending_hour_distance_count = 0
            self.pending_distance_sum = 0.0
            self.pending_distance_count = 0
            self.distance_sum_total = 0.0
            self.distance_count_total = 0
            self.distances_buffer.clear()
            with self.active_lock:
                self.active_alerts.clear()
            self._refresh_active_alerts()
            self.screen_time_label.configure(text="Screen Time: 0s")
            self.time_bad_posture_label.configure(text="Time with Bad Posture (session): 0s")
            self.session_posture_alerts_label.configure(text="Session Posture Alerts: 0")
            self.session_distance_alerts_label.configure(text="Session Distance Alerts: 0")
            self.session_face_touch_alerts_label.configure(text="Session Face Touch Alerts: 0")
            self._load_logs()
            self._update_feedback()
            if hasattr(self, 'stats_win') and self.stats_win.winfo_exists():
                self._redraw_all_stats_charts()
            if hasattr(self, "calendar_frame"):
                self._update_calendar_selection(date.today(), ensure_visible=True)
            self.data_erase_state["armed"] = False
            self.arm_data_button.configure(text="Arm Panic Button", state="normal")
            self.confirm_data_button.configure(state="disabled", fg_color="#660000", hover_color="#440000")
            self.data_erase_message.configure(text="Data erased successfully. All metrics have been reset.")
        except Exception:
            log_exc()
    def _toggle_twenty(self):
        try:
            self.enable_twenty = bool(self.twenty_switch.get())
            cfg = load_json(CONFIG_FILE, {}); cfg["enable_twenty"] = self.enable_twenty; save_json(CONFIG_FILE, cfg)
        except Exception:
            log_exc()
    def _set_mode(self, val):
        try:
            self.display_mode = val; cfg = load_json(CONFIG_FILE, {}); cfg["display_mode"] = self.display_mode; save_json(CONFIG_FILE, cfg)
        except Exception:
            log_exc()
    def _set_unit(self, val):
        try:
            self.unit = val; cfg = load_json(CONFIG_FILE, {}); cfg["unit"] = self.unit; save_json(CONFIG_FILE, cfg)
            if self.unit == "cm":
                self.min_distance_slider.configure(from_=30, to=120)
                self.min_distance_slider.set(self.min_distance_cm)
                self.min_distance_value.configure(text=f"{int(self.min_distance_cm)} cm")
            else:
                self.min_distance_slider.configure(from_=12, to=48)
                self.min_distance_slider.set(round(self.min_distance_cm / 2.54,1))
                self.min_distance_value.configure(text=f"{round(self.min_distance_cm/2.54,1)} in")
            if self.today_avg_cm is not None:
                if self.unit == "in":
                    ad = round(self.today_avg_cm / 2.54,1)
                    u = "in"
                else:
                    ad = int(round(self.today_avg_cm))
                    u = "cm"
                self.today_avg_distance_label.configure(text=f"Avg Distance: {ad} {u}")
            self._reload_pinned_graphs()
            if hasattr(self, "stats_win") and self.stats_win.winfo_exists():
                self._redraw_all_stats_charts()
        except Exception:
            log_exc()
    def _set_theme(self, val):
        try:
            self.theme_mode = val
            mode = "System" if val=="System" else ("Dark" if val=="Dark" else "Light")
            ctk.set_appearance_mode(mode)
            cfg = load_json(CONFIG_FILE, {}); cfg["theme_mode"] = self.theme_mode; save_json(CONFIG_FILE, cfg)
            self._apply_accent_theme()
            self._reload_pinned_graphs()
        except Exception:
            log_exc()
    def _set_period(self, val):
        try:
            self.default_period = val
            self.current_period = val
            cfg = load_json(CONFIG_FILE, {}); cfg["default_period"] = self.default_period; save_json(CONFIG_FILE, cfg)
            self._reload_pinned_graphs()
            self._update_feedback()
        except Exception:
            log_exc()
    def _pick_accent_color(self):
        try:
            color = colorchooser.askcolor(title="Pick accent color", initialcolor=self.accent_color)
            if color and color[1]:
                self.accent_color = color[1]
                cfg = load_json(CONFIG_FILE, {}); cfg["accent_color"] = self.accent_color; save_json(CONFIG_FILE, cfg)
                self._apply_accent_theme()
        except Exception:
            log_exc()
    def _contact_support(self):
        try:
            webbrowser.open(f"mailto:{SUPPORT_EMAIL}?subject=ScreenGuardian%20Support")
        except Exception:
            log_exc()
    def _toggle_sidebar(self):
        try:
            if self.sidebar_outer.winfo_ismapped():
                self.sidebar_outer.grid_remove()
                self.grid_columnconfigure(0, minsize=0, weight=0)
                self.grid_columnconfigure(1, weight=1)
                self.main.grid_columnconfigure(0, weight=1)
                self.main.grid_columnconfigure(1, weight=1)
                self.toggle_btn.configure(text=">> Show Settings")
            else:
                self.sidebar_outer.grid()
                width = self.sidebar_outer.winfo_width() or 260
                self.grid_columnconfigure(0, minsize=width, weight=0)
                self.grid_columnconfigure(1, weight=1)
                self.main.grid_columnconfigure(0, weight=1)
                self.main.grid_columnconfigure(1, weight=1)
                self.toggle_btn.configure(text="<< Hide Settings")
            self.after(100, self._on_window_resize, None) # force resize
        except Exception:
            log_exc()
    def _build_alert_panel(self):
        try:
            if self.alert_panel is not None and self.alert_panel.winfo_exists():
                try:
                    self.alert_panel.destroy()
                except Exception:
                    pass
            panel_width = 320
            border_color = self._brighten_hex(self.accent_color)
            self.alert_panel = ctk.CTkFrame(self, corner_radius=12, width=panel_width, border_width=3, border_color=border_color, fg_color=("#1e1e1e", "#101010"))
            self.alert_panel.place_forget()
            header = ctk.CTkFrame(self.alert_panel, fg_color="transparent")
            header.pack(fill="x", padx=12, pady=(12,6))
            ctk.CTkLabel(header, text="Alert Log", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
            close_btn = ctk.CTkButton(header, text="X", width=32, command=self._toggle_alert_panel)
            close_btn.pack(side="right")
            body = ctk.CTkFrame(self.alert_panel, corner_radius=6)
            body.pack(fill="both", expand=True, padx=12, pady=(0,12))
            body.grid_rowconfigure(0, weight=1)
            body.grid_columnconfigure(0, weight=1)
            self.log_text = ctk.CTkTextbox(body, wrap="word", state="disabled")
            self.log_text.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
            self.alert_panel_visible = False
            self._load_logs()
            self._apply_accent_theme(self.alert_panel)
        except Exception:
            log_exc()
    def _toggle_alert_panel(self):
        try:
            if not self.alert_panel or not self.alert_panel.winfo_exists():
                self._build_alert_panel()
            if self.alert_panel_visible:
                self.alert_panel.place_forget()
                self.alert_panel_visible = False
                if self.alert_log_btn:
                    self.alert_log_btn.configure(text="Alert Log")
            else:
                self.alert_panel.place(relx=1.0, rely=0.0, anchor="ne", relheight=1.0)
                self.alert_panel_visible = True
                if self.alert_log_btn:
                    self.alert_log_btn.configure(text="Hide Alert Log")
        except Exception:
            log_exc()
    # logs
    def _load_logs(self):
        try:
            self.log_text.configure(state="normal"); self.log_text.delete("0.0","end")
            if cursor:
                cursor.execute("SELECT timestamp, message FROM alerts ORDER BY timestamp DESC LIMIT 200")
                rows = cursor.fetchall()
            else:
                rows = []
            for ts, msg in rows:
                self.log_text.insert("end", f"{ts}: {msg}\n")
            self.log_text.configure(state="disabled")
        except Exception:
            log_exc()
    def _prepend_log_ui(self, entry: str):
        try:
            self.log_text.configure(state="normal")
            prev = self.log_text.get("0.0","end")
            self.log_text.delete("0.0","end")
            self.log_text.insert("0.0", entry + "\n" + prev)
            self.log_text.configure(state="disabled")
        except Exception:
            log_exc()
    # Video worker
    def _video_worker(self):
        try:
            cap = get_camera_cap()
            if cap is None:
                self.after(0, lambda: messagebox.showerror("Camera Error", "No camera detected. Video features disabled."))
                try:
                    self.frame_queue.put_nowait(None)
                except queue.Full:
                    try:
                        self.frame_queue.get_nowait()
                    except Exception:
                        pass
                    try:
                        self.frame_queue.put_nowait(None)
                    except Exception:
                        pass
                return
            CAM_W = 640
            CAM_H = 480
            mp_face = mp.solutions.face_mesh.FaceMesh(static_image_mode=False, max_num_faces=1, refine_landmarks=True, min_detection_confidence=0.5)
            mp_pose = mp.solutions.pose.Pose(static_image_mode=False, model_complexity=1, min_detection_confidence=0.5, min_tracking_confidence=0.5)
            mp_hands = mp.solutions.hands.Hands(static_image_mode=False, max_num_hands=2, min_detection_confidence=0.5)
            frame_interval = 1.0 / TARGET_FRAME_FPS
            frame_idx = 0
            read_failures = 0
            max_read_failures = 20
            while self.running:
                try:
                    loop_start = time.perf_counter()
                    ret, frame = cap.read()
                    if not ret:
                        read_failures += 1
                        if read_failures >= max_read_failures:
                            self.after(0, lambda: messagebox.showerror("Camera Error", "Camera feed unavailable. Video stopped."))
                            try:
                                self.frame_queue.put_nowait(None)
                            except queue.Full:
                                try:
                                    self.frame_queue.get_nowait()
                                except Exception:
                                    pass
                                try:
                                    self.frame_queue.put_nowait(None)
                                except Exception:
                                    pass
                            break
                        time.sleep(0.03); continue
                    read_failures = 0
                    frame = cv2.flip(frame, 1) 
                    frame = cv2.resize(frame, (CAM_W, CAM_H))
                    try:
                        self.frame_queue.put_nowait(frame.copy())  # Share frame with stats worker
                    except queue.Full:
                        pass
                    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    img_h, img_w = frame.shape[:2]
                    face_box = None
                    detected_eyes = []
                    detected_shoulders = None
                    shoulder_mid = None
                    lm_px_norm = None
                    mouth_box = None
                    hand_landmarks = None
                    run_landmarks = True
                    if self.performance_mode and self.display_mode == "Video":
                        run_landmarks = False
                    detect_frame = run_landmarks and (frame_idx % max(1, self.video_process_every) == 0)
                    if detect_frame:
                        fres = mp_face.process(img_rgb)
                        if fres and fres.multi_face_landmarks:
                            lm = fres.multi_face_landmarks[0]
                            lm_px_norm = [(p.x, p.y) for p in lm.landmark]
                            xs = [int(p.x * img_w) for p in lm.landmark]; ys = [int(p.y * img_h) for p in lm.landmark]
                            if xs and ys:
                                min_x, max_x = max(0, min(xs)), min(img_w, max(xs))
                                min_y, max_y = max(0, min(ys)), min(img_h, max(ys))
                                pad_x = int(0.04*(max_x-min_x)+1); pad_y = int(0.06*(max_y-min_y)+1)
                                fx = clamp(min_x-pad_x, 0, img_w-1); fy = clamp(min_y-pad_y, 0, img_h-1)
                                fw = clamp(max_x+pad_x, 0, img_w) - fx; fh = clamp(max_y+pad_y, 0, img_h) - fy
                                face_box = (fx, fy, fw, fh)
                                def eye_box(idxs):
                                    pts = [lm.landmark[i] for i in idxs if i < len(lm.landmark)]
                                    if not pts: return None
                                    cx = int(sum(p.x for p in pts)/len(pts)*img_w)
                                    cy = int(sum(p.y for p in pts)/len(pts)*img_h)
                                    wbox = max(8, int(0.12*fw)); hbox = max(6, int(0.08*fh))
                                    return (cx-wbox//2, cy-hbox//2, wbox, hbox)
                                le = eye_box(LEFT_EYE_IDX); re = eye_box(RIGHT_EYE_IDX)
                                if le: detected_eyes.append(le)
                                if re: detected_eyes.append(re)
                                mouth_pts = [(int(lm.landmark[i].x * img_w), int(lm.landmark[i].y * img_h)) for i in MOUTH_IDX if i < len(lm.landmark)]
                                if mouth_pts:
                                    min_x = min(p[0] for p in mouth_pts)
                                    max_x = max(p[0] for p in mouth_pts)
                                    min_y = min(p[1] for p in mouth_pts)
                                    max_y = max(p[1] for p in mouth_pts)
                                    mw = max_x - min_x
                                    mh = max_y - min_y
                                    pad = 10
                                    mouth_box = (min_x - pad, min_y - pad, mw + 2*pad, mh + 2*pad)
                        pres = mp_pose.process(img_rgb)
                        if pres and pres.pose_landmarks:
                            pts = pres.pose_landmarks.landmark
                            ls_i = mp.solutions.pose.PoseLandmark.LEFT_SHOULDER.value
                            rs_i = mp.solutions.pose.PoseLandmark.RIGHT_SHOULDER.value
                            ls = pts[ls_i]
                            rs = pts[rs_i]
                            if (0 < ls.x <1 and 0 < ls.y <1 and ls.visibility >0.5 and
                                0 < rs.x <1 and 0 < rs.y <1 and rs.visibility >0.5):
                                ls_px = (int(ls.x*img_w), int(ls.y*img_h))
                                rs_px = (int(rs.x*img_w), int(rs.y*img_h))
                                detected_shoulders = (ls_px, rs_px)
                                shoulder_mid = ((ls_px[0]+rs_px[0])/2.0, (ls_px[1]+rs_px[1])/2.0)
                        if self.enable_nail_biting or self.enable_face_touch:
                            hres = mp_hands.process(img_rgb)
                            if hres and hres.multi_hand_landmarks:
                                hand_landmarks = hres.multi_hand_landmarks
                                self.last_hand_landmarks = hand_landmarks
                            else:
                                self.last_hand_landmarks = None
                        else:
                            self.last_hand_landmarks = None
                    else:
                        detected_shoulders = self._last_detected_shoulders
                        mouth_box = self._last_mouth_box
                    if detect_frame and face_box:
                        if self.last_face_box is None:
                            self.last_face_box = face_box
                        else:
                            a = 0.28
                            self.last_face_box = tuple(int(round(a*face_box[i] + (1-a)*self.last_face_box[i])) for i in range(4))
                    if detect_frame and detected_eyes:
                        if not self.last_eyes:
                            self.last_eyes = detected_eyes
                        else:
                            sm = []
                            alpha = 0.28
                            for i,e in enumerate(detected_eyes[:2]):
                                if i < len(self.last_eyes):
                                    ox,oy,ow,oh = self.last_eyes[i]; nx,ny,nw,nh = e
                                    sm.append((int(round(alpha*nx + (1-alpha)*ox)),
                                               int(round(alpha*ny + (1-alpha)*oy)),
                                               int(round(alpha*nw + (1-alpha)*ow)),
                                               int(round(alpha*nh + (1-alpha)*oh))))
                                else:
                                    sm.append(e)
                            self.last_eyes = sm
                    if detect_frame and shoulder_mid:
                        self._shoulder_history.append(shoulder_mid)
                        if len(self._shoulder_history) > 6: self._shoulder_history.pop(0)
                        hx = int(np.mean([p[0] for p in self._shoulder_history])); hy = int(np.mean([p[1] for p in self._shoulder_history]))
                        self._smoothed_shoulder_mid = (hx, hy)
                    if detect_frame:
                        if face_box or lm_px_norm:
                            self._fully_missing_count = 0
                            missing_parts = 0
                            if not detected_eyes or len(self.last_eyes) < 2:
                                missing_parts += 1
                            if not self._smoothed_shoulder_mid:
                                missing_parts += 1
                            if missing_parts >= 1:
                                self._partial_missing_count += 1
                            else:
                                self._partial_missing_count = 0
                        else:
                            self._fully_missing_count += 1
                            self._partial_missing_count = 0
                    if detect_frame:
                        self._last_detected_shoulders = detected_shoulders
                        self._last_mouth_box = mouth_box
                    detected_shoulders = self._last_detected_shoulders
                    mouth_box = self._last_mouth_box
                    # Landmark drawing starts here
                    mode = self.display_mode
                    if mode == "Video":
                        draw_img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    elif mode == "Landmarks":
                        draw_img = np.full((img_h, img_w, 3), 240, dtype=np.uint8)
                    else:
                        draw_img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    pil = Image.fromarray(draw_img).convert("RGBA")
                    overlay = Image.new("RGBA", pil.size, (0,0,0,0))
                    draw = ImageDraw.Draw(overlay, "RGBA")
                    # Landmark color indicators
                    with self.active_lock:
                        if "Bad Posture" in self.active_alerts:
                            col = (255, 0, 0, 255)
                        elif "Distance Alerts - Too close to screen" in self.active_alerts:
                            col = (255, 165, 0, 255)
                        else:
                            col = (0, 255, 0, 255)
                    if self.last_face_box and mode in ("Both","Landmarks"):
                        fx,fy,fw,fh = self.last_face_box
                        r = int(min(fw, fh) * 0.12)
                        left, top, right, bottom = fx, fy, fx+fw, fy+fh
                        draw.rounded_rectangle([left, top, right, bottom], radius=r, outline=col, width=4)
                        for e in self.last_eyes:
                            ex,ey,ew,eh = e; cx=int(ex+ew/2); cy=int(ey+eh/2)
                            draw.ellipse([cx-4, cy-4, cx+4, cy+4], fill=col, width=2)
                        if mouth_box:
                            mx, my, mw, mh = mouth_box
                            draw.rounded_rectangle([mx, my, mx+mw, my+mh], radius=8, outline=col, width=2)
                    if self._smoothed_shoulder_mid and mode in ("Landmarks","Both"):
                        sx, sy = int(self._smoothed_shoulder_mid[0]), int(self._smoothed_shoulder_mid[1])
                        draw.ellipse([sx-5, sy-5, sx+5, sy+5], fill=col)
                        if detected_shoulders:
                            ls_px, rs_px = detected_shoulders
                            draw.ellipse([ls_px[0]-4, ls_px[1]-4, ls_px[0]+4, ls_px[1]+4], fill=col)
                            draw.ellipse([rs_px[0]-4, rs_px[1]-4, rs_px[0]+4, rs_px[1]+4], fill=col)
                            draw.line([ls_px, rs_px], fill=col, width=4)
                        if self.last_face_box:
                            fx,fy,fw,fh = self.last_face_box
                            head_bottom = (int(fx + fw/2), int(fy + fh))
                            draw.line([head_bottom, ((head_bottom[0]+sx)//2, (head_bottom[1]+sy)//2), (sx,sy)], fill=col, width=4)
                    if (self.enable_nail_biting or self.enable_face_touch) and mode in ("Landmarks","Both") and self.last_hand_landmarks:
                        if self._nail_biting_detected:
                            contact_col = (255, 0, 0, 255)
                        elif self._face_touch_detected:
                            contact_col = (255, 140, 0, 255)
                        else:
                            contact_col = (0, 255, 0, 255)
                        for hand_lm in self.last_hand_landmarks:
                            for i in FINGERTIP_IDX:
                                p = hand_lm.landmark[i]
                                hx = int(p.x * img_w)
                                hy = int(p.y * img_h)
                                draw.ellipse([hx-3, hy-3, hx+3, hy+3], fill=contact_col)
                    pil = Image.alpha_composite(pil, overlay).convert("RGB")
                    with self.frame_lock:
                        self.latest_pil = pil.copy()
                    frame_idx += 1
                    elapsed = time.perf_counter() - loop_start
                    if elapsed < frame_interval:
                        time.sleep(frame_interval - elapsed)
                except Exception:
                    log_exc()
                    time.sleep(0.03)
            try: cap.release()
            except Exception: pass
        except Exception:
            log_exc()
    # poller
    def _poll_latest_frame(self):
        try:
            pil = None
            with self.frame_lock:
                if self.latest_pil is not None:
                    pil = self.latest_pil.copy()
                    self.latest_pil = None
            if pil is not None:
                try:
                    w = getattr(self, "display_draw_w", 800)
                    h = getattr(self, "display_draw_h", 600)
                    pil_resized = pil.resize((int(w), int(h)), Image.LANCZOS).convert("RGBA")
                    mask = Image.new("L", pil_resized.size, 0)
                    draw = ImageDraw.Draw(mask)
                    draw.rounded_rectangle((0, 0, w, h), radius=8, fill=255)
                    pil_resized.putalpha(mask)
                    ctk_image = CTkImage(light_image=pil_resized, dark_image=pil_resized, size=(w, h))
                    self.video_label.configure(image=ctk_image)
                    self.video_label.image = ctk_image
                except Exception:
                    log_exc()
            self.after(30, self._poll_latest_frame)
        except Exception:
            log_exc()
            self.after(200, self._poll_latest_frame)
    # Posture analysis
    def _compute_posture_flags(self, nose_px, head_center_px, shoulder_mid_px, detected_shoulders, face_width_px, mouth_box, face_box, hand_landmarks, image_size=None):
        try:
            img_w, img_h = image_size if image_size else (None, None)
            flags = {"vertical_bad": False, "depth_bad": False, "eye_tilt_bad": False, "head_twist_bad": False, "neck_short_bad": False, "body_turned": False, "horizontal_offset_bad": False, "nail_biting": False, "face_touch": False}
            diag = {}
            if not face_width_px or face_width_px <= 1:
                return flags, diag
            hx = head_center_px[0] if head_center_px else (nose_px[0] if nose_px else None)
            hy = head_center_px[1] if head_center_px else (nose_px[1] if nose_px else None)
            if hx is None or hy is None:
                return flags, diag
            shoulder_angle = 0.0
            if detected_shoulders and len(detected_shoulders) == 2:
                ls, rs = detected_shoulders
                shoulder_span = float(np.linalg.norm(np.array(ls) - np.array(rs)))
                shoulder_vec = (rs[0]-ls[0], rs[1]-ls[1])
                shoulder_angle = math.degrees(math.atan2(shoulder_vec[1], shoulder_vec[0]))
            else:
                shoulder_span = max(1.0, face_width_px * 1.6)
                shoulder_angle = 0.0
            diag['shoulder_span'] = shoulder_span
            diag['shoulder_angle'] = shoulder_angle
            ratio = shoulder_span / (face_width_px + 1e-6)
            diag['shoulder_face_ratio'] = ratio
            body_turn_ratio_threshold = 1.15
            flags['body_turned'] = (ratio < (body_turn_ratio_threshold * 0.78))
            if shoulder_mid_px:
                vertical_ratio = (shoulder_mid_px[1] - hy) / (face_width_px * 1.25 + 1e-6)
                flags['vertical_bad'] = vertical_ratio < self.posture_vert_thresh
                diag['vertical_ratio'] = vertical_ratio
            else:
                diag['vertical_ratio'] = None
            depth_ratio = (face_width_px / (shoulder_span + 1e-6))
            if self._depth_baseline is None:
                self._depth_baseline = depth_ratio
            else:
                self._depth_baseline = 0.08 * depth_ratio + (1 - 0.08) * self._depth_baseline
            diag['depth_ratio'] = depth_ratio; diag['depth_baseline'] = self._depth_baseline
            flags['depth_bad'] = (depth_ratio > (self._depth_baseline * self.posture_depth_thresh))
            eye_tilt_norm = 0.0
            eye_tilt_angle = 0.0
            eye_vertical_diff = 0.0
            try:
                if self.last_eyes and len(self.last_eyes) >= 2:
                    l = self.last_eyes[0]; r = self.last_eyes[1]
                    lx = l[0] + l[2]/2.0; ly = l[1] + l[3]/2.0
                    rx = r[0] + r[2]/2.0; ry = r[1] + r[3]/2.0
                    dy = ry - ly
                    dx = rx - lx
                    eye_tilt_angle = math.degrees(math.atan2(dy, dx))
                    eye_tilt_norm = abs(dy) / (face_width_px * 1.25 + 1e-6)
                    eye_vertical_diff = abs(dy)
            except Exception:
                eye_tilt_norm = 0.0
                eye_tilt_angle = 0.0
                eye_vertical_diff = 0.0
            diag['eye_tilt_norm'] = eye_tilt_norm
            diag['eye_tilt_angle'] = eye_tilt_angle
            diag['eye_vertical_diff_norm'] = eye_vertical_diff / (face_width_px + 1e-6)
            neutral_tilt = self.calib.get('neutral', {}).get('eye_tilt_angle', 0.0)
            flags['eye_tilt_bad'] = (eye_tilt_norm > self.posture_eye_tilt_thresh or abs(eye_tilt_angle - neutral_tilt) > 10)
            diag['head_twist_deg'] = abs(eye_tilt_angle - neutral_tilt)
            if diag['head_twist_deg'] > 12:
                flags['head_twist_bad'] = True
            if diag['eye_vertical_diff_norm'] > 0.05:
                flags['eye_tilt_bad'] = True
            neck_len = None
            if nose_px and shoulder_mid_px:
                neck_len = (shoulder_mid_px[1] - float(nose_px[1])) / (face_width_px * 1.25 + 1e-6)
            else:
                neck_len = diag.get('vertical_ratio', 0.0)
            diag['neck_len'] = neck_len
            flags['neck_short_bad'] = ((1.0 - neck_len) > self.posture_neck_thresh)
            if shoulder_mid_px and hx:
                horizontal_offset_norm = abs(hx - shoulder_mid_px[0]) / (face_width_px + 1e-6)
                diag['horizontal_offset_norm'] = horizontal_offset_norm
                flags['horizontal_offset_bad'] = horizontal_offset_norm > 0.15 and not flags['body_turned'] # suppress if body turned
            else:
                diag['horizontal_offset_norm'] = None
            # Nail biting detection
            if (self.enable_nail_biting or self.enable_face_touch) and hand_landmarks and img_w and img_h:
                face_reference = face_box or (self.last_face_box if self.last_face_box else None)
                for hand_lm in hand_landmarks:
                    for i in FINGERTIP_IDX:
                        p = hand_lm.landmark[i]
                        px = int(p.x * img_w)
                        py = int(p.y * img_h)
                        if self.enable_nail_biting and mouth_box:
                            mx, my, mw, mh = mouth_box
                            if (mx - NAIL_CONTACT_MARGIN <= px <= mx + mw + NAIL_CONTACT_MARGIN and
                                    my - NAIL_CONTACT_MARGIN <= py <= my + mh + NAIL_CONTACT_MARGIN and
                                    p.z < NAIL_BITING_DEPTH_THRESH):
                                flags['nail_biting'] = True
                                break
                        # Face touch detection
                        if self.enable_face_touch and face_reference:
                            fx0, fy0, fw0, fh0 = face_reference
                            if (fx0 + FACE_TOUCH_MARGIN <= px <= fx0 + fw0 - FACE_TOUCH_MARGIN and
                                    fy0 + FACE_TOUCH_MARGIN <= py <= fy0 + fh0 - FACE_TOUCH_MARGIN and
                                    p.z < NAIL_BITING_DEPTH_THRESH):
                                flags["face_touch"] = True
                                break
                    if flags.get('nail_biting') and flags.get('face_touch'):
                        break
            # Suppress posture alerts when entire body turns
            if flags['body_turned']:
                flags['eye_tilt_bad'] = False
                flags['head_twist_bad'] = False
                flags['vertical_bad'] = False
                flags['depth_bad'] = False
                flags['neck_short_bad'] = False
                flags['horizontal_offset_bad'] = False
                diag['reason'] = 'body_turned suppress posture health alerts'
            else:
                if abs(shoulder_angle) > 15:
                    flags['eye_tilt_bad'] = False
            return flags, diag
        except Exception:
            log_exc()
            return {"vertical_bad": False, "depth_bad": False, "eye_tilt_bad": False, "head_twist_bad": False, "neck_short_bad": False, "body_turned": False, "horizontal_offset_bad": False, "nail_biting": False, "face_touch": False}, {}
    def _update_posture_state(self, flags, diag):
        try:
            now = time.time()
            changed = False
            if flags.get("body_turned", False):
                label = "Off Task - Body Turned"
                if getattr(self, "_body_turned_start", None) is None:
                    self._body_turned_start = now
                    self._body_turned_active_since = now
                elif (now - self._body_turned_active_since) >= self.active_alert_appear_seconds:
                    with self.active_lock:
                        if label not in self.active_alerts:
                            self.active_alerts.add(label); changed = True
                if not getattr(self, "_body_turned_notified", False):
                    if (now - getattr(self, "_body_turned_start", now)) >= max(1, self.delay_seconds):
                        notify_os("Off Task", "Body turned away from screen.")
                        self._emit_alert(label)
                        self._body_turned_notified = True
            else:
                for name in ("_body_turned_start","_body_turned_active_since","_body_turned_notified"):
                    if getattr(self, name, None) is not None:
                        try:
                            delattr(self, name)
                        except Exception:
                            pass
                with self.active_lock:
                    if "Off Task - Body Turned" in self.active_alerts:
                        self.active_alerts.discard("Off Task - Body Turned"); changed = True
            posture_detected = False
            self.posture_reasons.clear()
            category_map = {
                "vertical_bad": "Sit up straight",
                "depth_bad": "Lean back",
                "eye_tilt_bad": "Straighten your head",
                "head_twist_bad": "Level your head",
                "neck_short_bad": "Straighten your neck",
                "horizontal_offset_bad": "Straighten your neck"
            }
            for key, desc in category_map.items():
                if flags.get(key, False):
                    posture_detected = True
                    self.posture_reasons.add(desc)
                    if key == "eye_tilt_bad":
                        append_log_line("DEBUG: eye_tilt_bad triggered")
            body_turn = flags.get("body_turned", False)
            head_turn_components = flags.get("eye_tilt_bad", False) or flags.get("head_twist_bad", False) or flags.get("horizontal_offset_bad", False)
            head_turn_bad = False
            if head_turn_components and not body_turn:
                if self._head_turn_start is None:
                    self._head_turn_start = now
                self._head_turn_duration = now - self._head_turn_start
                if self._head_turn_duration > 30:
                    head_turn_bad = True
                    self.posture_reasons.add("Face forward")
                    posture_detected = True
            else:
                self._head_turn_start = None
                self._head_turn_duration = 0
            label = "Bad Posture"
            if posture_detected and (not body_turn or head_turn_bad):
                if getattr(self, "_posture_start", None) is None:
                    self._posture_start = now
                    self._posture_active_since = now
                elif (now - self._posture_active_since) >= self.active_alert_appear_seconds:
                    with self.active_lock:
                        if label not in self.active_alerts:
                            self.active_alerts.add(label); changed = True
                if not getattr(self, "_posture_notified", False):
                    if (now - self._posture_start) >= max(1, self.delay_seconds):
                        reasons_str = ", ".join(self.posture_reasons)
                        notify_os("Bad Posture", reasons_str)
                        self._emit_alert(f"Bad Posture - {reasons_str}")
                        self.today_posture_alerts += 1
                        self.session_posture_alerts += 1
                        self.after(0, lambda: self.session_posture_alerts_label.configure(text=f"Session Posture Alerts: {self.session_posture_alerts}"))
                        self._posture_notified = True
                if self.slouch_session_start is None:
                    self.slouch_session_start = now
            else:
                for n in ("_posture_start", "_posture_active_since", "_posture_notified"):
                    if getattr(self, n, None) is not None:
                        try: delattr(self, n)
                        except Exception: pass
                with self.active_lock:
                    if label in self.active_alerts:
                        self.active_alerts.discard(label); changed = True
                if self.slouch_session_start is not None:
                    self.slouch_accum_seconds += int(now - self.slouch_session_start)
                    self.slouch_session_start = None
            if self.enable_nail_biting and flags.get("nail_biting", False):
                self._nail_biting_detected = True
                if getattr(self, "_nail_active_since", None) is None:
                    self._nail_active_since = now
                with self.active_lock:
                    if "Nail Biting Detected" not in self.active_alerts:
                        self.active_alerts.add("Nail Biting Detected")
                        changed = True
                if self._nail_biting_start is None:
                    self._nail_biting_start = now
                if (now - self._nail_biting_start) >= NAIL_BITING_DURATION:
                    notify_os("Nail Biting Detected", "Stop biting your nails.")
                    self._emit_alert("Nail Biting Detected")
                    self._nail_biting_start = now + 60
            else:
                self._nail_biting_detected = False
                self._nail_biting_start = None
                if hasattr(self, "_nail_active_since"):
                    delattr(self, "_nail_active_since")
                with self.active_lock:
                    if "Nail Biting Detected" in self.active_alerts:
                        self.active_alerts.discard("Nail Biting Detected")
                        changed = True
            if self.enable_face_touch and flags.get("face_touch", False):
                self._face_touch_detected = True
                if self._face_touch_active_since is None:
                    self._face_touch_active_since = now
                with self.active_lock:
                    if "Face Touch Detected" not in self.active_alerts:
                        self.active_alerts.add("Face Touch Detected")
                        changed = True
                if self._face_touch_start is None or self._face_touch_start <= now:
                    self._face_touch_start = now
                if (now - self._face_touch_start) >= FACE_TOUCH_DURATION:
                    notify_os("Face Touch Detected", "Avoid touching your face.")
                    self._emit_alert("Face Touch Detected")
                    self.today_face_touch_alerts += 1
                    self.session_face_touch_alerts += 1
                    self.after(0, lambda: self.session_face_touch_alerts_label.configure(text=f"Session Face Touch Alerts: {self.session_face_touch_alerts}"))
                    self._face_touch_start = now + FACE_TOUCH_COOLDOWN
            else:
                self._face_touch_detected = False
                self._face_touch_active_since = None
                self._face_touch_start = None
                with self.active_lock:
                    if "Face Touch Detected" in self.active_alerts:
                        self.active_alerts.discard("Face Touch Detected")
                        changed = True
            if changed:
                self.after(0, self._refresh_active_alerts)
        except Exception:
            log_exc()
    # Stats worker
    def _stats_worker(self):
        try:
            mp_face = mp.solutions.face_mesh.FaceMesh(static_image_mode=False, max_num_faces=1, refine_landmarks=True, min_detection_confidence=0.5)
            mp_pose = mp.solutions.pose.Pose(static_image_mode=False, model_complexity=1, min_detection_confidence=0.5, min_tracking_confidence=0.5)
            mp_hands = mp.solutions.hands.Hands(static_image_mode=False, max_num_hands=2, min_detection_confidence=0.5)
            CAM_W = 640
            CAM_H = 480
            self.last_hour = datetime.now().strftime("%Y-%m-%d %H")
            frame_counter = 0
            while self.running:
                try:
                    frame = self.frame_queue.get(timeout=0.5)  # Get shared frame from queue
                    if frame is None:
                        break
                except queue.Empty:
                    continue
                frame_counter += 1
                if STATS_PROCESS_EVERY > 1 and (frame_counter % STATS_PROCESS_EVERY):
                    continue
                try:
                    now = time.time()
                    current_hour = datetime.now().strftime("%Y-%m-%d %H")
                    if self.last_hour is None:
                        self.last_hour = current_hour
                    elif current_hour != self.last_hour:
                        self._flush_hourly_metrics(self.last_hour)
                        self.last_hour = current_hour
                    if self.enable_twenty and (now - getattr(self, "last_twenty", 0) > TWENTY_TWENTY_SEC):
                        notify_os("20-20-20 Reminder","Look 20ft away for 20 seconds.")
                        self.last_twenty = now
                        if cursor:
                            cursor.execute("INSERT INTO alerts VALUES (?, ?)", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "20-20-20 reminder")); conn.commit()
                            self._prepend_log_ui(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: 20-20-20 reminder")
                    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB); img_h, img_w = frame.shape[:2]
                    lm_px_norm = None
                    nose_px=None; face_width=None; shoulder_mid=None; detected_shoulders=None
                    mouth_box = None
                    hand_landmarks = None
                    face_detected = False
                    face_box = None
                    fres = mp_face.process(img_rgb)
                    pres = mp_pose.process(img_rgb)
                    missing_parts = 0
                    if fres and fres.multi_face_landmarks:
                        face_detected = True
                        lm = fres.multi_face_landmarks[0]
                        lm_px_norm = [(p.x, p.y) for p in lm.landmark]
                        if len(lm_px_norm) > NOSE_IDX:
                            nose_px = (int(lm_px_norm[NOSE_IDX][0]*img_w), int(lm_px_norm[NOSE_IDX][1]*img_h))
                        xs = [int(p.x*img_w) for p in lm.landmark]
                        ys = [int(p.y*img_h) for p in lm.landmark]
                        face_width = (max(xs)-min(xs)) if xs else None
                        if xs and ys:
                            min_x, max_x = max(0, min(xs)), min(img_w, max(xs))
                            min_y, max_y = max(0, min(ys)), min(img_h, max(ys))
                            pad_x = int(0.04 * (max_x - min_x) + 1)
                            pad_y = int(0.06 * (max_y - min_y) + 1)
                            fx = clamp(min_x - pad_x, 0, img_w - 1)
                            fy = clamp(min_y - pad_y, 0, img_h - 1)
                            fw = clamp(max_x + pad_x, 0, img_w) - fx
                            fh = clamp(max_y + pad_y, 0, img_h) - fy
                            face_box = (fx, fy, fw, fh)
                        left_eye_in = all(0 <= lm.landmark[i].x <=1 and 0 <= lm.landmark[i].y <=1 for i in LEFT_EYE_IDX if i < len(lm.landmark))
                        right_eye_in = all(0 <= lm.landmark[i].x <=1 and 0 <= lm.landmark[i].y <=1 for i in RIGHT_EYE_IDX if i < len(lm.landmark))
                        if not left_eye_in or not right_eye_in:
                            missing_parts += 1
                        mouth_pts = [(int(lm.landmark[i].x * img_w), int(lm.landmark[i].y * img_h)) for i in MOUTH_IDX if i < len(lm.landmark)]
                        if mouth_pts:
                            min_x = min(p[0] for p in mouth_pts)
                            max_x = max(p[0] for p in mouth_pts)
                            min_y = min(p[1] for p in mouth_pts)
                            max_y = max(p[1] for p in mouth_pts)
                            mw = max_x - min_x
                            mh = max_y - min_y
                            pad = 10
                            mouth_box = (min_x - pad, min_y - pad, mw + 2*pad, mh + 2*pad)
                    if pres and pres.pose_landmarks:
                        pts = pres.pose_landmarks.landmark
                        ls_i = mp.solutions.pose.PoseLandmark.LEFT_SHOULDER.value
                        rs_i = mp.solutions.pose.PoseLandmark.RIGHT_SHOULDER.value
                        ls = pts[ls_i]
                        rs = pts[rs_i]
                        if (0 < ls.x <1 and 0 < ls.y <1 and ls.visibility >0.5 and
                            0 < rs.x <1 and 0 < rs.y <1 and rs.visibility >0.5):
                            ls_px = (int(ls.x*img_w), int(ls.y*img_h))
                            rs_px = (int(rs.x*img_w), int(rs.y*img_h))
                            detected_shoulders = (ls_px, rs_px)
                            shoulder_mid = ((ls_px[0]+rs_px[0])/2.0, (ls_px[1]+rs_px[1])/2.0)
                        else:
                            missing_parts += 1
                    if self.enable_nail_biting or self.enable_face_touch:
                        hres = mp_hands.process(img_rgb)
                        if hres and hres.multi_hand_landmarks:
                            hand_landmarks = hres.multi_hand_landmarks
                        else:
                            hand_landmarks = None
                    if face_detected:
                        if not self.visible_start:
                            self.visible_start = now
                            self._session_start = now
                            self._session_count += 1
                        self._fully_missing_count = 0
                    else:
                        if self.slouch_session_start is not None:
                            self.slouch_accum_seconds += int(now - self.slouch_session_start)
                            self.slouch_session_start = None
                        for attr in ("_posture_start", "_posture_active_since", "_posture_notified"):
                            if getattr(self, attr, None) is not None:
                                try:
                                    delattr(self, attr)
                                except Exception:
                                    pass
                        with self.active_lock:
                            if "Bad Posture" in self.active_alerts:
                                self.active_alerts.discard("Bad Posture")
                                self.after(0, self._refresh_active_alerts)
                        self.posture_reasons.clear()
                        accum_session = self.slouch_accum_seconds
                        self.after(0, lambda a=accum_session: self.time_bad_posture_label.configure(text=f"Time with Bad Posture (session): {format_time_dynamic(int(round(a)))}"))
                        if self.visible_start:
                            diff_sec = int(now - self.visible_start)
                            self.visible_seconds += diff_sec
                            self.visible_start = None
                            if self._session_start:
                                session_length = now - self._session_start
                                self._session_start = None
                    total_visible = self.visible_seconds + (int(now - self.visible_start) if self.visible_start else 0)
                    delta_visible = max(0, total_visible - self._prev_total_visible)
                    if delta_visible > 0:
                        self.pending_hour_visible_seconds += delta_visible
                    self._prev_total_visible = total_visible
                    self.after(0, lambda t=total_visible: self.screen_time_label.configure(text=f"Screen Time: {format_time_dynamic(t)}"))
                    partial_flag = False
                    fully_out_flag = False
                    if not face_detected:
                        self._fully_missing_count += 1
                    else:
                        self._fully_missing_count = 0
                    if not self.last_eyes or len(self.last_eyes) < 2:
                        missing_parts += 1
                    if not self._smoothed_shoulder_mid:
                        missing_parts += 1
                    if missing_parts >= 1 and face_detected:
                        self._partial_missing_count += 1
                    else:
                        self._partial_missing_count = 0
                    if self._partial_missing_count >= 1:
                        partial_flag = True
                    if self._fully_missing_count >= 6:
                        fully_out_flag = True
                    if partial_flag and not fully_out_flag:
                        if getattr(self, "_partial_start", None) is None:
                            self._partial_start = now; self._partial_active_since = now
                        else:
                            if (now - getattr(self, "_partial_active_since", now)) >= self.active_alert_appear_seconds:
                                with self.active_lock:
                                    if "Please come fully into frame" not in self.active_alerts:
                                        self.active_alerts.add("Please come fully into frame")
                                        self.after(0, self._refresh_active_alerts)
                        if not getattr(self, "_partial_notified", False):
                            if (now - self._partial_start) >= max(1, self.delay_seconds):
                                notify_os("Frame Warning", "Please come fully into frame for accurate tracking.")
                                self._emit_alert("Partial Frame - Please come fully into frame")
                                self._partial_notified = True
                    else:
                        for n in ("_partial_start","_partial_active_since","_partial_notified"):
                            if getattr(self, n, None) is not None:
                                try: delattr(self, n)
                                except Exception: pass
                        with self.active_lock:
                            if "Please come fully into frame" in self.active_alerts:
                                self.active_alerts.discard("Please come fully into frame"); self.after(0, self._refresh_active_alerts)
                    current_slouch_total = self.slouch_accum_seconds + (int(now - self.slouch_session_start) if self.slouch_session_start else 0)
                    delta_slouch = max(0, current_slouch_total - self._prev_total_slouch)
                    if delta_slouch > 0:
                        self.pending_hour_slouch_seconds += delta_slouch
                    self._prev_total_slouch = current_slouch_total
                    if self.enable_posture and face_detected and nose_px and shoulder_mid and face_width and len(self.last_eyes) >= 2 and self._smoothed_shoulder_mid:
                        use_face_box = face_box or self.last_face_box
                        flags, diag = self._compute_posture_flags(nose_px, nose_px, shoulder_mid, detected_shoulders, face_width, mouth_box, use_face_box, hand_landmarks, (img_w, img_h))
                        self._update_posture_state(flags, diag)
                        self.after(0, lambda: self.time_bad_posture_label.configure(text=f"Time with Bad Posture (session): {format_time_dynamic(self.slouch_accum_seconds + (int(time.time()-self.slouch_session_start) if self.slouch_session_start else 0))}"))
                        horizontal_offset = diag.get('horizontal_offset_norm', 0)
                        self._horizontal_offset_history.append(horizontal_offset)
                        if len(self._horizontal_offset_history) > 10:
                            self._horizontal_offset_history.pop(0)
                        self.today_horizontal_offset_avg = np.mean(self._horizontal_offset_history)
                        self.after(0, lambda: self.horizontal_offset_label.configure(text=f"Avg Horizontal Offset: {round(self.today_horizontal_offset_avg, 2)}"))
                        eye_tilt = diag.get('eye_tilt_norm', 0)
                        self._eye_tilt_history.append(eye_tilt)
                        if len(self._eye_tilt_history) > 10:
                            self._eye_tilt_history.pop(0)
                        self.today_eye_tilt_avg = np.mean(self._eye_tilt_history)
                        self.after(0, lambda: self.eye_tilt_label.configure(text=f"Avg Eye Tilt: {round(self.today_eye_tilt_avg, 2)}"))
                        self.today_head_turn_time = self._head_turn_duration
                        self.after(0, lambda: self.head_turn_time_label.configure(text=f"Head Turn Time: {format_time_dynamic(int(self.today_head_turn_time))}"))
                        good_posture_time = total_visible - self.slouch_accum_seconds
                        self.today_posture_score = (good_posture_time / total_visible * 100) if total_visible > 0 else 0
                        self.after(0, lambda: self.posture_score_label.configure(text=f"Posture Score: {int(self.today_posture_score)}%"))
                        self.today_session_count = self._session_count
                        avg_session = (total_visible / self.today_session_count) if self.today_session_count > 0 else 0
                        self.after(0, lambda: self.avg_session_length_label.configure(text=f"Avg Session Length: {format_time_dynamic(int(avg_session))}"))
                    else:
                        self.after(0, lambda: self.time_bad_posture_label.configure(text=f"Time with Bad Posture (session): {format_time_dynamic(self.slouch_accum_seconds)}"))
                    pixel_ipd = None
                    try:
                        if lm_px_norm:
                            left = [lm_px_norm[i] for i in LEFT_EYE_IDX if i < len(lm_px_norm)]
                            right = [lm_px_norm[i] for i in RIGHT_EYE_IDX if i < len(lm_px_norm)]
                            if left and right:
                                lcx = sum(p[0] for p in left)/len(left); rcx = sum(p[0] for p in right)/len(right)
                                lcy = sum(p[1] for p in left)/len(left); rcy = sum(p[1] for p in right)/len(right)
                                pixel_ipd = np.linalg.norm(np.array((lcx*img_w,lcy*img_h)) - np.array((rcx*img_w,rcy*img_h)))
                    except Exception:
                        pixel_ipd = None
                    if pixel_ipd is None and len(self.last_eyes) >= 2:
                        try:
                            lx,ly,lw,lh = self.last_eyes[0]; rx,ry,rw,rh = self.last_eyes[1]
                            left = (lx + lw/2.0, ly + lh/2.0); right = (rx + rw/2.0, ry + rh/2.0)
                            pixel_ipd = np.linalg.norm(np.array(left) - np.array(right))
                        except Exception:
                            pixel_ipd = None
                    distance_cm = None
                    if self.enable_distance:
                        if pixel_ipd and pixel_ipd>2.0:
                            try:
                                real_ipd = self.calib.get("real_ipd_cm", self.real_ipd_cm)
                                focal = self.calib.get("focal_length", self.focal_length)
                                if real_ipd and focal:
                                    distance_cm = (real_ipd * focal) / float(pixel_ipd)
                                    prev = getattr(self, "_smoothed_distance_cm", None)
                                    beta = 0.6
                                    self._smoothed_distance_cm = distance_cm if prev is None else (beta * distance_cm + (1-beta) * prev)
                                    distance_cm = self._smoothed_distance_cm
                            except Exception:
                                distance_cm = None
                        if distance_cm is None and face_width is not None and face_width > 8:
                            try:
                                focal = self.calib.get("focal_length", self.focal_length)
                                avg_face_cm = 14.0
                                distance_cm = (avg_face_cm * focal) / float(face_width)
                                prev = getattr(self, "_smoothed_distance_cm", None)
                                beta = 0.6
                                self._smoothed_distance_cm = distance_cm if prev is None else (beta * distance_cm + (1-beta) * prev)
                                distance_cm = self._smoothed_distance_cm
                            except Exception:
                                distance_cm = None
                        if distance_cm is not None:
                            try:
                                sample_val = float(distance_cm)
                                self.distances_buffer.append(sample_val)
                                if len(self.distances_buffer) > 600: self.distances_buffer.pop(0)
                                if self.unit == "in":
                                    d_display = int(round(sample_val / 2.54)); unit_label="in"
                                else:
                                    d_display = int(round(sample_val)); unit_label="cm"
                                self.after(0, lambda d=d_display,u=unit_label: self.distance_label.configure(text=f"Screen Distance: {d} {u}"))
                                self.distance_sum_total += sample_val
                                self.distance_count_total += 1
                                self.pending_distance_sum += sample_val
                                self.pending_distance_count += 1
                                self.pending_hour_distance_sum += sample_val
                                self.pending_hour_distance_count += 1
                                if self.distance_count_total > 0:
                                    self.today_avg_cm = self.distance_sum_total / self.distance_count_total
                            except Exception:
                                pass
                        if self.distances_buffer:
                            avg_cm = sum(self.distances_buffer)/len(self.distances_buffer)
                            if self.unit=="in": ad = round(avg_cm/2.54); u="in"
                            else: ad=int(round(avg_cm)); u="cm"
                            self.after(0, lambda a=ad,uu=u: self.avg_distance_label.configure(text=f"Average Distance (session): {a} {uu}"))
                            self.after(0, lambda a=ad,uu=u: self.today_avg_distance_label.configure(text=f"Avg Distance: {a} {u}"))
                            is_too_close = False
                            if distance_cm is not None:
                                is_too_close = distance_cm < float(self.min_distance_cm)
                            if is_too_close:
                                if getattr(self, "too_close_start", None) is None:
                                    self.too_close_start = now; self.too_close_active_since = now
                                else:
                                    if (now - getattr(self, "too_close_active_since", now)) >= self.active_alert_appear_seconds:
                                        with self.active_lock:
                                            if "Distance Alerts - Too close to screen" not in self.active_alerts:
                                                self.active_alerts.add("Distance Alerts - Too close to screen"); self.after(0, self._refresh_active_alerts)
                                if now - self.too_close_start > max(1, int(self.delay_seconds)):
                                    notify_os("Too Close", "Move back from the screen.")
                                    self._emit_alert("Distance Alerts - Too close to screen")
                                    self.today_distance_alerts += 1
                                    self.session_distance_alerts += 1
                                    self.after(0, lambda: self.session_distance_alerts_label.configure(text=f"Session Distance Alerts: {self.session_distance_alerts}"))
                                    self.too_close_start = now + 60
                            else:
                                self.too_close_start = None
                                with self.active_lock:
                                    if "Distance Alerts - Too close to screen" in self.active_alerts:
                                        self.active_alerts.discard("Distance Alerts - Too close to screen"); self.after(0, self._refresh_active_alerts)
                    self._refresh_active_alerts()
                    self.after(0, self._update_feedback)
                    # Save to DB
                    if now - self.last_save_time > SAVE_INTERVAL_SEC and cursor:
                        try:
                            today_str = date.today().isoformat()
                            current_hour = datetime.now().strftime("%Y-%m-%d %H")
                            current_visible = total_visible
                            changes_made = False
                            diff_visible = max(0, current_visible - self.saved_visible_seconds)
                            if diff_visible > 0:
                                cursor.execute("SELECT duration_sec FROM screen_time WHERE date = ?", (today_str,))
                                res = cursor.fetchone()
                                current_sec = res[0] if res else 0
                                new_sec = current_sec + diff_visible
                                cursor.execute("INSERT OR REPLACE INTO screen_time (date, duration_sec) VALUES (?, ?)", (today_str, new_sec))
                                self.today_screen_sec = new_sec
                                self.saved_visible_seconds = current_visible
                                changes_made = True
                            current_slouch = current_slouch_total
                            diff_slouch = max(0, current_slouch - self.saved_slouch_seconds)
                            if diff_slouch > 0:
                                cursor.execute("SELECT seconds FROM posture_time WHERE date = ?", (today_str,))
                                res = cursor.fetchone()
                                current_sec = res[0] if res else 0
                                new_sec = current_sec + diff_slouch
                                cursor.execute("INSERT OR REPLACE INTO posture_time (date, seconds) VALUES (?, ?)", (today_str, new_sec))
                                self.today_posture_sec = new_sec
                                self.saved_slouch_seconds = current_slouch
                                changes_made = True
                            if self.enable_distance and self.pending_distance_count > 0:
                                cursor.execute("SELECT avg_distance_cm, count FROM distance_log WHERE date = ?", (today_str,))
                                res = cursor.fetchone()
                                old_avg = res[0] if res and res[0] is not None else 0.0
                                old_count = res[1] if res and res[1] is not None else 0
                                old_sum = old_avg * old_count
                                new_total_sum = old_sum + self.pending_distance_sum
                                new_total_count = old_count + self.pending_distance_count
                                new_avg = new_total_sum / new_total_count if new_total_count > 0 else 0.0
                                cursor.execute("INSERT OR REPLACE INTO distance_log (date, avg_distance_cm, count) VALUES (?, ?, ?)",
                                               (today_str, new_avg, new_total_count))
                                self.today_avg_cm = new_avg
                                self.today_distance_count = new_total_count
                                self.distance_sum_total = new_total_sum
                                self.distance_count_total = new_total_count
                                self.pending_distance_sum = 0.0
                                self.pending_distance_count = 0
                                changes_made = True
                            hourly_changed = self._flush_hourly_metrics(current_hour, auto_commit=False)
                            if hourly_changed:
                                changes_made = True
                            if changes_made:
                                conn.commit()
                                self.last_save_time = now
                                self.after(0, lambda: self.today_screen_label.configure(text=f"Screen Time: {format_time_dynamic(self.today_screen_sec)}"))
                                if self.today_avg_cm is not None:
                                    if self.unit == "in":
                                        ad = round(self.today_avg_cm / 2.54,1)
                                        u = "in"
                                    else:
                                        ad = int(round(self.today_avg_cm))
                                        u = "cm"
                                    self.after(0, lambda a=ad, uu=u: self.today_avg_distance_label.configure(text=f"Avg Distance: {a} {u}"))
                                self.after(0, self._reload_pinned_graphs)
                        except Exception:
                            log_exc()
                    # Check if window is minimized or out of focus
                    if self.state() == 'iconic' or self.focus_get() is None:
                        time.sleep(2.0) # Reduce processing rate
                    else:
                        time.sleep(0.8)
                except Exception:
                    log_exc()
                    time.sleep(0.5)
        except Exception:
            log_exc()
    def _flush_hourly_metrics(self, hour_key, auto_commit=True):
        try:
            if cursor is None or hour_key is None:
                return False
            changed = False
            reset_visible = reset_slouch = reset_distance = False
            if self.pending_hour_visible_seconds > 0:
                cursor.execute("SELECT duration_sec FROM screen_hourly WHERE date_hour = ?", (hour_key,))
                res = cursor.fetchone()
                current_h_sec = res[0] if res else 0
                new_h_sec = current_h_sec + int(self.pending_hour_visible_seconds)
                cursor.execute("INSERT OR REPLACE INTO screen_hourly (date_hour, duration_sec) VALUES (?, ?)", (hour_key, new_h_sec))
                reset_visible = True
                changed = True
            if self.pending_hour_slouch_seconds > 0:
                cursor.execute("SELECT seconds FROM posture_hourly WHERE date_hour = ?", (hour_key,))
                res = cursor.fetchone()
                current_h_sec = res[0] if res else 0
                new_h_sec = current_h_sec + int(self.pending_hour_slouch_seconds)
                cursor.execute("INSERT OR REPLACE INTO posture_hourly (date_hour, seconds) VALUES (?, ?)", (hour_key, new_h_sec))
                reset_slouch = True
                changed = True
            if self.pending_hour_distance_count > 0:
                cursor.execute("SELECT sum_distance_cm, count FROM distance_hourly WHERE date_hour = ?", (hour_key,))
                res = cursor.fetchone()
                current_h_sum = res[0] if res and res[0] is not None else 0.0
                current_h_count = res[1] if res and res[1] is not None else 0
                new_h_sum = current_h_sum + self.pending_hour_distance_sum
                new_h_count = current_h_count + self.pending_hour_distance_count
                cursor.execute("INSERT OR REPLACE INTO distance_hourly (date_hour, sum_distance_cm, count) VALUES (?, ?, ?)",
                               (hour_key, new_h_sum, new_h_count))
                reset_distance = True
                changed = True
            if changed and auto_commit:
                conn.commit()
            if reset_visible:
                self.pending_hour_visible_seconds = 0
            if reset_slouch:
                self.pending_hour_slouch_seconds = 0
            if reset_distance:
                self.pending_hour_distance_sum = 0.0
                self.pending_hour_distance_count = 0
            return changed
        except Exception:
            log_exc()
            return False
    # Active alerts widget
    def _refresh_active_alerts(self):
        try:
            if threading.current_thread() is not threading.main_thread():
                self.after(0, self._refresh_active_alerts); return
            with self.active_lock:
                items = sorted(self.active_alerts)
            self.active_list.configure(state="normal"); self.active_list.delete("0.0","end")
            for a in items:
                if a == "Bad Posture":
                    reasons_str = ", ".join(self.posture_reasons) if self.posture_reasons else ""
                    content = f": {reasons_str}" if reasons_str else ""
                    title = "Bad Posture"
                elif a == "Nail Biting Detected":
                    title = "Nail Biting Detected"
                    content = ": Fingertips near mouth"
                elif a == "Face Touch Detected":
                    title = "Face Touch Detected"
                    content = ": Hand contact with face"
                else:
                    parts = a.split(":", 1)
                    title = parts[0].strip()
                    content = f": {parts[1].strip()}" if len(parts) > 1 else ""
                self.active_list.insert("end", title, ("alert_title",))
                self.active_list.insert("end", f"{content}\n")
            self.active_list.configure(state="disabled")
            try:
                self.active_list.tag_config("alert_title", foreground=GRAPH_COLOR_ALERTS)
            except Exception:
                pass
        except Exception:
            log_exc()
    def _emit_alert(self, message: str):
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if cursor:
                cursor.execute("INSERT INTO alerts VALUES (?, ?)", (ts, message)); conn.commit()
            self.after(0, lambda m=f"{ts}: {message}": self._prepend_log_ui(m))
            self.after(0, self._reload_pinned_graphs)
        except Exception:
            log_exc()
    # Calibration
    def _guided_calibration_prompt(self):
        try:
            res = messagebox.askyesno("Calibration", "Start full guided calibration now? You will be asked to hold a standard card at your mouth/upper-lip inside the on-screen box.")
            if not res: return
            ok = self._run_card_calibration(preview_size=(CALIB_PREVIEW_W, CALIB_PREVIEW_H))
            if not ok:
                messagebox.showerror("Calibration", "Card calibration failed.")
                return
            res2 = messagebox.askyesno("Calibration", "Card calibration done. Capture neutral posture now? Sit upright and press Yes to capture baseline posture.")
            if res2:
                self._capture_neutral(preview_size=(CALIB_PREVIEW_W, CALIB_PREVIEW_H))
            messagebox.showinfo("Calibration", "Calibration complete.")
        except Exception:
            log_exc(); messagebox.showerror("Calibration", "Guided calibration failed to start.")
    def _run_card_calibration(self, preview_size=(384,288)) -> bool:
        try:
            calib_win = ctk.CTkToplevel(self)
            calib_win.title("Card Calibration")
            pw, ph = preview_size
            calib_win.geometry(f"{pw+30}x{ph+120}")
            instr = ctk.CTkLabel(calib_win, text="Hold standard card horizontally against your upper lip. Move it to fit inside the green box. Press Confirm.")
            instr.pack(pady=6)
            video_lab = ctk.CTkLabel(calib_win, text="")
            video_lab.pack()
            # Box to fit card to
            box_scale = 0.15 
            box_w = int(pw * box_scale)
            box_h = int(box_w / REAL_CARD_ASPECT)
            box_x = (pw - box_w)//2; box_y = int(ph*0.45)
            confirm_state = {"ok": False, "pixel_card": None}
            cap = get_camera_cap()
            if cap is None:
                messagebox.showerror("Camera Error", "No camera detected for calibration.")
                calib_win.destroy()
                return False
            stop_flag = {"stop": False}
            fail_count = {"count": 0}
            def update_loop():
                try:
                    time.sleep(0.5)
                    while not stop_flag["stop"]:
                        ret, frame = cap.read()
                        if not ret:
                            fail_count["count"] += 1
                            if fail_count["count"] >= 10:
                                stop_flag["stop"] = True
                                def _notify_fail():
                                    messagebox.showerror("Camera Error", "Camera feed unavailable during calibration.")
                                    try:
                                        calib_win.destroy()
                                    except Exception:
                                        pass
                                self.after(0, _notify_fail)
                                break
                            time.sleep(0.1); continue
                        fail_count["count"] = 0
                        frame = cv2.flip(frame, 1)
                        frame = cv2.resize(frame, (pw, ph))
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        pil = Image.fromarray(frame_rgb).convert("RGBA")
                        overlay = Image.new("RGBA", pil.size, (0,0,0,0))
                        draw = ImageDraw.Draw(overlay)
                        draw.rounded_rectangle([box_x, box_y, box_x+box_w, box_y+box_h], radius=8, outline=(50,200,50,255), width=3)
                        pil = Image.alpha_composite(pil, overlay)
                        mask = Image.new("L", pil.size, 0)
                        draw = ImageDraw.Draw(mask)
                        draw.rounded_rectangle([0, 0, pw, ph], radius=16, fill=255)
                        pil.putalpha(mask)
                        ctk_img = CTkImage(light_image=pil, dark_image=pil, size=(pw, ph))
                        video_lab.configure(image=ctk_img)
                        video_lab.image = ctk_img
                        time.sleep(0.03)
                        if not calib_win.winfo_exists():
                            break
                except Exception:
                    log_exc()
            t = threading.Thread(target=update_loop, daemon=True); t.start()
            def confirm():
                try:
                    ret, frame = cap.read()
                    if not ret:
                        messagebox.showerror("Calibration", "Camera read failed.")
                        return
                    frame = cv2.flip(frame, 1) # mirror
                    frame = cv2.resize(frame, (pw, ph))
                    roi = frame[box_y:box_y+box_h, box_x:box_x+box_w]
                    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                    blur = cv2.GaussianBlur(gray, (5,5), 0)
                    edges = cv2.Canny(blur, 50, 150)
                    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    if not contours:
                        messagebox.showerror("Calibration", "Could not detect card in box. Make sure card edges are visible and try again.")
                        return
                    best_w = 0
                    for c in contours:
                        x,y,w,h = cv2.boundingRect(c)
                        if w > best_w and w > h and w > 8:
                            best_w = w
                    if best_w <= 0:
                        messagebox.showerror("Calibration", "Could not detect a clear card width. Try again with better lighting.")
                        return
                    pixel_card_preview = best_w
                    scale = float(640) / float(pw)
                    pixel_card_cam = pixel_card_preview * scale
                    focal = (pixel_card_cam * ASSUMED_CALIB_DISTANCE_CM) / REAL_CARD_WIDTH_CM
                    self.calib['focal_length'] = float(focal)
                    self.calib['card_pixel_width'] = float(pixel_card_cam)
                    self.calib['real_ipd_cm'] = float(self.calib.get('real_ipd_cm', 6.3))
                    save_json(CALIB_FILE, self.calib)
                    confirm_state['ok'] = True
                    confirm_state['pixel_card'] = pixel_card_cam
                    messagebox.showinfo("Calibration", "Card calibration complete.")
                    stop_flag["stop"] = True
                    try: calib_win.destroy()
                    except Exception: pass
                except Exception:
                    log_exc(); messagebox.showerror("Calibration", "Card calibration failed. Try again.")
            def cancel():
                stop_flag["stop"] = True
                try: calib_win.destroy()
                except Exception: pass
            btn_frame = ctk.CTkFrame(calib_win)
            btn_frame.pack(pady=8)
            ctk.CTkButton(btn_frame, text="Confirm", command=confirm).pack(side="left", padx=6)
            ctk.CTkButton(btn_frame, text="Cancel", command=cancel).pack(side="left", padx=6)
            self.wait_window(calib_win)
            try: cap.release()
            except Exception: pass
            return confirm_state['ok']
        except Exception:
            log_exc()
            return False
    def _capture_neutral(self, preview_size=(384,288)):
        try:
            win = ctk.CTkToplevel(self); win.title("Capture Neutral Posture")
            pw, ph = preview_size
            win.geometry(f"{pw+30}x{ph+120}")
            ctk.CTkLabel(win, text="Sit upright in natural neutral posture and press Confirm.").pack(pady=6)
            video_lab = ctk.CTkLabel(win, text=""); video_lab.pack()
            cap = get_camera_cap()
            if cap is None:
                messagebox.showerror("Camera Error", "No camera detected for calibration.")
                win.destroy()
                return
            sample = {"face_width": None, "shoulder_span": None}
            stop_flag = {"stop": False}
            fail_count = {"count": 0}
            def update_loop2():
                try:
                    time.sleep(0.5)
                    while not stop_flag["stop"]:
                        ret, frame = cap.read()
                        if not ret:
                            fail_count["count"] += 1
                            if fail_count["count"] >= 10:
                                stop_flag["stop"] = True
                                def _notify_fail():
                                    messagebox.showerror("Camera Error", "Camera feed unavailable during calibration.")
                                    try:
                                        win.destroy()
                                    except Exception:
                                        pass
                                self.after(0, _notify_fail)
                                break
                            time.sleep(0.1); continue
                        fail_count["count"] = 0
                        frame = cv2.flip(frame, 1)
                        frame = cv2.resize(frame, (pw, ph))
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        pil = Image.fromarray(frame_rgb).convert("RGBA")
                        mask = Image.new("L", pil.size, 0)
                        draw = ImageDraw.Draw(mask)
                        draw.rounded_rectangle([0, 0, pw, ph], radius=16, fill=255)
                        pil.putalpha(mask)
                        ctk_img = CTkImage(light_image=pil, dark_image=pil, size=(pw, ph))
                        video_lab.configure(image=ctk_img)
                        video_lab.image = ctk_img
                        time.sleep(0.03)
                        if not win.winfo_exists():
                            break
                except Exception:
                    log_exc()
            t = threading.Thread(target=update_loop2, daemon=True); t.start()
            def confirm_neutral():
                try:
                    ret, frame = cap.read()
                    if not ret:
                        messagebox.showerror("Neutral", "Camera read failed."); return
                    face_width_px = None; shoulder_span = None; eye_tilt_angle = None
                    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mpf = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, refine_landmarks=True, min_detection_confidence=0.5)
                    res = mpf.process(img_rgb)
                    if res and res.multi_face_landmarks:
                        lm = res.multi_face_landmarks[0].landmark
                        xs = [p.x for p in lm]; ys = [p.y for p in lm]
                        if xs:
                            face_width_px = (max(xs)-min(xs)) * frame.shape[1]
                        # Compute face tilt
                        left = np.mean([[lm[i].x * frame.shape[1], lm[i].y * frame.shape[0]] for i in LEFT_EYE_IDX], axis=0)
                        right = np.mean([[lm[i].x * frame.shape[1], lm[i].y * frame.shape[0]] for i in RIGHT_EYE_IDX], axis=0)
                        dx = right[0] - left[0]
                        dy = right[1] - left[1]
                        eye_tilt_angle = math.degrees(math.atan2(dy, dx))
                    mpp = mp.solutions.pose.Pose(static_image_mode=True, model_complexity=1, min_detection_confidence=0.5)
                    pres = mpp.process(img_rgb)
                    if pres and pres.pose_landmarks:
                        ls = pres.pose_landmarks.landmark[mp.solutions.pose.PoseLandmark.LEFT_SHOULDER.value]
                        rs = pres.pose_landmarks.landmark[mp.solutions.pose.PoseLandmark.RIGHT_SHOULDER.value]
                        ls_px = (int(ls.x*frame.shape[1]), int(ls.y*frame.shape[0])); rs_px = (int(rs.x*frame.shape[1]), int(rs.y*frame.shape[0]))
                        shoulder_span = float(np.linalg.norm(np.array(ls_px)-np.array(rs_px)))
                    self.calib['neutral'] = {"face_width_px": float(face_width_px) if face_width_px else None,
                                             "shoulder_span_px": float(shoulder_span) if shoulder_span else None,
                                             "eye_tilt_angle": float(eye_tilt_angle) if eye_tilt_angle is not None else 0.0}
                    save_json(CALIB_FILE, self.calib)
                    messagebox.showinfo("Neutral", "Neutral posture captured.")
                    stop_flag["stop"] = True
                    try: win.destroy()
                    except Exception: pass
                except Exception:
                    log_exc(); messagebox.showerror("Neutral", "Failed to capture neutral posture.")
            btn_frame = ctk.CTkFrame(win); btn_frame.pack(pady=8)
            ctk.CTkButton(btn_frame, text="Confirm", command=confirm_neutral).pack(side="left", padx=6)
            ctk.CTkButton(btn_frame, text="Cancel", command=lambda: (stop_flag.update({"stop": True}), win.destroy())).pack(side="left", padx=6)
            self.wait_window(win)
            try: cap.release()
            except Exception: pass
        except Exception:
            log_exc()
    # Stats widget
    def _open_stats_window(self):
        try:
            if hasattr(self, 'stats_win') and self.stats_win.winfo_exists():
                self.stats_win.lift()
                return
            self._stats_period_stack.clear()
            self.stats_win = ctk.CTkToplevel(self)
            self.stats_win.title("Statistics")
            self.stats_win.geometry("1100x760")
            options_frame = ctk.CTkFrame(self.stats_win, width=220)
            options_frame.pack(side="left", fill="y", padx=12, pady=12)
            options_inner = ctk.CTkFrame(options_frame, fg_color="transparent")
            options_inner.pack(fill="both", expand=True, padx=12, pady=12)
            ctk.CTkLabel(options_inner, text="Options", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=4, pady=(0, 10))
            period_frame = ctk.CTkFrame(options_inner)
            period_frame.pack(fill="x", pady=4, padx=4)
            ctk.CTkLabel(period_frame, text="Time Period:").pack(side="left", padx=4)
            self.opt_period = ctk.CTkOptionMenu(period_frame, values=["Day","Week","Month","Year"], command=self._update_current_period, width=120)
            self._set_option_menu_value(self.opt_period, self.current_period, "_suppress_period_callback")
            self.opt_period.pack(side="right", padx=4)
            type_frame = ctk.CTkFrame(options_inner)
            type_frame.pack(fill="x", pady=4, padx=4)
            ctk.CTkLabel(type_frame, text="Chart Type:").pack(side="left", padx=4)
            self.opt_type = ctk.CTkOptionMenu(type_frame, values=["Bar","Line"], command=self._update_current_type, width=120)
            self._set_option_menu_value(self.opt_type, self.current_chart_type, "_suppress_type_callback")
            self.opt_type.pack(side="right", padx=4)
            self._init_calendar(options_inner)
            back_frame = ctk.CTkFrame(self.stats_win)
            back_frame.configure(height=44)
            back_frame.pack(fill="x", padx=8, pady=(0,4))
            back_frame.pack_propagate(False)
            back_frame.grid_columnconfigure(0, weight=0)
            back_frame.grid_columnconfigure(1, weight=1)
            self.back_btn = ctk.CTkButton(back_frame, text="Back", fg_color=self.accent_color, command=self._on_back_stats, width=88)
            self._back_btn_grid_kwargs = {"row": 0, "column": 0, "sticky": "w", "padx": (0, 8), "pady": 4}
            self.back_btn_placeholder = ctk.CTkLabel(back_frame, text="")
            self.back_btn_placeholder.grid(row=0, column=1, sticky="ew")
            self._back_btn_visible = False
            self._update_back_button()
            nb = ctk.CTkTabview(self.stats_win)
            nb.pack(side="left", fill="both", expand=True, padx=8, pady=8)
            nb.add("Screen Time"); nb.add("Posture Alerts"); nb.add("Average Distance"); nb.add("Distance Alerts"); nb.add("Nail Biting Alerts"); nb.add("Face Touch Alerts")
            self.f1 = ctk.CTkFrame(nb.tab("Screen Time")); self.f1.pack(fill="both", expand=True, padx=8, pady=8)
            self.fig1, self.ax1 = plt.subplots(figsize=(9, 5.0625)); self.canvas1 = FigureCanvasTkAgg(self.fig1, master=self.f1); self.canvas1.get_tk_widget().pack(fill="both", expand=True)
            self._draw_screen_chart(self.fig1, self.ax1, self.canvas1, self.current_period, self.current_chart_type)
            self.f2 = ctk.CTkFrame(nb.tab("Posture Alerts")); self.f2.pack(fill="both", expand=True, padx=8, pady=8)
            self.fig2, self.ax2 = plt.subplots(figsize=(9, 5.0625)); self.canvas2 = FigureCanvasTkAgg(self.fig2, master=self.f2); self.canvas2.get_tk_widget().pack(fill="both", expand=True)
            self._draw_posture_alerts_chart(self.fig2, self.ax2, self.canvas2, self.current_period, self.current_chart_type)
            self.f3 = ctk.CTkFrame(nb.tab("Average Distance")); self.f3.pack(fill="both", expand=True, padx=8, pady=8)
            self.fig3, self.ax3 = plt.subplots(figsize=(9, 5.0625)); self.canvas3 = FigureCanvasTkAgg(self.fig3, master=self.f3); self.canvas3.get_tk_widget().pack(fill="both", expand=True)
            self._draw_distance_chart(self.fig3, self.ax3, self.canvas3, self.current_period, self.current_chart_type)
            self.f4 = ctk.CTkFrame(nb.tab("Distance Alerts")); self.f4.pack(fill="both", expand=True, padx=8, pady=8)
            self.fig4, self.ax4 = plt.subplots(figsize=(9, 5.0625)); self.canvas4 = FigureCanvasTkAgg(self.fig4, master=self.f4); self.canvas4.get_tk_widget().pack(fill="both", expand=True)
            self._draw_distance_notifications_chart(self.fig4, self.ax4, self.canvas4, self.current_period, self.current_chart_type)
            self.f5 = ctk.CTkFrame(nb.tab("Nail Biting Alerts")); self.f5.pack(fill="both", expand=True, padx=8, pady=8)
            self.fig5, self.ax5 = plt.subplots(figsize=(9, 5.0625)); self.canvas5 = FigureCanvasTkAgg(self.fig5, master=self.f5); self.canvas5.get_tk_widget().pack(fill="both", expand=True)
            self._draw_nail_biting_chart(self.fig5, self.ax5, self.canvas5, self.current_period, self.current_chart_type)
            self.f6 = ctk.CTkFrame(nb.tab("Face Touch Alerts")); self.f6.pack(fill="both", expand=True, padx=8, pady=8)
            self.fig6, self.ax6 = plt.subplots(figsize=(9, 5.0625)); self.canvas6 = FigureCanvasTkAgg(self.fig6, master=self.f6); self.canvas6.get_tk_widget().pack(fill="both", expand=True)
            self._draw_face_touch_chart(self.fig6, self.ax6, self.canvas6, self.current_period, self.current_chart_type)
            self._apply_accent_theme(self.stats_win)
            self.stats_win.protocol("WM_DELETE_WINDOW", lambda: self.stats_win.destroy())
        except Exception:
            log_exc()
    def _on_back_stats(self):
        try:
            if not self._stats_period_stack:
                return
            prev_period, prev_view = self._stats_period_stack.pop()
            self.current_period = prev_period
            self.current_view_start = prev_view
            if hasattr(self, "opt_period"):
                self._set_option_menu_value(self.opt_period, self.current_period, "_suppress_period_callback")
            self._redraw_all_stats_charts()
        except Exception:
            log_exc()
    def _update_current_period(self, val):
        try:
            if getattr(self, "_suppress_period_callback", False):
                return
            self.current_period = val
            self.current_view_start = None
            self._stats_period_stack.clear()
            self._redraw_all_stats_charts()
            if val == "Day":
                self._update_calendar_selection(date.today(), ensure_visible=True)
        except Exception:
            log_exc()
    def _update_current_type(self, val):
        try:
            if getattr(self, "_suppress_type_callback", False):
                return
            self.current_chart_type = val
            self._redraw_all_stats_charts()
        except Exception:
            log_exc()
    def _init_calendar(self, parent):
        try:
            self.calendar_frame = ctk.CTkFrame(parent)
            self.calendar_frame.pack(fill="x", pady=(12,8))
            ctk.CTkLabel(self.calendar_frame, text="Browse Dates", font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=6, pady=(0,4))
            header = ctk.CTkFrame(self.calendar_frame, fg_color="transparent")
            header.pack(fill="x", padx=0, pady=(0,4))
            self.calendar_prev_btn = ctk.CTkButton(header, text="<", width=28, command=lambda: self._change_calendar_month(-1))
            self.calendar_prev_btn.pack(side="left", padx=(0,6))
            self.calendar_title = ctk.CTkLabel(header, text="", font=ctk.CTkFont(size=12, weight="bold"))
            self.calendar_title.pack(side="left", expand=True)
            self.calendar_next_btn = ctk.CTkButton(header, text=">", width=28, command=lambda: self._change_calendar_month(1))
            self.calendar_next_btn.pack(side="right", padx=(6,0))
            self.calendar_grid = ctk.CTkFrame(self.calendar_frame, fg_color="transparent")
            self.calendar_grid.pack(fill="x")
            base_date = None
            if self.current_period == "Day" and self.current_view_start:
                base_date = self.current_view_start
            if base_date is None:
                base_date = date.today()
            self.calendar_selected_date = base_date
            self.calendar_year = base_date.year
            self.calendar_month = base_date.month
            self._refresh_calendar()
        except Exception:
            log_exc()
    def _change_calendar_month(self, delta):
        try:
            if self.calendar_year is None or self.calendar_month is None:
                return
            new_month = self.calendar_month + delta
            new_year = self.calendar_year
            while new_month < 1:
                new_month += 12
                new_year -= 1
            while new_month > 12:
                new_month -= 12
                new_year += 1
            self.calendar_month = new_month
            self.calendar_year = new_year
            self._refresh_calendar()
        except Exception:
            log_exc()
    def _refresh_calendar(self):
        try:
            if not hasattr(self, "calendar_grid") or self.calendar_year is None or self.calendar_month is None:
                return
            for widget in self.calendar_grid.winfo_children():
                widget.destroy()
            month_name = date(self.calendar_year, self.calendar_month, 1).strftime("%B %Y")
            if hasattr(self, "calendar_title"):
                self.calendar_title.configure(text=month_name)
            weekdays = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
            for col, name in enumerate(weekdays):
                lbl = ctk.CTkLabel(self.calendar_grid, text=name, width=32, anchor="center")
                lbl.grid(row=0, column=col, padx=1, pady=1, sticky="nsew")
            self.calendar_buttons = []
            month_matrix = calendar.monthcalendar(self.calendar_year, self.calendar_month)
            for row_idx, week in enumerate(month_matrix, start=1):
                for col_idx, day_num in enumerate(week):
                    if day_num == 0:
                        lbl = ctk.CTkLabel(self.calendar_grid, text="", width=32)
                        lbl.grid(row=row_idx, column=col_idx, padx=1, pady=1, sticky="nsew")
                    else:
                        btn_date = date(self.calendar_year, self.calendar_month, day_num)
                        btn = ctk.CTkButton(
                            self.calendar_grid,
                            text=str(day_num),
                            width=32,
                            command=lambda d=day_num: self._select_calendar_day(d)
                        )
                        btn.grid(row=row_idx, column=col_idx, padx=1, pady=1, sticky="nsew")
                        self.calendar_buttons.append((btn_date, btn))
            self._update_calendar_highlight()
        except Exception:
            log_exc()
    def _update_calendar_highlight(self):
        try:
            if not hasattr(self, "calendar_buttons"):
                return
            selected = self.calendar_selected_date
            fg_default = self._get_fg_color()
            hover_default = self._brighten_hex(self.accent_color)
            for date_obj, btn in list(self.calendar_buttons):
                if not btn.winfo_exists():
                    continue
                if selected and date_obj == selected:
                    btn.configure(fg_color=self.accent_color,
                                  text_color=self._contrast_for_accent(),
                                  hover_color=self._darken_hex(self.accent_color))
                else:
                    btn.configure(fg_color="transparent",
                                  text_color=fg_default,
                                  hover_color=hover_default)
        except Exception:
            log_exc()
    def _select_calendar_day(self, day):
        try:
            if self.calendar_year is None or self.calendar_month is None:
                return
            target = date(self.calendar_year, self.calendar_month, day)
            self.calendar_selected_date = target
            self._stats_period_stack.clear()
            self.current_period = "Day"
            self.current_view_start = target
            if hasattr(self, "opt_period"):
                self._set_option_menu_value(self.opt_period, "Day", "_suppress_period_callback")
            self._redraw_all_stats_charts()
            self._update_calendar_highlight()
        except Exception:
            log_exc()
    def _update_calendar_selection(self, target_date, ensure_visible=True):
        try:
            if not hasattr(self, "calendar_grid"):
                return
            if target_date is None:
                self.calendar_selected_date = None
            else:
                self.calendar_selected_date = target_date
                if ensure_visible or self.calendar_year is None or self.calendar_month is None:
                    self.calendar_year = target_date.year
                    self.calendar_month = target_date.month
            self._refresh_calendar()
        except Exception:
            log_exc()
    def _redraw_all_stats_charts(self):
        try:
            if hasattr(self, 'stats_win') and self.stats_win.winfo_exists():
                self._draw_screen_chart(self.fig1, self.ax1, self.canvas1, self.current_period, self.current_chart_type)
                self._draw_posture_alerts_chart(self.fig2, self.ax2, self.canvas2, self.current_period, self.current_chart_type)
                self._draw_distance_chart(self.fig3, self.ax3, self.canvas3, self.current_period, self.current_chart_type)
                self._draw_distance_notifications_chart(self.fig4, self.ax4, self.canvas4, self.current_period, self.current_chart_type)
                self._draw_nail_biting_chart(self.fig5, self.ax5, self.canvas5, self.current_period, self.current_chart_type)
                self._draw_face_touch_chart(self.fig6, self.ax6, self.canvas6, self.current_period, self.current_chart_type)
                self._update_back_button()
        except Exception:
            log_exc()
    def _update_back_button(self):
        try:
            if not hasattr(self, 'back_btn'):
                return
            target_visible = bool(self._stats_period_stack)
            if target_visible and not self._back_btn_visible:
                if self._back_btn_grid_kwargs:
                    self.back_btn.grid(**self._back_btn_grid_kwargs)
                else:
                    self.back_btn.grid(row=0, column=0, sticky="w", padx=(0,8), pady=4)
                self._back_btn_visible = True
            elif not target_visible and self._back_btn_visible:
                self.back_btn.grid_remove()
                self._back_btn_visible = False
        except Exception:
            log_exc()
    def _set_option_menu_value(self, widget, value, suppress_attr):
        try:
            setattr(self, suppress_attr, True)
            widget.set(value)
        except Exception:
            log_exc()
        finally:
            setattr(self, suppress_attr, False)
    def _smooth_line(self, values):
        try:
            arr = np.asarray(values, dtype=float)
            if arr.size < 3:
                return arr.tolist()
            kernel = np.array([0.25, 0.5, 0.25])
            smoothed = np.convolve(arr, kernel, mode="same")
            smoothed[0] = (arr[0] + arr[1]) / 2.0
            smoothed[-1] = (arr[-1] + arr[-2]) / 2.0
            return smoothed.tolist()
        except Exception:
            log_exc()
            return list(values)
    def _catmull_rom(self, x, y, samples=24):
        try:
            xp = np.asarray(x, dtype=float)
            yp = np.asarray(y, dtype=float)
            n = xp.size
            if n < 3:
                return xp, yp
            if samples < 4:
                samples = 4
            xp_ext = np.concatenate(([xp[0] - (xp[1] - xp[0])], xp, [xp[-1] + (xp[-1] - xp[-2])]))
            yp_ext = np.concatenate(([yp[0] - (yp[1] - yp[0])], yp, [yp[-1] + (yp[-1] - yp[-2])]))
            xs = []
            ys = []
            t_values = np.linspace(0, 1, samples, endpoint=False)
            for i in range(1, len(xp_ext) - 2):
                p0x, p0y = xp_ext[i-1], yp_ext[i-1]
                p1x, p1y = xp_ext[i], yp_ext[i]
                p2x, p2y = xp_ext[i+1], yp_ext[i+1]
                p3x, p3y = xp_ext[i+2], yp_ext[i+2]
                segment_min = min(p0y, p1y, p2y, p3y)
                segment_max = max(p0y, p1y, p2y, p3y)
                for t in t_values:
                    t2 = t * t
                    t3 = t2 * t
                    x_val = 0.5 * ((2 * p1x) + (-p0x + p2x) * t + (2*p0x - 5*p1x + 4*p2x - p3x) * t2 + (-p0x + 3*p1x - 3*p2x + p3x) * t3)
                    y_val = 0.5 * ((2 * p1y) + (-p0y + p2y) * t + (2*p0y - 5*p1y + 4*p2y - p3y) * t2 + (-p0y + 3*p1y - 3*p2y + p3y) * t3)
                    if segment_max >= segment_min:
                        y_val = min(max(y_val, segment_min), segment_max)
                    xs.append(x_val)
                    ys.append(y_val)
            xs.append(xp[-1])
            ys.append(yp[-1])
            return np.asarray(xs), np.asarray(ys)
        except Exception:
            log_exc()
            return np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    def _get_chart_bg_color(self):
        try:
            appearance = ctk.get_appearance_mode().lower()
            if appearance == 'dark':
                return '#2b2b2b'
            else:
                return '#dbdada'  
        except Exception:
            return '#dbdada'
    def _get_grid_color(self):
        try:
            appearance = ctk.get_appearance_mode().lower()
            if appearance == 'dark':
                return '#bbbbbb' 
            else:
                return '#666666' 
        except Exception:
            return '#666666'
    def _get_fg_color(self):
        try:
            appearance = ctk.get_appearance_mode().lower()
            return '#ffffff' if appearance == 'dark' else '#000000'
        except Exception:
            return '#000000'
    def _draw_screen_chart(self, fig, ax, canvas, period, chart_type="Bar", is_pinned=False):
        try:
            plt.style.use('seaborn-v0_8-darkgrid' if ctk.get_appearance_mode().lower() == 'dark' else 'seaborn-v0_8-whitegrid')
            fig.clear(); ax = fig.add_subplot(111)
            bg_color = self._get_chart_bg_color()
            fg_color = self._get_fg_color()
            grid_color = self._get_grid_color()
            fig.patch.set_facecolor(bg_color)
            ax.set_facecolor(bg_color)
            ax.tick_params(colors=fg_color)
            for spine in ax.spines.values():
                spine.set_color(fg_color)
            if cursor:
                cursor.execute("SELECT date, duration_sec FROM screen_time ORDER BY date")
                rows=cursor.fetchall()
            else: rows=[]
            data={d:m for d,m in rows}
            if not data and period != "Day":
                ax.text(0.5,0.5,"No data",ha="center", color=fg_color); canvas.draw(); return
            curr_start, curr_end, _, _ = self._compute_period_ranges(period, use_view_start=True)
            today = date.today()
            if period == "Day":
                target_day = curr_start
                today_str = target_day.isoformat()
                if cursor:
                    cursor.execute("SELECT date_hour, duration_sec FROM screen_hourly WHERE date_hour LIKE ?", (today_str + '%',))
                    rows_h = cursor.fetchall()
                else: rows_h = []
                hour_data = {int(r[0][-2:]): r[1] for r in rows_h}
                if target_day == today:
                    unsaved_visible = self._unsaved_visible_seconds()
                    if unsaved_visible > 0:
                        current_hour_idx = datetime.now().hour
                        hour_data[current_hour_idx] = hour_data.get(current_hour_idx, 0) + unsaved_visible
                keys = list(range(24))
                vals = [hour_data.get(h, 0) for h in keys]
                noise_threshold = 5 
                xtick_labels = [f"{h:02d}:00" for h in keys]
                labels = xtick_labels
            elif period == "Week":
                keys = []
                current_day = curr_start
                while current_day <= curr_end:
                    keys.append(current_day)
                    current_day += timedelta(days=1)
                vals = [data.get(k.isoformat(), 0) for k in keys]
                noise_threshold = 0
                xtick_labels = [k.strftime("%a") for k in keys]
                labels = [k.strftime("%A") for k in keys]
            elif period == "Month":
                week_agg = {}
                current = curr_start
                while current <= curr_end:
                    week_start = current - timedelta(days=current.weekday())
                    week_agg[week_start] = week_agg.get(week_start, 0)
                    week_agg[week_start] += data.get(current.isoformat(), 0)
                    current += timedelta(days=1)
                noise_threshold = 0
                keys = sorted(week_agg.keys())
                vals = [week_agg[k] for k in keys]
                xtick_labels = [f"Week of {k.strftime('%Y-%m-%d')}" for k in keys]
                labels = xtick_labels
            elif period == "Year":
                month_agg = {}
                for day_str, val in data.items():
                    try:
                        day_obj = date.fromisoformat(day_str)
                    except Exception:
                        continue
                    if curr_start <= day_obj <= curr_end:
                        month_start = day_obj.replace(day=1)
                        month_agg[month_start] = month_agg.get(month_start, 0) + val
                noise_threshold = 0
                keys = sorted(month_agg.keys())
                vals = [month_agg[k] for k in keys]
                xtick_labels = [k.strftime("%b %Y") for k in keys]
                labels = xtick_labels
            else:
                noise_threshold = 0
                keys = []
                vals = []
                xtick_labels = []
                labels = []
            if not keys:
                ax.text(0.5, 0.5, "No data", ha="center", color=fg_color)
                canvas.draw()
                return
            vals = [v if v >= noise_threshold else 0 for v in vals]
            raw_vals = [max(0, v) for v in vals]
            max_v = max(raw_vals or [0])
            if max_v > 3600:
                plot_vals = [v / 3600 for v in raw_vals]
                ylabel = "Hours"
                unit = "hours"
            elif max_v > 60:
                plot_vals = [v / 60 for v in raw_vals]
                ylabel = "Minutes"
                unit = "minutes"
            else:
                plot_vals = raw_vals[:]
                ylabel = "Minutes"
                unit = "minutes"
            combined = [(k, pv, lbl, rv) for k, pv, lbl, rv in zip(keys, plot_vals, xtick_labels, raw_vals) if rv > 0]
            if not combined:
                ax.text(0.5,0.5,"No data",ha="center", color=fg_color); canvas.draw(); return
            keys, plot_vals, xtick_labels, raw_vals = zip(*combined)
            plot_vals = list(plot_vals); raw_vals = list(raw_vals); keys = list(keys); xtick_labels = list(xtick_labels)
            n = len(plot_vals); idx = np.arange(n); width = 0.92 if n > 1 else 0.6
            max_val = max(plot_vals) if plot_vals else 0
            if max_val <= 0:
                upper = 1.0
                text_offset = 0.2
            else:
                headroom = max(max_val * 0.05, 0.5 if max_val < 5 else 0.0)
                upper = max_val + headroom
                text_offset = max(upper * 0.02, headroom * 0.3 if headroom else 0.2)
            elements = None
            if chart_type == "Line" or is_pinned:
                smooth_base = plot_vals
                if (chart_type == "Line" or is_pinned) and len(idx) >= 3:
                    dense_x, dense_y = self._catmull_rom(idx, smooth_base, samples=24 if chart_type == "Line" else 16)
                else:
                    dense_x, dense_y = np.asarray(idx, dtype=float), np.asarray(smooth_base, dtype=float)
                visible_line, = ax.plot(dense_x, dense_y, color=GRAPH_COLOR_SCREEN, marker=None)
                self._apply_line_style(visible_line, GRAPH_COLOR_SCREEN)
                alpha = 0.22 if chart_type == "Line" else 0.12
                ax.fill_between(dense_x, dense_y, color=GRAPH_COLOR_SCREEN, alpha=alpha)
                pick_line, = ax.plot(idx, plot_vals, marker='o', linestyle='None', alpha=0)
                pick_line.set_markersize(8)
                pick_line.set_pickradius(8)
                pick_line.set_picker(5)
                self._configure_pick_line(pick_line)
                self._create_line_markers(ax, idx, plot_vals, GRAPH_COLOR_SCREEN)
                elements = [pick_line]
            else:
                bars = ax.bar(idx, plot_vals, width=width, color=GRAPH_COLOR_SCREEN, edgecolor=fg_color)
                elements = bars
                self._apply_bar_palette(bars, GRAPH_COLOR_SCREEN)
                for bar, val, raw in zip(bars, plot_vals, raw_vals):
                    if val <= 0:
                        continue
                    text_y = min(val + text_offset, upper * 0.98)
                    ax.text(bar.get_x() + bar.get_width()/2, text_y, format_time_dynamic(int(raw)), ha='center', va='bottom', color=fg_color, fontsize=8, rotation=45 if n > 10 else 0)
            ax.set_xticks(idx)
            ax.set_xticklabels(xtick_labels, rotation=30, ha="right", fontsize=8)
            ax.set_ylabel(ylabel, color=fg_color); ax.set_title(f"Screen Time ({period})", color=fg_color, fontsize=10)
            ax.set_xlabel("Time", color=fg_color)
            ax.grid(True, axis='y', linestyle='--', alpha=0.5, color=grid_color)
            ax.set_ylim(0, upper)
            ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
            if n == 1: ax.set_xlim(-0.8, 0.8)
            else: ax.set_xlim(-0.5, n - 0.5)
            if not is_pinned:
                def hover_formatter(display_value, raw_value, label_text):
                    base = format_time_dynamic(int(raw_value))
                    if unit == "hours":
                        return f"{base}\n({display_value:.2f} h)"
                    elif unit == "minutes":
                        return f"{base}\n({display_value:.0f} min)"
                    return base
                self._add_hover(fig, ax, elements, plot_vals, unit, canvas, xtick_labels, max_val if max_val > 0 else 1,
                                raw_vals=raw_vals, formatter=hover_formatter)
            fig.tight_layout(); canvas.draw()
        except Exception:
            log_exc()
    def _draw_posture_alerts_chart(self, fig, ax, canvas, period, chart_type="Bar", is_pinned=False):
        try:
            plt.style.use('seaborn-v0_8-darkgrid' if ctk.get_appearance_mode().lower() == 'dark' else 'seaborn-v0_8-whitegrid')
            fig.clear(); ax = fig.add_subplot(111)
            bg_color = self._get_chart_bg_color()
            fg_color = self._get_fg_color()
            grid_color = self._get_grid_color()
            fig.patch.set_facecolor(bg_color)
            ax.set_facecolor(bg_color)
            ax.tick_params(colors=fg_color)
            for spine in ax.spines.values():
                spine.set_color(fg_color)
            if cursor:
                cursor.execute("SELECT timestamp, message FROM alerts ORDER BY timestamp")
                rows=cursor.fetchall()
            else: rows=[]
            posture_alerts = [r for r in rows if "Bad Posture" in r[1]]
            if not posture_alerts:
                ax.text(0.5,0.5,"No data",ha="center", color=fg_color); canvas.draw(); return
            curr_start, curr_end, _, _ = self._compute_period_ranges(period, use_view_start=True)
            today = date.today()
            if period == "Day":
                target_day = curr_start
                day_str = target_day.isoformat()
                filtered = [r for r in posture_alerts if r[0].startswith(day_str)]
                hour_counts = Counter(int(r[0][11:13]) for r in filtered)
                keys = list(range(24))
                vals = [hour_counts.get(h, 0) for h in keys]
                xtick_labels = [f"{h:02d}:00" for h in keys]
                labels = xtick_labels
                ylabel = "Count"
                unit = ""
                title = f"Posture Alerts ({period})"
            elif period == "Week":
                filtered = [r for r in posture_alerts if curr_start.isoformat() <= r[0][:10] <= curr_end.isoformat()]
                day_counts = Counter(r[0][:10] for r in filtered)
                keys = []
                current_day = curr_start
                while current_day <= curr_end:
                    keys.append(current_day)
                    current_day += timedelta(days=1)
                vals = [day_counts.get(k.isoformat(), 0) for k in keys]
                xtick_labels = [k.strftime("%a") for k in keys]
                labels = [k.strftime("%A") for k in keys]
                ylabel = "Count"
                unit = ""
                title = f"Posture Alerts ({period})"
            elif period == "Month":
                filtered = [r for r in posture_alerts if curr_start.isoformat() <= r[0][:10] <= curr_end.isoformat()]
                week_counts = {}
                for ts, _ in filtered:
                    d = date.fromisoformat(ts[:10])
                    week_start = d - timedelta(days=d.weekday())
                    week_counts[week_start] = week_counts.get(week_start, 0) + 1
                keys = sorted(week_counts.keys())
                vals = [week_counts[k] for k in keys]
                xtick_labels = [f"Week of {k.strftime('%Y-%m-%d')}" for k in keys]
                labels = xtick_labels
                ylabel = "Count"
                unit = ""
                title = f"Posture Alerts ({period})"
            elif period == "Year":
                filtered = [r for r in posture_alerts if curr_start.isoformat() <= r[0][:10] <= curr_end.isoformat()]
                month_counts = {}
                for ts, _ in filtered:
                    d = date.fromisoformat(ts[:10])
                    month_start = d.replace(day=1)
                    month_counts[month_start] = month_counts.get(month_start, 0) + 1
                keys = sorted(month_counts.keys())
                vals = [month_counts[k] for k in keys]
                xtick_labels = [k.strftime("%b %Y") for k in keys]
                labels = xtick_labels
                ylabel = "Count"
                unit = ""
                title = f"Posture Alerts ({period})"
            raw_vals = [max(0, v) for v in vals]
            combined = [(k, rv, lbl) for k, rv, lbl in zip(keys, raw_vals, xtick_labels) if rv > 0]
            if not combined:
                ax.text(0.5,0.5,"No data",ha="center", color=fg_color); canvas.draw(); return
            keys, raw_vals, xtick_labels = zip(*combined)
            keys = list(keys); raw_vals = list(raw_vals); xtick_labels = list(xtick_labels)
            plot_vals = raw_vals[:]
            n = len(plot_vals); idx = np.arange(n); width = 0.92 if n > 1 else 0.6
            max_val = max(plot_vals) if plot_vals else 0
            if max_val <= 0:
                upper = 1.0
                text_offset = 0.2
            else:
                headroom = max(max_val * 0.05, 0.5 if max_val < 5 else 0.0)
                upper = max_val + headroom
                text_offset = max(upper * 0.02, headroom * 0.3 if headroom else 0.2)
            elements = None
            if chart_type == "Line" or is_pinned:
                smooth_base = plot_vals
                if (chart_type == "Line" or is_pinned) and len(idx) >= 3:
                    dense_x, dense_y = self._catmull_rom(idx, smooth_base, samples=24 if chart_type == "Line" else 16)
                else:
                    dense_x, dense_y = np.asarray(idx, dtype=float), np.asarray(smooth_base, dtype=float)
                visible_line, = ax.plot(dense_x, dense_y, color=GRAPH_COLOR_POSTURE, marker=None)
                self._apply_line_style(visible_line, GRAPH_COLOR_POSTURE)
                alpha = 0.22 if chart_type == "Line" else 0.12
                ax.fill_between(dense_x, dense_y, color=GRAPH_COLOR_POSTURE, alpha=alpha)
                pick_line, = ax.plot(idx, plot_vals, marker='o', linestyle='None', alpha=0)
                pick_line.set_markersize(8)
                pick_line.set_pickradius(8)
                pick_line.set_picker(5)
                self._configure_pick_line(pick_line)
                self._create_line_markers(ax, idx, plot_vals, GRAPH_COLOR_POSTURE)
                elements = [pick_line]
            else:
                bars = ax.bar(idx, plot_vals, width=width, color=GRAPH_COLOR_POSTURE, edgecolor=fg_color)
                elements = bars
                self._apply_bar_palette(bars, GRAPH_COLOR_POSTURE)
                for bar, val in zip(bars, plot_vals):
                    if val <= 0:
                        continue
                    text_y = min(val + text_offset, upper * 0.98)
                    ax.text(bar.get_x() + bar.get_width()/2, text_y, f"{int(round(val))}", ha='center', va='bottom', color=fg_color, fontsize=8, rotation=45 if n > 10 else 0)
            ax.set_xticks(idx)
            ax.set_xticklabels(xtick_labels, rotation=30, ha="right", fontsize=8)
            ax.set_ylabel(ylabel, color=fg_color); ax.set_title(title, color=fg_color, fontsize=10)
            ax.set_xlabel("Time", color=fg_color)
            ax.grid(True, axis='y', linestyle='--', alpha=0.5, color=grid_color)
            ax.set_ylim(0, upper)
            ax.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
            if n == 1: ax.set_xlim(-0.8, 0.8)
            else: ax.set_xlim(-0.5, n - 0.5)
            if not is_pinned:
                self._add_hover(
                    fig,
                    ax,
                    elements,
                    plot_vals,
                    unit,
                    canvas,
                    xtick_labels,
                    max_val if max_val > 0 else 1,
                    raw_vals=raw_vals,
                    formatter=lambda disp, raw, label: f"{int(round(raw))} alerts"
                )
            fig.tight_layout(); canvas.draw()
        except Exception:
            log_exc()
    def _draw_distance_chart(self, fig, ax, canvas, period, chart_type="Bar", is_pinned=False):
        try:
            plt.style.use('seaborn-v0_8-darkgrid' if ctk.get_appearance_mode().lower() == 'dark' else 'seaborn-v0_8-whitegrid')
            fig.clear(); ax = fig.add_subplot(111)
            bg_color = self._get_chart_bg_color()
            fg_color = self._get_fg_color()
            grid_color = self._get_grid_color()
            fig.patch.set_facecolor(bg_color)
            ax.set_facecolor(bg_color)
            ax.tick_params(colors=fg_color)
            for spine in ax.spines.values():
                spine.set_color(fg_color)
            if cursor:
                cursor.execute("SELECT date, avg_distance_cm, count FROM distance_log ORDER BY date")
                rows=cursor.fetchall()
            else: rows=[]
            data={r[0]: (r[1], r[2]) for r in rows}
            if not data and period != "Day":
                ax.text(0.5,0.5,"No data",ha="center", color=fg_color); canvas.draw(); return
            today = date.today()
            start, end = None, None
            if self.current_view_start:
                if period == "Week":
                    start = self.current_view_start
                    end = start + timedelta(days=6)
                elif period == "Day":
                    start = self.current_view_start
                    end = start
            if period == "Day":
                if start is None:
                    start = today
                today_str = start.isoformat()
                if cursor:
                    cursor.execute("SELECT date_hour, sum_distance_cm, count FROM distance_hourly WHERE date_hour LIKE ?", (today_str + '%',))
                    rows_h = cursor.fetchall()
                else: rows_h = []
                hour_data = {int(r[0][-2:]): [r[1] if r[1] is not None else 0.0, r[2] if r[2] is not None else 0] for r in rows_h}
                if start == date.today():
                    extra_sum = self.pending_hour_distance_sum
                    extra_count = self.pending_hour_distance_count
                    if extra_count > 0:
                        current_hour_idx = datetime.now().hour
                        pair = hour_data.get(current_hour_idx, [0.0, 0])
                        pair[0] += extra_sum
                        pair[1] += extra_count
                        hour_data[current_hour_idx] = pair
                keys = list(range(24))
                vals = []
                for h in keys:
                    sum_val, count_val = hour_data.get(h, [0.0, 0])
                    vals.append((sum_val / count_val) if count_val > 0 else 0)
                xtick_labels = [f"{h:02d}:00" for h in keys]
                labels = xtick_labels
            elif period == "Week":
                if start is None:
                    start = today - timedelta(days=6)
                keys = [start + timedelta(days=i) for i in range(7)]
                vals = [data.get(k.isoformat(), (0.0, 0))[0] for k in keys]
                xtick_labels = [k.strftime("%a") for k in keys]
                labels = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            elif period == "Month":
                if start is None:
                    start = today.replace(day=1)
                end_curr = (start + timedelta(days=31)).replace(day=1) - timedelta(days=1)
                total_sum = 0.0
                total_count = 0
                for k in data:
                    if start.isoformat() <= k <= end_curr.isoformat():
                        avg, cnt = data[k]
                        total_sum += avg * cnt if cnt is not None else 0
                        total_count += cnt if cnt is not None else 0
                keys = [start]
                vals = [total_sum / total_count if total_count > 0 else 0.0]
                xtick_labels = ["This Month"]
                labels = xtick_labels
            elif period == "Year":
                start = today.replace(month=1, day=1)
                end_curr = today.replace(month=12, day=31)
                total_sum = 0.0
                total_count = 0
                for k in data:
                    if start.isoformat() <= k <= end_curr.isoformat():
                        avg, cnt = data[k]
                        total_sum += avg * cnt if cnt is not None else 0
                        total_count += cnt if cnt is not None else 0
                keys = [start]
                vals = [total_sum / total_count if total_count > 0 else 0.0]
                xtick_labels = ["This Year"]
                labels = xtick_labels
            raw_vals = [float(v) for v in vals]
            non_zero = [(k, rv, lbl) for k, rv, lbl in zip(keys, raw_vals, xtick_labels) if rv > 0]
            if not non_zero:
                ax.text(0.5,0.5,"No data",ha="center", color=fg_color); canvas.draw(); return
            keys, raw_vals, xtick_labels = zip(*non_zero)
            keys = list(keys); raw_vals = list(raw_vals); xtick_labels = list(xtick_labels)
            if self.unit == "in":
                plot_vals = [rv / 2.54 for rv in raw_vals]
                display_unit = "in"
            else:
                plot_vals = raw_vals[:]
                display_unit = "cm"
            ylabel = f"Average Distance ({display_unit})"
            n=len(plot_vals); idx=np.arange(n); width=0.92 if n>1 else 0.6
            max_val = max(plot_vals) if plot_vals else 0
            if max_val <= 0:
                upper = 1.0
                text_offset = 0.2
            else:
                headroom = max(max_val * 0.05, 0.5 if max_val < 5 else 0.0)
                upper = max_val + headroom
                text_offset = max(upper * 0.02, headroom * 0.3 if headroom else 0.2)
            elements = None
            if chart_type == "Line" or is_pinned:
                smooth_base = plot_vals
                if (chart_type == "Line" or is_pinned) and len(idx) >= 3:
                    dense_x, dense_y = self._catmull_rom(idx, smooth_base, samples=24 if chart_type == "Line" else 16)
                else:
                    dense_x, dense_y = np.asarray(idx, dtype=float), np.asarray(smooth_base, dtype=float)
                visible_line, = ax.plot(dense_x, dense_y, color=GRAPH_COLOR_DISTANCE, marker=None)
                self._apply_line_style(visible_line, GRAPH_COLOR_DISTANCE)
                alpha = 0.22 if chart_type == "Line" else 0.12
                ax.fill_between(dense_x, dense_y, color=GRAPH_COLOR_DISTANCE, alpha=alpha)
                pick_line, = ax.plot(idx, plot_vals, marker='o', linestyle='None', alpha=0)
                pick_line.set_markersize(8)
                pick_line.set_pickradius(8)
                pick_line.set_picker(5)
                self._configure_pick_line(pick_line)
                self._create_line_markers(ax, idx, plot_vals, GRAPH_COLOR_DISTANCE)
                elements = [pick_line]
            else:
                bars = ax.bar(idx, plot_vals, width=width, color=GRAPH_COLOR_DISTANCE, edgecolor=fg_color)
                elements = bars
                self._apply_bar_palette(bars, GRAPH_COLOR_DISTANCE)
                for bar, val in zip(bars, plot_vals):
                    if val <= 0:
                        continue
                    text_y = min(val + text_offset, upper * 0.98)
                    ax.text(bar.get_x() + bar.get_width()/2, text_y, f"{val:.1f}", ha='center', va='bottom', color=fg_color, fontsize=8, rotation=45 if n > 10 else 0)
            ax.set_xticks(idx)
            ax.set_xticklabels(xtick_labels, rotation=30, ha="right", fontsize=8)
            ax.set_ylabel(ylabel, color=fg_color); ax.set_title(f"Average Screen Distance ({period})", color=fg_color, fontsize=10)
            ax.set_xlabel("Time", color=fg_color)
            ax.grid(True, axis='y', linestyle='--', alpha=0.5, color=grid_color)
            ax.set_ylim(0, upper)
            ax.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
            if n == 1: ax.set_xlim(-0.8, 0.8)
            else: ax.set_xlim(-0.5, n - 0.5)
            if not is_pinned:
                def hover_formatter(display_value, raw_value, label_text):
                    cm_text = f"{raw_value:.1f} cm"
                    in_text = f"{raw_value / 2.54:.1f} in"
                    if display_unit == "in":
                        return f"{display_value:.1f} in\n({cm_text})"
                    return f"{cm_text}\n({in_text})"
                self._add_hover(fig, ax, elements, plot_vals, display_unit, canvas, xtick_labels, max_val if max_val > 0 else 1, raw_vals=raw_vals, formatter=hover_formatter)
            fig.tight_layout(); canvas.draw()
        except Exception:
            log_exc()
    def _draw_distance_notifications_chart(self, fig, ax, canvas, period, chart_type="Bar", is_pinned=False):
        try:
            plt.style.use('seaborn-v0_8-darkgrid' if ctk.get_appearance_mode().lower() == 'dark' else 'seaborn-v0_8-whitegrid')
            fig.clear(); ax = fig.add_subplot(111)
            bg_color = self._get_chart_bg_color()
            fg_color = self._get_fg_color()
            grid_color = self._get_grid_color()
            fig.patch.set_facecolor(bg_color)
            ax.set_facecolor(bg_color)
            ax.tick_params(colors=fg_color)
            for spine in ax.spines.values():
                spine.set_color(fg_color)
            if cursor:
                cursor.execute("SELECT timestamp, message FROM alerts ORDER BY timestamp")
                rows=cursor.fetchall()
            else: rows=[]
            distance_alerts = [r for r in rows if "Distance" in r[1]]
            if not distance_alerts:
                ax.text(0.5,0.5,"No data",ha="center", color=fg_color); canvas.draw(); return
            today = date.today()
            start, end = None, None
            if self.current_view_start:
                if period == "Week":
                    start = self.current_view_start
                    end = start + timedelta(days=6)
                elif period == "Day":
                    start = self.current_view_start
                    end = start
            if period == "Day":
                if start is None:
                    start = today
                today_str = start.isoformat()
                filtered = [r for r in distance_alerts if r[0].startswith(today_str)]
                hour_counts = Counter(int(r[0][11:13]) for r in filtered)
                keys = list(range(24))
                vals = [hour_counts.get(h, 0) for h in keys]
                xtick_labels = [f"{h:02d}:00" for h in keys]
                labels = xtick_labels
            elif period == "Week":
                if start is None:
                    start = today - timedelta(days=6)
                end = start + timedelta(days=6)
                filtered = [r for r in distance_alerts if start.isoformat() <= r[0][:10] <= end.isoformat()]
                day_counts = Counter(r[0][:10] for r in filtered)
                keys = [start + timedelta(days=i) for i in range(7)]
                vals = [day_counts.get(k.isoformat(), 0) for k in keys]
                xtick_labels = [k.strftime("%a") for k in keys]
                labels = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            elif period == "Month":
                if start is None:
                    start = today.replace(day=1)
                end = (start + timedelta(days=31)).replace(day=1) - timedelta(days=1)
                filtered = [r for r in distance_alerts if start.isoformat() <= r[0][:10] <= end.isoformat()]
                week_counts = {}
                for ts, _ in filtered:
                    d = date.fromisoformat(ts[:10])
                    week_start = d - timedelta(days=d.weekday())
                    week_counts[week_start] = week_counts.get(week_start, 0) + 1
                keys = sorted(week_counts.keys())
                vals = [week_counts[k] for k in keys]
                xtick_labels = [f"Week of {k.strftime('%Y-%m-%d')}" for k in keys]
                labels = xtick_labels
            elif period == "Year":
                start = today.replace(month=1, day=1)
                end = today.replace(month=12, day=31)
                filtered = [r for r in distance_alerts if start.isoformat() <= r[0][:10] <= end.isoformat()]
                month_counts = {}
                for ts, _ in filtered:
                    d = date.fromisoformat(ts[:10])
                    month_start = d.replace(day=1)
                    month_counts[month_start] = month_counts.get(month_start, 0) + 1
                keys = sorted(month_counts.keys())
                vals = [month_counts[k] for k in keys]
                xtick_labels = [k.strftime("%b %Y") for k in keys]
                labels = xtick_labels
            non_zero = [(k, v, l) for k, v, l in zip(keys, vals, xtick_labels) if v > 0]
            if not non_zero:
                ax.text(0.5,0.5,"No data",ha="center", color=fg_color); canvas.draw(); return
            keys, vals, xtick_labels = zip(*non_zero)
            keys = list(keys); vals = [int(v) for v in vals]; xtick_labels = list(xtick_labels)
            plot_vals = vals[:]
            n = len(plot_vals); idx = np.arange(n); width = 0.92 if n > 1 else 0.6
            max_val = max(plot_vals) if plot_vals else 0
            if max_val <= 0:
                upper = 1.0
                text_offset = 0.2
            else:
                headroom = max(max_val * 0.05, 0.5 if max_val < 5 else 0.0)
                upper = max_val + headroom
                text_offset = max(upper * 0.02, headroom * 0.3 if headroom else 0.2)
            elements = None
            if chart_type == "Line" or is_pinned:
                smooth_base = plot_vals
                if (chart_type == "Line" or is_pinned) and len(idx) >= 3:
                    dense_x, dense_y = self._catmull_rom(idx, smooth_base, samples=24 if chart_type == "Line" else 16)
                else:
                    dense_x, dense_y = np.asarray(idx, dtype=float), np.asarray(smooth_base, dtype=float)
                visible_line, = ax.plot(dense_x, dense_y, color=GRAPH_COLOR_ALERTS, marker=None)
                self._apply_line_style(visible_line, GRAPH_COLOR_ALERTS)
                alpha = 0.22 if chart_type == "Line" else 0.12
                ax.fill_between(dense_x, dense_y, color=GRAPH_COLOR_ALERTS, alpha=alpha)
                pick_line, = ax.plot(idx, plot_vals, marker='o', linestyle='None', alpha=0)
                pick_line.set_markersize(8)
                pick_line.set_pickradius(8)
                pick_line.set_picker(5)
                self._configure_pick_line(pick_line)
                self._create_line_markers(ax, idx, plot_vals, GRAPH_COLOR_ALERTS)
                elements = [pick_line]
            else:
                bars = ax.bar(idx, plot_vals, width=width, color=GRAPH_COLOR_ALERTS, edgecolor=fg_color)
                elements = bars
                self._apply_bar_palette(bars, GRAPH_COLOR_ALERTS)
                for bar, val in zip(bars, plot_vals):
                    if val <= 0:
                        continue
                    text_y = min(val + text_offset, upper * 0.98)
                    ax.text(bar.get_x() + bar.get_width()/2, text_y, f"{int(round(val))}", ha='center', va='bottom', color=fg_color, fontsize=8, rotation=45 if n > 10 else 0)
            ax.set_xticks(idx)
            ax.set_xticklabels(xtick_labels, rotation=30, ha="right", fontsize=8)
            ax.set_ylabel("Count", color=fg_color); ax.set_title(f"Distance Alerts ({period})", color=fg_color, fontsize=10)
            ax.set_xlabel("Time", color=fg_color)
            ax.grid(True, axis='y', linestyle='--', alpha=0.5, color=grid_color)
            ax.set_ylim(0, upper)
            ax.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
            if n == 1: ax.set_xlim(-0.8, 0.8)
            else: ax.set_xlim(-0.5, n - 0.5)
            if not is_pinned:
                self._add_hover(fig, ax, elements, plot_vals, "", canvas, xtick_labels, max_val if max_val > 0 else 1, raw_vals=plot_vals, formatter=lambda disp, raw, label: f"{int(round(raw))} alerts")
            fig.tight_layout(); canvas.draw()
        except Exception:
            log_exc()
    def _draw_nail_biting_chart(self, fig, ax, canvas, period, chart_type="Bar", is_pinned=False):
        try:
            plt.style.use('seaborn-v0_8-darkgrid' if ctk.get_appearance_mode().lower() == 'dark' else 'seaborn-v0_8-whitegrid')
            fig.clear(); ax = fig.add_subplot(111)
            bg_color = self._get_chart_bg_color()
            fg_color = self._get_fg_color()
            grid_color = self._get_grid_color()
            fig.patch.set_facecolor(bg_color)
            ax.set_facecolor(bg_color)
            ax.tick_params(colors=fg_color)
            for spine in ax.spines.values():
                spine.set_color(fg_color)
            if cursor:
                cursor.execute("SELECT timestamp, message FROM alerts ORDER BY timestamp")
                rows = cursor.fetchall()
            else:
                rows = []
            nail_alerts = [r for r in rows if "Nail Biting" in r[1]]
            if not nail_alerts:
                ax.text(0.5,0.5,"No data",ha="center", color=fg_color); canvas.draw(); return
            today = date.today()
            start, end = None, None
            if self.current_view_start:
                if period == "Week":
                    start = self.current_view_start
                    end = start + timedelta(days=6)
                elif period == "Day":
                    start = self.current_view_start
                    end = start
            if period == "Day":
                if start is None:
                    start = today
                today_str = start.isoformat()
                filtered = [r for r in nail_alerts if r[0].startswith(today_str)]
                hour_counts = Counter(int(r[0][11:13]) for r in filtered)
                keys = list(range(24))
                vals = [hour_counts.get(h, 0) for h in keys]
                xtick_labels = [f"{h:02d}:00" for h in keys]
                labels = xtick_labels
            elif period == "Week":
                if start is None:
                    start = today - timedelta(days=6)
                end = start + timedelta(days=6)
                filtered = [r for r in nail_alerts if start.isoformat() <= r[0][:10] <= end.isoformat()]
                day_counts = Counter(r[0][:10] for r in filtered)
                keys = [start + timedelta(days=i) for i in range(7)]
                vals = [day_counts.get(k.isoformat(), 0) for k in keys]
                xtick_labels = [k.strftime("%a") for k in keys]
                labels = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            elif period == "Month":
                if start is None:
                    start = today.replace(day=1)
                end = (start + timedelta(days=31)).replace(day=1) - timedelta(days=1)
                filtered = [r for r in nail_alerts if start.isoformat() <= r[0][:10] <= end.isoformat()]
                week_counts = {}
                for ts, _ in filtered:
                    d = date.fromisoformat(ts[:10])
                    week_start = d - timedelta(days=d.weekday())
                    week_counts[week_start] = week_counts.get(week_start, 0) + 1
                keys = sorted(week_counts.keys())
                vals = [week_counts[k] for k in keys]
                xtick_labels = [f"Week of {k.strftime('%Y-%m-%d')}" for k in keys]
                labels = xtick_labels
            elif period == "Year":
                start = today.replace(month=1, day=1)
                end = today.replace(month=12, day=31)
                filtered = [r for r in nail_alerts if start.isoformat() <= r[0][:10] <= end.isoformat()]
                month_counts = {}
                for ts, _ in filtered:
                    d = date.fromisoformat(ts[:10])
                    month_start = d.replace(day=1)
                    month_counts[month_start] = month_counts.get(month_start, 0) + 1
                keys = sorted(month_counts.keys())
                vals = [month_counts[k] for k in keys]
                xtick_labels = [k.strftime("%b %Y") for k in keys]
                labels = xtick_labels
            else:
                keys = []
                vals = []
                xtick_labels = []
                labels = []
            non_zero = [(k, v, l) for k, v, l in zip(keys, vals, xtick_labels) if v > 0]
            if not non_zero:
                ax.text(0.5,0.5,"No data",ha="center", color=fg_color); canvas.draw(); return
            keys, vals, xtick_labels = zip(*non_zero)
            keys = list(keys); vals = [int(v) for v in vals]; xtick_labels = list(xtick_labels)
            plot_vals = vals[:]
            n = len(plot_vals); idx = np.arange(n); width = 0.92 if n > 1 else 0.6
            max_val = max(plot_vals) if plot_vals else 0
            if max_val <= 0:
                upper = 1.0
                text_offset = 0.2
            else:
                headroom = max(max_val * 0.05, 0.5 if max_val < 5 else 0.0)
                upper = max_val + headroom
                text_offset = max(upper * 0.02, headroom * 0.3 if headroom else 0.2)
            elements = None
            if chart_type == "Line" or is_pinned:
                smooth_base = plot_vals
                if (chart_type == "Line" or is_pinned) and len(idx) >= 3:
                    dense_x, dense_y = self._catmull_rom(idx, smooth_base, samples=24 if chart_type == "Line" else 16)
                else:
                    dense_x, dense_y = np.asarray(idx, dtype=float), np.asarray(smooth_base, dtype=float)
                visible_line, = ax.plot(dense_x, dense_y, color=GRAPH_COLOR_NAIL, marker=None)
                self._apply_line_style(visible_line, GRAPH_COLOR_NAIL)
                alpha = 0.22 if chart_type == "Line" else 0.12
                ax.fill_between(dense_x, dense_y, color=GRAPH_COLOR_NAIL, alpha=alpha)
                pick_line, = ax.plot(idx, plot_vals, marker='o', linestyle='None', alpha=0)
                pick_line.set_markersize(8)
                pick_line.set_pickradius(8)
                pick_line.set_picker(5)
                self._configure_pick_line(pick_line)
                self._create_line_markers(ax, idx, plot_vals, GRAPH_COLOR_NAIL)
                elements = [pick_line]
            else:
                bars = ax.bar(idx, plot_vals, width=width, color=GRAPH_COLOR_NAIL, edgecolor=fg_color)
                elements = bars
                self._apply_bar_palette(bars, GRAPH_COLOR_NAIL)
                for bar, val in zip(bars, plot_vals):
                    if val <= 0:
                        continue
                    text_y = min(val + text_offset, upper * 0.98)
                    ax.text(bar.get_x() + bar.get_width()/2, text_y, f"{int(round(val))}", ha='center', va='bottom', color=fg_color, fontsize=8, rotation=45 if n > 10 else 0)
            ax.set_xticks(idx)
            ax.set_xticklabels(xtick_labels, rotation=30, ha="right", fontsize=8)
            ax.set_ylabel("Count", color=fg_color); ax.set_title(f"Nail Biting Alerts ({period})", color=fg_color, fontsize=10)
            ax.set_xlabel("Time", color=fg_color)
            ax.grid(True, axis='y', linestyle='--', alpha=0.5, color=grid_color)
            ax.set_ylim(0, upper)
            ax.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
            if n == 1:
                ax.set_xlim(-0.8, 0.8)
            else:
                ax.set_xlim(-0.5, n - 0.5)
            if not is_pinned:
                self._add_hover(fig, ax, elements, plot_vals, "", canvas, xtick_labels, max_val if max_val > 0 else 1, raw_vals=plot_vals, formatter=lambda disp, raw, label: f"{int(round(raw))} alerts")
            fig.tight_layout(); canvas.draw()
        except Exception:
            log_exc()
    def _draw_face_touch_chart(self, fig, ax, canvas, period, chart_type="Bar", is_pinned=False):
        try:
            plt.style.use('seaborn-v0_8-darkgrid' if ctk.get_appearance_mode().lower() == 'dark' else 'seaborn-v0_8-whitegrid')
            fig.clear(); ax = fig.add_subplot(111)
            bg_color = self._get_chart_bg_color()
            fg_color = self._get_fg_color()
            grid_color = self._get_grid_color()
            fig.patch.set_facecolor(bg_color)
            ax.set_facecolor(bg_color)
            ax.tick_params(colors=fg_color)
            for spine in ax.spines.values():
                spine.set_color(fg_color)
            if cursor:
                cursor.execute("SELECT timestamp, message FROM alerts ORDER BY timestamp")
                rows = cursor.fetchall()
            else:
                rows = []
            face_alerts = [r for r in rows if "Face Touch" in r[1]]
            if not face_alerts:
                ax.text(0.5,0.5,"No data",ha="center", color=fg_color); canvas.draw(); return
            today = date.today()
            start, end = None, None
            if self.current_view_start:
                if period == "Week":
                    start = self.current_view_start
                    end = start + timedelta(days=6)
                elif period == "Day":
                    start = self.current_view_start
                    end = start
            if period == "Day":
                if start is None:
                    start = today
                today_str = start.isoformat()
                filtered = [r for r in face_alerts if r[0].startswith(today_str)]
                hour_counts = Counter(int(r[0][11:13]) for r in filtered)
                keys = list(range(24))
                vals = [hour_counts.get(h, 0) for h in keys]
                xtick_labels = [f"{h:02d}:00" for h in keys]
                labels = xtick_labels
            elif period == "Week":
                if start is None:
                    start = today - timedelta(days=6)
                end = start + timedelta(days=6)
                filtered = [r for r in face_alerts if start.isoformat() <= r[0][:10] <= end.isoformat()]
                day_counts = Counter(r[0][:10] for r in filtered)
                keys = [start + timedelta(days=i) for i in range(7)]
                vals = [day_counts.get(k.isoformat(), 0) for k in keys]
                xtick_labels = [k.strftime("%a") for k in keys]
                labels = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            elif period == "Month":
                if start is None:
                    start = today.replace(day=1)
                end = (start + timedelta(days=31)).replace(day=1) - timedelta(days=1)
                filtered = [r for r in face_alerts if start.isoformat() <= r[0][:10] <= end.isoformat()]
                week_counts = {}
                for ts, _ in filtered:
                    d = date.fromisoformat(ts[:10])
                    week_start = d - timedelta(days=d.weekday())
                    week_counts[week_start] = week_counts.get(week_start, 0) + 1
                keys = sorted(week_counts.keys())
                vals = [week_counts[k] for k in keys]
                xtick_labels = [f"Week of {k.strftime('%Y-%m-%d')}" for k in keys]
                labels = xtick_labels
            elif period == "Year":
                start = today.replace(month=1, day=1)
                end = today.replace(month=12, day=31)
                filtered = [r for r in face_alerts if start.isoformat() <= r[0][:10] <= end.isoformat()]
                month_counts = {}
                for ts, _ in filtered:
                    d = date.fromisoformat(ts[:10])
                    month_start = d.replace(day=1)
                    month_counts[month_start] = month_counts.get(month_start, 0) + 1
                keys = sorted(month_counts.keys())
                vals = [month_counts[k] for k in keys]
                xtick_labels = [k.strftime("%b %Y") for k in keys]
                labels = xtick_labels
            else:
                keys = []
                vals = []
                xtick_labels = []
                labels = []
            non_zero = [(k, v, l) for k, v, l in zip(keys, vals, xtick_labels) if v > 0]
            if not non_zero:
                ax.text(0.5,0.5,"No data",ha="center", color=fg_color); canvas.draw(); return
            keys, vals, xtick_labels = zip(*non_zero)
            keys = list(keys); vals = [int(v) for v in vals]; xtick_labels = list(xtick_labels)
            plot_vals = vals[:]
            n = len(plot_vals); idx = np.arange(n); width = 0.92 if n > 1 else 0.6
            max_val = max(plot_vals) if plot_vals else 0
            if max_val <= 0:
                upper = 1.0
                text_offset = 0.2
            else:
                headroom = max(max_val * 0.05, 0.5 if max_val < 5 else 0.0)
                upper = max_val + headroom
                text_offset = max(upper * 0.02, headroom * 0.3 if headroom else 0.2)
            elements = None
            if chart_type == "Line" or is_pinned:
                smooth_base = plot_vals
                if (chart_type == "Line" or is_pinned) and len(idx) >= 3:
                    dense_x, dense_y = self._catmull_rom(idx, smooth_base, samples=24 if chart_type == "Line" else 16)
                else:
                    dense_x, dense_y = np.asarray(idx, dtype=float), np.asarray(smooth_base, dtype=float)
                visible_line, = ax.plot(dense_x, dense_y, color=GRAPH_COLOR_FACE, marker=None)
                self._apply_line_style(visible_line, GRAPH_COLOR_FACE)
                alpha = 0.22 if chart_type == "Line" else 0.12
                ax.fill_between(dense_x, dense_y, color=GRAPH_COLOR_FACE, alpha=alpha)
                pick_line, = ax.plot(idx, plot_vals, marker='o', linestyle='None', alpha=0)
                pick_line.set_markersize(8)
                pick_line.set_pickradius(8)
                pick_line.set_picker(5)
                self._configure_pick_line(pick_line)
                self._create_line_markers(ax, idx, plot_vals, GRAPH_COLOR_FACE)
                elements = [pick_line]
            else:
                bars = ax.bar(idx, plot_vals, width=width, color=GRAPH_COLOR_FACE, edgecolor=fg_color)
                elements = bars
                self._apply_bar_palette(bars, GRAPH_COLOR_FACE)
                for bar, val in zip(bars, plot_vals):
                    if val <= 0:
                        continue
                    text_y = min(val + text_offset, upper * 0.98)
                    ax.text(bar.get_x() + bar.get_width()/2, text_y, f"{int(round(val))}", ha='center', va='bottom', color=fg_color, fontsize=8, rotation=45 if n > 10 else 0)
            ax.set_xticks(idx)
            ax.set_xticklabels(xtick_labels, rotation=30, ha="right", fontsize=8)
            ax.set_ylabel("Count", color=fg_color); ax.set_title(f"Face Touch Alerts ({period})", color=fg_color, fontsize=10)
            ax.set_xlabel("Time", color=fg_color)
            ax.grid(True, axis='y', linestyle='--', alpha=0.5, color=grid_color)
            ax.set_ylim(0, upper)
            ax.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
            if n == 1:
                ax.set_xlim(-0.8, 0.8)
            else:
                ax.set_xlim(-0.5, n - 0.5)
            if not is_pinned:
                self._add_hover(fig, ax, elements, plot_vals, "", canvas, xtick_labels, max_val if max_val > 0 else 1, raw_vals=plot_vals, formatter=lambda disp, raw, label: f"{int(round(raw))} alerts")
            fig.tight_layout(); canvas.draw()
        except Exception:
            log_exc()
    def _apply_bar_palette(self, bars, base_color):
        try:
            bar_list = list(bars) if bars is not None else []
            if not bar_list:
                return
            base_rgb = np.array(to_rgb(base_color))
            white = np.ones(3)
            total = len(bar_list)
            for idx, bar in enumerate(bar_list):
                blend = 0.25 + 0.45 * (idx / max(total - 1, 1))
                color_rgb = base_rgb * (1 - blend) + white * blend
                bar.set_picker(True)
                bar.set_facecolor((0, 0, 0, 0))
                bar.set_edgecolor("none")
                bar.set_linewidth(0.0)
                bar.set_alpha(0.0)
                height = bar.get_height()
                if height <= 0:
                    continue
                x, y = bar.get_x(), bar.get_y()
                width = bar.get_width()
                radius = min(width * 0.35, height * 0.6, 12.0)
                z = bar.get_zorder()
                base_height = max(height - radius, 0)
                if base_height > 0:
                    rect = patches.Rectangle((x, y), width, base_height, linewidth=0.0, facecolor=color_rgb, edgecolor='none')
                    rect.set_antialiased(True)
                    rect.set_zorder(z)
                    bar.axes.add_patch(rect)
                top_y = y + base_height
                top_height = height - base_height
                top_patch = self._create_top_round_patch(x, top_y, width, top_height, radius, color_rgb)
                top_patch.set_zorder(z + 0.01)
                top_patch.set_path_effects([
                    patheffects.SimpleLineShadow(offset=(-0.6, -0.6), shadow_color="#000000", alpha=0.18),
                    patheffects.Normal()
                ])
                bar.axes.add_patch(top_patch)
        except Exception:
            log_exc()
    def _create_top_round_patch(self, x, y, width, height, radius, color_rgb):
        try:
            if height <= 0 or radius <= 0:
                patch = patches.Rectangle((x, y), width, height, linewidth=0.0, facecolor=color_rgb, edgecolor='none')
                patch.set_antialiased(True)
                return patch
            r = min(radius, width / 2.0, height)
            y_top = y + height
            y_line = y_top - r
            k = 0.5522847498
            verts = [
                (x, y),
                (x, y_line),
                (x, y_line + r * k),
                (x + r * (1 - k), y_top),
                (x + r, y_top),
                (x + width - r, y_top),
                (x + width - r * (1 - k), y_top),
                (x + width, y_line + r * k),
                (x + width, y_line),
                (x + width, y),
                (x, y),
            ]
            codes = [
                Path.MOVETO,
                Path.LINETO,
                Path.CURVE4,
                Path.CURVE4,
                Path.CURVE4,
                Path.LINETO,
                Path.CURVE4,
                Path.CURVE4,
                Path.CURVE4,
                Path.LINETO,
                Path.CLOSEPOLY,
            ]
            patch = patches.PathPatch(Path(verts, codes), facecolor=color_rgb, edgecolor='none', linewidth=0.0)
            patch.set_antialiased(True)
            return patch
        except Exception:
            log_exc()
            fallback = patches.Rectangle((x, y), width, height, linewidth=0.0, facecolor=color_rgb, edgecolor='none')
            fallback.set_antialiased(True)
            return fallback
    def _apply_line_style(self, line, base_color):
        try:
            line.set_linewidth(2.4)
            line.set_markeredgewidth(0)
            line.set_markerfacecolor(base_color)
            line.set_markeredgecolor(self._darken_hex(base_color, 0.75))
            line.set_alpha(0.95)
            line.set_solid_joinstyle('round')
            line.set_solid_capstyle('round')
            line.set_path_effects([
                patheffects.SimpleLineShadow(offset=(-1.0, -1.0), shadow_color="#000000", alpha=0.25),
                patheffects.Normal()
            ])
        except Exception:
            log_exc()
    def _configure_pick_line(self, line):
        try:
            line.set_alpha(0.0)
            line.set_markerfacecolor((0, 0, 0, 0))
            line.set_markeredgecolor((0, 0, 0, 0))
            line.set_markeredgewidth(0.0)
        except Exception:
            log_exc()
    def _create_line_markers(self, ax, xs, ys, base_color):
        try:
            edge = self._darken_hex(base_color, 0.75)
            face = base_color
            scatter = ax.scatter(xs, ys, s=28, c=face, edgecolors=edge, linewidths=0.7, zorder=4)
            scatter.set_alpha(0.95)
            return scatter
        except Exception:
            log_exc()
            return None
    def _add_hover(self, fig, ax, elements, vals, unit, canvas, labels=None, max_v=1, raw_vals=None, formatter=None):
        try:
            if not elements:
                return
            annot = Annotation("", xy=(0,0), xytext=(20,20), textcoords="offset points",
                               bbox=dict(boxstyle="round", fc="w", alpha=0.8),
                               arrowprops=dict(arrowstyle="->"), fontsize=12)
            annot.set_visible(False)
            mean_v = np.mean(vals) if vals else 1
            state = {"pinned": False, "index": None}
            def update_annot(ind, val, label=None):
                state["index"] = ind
                raw_val = raw_vals[ind] if raw_vals is not None and ind < len(raw_vals) else val
                if isinstance(elements[0], plt.Line2D):
                    pos = (ind, val)
                else:
                    bar = elements[ind]
                    pos = (bar.get_x() + bar.get_width()/2, bar.get_y() + bar.get_height())
                annot.xy = pos
                if formatter:
                    text_body = formatter(val, raw_val, label)
                else:
                    primary = f"{val:.2f}".rstrip("0").rstrip(".")
                    text_body = primary + (f" {unit}" if unit else "")
                    pct_max = (val / max_v * 100) if max_v > 0 else 0
                    pct_avg = (val / mean_v * 100) if mean_v > 0 else 0
                    text_body += f"\n{int(pct_max)}% of max, {int(pct_avg)}% of avg"
                if label:
                    text = f"{label}\n{text_body}"
                else:
                    text = text_body
                annot.set_text(text)
                annot.get_bbox_patch().set_facecolor('yellow' if ctk.get_appearance_mode().lower() == 'dark' else 'lightgray')
            def hover(event):
                vis = annot.get_visible()
                if event.inaxes == ax:
                    found = False
                    for i in range(len(vals)):
                        if isinstance(elements[0], plt.Line2D):
                            cont = abs(event.xdata - i) < 0.1 if event.xdata is not None else False
                        else:
                            cont, _ = elements[i].contains(event)
                        if cont:
                            label = labels[i] if labels else None
                            update_annot(i, vals[i], label)
                            annot.set_visible(True)
                            fig.canvas.draw_idle()
                            found = True
                            return
                    if not found and state["pinned"] and state["index"] is not None:
                        annot.set_visible(True)
                        fig.canvas.draw_idle()
                        return
                if vis and not state["pinned"]:
                    annot.set_visible(False)
                    fig.canvas.draw_idle()
            def click(event):
                if event.inaxes != ax:
                    if state["pinned"]:
                        state["pinned"] = False
                        annot.set_visible(False)
                        fig.canvas.draw_idle()
                    return
                idx = None
                if isinstance(elements[0], plt.Line2D):
                    if event.xdata is not None:
                        idx_candidate = int(round(event.xdata))
                        if 0 <= idx_candidate < len(vals):
                            idx = idx_candidate
                else:
                    for i in range(len(vals)):
                        contains, _ = elements[i].contains(event)
                        if contains:
                            idx = i
                            break
                if idx is not None:
                    label = labels[idx] if labels else None
                    update_annot(idx, vals[idx], label)
                    state["pinned"] = True
                    annot.set_visible(True)
                    fig.canvas.draw_idle()
                else:
                    if state["pinned"]:
                        state["pinned"] = False
                        annot.set_visible(False)
                        fig.canvas.draw_idle()
            fig.canvas.mpl_connect("motion_notify_event", hover)
            fig.canvas.mpl_connect("button_press_event", click)
        except Exception:
            log_exc()
    def _on_chart_pick(self, event, keys, period, canvas):
        try:
            if not keys:
                return
            mouse_event = getattr(event, "mouseevent", None)
            if mouse_event is None or getattr(mouse_event, "button", None) not in (1,):
                return
            inds = getattr(event, "ind", None)
            if not inds:
                return
            ind = inds[0]
            if ind >= len(keys):
                return
            selected_key = keys[ind]
            self._stats_period_stack.append((self.current_period, self.current_view_start))
            if period == "Month":
                self.current_period = "Week"
                self.current_view_start = selected_key  
            elif period == "Week":
                self.current_period = "Day"
                self.current_view_start = selected_key 
            else:
                if self._stats_period_stack:
                    self._stats_period_stack.pop()
                self._update_back_button()
                return
            if hasattr(self, "opt_period"):
                self._set_option_menu_value(self.opt_period, self.current_period, "_suppress_period_callback")
            self._redraw_all_stats_charts()
        except Exception:
            log_exc()
    # Resize handling
    def _on_window_resize(self, event):
        try:
            new_width = max(240, min(260, event.width // 5))
            if self.sidebar_outer.winfo_ismapped():
                self.sidebar_outer.configure(width=new_width)
                self.grid_columnconfigure(0, minsize=new_width)
            else:
                self.grid_columnconfigure(0, minsize=0)
            total_height = max(200, self.winfo_height())
            target_top = max(120, int(total_height * TOP_MAX_HEIGHT_RATIO))
            current_video = max(120, getattr(self, "display_draw_h", target_top))
            self._apply_video_height_constraints(min(current_video, target_top))
            self.after(50, self._on_video_outer_resize, None)
        except Exception:
            log_exc()
    def _on_video_outer_resize(self, event):
        try:
            if getattr(self, "_layout_resize_active", False):
                return
            if not hasattr(self, "video_outer"):
                return
            pad = 16
            container_w = event.width if event else self.video_outer.winfo_width()
            container_h = event.height if event else self.video_outer.winfo_height()
            container_w = max(40, int(container_w) - pad)
            container_h = max(40, int(container_h) - pad)
            if container_w <= 0 or container_h <= 0:
                return
            aspect_w, aspect_h = VIDEO_ASPECT
            aspect_ratio = aspect_w / aspect_h
            width_based_height = int(container_w * aspect_h / aspect_w)
            height_based_width = int(container_h * aspect_w / aspect_h)
            target_w = container_w
            target_h = width_based_height
            if target_h > container_h:
                target_h = container_h
                target_w = height_based_width
            desired_h = max(120, min(container_h, target_h))
            desired_w = int(desired_h * aspect_ratio)
            if desired_w > container_w:
                desired_w = container_w
                desired_h = int(desired_w / aspect_ratio)
            desired_w = max(160, min(container_w, desired_w))
            desired_h = max(120, min(container_h, desired_h))
            final_h = self._apply_video_height_constraints(desired_h)
            if final_h != desired_h:
                desired_h = final_h
                desired_w = int(desired_h * aspect_ratio)
                if desired_w > container_w:
                    desired_w = container_w
                    desired_h = int(desired_w / aspect_ratio)
                    desired_h = self._apply_video_height_constraints(desired_h)
            desired_w = min(container_w, int(desired_h * aspect_ratio))
            desired_w = max(160, desired_w)
            desired_h = max(120, desired_h)
            if (self.display_draw_w, self.display_draw_h) != (desired_w, desired_h):
                self.display_draw_w, self.display_draw_h = desired_w, desired_h
            self.video_label.configure(width=desired_w, height=desired_h)
            self.video_label.place_configure(relx=0.5, rely=0.5, anchor="center")
            self.main.grid_columnconfigure(1, weight=1, minsize=0)
        except Exception:
            log_exc()
    # Shutdown handling
    def _on_close(self):
        try:
            now = time.time()
            if self.visible_start:
                diff_sec = int(now - self.visible_start)
                self.visible_seconds += diff_sec
                self.visible_start = None
            if self.slouch_session_start is not None:
                self.slouch_accum_seconds += int(now - self.slouch_session_start)
                self.slouch_session_start = None
            if cursor:
                try:
                    today_str = date.today().isoformat()
                    current_hour = datetime.now().strftime("%Y-%m-%d %H")
                    changes_made = False
                    current_visible = self.visible_seconds
                    diff_visible = max(0, current_visible - self.saved_visible_seconds)
                    if diff_visible > 0:
                        cursor.execute("SELECT duration_sec FROM screen_time WHERE date = ?", (today_str,))
                        res = cursor.fetchone()
                        current_sec = res[0] if res else 0
                        new_sec = current_sec + diff_visible
                        cursor.execute("INSERT OR REPLACE INTO screen_time (date, duration_sec) VALUES (?, ?)", (today_str, new_sec))
                        self.saved_visible_seconds = current_visible
                        changes_made = True
                    current_slouch = self.slouch_accum_seconds
                    diff_slouch = max(0, current_slouch - self.saved_slouch_seconds)
                    if diff_slouch > 0:
                        cursor.execute("SELECT seconds FROM posture_time WHERE date = ?", (today_str,))
                        res = cursor.fetchone()
                        current_sec = res[0] if res else 0
                        new_sec = current_sec + diff_slouch
                        cursor.execute("INSERT OR REPLACE INTO posture_time (date, seconds) VALUES (?, ?)", (today_str, new_sec))
                        self.saved_slouch_seconds = current_slouch
                        changes_made = True
                    if self.enable_distance and self.pending_distance_count > 0:
                        cursor.execute("SELECT avg_distance_cm, count FROM distance_log WHERE date = ?", (today_str,))
                        res = cursor.fetchone()
                        old_avg = res[0] if res and res[0] is not None else 0.0
                        old_count = res[1] if res and res[1] is not None else 0
                        old_sum = old_avg * old_count
                        new_total_sum = old_sum + self.pending_distance_sum
                        new_total_count = old_count + self.pending_distance_count
                        new_avg = new_total_sum / new_total_count if new_total_count > 0 else 0.0
                        cursor.execute("INSERT OR REPLACE INTO distance_log (date, avg_distance_cm, count) VALUES (?, ?, ?)",
                                       (today_str, new_avg, new_total_count))
                        self.distance_sum_total = new_total_sum
                        self.distance_count_total = new_total_count
                        self.pending_distance_sum = 0.0
                        self.pending_distance_count = 0
                        changes_made = True
                    hourly_changed = self._flush_hourly_metrics(current_hour, auto_commit=False)
                    if hourly_changed:
                        changes_made = True
                    if changes_made:
                        conn.commit()
                except Exception:
                    log_exc()
            cfg = load_json(CONFIG_FILE, {})
            cfg.update({
                "delay_seconds": self.delay_seconds,
                "display_mode": self.display_mode,
                "unit": self.unit,
                "min_distance_cm": self.min_distance_cm,
                "theme_mode": self.theme_mode,
                "enable_posture": self.enable_posture,
                "enable_distance": self.enable_distance,
                "enable_twenty": self.enable_twenty,
                "enable_nail_biting": self.enable_nail_biting,
                "enable_face_touch": self.enable_face_touch,
                "performance_mode": self.performance_mode,
                "accent_color": self.accent_color,
                "default_period": self.default_period,
                "pinned_graphs": self.pinned_graphs
            }); save_json(CONFIG_FILE, cfg)
        except Exception:
            log_exc()
        self.running = False
        try:
            self.destroy()
        except Exception:
            pass
        try:
            self.quit()
        except Exception:
            pass
        try:
            if conn: conn.close()
        except Exception:
            pass

if __name__ == "__main__":
    try:
        app = ScreenGuardianApp()
        app.mainloop()
    except Exception:
        append_log_line("Top-level crash")
        log_exc()
        print("App crashed. See screenguardian.log in app data dir.")
