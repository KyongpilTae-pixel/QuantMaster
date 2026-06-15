import reflex as rx

config = rx.Config(
    app_name="main",
    stylesheets=["print.css", "mobile.css"],
    # 로컬 네트워크 접속용: 모바일/다른 기기에서 192.168.0.84:3000 으로 접속
    api_url="http://192.168.0.84:7500",
    backend_host="0.0.0.0",
)
