@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ============================================
echo   猫叔的深思熟虑 - EXE 打包脚本
echo ============================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 Python，请先安装 Python 3.10+
    pause & exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo [OK] %%i

:: 安装 / 升级 PyInstaller
echo.
echo [1/4] 安装 PyInstaller...
pip install pyinstaller --quiet --upgrade
if errorlevel 1 (
    echo [ERROR] PyInstaller 安装失败
    pause & exit /b 1
)
echo [OK] PyInstaller 就绪

:: 确认源码目录存在
set SRC_DIR=%~dp0..\cat-research
if not exist "%SRC_DIR%\run_api.py" (
    echo [ERROR] 未找到源码目录: %SRC_DIR%
    echo         请确保 cat-research 目录在同一父目录下
    pause & exit /b 1
)
echo [OK] 源码目录: %SRC_DIR%

:: 安装项目依赖
echo.
echo [2/4] 安装项目依赖...
pip install -r "%SRC_DIR%\requirements.txt" --quiet
if errorlevel 1 (
    echo [WARN] 部分依赖安装失败，继续打包...
)
echo [OK] 依赖安装完成

:: 清理旧构建
echo.
echo [3/4] 清理旧构建...
if exist "%~dp0dist\cat-research" (
    rmdir /s /q "%~dp0dist\cat-research"
    echo [OK] 已清理旧版本
)
if exist "%~dp0build" (
    rmdir /s /q "%~dp0build"
)

:: 执行打包
echo.
echo [4/4] 开始打包（可能需要 2~5 分钟）...
cd /d "%~dp0"
pyinstaller cat_research.spec --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] 打包失败，请检查上方错误信息
    pause & exit /b 1
)

echo.
echo ============================================
echo   打包成功！
echo ============================================
echo.
echo   输出目录: %~dp0dist\cat-research\
echo   启动文件: %~dp0dist\cat-research\cat-research.exe
echo.
echo   使用说明：
echo   1. 将 dist\cat-research\ 整个文件夹复制给用户
echo   2. 用户双击 cat-research.exe 即可启动
echo   3. 程序会自动打开浏览器到 http://localhost:8000
echo   4. 首次使用需在 Web UI 的「设置」中配置 API Key
echo   5. 运行研究功能需要系统中已安装 Claude Code CLI
echo.

:: 创建桌面快捷方式脚本（放在 dist 目录下，用户自行运行）
echo 正在生成快捷方式脚本...
set SHORTCUT_SCRIPT=%~dp0dist\cat-research\创建桌面快捷方式.bat
(
  echo @echo off
  echo chcp 65001 ^>nul
  echo set "EXE_PATH=%%~dp0cat-research.exe"
  echo set "SHORTCUT=%%USERPROFILE%%\Desktop\猫叔的深思熟虑.lnk"
  echo powershell -Command "$ws=New-Object -ComObject WScript.Shell;$sc=$ws.CreateShortcut('%%SHORTCUT%%');$sc.TargetPath='%%EXE_PATH%%';$sc.WorkingDirectory='%%~dp0';$sc.Description='猫叔的深思熟虑';$sc.Save()"
  echo echo 快捷方式已创建到桌面！
  echo pause
) > "%SHORTCUT_SCRIPT%"

echo [OK] 快捷方式脚本已生成

pause
