"""
Kiểm thử tự động cho Giao thức tầng ứng dụng (Milestone 1 - Protocol Design).
Kiểm tra khả năng chống dính gói (Packet Sticking) và chống phân mảnh (Fragmentation).
"""

import io
import unittest
from common.constants import HEADER_SIZE, MAGIC_NUMBER, PROTOCOL_VERSION
from common.message_types import MessageType
from common.protocol import pack_packet, read_exact, receive_packet


class MockSocket:
    """
    Giả lập socket TCP stream dựa trên buffer byte trong bộ nhớ.
    Cho phép cắt nhỏ buffer (mô phỏng phân mảnh) hoặc dồn nhiều gói vào 1 lần đọc (dính gói).
    """

    def __init__(self, data: bytes = b"", chunk_step: int = 5):
        self.data = data
        self.offset = 0
        self.chunk_step = chunk_step

    def recv(self, num_bytes: int) -> bytes:
        if self.offset >= len(self.data):
            return b""
        # Giới hạn số byte đọc để kiểm tra khả năng ghép phân đoạn
        actual_bytes = min(num_bytes, self.chunk_step, len(self.data) - self.offset)
        chunk = self.data[self.offset : self.offset + actual_bytes]
        self.offset += actual_bytes
        return chunk


class TestProtocol(unittest.TestCase):

    def test_pack_and_unpack_simple(self):
        """
        Kiểm tra đóng gói và giải gói tin nhắn thông thường.
        """
        original_msg = {"text": "Xin chào thế giới!", "user": "alice"}
        packed_bytes = pack_packet(MessageType.MSG_BROADCAST, original_msg, encrypt=True)

        self.assertGreaterEqual(len(packed_bytes), HEADER_SIZE)

        mock_sock = MockSocket(packed_bytes, chunk_step=1024)
        packet = receive_packet(mock_sock)

        self.assertIsNotNone(packet)
        self.assertEqual(packet.magic, MAGIC_NUMBER)
        self.assertEqual(packet.version, PROTOCOL_VERSION)
        self.assertEqual(packet.msg_type, MessageType.MSG_BROADCAST)
        self.assertEqual(packet.data, original_msg)

    def test_packet_fragmentation(self):
        """
        Mô phỏng hiện tượng phân mảnh: Socket chỉ trả về 3 byte mỗi lần gọi recv().
        Bộ nhận phải lặp và ráp lại đủ dữ liệu mà không bị lỗi.
        """
        test_payload = {"status": "ok", "numbers": list(range(100))}
        packed_bytes = pack_packet(MessageType.USER_LIST_RESP, test_payload, encrypt=True)

        # Cắt nhỏ chỉ 3 bytes / lần recv
        fragmented_sock = MockSocket(packed_bytes, chunk_step=3)
        packet = receive_packet(fragmented_sock)

        self.assertIsNotNone(packet)
        self.assertEqual(packet.data, test_payload)

    def test_packet_sticking(self):
        """
        Mô phỏng hiện tượng dính gói: Hai gói tin liên tiếp được đẩy chung vào 1 stream.
        Bộ nhận phải đọc chính xác gói 1, sau đó đọc tiếp chính xác gói 2.
        """
        msg1 = {"step": 1, "note": "gói thứ nhất"}
        msg2 = {"step": 2, "note": "gói thứ hai"}

        packed1 = pack_packet(MessageType.MSG_BROADCAST, msg1, encrypt=True)
        packed2 = pack_packet(MessageType.MSG_UNICAST, msg2, encrypt=True)
        combined_stream = packed1 + packed2

        sock = MockSocket(combined_stream, chunk_step=7)

        # Đọc gói 1
        pkt1 = receive_packet(sock)
        self.assertIsNotNone(pkt1)
        self.assertEqual(pkt1.msg_type, MessageType.MSG_BROADCAST)
        self.assertEqual(pkt1.data, msg1)

        # Đọc gói 2
        pkt2 = receive_packet(sock)
        self.assertIsNotNone(pkt2)
        self.assertEqual(pkt2.msg_type, MessageType.MSG_UNICAST)
        self.assertEqual(pkt2.data, msg2)

    def test_udp_pack_and_unpack(self):
        """
        Kiểm tra đóng gói và giải gói nhị phân cho UDP File Transfer.
        """
        from common.protocol import pack_udp_packet, unpack_udp_packet
        from common.constants import UDP_HEADER_SIZE

        sample_raw = b"BINARY_DATA_CHUNK_RAW_1234567890\x00\xff\xfe"
        packed_bytes = pack_udp_packet(
            msg_type=MessageType.FILE_CHUNK_DATA,
            transfer_id="abc12345",
            chunk_index=3,
            total_chunks=10,
            raw_payload=sample_raw,
            encrypt=True,
        )

        self.assertGreater(len(packed_bytes), UDP_HEADER_SIZE)

        udp_pkt = unpack_udp_packet(packed_bytes, decrypt=True)
        self.assertIsNotNone(udp_pkt)
        self.assertEqual(udp_pkt.magic, MAGIC_NUMBER)
        self.assertEqual(udp_pkt.msg_type, MessageType.FILE_CHUNK_DATA)
        self.assertEqual(udp_pkt.transfer_id, "abc12345")
        self.assertEqual(udp_pkt.chunk_index, 3)
        self.assertEqual(udp_pkt.total_chunks, 10)
        self.assertEqual(udp_pkt.raw_payload, sample_raw)


if __name__ == "__main__":
    unittest.main()
