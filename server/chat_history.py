"""
Module chat_history: Quản lý lịch sử tin nhắn trong bộ nhớ RAM của Server (In-Memory).
Khi tắt Server, toàn bộ lịch sử sẽ tự động bị xóa bỏ.
Hỗ trợ lưu trữ riêng biệt phòng chat chung (Broadcast) và từng cuộc chat riêng 1-1.
Đảm bảo an toàn luồng (Thread-Safe) bằng threading.Lock.
"""

from collections import defaultdict, deque
import logging
import threading
from typing import Dict, List, Tuple

logger = logging.getLogger("ChatHistory")

DEFAULT_MAX_HISTORY_PER_CHAT = 100
BROADCAST_TARGET = "__BROADCAST__"


class ChatHistoryManager:
    """
    Quản lý lưu vết lịch sử trò chuyện trong RAM của máy chủ.
    """

    def __init__(self, max_history: int = DEFAULT_MAX_HISTORY_PER_CHAT):
        self.max_history = max_history
        self._lock = threading.Lock()
        # Lịch sử phòng chat chung
        self._broadcast_history: deque = deque(maxlen=self.max_history)
        # Lịch sử chat 1-1: Key là cặp (userA, userB) đã sắp xếp theo thứ tự bảng chữ cái
        self._direct_histories: Dict[Tuple[str, str], deque] = defaultdict(
            lambda: deque(maxlen=self.max_history)
        )

    def _get_direct_key(self, user1: str, user2: str) -> Tuple[str, str]:
        """
        Tạo khóa định danh đối xứng duy nhất giữa 2 người dùng.
        Đảm bảo Alice -> Bob và Bob -> Alice cùng chung 1 luồng chat.
        """
        return tuple(sorted([user1, user2]))

    def add_broadcast_message(self, sender: str, text: str, timestamp: str) -> dict:
        """
        Lưu một tin nhắn gửi đến phòng chung.
        """
        msg = {
            "sender": sender,
            "target": BROADCAST_TARGET,
            "text": text,
            "timestamp": timestamp,
            "is_private": False,
        }
        with self._lock:
            self._broadcast_history.append(msg)
        return msg

    def add_direct_message(self, sender: str, target: str, text: str, timestamp: str) -> dict:
        """
        Lưu một tin nhắn gửi riêng tư giữa hai người dùng.
        """
        msg = {
            "sender": sender,
            "target": target,
            "text": text,
            "timestamp": timestamp,
            "is_private": True,
        }
        key = self._get_direct_key(sender, target)
        with self._lock:
            self._direct_histories[key].append(msg)
        return msg

    def get_history(self, requester: str, target: str) -> List[dict]:
        """
        Lấy danh sách tin nhắn lịch sử theo yêu cầu của requester.
        - Nếu target là '__BROADCAST__': Trả về lịch sử phòng chung.
        - Nếu target là một username: Trả về lịch sử 1-1 giữa requester và target đó.
        (Đảm bảo tính bảo mật: Người dùng chỉ đọc được lịch sử mà mình có tham gia).
        """
        with self._lock:
            if target == BROADCAST_TARGET:
                return list(self._broadcast_history)
            
            key = self._get_direct_key(requester, target)
            if key in self._direct_histories:
                return list(self._direct_histories[key])
            return []

    def clear(self):
        """
        Xóa toàn bộ lịch sử trong RAM.
        """
        with self._lock:
            self._broadcast_history.clear()
            self._direct_histories.clear()
