"""
Kịch bản kiểm thử tải đồng thời (Milestone 10 - Testing & Scalability).
Tự động kích hoạt 15 - 20 Client kết nối đồng thời đến Server,
thực hiện gửi tin nhắn chat và kiểm tra độ ổn định của máy chủ.
"""

import sys
import threading
import time
import random
from client.core_client import CollaborationClient
from common.constants import DEFAULT_HOST, DEFAULT_TCP_PORT

NUM_CLIENTS = 15
MESSAGES_PER_CLIENT = 3


def client_worker(client_id: int, host: str, port: int, results: list):
    username = f"Bot_User_{client_id:02d}"
    client = CollaborationClient()

    try:
        # 1. Bắt tay kết nối
        if not client.connect(host, port):
            results.append((client_id, False, "Không thể kết nối socket"))
            return

        # 2. Đăng nhập
        client.login(username)
        time.sleep(0.3)

        if not client.is_authenticated:
            results.append((client_id, False, "Xác thực không thành công"))
            client.disconnect()
            return

        # 3. Gửi tin nhắn Broadcast và Unicast ngẫu nhiên
        for i in range(MESSAGES_PER_CLIENT):
            time.sleep(random.uniform(0.1, 0.4))
            msg = f"Tin nhắn kiểm thử tải #{i+1} từ {username}"
            client.send_broadcast(msg)

        time.sleep(0.5)
        # 4. Thoát êm
        client.disconnect()
        results.append((client_id, True, "Thành công hoàn tất"))
    except Exception as e:
        results.append((client_id, False, str(e)))
        client.disconnect()


def run_load_test(host: str = DEFAULT_HOST, port: int = DEFAULT_TCP_PORT):
    print("=" * 65)
    print(f"[*] BẮT ĐẦU KIỂM THỬ TẢI VỚI {NUM_CLIENTS} CLIENTS ĐỒNG THỜI")
    print(f"[*] Đích: {host}:{port}")
    print("=" * 65)

    threads = []
    results = []

    start_time = time.time()

    for i in range(1, NUM_CLIENTS + 1):
        t = threading.Thread(target=client_worker, args=(i, host, port, results))
        threads.append(t)
        t.start()
        time.sleep(0.05)  # Giãn cách nhỏ mô phỏng kết nối liên tục

    for t in threads:
        t.join()

    total_time = time.time() - start_time
    success_count = sum(1 for _, ok, _ in results if ok)

    print("\n" + "=" * 65)
    print("                    KẾT QUẢ KIỂM THỬ TẢI")
    print("=" * 65)
    print(f"• Tổng số clients tham gia : {NUM_CLIENTS}")
    print(f"• Số client thành công     : {success_count} / {NUM_CLIENTS}")
    print(f"• Thời gian hoàn thành     : {total_time:.2f} giây")
    print(f"• Trạng thái hệ thống      : {'ĐẠT CHUẨN 10/10' if success_count == NUM_CLIENTS else 'CÓ LỖI XẢY RA'}")
    print("=" * 65)

    if success_count < NUM_CLIENTS:
        print("[!] Các lỗi chi tiết:")
        for cid, ok, err in results:
            if not ok:
                print(f"  - Client {cid}: {err}")


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TCP_PORT
    run_load_test(host, port)
