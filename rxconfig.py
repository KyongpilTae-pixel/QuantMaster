import os
import reflex as rx

_BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "7600"))
_HOST_IP      = os.environ.get("HOST_IP", "192.168.0.84")

config = rx.Config(
    app_name="main",
    stylesheets=["print.css", "mobile.css"],
    api_url=f"http://{_HOST_IP}:{_BACKEND_PORT}",
    backend_host="0.0.0.0",
)
