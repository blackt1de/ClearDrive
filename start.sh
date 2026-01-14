#!/bin/bash
# Start ClearDrive backend server

# Set your Groq API key here or as environment variable
# export GROQ_API_KEY="your-key-here"

echo "Starting ClearDrive backend..."
echo "Server will be available at http://localhost:8000"
echo ""

python3 main.py
