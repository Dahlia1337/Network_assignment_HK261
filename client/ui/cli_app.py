"""
Module cli_app: Giao diện dòng lệnh tương tác trực tiếp (Milestone 9 - CLI Integration).
Cho phép chat và nhận thông báo trong terminal.
"""

import sys
import time
from typing import List

from client.core_client import CollaborationClient


class CliApplication:
    """
    Ứng dụng giao diện CLI thân thiện.
    """

    def __init__(self, client: CollaborationClient):
        self.client = client
        self.running = True
        self._setup_callbacks()

    def _setup_callbacks(self):
        self.client.on_login_result = self._on_login
        self.client.on_user_list_updated = self._on_user_list
        self.client.on_user_joined = lambda u: print(f"\n[+] Người dùng '{u}' vừa tham gia.")
        self.client.on_user_left = lambda u: print(f"\n[-] Người dùng '{u}' đã rời khỏi mạng.")
        self.client.on_message_received = self._on_message
        self.client.on_file_request_received = self._on_file_req
        self.client.on_file_progress = self._on_file_progress
        self.client.on_file_complete = self._on_file_complete
        self.client.on_error = lambda err: print(f"\n[!] CẢNH BÁO: {err}")
        self.client.on_disconnected = self._on_disconnect

    def _on_login(self, success: bool, msg: str):
        if success:
            print(f"\n[✓] {msg}")
            print("Gõ /help để xem danh sách các lệnh hỗ trợ.\n")
        else:
            print(f"\n[X] Đăng nhập thất bại: {msg}")

    def _on_user_list(self, users: List[dict]):
        print("\n--- DANH SÁCH THÀNH VIÊN TRỰC TUYẾN ---")
        for u in users:
            print(f"  • {u['username']} ({u['ip']}:{u['port']})")
        print("---------------------------------------")

    def _on_message(self, sender: str, text: str, is_private: bool, timestamp: str = None):
        time_prefix = f"[{timestamp}] " if timestamp else ""
        prefix = f"{time_prefix}[RIÊNG TỪ {sender}]" if is_private else f"{time_prefix}[{sender}]"
        print(f"\n{prefix}: {text}")

    def _on_file_req(self, sender: str, filename: str, filesize: int, transfer_id: str):
        kb_size = filesize / 1024
        print(f"\n[FILE] '{sender}' muốn gửi tệp: '{filename}' ({kb_size:.1f} KB)")
        print(f"       Gõ '/accept {transfer_id}' để nhận hoặc '/reject {transfer_id}' để từ chối.")

    def _on_file_progress(self, transfer_id: str, percent: float, is_upload: bool):
        action = "Đang tải lên" if is_upload else "Đang nhận"
        bars = int(percent // 5)
        bar_str = "=" * bars + "-" * (20 - bars)
        sys.stdout.write(f"\r[FILE {transfer_id}] {action}: [{bar_str}] {percent:.1f}%")
        sys.stdout.flush()
        if percent >= 100.0:
            print()

    def _on_file_complete(self, transfer_id: str, filename: str, filepath: str):
        print(f"\n[✓ FILE] Hoàn tất nhận/gửi tệp '{filename}' an toàn tại: {filepath}")

    def _on_disconnect(self):
        print("\n[!] Đã ngắt kết nối với máy chủ.")
        self.running = False

    def run_loop(self):
        """
        Vòng lặp đọc lệnh từ người dùng.
        """
        while self.running and self.client.is_connected:
            try:
                line = input().strip()
                if not line:
                    continue
                if line.startswith("/"):
                    self._handle_command(line)
                else:
                    # Mặc định là gửi tin nhắn broadcast
                    self.client.send_broadcast(line)
            except (KeyboardInterrupt, EOFError):
                break
        self.client.disconnect()

    def _handle_command(self, cmd_line: str):
        parts = cmd_line.split(" ", 2)
        cmd = parts[0].lower()

        if cmd == "/help":
            print("""
Các lệnh khả dụng:
  <tin_nhắn>                     : Gửi tin nhắn đến phòng chat chung (Broadcast)
  /msg <user> <nội_dung>         : Gửi tin nhắn riêng đến 1 người (Unicast)
  /send <user> <đường_dẫn_file>  : Gửi tệp tin cậy đến người dùng
  /accept <id>                   : Chấp thuận nhận file
  /reject <id>                   : Từ chối nhận file
  /list                          : Xem danh sách thành viên online
  /quit                          : Đăng xuất và thoát
""")
        elif cmd == "/list":
            self.client.refresh_user_list()
        elif cmd == "/msg":
            if len(parts) < 3:
                print("Cú pháp: /msg <username> <nội_dung>")
                return
            target_user = parts[1]
            text = parts[2]
            self.client.send_unicast(target_user, text)
            print(f"[ĐÃ GỬI TỚI {target_user}]: {text}")
        elif cmd == "/send":
            if len(parts) < 3:
                print("Cú pháp: /send <username> <đường_dẫn_file>")
                return
            target_user = parts[1]
            filepath = parts[2]
            print(f"[*] Đang gửi yêu cầu truyền file '{filepath}' đến '{target_user}'...")
            self.client.send_file_request(target_user, filepath)
        elif cmd == "/accept":
            if len(parts) < 2:
                print("Cú pháp: /accept <transfer_id>")
                return
            self.client.respond_file_request(parts[1], accept=True)
            print(f"[*] Đã chấp thuận nhận file [ID: {parts[1]}]")
        elif cmd == "/reject":
            if len(parts) < 2:
                print("Cú pháp: /reject <transfer_id>")
                return
            self.client.respond_file_request(parts[1], accept=False)
            print(f"[*] Đã từ chối file [ID: {parts[1]}]")
        elif cmd in ("/quit", "/exit"):
            self.running = False
        else:
            print(f"Lệnh không hợp lệ: {cmd}. Gõ /help để được hướng dẫn.")
