# ĐẶC TẢ GIAO THỨC TẦNG ỨNG DỤNG (PROTOCOL SPECIFICATION)
## DISTRIBUTED COLLABORATION PROTOCOL (DCP v1.0)
**Môn học:** Phát triển Ứng dụng Mạng (MMT261)  

---

## 1. TỔNG QUAN
Giao thức **Distributed Collaboration Protocol (DCP v1.0)** là giao thức tầng ứng dụng được thiết kế riêng chạy trên nền giao thức truyền tải tin cậy **TCP** (Transmission Control Protocol), kết hợp **UDP** cho tính năng tìm kiếm máy chủ (Discovery).

Để giải quyết bản chất hướng dòng (stream-oriented) của TCP dẫn đến hiện tượng **Dính gói (Packet Sticking / Coalescing)** và **Phân mảnh (Packet Fragmentation)**, DCP sử dụng kỹ thuật **Đóng khung bằng tiền tố độ dài (Length-Prefixed Framing)** với cấu trúc Header kích thước cố định **12 Bytes**.

---

## 2. CẤU TRÚC GÓI TIN TỔNG QUÁT (PACKET STRUCTURE)

Mỗi gói tin DCP bao gồm hai phần:
```
+-------------------------------------------------------------+
|                 HEADER CỐ ĐỊNH (12 BYTES)                   |
+-------------------------------------------------------------+
|                     PAYLOAD DỮ LIỆU                         |
|     (Đã mã hóa AES, kích thước = Payload Length Bytes)      |
+-------------------------------------------------------------+
```

### 2.1. Bản đồ Byte của Header (Header Bit/Byte Layout):
```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|       MAGIC (2 Bytes)         |       VERSION (1B)    |FLAGS(1)|
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|       MSG TYPE (2 Bytes)      |          RESERVED (2 Bytes)   |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                     PAYLOAD LENGTH (4 Bytes)                  |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### 2.2. Chi tiết các trường Header:

| Tên trường | Kiểu dữ liệu | Kích thước | Thứ tự Byte | Mô tả & Ý nghĩa |
| :--- | :---: | :---: | :---: | :--- |
| **Magic Number** | `uint16` | 2 Bytes | Big-Endian | Giá trị cố định `0xAA55` (43605). Dùng để xác thực đây là gói tin DCP hợp lệ, loại bỏ các kết nối rác. |
| **Version** | `uint8` | 1 Byte | - | Phiên bản giao thức (hiện tại là `0x01`). |
| **Flags** | `uint8` | 1 Byte | - | Cờ điều khiển: <br>• Bit 0 (`0x01`): Payload được mã hóa AES (FLAG_ENCRYPTED). <br>• Bit 1 (`0x02`): Payload được nén (FLAG_COMPRESSED). <br>• `0x00`: Dữ liệu Plaintext. |
| **Message Type** | `uint16` | 2 Bytes | Big-Endian | Mã lệnh định danh loại hành động cần thực thi (Xem Bảng Message Types). |
| **Reserved** | `uint16` | 2 Bytes | Big-Endian | Dự phòng cho việc nâng cấp giao thức trong tương lai (giá trị mặc định `0x0000`). |
| **Payload Length** | `uint32` | 4 Bytes | Big-Endian | Kích thước chính xác (tính theo byte) của phần Payload theo sau. Cho phép payload tối đa 4GB. |

---

## 3. DANH MỤC CÁC LOẠI THÔNG ĐIỆP (MESSAGE TYPES)

### 3.1. Nhóm Xác thực & Khởi tạo phiên
* **`AUTH_REQ` (`0x0001`):** Client gửi yêu cầu đăng nhập.
  * *Payload (JSON):* `{"username": "Alice"}`
* **`AUTH_SUCCESS` (`0x0002`):** Server xác nhận đăng nhập thành công.
  * *Payload (JSON):* `{"message": "Chào mừng...", "username": "Alice"}`
* **`AUTH_FAIL` (`0x0003`):** Server từ chối đăng nhập.
  * *Payload (JSON):* `{"reason": "Tên đã tồn tại"}`

### 3.2. Nhóm Định danh & Khám phá người dùng (User Discovery)
* **`USER_LIST_REQ` (`0x0010`):** Client yêu cầu danh sách các thành viên online.
  * *Payload:* Rỗng.
* **`USER_LIST_RESP` (`0x0011`):** Server trả lời danh sách người dùng online.
  * *Payload (JSON):* `{"users": [{"username": "Alice", "ip": "127.0.0.1", "port": 54321}, ...]}`
* **`USER_JOIN_BROADCAST` (`0x0012`):** Server báo cho các client khác có thành viên mới online.
  * *Payload (JSON):* `{"username": "Bob", "ip": "127.0.0.1", "port": 54322}`
* **`USER_LEAVE_BROADCAST` (`0x0013`):** Server thông báo có thành viên vừa ngắt kết nối.
  * *Payload (JSON):* `{"username": "Bob"}`

### 3.3. Nhóm Tin nhắn văn bản thời gian thực (Real-time Messaging)
* **`MSG_BROADCAST` (`0x0020`):** Tin nhắn phòng chat chung.
  * *Payload (JSON):* `{"sender": "Alice", "text": "Chào cả phòng!"}`
* **`MSG_UNICAST` (`0x0021`):** Tin nhắn trò chuyện riêng 1-1.
  * *Payload (JSON):* `{"sender": "Alice", "target": "Bob", "text": "Tin nhắn riêng tư"}`

### 3.4. Nhóm Truyền tệp tin cậy (Reliable File Transfer)
* **`FILE_TRANSFER_REQ` (`0x0030`):** Đề nghị gửi tệp kèm thông số kiểm tra toàn vẹn.
  * *Payload (JSON):* `{"target": "Bob", "filename": "report.pdf", "filesize": 1048576, "sha256": "e3b0c44298fc1c..."}`
* **`FILE_TRANSFER_ACCEPT` (`0x0031`):** Người nhận chấp thuận tải tệp.
  * *Payload (JSON):* `{"transfer_id": "a1b2c3d4"}`
* **`FILE_TRANSFER_REJECT` (`0x0032`):** Người nhận từ chối tệp.
  * *Payload (JSON):* `{"transfer_id": "a1b2c3d4", "reason": "Không có nhu cầu"}`
* **`FILE_CHUNK_DATA` (`0x0033`):** Khối dữ liệu phân mảnh của tệp (32 KB/chunk).
  * *Payload (JSON):* `{"transfer_id": "a1b2c3d4", "chunk_index": 0, "total_chunks": 32, "data_b64": "<base64_data>"}`
* **`FILE_TRANSFER_COMPLETE` (`0x0035`):** Thông báo hoàn tất truyền tệp.
  * *Payload (JSON):* `{"transfer_id": "a1b2c3d4"}`

### 3.5. Nhóm Quản lý kết nối & Trạng thái mạng
* **`HEARTBEAT_PING` (`0x0090`):** Gói kiểm tra kết nối sống (Keep-alive).
* **`HEARTBEAT_PONG` (`0x0091`):** Phản hồi gói giữ kết nối.
* **`DISCONNECT_REQ` (`0x00FE`):** Client thông báo đóng kết nối chuẩn mực (Graceful Disconnect).

---

## 4. GIẢI THUẬT XỬ LÝ DÒNG TCP STREAM (FRAMING ALGORITHM)

### 4.1. Phía gửi (Sender Side):
1. Chuẩn bị `data` (chuỗi văn bản hoặc JSON).
2. Mã hóa dữ liệu bằng khóa bí mật đối xứng AES (nếu cờ `FLAG_ENCRYPTED = 1`).
3. Tính toán `payload_length = len(encrypted_bytes)`.
4. Đóng gói Header 12 bytes theo thứ tự mạng (Network Byte Order - Big Endian):
   `struct.pack("!HBBHHI", 0xAA55, 1, flags, msg_type, 0, payload_length)`
5. Ghép `header + encrypted_bytes` và truyền toàn bộ qua `socket.sendall()`.

### 4.2. Phía nhận (Receiver Side):
1. **Bước 1 (Đọc Header):** Gọi vòng lặp `read_exact(12)` để nhận đủ chính xác 12 bytes Header cố định.
2. **Bước 2 (Giải nén Header):** Sử dụng `struct.unpack("!HBBHHI", header_bytes)`. Xác thực Magic Number `0xAA55`.
3. **Bước 3 (Đọc Payload):** Lấy giá trị `payload_length`. Gọi tiếp vòng lặp `read_exact(payload_length)` cho tới khi nhận đủ chính xác số byte này từ dòng TCP.
4. **Bước 4 (Giải mã & Khôi phục):** Nếu cờ `FLAG_ENCRYPTED` được bật, giải mã chuỗi byte vừa nhận bằng khóa AES, sau đó phân tích dữ liệu JSON/text về dạng ban đầu.
