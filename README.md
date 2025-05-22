# codex_test

This repository contains a sample FastAPI backend and agent for deploying user uploaded Gradio or Docker apps on a GPU server.

## Backend

Run the backend server:

```bash
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
