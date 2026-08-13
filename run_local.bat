@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/2] 安装/检查依赖...
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo 安装失败，请确认已安装 Python 3.10-3.12，并可使用 py 命令。
  pause
  exit /b 1
)
echo [2/2] 启动 WAVE-Replay...
py -m streamlit run streamlit_app.py
pause
