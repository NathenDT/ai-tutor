# AI Tutor - Gemini Live API, Python SDK & Vanilla JS

A real-time tutoring assistant using the [Google Gen AI Python SDK](https://github.com/googleapis/python-genai) for the backend and vanilla JavaScript for the frontend. The agent is configured to guide students with questions and hints first, then provide more direct help when they remain stuck.

## Quick Start

### 1. Backend Setup

Install dependencies and start the FastAPI server using `uv`:

```bash
# Create a virtual environment and install dependencies
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt

# Start the server
uv run main.py
```

### 2. Frontend

Open your browser and navigate to:

[http://localhost:8001](http://localhost:8001)

The landing page is a login screen. New users can create an account at:

[http://localhost:8001/create-user](http://localhost:8001/create-user)

After logging in, the tutor is available at:

[http://localhost:8001/tutor](http://localhost:8001/tutor)

## Features

- **Google Gen AI SDK**: Uses the official Python SDK (`google-genai`) for simplified API interaction.
- **FastAPI Backend**: Robust, async-ready web server handling WebSocket connections.
- **Simple Login Gate**: Protects the tutor page and WebSocket with an HTTP-only signed session cookie.
- **Real-time Streaming**: Bi-directional audio and video streaming.
- **Tutor Behavior**: Encourages students to show their thinking, avoids giving final answers immediately, and escalates help gradually.
- **Tool Use**: Demonstrates how to register and handle server-side tools.
- **Vanilla JS Frontend**: Lightweight frontend with no build steps or framework dependencies.

## Project Structure

```
/
├── main.py             # FastAPI server & WebSocket endpoint
├── gemini_live.py      # Gemini Live API wrapper using Gen AI SDK
├── requirements.txt    # Python dependencies
└── frontend/
    ├── index.html      # Login page
    ├── create-user.html # Create user page
    ├── tutor.html      # Tutor interface
    ├── create-user.js  # Create user page logic
    ├── login.js        # Login page logic
    ├── main.js         # Tutor application logic
    ├── gemini-client.js # WebSocket client for backend communication
    ├── media-handler.js # Audio/Video capture and playback
    └── pcm-processor.js # AudioWorklet for PCM processing
```

## Configuration

You can configure the application by setting environment variables or by using a `.env` file.

**Important:** You must set the `GEMINI_API_KEY` to your Google AI Studio API key.
Login users are stored in a local SQLite database. On first startup, the app creates
the database and seeds one user from the bootstrap values if the users table is empty.

1.  Create a `.env` file in the root directory.
2.  Add your API key and first-user bootstrap values:

```env
GEMINI_API_KEY=your_api_key_here
AUTH_DATABASE_PATH=data/auth.db
AUTH_BOOTSTRAP_USERNAME=your_username
AUTH_BOOTSTRAP_PASSWORD=your_password
```

`AUTH_SESSION_SECRET` is optional for local development. If omitted, the app stores
a generated session secret in the local auth database. Set it explicitly if you need
sessions to survive database replacement or multi-instance deployments.

Alternatively, you can set it in your shell:

```bash
export GEMINI_API_KEY=your_api_key_here
export AUTH_BOOTSTRAP_USERNAME=your_username
export AUTH_BOOTSTRAP_PASSWORD=your_password
```

## Core Components

### Backend (`gemini_live.py`)

The `GeminiLive` class wraps the `genai.Client` to manage the session:

```python
# Connects using the SDK
async with self.client.aio.live.connect(model=self.model, config=config) as session:
    # Manages input/output queues
    await asyncio.gather(
        send_audio(),
        send_video(),
        receive_responses()
    )
```

### Frontend (`gemini-client.js`)

The frontend communicates with the FastAPI backend via WebSockets, sending base64-encoded media chunks and receiving audio responses.
