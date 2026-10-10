@echo off
REM 打包 GitHub AI 今日热榜桌面组件
pip install pyinstaller
pyinstaller -F -w -n GitHubAIHotlist app.py
echo.
echo 打包完成：dist\GitHubAIHotlist.exe
echo 请将 avatar.png 复制到 exe 同目录运行。
pause
