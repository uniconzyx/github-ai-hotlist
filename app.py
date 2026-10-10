# -*- coding: utf-8 -*-
"""
GitHub AI 今日热榜 —— Windows 桌面动态悬浮小组件
==================================================
无边框 / 半透明毛玻璃 / 大圆角 / 始终置顶 / 不进任务栏
启动自动定位屏幕右上角，可拖动。
动态化：加载动画 / 榜单逐条入场 / 悬停反馈 / 点击刷新 / 时间实时跳动
每 1 小时自动刷新一次 GitHub AI 热门项目。

运行:  python app.py
打包:  pyinstaller -F -w -i none app.py
"""
import sys
import os
import json
import threading
import webbrowser
from datetime import datetime, timedelta

import requests
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QSizePolicy, QGraphicsOpacityEffect,
)
from PyQt5.QtCore import (
    Qt, QTimer, QPoint, QUrl, pyqtSignal,
    QPropertyAnimation, QEasingCurve,
)
from PyQt5.QtGui import (
    QFont, QPixmap, QPainter, QColor, QBrush, QPen,
)

# ============================ 可配置参数区 ============================
WINDOW_WIDTH      = 400          # 窗口宽度 px
WINDOW_HEIGHT     = 500          # 窗口高度 px
SCREEN_MARGIN     = 20           # 距屏幕右上角的边距 px
REFRESH_INTERVAL  = 60 * 60      # 自动刷新间隔（秒）1 小时
ITEM_COUNT        = 7            # 榜单条目数量
CORNER_RADIUS     = 22           # 圆角半径
BG_OPACITY        = 172          # 背景半透明度 (0-255)
MAIN_COLOR        = "#4A90E2"    # 主色调（蓝）
TITLE_TEXT        = "AI 今日热榜"
MORE_LINK         = "https://github.com/topics/artificial-intelligence"
ROW_STEP_MS       = 90           # 榜单逐条入场的间隔毫秒
# =====================================================================

# 头像路径：打包成 exe 后从 exe 所在目录读取，脚本运行则从脚本目录读取
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AVATAR_PATH = os.path.join(BASE_DIR, "avatar.png")


class ClickableLabel(QLabel):
    """可点击的标签（刷新按钮用）"""
    clicked = pyqtSignal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class HotListItem(QWidget):
    """单条榜单：排名 | 项目名 | Star 数，点击打开链接；悬停有反馈"""
    def __init__(self, rank, repo_name, stars, url):
        super().__init__()
        self.url = url
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        lay = QHBoxLayout()
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(8)

        # 排名
        rank_lbl = QLabel(str(rank))
        rank_lbl.setFixedWidth(26)
        rank_lbl.setAlignment(Qt.AlignCenter)
        rfont = QFont()
        rfont.setBold(True)
        rank_lbl.setFont(rfont)
        if rank == 1:
            rank_lbl.setStyleSheet("color:#E44D4D;")   # 第1名 红
        elif rank == 2:
            rank_lbl.setStyleSheet("color:#F59E0B;")   # 第2名 橙
        elif rank == 3:
            rank_lbl.setStyleSheet("color:#4A90E2;")   # 第3名 亮蓝
        else:
            rank_lbl.setStyleSheet("color:#8A94A6;")

        # 项目名（蓝色，过长省略号）
        name_lbl = QLabel(repo_name)
        name_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        name_lbl.setStyleSheet("color:#2B6CB0; font-size:13px;")
        name_lbl.setToolTip(repo_name)
        name_lbl.setTextFormat(Qt.PlainText)

        # Star 数
        star_lbl = QLabel("★ {:,}".format(stars))
        star_lbl.setStyleSheet("color:#4A90E2; font-size:12px; font-weight:bold;")
        star_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        lay.addWidget(rank_lbl)
        lay.addWidget(name_lbl)
        lay.addWidget(star_lbl)
        self.setLayout(lay)

    def enterEvent(self, event):
        self.setStyleSheet("background: rgba(74,144,226,46); border-radius:9px;")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet("background: transparent;")
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.url:
            webbrowser.open(self.url)
        super().mouseReleaseEvent(event)


class GithubAIWidget(QWidget):
    """动态热榜组件：子线程只算数据，经信号槽回主线程更新 UI（避免闪退）"""
    data_ready = pyqtSignal(list, bool)   # (rows, ok)

    def __init__(self):
        super().__init__()
        self.last_pos = QPoint()
        self.items_data = []            # 兜底数据
        self._row_timer = None
        self._pending_rows = []
        self._pending_ok = True
        self._row_index = 0

        # 无边框 + 置顶 + 不进任务栏（Qt.Tool）
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self._build_ui()
        self._apply_shadow()

        # 数据经信号槽回主线程
        self.data_ready.connect(self._on_data_ready)

        # 自动刷新定时器
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.fetch_ai_repos)
        self.timer.start(REFRESH_INTERVAL * 1000)

        # 底部时间实时跳动（每分钟更新一次"更新时间"）
        self.clock = QTimer(self)
        self.clock.timeout.connect(self._tick_time)
        self.clock.start(30 * 1000)

        self._place_top_right()
        self._start_loading()
        self.fetch_ai_repos()          # 启动立即拉取

    # ---------------- UI ----------------
    def _build_ui(self):
        root = QVBoxLayout()
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        # 顶部标题行 + 刷新按钮 + 加载指示
        title_row = QHBoxLayout()
        title = QLabel(TITLE_TEXT)
        f = QFont()
        f.setBold(True)
        f.setPointSize(16)
        title.setFont(f)
        title.setStyleSheet("color:%s;" % MAIN_COLOR)
        title_row.addWidget(title)
        title_row.addStretch()

        self.loading_lbl = QLabel("◌ 正在加载…")
        self.loading_lbl.setStyleSheet("color:#6A7B9A; font-size:11px;")
        self.loading_lbl.setVisible(False)
        # 加载时做透明度脉冲动画
        self._load_effect = QGraphicsOpacityEffect(self.loading_lbl)
        self.loading_lbl.setGraphicsEffect(self._load_effect)
        self._load_anim = QPropertyAnimation(self._load_effect, b"opacity", self)
        self._load_anim.setDuration(700)
        self._load_anim.setStartValue(0.3)
        self._load_anim.setEndValue(1.0)
        self._load_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._load_anim.setLoopCount(-1)
        title_row.addWidget(self.loading_lbl)

        refresh_lbl = ClickableLabel("↻")
        refresh_lbl.setStyleSheet("color:#4A90E2; font-size:15px; font-weight:bold;")
        refresh_lbl.setToolTip("立即刷新")
        refresh_lbl.clicked.connect(self._manual_refresh)
        title_row.addWidget(refresh_lbl)
        root.addLayout(title_row)

        # 榜单
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget{ background: transparent; border: none; }
            QListWidget::item{
                background: rgba(255,255,255,215);
                border-radius: 9px;
                margin: 3px 0px 3px 0px;
            }
        """)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        root.addWidget(self.list_widget, 1)

        # 底部：更新时间 + 查看更多
        foot = QHBoxLayout()
        self.time_lbl = QLabel("正在连接数据源…")
        self.time_lbl.setStyleSheet("color:#7A8AA0; font-size:10px;")
        foot.addWidget(self.time_lbl)
        foot.addStretch()
        more = QLabel("<a style='color:#4A90E2; text-decoration:none;' href='%s'>查看更多</a>" % MORE_LINK)
        more.setStyleSheet("font-size:10px;")
        more.setOpenExternalLinks(True)
        more.linkActivated.connect(lambda u: webbrowser.open(u))
        foot.addWidget(more)
        root.addLayout(foot)

        # 头像行：占位 + Q版形象（右下角）
        avatar_row = QHBoxLayout()
        avatar_row.addStretch()
        self.avatar_lbl = QLabel()
        self.avatar_lbl.setFixedSize(64, 64)
        self.avatar_lbl.setAlignment(Qt.AlignCenter)
        pix = QPixmap(AVATAR_PATH)
        if not pix.isNull():
            pix = pix.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.avatar_lbl.setPixmap(pix)
            self.avatar_lbl.setToolTip("GitHub AI 热榜助手")
        else:
            self.avatar_lbl.setText("⚡")
            self.avatar_lbl.setStyleSheet("font-size:28px; color:#4A90E2;")
        avatar_row.addWidget(self.avatar_lbl)
        root.addLayout(avatar_row)

        self.setLayout(root)

    def _apply_shadow(self):
        """柔和阴影：弃用 QGraphicsDropShadowEffect（透明置顶窗口易崩溃），
        改为 paintEvent 手绘多层圆角模拟阴影。"""
        pass

    # ---------------- 圆角 + 毛玻璃背景 ----------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # 阴影层：向右下偏移的深色圆角，模拟悬浮阴影
        sh = self.rect().adjusted(0, 8, 2, 2)
        painter.setBrush(QColor(40, 80, 150, 55))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(sh, CORNER_RADIUS, CORNER_RADIUS)
        # 主体：半透明蓝白底模拟毛玻璃
        rect = self.rect().adjusted(2, 2, -2, -2)
        brush = QBrush(QColor(240, 247, 255, BG_OPACITY))
        pen = QPen(QColor(160, 200, 235, 70), 1)
        painter.setBrush(brush)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, CORNER_RADIUS, CORNER_RADIUS)

    # ---------------- 定位 ----------------
    def _place_top_right(self):
        """放到当前屏幕右上角，距顶/右各 SCREEN_MARGIN px（考虑任务栏与缩放）"""
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = geo.right() - WINDOW_WIDTH - SCREEN_MARGIN
        y = geo.top() + SCREEN_MARGIN
        self.move(x, y)

    # ---------------- 动态：加载动画 / 手动刷新 / 时间 ----------------
    def _start_loading(self):
        self.loading_lbl.setText("◌ 正在加载…")
        self.loading_lbl.setVisible(True)
        self._load_anim.start()

    def _stop_loading(self):
        self._load_anim.stop()
        self.loading_lbl.setVisible(False)

    def _manual_refresh(self):
        self.time_lbl.setText("正在刷新…")
        self._start_loading()
        self.fetch_ai_repos()

    def _tick_time(self):
        # 底部时间实时跳动：每分钟更新"更新时间"
        if self.items_data and "更新于" in self.time_lbl.text():
            self.time_lbl.setText(
                "更新于 %s · 点击条目打开项目" % datetime.now().strftime("%H:%M"))

    # ---------------- 数据拉取 ----------------
    def fetch_ai_repos(self):
        """拉取 AI 热门项目：今天→近7天→近30天→近90天逐级回退，
        再兜底不限时间取最热；全部在子线程算数据，仅经信号回主线程。"""
        def worker():
            try:
                today = datetime.now()
                for days in (0, 7, 30, 90):
                    d = (today - timedelta(days=days)).strftime("%Y-%m-%d")
                    url = ("https://api.github.com/search/repositories"
                           "?q=AI+created:>{0}&sort=stars&order=desc"
                           "&per_page={1}".format(d, ITEM_COUNT))
                    headers = {"User-Agent": "AI-Hotlist-Widget/1.0"}
                    r = requests.get(url, headers=headers, timeout=15)
                    if r.status_code != 200:
                        raise RuntimeError("HTTP %s" % r.status_code)
                    items = r.json().get("items", [])
                    if items:
                        break
                else:
                    # 绝对兜底：不限时间取最热 AI 项目，保证榜单非空
                    url = ("https://api.github.com/search/repositories"
                           "?q=AI&sort=stars&order=desc&per_page={0}".format(ITEM_COUNT))
                    r = requests.get(url, headers=headers, timeout=15)
                    if r.status_code != 200:
                        raise RuntimeError("HTTP %s" % r.status_code)
                    items = r.json().get("items", [])
                    if not items:
                        raise RuntimeError("empty result")

                rows = [
                    (i + 1, it.get("name", "?"),
                     int(it.get("stargazers_count", 0)),
                     it.get("html_url", ""))
                    for i, it in enumerate(items[:ITEM_COUNT])
                ]
                self.items_data = rows
                self.data_ready.emit(rows, True)
            except Exception as e:
                print("fetch error:", e)
                # 失败：保留旧数据，仅通过信号回主线程更新
                self.data_ready.emit(self.items_data, bool(self.items_data))

        threading.Thread(target=worker, daemon=True).start()

    # ---------------- 主线程：应用榜单（动态逐条入场） ----------------
    def _on_data_ready(self, rows, ok):
        self._stop_loading()
        self._pending_rows = rows
        self._pending_ok = ok
        self.list_widget.clear()
        self._row_index = 0
        if self._row_timer is not None:
            self._row_timer.stop()
        self._row_timer = QTimer(self)
        self._row_timer.timeout.connect(self._add_next_row)
        self._row_timer.start(ROW_STEP_MS)

    def _add_next_row(self):
        if self._row_index >= len(self._pending_rows):
            self._row_timer.stop()
            self._finish_rows()
            return
        rank, name, stars, url = self._pending_rows[self._row_index]
        item = QListWidgetItem()
        w = HotListItem(rank, name, stars, url)
        item.setSizeHint(w.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, w)
        self._row_index += 1

    def _finish_rows(self):
        if self._pending_ok:
            self.time_lbl.setText(
                "更新于 %s · 点击条目打开项目" % datetime.now().strftime("%H:%M"))
        elif self.items_data:
            self.time_lbl.setText("上次数据 · 自动刷新失败")
        else:
            self.time_lbl.setText("更新失败：请检查网络")

    # ---------------- 拖动 ----------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and not self.last_pos.isNull():
            delta = event.globalPos() - self.last_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.last_pos = event.globalPos()


if __name__ == "__main__":
    import traceback
    LOG_PATH = os.path.join(BASE_DIR, "hotlist_error.log")
    try:
        app = QApplication(sys.argv)
        app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        win = GithubAIWidget()
        win.show()
        sys.exit(app.exec_())
    except Exception:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("==== %s ====\n" % datetime.now())
            f.write(traceback.format_exc())
        raise
