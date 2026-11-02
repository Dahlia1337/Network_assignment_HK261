"""
Module file_router: Quản lý và chuyển tiếp các phiên truyền nhận tệp giữa các Client.
Hiện thực hóa Milestone 6 - Reliable File Transfer (Phía máy chủ điều phối).
"""

import logging
import socket
import threading
import uuid
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from common.message_types import MessageType
from common.protocol import unpack_udp_packet
from server.session_manager import SessionManager

logger = logging.getLogger("FileRouter")


@dataclass
class FileTransferSession:
    """
    Thông tin trạng thái của một phiên truyền file đang diễn ra giữa 2 peer.
    """
    transfer_id: str
    sender: str
    receiver: str
    filename: str
    filesize: int
    sha256_checksum: str
    status: str  # 'PENDING', 'ACCEPTED', 'TRANSFERRING', 'COMPLETED', 'REJECTED'


class FileRouter:
    """
    Bộ định tuyến tệp tin cậy: Nhận chunk từ Sender và chuyển tiếp ngay tới Receiver.
    """

    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager
        self._transfers: Dict[str, FileTransferSession] = {}
        self._lock = threading.Lock()

    def create_transfer_request(
        self,
        sender: str,
        receiver: str,
        filename: str,
        filesize: int,
        sha256: str,
    ) -> Optional[str]:
        """
        Khởi tạo yêu cầu truyền file mới và chuyển tiếp đến Receiver.
        :return: transfer_id nếu tạo thành công, None nếu Receiver không online.
        """
        receiver_session = self.session_manager.get_session(receiver)
        if not receiver_session:
            return None

        transfer_id = str(uuid.uuid4())[:8]
        transfer = FileTransferSession(
            transfer_id=transfer_id,
            sender=sender,
            receiver=receiver,
            filename=filename,
            filesize=filesize,
            sha256_checksum=sha256,
            status='PENDING',
        )

        with self._lock:
            self._transfers[transfer_id] = transfer

        # Gửi thông điệp đề nghị nhận file sang cho Receiver
        req_payload = {
            "transfer_id": transfer_id,
            "sender": sender,
            "filename": filename,
            "filesize": filesize,
            "sha256": sha256,
        }
        ok = self.session_manager.unicast(receiver, MessageType.FILE_TRANSFER_REQ, req_payload)
        if not ok:
            with self._lock:
                self._transfers.pop(transfer_id, None)
            return None

        logger.info(f"[File] Khởi tạo phiên truyền '{filename}' ({filesize} bytes) từ {sender} -> {receiver} [ID: {transfer_id}]")
        return transfer_id

    def handle_transfer_response(self, transfer_id: str, receiver: str, accepted: bool):
        """
            Xử lý phản hồi chấp nhận hoặc từ chối từ người nhận.
        """
        with self._lock:
            transfer = self._transfers.get(transfer_id)
            if not transfer or transfer.receiver != receiver:
                return

            transfer.status = 'ACCEPTED' if accepted else 'REJECTED'

        # Chuyển tiếp phản hồi ngược về cho Sender
        resp_type = MessageType.FILE_TRANSFER_ACCEPT if accepted else MessageType.FILE_TRANSFER_REJECT
        resp_payload = {
            "transfer_id": transfer_id,
            "receiver": receiver,
            "filename": transfer.filename,
        }
        self.session_manager.unicast(transfer.sender, resp_type, resp_payload)

        if not accepted:
            with self._lock:
                self._transfers.pop(transfer_id, None)
            logger.info(f"[File] Người nhận {receiver} đã từ chối nhận file [ID: {transfer_id}]")

    def route_chunk(self, transfer_id: str, sender: str, chunk_payload: dict) -> bool:
        """
        Chuyển tiếp trực tiếp khối dữ liệu chunk đến Receiver (TCP legacy fallback).
        """
        with self._lock:
            transfer = self._transfers.get(transfer_id)
            if not transfer or transfer.sender != sender:
                return False

        # Đẩy chunk đến socket của người nhận
        return self.session_manager.unicast(transfer.receiver, MessageType.FILE_CHUNK_DATA, chunk_payload)

    def route_udp_chunk(self, raw_datagram: bytes, udp_sock: socket.socket, src_addr: Tuple[str, int]) -> bool:
        """
        Tiếp nhận datagram UDP từ socket Server, định tuyến không lưu đĩa:
        - FILE_UDP_BIND: Đăng ký địa chỉ UDP của Client vào SessionManager.
        - FILE_CHUNK_DATA: Định tuyến datagram trực tiếp sang địa chỉ UDP của Receiver.
        - FILE_CHUNK_ACK: Chuyển tiếp xác nhận ACK trực tiếp sang địa chỉ UDP của Sender.
        """
        packet = unpack_udp_packet(raw_datagram, decrypt=False)
        if not packet:
            return False

        # 1. Gói tin định danh cổng UDP của Client
        if packet.msg_type == MessageType.FILE_UDP_BIND:
            username = packet.raw_payload.decode("utf-8", errors="ignore").strip()
            if username:
                self.session_manager.set_udp_address(username, src_addr)
                logger.info(f"[UDP Router] Ghi nhận UDP endpoint của '{username}' tại {src_addr[0]}:{src_addr[1]}")
                return True
            return False

        transfer_id = packet.transfer_id
        with self._lock:
            transfer = self._transfers.get(transfer_id)

        if not transfer:
            logger.debug(f"[UDP Router] Không tìm thấy phiên transfer_id '{transfer_id}'")
            return False

        # 2. Định tuyến gói tin dữ liệu file từ Sender -> Receiver
        if packet.msg_type == MessageType.FILE_CHUNK_DATA:
            receiver_addr = self.session_manager.get_udp_address(transfer.receiver)
            if not receiver_addr:
                logger.warning(f"[UDP Router] Chưa có địa chỉ UDP của Receiver '{transfer.receiver}' để chuyển tiếp chunk #{packet.chunk_index}")
                return False
            try:
                udp_sock.sendto(raw_datagram, receiver_addr)
                logger.debug(f"[UDP Router] Đã route Chunk #{packet.chunk_index} ({transfer_id}) -> {transfer.receiver} tại {receiver_addr}")
                return True
            except Exception as e:
                logger.error(f"[UDP Router] Lỗi sendto chunk tới {receiver_addr}: {e}")
                return False

        # 3. Định tuyến gói tin ACK từ Receiver -> Sender
        elif packet.msg_type == MessageType.FILE_CHUNK_ACK:
            sender_addr = self.session_manager.get_udp_address(transfer.sender)
            if not sender_addr:
                logger.warning(f"[UDP Router] Chưa có địa chỉ UDP của Sender '{transfer.sender}' để chuyển tiếp ACK #{packet.chunk_index}")
                return False
            try:
                udp_sock.sendto(raw_datagram, sender_addr)
                logger.debug(f"[UDP Router] Đã route ACK #{packet.chunk_index} ({transfer_id}) -> {transfer.sender} tại {sender_addr}")
                return True
            except Exception as e:
                logger.error(f"[UDP Router] Lỗi sendto ACK tới {sender_addr}: {e}")
                return False

        return False

    def complete_transfer(self, transfer_id: str, sender: str):
        """
        Đánh dấu hoàn tất phiên truyền tệp và giải phóng phiên.
        """
        with self._lock:
            transfer = self._transfers.pop(transfer_id, None)

        if transfer:
            self.session_manager.unicast(
                transfer.receiver,
                MessageType.FILE_TRANSFER_COMPLETE,
                {"transfer_id": transfer_id, "filename": transfer.filename, "sha256": transfer.sha256_checksum},
            )
            logger.info(f"[File] Hoàn tất thành công truyền file '{transfer.filename}' [ID: {transfer_id}]")
