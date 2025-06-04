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
  - `httpx`
- Docker installed and running
- Nginx installed and available in `PATH` (e.g., `apt-get install nginx`)


## Backend

Run the backend server:

```bash
uvicorn backend.main:app --reload
```

Example setup:

```bash
pip install fastapi uvicorn httpx
export AGENT_URL=http://localhost:8001  # adjust if agent runs elsewhere
uvicorn backend.main:app --reload
```

- `POST /upload`: upload a zip or project folder.
  - `name`: app name used for duplicate checks.
  - `allow_ips`: comma separated list of IPs allowed to access the app (optional).
  - `auth_header`: header value required for access (sent as `Authorization`, optional).
- `GET /status`: check running status of apps.
- `GET /logs/{app_id}`: view logs for an app.
- `POST /update_status`: (used by agent) update status in the database.
- `POST /stop/{app_id}`: stop a running app.
- `DELETE /apps/{app_id}`: remove an app and all associated files.

### Uploading Gradio or Docker apps

1. **Prepare your files**
   - **Gradio**: upload a single Python file or a zip archive containing your Gradio app. The backend will run the first `.py` file it finds in the uploaded directory.
   - **Docker**: include a `Dockerfile` in the uploaded directory or archive. If a `Dockerfile` is present the backend treats the app as a Docker project and builds it with `docker build`.

2. **Send a request**
  - Via the frontend: open `http://localhost:8000` in a browser and select a file to upload.
   - Via `curl`:

     ```bash
     curl -F "file=@my_app.zip" http://localhost:8000/upload
     ```

   Replace `my_app.zip` with your Python script or zipped folder. The response will include an `app_id` that can be used to check status.

## Agent

Run the agent on a GPU server:

```bash
uvicorn agent.agent:app --port 8001
```

The agent builds and runs Docker or Gradio apps and reports status back to the backend.

The backend specifies a port for each app which the agent forwards to Docker or sets as the `PORT` environment variable for Gradio scripts. Docker apps should listen on the port indicated by this `PORT` environment variable.

During upload the backend now verifies that the chosen port is free by briefly
binding to it. If the port is busy another from the `AVAILABLE_PORTS` pool is
tried. The agent performs the same check before launching an app, failing the
run if the port cannot be bound.


Example setup:

```bash
pip install fastapi uvicorn httpx
export BACKEND_URL=http://localhost:8000  # adjust if backend runs elsewhere
uvicorn agent.agent:app --port 8001
```

### Environment Variables

- `AGENT_URL`: URL where the agent can be reached (used by the backend).
  Defaults to `http://localhost:8001`.
- `BACKEND_URL`: URL of the backend API (used by the agent).
  Defaults to `http://localhost:8000`.
- `PROXY_LINK_PATH`: path where the agent attempts to symlink the generated
  Nginx config so it is loaded automatically. Defaults to
  `/etc/nginx/conf.d/apps.conf`.

## Proxy configuration

The agent writes Nginx configuration to `proxy/apps.conf` using the template
in `proxy/nginx_template.conf` and reloads Nginx whenever a new app starts.
The proxy module now tries to create a symlink to this file at the location
specified by `PROXY_LINK_PATH` (defaults to `/etc/nginx/conf.d/apps.conf`).
If the symlink is created successfully, Nginx will automatically pick up the
generated config. You can also set `PROXY_CONFIG_PATH` to write directly to the
Nginx directory. After writing the file, the agent calls `nginx -s reload` to
apply the changes. Without this step requests fall back to the backend and
return "Method Not Allowed." Each app is accessible via
`http://<server>:8080/apps/<app_id>/` (port 8080) and proxied to its assigned port.
```
server {
    listen 8080;
    location /apps/<app_id>/ {
        proxy_pass http://127.0.0.1:<port>/;
    }
}
```

You can restrict access by providing `allow_ips` (comma separated IP list) or an
`auth_header` when uploading an app. These values are injected into the Nginx
location block.
## Frontend

A minimal React+Tailwind UI is included in `frontend/index.html`. The backend now serves this file automatically, so simply navigate to `http://localhost:8000` in your browser after starting the backend.
