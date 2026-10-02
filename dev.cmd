@echo off
setlocal
cd /d "%~dp0"
uv run streamlit run app.py --server.address 127.0.0.1 --server.port 8501
