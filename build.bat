@echo off
echo ============================================
echo  ModWarden - Build Script
echo ============================================

echo.
echo [1/3] Installing dependencies...
pip install -r requirements.txt
pip install pyinstaller

echo.
echo [2/3] Building executable...
cd src
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "ModWarden" ^
    --add-data ".;." ^
    --add-data "..\assets;assets" ^
    main.py

echo.
echo [3/3] Moving output...
if not exist "..\dist" mkdir "..\dist"
copy "dist\ModWarden.exe" "..\dist\ModWarden.exe"
cd ..

echo.
echo ============================================
echo  Build complete!
echo  Output: dist\ModWarden.exe
echo ============================================
pause
