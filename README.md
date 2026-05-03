# Minerva - Gemini Live API

A real-time tutoring assistant using the [Google Gen AI Python SDK](https://github.com/googleapis/python-genai) for the backend and vanilla JavaScript for the frontend. The agent is configured to guide students with questions and hints first, then provide more direct help when they remain stuck.


## Demo Video


## Tech Stack

- Gemini API
- Pinecone API
- Canvas API
- Python
- HTML/CSS/Javascript

## AI Disclosure

This project was developed with the assistance of AI tools, including Codex and Claude, primarily for coding support and debugging. All implementation decisions and final integrations were made by the development team.

## Track Selection

This project is designed for the Google Gemini Track

## Quick Start

### 1. Backend Setup

Install dependencies and start the FastAPI server using `uv`:

```bash
# Create a virtual environment and install dependencies
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt

# Start the server
uv run python main.py
```

### 2. Frontend

Open your browser and navigate to:

[http://localhost:8001](http://localhost:8001)

The landing page is a login screen. New users can create an account at:

[http://localhost:8001/create-user](http://localhost:8001/create-user)

After logging in, the tutor is available at:

[http://localhost:8001/tutor](http://localhost:8001/tutor)

