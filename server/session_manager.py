"""
Module session_manager: Quản lý danh bạ phiên người dùng trực tuyến (Online Sessions).
Hiện thực hóa Milestone 4 - Authentication & State Management.
Đảm bảo an toàn luồng (Thread-Safe) bằng threading.Lock.
"""

import logging
import socket
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from common.message_types import MessageType
from common.protocol import send_packet

logger = logging.getLogger("SessionManager")


@dataclass
class ClientSession:
    """
    Thông tin chi tiết của một phiên kết nối Client đang hoạt động.
    """
    username: str
    sock: socket.socket
    address: Tuple[str, int]
    login_time: float
    last_seen_time: float = 0.0
    udp_address: Optional[Tuple[str, int]] = None

    @property
    def ip(self) -> str:
        return self.address[0]

    @property
    def port(self) -> int:
        return self.address[1]


class SessionManager:
    """
    Quản lý tập trung toàn bộ danh sách Client đang kết nối.
    Tất cả các thao tác đọc/ghi vào từ điển sessions đều được đồng bộ qua Lock.
    """

    def __init__(self):
        self._sessions: Dict[str, ClientSession] = {}
        self._lock = threading.Lock()

    def add_session(self, username: str, sock: socket.socket, address: Tuple[str, int]) -> bool:
        """
        Thêm một người dùng mới vào bảng phiên sau khi xác thực thành công.
        :return: True nếu thêm thành công, False nếu username đã tồn tại.
        """
        with self._lock:
            if username in self._sessions:
                return False
            now = time.time()
            self._sessions[username] = ClientSession(
                username=username,
                sock=sock,
                address=address,
                login_time=now,
                last_seen_time=now,
            )
            logger.info(f"[+] User '{username}' đã đăng nhập từ {address[0]}:{address[1]}. Tổng online: {len(self._sessions)}")
            return True

    def remove_session(self, username: str) -> Optional[ClientSession]:
        """
        Xóa một phiên người dùng khỏi hệ thống khi đăng xuất hoặc mất mạng.
        """
        with self._lock:
            session = self._sessions.pop(username, None)
            if session:
                logger.info(f"[-] User '{username}' đã thoát khỏi hệ thống. Còn lại online: {len(self._sessions)}")
            return session

    def remove_by_socket(self, sock: socket.socket) -> Optional[str]:
        """
        Tìm và xóa phiên dựa trên đối tượng socket khi xảy ra ngoại lệ ngắt kết nối.
        :return: Tên username đã bị xóa nếu tìm thấy.
        """
        with self._lock:
            target_username = None
            for uname, sess in self._sessions.items():
                if sess.sock == sock:
                    target_username = uname
                    break
            if target_username:
                del self._sessions[target_username]
                logger.info(f"[-] Tự động giải phóng phiên của '{target_username}' do socket đóng.")
            return target_username

    def get_session(self, username: str) -> Optional[ClientSession]:
        """
        Lấy thông tin phiên của một user theo username.
        """
        with self._lock:
            return self._sessions.get(username)

    def update_last_seen(self, username: str) -> bool:
        """
        Cập nhật mốc thời gian nhận dữ liệu/heartbeat gần nhất của user.
        Đảm bảo an toàn luồng (Thread-safe).
        """
        with self._lock:
            sess = self._sessions.get(username)
            if sess:
                sess.last_seen_time = time.time()
                return True
            return False

    def get_stale_sessions(self, timeout_seconds: float) -> List[str]:
        """
        Tìm và trả về danh sách các username có thời gian không tương tác vượt quá timeout_seconds.
        (time.time() - last_seen_time > timeout_seconds).
        Đảm bảo an toàn luồng (Thread-safe).
        """
        now = time.time()
        with self._lock:
            return [
                uname
                for uname, sess in self._sessions.items()
                if (now - sess.last_seen_time) > timeout_seconds
            ]

    def set_udp_address(self, username: str, udp_addr: Tuple[str, int]) -> bool:
        """
        Ghi nhận địa chỉ UDP (IP, port) của Client cho luồng truyền file UDP.
        """
        with self._lock:
            sess = self._sessions.get(username)
            if sess:
                sess.udp_address = udp_addr
                logger.info(f"[UDP] Đã đăng ký địa chỉ UDP cho user '{username}': {udp_addr[0]}:{udp_addr[1]}")
                return True
        return False

    def get_udp_address(self, username: str) -> Optional[Tuple[str, int]]:
        """
        Tra cứu địa chỉ UDP của Client theo username.
        """
        with self._lock:
            sess = self._sessions.get(username)
            return sess.udp_address if sess else None

    def get_all_users_info(self) -> List[Dict]:
        """
        Trả về danh sách tóm tắt tất cả người dùng đang online (User Discovery).
        """
        with self._lock:
            return [
                {
                    "username": sess.username,
                    "ip": sess.ip,
                    "port": sess.port,
                    "login_time": sess.login_time,
                }
                for sess in self._sessions.values()
            ]

    def broadcast(
        self,
        msg_type: MessageType,
        data: any,
        exclude_username: Optional[str] = None,
    ) -> int:
        """
        Gửi một thông điệp đến tất cả các Client đang online (Milestone 5 - Broadcast).
        :param exclude_username: Không gửi cho user này (thường là người gửi gốc).
        :return: Số lượng Client đã nhận thành công.
        """
        with self._lock:
            targets = [
                (uname, sess.sock)
                for uname, sess in self._sessions.items()
                if uname != exclude_username
            ]

        success_count = 0
        dead_users = []
        for uname, sock in targets:
            ok = send_packet(sock, msg_type, data)
            if ok:
                success_count += 1
            else:
                dead_users.append(uname)

        # Tự động dọn dẹp các client bị ngắt kết nối trong lúc broadcast
        for uname in dead_users:
            self.remove_session(uname)

        return success_count

    def unicast(self, target_username: str, msg_type: MessageType, data: any) -> bool:
        """
        Gửi một thông điệp riêng biệt đến một Client cụ thể (Milestone 5 - Unicast).
        """
        with self._lock:
            session = self._sessions.get(target_username)

        if not session:
            return False

        ok = send_packet(session.sock, msg_type, data)
        if not ok:
            self.remove_session(target_username)
            return False
        return True
