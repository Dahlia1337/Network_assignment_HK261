"""
Module file_transfer: Hiện thực hóa thuật toán truyền file phân mảnh (Chunking)
và tái hợp (Reassembly) kèm kiểm tra mã băm SHA-256 (Milestone 6 - Reliable File Transfer).
"""

import base64
import hashlib
import os
from typing import Callable, Dict, Optional, Set, Tuple

from common.constants import FILE_CHUNK_SIZE, UDP_CHUNK_SIZE


def calculate_sha256(filepath: str) -> str:
    """
    Tính toán mã băm SHA-256 của tệp để kiểm chứng tính toàn vẹn (Data Integrity).
    Đọc theo từng block để không gây tràn RAM khi file có dung lượng lớn.
    """
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


class FileSender:
    """
    Quản lý việc đọc file, phân mảnh nhị phân thô và phục vụ các chunk cho UDP streaming.
    """

    def __init__(self, filepath: str, chunk_size: int = UDP_CHUNK_SIZE):
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Không tìm thấy file: {filepath}")

        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.filesize = os.path.getsize(filepath)
        self.chunk_size = chunk_size
        self.sha256 = calculate_sha256(filepath)
        self.total_chunks = (self.filesize + chunk_size - 1) // chunk_size if self.filesize > 0 else 1

    def get_chunk_bytes(self, chunk_index: int) -> bytes:
        """
        Đọc trực tiếp byte nhị phân thô của chunk_index từ đĩa (không mã hóa Base64).
        """
        if chunk_index < 0 or chunk_index >= self.total_chunks:
            return b""
        with open(self.filepath, "rb") as f:
            f.seek(chunk_index * self.chunk_size)
            return f.read(self.chunk_size)

    def iter_chunks(self, progress_callback: Optional[Callable[[float], None]] = None):
        """
        Generator sinh từng khối dữ liệu nhị phân thô kèm số thứ tự.
        """
        bytes_sent = 0
        with open(self.filepath, "rb") as f:
            for chunk_idx in range(self.total_chunks):
                data = f.read(self.chunk_size)
                bytes_sent += len(data)
                percent = (bytes_sent / self.filesize * 100.0) if self.filesize > 0 else 100.0

                if progress_callback:
                    progress_callback(percent)

                yield {
                    "chunk_index": chunk_idx,
                    "total_chunks": self.total_chunks,
                    "raw_bytes": data,
                }


class FileReceiver:
    """
    Quản lý việc tiếp nhận các khối chunk nhị phân UDP, hỗ trợ sắp xếp các chunk đến lệch thứ tự (out-of-order),
    ghi tệp tạm (.part) và xác minh SHA-256 sau khi hoàn tất.
    """

    def __init__(self, save_dir: str, filename: str, filesize: int, expected_sha256: str):
        os.makedirs(save_dir, exist_ok=True)
        self.save_dir = save_dir
        self.final_filepath = os.path.join(save_dir, filename)
        self.temp_filepath = os.path.join(save_dir, f"{filename}.part")
        self.filesize = filesize
        self.expected_sha256 = expected_sha256

        self.bytes_received = 0
        self.total_chunks = 0
        self.received_chunks: Set[int] = set()
        self._buffered_chunks: Dict[int, bytes] = {}
        self._next_chunk_to_write: int = 0

        # Khởi tạo file tạm rỗng
        self._file_handle = open(self.temp_filepath, "wb")

    def write_raw_chunk(self, chunk_index: int, total_chunks: int, raw_bytes: bytes) -> float:
        """
        Tiếp nhận một khối dữ liệu nhị phân thô, lưu đệm và sắp xếp đúng thứ tự trước khi ghi xuống file tạm.
        :return: Phần trăm hoàn thành hiện tại (0.0 - 100.0).
        """
        self.total_chunks = total_chunks

        # Nếu chunk này đã được ghi/nhận trước đó (do gói tin retransmit đến trễ), bỏ qua việc ghi đè
        if chunk_index in self.received_chunks:
            percent = (len(self.received_chunks) / self.total_chunks * 100.0) if self.total_chunks > 0 else 100.0
            return min(percent, 100.0)

        self.received_chunks.add(chunk_index)
        self._buffered_chunks[chunk_index] = raw_bytes

        # Ghi liên tục các chunk nối tiếp đúng thứ tự từ bộ đệm vào đĩa
        while self._next_chunk_to_write in self._buffered_chunks:
            data = self._buffered_chunks.pop(self._next_chunk_to_write)
            self._file_handle.write(data)
            self._file_handle.flush()
            self.bytes_received += len(data)
            self._next_chunk_to_write += 1

        percent = (len(self.received_chunks) / self.total_chunks * 100.0) if self.total_chunks > 0 else 100.0
        return min(percent, 100.0)

    def write_chunk(self, chunk_index: int, total_chunks: int, data_b64: str) -> float:
        """
        Tương thích ngược: ghi chunk dạng base64.
        """
        raw_data = base64.b64decode(data_b64)
        return self.write_raw_chunk(chunk_index, total_chunks, raw_data)

    def finalize_and_verify(self) -> Tuple[bool, str]:
        """
        Đóng file tạm và đối soát mã băm SHA-256 với mã kỳ vọng.
        :return: (True, filepath) nếu toàn vẹn, (False, lỗi) nếu hỏng dữ liệu.
        """
        # Nếu còn chunk trong bộ đệm (hiếm khi xảy ra nếu đã đủ total_chunks), ghi nốt theo thứ tự
        sorted_indices = sorted(self._buffered_chunks.keys())
        for idx in sorted_indices:
            self._file_handle.write(self._buffered_chunks[idx])
        self._buffered_chunks.clear()

        self._file_handle.close()

        actual_sha256 = calculate_sha256(self.temp_filepath)
        if actual_sha256.lower() != self.expected_sha256.lower():
            # Xóa file tạm bị hỏng để bảo đảm an toàn
            try:
                os.remove(self.temp_filepath)
            except Exception:
                pass
            return False, f"Lỗi toàn vẹn: SHA-256 thực tế ({actual_sha256}) không khớp kỳ vọng ({self.expected_sha256})"

        # Đổi tên file tạm thành file chính thức
        if os.path.exists(self.final_filepath):
            os.remove(self.final_filepath)
        os.rename(self.temp_filepath, self.final_filepath)
        return True, self.final_filepath

    def cancel(self):
        """
        Hủy phiên nhận và dọn dẹp file tạm.
        """
        try:
            self._file_handle.close()
            if os.path.exists(self.temp_filepath):
                os.remove(self.temp_filepath)
        except Exception:
            pass
