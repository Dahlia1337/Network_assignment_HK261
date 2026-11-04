"""
Module client_handler: Luồng chuyên trách phục vụ một Client kết nối.
Hiện thực hóa Milestone 3 (Concurrency), Milestone 5 (Routing), Milestone 7 (Resilience).
"""

import logging
import socket
import threading
import time
from typing import Optional, Tuple

from common.message_types import MessageType
from common.protocol import Packet, receive_packet, send_packet
from server.chat_history import BROADCAST_TARGET, ChatHistoryManager
from server.file_router import FileRouter
from server.session_manager import SessionManager
from server.user_manager import UserManager

logger = logging.getLogger("ClientHandler")


class ClientHandler(threading.Thread):
    """
    Luồng độc lập phụ trách lắng nghe và thông dịch toàn bộ gói tin từ 1 Client.
    Không bao giờ block các Client khác (Đạt yêu cầu Concurrency 10-20 clients).
    """

    def __init__(
        self,
        sock: socket.socket,
        address: Tuple[str, int],
        session_manager: SessionManager,
        user_manager: UserManager,
        file_router: FileRouter,
        chat_history: Optional[ChatHistoryManager] = None,
    ):
        super().__init__(daemon=True)
        self.sock = sock
        self.address = address
        self.session_manager = session_manager
        self.user_manager = user_manager
        self.file_router = file_router
        self.chat_history = chat_history
        self.username: Optional[str] = None
        self.is_running = True

    def run(self):
        """
        Vòng lặp chính tiếp nhận và xử lý gói tin.
        Bao bọc trong khối try/except toàn diện để chống sập server (Network Resilience - Step 7).
        """
        logger.info(f"[*] Bắt đầu phục vụ kết nối mới từ {self.address[0]}:{self.address[1]}")
        try:
            while self.is_running:
                packet = receive_packet(self.sock)
                if packet is None:
                    # Client đã ngắt kết nối (EOF hoặc đứt cáp)
                    break
                self._dispatch_packet(packet)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as e:
            logger.warning(f"[!] Mất kết nối bất ngờ từ {self.username or self.address}: {e}")
        except Exception as e:
            logger.error(f"[X] Lỗi xử lý ngoại lệ ClientHandler ({self.username}): {e}", exc_info=True)
        finally:
            self._cleanup()

    def _dispatch_packet(self, packet: Packet):
        """
        Phân loại và điều phối xử lý theo loại thông điệp (Message Types).
        """
        msg_type = packet.msg_type
        data = packet.data

        if msg_type == MessageType.REGISTER_REQ:
            self._handle_register(data)
        elif msg_type == MessageType.AUTH_REQ:
            self._handle_auth(data)
        elif not self.username:
            # Chưa xác thực mà gửi bản tin khác -> Từ chối
            send_packet(self.sock, MessageType.AUTH_FAIL, {"reason": "Vui lòng đăng nhập trước!"})
        else:
            # Ghi nhận thời gian tương tác gần nhất của user
            self.session_manager.update_last_seen(self.username)

            if msg_type == MessageType.USER_LIST_REQ:
                self._handle_user_list()
            elif msg_type == MessageType.MSG_BROADCAST:
                self._handle_broadcast_msg(data)
            elif msg_type == MessageType.MSG_UNICAST:
                self._handle_unicast_msg(data)
            elif msg_type == MessageType.CHAT_HISTORY_REQ:
                self._handle_chat_history_req(data)
            elif msg_type == MessageType.FILE_TRANSFER_REQ:
                self._handle_file_req(data)
            elif msg_type in (MessageType.FILE_TRANSFER_ACCEPT, MessageType.FILE_TRANSFER_REJECT):
                self._handle_file_resp(msg_type, data)
            elif msg_type == MessageType.FILE_CHUNK_DATA:
                self._handle_file_chunk(data)
            elif msg_type == MessageType.FILE_TRANSFER_COMPLETE:
                self._handle_file_complete(data)
            elif msg_type == MessageType.DISCONNECT_REQ:
                self.is_running = False

    def _handle_register(self, data: any):
        """
        Xử lý đăng ký tài khoản mới.
        """
        if not isinstance(data, dict):
            send_packet(self.sock, MessageType.REGISTER_FAIL, {"reason": "Dữ liệu đăng ký không hợp lệ!"})
            return

        username = data.get("username", "").strip()
        password_hash = data.get("password_hash", "").strip()

        if not username or not password_hash:
            send_packet(self.sock, MessageType.REGISTER_FAIL, {"reason": "Tên đăng nhập và mật khẩu không được rỗng!"})
            return

        success, message = self.user_manager.register_user(username, password_hash)
        if success:
            send_packet(self.sock, MessageType.REGISTER_SUCCESS, {"message": message, "username": username})
        else:
            send_packet(self.sock, MessageType.REGISTER_FAIL, {"reason": message})

    def _handle_auth(self, data: any):
        """
        Xử lý đăng nhập (Milestone 4).
        """
        if not isinstance(data, dict):
            send_packet(self.sock, MessageType.AUTH_FAIL, {"reason": "Dữ liệu đăng nhập không hợp lệ!"})
            return

        username = data.get("username", "").strip()
        password_hash = data.get("password_hash", "").strip()

        if not username or not password_hash:
            send_packet(self.sock, MessageType.AUTH_FAIL, {"reason": "Tên đăng nhập và mật khẩu không được rỗng!"})
            return

        # 1. Đối soát tài khoản và mật khẩu từ UserManager
        auth_success, auth_msg = self.user_manager.authenticate_user(username, password_hash)
        if not auth_success:
            send_packet(self.sock, MessageType.AUTH_FAIL, {"reason": auth_msg})
            return

        # 2. Kiểm tra tài khoản đã đăng nhập ở nơi khác hay chưa
        if self.session_manager.get_session(username) is not None:
            send_packet(self.sock, MessageType.AUTH_FAIL, {"reason": f"Tài khoản '{username}' đang đăng nhập ở thiết bị khác!"})
            return

        # 3. Tạo phiên đăng nhập mới
        success = self.session_manager.add_session(username, self.sock, self.address)
        if success:
            self.username = username
            send_packet(self.sock, MessageType.AUTH_SUCCESS, {
                "message": f"Chào mừng {username} đến với hệ thống!",
                "username": username,
            })
            # Gửi danh sách online cập nhật cho chính user
            self._handle_user_list()
            # Báo cho toàn bộ các Client khác biết có người mới vào
            self.session_manager.broadcast(
                MessageType.USER_JOIN_BROADCAST,
                {"username": username, "ip": self.address[0], "port": self.address[1]},
                exclude_username=username,
            )
        else:
            send_packet(self.sock, MessageType.AUTH_FAIL, {"reason": f"Tên '{username}' đã được sử dụng!"})

    def _handle_user_list(self):
        """
        Gửi danh sách tất cả các user đang online cho Client.
        """
        users = self.session_manager.get_all_users_info()
        send_packet(self.sock, MessageType.USER_LIST_RESP, {"users": users})

    def _handle_broadcast_msg(self, data: any):
        """
        Định tuyến tin nhắn phòng chung (Milestone 5 - Broadcast).
        """
        text = data.get("text", "") if isinstance(data, dict) else str(data)
        timestamp = time.strftime("%H:%M:%S")
        if self.chat_history:
            self.chat_history.add_broadcast_message(self.username, text, timestamp)

        payload = {
            "sender": self.username,
            "text": text,
            "timestamp": timestamp,
        }
        # Phát tán đến toàn bộ các client khác
        self.session_manager.broadcast(MessageType.MSG_BROADCAST, payload, exclude_username=self.username)

    def _handle_unicast_msg(self, data: any):
        """
        Định tuyến tin nhắn riêng 1-1 (Milestone 5 - Unicast).
        """
        if not isinstance(data, dict):
            return
        target = data.get("target")
        text = data.get("text", "")
        if not target:
            return

        timestamp = time.strftime("%H:%M:%S")
        if self.chat_history:
            self.chat_history.add_direct_message(self.username, target, text, timestamp)

        payload = {
            "sender": self.username,
            "target": target,
            "text": text,
            "timestamp": timestamp,
        }
        success = self.session_manager.unicast(target, MessageType.MSG_UNICAST, payload)
        if not success:
            send_packet(self.sock, MessageType.ERROR_RESP, {"message": f"Người dùng '{target}' hiện không trực tuyến."})

    def _handle_chat_history_req(self, data: any):
        if not isinstance(data, dict):
            return
        target = data.get("target", BROADCAST_TARGET)
        # Phòng thủ: nếu client gửi cả dict chứa username
        if isinstance(target, dict):
            target = target.get("username", BROADCAST_TARGET)
        if not isinstance(target, str):
            target = str(target)

        messages = []
        if self.chat_history:
            messages = self.chat_history.get_history(self.username, target)

        send_packet(self.sock, MessageType.CHAT_HISTORY_RESP, {
            "target": target,
            "messages": messages,
        })

    def _handle_file_req(self, data: any):
        """
        Xử lý yêu cầu truyền file sang một Client khác (Milestone 6).
        """
        if not isinstance(data, dict):
            return
        receiver = data.get("target")
        filename = data.get("filename")
        filesize = data.get("filesize", 0)
        sha256 = data.get("sha256", "")

        transfer_id = self.file_router.create_transfer_request(
            sender=self.username,
            receiver=receiver,
            filename=filename,
            filesize=filesize,
            sha256=sha256,
        )
        if not transfer_id:
            send_packet(self.sock, MessageType.FILE_TRANSFER_REJECT, {
                "reason": f"Không thể kết nối tới người nhận '{receiver}'.",
                "filename": filename,
            })

    def _handle_file_resp(self, msg_type: MessageType, data: any):
        """
        Xử lý phản hồi chấp nhận/từ chối nhận file từ Receiver.
        """
        if not isinstance(data, dict):
            return
        transfer_id = data.get("transfer_id")
        accepted = (msg_type == MessageType.FILE_TRANSFER_ACCEPT)
        self.file_router.handle_transfer_response(transfer_id, self.username, accepted)

    def _handle_file_chunk(self, data: any):
        """
        Chuyển tiếp khối file (chunk) đến người nhận tương ứng.
        """
        if not isinstance(data, dict):
            return
        transfer_id = data.get("transfer_id")
        self.file_router.route_chunk(transfer_id, self.username, data)

    def _handle_file_complete(self, data: any):
        """
        Xử lý khi bên gửi đã đẩy xong toàn bộ chunks của file.
        """
        if not isinstance(data, dict):
            return
        transfer_id = data.get("transfer_id")
        target = data.get("target")
        filename = data.get("filename")
        filesize = data.get("filesize", 0)
        total_chunks = data.get("total_chunks", 0)
        elapsed_time = data.get("elapsed_time", 0.0)

        stats = {
            "total_chunks": total_chunks,
            "elapsed_time": elapsed_time,
            "filesize": filesize,
        }
        transfer = self.file_router.complete_transfer(transfer_id, self.username, stats=stats)

        receiver = target or (transfer.receiver if transfer else None)
        if receiver and self.chat_history:
            timestamp = time.strftime("%H:%M:%S")
            self.chat_history.add_file_message(
                sender=self.username,
                target=receiver,
                filename=filename or (transfer.filename if transfer else "unknown"),
                filesize=filesize or (transfer.filesize if transfer else 0),
                total_chunks=total_chunks,
                elapsed_time=elapsed_time,
                timestamp=timestamp
            )

    def _cleanup(self):
        """
        Dọn dẹp tài nguyên khi Client ngắt kết nối (Graceful Exit).
        """
        self.is_running = False
        try:
            self.sock.close()
        except Exception:
            pass

        if self.username:
            removed = self.session_manager.remove_session(self.username)
            if removed:
                # Thông báo cho toàn bộ các Client khác biết user này đã rời mạng
                self.session_manager.broadcast(
                    MessageType.USER_LEAVE_BROADCAST,
                    {"username": self.username},
                )
        logger.info(f"[-] Đã giải phóng hoàn tất luồng phục vụ Client: {self.username or self.address}")