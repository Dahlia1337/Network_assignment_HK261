"""
Module core_client: Quản lý socket TCP Client kết nối đến Server,
chạy luồng nền lắng nghe gói tin và phân phối sự kiện (Event-driven Architecture).
"""

import hashlib
import logging
import os
import socket
import threading
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

from common.constants import (
    DEFAULT_HOST,
    DEFAULT_TCP_PORT,
    DEFAULT_UDP_PORT,
    DEFAULT_UDP_FILE_PORT,
    HEARTBEAT_INTERVAL,
    HEARTBEAT_TIMEOUT,
    SOCKET_RECV_BUFFER_SIZE,
    UDP_ACK_TIMEOUT,
    UDP_CHUNK_SIZE,
    UDP_MAX_RETRIES,
    UDP_WINDOW_SIZE,
)
from common.message_types import MessageType
from common.protocol import (
    Packet,
    UDPFilePacket,
    pack_packet,
    pack_udp_packet,
    receive_packet,
    send_packet,
    send_udp_file_packet,
    send_udp_packet,
    unpack_packet,
    unpack_udp_packet,
)
from client.file_transfer import FileReceiver, FileSender

logger = logging.getLogger("CoreClient")


class CollaborationClient:
    """
    Client kết nối máy chủ phân tán:
    - Xử lý gửi tin nhắn, gửi/nhận file qua UDP Streaming ARQ.
    - Chạy luồng nền (Background Listener) nhận dữ liệu thời gian thực.
    """

    def __init__(self):
        self.sock: Optional[socket.socket] = None
        self.username: Optional[str] = None
        self.is_connected = False
        self.is_authenticated = False

        self._listener_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._last_pong_time: float = 0.0
        self._disconnect_lock = threading.Lock()

        # Socket và địa chỉ UDP Server cho Heartbeat Keep-Alive
        self.server_host: str = DEFAULT_HOST
        self.server_port: int = DEFAULT_TCP_PORT
        self.server_udp_addr: Optional[Tuple[str, int]] = None
        self.udp_sock: Optional[socket.socket] = None
        self._udp_heartbeat_thread: Optional[threading.Thread] = None

        # Socket và luồng lắng nghe dữ liệu UDP File Streaming
        self.udp_file_sock: Optional[socket.socket] = None
        self.server_udp_file_addr: Optional[Tuple[str, int]] = None
        self._udp_listener_thread: Optional[threading.Thread] = None
        self._active_senders_acks: Dict[str, Set[int]] = {}
        self._ack_events: Dict[str, threading.Event] = {}
        self._file_targets: Dict[str, str] = {}

        # Trạng thái các phiên file đang xử lý
        self._active_receivers: Dict[str, FileReceiver] = {}
        self._pending_send_files: Dict[str, str] = {}  # transfer_id -> local_filepath

        # Callback hooks để cập nhật giao diện (UI)
        self.on_register_result: Optional[Callable[[bool, str], None]] = None
        self.on_login_result: Optional[Callable[[bool, str], None]] = None
        self.on_user_list_updated: Optional[Callable[[List[dict]], None]] = None
        self.on_user_joined: Optional[Callable[[str], None]] = None
        self.on_user_left: Optional[Callable[[str], None]] = None
        self.on_message_received: Optional[Callable] = None  # (sender, text, is_private, timestamp)
        self.on_chat_history_received: Optional[Callable[[str, List[dict]], None]] = None  # (target, messages)
        self.on_file_request_received: Optional[Callable[[str, str, int, str], None]] = None  # (sender, name, size, id)
        self.on_file_progress: Optional[Callable[[str, float, bool], None]] = None  # (id, percent, is_upload)
        self.on_file_complete: Optional[Callable[..., None]] = None  # (id, name, path, stats)
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_disconnected: Optional[Callable[[], None]] = None
        self.cached_users: List[dict] = []

    def _hash_password(self, password: str) -> str:
        """
        Băm mật khẩu dạng plaintext sang chuỗi SHA-256 hex digest.
        """
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    def discover_server(self, timeout: float = 3.0, udp_port: int = DEFAULT_UDP_PORT) -> Tuple[Optional[str], Optional[int]]:
        """
        Tự động khám phá máy chủ (Auto-Discovery) qua UDP Broadcast trong mạng LAN.
        Gửi gói tin 'DISCOVER_COLLAB_SERVER' tới cổng DEFAULT_UDP_PORT (8889)
        và chờ phản hồi 'COLLAB_SERVER_OFFER:<tcp_port>'.

        :param timeout: Thời gian tối đa chờ phản hồi (giây).
        :param udp_port: Cổng UDP Discovery của máy chủ (mặc định: DEFAULT_UDP_PORT).
        :return: Tuple (server_ip, server_tcp_port) hoặc (None, None) nếu thất bại / timeout.
        """
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(timeout)

            logger.info(f"[UDP Discovery] Đang gửi broadcast tìm máy chủ trên cổng {udp_port} (timeout={timeout}s)...")
            message = "DISCOVER_COLLAB_SERVER".encode("utf-8")
            sock.sendto(message, ("<broadcast>", udp_port))

            start_time = time.time()
            while True:
                remaining = timeout - (time.time() - start_time)
                if remaining <= 0:
                    break
                sock.settimeout(remaining)
                data, addr = sock.recvfrom(1024)
                payload = data.decode("utf-8", errors="ignore").strip()

                if payload.startswith("COLLAB_SERVER_OFFER:"):
                    server_ip = addr[0]
                    server_tcp_port = int(payload.split(":")[1])
                    logger.info(f"[UDP Discovery] Phát hiện máy chủ tại {server_ip}:{server_tcp_port}")
                    return server_ip, server_tcp_port

        except (socket.timeout, OSError) as e:
            logger.debug(f"[UDP Discovery] Không nhận được phản hồi qua UDP Broadcast ({e})")
        except Exception as e:
            logger.warning(f"[UDP Discovery] Lỗi trong quá trình khám phá máy chủ: {e}")
        finally:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass

        return None, None

    def connect(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_TCP_PORT,
        udp_port: int = DEFAULT_UDP_PORT,
        udp_file_port: int = DEFAULT_UDP_FILE_PORT,
    ) -> bool:
        """
        Thiết lập kết nối TCP Socket, khởi tạo UDP Heartbeat Socket và UDP File Socket.
        """
        try:
            self.server_host = host
            self.server_port = port
            self.server_udp_addr = (host, udp_port)

            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((host, port))
            self.is_connected = True
            logger.info(f"[*] Kết nối TCP thành công đến Server {host}:{port}")

            # Khởi tạo UDP Socket cho Heartbeat & giao tiếp UDP
            self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_sock.bind(("", 0))
            local_udp_port = self.udp_sock.getsockname()[1]
            logger.info(f"[UDP] Khởi tạo UDP heartbeat socket tại cổng local {local_udp_port}")

            # Khởi động luồng nền lắng nghe phản hồi UDP Heartbeat PONG
            self._udp_heartbeat_thread = threading.Thread(target=self._udp_heartbeat_listen_loop, daemon=True)
            self._udp_heartbeat_thread.start()

            # Khởi tạo UDP Socket cho File Transfer (hệ điều hành tự gán cổng ephemeral)
            self.server_udp_file_addr = (host, udp_file_port)
            self.udp_file_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_file_sock.bind(("", 0))
            local_file_port = self.udp_file_sock.getsockname()[1]
            logger.info(f"[UDP] Khởi tạo UDP file socket tại cổng local {local_file_port}")

            # Khởi động luồng nền lắng nghe UDP File streaming
            self._udp_listener_thread = threading.Thread(target=self._udp_listen_loop, daemon=True)
            self._udp_listener_thread.start()

            # Khởi động luồng nền lắng nghe gói tin TCP từ Server
            self._listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._listener_thread.start()
            return True
        except Exception as e:
            logger.error(f"[X] Không thể kết nối đến {host}:{port}: {e}")
            if self.on_error:
                self.on_error(f"Không thể kết nối đến Server: {e}")
            return False

    def register(self, username: str, password: str) -> bool:
        """
        Gửi yêu cầu đăng ký tài khoản mới lên Server.
        """
        if not self.is_connected or not self.sock:
            return False
        password_hash = self._hash_password(password)
        payload = {"username": username, "password_hash": password_hash}
        return send_packet(self.sock, MessageType.REGISTER_REQ, payload)

    def login(self, username: str, password: str) -> bool:
        """
        Gửi yêu cầu đăng nhập bằng username và password (Milestone 4 - Authentication).
        """
        if not self.is_connected or not self.sock:
            return False
        self.username = username
        password_hash = self._hash_password(password)
        payload = {"username": username, "password_hash": password_hash}
        return send_packet(self.sock, MessageType.AUTH_REQ, payload)

    def send_broadcast(self, text: str) -> bool:
        """
        Gửi tin nhắn phòng chat chung (Milestone 5 - Broadcast).
        """
        if not self.is_authenticated or not self.sock:
            return False
        return send_packet(self.sock, MessageType.MSG_BROADCAST, {"text": text})

    def send_unicast(self, target_user: str, text: str) -> bool:
        """
        Gửi tin nhắn riêng tư 1-1 (Milestone 5 - Unicast).
        """
        if not self.is_authenticated or not self.sock:
            return False
        return send_packet(self.sock, MessageType.MSG_UNICAST, {"target": target_user, "text": text})

    def refresh_user_list(self) -> bool:
        """
        Yêu cầu Server gửi danh sách user online mới nhất.
        """
        if not self.is_authenticated or not self.sock:
            return False
        return send_packet(self.sock, MessageType.USER_LIST_REQ, {})

    def request_chat_history(self, target: str) -> bool:
        """
        Yêu cầu Server gửi lại lịch sử tin nhắn của phòng/đoạn chat mục tiêu.
        :param target: '__BROADCAST__' hoặc tên username đối phương.
        """
        if not self.is_authenticated or not self.sock:
            return False
        return send_packet(self.sock, MessageType.CHAT_HISTORY_REQ, {"target": target})

    def send_file_request(self, target_user: str, filepath: str) -> bool:
        """
        Bắt đầu quy trình gửi file đến target_user (Milestone 6).
        """
        if not self.is_authenticated or not self.sock:
            return False
        if not os.path.exists(filepath):
            if self.on_error:
                self.on_error(f"Tệp không tồn tại: {filepath}")
            return False

        sender = FileSender(filepath)
        payload = {
            "target": target_user,
            "filename": sender.filename,
            "filesize": sender.filesize,
            "sha256": sender.sha256,
        }

        self._file_targets[sender.filename] = target_user
        self._pending_send_files[sender.filename] = filepath
        
        return send_packet(self.sock, MessageType.FILE_TRANSFER_REQ, payload)

    def respond_file_request(self, transfer_id: str, accept: bool, save_dir: str = "./downloads"):
        """
        Phản hồi chấp nhận hoặc từ chối nhận file.
        """
        if not self.sock:
            return
        msg_type = MessageType.FILE_TRANSFER_ACCEPT if accept else MessageType.FILE_TRANSFER_REJECT
        send_packet(self.sock, msg_type, {"transfer_id": transfer_id})

    def _listen_loop(self):
        """
        Vòng lặp chạy nền liên tục đọc gói tin từ Server.
        """
        try:
            while self.is_connected:
                packet = receive_packet(self.sock)
                if packet is None:
                    break
                self._handle_server_packet(packet)
        except Exception as e:
            logger.warning(f"[!] Mất kết nối từ Server: {e}")
        finally:
            self._handle_disconnect()

    def _handle_server_packet(self, packet: Packet):
        """
        Điều phối xử lý sự kiện dựa trên loại gói tin.
        """
        msg_type = packet.msg_type
        data = packet.data

        if msg_type == MessageType.REGISTER_SUCCESS:
            msg = data.get("message", "Đăng ký thành công") if isinstance(data, dict) else str(data)
            logger.info(f"[✓] {msg}")
            if self.on_register_result:
                self.on_register_result(True, msg)

        elif msg_type == MessageType.REGISTER_FAIL:
            reason = data.get("reason", "Đăng ký thất bại") if isinstance(data, dict) else str(data)
            logger.error(f"[X] Đăng ký thất bại: {reason}")
            if self.on_register_result:
                self.on_register_result(False, reason)

        elif msg_type == MessageType.AUTH_SUCCESS:
            self.is_authenticated = True
            logger.info("[✓] Đăng nhập thành công!")

            # Đăng ký UDP endpoint của Client với Server ngay sau khi xác thực thành công
            if self.udp_file_sock and self.server_udp_file_addr and self.username:
                send_udp_file_packet(
                    sock=self.udp_file_sock,
                    addr=self.server_udp_file_addr,
                    msg_type=MessageType.FILE_UDP_BIND,
                    transfer_id="",
                    chunk_index=0,
                    total_chunks=0,
                    raw_payload=self.username.encode("utf-8"),
                    encrypt=False,
                )
                logger.info(f"[UDP] Đã gửi gói định danh UDP tới Server {self.server_udp_file_addr}")

            # Khởi động luồng gửi Heartbeat (Keep-Alive) định kỳ qua UDP
            self._last_pong_time = time.time()
            if not self._heartbeat_thread or not self._heartbeat_thread.is_alive():
                self._heartbeat_thread = threading.Thread(target=self._heartbeat_worker, daemon=True)
                self._heartbeat_thread.start()
            if self.on_login_result:
                self.on_login_result(True, data.get("message", "Thành công") if isinstance(data, dict) else str(data))

        elif msg_type == MessageType.AUTH_FAIL:
            reason = data.get("reason", "Lỗi xác thực") if isinstance(data, dict) else str(data)
            logger.error(f"[X] Đăng nhập thất bại: {reason}")
            if self.on_login_result:
                self.on_login_result(False, reason)

        elif msg_type == MessageType.HEARTBEAT_PONG:
            self._last_pong_time = time.time()
            logger.debug(f"[Heartbeat] Nhận phản hồi PONG từ server lúc {self._last_pong_time:.2f}")

        elif msg_type == MessageType.USER_LIST_RESP:
            users = data.get("users", []) if isinstance(data, dict) else []
            self.cached_users = users
            if self.on_user_list_updated:
                self.on_user_list_updated(users)

        elif msg_type == MessageType.USER_JOIN_BROADCAST:
            joined_user = data.get("username") if isinstance(data, dict) else str(data)
            if self.on_user_joined:
                self.on_user_joined(joined_user)
            self.refresh_user_list()

        elif msg_type == MessageType.USER_LEAVE_BROADCAST:
            left_user = data.get("username") if isinstance(data, dict) else str(data)
            if self.on_user_left:
                self.on_user_left(left_user)
            self.refresh_user_list()

        elif msg_type == MessageType.MSG_BROADCAST:
            sender = data.get("sender", "Hệ thống")
            text = data.get("text", "")
            timestamp = data.get("timestamp") or time.strftime("%H:%M:%S")
            if self.on_message_received:
                try:
                    self.on_message_received(sender, text, False, timestamp)
                except TypeError:
                    self.on_message_received(sender, text, False)

        elif msg_type == MessageType.MSG_UNICAST:
            sender = data.get("sender", "Ẩn danh")
            text = data.get("text", "")
            timestamp = data.get("timestamp") or time.strftime("%H:%M:%S")
            if self.on_message_received:
                try:
                    self.on_message_received(sender, text, True, timestamp)
                except TypeError:
                    self.on_message_received(sender, text, True)

        elif msg_type == MessageType.CHAT_HISTORY_RESP:
            target = data.get("target", "") if isinstance(data, dict) else ""
            messages = data.get("messages", []) if isinstance(data, dict) else []
            if self.on_chat_history_received:
                self.on_chat_history_received(target, messages)

        elif msg_type == MessageType.FILE_TRANSFER_REQ:
            sender = data.get("sender")
            filename = data.get("filename")
            filesize = data.get("filesize", 0)
            transfer_id = data.get("transfer_id")
            sha256 = data.get("sha256")

            # Khởi tạo bộ nhận tạm thời
            save_dir = os.path.abspath("./downloads")
            self._active_receivers[transfer_id] = FileReceiver(save_dir, filename, filesize, sha256)

            if self.on_file_request_received:
                self.on_file_request_received(sender, filename, filesize, transfer_id)

        elif msg_type == MessageType.FILE_TRANSFER_ACCEPT:
            transfer_id = data.get("transfer_id")
            filename = data.get("filename")
            filepath = self._pending_send_files.get(filename)
            if filepath:
                # Kích hoạt luồng truyền file UDP Streaming Selective Repeat ARQ
                threading.Thread(target=self._upload_udp_worker, args=(transfer_id, filepath), daemon=True).start()

        elif msg_type == MessageType.FILE_TRANSFER_REJECT:
            reason = data.get("reason", "Người nhận đã từ chối nhận file.")
            if self.on_error:
                self.on_error(f"[File] {reason}")

        elif msg_type == MessageType.FILE_CHUNK_DATA:
            # Fallback tương thích ngược nếu còn gói TCP
            transfer_id = data.get("transfer_id")
            receiver = self._active_receivers.get(transfer_id)
            if receiver:
                percent = receiver.write_chunk(
                    chunk_index=data.get("chunk_index"),
                    total_chunks=data.get("total_chunks"),
                    data_b64=data.get("data_b64"),
                )
                if self.on_file_progress:
                    self.on_file_progress(transfer_id, percent, False)

        elif msg_type == MessageType.FILE_TRANSFER_COMPLETE:
            transfer_id = data.get("transfer_id")
           
            receiver = self._active_receivers.pop(transfer_id, None)
            if receiver:
                success, path_or_err = receiver.finalize_and_verify()
                if success:
                    if self.on_file_complete:
                        stats = {
                            "filesize": data.get("filesize", receiver.filesize),
                            "total_chunks": data.get("total_chunks", receiver.total_chunks),
                            "elapsed_time": data.get("elapsed_time", 0.0),
                            "is_upload": False,
                            "sender": data.get("sender", ""),
                        }
                        self.on_file_complete(transfer_id, os.path.basename(path_or_err), path_or_err, stats)
                else:
                    if self.on_error:
                        self.on_error(path_or_err)

        elif msg_type == MessageType.ERROR_RESP:
            err_msg = data.get("message", "Lỗi từ server") if isinstance(data, dict) else str(data)
            if self.on_error:
                self.on_error(err_msg)

    def _udp_listen_loop(self):
        """
        Vòng lặp nền lắng nghe dữ liệu file nhị phân và phản hồi ACK qua UDP.
        """
        while self.is_connected:
            try:
                if not self.udp_file_sock:
                    break
                data, addr = self.udp_file_sock.recvfrom(SOCKET_RECV_BUFFER_SIZE)
                if not data:
                    continue

                packet = unpack_udp_packet(data, decrypt=True)
                if not packet:
                    continue

                # 1. Tiếp nhận khối dữ liệu file từ Sender (chuyển tiếp qua Server)
                if packet.msg_type == MessageType.FILE_CHUNK_DATA:
                    transfer_id = packet.transfer_id

                    # Phản hồi ngay gói FILE_CHUNK_ACK về Server để chuyển tiếp tới Sender
                    send_udp_file_packet(
                        sock=self.udp_file_sock,
                        addr=self.server_udp_file_addr,
                        msg_type=MessageType.FILE_CHUNK_ACK,
                        transfer_id=transfer_id,
                        chunk_index=packet.chunk_index,
                        total_chunks=packet.total_chunks,
                        raw_payload=b"",
                        encrypt=False,
                    )

                    # Ghi và sắp xếp khối dữ liệu vào tệp tạm (.part)
                    receiver = self._active_receivers.get(transfer_id)
                    if receiver:
                        percent = receiver.write_raw_chunk(
                            chunk_index=packet.chunk_index,
                            total_chunks=packet.total_chunks,
                            raw_bytes=packet.raw_payload,
                        )
                        if self.on_file_progress:
                            self.on_file_progress(transfer_id, percent, False)

                # 2. Tiếp nhận gói xác nhận ACK từ Receiver (chuyển tiếp qua Server)
                elif packet.msg_type == MessageType.FILE_CHUNK_ACK:
                    transfer_id = packet.transfer_id
                    if transfer_id in self._active_senders_acks:
                        self._active_senders_acks[transfer_id].add(packet.chunk_index)
                        logger.debug(f"[UDP Sender] Đã nhận ACK cho Chunk #{packet.chunk_index} [ID: {transfer_id}]")
                        if transfer_id in self._ack_events:
                            self._ack_events[transfer_id].set()

            except OSError:
                break
            except Exception as e:
                logger.error(f"[UDP Listener] Ngoại lệ khi nhận gói tin UDP: {e}")

    def _upload_udp_worker(self, transfer_id: str, filepath: str):
        """
        Luồng phát file UDP Streaming với cơ chế bảo đảm tin cậy Selective Repeat Sliding Window ARQ.
        """
        try:
            start_time = time.time()
            sender = FileSender(filepath, chunk_size=UDP_CHUNK_SIZE)
            total_chunks = sender.total_chunks
            target_user = self._file_targets.get(sender.filename, "")
            logger.info(f"[UDP Sender] Bắt đầu truyền file '{sender.filename}' ({sender.filesize} bytes, {total_chunks} chunks) [ID: {transfer_id}]")

            self._active_senders_acks[transfer_id] = set()
            ack_event = threading.Event()
            self._ack_events[transfer_id] = ack_event

            window_size = UDP_WINDOW_SIZE
            base = 0
            next_seq = 0
            sent_times: Dict[int, float] = {}
            retry_counts: Dict[int, int] = {}
            chunk_cache: Dict[int, bytes] = {}

            while len(self._active_senders_acks[transfer_id]) < total_chunks and self.is_connected:
                # 1. Phát các chunk mới trong phạm vi cửa sổ trượt [base, base + window_size)
                while next_seq < base + window_size and next_seq < total_chunks:
                    raw_bytes = sender.get_chunk_bytes(next_seq)
                    chunk_cache[next_seq] = raw_bytes
                    send_udp_file_packet(
                        sock=self.udp_file_sock,
                        addr=self.server_udp_file_addr,
                        msg_type=MessageType.FILE_CHUNK_DATA,
                        transfer_id=transfer_id,
                        chunk_index=next_seq,
                        total_chunks=total_chunks,
                        raw_payload=raw_bytes,
                        encrypt=True,
                    )
                    sent_times[next_seq] = time.time()
                    retry_counts[next_seq] = 0
                    logger.debug(f"[UDP Sender] Đã gửi Chunk #{next_seq}/{total_chunks} [ID: {transfer_id}]")
                    next_seq += 1

                # 2. Kiểm tra timeout cho các chunk chưa được ACK trong cửa sổ hiện tại
                now = time.time()
                acked_set = self._active_senders_acks[transfer_id]
                for seq in range(base, min(next_seq, base + window_size)):
                    if seq not in acked_set:
                        if now - sent_times.get(seq, 0) > UDP_ACK_TIMEOUT:
                            current_retries = retry_counts.get(seq, 0)
                            if current_retries >= UDP_MAX_RETRIES:
                                err = f"Truyền file thất bại: Mất gói #{seq} sau {UDP_MAX_RETRIES} lần gửi lại."
                                logger.error(f"[UDP Sender] {err}")
                                if self.on_error:
                                    self.on_error(err)
                                return
                            # Gửi lại (Retransmit)
                            send_udp_file_packet(
                                sock=self.udp_file_sock,
                                addr=self.server_udp_file_addr,
                                msg_type=MessageType.FILE_CHUNK_DATA,
                                transfer_id=transfer_id,
                                chunk_index=seq,
                                total_chunks=total_chunks,
                                raw_payload=chunk_cache[seq],
                                encrypt=True,
                            )
                            sent_times[seq] = time.time()
                            retry_counts[seq] = current_retries + 1
                            logger.warning(f"[UDP Sender] Retransmit #{retry_counts[seq]} cho Chunk #{seq} [ID: {transfer_id}]")

                # 3. Trượt cửa sổ khi chunk nhỏ nhất (base) đã được xác nhận ACK
                while base in acked_set and base < total_chunks:
                    chunk_cache.pop(base, None)
                    sent_times.pop(base, None)
                    retry_counts.pop(base, None)
                    base += 1

                # 4. Cập nhật tiến độ giao diện
                percent = (len(acked_set) / total_chunks * 100.0) if total_chunks > 0 else 100.0
                if self.on_file_progress:
                    self.on_file_progress(transfer_id, percent, True)

                # Chờ sự kiện có ACK mới hoặc hết 10ms
                ack_event.wait(timeout=0.01)
                ack_event.clear()

            # 5. Dọn dẹp trạng thái phiên
            self._active_senders_acks.pop(transfer_id, None)
            self._ack_events.pop(transfer_id, None)

            # 6. Báo hoàn tất qua kênh TCP Control
            elapsed_time = round(time.time() - start_time, 2)
            if self.is_connected:
                send_packet(self.sock, MessageType.FILE_TRANSFER_COMPLETE, {
                    "transfer_id": transfer_id,
                    "target": target_user,
                    "filename": sender.filename,
                    "filesize": sender.filesize,
                    "total_chunks": total_chunks,
                    "elapsed_time": elapsed_time
                })
                logger.info(f"[✓] Hoàn tất 100% truyền file '{sender.filename}' [ID: {transfer_id}]")
                
                # 7. Xóa file tạm đi
                upload_dir = os.path.abspath("./uploads")
                if os.path.abspath(filepath).startswith(upload_dir) and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                        logger.info(f"[Cleanup] Đã tự động xóa file tạm sau khi gửi xong: {filepath}")
                    except Exception as e:
                        logger.warning(f"[Cleanup] Không thể xóa file tạm: {e}")
                
                if self.on_file_complete:
                    stats = {
                        "filesize": sender.filesize,
                        "total_chunks": total_chunks,
                        "elapsed_time": elapsed_time,
                        "is_upload": True,
                        "target": target_user,
                    }
                    self.on_file_complete(transfer_id, sender.filename, filepath, stats)

        except Exception as e:
            logger.error(f"[X] Lỗi trong luồng upload UDP file ({filepath}): {e}", exc_info=True)
            if self.on_error:
                self.on_error(f"Lỗi truyền file UDP: {e}")

    def _udp_heartbeat_listen_loop(self):
        """
        Vòng lặp nền lắng nghe phản hồi HEARTBEAT_PONG từ Server qua UDP.
        """
        while self.is_connected:
            try:
                if not self.udp_sock:
                    break
                data, addr = self.udp_sock.recvfrom(SOCKET_RECV_BUFFER_SIZE)
                if not data:
                    continue
                packet = unpack_packet(data)
                if packet and packet.msg_type == MessageType.HEARTBEAT_PONG:
                    self._last_pong_time = time.time()
                    logger.debug(f"[Heartbeat UDP] Nhận phản hồi PONG từ {addr} lúc {self._last_pong_time:.2f}")
            except OSError:
                break
            except Exception as e:
                logger.error(f"[UDP Heartbeat Listener] Ngoại lệ khi nhận gói tin UDP: {e}")

    def _heartbeat_worker(self):
        """
        Luồng gửi gói tin HEARTBEAT_PING định kỳ qua UDP tới Server (Milestone 7).
        """
        logger.info(f"[*] Bắt đầu luồng UDP Heartbeat (chu kỳ {HEARTBEAT_INTERVAL}s, timeout {HEARTBEAT_TIMEOUT}s)")
        self._last_pong_time = time.time()

        while self.is_connected and self.is_authenticated:
            try:
                if self.udp_sock and self.server_udp_addr and self.username:
                    send_udp_packet(
                        sock=self.udp_sock,
                        addr=self.server_udp_addr,
                        msg_type=MessageType.HEARTBEAT_PING,
                        data={"username": self.username},
                    )
                    logger.debug(f"[Heartbeat UDP] Đã gửi PING cho user '{self.username}' tới {self.server_udp_addr}")
            except Exception as e:
                logger.warning(f"[Heartbeat UDP] Ngoại lệ khi gửi UDP PING: {e}")

            sleep_elapsed = 0.0
            while sleep_elapsed < HEARTBEAT_INTERVAL and self.is_connected and self.is_authenticated:
                time.sleep(0.5)
                sleep_elapsed += 0.5
                if time.time() - self._last_pong_time > HEARTBEAT_TIMEOUT:
                    logger.error(
                        f"[Heartbeat UDP] Mất kết nối tới Server: Quá {HEARTBEAT_TIMEOUT}s "
                        f"không nhận được UDP PONG!"
                    )
                    if self.on_error:
                        try:
                            self.on_error("Mất kết nối máy chủ (Heartbeat Timeout)!")
                        except Exception:
                            pass
                    self._handle_disconnect()
                    return

    def _handle_disconnect(self):
        """
        Dọn dẹp tài nguyên khi ngắt kết nối.
        """
        with self._disconnect_lock:
            if not self.is_connected and not self.is_authenticated:
                return
            self.is_connected = False
            self.is_authenticated = False

        try:
            if self.sock:
                self.sock.close()
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
        if self.on_disconnected:
            try:
                self.on_disconnected()
            except Exception as e:
                logger.warning(f"Lỗi khi gọi callback on_disconnected: {e}")

    def disconnect(self):
        """
        Thoát êm theo yêu cầu người dùng (Milestone 7).
        """
        if self.sock and self.is_connected:
            try:
                send_packet(self.sock, MessageType.DISCONNECT_REQ, {})
            except Exception:
                pass
        self._handle_disconnect()