"""
Điểm khởi chạy ứng dụng Client (Client Entrypoint) - Chế độ Web Gateway.
Cách chạy:
    python -m client.client_main --host 127.0.0.1 --port 8888 --web-port 5000
"""

import argparse
import logging
import sys
import webbrowser
import threading

from common.constants import DEFAULT_HOST, DEFAULT_TCP_PORT
from client.core_client import CollaborationClient
from client.web_server import run_web_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("client.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger("ClientMain")

def main():
    parser = argparse.ArgumentParser(description="Distributed Web Client - MMT261")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Địa chỉ IP máy chủ (mặc định: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_TCP_PORT, help=f"Cổng TCP máy chủ (mặc định: {DEFAULT_TCP_PORT})")
    parser.add_argument("--web-host", default="0.0.0.0", help="Địa chỉ LAN cho Web Gateway (mặc định: 0.0.0.0)")
    parser.add_argument("--web-port", type=int, default=5000, help="Cổng Web UI (mặc định: 5000)")

    args = parser.parse_args()

    client = CollaborationClient()

    logger.info(f"[*] Đang kết nối mạng nền tới Server {args.host}:{args.port}...")
    if not client.connect(args.host, args.port):
        logger.error(f"[X] Không thể kết nối đến {args.host}:{args.port}. Hãy kiểm tra máy chủ đã chạy chưa!")
        sys.exit(1)

    logger.info(f"[✓] Kết nối Socket thành công! Chờ người dùng đăng nhập qua Web UI...")

    # Khởi chạy Local Web Gateway trên luồng chính
    web_url = f"http://127.0.0.1:{args.web_port}"
    logger.info("=" * 60)
    logger.info(f"🚀 GIAO DIỆN WEB SẴN SÀNG TẠI: {web_url}")
    logger.info(f"🌐 TRUY CẬP TỪ MẠNG LAN: http://<IP_MÁY_NÀY>:{args.web_port}")
    logger.info("=" * 60)

    # Tự động mở trình duyệt
    threading.Timer(1.0, lambda: webbrowser.open(web_url)).start()

    try:
        run_web_server(client, args.web_host, args.web_port)
    except KeyboardInterrupt:
        logger.info("[!] Đang đóng ứng dụng...")
        client.disconnect()
        sys.exit(0)

if __name__ == "__main__":
    main()