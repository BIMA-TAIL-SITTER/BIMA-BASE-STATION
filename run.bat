@echo off
echo ======================================
echo     Starting BIMA GCS Services
echo ======================================

echo [1/2] Starting FastAPI Backend in new window...
start "BIMA Backend (FastAPI)" cmd /k "if not exist venv (echo [33mVirtual environment not found. Creating and installing dependencies...[0m & python -m venv venv & call venv\Scripts\activate.bat & pip install -r requirements.txt & if not exist .env copy .env.example .env) else (call venv\Scripts\activate.bat) & uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

echo [2/2] Starting Next.js Frontend in new window...
cd gcs_js
start "BIMA Frontend (Next.js)" cmd /k "npm run dev"
cd ..

echo ======================================
echo ✅ Services started in separate windows!
echo 📡 Backend URL: http://localhost:8000
echo 🖥️  Frontend URL: http://localhost:3000
echo ======================================
