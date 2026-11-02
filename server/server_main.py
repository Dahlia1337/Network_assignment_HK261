"""
Điểm khởi chạy máy chủ phân tán (Server Entrypoint).
Cách chạy:
    python -m server.server_main
    python -m server.server_main --host 0.0.0.0 --port 8888
"""

import argparse
import logging
import sys

from common.constants import DEFAULT_HOST, DEFAULT_TCP_PORT, DEFAULT_UDP_PORT, DEFAULT_UDP_FILE_PORT
from server.core_server import CollaborationServer

# Thiết lập định dạng log chuẩn mực
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("server.log", encoding="utf-8")
    ],
)
logger = logging.getLogger("Main")


def main():
    parser = argparse.ArgumentParser(description="Distributed Collaboration Server - MMT261")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Địa chỉ IP lắng nghe (mặc định: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_TCP_PORT, help=f"Cổng TCP lắng nghe (mặc định: {DEFAULT_TCP_PORT})")
    parser.add_argument("--udp-port", type=int, default=DEFAULT_UDP_PORT, help=f"Cổng UDP Discovery (mặc định: {DEFAULT_UDP_PORT})")
    parser.add_argument("--udp-file-port", type=int, default=DEFAULT_UDP_FILE_PORT, help=f"Cổng UDP File Streaming (mặc định: {DEFAULT_UDP_FILE_PORT})")

    args = parser.parse_args()

    print("=" * 65)
    print("      DISTRIBUTED CLIENT-SERVER COLLABORATION APPLICATION")
    print("                     SERVER CONSOLE")
    print("=" * 65)

    server = CollaborationServer(host=args.host, port=args.port, udp_port=args.udp_port, udp_file_port=args.udp_file_port)

    try:
        server.start()
    except KeyboardInterrupt:
        logger.info("\n[!] Nhận tín hiệu dừng từ bàn phím (Ctrl+C). Đang tắt server...")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
