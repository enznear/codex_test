# codex_test

This repository contains a sample FastAPI backend and agent for deploying user uploaded Gradio or Docker apps on a GPU server.


## Setup

Install the required Python packages:

```bash
pip install -r requirements.txt
```

## Prerequisites

- Python 3 with the following packages:
  - `fastapi`
  - `uvicorn`
  - `requests`
- Docker installed and running


## Backend

Run the backend server:

```bash
uvicorn backend.main:app --reload
```

Example setup:

```bash
pip install fastapi uvicorn requests
export AGENT_URL=http://localhost:8001  # adjust if agent runs elsewhere
uvicorn backend.main:app --reload
```

### API Endpoints
- `POST /upload`: upload a zip or project folder.
- `GET /status`: check running status of apps.
- `GET /logs/{app_id}`: view logs for an app.
- `POST /update_status`: (used by agent) update status in the database.

## Agent

Run the agent on a GPU server:

```bash
uvicorn agent.agent:app --port 8001
```

The agent builds and runs Docker or Gradio apps and reports status back to the backend.

Example setup:

```bash
pip install fastapi uvicorn requests
export BACKEND_URL=http://localhost:8000  # adjust if backend runs elsewhere
uvicorn agent.agent:app --port 8001
```

### Environment Variables

- `AGENT_URL`: URL where the agent can be reached (used by the backend).
  Defaults to `http://localhost:8001`.
- `BACKEND_URL`: URL of the backend API (used by the agent).
  Defaults to `http://localhost:8000`.
## Frontend

A minimal React+Tailwind UI is available in `frontend/index.html`. It can be served using any static file server. For example:

```bash
python -m http.server 3000 --directory frontend
```

Then open `http://localhost:3000` in your browser.
