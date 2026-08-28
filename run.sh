#!/bin/bash

# Navigate to the directory of the script
cd "$(dirname "$0")"

echo "======================================"
echo "    Starting BIMA GCS Services      "
echo "======================================"

# Setup backend if necessary
if [ ! -d "venv" ]; then
    echo "⚠️ Virtual environment (venv) not found. Creating and installing dependencies..."
    python -m venv venv
    
    if [ -f "venv/Scripts/activate" ]; then
        source venv/Scripts/activate
    elif [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    fi
    
    pip install -r requirements.txt
    
    if [ ! -f ".env" ]; then
        echo "⚠️ .env file not found. Copying from .env.example..."
        cp .env.example .env
    fi
fi

# Start backend in background
echo "[1/2] Starting FastAPI Backend..."
if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Start frontend in background
echo "[2/2] Starting Next.js Frontend..."
cd gcs_js
npm run dev &
FRONTEND_PID=$!

echo "======================================"
echo "✅ Services started!"
echo "📡 Backend URL: http://localhost:8000"
echo "🖥️  Frontend URL: http://localhost:3000"
echo "⚠️  Press [CTRL+C] to stop both services."
echo "======================================"

# Wait for user interrupt and then kill processes
trap "echo -e '\nStopping services...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT
wait
