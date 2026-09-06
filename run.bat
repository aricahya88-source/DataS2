@echo off
setlocal
if not exist .venv (
  py -m venv .venv
)
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env (
  echo.
  echo CATATAN: Buat environment variables GAS_ENDPOINT, GAS_SECRET, dan SECRET_KEY sebelum menjalankan aplikasi.
)
python app.py
pause
