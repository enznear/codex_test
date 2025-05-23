import os
import json
import subprocess
import logging

ROUTES_FILE = os.environ.get("ROUTES_FILE", os.path.join(os.path.dirname(__file__), "routes.json"))
CONFIG_PATH = os.environ.get("PROXY_CONFIG_PATH", os.path.join(os.path.dirname(__file__), "apps.conf"))
BASE_PORT = int(os.environ.get("APP_BASE_PORT", "10000"))


def load_routes():
    if os.path.exists(ROUTES_FILE):
        with open(ROUTES_FILE) as f:
            return json.load(f)
    return {}


def save_routes(routes):
    os.makedirs(os.path.dirname(ROUTES_FILE), exist_ok=True)
    with open(ROUTES_FILE, "w") as f:
        json.dump(routes, f)


def allocate_port(routes):
    used = {info["port"] for info in routes.values()}
    port = BASE_PORT
    while port in used:
        port += 1
    return port


def generate_config(routes):
    lines = ["server {", "    listen 80;"]
    for app_id, info in routes.items():
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


def reload_proxy():
    try:
        subprocess.run(["nginx", "-s", "reload"], check=False)
    except FileNotFoundError:
        logging.warning("Nginx not installed; skipping reload")


def add_route(app_id, allow_ips=None, auth_header=None):
    routes = load_routes()
    if app_id in routes:
        port = routes[app_id]["port"]
    else:
        port = allocate_port(routes)
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
