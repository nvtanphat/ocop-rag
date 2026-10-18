@echo off
cd /d "%~dp0"
npm run dev > vite.out.log 2> vite.err.log
