import os
import json
import subprocess
import logging

ROUTES_FILE = os.environ.get(
    "ROUTES_FILE", os.path.join(os.path.dirname(__file__), "routes.json")
)
CONFIG_PATH = os.environ.get(
    "PROXY_CONFIG_PATH", os.path.join(os.path.dirname(__file__), "apps.conf")
)
# Path where nginx will read the config; defaults to /etc/nginx/conf.d/apps.conf
LINK_PATH = os.environ.get("PROXY_LINK_PATH", "/etc/nginx/conf.d/apps.conf")


def ensure_link():
    """Create or update symlink for Nginx to load the generated config."""
    if CONFIG_PATH == LINK_PATH:
        return
    try:
        if os.path.islink(LINK_PATH):
            current = os.readlink(LINK_PATH)
            if current != CONFIG_PATH:
                os.unlink(LINK_PATH)
                os.symlink(CONFIG_PATH, LINK_PATH)
        else:
            if os.path.exists(LINK_PATH):
                os.unlink(LINK_PATH)
            os.symlink(CONFIG_PATH, LINK_PATH)
    except PermissionError:
        logging.warning("Permission denied creating Nginx config link")


def load_routes():
    if os.path.exists(ROUTES_FILE):
        with open(ROUTES_FILE) as f:
            return json.load(f)
    return {}


def save_routes(routes):
    os.makedirs(os.path.dirname(ROUTES_FILE), exist_ok=True)
    with open(ROUTES_FILE, "w") as f:
        json.dump(routes, f)




def generate_config(routes):
    lines = ["server {", "    listen 8080;"]
    for app_id, info in routes.items():
        lines.append(f"    location = /apps/{app_id} {{")
        lines.append(f"        return 301 /apps/{app_id}/;")
        lines.append("    }")
        lines.append(f"    location /apps/{app_id}/ {{")
        lines.append(f"        proxy_pass http://127.0.0.1:{info['port']}/;")
        if info.get("allow_ips"):
            for ip in info["allow_ips"]:
                lines.append(f"        allow {ip};")
            lines.append("        deny all;")
        if info.get("auth_header"):
            header = info["auth_header"].replace('-', '_').lower()
            lines.append(f"        if ($http_{header} = '') {{ return 403; }}")
        lines.append("    }")
    lines.append("}")
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        f.write("\n".join(lines))
    ensure_link()


def reload_proxy():
    try:
        subprocess.run(["nginx", "-s", "reload"], check=False)
    except FileNotFoundError:
        logging.warning("Nginx not installed; skipping reload")


def add_route(app_id, port, allow_ips=None, auth_header=None):
    routes = load_routes()
    routes[app_id] = {"port": port}
    if allow_ips:
        routes[app_id]["allow_ips"] = allow_ips
    if auth_header:
        routes[app_id]["auth_header"] = auth_header
    save_routes(routes)
    generate_config(routes)
    reload_proxy()
    return port


def remove_route(app_id):
    """Remove an app's route and reload the proxy."""
    routes = load_routes()
    if app_id in routes:
        routes.pop(app_id)
        save_routes(routes)
        generate_config(routes)
        reload_proxy()
