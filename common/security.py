"""
Module security: Hiện thực hóa lớp bảo mật dữ liệu (Security Layer - Rubric Step 8).
Cung cấp các hàm mã hóa đối xứng (Symmetric Encryption) và giải mã payload
trước khi truyền qua socket, ngăn chặn kỹ thuật bắt gói tin (Packet Sniffing).
"""

import base64
import os
from typing import Tuple

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False


class SecurityService:
    """
    Dịch vụ mã hóa và giải mã bảo mật dữ liệu payload.
    Mặc định sử dụng Fernet (AES-128-CBC + HMAC-SHA256 authenticated encryption)
    hoặc thuật toán XOR-Salt dự phòng nếu môi trường chưa cài đặt thư viện ngoài.
    """

    def __init__(self, secret_key: bytes = b"MMT261_DISTRIBUTED_APP_SECRET_2026"):
        self.secret_key = secret_key
        self._cipher = None
        self._init_cipher()

    def _init_cipher(self):
        if CRYPTOGRAPHY_AVAILABLE:
            # Tạo khóa 32 bytes chuẩn Fernet từ secret_key dùng KDF
            salt = b"mmt261_salt_fixed"
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100_000,
            )
            derived_key = base64.urlsafe_b64encode(kdf.derive(self.secret_key))
            self._cipher = Fernet(derived_key)
        else:
            self._cipher = None

    def encrypt(self, data: bytes) -> bytes:
        """
        Mã hóa dữ liệu thô sang dạng byte mã hóa.
        """
        if not data:
            return b""
        if self._cipher:
            return self._cipher.encrypt(data)
        else:
            # Thuật toán đối xứng dự phòng (XOR with key stream) nếu chưa cài cryptography
            key_len = len(self.secret_key)
            return bytes([b ^ self.secret_key[i % key_len] for i, b in enumerate(data)])

    def decrypt(self, encrypted_data: bytes) -> bytes:
        """
        Giải mã dữ liệu đã mã hóa trở lại dạng byte thô ban đầu.
        """
        if not encrypted_data:
            return b""
        if self._cipher:
            return self._cipher.decrypt(encrypted_data)
        else:
            # Giải mã bằng XOR đối xứng dự phòng
            key_len = len(self.secret_key)
            return bytes([b ^ self.secret_key[i % key_len] for i, b in enumerate(encrypted_data)])


# Đối tượng dịch vụ mặc định dùng chung
default_security = SecurityService()
