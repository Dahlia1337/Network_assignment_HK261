"""
Module user_manager: Quản lý đọc/ghi thông tin tài khoản người dùng
lưu trữ trong tệp JSON với cơ chế Thread-safety.
"""

import json
import logging
import os
import threading
from datetime import datetime
from typing import Dict, Tuple

logger = logging.getLogger("UserManager")


class UserManager:
    """
    Lớp quản lý đăng ký và xác thực tài khoản người dùng.
    Sử dụng threading.Lock() để đảm bảo an toàn luồng khi đọc/ghi file users.json.
    """

    def __init__(self, filepath: str = "server/users.json"):
        self.filepath = filepath
        self._lock = threading.Lock()
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        """
        Khởi tạo file JSON rỗng nếu tệp chưa tồn tại hoặc bị lỗi cấu trúc.
        """
        with self._lock:
            if not os.path.exists(self.filepath):
                try:
                    dir_name = os.path.dirname(self.filepath)
                    if dir_name:
                        os.makedirs(dir_name, exist_ok=True)
                    with open(self.filepath, "w", encoding="utf-8") as f:
                        json.dump({}, f, indent=4, ensure_ascii=False)
                    logger.info(f"[*] Đã tạo mới file lưu trữ tài khoản tại: {self.filepath}")
                except Exception as e:
                    logger.error(f"[X] Lỗi khi tạo file {self.filepath}: {e}")

    def _load_users(self) -> Dict[str, dict]:
        """
        Đọc danh sách người dùng từ file JSON (yêu cầu gọi bên trong lock).
        """
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"[X] Lỗi khi đọc file users.json: {e}")
            return {}

    def _save_users(self, users: Dict[str, dict]) -> bool:
        """
        Ghi toàn bộ danh sách người dùng vào file JSON (yêu cầu gọi bên trong lock).
        """
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(users, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"[X] Lỗi khi ghi file users.json: {e}")
            return False

    def register_user(self, username: str, password_hash: str) -> Tuple[bool, str]:
        """
        Đăng ký tài khoản mới.
        :param username: Tên tài khoản
        :param password_hash: Chuỗi mật khẩu đã được băm SHA-256 từ phía Client
        :return: (True/False, thông điệp)
        """
        username = username.strip()
        if not username or not password_hash:
            return False, "Tên tài khoản và mật khẩu không được để rỗng!"

        with self._lock:
            users = self._load_users()
            if username in users:
                logger.warning(f"[Register] Đăng ký thất bại: Tài khoản '{username}' đã tồn tại.")
                return False, "Tên tài khoản đã được sử dụng!"

            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            users[username] = {
                "username": username,
                "password_hash": password_hash,
                "created_at": created_at,
            }

            if self._save_users(users):
                logger.info(f"[Register] Đăng ký thành công tài khoản mới: '{username}'")
                return True, "Đăng ký tài khoản thành công!"
            else:
                return False, "Lỗi hệ thống khi lưu thông tin tài khoản!"

    def authenticate_user(self, username: str, password_hash: str) -> Tuple[bool, str]:
        """
        Xác thực tài khoản đăng nhập.
        :param username: Tên tài khoản
        :param password_hash: Chuỗi mật khẩu đã được băm SHA-256 từ phía Client
        :return: (True/False, thông điệp)
        """
        username = username.strip()
        if not username or not password_hash:
            return False, "Tên tài khoản và mật khẩu không được để rỗng!"

        with self._lock:
            users = self._load_users()
            user_info = users.get(username)

            if not user_info:
                logger.warning(f"[Auth] Xác thực thất bại: Tài khoản '{username}' không tồn tại.")
                return False, "Tài khoản không tồn tại!"

            if user_info.get("password_hash") == password_hash:
                logger.info(f"[Auth] Xác thực thành công cho tài khoản: '{username}'")
                return True, "Đăng nhập thành công!"
            else:
                logger.warning(f"[Auth] Xác thực thất bại: Sai mật khẩu cho tài khoản '{username}'.")
                return False, "Mật khẩu không chính xác!"