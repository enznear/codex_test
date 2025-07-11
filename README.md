# codex_test

This repository contains a sample FastAPI backend and agent for deploying user uploaded Gradio or Docker apps on a GPU server.


## Setup

Install the required Python packages:

```bash
pip install -r requirements.txt
```

Running `flake8` (or another linter) before committing is recommended to catch
style issues early. This tool may need to be installed locally.

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
- `POST /restart/{app_id}`: restart a previously uploaded Docker app using the existing image.
- `DELETE /apps/{app_id}`: remove an app and all associated files.

### Uploading Gradio or Docker apps

1. **Prepare your files**
   - **Gradio**: upload a single Python file or a zip archive containing your Gradio app. If an `app.py` file is present it will be used; otherwise the backend runs the first `.py` file it finds in the uploaded directory.
     If the archive contains a `requirements.txt` file it will be installed into
     a fresh Python **3.10** virtual environment which is then used to run the
     script.
     You can use `examples/gradio_app.py` as a starting point; it simply launches on the provided port. The proxy rewrites the path prefix so no extra `root_path` argument is needed.
   - **Docker**: include a `Dockerfile` in the uploaded directory or archive. If a `Dockerfile` is present the backend treats the app as a Docker project and builds it with `docker build`.
   - **Docker compose**: include a `docker-compose.yml` file. The compose project will be started with `docker compose up` and should map the container port to `${PORT}` so the backend assigned port is used.
   - **Docker tar**: upload a tar archive created with `docker save`. The agent loads the image and runs it with GPU access using `docker run --gpus all`.

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

The agent builds and runs Docker or Gradio apps and reports status back to the backend. It can also load images from tar archives and launch them with GPU access.

When launching Docker images manually, ensure GPU access is enabled. Install the
`nvidia-container-toolkit` and run containers with `--gpus all` (or
`--runtime=nvidia` on older Docker versions) so frameworks like PyTorch can find
CUDA. If you want to target a specific GPU, use `--gpus device=N`. Docker maps
the chosen GPU to `CUDA_VISIBLE_DEVICES=0` inside the container.

Apps can set a `vram_required` value when uploaded. If a single GPU does not
have enough free memory the agent will allocate multiple GPUs whose combined
free memory satisfies the request. The selected indices are passed to Docker as
`--gpus device=0,1` and reported by the status APIs.

The backend specifies a port for each app which the agent forwards to Docker or sets as the `PORT` environment variable for Gradio scripts. Docker apps and compose services should listen on the port indicated by this variable. The proxy now rewrites incoming requests so frameworks like Gradio no longer need a `root_path` argument. The agent still sets `ROOT_PATH` for compatibility, but it can be ignored.

During upload the backend now verifies that the chosen port is free by briefly
binding to it. If the port is busy another from the `AVAILABLE_PORTS` pool is
tried. The agent performs the same check before launching an app, failing the
run if the port cannot be bound.

On startup the agent now checks existing proxy routes and any running Docker
containers. This allows it to restore heartbeat loops for previously deployed
apps. Recovered apps are marked as running again so their status shows up
correctly in the backend.


Example setup:

```bash
pip install fastapi uvicorn httpx
export BACKEND_URL=http://localhost:8000  # adjust if backend runs elsewhere
uvicorn agent.agent:app --port 8001
```

### Environment Variables

- `AGENT_URL`: URL where the agent can be reached (used by the backend).
  Defaults to `http://localhost:8001`.
- `AGENT_TIMEOUT`: Timeout in seconds for requests from the backend to the agent.
  Defaults to `30`.
- `BACKEND_URL`: URL of the backend API (used by the agent).
  Defaults to `http://localhost:8000`.
- `PROXY_LINK_PATH`: path where the agent attempts to symlink the generated
  Nginx config so it is loaded automatically. Defaults to
  `/etc/nginx/conf.d/apps.conf`.
- `HUGGINGFACE_HUB_TOKEN`: optional token used by the agent when running apps
  or installing dependencies. Providing it allows apps to download gated models
  from Hugging Face. The environment variable `HF_TOKEN` is also respected.

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
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header Range $http_range;
        proxy_set_header If-Range $http_if_range;
        proxy_buffering off;
    }
}
```

Gradio apps rely on WebSockets, so the proxy configuration must forward upgrade
headers as shown above. You can restrict access by providing `allow_ips`
(comma separated IP list) or an `auth_header` when uploading an app. These
values are injected into the Nginx location block.
## Frontend

A minimal React+Tailwind UI is included in `frontend/index.html`. The backend now serves this file automatically, so simply navigate to `http://localhost:8000` in your browser after starting the backend.

## Templates

You can store reusable app templates and deploy them with a single click.

- `POST /templates` – upload a template archive or folder.
  - `name`: template name.
  - `file`: archive or single file containing the template.
  - `description` (optional): short text shown in the UI.
  - `vram_required` (optional): expected VRAM for apps deployed from this template.
- `GET /templates` – list available templates with `id`, `name`, `description`, `type` and `vram_required`.
- `POST /deploy_template/{template_id}` – copy the template to the uploads directory and start it just like an uploaded app. The response includes the new `app_id` and URL.
- `POST /save_template/{app_id}` – save an uploaded app as a new template using its current name and description.
- `DELETE /templates/{template_id}` – remove a saved template and its files.

Any folder placed directly under `./templates` will be automatically registered as a template when the backend starts or when the templates list is fetched.


On the frontend the templates are loaded on page load and displayed with a **Deploy** button. Clicking it triggers the deployment endpoint and the running apps list is refreshed automatically.
Each uploaded app also shows a **Save Template** button to store it for future reuse.
Templates display their name, description, type and VRAM, along with a **Delete** button to remove them.

## Authentication

An `admin` user is created automatically on first run. Set the `ADMIN_PASSWORD`
environment variable to control the default password.

Create a user account via the `/register` endpoint (or through the Register form on the login page):


```bash
curl -X POST -F "username=myuser" -F "password=mypass" http://localhost:8000/register
```

Then obtain a token using `/login`:

```bash
curl -X POST -d "username=myuser&password=mypass" http://localhost:8000/login
```

The response contains an `access_token` that must be included in the `Authorization` header when calling protected endpoints like `/upload` or `/templates`:

```bash
Authorization: Bearer <token>
```

The React frontend now prompts for login on first visit and stores the token in `localStorage`. A Register tab is available for creating additional users.


