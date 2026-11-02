"""
Module message_types: Định nghĩa các loại mã thông điệp (Message Types)
được hỗ trợ trong giao thức tầng ứng dụng của hệ thống.
"""

from enum import IntEnum

class MessageType(IntEnum):
    """
    Tập hợp các loại thông điệp trao đổi giữa Client và Server.
    Được mã hóa thành 2 bytes unsigned short trong Header.
    """
    # --- 1. Nhóm Xác thực, Khởi tạo phiên & Đăng ký (0x0001 - 0x000F) ---
    AUTH_REQ = 0x0001               # Client gửi yêu cầu đăng nhập (username, password_hash)
    AUTH_SUCCESS = 0x0002           # Server phản hồi đăng nhập thành công
    AUTH_FAIL = 0x0003              # Server phản hồi đăng nhập thất bại (trùng tên, sai password)
    REGISTER_REQ = 0x0004           # Client gửi yêu cầu đăng ký (username, password_hash)
    REGISTER_SUCCESS = 0x0005       # Server phản hồi đăng ký thành công
    REGISTER_FAIL = 0x0006          # Server phản hồi đăng ký thất bại (VD: tài khoản đã tồn tại)

    # --- 2. Nhóm Định danh & Khám phá người dùng (0x0010 - 0x001F) ---
    USER_LIST_REQ = 0x0010          # Client yêu cầu danh sách người dùng đang online
    USER_LIST_RESP = 0x0011         # Server trả về danh sách người dùng online
    USER_JOIN_BROADCAST = 0x0012    # Server thông báo có người dùng mới online
    USER_LEAVE_BROADCAST = 0x0013   # Server thông báo có người dùng ngắt kết nối

    # --- 3. Nhóm Tin nhắn văn bản thời gian thực (0x0020 - 0x002F) ---
    MSG_BROADCAST = 0x0020          # Tin nhắn gửi đến phòng chat chung (cho mọi người)
    MSG_UNICAST = 0x0021            # Tin nhắn gửi riêng tư 1-1 đến một người dùng cụ thể
    MSG_ACK = 0x0022                # Xác nhận tin nhắn đã được nhận
    CHAT_HISTORY_REQ = 0x0023       # Client yêu cầu lấy lịch sử chat
    CHAT_HISTORY_RESP = 0x0024      # Server trả về lịch sử chat

    # --- 4. Nhóm Truyền nhận tệp tin cậy (0x0030 - 0x003F) ---
    FILE_TRANSFER_REQ = 0x0030      # Client A yêu cầu gửi file đến Client B (kèm metadata, SHA256)
    FILE_TRANSFER_ACCEPT = 0x0031   # Client B đồng ý nhận file
    FILE_TRANSFER_REJECT = 0x0032   # Client B từ chối nhận file
    FILE_CHUNK_DATA = 0x0033        # Gói tin chứa một khối (chunk) dữ liệu của tệp
    FILE_CHUNK_ACK = 0x0034         # Xác nhận đã nhận khối dữ liệu (cho flow control)
    FILE_TRANSFER_COMPLETE = 0x0035 # Thông báo hoàn tất truyền tệp toàn diện
    FILE_TRANSFER_ERROR = 0x0036    # Thông báo lỗi trong quá trình truyền nhận tệp
    FILE_UDP_BIND = 0x0037          # Gói tin định danh địa chỉ UDP của Client với Server (Hole-punching)

    # --- 5. Nhóm Kiểm tra trạng thái & Quản lý kết nối (0x0090 - 0x00FF) ---
    HEARTBEAT_PING = 0x0090         # Client/Server gửi gói tin kiểm tra kết nối sống (Keep-alive)
    HEARTBEAT_PONG = 0x0091         # Phản hồi nhịp tim sống
    DISCONNECT_REQ = 0x00FE         # Client gửi thông báo thoát êm (Graceful disconnect)
    ERROR_RESP = 0x00FF             # Thông báo lỗi chung của hệ thống