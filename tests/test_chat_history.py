"""
Unit tests cho ChatHistoryManager (In-Memory Server Chat History).
"""

import unittest
from server.chat_history import BROADCAST_TARGET, ChatHistoryManager


class TestChatHistoryManager(unittest.TestCase):

    def setUp(self):
        self.mgr = ChatHistoryManager(max_history=5)

    def test_broadcast_history(self):
        self.mgr.add_broadcast_message("Alice", "Hello World", "10:00:00")
        self.mgr.add_broadcast_message("Bob", "Hi Alice", "10:00:05")

        history = self.mgr.get_history("Charlie", BROADCAST_TARGET)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["sender"], "Alice")
        self.assertEqual(history[0]["text"], "Hello World")
        self.assertEqual(history[1]["sender"], "Bob")
        self.assertFalse(history[0]["is_private"])

    def test_direct_history_symmetry(self):
        self.mgr.add_direct_message("Alice", "Bob", "Tin nhan 1", "10:01:00")
        self.mgr.add_direct_message("Bob", "Alice", "Tin nhan 2", "10:01:10")

        # Alice xem lịch sử với Bob
        h_alice = self.mgr.get_history("Alice", "Bob")
        self.assertEqual(len(h_alice), 2)
        self.assertEqual(h_alice[0]["text"], "Tin nhan 1")
        self.assertEqual(h_alice[1]["text"], "Tin nhan 2")

        # Bob xem lịch sử với Alice -> kết quả phải giống hệt
        h_bob = self.mgr.get_history("Bob", "Alice")
        self.assertEqual(len(h_bob), 2)
        self.assertEqual(h_bob[0]["text"], "Tin nhan 1")
        self.assertEqual(h_bob[1]["text"], "Tin nhan 2")

    def test_direct_history_isolation(self):
        self.mgr.add_direct_message("Alice", "Bob", "Bi mat AB", "10:02:00")

        # Charlie không thể lấy lịch sử chat giữa Alice và Bob
        h_charlie_bob = self.mgr.get_history("Charlie", "Bob")
        self.assertEqual(len(h_charlie_bob), 0)

        h_charlie_alice = self.mgr.get_history("Charlie", "Alice")
        self.assertEqual(len(h_charlie_alice), 0)

    def test_max_history_limit(self):
        # Giới hạn 5 tin nhắn
        for i in range(10):
            self.mgr.add_broadcast_message("Tester", f"Msg {i}", f"10:0{i}:00")

        history = self.mgr.get_history("User", BROADCAST_TARGET)
        self.assertEqual(len(history), 5)
        # Các tin cũ nhất bị đẩy ra (FIFO)
        self.assertEqual(history[0]["text"], "Msg 5")
        self.assertEqual(history[-1]["text"], "Msg 9")


if __name__ == "__main__":
    unittest.main()
