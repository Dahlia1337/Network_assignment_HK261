"""
Module protocol: Hiện thực hóa kỹ thuật đóng khung gói tin (Length-Prefixed Framing)
và giải quyết triệt để vấn đề dính gói (Packet Sticking) & phân mảnh gói (Fragmentation).
(Đáp ứng Milestone 1 - Setup & Protocol Design).
"""

import json
import socket
import struct
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Union

from common.constants import (
    ENCODING,
    FLAG_ENCRYPTED,
    FLAG_PLAINTEXT,
    HEADER_FORMAT,
    HEADER_SIZE,
    MAGIC_NUMBER,
    PROTOCOL_VERSION,
    UDP_HEADER_FORMAT,
    UDP_HEADER_SIZE,
)
from common.message_types import MessageType
from common.security import default_security


@dataclass
class Packet:
    """
    Biểu diễn một gói tin tầng ứng dụng hoàn chỉnh.
    """
    magic: int
    version: int
    flags: int
    msg_type: MessageType
    reserved: int
    payload_length: int
    raw_payload: bytes
    data: Any  # Dữ liệu sau khi giải mã (Dict, Str hoặc Bytes)

    @property
    def is_encrypted(self) -> bool:
        return bool(self.flags & FLAG_ENCRYPTED)


def pack_packet(
    msg_type: Union[MessageType, int],
    data: Union[Dict, str, bytes] = None,
    encrypt: bool = True,
    security_service=default_security,
) -> bytes:
    """
    Đóng gói dữ liệu thành chuỗi byte tuân thủ cấu trúc Header 12 Bytes + Payload.

    :param msg_type: Loại thông điệp (MessageType enum hoặc int)
    :param data: Dữ liệu cần gửi (dict sẽ được json dump, str sẽ encode utf-8, bytes giữ nguyên)
    :param encrypt: Có mã hóa payload hay không (mặc định True theo yêu cầu bảo mật)
    :param security_service: Dịch vụ bảo mật dùng để mã hóa
    :return: Toàn bộ mảng byte sẵn sàng gửi qua socket
    """
    if data is None:
        raw_payload = b""
    elif isinstance(data, dict):
        raw_payload = json.dumps(data, ensure_ascii=False).encode(ENCODING)
    elif isinstance(data, str):
        raw_payload = data.encode(ENCODING)
    elif isinstance(data, bytes):
        raw_payload = data
    else:
        raise ValueError(f"Kiểu dữ liệu payload không hợp lệ: {type(data)}")

    flags = FLAG_PLAINTEXT
    if encrypt and raw_payload:
        raw_payload = security_service.encrypt(raw_payload)
        flags |= FLAG_ENCRYPTED

    payload_length = len(raw_payload)
    reserved = 0

    # Đóng gói Header 12 Bytes theo chuẩn Big-Endian: !HBBHHI
    header = struct.pack(
        HEADER_FORMAT,
        MAGIC_NUMBER,
        PROTOCOL_VERSION,
        flags,
        int(msg_type),
        reserved,
        payload_length,
    )

    return header + raw_payload


def read_exact(sock: socket.socket, num_bytes: int) -> Optional[bytes]:
    """
    Hàm đọc chính xác đúng `num_bytes` từ socket TCP stream.
    Nếu đối phương ngắt kết nối trước khi đọc đủ, trả về None.
    Đây là kỹ thuật cốt lõi để chống phân mảnh gói (Packet Fragmentation).
    """
    buffer = bytearray()
    while len(buffer) < num_bytes:
        try:
            chunk = sock.recv(num_bytes - len(buffer))
            if not chunk:
                # Đối phương đã đóng socket (EOF)
                return None
            buffer.extend(chunk)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            return None
    return bytes(buffer)


def receive_packet(
    sock: socket.socket,
    security_service=default_security,
) -> Optional[Packet]:
    """
    Đọc một gói tin hoàn chỉnh từ socket:
    1. Đọc đúng 12 bytes Header.
    2. Giải nén trường payload_length.
    3. Đọc đúng payload_length bytes của phần thân (Payload).
    4. Giải mã (nếu cờ FLAG_ENCRYPTED bật) và thông dịch dữ liệu (JSON/text/bytes).

    :return: Packet nếu thành công, None nếu kết nối bị ngắt hoặc lỗi gói tin.
    """
    header_bytes = read_exact(sock, HEADER_SIZE)
    if not header_bytes:
        return None

    magic, version, flags, msg_type_raw, reserved, payload_length = struct.unpack(
        HEADER_FORMAT, header_bytes
    )

    # Kiểm tra Magic Number để phát hiện gói tin rác/không đúng chuẩn
    if magic != MAGIC_NUMBER:
        raise ValueError(f"Gói tin không hợp lệ: Magic = {hex(magic)}, kỳ vọng {hex(MAGIC_NUMBER)}")

    raw_payload = b""
    if payload_length > 0:
        raw_payload = read_exact(sock, payload_length)
        if raw_payload is None:
            return None

    # Xử lý giải mã nếu cờ mã hóa được kích hoạt
    decrypted_bytes = raw_payload
    if (flags & FLAG_ENCRYPTED) and raw_payload:
        decrypted_bytes = security_service.decrypt(raw_payload)

    # Thông dịch dữ liệu (Data Deserialization)
    parsed_data = decrypted_bytes
    if decrypted_bytes:
        try:
            # Thử parse JSON
            text = decrypted_bytes.decode(ENCODING)
            try:
                parsed_data = json.loads(text)
            except json.JSONDecodeError:
                parsed_data = text
        except UnicodeDecodeError:
            # Dữ liệu nhị phân nguyên bản (như file chunks)
            parsed_data = decrypted_bytes

    try:
        msg_type_enum = MessageType(msg_type_raw)
    except ValueError:
        msg_type_enum = msg_type_raw

    return Packet(
        magic=magic,
        version=version,
        flags=flags,
        msg_type=msg_type_enum,
        reserved=reserved,
        payload_length=payload_length,
        raw_payload=raw_payload,
        data=parsed_data,
    )


def send_packet(
    sock: socket.socket,
    msg_type: Union[MessageType, int],
    data: Union[Dict, str, bytes] = None,
    encrypt: bool = True,
    security_service=default_security,
) -> bool:
    """
    Đóng gói và gửi an toàn qua socket bằng sendall().
    :return: True nếu gửi thành công, False nếu kết nối đã bị đóng.
    """
    packet_bytes = pack_packet(msg_type, data, encrypt=encrypt, security_service=security_service)
    try:
        sock.sendall(packet_bytes)
        return True
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
        return False


def unpack_packet(
    data: bytes,
    security_service=default_security,
) -> Optional[Packet]:
    """
    Giải nén một gói tin nhị phân (chẳng hạn nhận từ socket UDP datagram)
    thành đối tượng Packet hoàn chỉnh.
    :return: Packet nếu hợp lệ, None nếu dữ liệu hỏng hoặc sai magic.
    """
    if not data or len(data) < HEADER_SIZE:
        return None

    magic, version, flags, msg_type_raw, reserved, payload_length = struct.unpack(
        HEADER_FORMAT, data[:HEADER_SIZE]
    )

    if magic != MAGIC_NUMBER:
        return None

    raw_payload = data[HEADER_SIZE : HEADER_SIZE + payload_length]
    if len(raw_payload) < payload_length:
        return None

    # Xử lý giải mã nếu cờ mã hóa được kích hoạt
    decrypted_bytes = raw_payload
    if (flags & FLAG_ENCRYPTED) and raw_payload:
        try:
            decrypted_bytes = security_service.decrypt(raw_payload)
        except Exception:
            return None

    # Thông dịch dữ liệu (Data Deserialization)
    parsed_data = decrypted_bytes
    if decrypted_bytes:
        try:
            text = decrypted_bytes.decode(ENCODING)
            try:
                parsed_data = json.loads(text)
            except json.JSONDecodeError:
                parsed_data = text
        except UnicodeDecodeError:
            parsed_data = decrypted_bytes

    try:
        msg_type_enum = MessageType(msg_type_raw)
    except ValueError:
        msg_type_enum = msg_type_raw

    return Packet(
        magic=magic,
        version=version,
        flags=flags,
        msg_type=msg_type_enum,
        reserved=reserved,
        payload_length=payload_length,
        raw_payload=raw_payload,
        data=parsed_data,
    )


# ==================== ĐẶC TẢ GIAO THỨC UDP FILE TRANSFER ====================

@dataclass
class UDPFilePacket:
    """
    Biểu diễn một gói tin nhị phân UDP hoàn chỉnh phục vụ truyền file.
    Header kích thước 24 Bytes cố định:
    [Magic: 2B][MsgType: 2B][TransferID: 8B][ChunkIndex: 4B][TotalChunks: 4B][PayloadLen: 4B] + [Payload: NB]
    """
    magic: int
    msg_type: MessageType
    transfer_id: str
    chunk_index: int
    total_chunks: int
    payload_len: int
    raw_payload: bytes


def pack_udp_packet(
    msg_type: Union[MessageType, int],
    transfer_id: str,
    chunk_index: int = 0,
    total_chunks: int = 0,
    raw_payload: bytes = b"",
    encrypt: bool = True,
    security_service=default_security,
) -> bytes:
    """
    Đóng gói dữ liệu thành chuỗi byte nhị phân thô tuân thủ Header UDP 24 Bytes + Payload.
    Không sử dụng Base64 hay JSON để đạt hiệu năng tối đa.
    """
    # Chuẩn hóa transfer_id thành đúng 8 bytes
    transfer_id_bytes = transfer_id.encode("ascii", errors="ignore")[:8].ljust(8, b"\x00")

    payload_to_send = raw_payload
    if encrypt and raw_payload:
        payload_to_send = security_service.encrypt(raw_payload)

    payload_len = len(payload_to_send)

    header = struct.pack(
        UDP_HEADER_FORMAT,
        MAGIC_NUMBER,
        int(msg_type),
        transfer_id_bytes,
        int(chunk_index),
        int(total_chunks),
        payload_len,
    )

    return header + payload_to_send


def unpack_udp_packet(
    data: bytes,
    decrypt: bool = True,
    security_service=default_security,
) -> Optional[UDPFilePacket]:
    """
    Giải gói một datagram UDP nhị phân nhận được từ socket.
    :return: UDPFilePacket nếu hợp lệ, None nếu dữ liệu hỏng hoặc sai magic.
    """
    if len(data) < UDP_HEADER_SIZE:
        return None

    magic, msg_type_raw, transfer_id_bytes, chunk_index, total_chunks, payload_len = struct.unpack(
        UDP_HEADER_FORMAT, data[:UDP_HEADER_SIZE]
    )

    if magic != MAGIC_NUMBER:
        return None

    transfer_id = transfer_id_bytes.decode("ascii", errors="ignore").rstrip("\x00")

    enc_payload = data[UDP_HEADER_SIZE : UDP_HEADER_SIZE + payload_len]

    raw_payload = enc_payload
    if decrypt and enc_payload:
        raw_payload = security_service.decrypt(enc_payload)

    try:
        msg_type_enum = MessageType(msg_type_raw)
    except ValueError:
        msg_type_enum = msg_type_raw

    return UDPFilePacket(
        magic=magic,
        msg_type=msg_type_enum,
        transfer_id=transfer_id,
        chunk_index=chunk_index,
        total_chunks=total_chunks,
        payload_len=len(raw_payload),
        raw_payload=raw_payload,
    )


def send_udp_packet(
    sock: socket.socket,
    addr: Tuple[str, int],
    msg_type: Union[MessageType, int],
    data: Union[Dict, str, bytes] = None,
    encrypt: bool = True,
    security_service=default_security,
) -> bool:
    """
    Đóng gói và gửi gói tin UDP chuẩn (Header 12 Bytes + Payload) tới địa chỉ đích.
    :return: True nếu gửi thành công, False nếu gặp lỗi socket.
    """
    packet_bytes = pack_packet(msg_type, data, encrypt=encrypt, security_service=security_service)
    try:
        sock.sendto(packet_bytes, addr)
        return True
    except (OSError, Exception):
        return False


def send_udp_file_packet(
    sock: socket.socket,
    addr: Tuple[str, int],
    msg_type: Union[MessageType, int],
    transfer_id: str,
    chunk_index: int = 0,
    total_chunks: int = 0,
    raw_payload: bytes = b"",
    encrypt: bool = True,
    security_service=default_security,
) -> bool:
    """
    Đóng gói và gửi gói tin UDP File Transfer (Header 24 Bytes + Binary Payload) tới địa chỉ đích.
    :return: True nếu gửi thành công, False nếu gặp lỗi socket.
    """
    packet_bytes = pack_udp_packet(
        msg_type=msg_type,
        transfer_id=transfer_id,
        chunk_index=chunk_index,
        total_chunks=total_chunks,
        raw_payload=raw_payload,
        encrypt=encrypt,
        security_service=security_service,
    )
    try:
        sock.sendto(packet_bytes, addr)
        return True
    except (OSError, Exception):
        return False