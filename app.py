# -*- coding: utf-8 -*-
"""
AI 今日热榜 —— Windows 桌面动态悬浮小组件（多源版）
=====================================================
无边框 / 半透明毛玻璃 / 大圆角 / 始终置顶 / 不进任务栏
启动自动定位屏幕右上角，可拖动。

多数据源（顶部 Tab 切换）：
  - GitHub Trending：api.github.com/search/repositories?q=AI
  - Hacker News：hacker-news.firebaseio.com（过滤 AI 相关）
  - HuggingFace Papers：huggingface.co/api/daily_papers

动态化：加载动画 / 榜单逐条入场 / 悬停反馈 / 点击刷新 / 时间实时跳动
每 1 小时自动刷新当前源一次。

运行:  python app.py
打包:  pyinstaller -F -w app.py
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
    QPushButton, QButtonGroup,
)
from PyQt5.QtCore import (
    Qt, QTimer, QPoint, QUrl, pyqtSignal,
    QPropertyAnimation, QEasingCurve,
)
from PyQt5.QtGui import (
    QFont, QPixmap, QPainter, QColor, QBrush, QPen,
)

# ============================ 可配置参数区 ============================
WINDOW_WIDTH      = 500          # 窗口宽度 px（加宽容纳5个Tab）
WINDOW_HEIGHT     = 620          # 窗口高度 px
SCREEN_MARGIN     = 20           # 距屏幕右上角的边距 px
REFRESH_INTERVAL  = 60 * 60      # 自动刷新间隔（秒）1 小时
ITEM_COUNT        = 7            # 每个源的榜单条目数量
CORNER_RADIUS     = 22           # 圆角半径
BG_OPACITY        = 178          # 背景半透明度 (0-255)
MAIN_COLOR        = "#4A90E2"    # 主色调（蓝）
TITLE_TEXT        = "AI 今日热榜"
ROW_STEP_MS       = 80           # 榜单逐条入场间隔 ms

# 数据源定义：(key, 显示名, metric 图标, 兜底链接)
SOURCES = [
    ("github",       "AI项目",   "★",
     "https://github.com/topics/artificial-intelligence"),
    ("github_ml",    "机器学习", "★",
     "https://github.com/topics/machine-learning"),
    ("github_py",    "Python",   "★",
     "https://github.com/topics/python"),
    ("embodied",     "具身智能", "🤖",
     "https://github.com/topics/embodied-ai"),
    ("hn",           "HN资讯",   "▲",
     "https://news.ycombinator.com"),
    ("hf",           "HF论文",   "⬆",
     "https://huggingface.co/papers"),
]
# 每个源对应的 GitHub 搜索关键词
GITHUB_QUERIES = {
    "github": "AI",
    "github_ml": "machine learning",
    "github_py": "python",
}
# =====================================================================

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AVATAR_PATH = os.path.join(BASE_DIR, "avatar.png")


# ============================ 数据拉取函数（子线程调用） ============================
def fetch_github(query="AI"):
    """GitHub Search：按关键词搜项目，今天→近7天→近30天→不限时间"""
    today = datetime.now()
    headers = {"User-Agent": "AI-Hotlist-Widget/1.0"}
    q = query.replace(" ", "+")
    for days in (0, 7, 30, 90):
        d = (today - timedelta(days=days)).strftime("%Y-%m-%d")
        url = ("https://api.github.com/search/repositories"
               "?q={0}+created:>{1}&sort=stars&order=desc"
               "&per_page={2}".format(q, d, ITEM_COUNT))
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            continue
        items = r.json().get("items", [])
        if items:
            break
    else:
        url = ("https://api.github.com/search/repositories"
               "?q={0}&sort=stars&order=desc&per_page={1}".format(q, ITEM_COUNT))
        r = requests.get(url, headers=headers, timeout=15)
        items = r.json().get("items", [])
    rows = []
    for i, it in enumerate(items[:ITEM_COUNT]):
        desc = (it.get("description") or "").strip()
        if desc and len(desc) > 60:
            desc = desc[:58] + "…"
        rows.append((
            i + 1,
            it.get("name", "?"),
            int(it.get("stargazers_count", 0)),
            it.get("html_url", ""),
            desc,  # 一句话解释
        ))
    return rows


def fetch_hackernews():
    """Hacker News：topstories，过滤 AI 相关关键词"""
    headers = {"User-Agent": "AI-Hotlist-Widget/1.0"}
    r = requests.get(
        "https://hacker-news.firebaseio.com/v0/topstories.json",
        headers=headers, timeout=15)
    ids = r.json()[:12]  # 取前12条筛（减少网络请求）
    kw = ("AI", "LLM", "GPT", "agent", "Agent", "model", "language model",
          "OpenAI", "Claude", "Gemini", "diffusion", "transformer",
          "machine learning", "deep learning", "neural")
    rows = []
    for sid in ids:
        if len(rows) >= ITEM_COUNT:
            break
        try:
            ir = requests.get(
                "https://hacker-news.firebaseio.com/v0/item/{}.json".format(sid),
                headers=headers, timeout=3)
            it = ir.json()
            if not it:
                continue
            title = it.get("title", "")
            if not any(k.lower() in title.lower() for k in kw):
                continue
            url = it.get("url") or ("https://news.ycombinator.com/item?id=%s" % sid)
            rows.append((
                len(rows) + 1,
                title[:48] + ("…" if len(title) > 48 else ""),
                int(it.get("score", 0)),
                url,
                "",  # HN 无 desc
            ))
        except Exception:
            continue
    return rows


def fetch_hf_papers():
    """HuggingFace Daily Papers：直接走国内镜像（huggingface.co 被墙）"""
    headers = {"User-Agent": "AI-Hotlist-Widget/1.0"}
    urls = [
        "https://hf-mirror.com/api/daily_papers",  # 国内镜像，首选
        "https://huggingface.co/api/daily_papers",
    ]
    data = None
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code == 200:
                data = r.json()
                break
        except Exception:
            continue
    if data is None:
        raise RuntimeError("HF unreachable")
    rows = []
    for i, it in enumerate(data[:ITEM_COUNT]):
        p = it.get("paper", it)
        title = p.get("title", "?")
        up = int(p.get("upvotes", it.get("numUpvotes", 0)))
        pid = p.get("id", it.get("paper", {}).get("id", ""))
        url = "https://huggingface.co/papers/%s" % pid if pid else "https://huggingface.co/papers"
        rows.append((
            i + 1,
            title[:46] + ("…" if len(title) > 46 else ""),
            up,
            url,
            "",  # HF 无 desc
        ))
    return rows


FETCHERS = {
    "github":     lambda: fetch_github("AI"),
    "github_ml":  lambda: fetch_github("machine learning"),
    "github_py":  lambda: fetch_github("python"),
    "embodied":   lambda: fetch_github("embodied AI robot"),
    "hn":         fetch_hackernews,
    "hf":         fetch_hf_papers,
}


# ============================ UI 组件 ============================
class ClickableLabel(QLabel):
    clicked = pyqtSignal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class HotListItem(QWidget):
    """单条榜单：排名 | 名称+desc | 热度"""
    def __init__(self, rank, name, metric, url, metric_icon="★", desc=""):
        super().__init__()
        self.url = url
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        row = QHBoxLayout()
        row.setContentsMargins(10, 5, 10, 2)
        row.setSpacing(8)

        rank_lbl = QLabel(str(rank))
        rank_lbl.setFixedWidth(26)
        rank_lbl.setAlignment(Qt.AlignCenter)
        f = QFont()
        f.setBold(True)
        f.setPointSize(14)
        rank_lbl.setFont(f)
        if rank == 1:
            rank_lbl.setStyleSheet("color:#E44D4D;")
        elif rank == 2:
            rank_lbl.setStyleSheet("color:#F59E0B;")
        elif rank == 3:
            rank_lbl.setStyleSheet("color:#4A90E2;")
        else:
            rank_lbl.setStyleSheet("color:#8A94A6;")

        name_col = QVBoxLayout()
        name_col.setSpacing(1)
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("color:#2B6CB0; font-size:16px; font-weight:bold;")
        name_lbl.setToolTip(name)
        name_col.addWidget(name_lbl)
        if desc:
            desc_lbl = QLabel(desc)
            desc_lbl.setStyleSheet("color:#7A8AA0; font-size:12px;")
            desc_lbl.setWordWrap(True)
            name_col.addWidget(desc_lbl)

        metric_lbl = QLabel("{} {:,}".format(metric_icon, metric))
        metric_lbl.setStyleSheet("color:#4A90E2; font-size:14px; font-weight:bold;")
        metric_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        row.addWidget(rank_lbl)
        row.addLayout(name_col, 1)
        row.addWidget(metric_lbl)
        outer.addLayout(row)
        self.setLayout(outer)

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


# ============================ 主组件 ============================
class HotlistWidget(QWidget):
    data_ready = pyqtSignal(list, bool, str)  # (rows, ok, source_key)

    def __init__(self):
        super().__init__()
        self.last_pos = QPoint()
        self.current_source = "github"
        self.items_data = {s[0]: [] for s in SOURCES}
        self._row_timer = None
        self._pending_rows = []
        self._pending_ok = True
        self._row_index = 0
        self.click_through = False

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self._build_ui()
        self.data_ready.connect(self._on_data_ready)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.fetch_current)
        self.timer.start(REFRESH_INTERVAL * 1000)

        self.clock = QTimer(self)
        self.clock.timeout.connect(self._tick_time)
        self.clock.start(30 * 1000)

        self._place_top_right()
        self._start_loading()
        self.fetch_current()

    # ---------------- UI ----------------
    def _build_ui(self):
        root = QVBoxLayout()
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(8)

        # 标题行
        title_row = QHBoxLayout()
        title = QLabel(TITLE_TEXT)
        f = QFont()
        f.setBold(True)
        f.setPointSize(17)
        title.setFont(f)
        title.setStyleSheet("color:%s;" % MAIN_COLOR)
        title_row.addWidget(title)
        title_row.addStretch()

        self.loading_lbl = QLabel("◌ 加载中…")
        self.loading_lbl.setStyleSheet("color:#6A7B9A; font-size:11px;")
        self.loading_lbl.setVisible(False)
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
        refresh_lbl.setStyleSheet("color:#4A90E2; font-size:16px; font-weight:bold;")
        refresh_lbl.setToolTip("立即刷新")
        refresh_lbl.clicked.connect(self._manual_refresh)
        title_row.addWidget(refresh_lbl)
        root.addLayout(title_row)

        # 来源切换 Tab
        tab_row = QHBoxLayout()
        tab_row.setSpacing(6)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.tab_buttons = {}
        for key, name, icon, more_url in SOURCES:
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(26)
            btn.setStyleSheet(self._tab_style(active=(key == self.current_source)))
            btn.clicked.connect(lambda checked, k=key: self._switch_source(k))
            self.tab_group.addButton(btn)
            self.tab_buttons[key] = btn
            tab_row.addWidget(btn)
        tab_row.addStretch()
        root.addLayout(tab_row)

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

        # 底部
        foot = QHBoxLayout()
        self.time_lbl = QLabel("正在连接数据源…")
        self.time_lbl.setStyleSheet("color:#7A8AA0; font-size:10px;")
        foot.addWidget(self.time_lbl)
        foot.addStretch()
        self.more_lbl = QLabel("")
        self.more_lbl.setStyleSheet("font-size:10px;")
        self.more_lbl.setOpenExternalLinks(True)
        foot.addWidget(self.more_lbl)
        root.addLayout(foot)

        # 头像
        avatar_row = QHBoxLayout()
        avatar_row.addStretch()
        self.avatar_lbl = QLabel()
        self.avatar_lbl.setFixedSize(68, 68)
        self.avatar_lbl.setAlignment(Qt.AlignCenter)
        pix = QPixmap(AVATAR_PATH)
        if not pix.isNull():
            pix = pix.scaled(68, 68, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.avatar_lbl.setPixmap(pix)
        else:
            self.avatar_lbl.setText("⚡")
            self.avatar_lbl.setStyleSheet("font-size:28px; color:#4A90E2;")
        avatar_row.addWidget(self.avatar_lbl)
        root.addLayout(avatar_row)

        self.setLayout(root)
        self._update_more_link()

    def _tab_style(self, active):
        if active:
            return ("QPushButton{ background:rgba(74,144,226,230); color:white;"
                    "border:none; border-radius:13px; padding:0 12px; font-size:12px; font-weight:bold;}"
                    "QPushButton:hover{ background:rgba(74,144,226,255);}")
        return ("QPushButton{ background:rgba(255,255,255,180); color:#4A90E2;"
                "border:1px solid rgba(74,144,226,80); border-radius:13px;"
                "padding:0 12px; font-size:12px;}"
                "QPushButton:hover{ background:rgba(255,255,255,230);}")

    def _update_more_link(self):
        for key, name, icon, url in SOURCES:
            if key == self.current_source:
                self.more_lbl.setText(
                    "<a style='color:#4A90E2; text-decoration:none;' href='%s'>查看更多</a>" % url)
                break

    # ---------------- 圆角背景 ----------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        sh = self.rect().adjusted(0, 8, 2, 2)
        painter.setBrush(QColor(40, 80, 150, 55))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(sh, CORNER_RADIUS, CORNER_RADIUS)
        rect = self.rect().adjusted(2, 2, -2, -2)
        brush = QBrush(QColor(240, 247, 255, BG_OPACITY))
        pen = QPen(QColor(160, 200, 235, 70), 1)
        painter.setBrush(brush)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, CORNER_RADIUS, CORNER_RADIUS)

    def _place_top_right(self):
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = geo.right() - WINDOW_WIDTH - SCREEN_MARGIN
        y = geo.top() + SCREEN_MARGIN
        self.move(x, y)

    # ---------------- 交互 ----------------
    def _start_loading(self):
        self.loading_lbl.setText("◌ 加载中…")
        self.loading_lbl.setVisible(True)
        self._load_anim.start()

    def _stop_loading(self):
        self._load_anim.stop()
        self.loading_lbl.setVisible(False)

    def _manual_refresh(self):
        self.time_lbl.setText("正在刷新…")
        self._start_loading()
        self.fetch_current()

    def _tick_time(self):
        if self.items_data[self.current_source]:
            self.time_lbl.setText(
                "更新于 %s · 点击条目打开" % datetime.now().strftime("%H:%M"))

    def _switch_source(self, key):
        if key == self.current_source:
            return
        self.current_source = key
        for k, btn in self.tab_buttons.items():
            btn.setStyleSheet(self._tab_style(active=(k == key)))
        self._update_more_link()
        if self.items_data[key]:
            self._on_data_ready(self.items_data[key], True, key)
        else:
            # 立即清空旧数据，避免切换后还显示上一个源的内容
            self.list_widget.clear()
            self._start_loading()
            names = dict((s[0], s[1]) for s in SOURCES)
            self.time_lbl.setText("正在加载 " + names.get(key, key) + " …")
            self.fetch_current()

    # ---------------- 数据拉取 ----------------
    def fetch_current(self):
        src = self.current_source
        fetcher = FETCHERS.get(src)
        if not fetcher:
            return

        def worker():
            try:
                rows = fetcher()
                if not rows:
                    raise RuntimeError("empty result")
                self.items_data[src] = rows
                self.data_ready.emit(rows, True, src)
            except Exception as e:
                print("fetch error [%s]:" % src, e)
                cached = self.items_data.get(src, [])
                self.data_ready.emit(cached, bool(cached), src)

        threading.Thread(target=worker, daemon=True).start()

    # ---------------- 主线程：动态入场 ----------------
    def _on_data_ready(self, rows, ok, source_key):
        if source_key != self.current_source:
            return  # 异步返回但用户已切走
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
        row_data = self._pending_rows[self._row_index]
        if len(row_data) >= 5:
            rank, name, metric, url, desc = row_data
        else:
            rank, name, metric, url = row_data
            desc = ""
        icon = "★"
        for k, n, ic, u in SOURCES:
            if k == self.current_source:
                icon = ic
                break
        item = QListWidgetItem()
        w = HotListItem(rank, name, metric, url, metric_icon=icon, desc=desc)
        item.setSizeHint(w.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, w)
        self._row_index += 1

    def _finish_rows(self):
        if self._pending_ok:
            self.time_lbl.setText(
                "更新于 %s · 点击条目打开" % datetime.now().strftime("%H:%M"))
        elif self.items_data[self.current_source]:
            self.time_lbl.setText("上次数据 · 刷新失败")
        else:
            self.time_lbl.setText("更新失败：请检查网络")

    # ---------------- 拖动 ----------------
    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._show_menu(event.globalPos())
            return
        if event.button() == Qt.LeftButton and not self.click_through:
            self.last_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        if self.click_through:
            return
        if event.buttons() & Qt.LeftButton and not self.last_pos.isNull():
            delta = event.globalPos() - self.last_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.last_pos = event.globalPos()

    def _show_menu(self, pos):
        from PyQt5.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("👆 点击穿透：" + ("开" if self.click_through else "关"),
                    self._toggle_click_through)
        m.addSeparator()
        m.addAction("刷新", self.fetch_current)
        m.addAction("退出", self.close)
        m.exec_(pos)

    def _toggle_click_through(self):
        self.click_through = not self.click_through
        if self.click_through:
            self.setWindowFlags(self.windowFlags() | Qt.WindowTransparentForInput)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.show()


if __name__ == "__main__":
    import traceback
    LOG_PATH = os.path.join(BASE_DIR, "hotlist_error.log")
    try:
        app = QApplication(sys.argv)
        app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        win = HotlistWidget()
        win.show()
        sys.exit(app.exec_())
    except Exception:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("==== %s ====\n" % datetime.now())
            f.write(traceback.format_exc())
        raise
