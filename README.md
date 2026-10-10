# GitHub AI 今日热榜 · 桌面悬浮小组件

Windows 桌面右上角的 AI 热门项目「热搜榜」。无边框、半透明毛玻璃、大圆角、始终置顶、不进任务栏；实时从 GitHub 拉取最新最热的 AI 开源项目，交互像微博热搜——左侧排名、中间项目名、右侧 Star 数，点击即可在浏览器打开对应项目。

![GitHub AI Hotlist](avatar.png)

## 功能特性

- **动态榜单**：启动即拉取，之后每 1 小时自动刷新，也可点标题栏「↻」手动刷新
- **永不为空**：按 今天 → 近7天 → 近30天 → 近90天 逐级放宽时间窗；全空再兜底「不限时间最热 AI 项目」
- **动态 UI**：加载动画、榜单逐条入场、条目悬停反馈、更新时间实时跳动
- **排名强调**：第 1 名红、第 2 名橙、第 3 名亮蓝
- **桌面体验**：无边框透明窗口、自绘圆角阴影、始终置顶、可拖动、自动定位右上角、开机自启
- **稳定可靠**：网络请求在子线程计算、经信号槽回主线程更新界面（避免跨线程崩溃）；失败自动保留上次数据

## 环境要求

- Windows 10 / 11
- Python 3.8+

## 安装与运行

```bash
pip install PyQt5 requests
python app.py
```

## 打包为 exe

```bash
pip install pyinstaller
pyinstaller -F -w -n GitHubAIHotlist app.py
# 生成 dist/GitHubAIHotlist.exe，与 avatar.png 放在同一目录运行
```

打包后开机自启（可选）：将 exe 放入启动文件夹（`Win+R` → `shell:startup`），或用任务计划程序。

## 项目结构

```
github-ai-hotlist/
├── app.py               # 主程序（UI + 数据拉取 + 动态动画）
├── avatar.png           # Q 版形象（右下角装饰，可替换）
├── README.md
├── LICENSE              # MIT
└── requirements.txt
```

## 配置说明

所有关键参数集中在 `app.py` 顶部「可配置参数区」：

| 参数 | 默认 | 说明 |
|---|---|---|
| `WINDOW_WIDTH / HEIGHT` | 400 / 500 | 窗口尺寸 px |
| `REFRESH_INTERVAL` | 3600 | 自动刷新间隔（秒） |
| `ITEM_COUNT` | 7 | 榜单条目数 |
| `MAIN_COLOR` | `#4A90E2` | 主色调（蓝） |
| `CORNER_RADIUS` | 22 | 圆角半径 |
| `ROW_STEP_MS` | 90 | 榜单逐条入场间隔 ms |

## 数据源

- [GitHub 搜索 API](https://api.github.com/search/repositories?q=AI&sort=stars&order=desc)
  `GET /search/repositories?q=AI&sort=stars&order=desc&per_page=7`
- 未认证限流约 60 次/小时，本项目 1 小时刷新一次完全够用

## 免责声明

本项目为个人学习与桌面美化用途。榜单内容来自 GitHub 公开数据，项目所有权归各开源作者所有。

## License

[MIT](LICENSE)
