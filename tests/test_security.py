"""
Kiểm thử tự động cho Lớp Bảo mật (Milestone 8 - Security Layer).
Kiểm tra tính đúng đắn của mã hóa và giải mã đối xứng.
"""

import unittest
from common.security import SecurityService


class TestSecurity(unittest.TestCase):

    def setUp(self):
        self.security = SecurityService(secret_key=b"MY_SUPER_SECRET_KEY_1234567890!")

    def test_encrypt_decrypt_text(self):
        raw_text = "Dữ liệu tiếng Việt có dấu: Hệ thống phân tán Client-Server 2026."
        raw_bytes = raw_text.encode("utf-8")

        cipher_bytes = self.security.encrypt(raw_bytes)
        self.assertNotEqual(cipher_bytes, raw_bytes)

        decrypted_bytes = self.security.decrypt(cipher_bytes)
        self.assertEqual(decrypted_bytes, raw_bytes)
        self.assertEqual(decrypted_bytes.decode("utf-8"), raw_text)

    def test_encrypt_decrypt_binary(self):
        # Dữ liệu nhị phân ngẫu nhiên (mô phỏng file chunk)
        raw_binary = bytes(range(256))
        cipher_bytes = self.security.encrypt(raw_binary)
        decrypted_bytes = self.security.decrypt(cipher_bytes)
        self.assertEqual(decrypted_bytes, raw_binary)

    def test_empty_payload(self):
        empty_data = b""
        cipher_bytes = self.security.encrypt(empty_data)
        self.assertEqual(self.security.decrypt(cipher_bytes), empty_data)


if __name__ == "__main__":
    unittest.main()
