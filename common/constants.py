"""
Module constants: Định nghĩa các hằng số cấu hình hệ thống toàn cục.
"""

# ==================== ĐẶC TẢ GIAO THỨC (PROTOCOL SPECIFICATION) ====================
# Magic Bytes định danh gói tin hợp lệ (0xAA55 = 43605)
MAGIC_NUMBER: int = 0xAA55

# Phiên bản giao thức hiện tại
PROTOCOL_VERSION: int = 1

# Các bit cờ trạng thái (Flags)
FLAG_PLAINTEXT: int = 0x00
FLAG_ENCRYPTED: int = 0x01
FLAG_COMPRESSED: int = 0x02

# Định dạng nhị phân của Header (Kích thước cố định 12 Bytes):
# !: Big-endian (network byte order)
# H: Magic Number (2 bytes unsigned short)
# B: Protocol Version (1 byte unsigned char)
# B: Flags (1 byte unsigned char)
# H: Message Type (2 bytes unsigned short)
# H: Reserved (2 bytes unsigned short)
HEADER_FORMAT: str = "!HBBHHI"
HEADER_SIZE: int = 12

# Định dạng nhị phân Header UDP File Streaming (Kích thước 24 Bytes):
# !: Big-endian
# H: Magic Number (2 bytes unsigned short)
# H: Message Type (2 bytes unsigned short)
# 8s: Transfer ID (8 bytes string)
# I: Chunk Index (4 bytes unsigned int)
# I: Total Chunks (4 bytes unsigned int)
# I: Payload Length (4 bytes unsigned int)
UDP_HEADER_FORMAT: str = "!HH8sIII"
UDP_HEADER_SIZE: int = 24

# ==================== CẤU HÌNH MẠNG (NETWORK CONFIGURATION) ====================
DEFAULT_HOST: str = "0.0.0.0"
DEFAULT_TCP_PORT: int = 8888
DEFAULT_UDP_PORT: int = 8889
DEFAULT_UDP_FILE_PORT: int = 8890

# Kích thước bộ đệm socket đọc/ghi (Bytes)
SOCKET_RECV_BUFFER_SIZE: int = 4096

# Kích thước mỗi khối file khi phân mảnh UDP (1400 Bytes tránh IP Fragmentation)
FILE_CHUNK_SIZE: int = 1400

# Cấu hình UDP Reliable ARQ (Selective Repeat)
UDP_ACK_TIMEOUT: float = 0.1      # 100ms
UDP_WINDOW_SIZE: int = 5          # Kích thước cửa sổ trượt (5 chunks)
UDP_MAX_RETRIES: int = 5          # Tối đa 5 lần gửi lại cho mỗi chunk trước khi hủy

# Thời gian chờ socket timeout (giây)
SOCKET_TIMEOUT: float = 30.0

# Cấu hình HEARTBEAT
HEARTBEAT_INTERVAL: float = 5.0
HEARTBEAT_TIMEOUT: float = 15.0

# Bảng mã ký tự chuẩn
ENCODING: str = "utf-8"

# ==================== CẤU HÌNH BẢO MẬT (SECURITY CONFIGURATION) ====================
# Khóa đối xứng dùng chung mặc định (32 bytes url-safe base64 key cho Fernet / AES-256)
DEFAULT_AES_KEY: bytes = b"MMT261_SECRET_KEY_FOR_AES_256_COLLABORATION_32BYTES!"[:32]
