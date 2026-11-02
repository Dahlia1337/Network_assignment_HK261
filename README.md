# DISTRIBUTED CLIENT-SERVER COLLABORATION APPLICATION
> **Môn học:** Phát triển Ứng dụng Mạng (Network Application Development - MMT261)  
> **Ngôn ngữ:** Python 3 (Sử dụng Raw Sockets)  
> **Kiến trúc:** Client - Server phân tán đa luồng (Multi-threaded Concurrency)  

---

## 📖 GIỚI THIỆU DỰ ÁN
Ứng dụng cộng tác phân tán được thiết kế để hoạt động hoàn toàn tự lưu trữ (self-hosted) trong môi trường mạng nội bộ (LAN / VPN). Ứng dụng triển khai một **Giao thức tầng ứng dụng tùy chỉnh (Custom Application Layer Protocol)** chạy trên nền TCP (truyền tin cậy cho Chat & File Transfer) và UDP (Broadcast Discovery).

Hệ thống tuân thủ nghiêm ngặt các yêu cầu:
* **Không sử dụng framework bậc cao** (No Flask, Django, WebSockets, HTTP).
* **Sử dụng Raw Socket tiêu chuẩn** (`import socket`).
* **Kỹ thuật đóng khung gói tin (Length-Prefixed Framing)** giải quyết triệt để vấn đề dính gói và phân mảnh TCP.
* **Xử lý đồng thời (Concurrency)**: Hỗ trợ 15 - 20 Client kết nối và hoạt động song song.
* **Bảo mật dữ liệu (Security Layer)**: Toàn bộ payload được mã hóa đối xứng (AES-256) trước khi truyền qua mạng.
* **Truyền file tin cậy (Reliable File Transfer)**: Phân mảnh tệp (Chunking 32KB), tái hợp và kiểm tra toàn vẹn bằng hàm băm SHA-256 kèm thanh tiến trình trực quan.

---

## 🛠 HƯỚNG DẪN CÀI ĐẶT & MÔI TRƯỜNG

### 1. Yêu cầu hệ thống
* Hệ điều hành: Windows, macOS, hoặc Linux.
* Python: Phiên bản **3.10 trở lên**.

### 2. Cài đặt thư viện phụ trợ
Mở Terminal/PowerShell tại thư mục gốc của dự án (`d:/MyBachKhoa/MMT261`) và chạy lệnh:

```bash
pip install -r requirements.txt
```

*(Lưu ý: Nếu máy không thể cài thư viện `cryptography`, hệ thống đã tích hợp sẵn cơ chế mã hóa dự phòng để vẫn chạy ổn định).*

---

## 🚀 HƯỚNG DẪN KHỞI CHẠY ỨNG DỤNG

### Bước 1: Khởi động Máy chủ (Server)
Mở một cửa sổ Terminal mới và chạy:

```bash
python -m server.server_main
```

Hoặc tùy chỉnh địa chỉ IP và Port:
```bash
python -m server.server_main --host 0.0.0.0 --port 8888 --udp-port 8889
```

Khi máy chủ khởi động thành công, màn hình sẽ hiển thị:
```
=================================================================
      DISTRIBUTED CLIENT-SERVER COLLABORATION APPLICATION
                     SERVER CONSOLE
=================================================================
[TCP] Server đang lắng nghe tại 127.0.0.1:8888 (Sẵn sàng phục vụ)
[UDP] Discovery service đang hoạt động trên cổng UDP 8889
```

---

### Bước 2: Khởi chạy Máy trạm (Clients)

Mở thêm các cửa sổ Terminal riêng biệt cho từng người dùng:

#### 1. Chạy ở chế độ Giao diện đồ họa (GUI - Khuyên dùng)
* **Khách hàng 1 (Alice):**
  ```bash
  python -m client.client_main --user Alice
  ```
* **Khách hàng 2 (Bob):**
  ```bash
  python -m client.client_main --user Bob
  ```

*Giao diện GUI sẽ xuất hiện với danh sách thành viên online, khung chat chung, danh sách chọn chat 1-1, nút gửi file và thanh Progress Bar.*

#### 2. Chạy ở chế độ Dòng lệnh (CLI)
Nếu muốn chạy trực tiếp trong terminal:
```bash
python -m client.client_main --user Charlie --cli
```

Các lệnh trong giao diện CLI:
* `<nội_dung>`: Gửi tin nhắn phòng chat chung (Broadcast).
* `/msg <username> <nội_dung>`: Gửi tin nhắn riêng (Unicast).
* `/send <username> <đường_dẫn_file>`: Gửi tệp tin cậy đến người dùng.
* `/accept <transfer_id>`: Đồng ý nhận tệp.
* `/reject <transfer_id>`: Từ chối nhận tệp.
* `/list`: Xem danh sách thành viên online.
* `/quit`: Thoát khỏi hệ thống an toàn.

---

## 🧪 CHẠY KIỂM THỬ TỰ ĐỘNG & KIỂM THỬ TẢI

Dự án cung cấp bộ kiểm thử tự động toàn diện:

### 1. Kiểm thử Giao thức & Đóng khung (Protocol & Framing Test)
Kiểm tra khả năng chống dính gói (Packet Sticking) và chống phân mảnh (Fragmentation):
```bash
python -m unittest tests/test_protocol.py
```

### 2. Kiểm thử Lớp Bảo mật (Security Layer Test)
Kiểm tra giải thuật mã hóa và giải mã dữ liệu:
```bash
python -m unittest tests/test_security.py
```

### 3. Kiểm thử Tải đồng thời 15-20 Clients (Concurrency & Scalability Test)
*Đảm bảo Server đang chạy ở Bước 1*, sau đó mở terminal khác chạy:
```bash
python -m tests.simulate_load
```
*Script sẽ giả lập 15 bot kết nối, đăng nhập, gửi tin nhắn liên tục và thoát êm.*

---

## 📁 CẤU TRÚC THƯ MỤC DỰ ÁN
```
d:/MyBachKhoa/MMT261/
│
├── docs/                               # Tài liệu & Đề bài
│   ├── Assignment 1 - Distributed...   # Đề bài gốc (PDF)
│   ├── plan.md                         # Kế hoạch chi tiết & 10 bước Rubric
│   └── protocol_spec.md                # Đặc tả chi tiết gói tin nhị phân
│
├── common/                             # Module dùng chung (Giao thức & Bảo mật)
│   ├── constants.py                    # Hằng số cấu hình hệ thống
│   ├── message_types.py                # Mã định danh các thông điệp (Enum)
│   ├── protocol.py                     # Đóng gói và giải mã Header 12B + Payload
│   └── security.py                     # Mã hóa AES-256 bảo vệ dữ liệu
│
├── server/                             # Mã nguồn Máy chủ
│   ├── server_main.py                  # Entrypoint khởi chạy Server
│   ├── core_server.py                  # TCP Listener + UDP Discovery
│   ├── client_handler.py               # Luồng chuyên trách cho từng client
│   ├── session_manager.py              # Quản lý danh bạ online an toàn đa luồng
│   └── file_router.py                  # Định tuyến phiên truyền tệp và chunk
│
├── client/                             # Mã nguồn Máy trạm
│   ├── client_main.py                  # Entrypoint khởi chạy Client
│   ├── core_client.py                  # Socket client nền và event dispatcher
│   ├── file_transfer.py                # Phân mảnh, tái hợp và xác thực SHA-256
│   └── ui/                             # Giao diện người dùng
│       ├── gui_app.py                  # Giao diện đồ họa Tkinter (Progress Bar)
│       └── cli_app.py                  # Giao diện dòng lệnh Terminal
│
├── tests/                              # Bộ kiểm thử tự động
│   ├── test_protocol.py                # Unit test Protocol & Framing
│   ├── test_security.py                # Unit test mã hóa bảo mật
│   └── simulate_load.py                # Giả lập tải 15-20 clients đồng thời
│
├── requirements.txt                    # Thư viện phụ trợ
└── README.md                           # Hướng dẫn chi tiết dự án (File này)
```
