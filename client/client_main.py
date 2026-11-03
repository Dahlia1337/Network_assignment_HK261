"""
Điểm khởi chạy ứng dụng Client (Client Entrypoint) - Chế độ Web Gateway.
Cách chạy:
    python -m client.client_main
    python -m client.client_main --auto-discover
    python -m client.client_main --host 127.0.0.1 --port 8888 --web-port 5000
"""

import argparse
import logging
import sys
import webbrowser
import threading

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
    parser.add_argument("--host", default="127.0.0.1", help="Địa chỉ IP máy chủ (mặc định: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_TCP_PORT, help=f"Cổng TCP máy chủ (mặc định: {DEFAULT_TCP_PORT})")
    parser.add_argument("--auto-discover", action="store_true", help="Tự động dò tìm máy chủ qua UDP Broadcast trong mạng LAN")
    parser.add_argument("--web-host", default="0.0.0.0", help="Địa chỉ LAN cho Web Gateway (mặc định: 0.0.0.0)")
    parser.add_argument("--web-port", type=int, default=5000, help="Cổng Web UI (mặc định: 5000)")

    args = parser.parse_args()

    client = CollaborationClient()

    target_host = args.host
    target_port = args.port

    # Tự động quét Server qua UDP Broadcast nếu cờ --auto-discover bật hoặc giữ --host mặc định (127.0.0.1 hoặc 0.0.0.0)
    if args.auto_discover or args.host in ("127.0.0.1", DEFAULT_HOST):
        logger.info("[*] Đang dò tìm máy chủ tự động qua UDP Broadcast...")
        discovered_ip, discovered_tcp_port = client.discover_server(timeout=2.0)
        if discovered_ip and discovered_tcp_port:
            target_host = discovered_ip
            target_port = discovered_tcp_port
            logger.info(f"[✓] Đã tự động phát hiện Server tại {target_host}:{target_port} qua UDP Discovery!")
        else:
            logger.info(f"[*] Không phát hiện thấy Server qua UDP Broadcast. Fallback về cấu hình: {target_host}:{target_port}")

    logger.info(f"[*] Đang kết nối mạng nền tới Server {target_host}:{target_port}...")
    if not client.connect(target_host, target_port):
        logger.error(f"[X] Không thể kết nối đến {target_host}:{target_port}. Hãy kiểm tra máy chủ đã chạy chưa!")
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