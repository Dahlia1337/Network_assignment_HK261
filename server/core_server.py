"""
Module core_server: Khởi tạo TCP Socket Server và UDP Discovery Service.
Hiện thực hóa Milestone 2 (Basic Client-Server Handshake) & Milestone 3 (Concurrency).
"""

import logging
import socket
import threading
import time
from typing import Optional

from common.constants import (
    DEFAULT_HOST,
    DEFAULT_TCP_PORT,
    DEFAULT_UDP_PORT,
    DEFAULT_UDP_FILE_PORT,
    ENCODING,
    HEARTBEAT_TIMEOUT,
    SOCKET_RECV_BUFFER_SIZE,
)
from common.message_types import MessageType
from common.protocol import pack_packet, send_udp_packet, unpack_packet
from server.chat_history import ChatHistoryManager
from server.client_handler import ClientHandler
from server.file_router import FileRouter
from server.session_manager import SessionManager
from server.user_manager import UserManager

logger = logging.getLogger("CoreServer")


class CollaborationServer:
    """
    Máy chủ cộng tác phân tán:
    - TCP Listener: Xử lý kết nối tin cậy cho Xác thực, Tin nhắn và Điều phối tệp.
    - UDP Responder: Hỗ trợ tính năng Discovery tự động phát hiện máy chủ trong mạng LAN.
    - UDP File Router: Định tuyến luồng dữ liệu file binary (Streaming ARQ).
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_TCP_PORT,
        udp_port: int = DEFAULT_UDP_PORT,
        udp_file_port: int = DEFAULT_UDP_FILE_PORT,
    ):
        self.host = host
        self.port = port
        self.udp_port = udp_port
        self.udp_file_port = udp_file_port

        self.session_manager = SessionManager()
        self.user_manager = UserManager()
        self.file_router = FileRouter(self.session_manager)
        self.chat_history = ChatHistoryManager()

        self.tcp_sock: Optional[socket.socket] = None
        self.udp_sock: Optional[socket.socket] = None
        self.udp_file_sock: Optional[socket.socket] = None
        self.is_running = False

        self._threads = []

    def start(self):
        """
        Khởi động cả 4 dịch vụ: TCP Server, UDP Discovery/Heartbeat, Dead Session Cleaner và UDP File Router.
        """
        self.is_running = True
        self._start_udp_discovery()
        self._start_udp_file_router()
        self._start_session_cleaner()
        self._start_tcp_server()

    def _start_tcp_server(self):
        """
        Khởi tạo TCP Raw Socket với SO_REUSEADDR và lắng nghe kết nối.
        """
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.tcp_sock.bind((self.host, self.port))
            self.tcp_sock.listen(50)  # Hàng đợi tối đa 50 kết nối đồng thời
            logger.info(f"[TCP] Server đang lắng nghe tại {self.host}:{self.port} (Sẵn sàng phục vụ)")
        except Exception as e:
            logger.error(f"[X] Không thể bind TCP socket trên {self.host}:{self.port}: {e}")
            self.stop()
            return

        while self.is_running:
            try:
                client_sock, client_addr = self.tcp_sock.accept()
                # Tạo một luồng riêng xử lý cho mỗi Client kết nối (Milestone 3)
                handler = ClientHandler(
                    sock=client_sock,
                    address=client_addr,
                    session_manager=self.session_manager,
                    user_manager=self.user_manager,
                    file_router=self.file_router,
                    chat_history=self.chat_history,
                )
                handler.start()
                self._threads.append(handler)
            except OSError:
                break
            except Exception as e:
                logger.error(f"[X] Lỗi accept kết nối mới: {e}")

    def _start_udp_discovery(self):
        """
        Dịch vụ khám phá mạng và Heartbeat qua UDP (Section 6 & Milestone 7).
        - Khi Client phát sóng broadcast 'DISCOVER_COLLAB_SERVER', Server phản hồi địa chỉ TCP.
        - Khi Client gửi HEARTBEAT_PING (0x0090), Server cập nhật last_seen và phản hồi HEARTBEAT_PONG (0x0091).
        """
        def udp_worker():
            try:
                self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.udp_sock.bind(("", self.udp_port))
                logger.info(f"[UDP] Discovery & Heartbeat service đang hoạt động trên cổng UDP {self.udp_port}")

                while self.is_running:
                    try:
                        data, addr = self.udp_sock.recvfrom(SOCKET_RECV_BUFFER_SIZE)
                        if not data:
                            continue

                        # 1. Khám phá mạng (Discovery)
                        try:
                            text = data.decode(ENCODING, errors="ignore").strip()
                            if text == "DISCOVER_COLLAB_SERVER":
                                response = f"COLLAB_SERVER_OFFER:{self.port}".encode(ENCODING)
                                self.udp_sock.sendto(response, addr)
                                continue
                        except Exception:
                            pass

                        # 2. Xử lý UDP Heartbeat (Keep-alive)
                        packet = unpack_packet(data)
                        if packet and packet.msg_type == MessageType.HEARTBEAT_PING:
                            username = None
                            if isinstance(packet.data, dict):
                                username = packet.data.get("username")
                            elif isinstance(packet.data, str):
                                username = packet.data

                            if username:
                                self.session_manager.update_last_seen(username)
                                logger.debug(f"[UDP Heartbeat] Đã cập nhật last_seen cho '{username}' từ {addr}")

                            send_udp_packet(
                                sock=self.udp_sock,
                                addr=addr,
                                msg_type=MessageType.HEARTBEAT_PONG,
                                data={"status": "alive", "username": username or ""},
                            )

                    except OSError:
                        break
                    except Exception as e:
                        logger.error(f"[UDP Worker] Lỗi xử lý datagram: {e}")
            except Exception as e:
                logger.warning(f"[UDP] Lỗi khởi tạo UDP service: {e}")

        t = threading.Thread(target=udp_worker, daemon=True)
        t.start()

    def _start_session_cleaner(self):
        """
        Luồng quét ngầm định kỳ dọn dẹp các phiên chết (Dead Session Eviction - Milestone 7).
        Chạy lặp lại mỗi 3 giây, gọi session_manager.get_stale_sessions(HEARTBEAT_TIMEOUT).
        Với mỗi user bị sập, thực hiện đóng TCP socket, remove_session(), và phát gói TCP USER_LEAVE_BROADCAST.
        """
        def cleaner_worker():
            logger.info(f"[Session Cleaner] Luồng dọn dẹp phiên chết đã khởi động (chu kỳ 3s, timeout {HEARTBEAT_TIMEOUT}s)")
            while self.is_running:
                try:
                    time.sleep(3.0)
                    if not self.is_running:
                        break

                    stale_users = self.session_manager.get_stale_sessions(HEARTBEAT_TIMEOUT)
                    for username in stale_users:
                        logger.warning(
                            f"[Session Cleaner] Phát hiện phiên chết của user '{username}' "
                            f"(quá {HEARTBEAT_TIMEOUT}s không có heartbeat). Tiến hành dọn dẹp..."
                        )
                        sess = self.session_manager.get_session(username)
                        if sess:
                            try:
                                sess.sock.close()
                            except Exception:
                                pass

                        removed = self.session_manager.remove_session(username)
                        if removed:
                            self.session_manager.broadcast(
                                MessageType.USER_LEAVE_BROADCAST,
                                {"username": username},
                            )
                except Exception as e:
                    logger.error(f"[Session Cleaner] Lỗi trong luồng quét phiên chết: {e}")

        t = threading.Thread(target=cleaner_worker, daemon=True)
        t.start()

    def _start_udp_file_router(self):
        """
        Khởi tạo socket UDP riêng chuyên dùng cho File Transfer (DEFAULT_UDP_FILE_PORT = 8890).
        Lắng nghe datagram từ Sender/Receiver và định tuyến trực tiếp qua FileRouter không ghi đĩa.
        """
        def udp_file_worker():
            try:
                self.udp_file_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.udp_file_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.udp_file_sock.bind(("", self.udp_file_port))
                logger.info(f"[UDP File Router] Đang lắng nghe file streaming tại cổng UDP {self.udp_file_port}")

                while self.is_running:
                    try:
                        data, addr = self.udp_file_sock.recvfrom(SOCKET_RECV_BUFFER_SIZE)
                        if data:
                            self.file_router.route_udp_chunk(data, self.udp_file_sock, addr)
                    except OSError:
                        break
                    except Exception as e:
                        logger.error(f"[UDP File Router] Lỗi xử lý datagram: {e}")
            except Exception as e:
                logger.error(f"[UDP File Router] Lỗi khởi tạo UDP file socket: {e}")

        t = threading.Thread(target=udp_file_worker, daemon=True)
        t.start()

    def stop(self):
        """
        Dừng toàn bộ server và giải phóng tài nguyên mạng an toàn.
        """
        self.is_running = False
        if self.tcp_sock:
            try:
                self.tcp_sock.close()
            except Exception:
                pass
        if self.udp_sock:
            try:
                self.udp_sock.close()
            except Exception:
                pass
        if self.udp_file_sock:
            try:
                self.udp_file_sock.close()
            except Exception:
                pass
        logger.info("[!] Máy chủ đã dừng hoạt động thành công.")