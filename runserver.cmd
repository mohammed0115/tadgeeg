@echo off
cd /d "%~dp0"
del /q logs\runserver.out.log logs\runserver.err.log 2>nul
python manage.py runserver 0.0.0.0:8000 > logs\runserver.out.log 2> logs\runserver.err.log
