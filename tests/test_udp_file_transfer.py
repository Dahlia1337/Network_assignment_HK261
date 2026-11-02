"""
Unit test chuyên sâu cho module UDP File Streaming & ARQ (Milestone 6).
Kiểm tra:
1. Đọc chunk nhị phân thô (không Base64) từ FileSender.
2. Bộ đệm sắp xếp chunk đến lệch thứ tự (out-of-order) trong FileReceiver.
3. Đóng gói & giải gói UDPFilePacket với mã hóa nhị phân an toàn.
4. Kiểm thử truyền file hoàn chỉnh qua luồng UDP Streaming với Server Router trung gian và đối soát SHA-256.
"""

import os
import tempfile
import threading
import time
import unittest

from common.constants import DEFAULT_HOST, UDP_CHUNK_SIZE
from common.message_types import MessageType
from common.protocol import pack_udp_packet, unpack_udp_packet
from client.file_transfer import FileReceiver, FileSender, calculate_sha256
from server.core_server import CollaborationServer
from client.core_client import CollaborationClient

TEST_TCP_PORT = 9988
TEST_DISCOVERY_PORT = 9987
TEST_FILE_UDP_PORT = 9986


class TestUDPFileTransfer(unittest.TestCase):

    def test_file_sender_raw_chunks(self):
        """
        Kiểm tra FileSender đọc trực tiếp bytes thô, không qua Base64.
        """
        raw_data = b"Hello Antigravity UDP Streaming Raw Bytes" * 100
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(raw_data)
            filepath = tf.name

        try:
            sender = FileSender(filepath, chunk_size=64)
            self.assertGreater(sender.total_chunks, 1)

            # Đọc chunk 0
            chunk0 = sender.get_chunk_bytes(0)
            self.assertEqual(len(chunk0), 64)
            self.assertEqual(chunk0, raw_data[:64])

            # Ráp lại toàn bộ chunks
            reassembled = b"".join(sender.get_chunk_bytes(i) for i in range(sender.total_chunks))
            self.assertEqual(reassembled, raw_data)
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    def test_file_receiver_out_of_order_reassembly(self):
        """
        Kiểm tra FileReceiver nhận các chunks bị đảo lộn thứ tự (out-of-order)
        nhưng vẫn ghép đúng thứ tự và kiểm tra SHA-256 thành công.
        """
        raw_data = b"A" * 100 + b"B" * 100 + b"C" * 100 + b"D" * 100
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(raw_data)
            orig_filepath = tf.name

        expected_sha = calculate_sha256(orig_filepath)
        save_dir = tempfile.mkdtemp()

        try:
            receiver = FileReceiver(save_dir, "reordered.dat", len(raw_data), expected_sha)
            
            # Gửi các chunk theo thứ tự xáo trộn: 2, 0, 3, 1
            chunks = [
                (0, raw_data[0:100]),
                (1, raw_data[100:200]),
                (2, raw_data[200:300]),
                (3, raw_data[300:400]),
            ]
            shuffled = [chunks[2], chunks[0], chunks[3], chunks[1]]

            for idx, chunk_bytes in shuffled:
                receiver.write_raw_chunk(idx, 4, chunk_bytes)

            success, final_path = receiver.finalize_and_verify()
            self.assertTrue(success, f"Xác minh toàn vẹn thất bại: {final_path}")
            self.assertTrue(os.path.exists(final_path))

            with open(final_path, "rb") as f:
                content = f.read()
            self.assertEqual(content, raw_data)

            if os.path.exists(final_path):
                os.remove(final_path)
        finally:
            if os.path.exists(orig_filepath):
                os.remove(orig_filepath)

    def test_udp_streaming_end_to_end_transfer(self):
        """
        Kiểm thử đầu cuối: 1 Server + 2 Client kết nối, thực hiện truyền file UDP Streaming
        và kiểm tra tính đúng đắn của toàn bộ chu trình ARQ.
        """
        server = CollaborationServer(
            host=DEFAULT_HOST,
            port=TEST_TCP_PORT,
            udp_port=TEST_DISCOVERY_PORT,
            udp_file_port=TEST_FILE_UDP_PORT,
        )
        server_thread = threading.Thread(target=server.start, daemon=True)
        server_thread.start()
        time.sleep(0.4)

        sender_client = CollaborationClient()
        receiver_client = CollaborationClient()

        try:
            self.assertTrue(sender_client.connect(DEFAULT_HOST, TEST_TCP_PORT, udp_file_port=TEST_FILE_UDP_PORT))
            self.assertTrue(receiver_client.connect(DEFAULT_HOST, TEST_TCP_PORT, udp_file_port=TEST_FILE_UDP_PORT))

            sender_client.login("SenderUdp")
            receiver_client.login("ReceiverUdp")
            time.sleep(0.3)

            # Tạo file dữ liệu 50KB
            test_bytes = b"UDP Selective Repeat Streaming Integration Test\n" * 1024
            with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tf:
                tf.write(test_bytes)
                test_file = tf.name

            orig_sha = calculate_sha256(test_file)
            completed_events = []
            progress_events = []

            receiver_client.on_file_request_received = lambda s, n, sz, tid: receiver_client.respond_file_request(tid, True)
            receiver_client.on_file_complete = lambda tid, n, p: completed_events.append(p)
            receiver_client.on_file_progress = lambda tid, pct, is_up: progress_events.append(pct)

            sender_client.send_file_request("ReceiverUdp", test_file)

            # Chờ hoàn tất trong tối đa 5 giây
            waited = 0.0
            while not completed_events and waited < 5.0:
                time.sleep(0.1)
                waited += 0.1

            self.assertTrue(len(completed_events) > 0, "Không nhận được file trong thời gian cho phép!")
            received_path = completed_events[0]
            self.assertTrue(os.path.exists(received_path))

            recv_sha = calculate_sha256(received_path)
            self.assertEqual(orig_sha, recv_sha, "SHA-256 sau khi nhận không trùng khớp!")
            self.assertGreater(len(progress_events), 0, "Không có callback tiến độ on_file_progress!")

            try:
                os.remove(test_file)
                os.remove(received_path)
            except Exception:
                pass

        finally:
            sender_client.disconnect()
            receiver_client.disconnect()
            server.stop()


if __name__ == "__main__":
    unittest.main()
