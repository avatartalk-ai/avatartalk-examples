#!/bin/bash
# Run the AvatarTalk Expressive WebChat client using uv

set -e

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Creating from .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✓ Created .env file. Please edit it with your API keys."
        echo ""
        echo "Required variables:"
        echo "  - OPENAI_API_KEY"
        echo "  - DEEPGRAM_API_KEY"
        echo "  - AVATARTALK_API_KEY"
        echo ""
        exit 1
    else
        echo "❌ .env.example not found. Please create .env manually."
        exit 1
    fi
fi

# Check if venv exists
if [ ! -d .venv ]; then
    echo "Creating virtual environment with uv..."
    uv venv
    echo "Installing dependencies..."
    uv pip install -e .
fi

echo "Starting AvatarTalk Expressive WebChat..."
echo "Access the client at: http://localhost:8080"
echo ""

# Run with uv
uv run uvicorn src.app:app --reload --port 8080 --host 0.0.0.0
