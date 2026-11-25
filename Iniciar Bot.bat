@echo off
cd /d "%~dp0"
title Bot Mosteiro - Servico Unificado
color 0a

echo ==========================================
echo      INICIALIZANDO BOT DO MOSTEIRO
echo ==========================================
echo.
echo [1/2] Ativando o ambiente virtual Python...
".venv\Scripts\python.exe" bot.py

echo.
echo O bot foi encerrado ou encontrou um erro.
pause
