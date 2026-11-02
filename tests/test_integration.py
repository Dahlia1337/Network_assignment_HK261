"""
Kiểm thử tích hợp đầu-cuối (End-to-End Integration Test).
Tự động khởi động Server trong background thread, kết nối các Client,
thực hiện Đăng nhập, Chat Broadcast, Chat Unicast, Gửi file tin cậy và kiểm tra SHA-256.
"""

import os
import tempfile
import threading
import time
import unittest

from common.constants import DEFAULT_HOST
from server.core_server import CollaborationServer
from client.core_client import CollaborationClient
from client.file_transfer import calculate_sha256

TEST_PORT = 9999
TEST_UDP_PORT = 9998
TEST_UDP_FILE_PORT = 9997


class TestEndToEnd(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Khởi động Server thử nghiệm trên cổng riêng
        cls.server = CollaborationServer(
            host=DEFAULT_HOST,
            port=TEST_PORT,
            udp_port=TEST_UDP_PORT,
            udp_file_port=TEST_UDP_FILE_PORT,
        )
        cls.server_thread = threading.Thread(target=cls.server.start, daemon=True)
        cls.server_thread.start()
        time.sleep(0.5)  # Chờ server bind socket

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_client_handshake_and_chat(self):
        """
        Kiểm thử bắt tay kết nối, xác thực và gửi nhận tin nhắn Broadcast & Unicast.
        """
        client_a = CollaborationClient()
        client_b = CollaborationClient()

        received_by_b = []
        received_by_a_private = []

        client_b.on_message_received = lambda s, t, p: received_by_b.append((s, t, p))
        client_a.on_message_received = lambda s, t, p: received_by_a_private.append((s, t, p))

        # 1. Kết nối & Đăng nhập
        self.assertTrue(client_a.connect(DEFAULT_HOST, TEST_PORT))
        self.assertTrue(client_b.connect(DEFAULT_HOST, TEST_PORT))

        client_a.login("Alice")
        client_b.login("Bob")
        time.sleep(0.3)

        self.assertTrue(client_a.is_authenticated)
        self.assertTrue(client_b.is_authenticated)

        # 2. Test Broadcast Chat
        client_a.send_broadcast("Chào mọi người từ Alice")
        time.sleep(0.3)

        self.assertTrue(any("Chào mọi người từ Alice" in item[1] for item in received_by_b))

        # 3. Test Unicast Chat
        client_b.send_unicast("Alice", "Chào riêng Alice từ Bob")
        time.sleep(0.3)

        self.assertTrue(any("Chào riêng Alice từ Bob" in item[1] for item in received_by_a_private))

        client_a.disconnect()
        client_b.disconnect()

    def test_reliable_file_transfer(self):
        """
        Kiểm thử truyền file tin cậy: Tạo file mẫu, gửi từ Sender sang Receiver,
        đối soát mã băm SHA-256 đảm bảo trùng khớp 100%.
        """
        sender_client = CollaborationClient()
        receiver_client = CollaborationClient()

        sender_client.connect(DEFAULT_HOST, TEST_PORT, udp_file_port=TEST_UDP_FILE_PORT)
        receiver_client.connect(DEFAULT_HOST, TEST_PORT, udp_file_port=TEST_UDP_FILE_PORT)

        sender_client.login("SenderUser")
        receiver_client.login("ReceiverUser")
        time.sleep(0.3)

        # Tạo file mẫu 100KB ngẫu nhiên
        test_content = b"MMT261 Network Application Development Distributed File Transfer Test" * 1500
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dat") as tf:
            tf.write(test_content)
            temp_filepath = tf.name

        original_sha256 = calculate_sha256(temp_filepath)
        completed_files = []

        # Tự động đồng ý khi có yêu cầu nhận file
        receiver_client.on_file_request_received = lambda s, n, sz, tid: receiver_client.respond_file_request(tid, True)
        receiver_client.on_file_complete = lambda tid, name, path: completed_files.append(path)

        # Gửi file
        sender_client.send_file_request("ReceiverUser", temp_filepath)

        # Chờ truyền nhận hoàn tất
        waited = 0
        while not completed_files and waited < 5.0:
            time.sleep(0.2)
            waited += 0.2

        self.assertTrue(len(completed_files) > 0, "Không nhận được file trong thời gian chờ!")
        received_path = completed_files[0]
        self.assertTrue(os.path.exists(received_path))

        received_sha256 = calculate_sha256(received_path)
        self.assertEqual(original_sha256, received_sha256, "Mã SHA-256 không trùng khớp!")

        # Dọn dẹp
        try:
            os.remove(temp_filepath)
            os.remove(received_path)
        except Exception:
            pass

        sender_client.disconnect()
        receiver_client.disconnect()

    def test_heartbeat_ping_pong(self):
        """
        Kiểm thử cơ chế nhịp tim sống (Heartbeat Keep-Alive):
        Client gửi HEARTBEAT_PING lên Server và nhận về HEARTBEAT_PONG thành công.
        """
        client = CollaborationClient()
        self.assertTrue(client.connect(DEFAULT_HOST, TEST_PORT))
        client.login("HeartbeatUser")
        time.sleep(0.3)
        self.assertTrue(client.is_authenticated)

        # Gửi thủ công gói PING để kiểm tra phản hồi tức thì
        from common.protocol import send_packet
        from common.message_types import MessageType
        prev_pong_time = client._last_pong_time
        send_packet(client.sock, MessageType.HEARTBEAT_PING, {})
        time.sleep(0.4)

        self.assertGreater(client._last_pong_time, prev_pong_time, "Không nhận được phản hồi PONG từ server!")
        client.disconnect()

    def test_chat_history_isolation_and_retrieval(self):
        """
        Kiểm thử tính năng lịch sử chat:
        - Phân biệt độc lập giữa Broadcast và các đoạn chat 1-1.
        - Khả năng tải lại lịch sử (On-demand) khi client yêu cầu.
        - Bảo mật riêng tư: Client khác không xem được chat 1-1 của người khác.
        """
        from server.chat_history import BROADCAST_TARGET

        client_x = CollaborationClient()
        client_y = CollaborationClient()
        client_z = CollaborationClient()

        self.assertTrue(client_x.connect(DEFAULT_HOST, TEST_PORT))
        self.assertTrue(client_y.connect(DEFAULT_HOST, TEST_PORT))
        self.assertTrue(client_z.connect(DEFAULT_HOST, TEST_PORT))

        client_x.login("UserX")
        client_y.login("UserY")
        client_z.login("UserZ")
        time.sleep(0.3)

        # 1. UserX gửi broadcast
        client_x.send_broadcast("Tin nhắn chung từ UserX")
        time.sleep(0.2)

        # 2. UserX gửi tin riêng cho UserY
        client_x.send_unicast("UserY", "Tin bí mật gửi UserY")
        time.sleep(0.2)

        # 3. UserY gửi lại cho UserX
        client_y.send_unicast("UserX", "UserY đã nhận tin bí mật")
        time.sleep(0.2)

        # 4. UserX request lịch sử Broadcast
        history_x_broadcast = []
        client_x.on_chat_history_received = lambda tgt, msgs: history_x_broadcast.extend(msgs) if tgt == BROADCAST_TARGET else None
        client_x.request_chat_history(BROADCAST_TARGET)
        time.sleep(0.3)

        self.assertTrue(any("Tin nhắn chung từ UserX" == m.get("text") for m in history_x_broadcast))

        # 5. UserX request lịch sử riêng với UserY
        history_xy = []
        client_x.on_chat_history_received = lambda tgt, msgs: history_xy.extend(msgs) if tgt == "UserY" else None
        client_x.request_chat_history("UserY")
        time.sleep(0.3)

        self.assertEqual(len(history_xy), 2)
        self.assertEqual(history_xy[0]["text"], "Tin bí mật gửi UserY")
        self.assertEqual(history_xy[1]["text"], "UserY đã nhận tin bí mật")
        self.assertTrue(all("timestamp" in m for m in history_xy))

        # 6. UserY request lịch sử với UserX (đối xứng, chung luồng)
        history_yx = []
        client_y.on_chat_history_received = lambda tgt, msgs: history_yx.extend(msgs) if tgt == "UserX" else None
        client_y.request_chat_history("UserX")
        time.sleep(0.3)

        self.assertEqual(len(history_yx), 2)
        self.assertEqual(history_yx[0]["text"], "Tin bí mật gửi UserY")
        self.assertEqual(history_yx[1]["text"], "UserY đã nhận tin bí mật")

        # 7. UserZ request lịch sử riêng của UserX -> Phải rỗng (bảo mật riêng tư)
        history_z_with_x = []
        client_z.on_chat_history_received = lambda tgt, msgs: history_z_with_x.extend(msgs) if tgt == "UserX" else None
        client_z.request_chat_history("UserX")
        time.sleep(0.3)

        self.assertEqual(len(history_z_with_x), 0, "UserZ không được xem lịch sử chat giữa UserX và UserY!")

        client_x.disconnect()
        client_y.disconnect()
        client_z.disconnect()


if __name__ == "__main__":
    unittest.main()
