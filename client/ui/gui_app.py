"""
Module gui_app: Giao diện đồ họa người dùng trực quan viết bằng Tkinter (Milestone 9 - UI Integration).
Bao gồm: Danh sách thành viên trực tuyến, Khung chat thời gian thực,
Nút gửi file và Thanh tiến trình truyền file (Progress Bar).
"""

import os
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List

from client.core_client import CollaborationClient

BROADCAST_LABEL = "📢 TẤT CẢ (Broadcast)"
BROADCAST_TARGET = "__BROADCAST__"


class GuiApplication:
    """
    Ứng dụng Giao diện đồ họa (GUI) cho Collaboration Client.
    """

    def __init__(self, client: CollaborationClient):
        self.client = client
        self.root = tk.Tk()
        self.root.title("Distributed Client-Server Collaboration App (MMT261)")
        self.root.geometry("880x600")
        self.root.minsize(750, 500)

        # Trạng thái người dùng được chọn để chat ("__BROADCAST__" hoặc tên username)
        self.selected_target_user = BROADCAST_TARGET
        self.selected_target_display = "TẤT CẢ (Broadcast)"
        self.cached_users: List[dict] = []
        self.unread_users: set = set()
        self.unread_broadcast = False

        self._create_widgets()
        self._bind_client_events()

    def _create_widgets(self):
        # 1. Khung trên cùng: Thông tin trạng thái
        top_frame = ttk.Frame(self.root, padding=6)
        top_frame.pack(fill=tk.X)

        self.lbl_status = ttk.Label(
            top_frame,
            text=f"Đã đăng nhập với tư cách: {self.client.username or 'Chưa xác thực'}",
            font=("Segoe UI", 10, "bold"),
        )
        self.lbl_status.pack(side=tk.LEFT)

        btn_refresh = ttk.Button(top_frame, text="Làm mới danh sách", command=self.client.refresh_user_list)
        btn_refresh.pack(side=tk.RIGHT)

        # 2. Khung chính chia 2 cột: Trái (Danh sách user), Phải (Khung chat + file)
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        # --- CỘT TRÁI: Danh sách User Online ---
        left_frame = ttk.Labelframe(main_paned, text="Thành viên Online", padding=6)
        main_paned.add(left_frame, weight=1)

        self.user_listbox = tk.Listbox(left_frame, font=("Segoe UI", 10))
        self.user_listbox.pack(fill=tk.BOTH, expand=True)
        self.user_listbox.bind("<<ListboxSelect>>", self._on_user_select)

        lbl_hint = ttk.Label(left_frame, text="Chọn thành viên để Chat 1-1\nhoặc Gửi tệp", font=("Segoe UI", 8))
        lbl_hint.pack(pady=4)

        # --- CỘT PHẢI: Khung Chat và Gửi File ---
        right_frame = ttk.Labelframe(main_paned, text="Phòng Trò Chuyện & Chia Sẻ Tệp", padding=6)
        main_paned.add(right_frame, weight=3)

        # Tiêu đề mục chat hiện tại
        self.lbl_chat_target = ttk.Label(
            right_frame,
            text=f"Đang xem: {self.selected_target_display}",
            font=("Segoe UI", 10, "italic"),
            foreground="#0055aa",
        )
        self.lbl_chat_target.pack(anchor=tk.W, pady=2)

        # Khung hiển thị tin nhắn (Scrolled Text)
        self.txt_messages = tk.Text(right_frame, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 10))
        self.txt_messages.pack(fill=tk.BOTH, expand=True, pady=4)

        # Khung Tiến trình truyền file (Progress Bar)
        progress_frame = ttk.Frame(right_frame)
        progress_frame.pack(fill=tk.X, pady=2)

        self.lbl_progress = ttk.Label(progress_frame, text="Tiến trình tệp: Sẵn sàng", font=("Segoe UI", 9))
        self.lbl_progress.pack(anchor=tk.W)

        self.progress_bar = ttk.Progressbar(progress_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=2)

        # Khung nhập tin nhắn và nút thao tác
        bottom_frame = ttk.Frame(right_frame)
        bottom_frame.pack(fill=tk.X, pady=4)

        self.ent_message = ttk.Entry(bottom_frame, font=("Segoe UI", 10))
        self.ent_message.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.ent_message.bind("<Return>", lambda e: self._send_message())

        btn_send = ttk.Button(bottom_frame, text="Gửi tin", command=self._send_message)
        btn_send.pack(side=tk.LEFT, padx=2)

        btn_file = ttk.Button(bottom_frame, text="Gửi File 📎", command=self._open_file_dialog)
        btn_file.pack(side=tk.LEFT, padx=2)

    def _bind_client_events(self):
        """
        Đăng ký các callback từ CoreClient để cập nhật UI mượt mà.
        Sử dụng root.after() để đảm bảo tính an toàn giao diện (Thread-safe Tkinter).
        """
        self.client.on_user_list_updated = lambda users: self.root.after(0, self._update_user_list, users)
        self.client.on_message_received = self._on_message_received_safe
        self.client.on_chat_history_received = lambda tgt, msgs: self.root.after(0, self._render_chat_history, tgt, msgs)
        self.client.on_file_request_received = lambda s, n, sz, tid: self.root.after(0, self._show_file_request, s, n, sz, tid)
        self.client.on_file_progress = lambda tid, pct, is_up: self.root.after(0, self._update_progress, tid, pct, is_up)
        self.client.on_file_complete = lambda tid, name, path: self.root.after(0, self._on_file_done, name, path)
        self.client.on_error = lambda err: self.root.after(0, messagebox.showwarning, "Thông báo hệ thống", err)
        self.client.on_disconnected = lambda: self.root.after(0, self._on_disconnect_gui)

    def _on_message_received_safe(self, sender: str, text: str, is_private: bool, timestamp: str = None):
        if not timestamp:
            timestamp = time.strftime("%H:%M:%S")
        self.root.after(0, self._handle_incoming_message, sender, text, is_private, timestamp)

    def _update_user_list(self, users: List[dict]):
        self.cached_users = users
        self._render_user_listbox()

    def _render_user_listbox(self):
        """
        Cập nhật danh sách hiển thị người dùng, kèm huy hiệu (*) cho tin nhắn chưa đọc.
        """
        # Lưu lại index đang chọn nếu có
        current_selection = self.user_listbox.curselection()
        selected_idx = current_selection[0] if current_selection else None

        self.user_listbox.delete(0, tk.END)

        # Mục Broadcast
        bcast_text = "📢 TẤT CẢ (Broadcast) (*)" if self.unread_broadcast else "📢 TẤT CẢ (Broadcast)"
        self.user_listbox.insert(tk.END, bcast_text)

        # Các user
        idx_to_reselect = 0 if self.selected_target_user == BROADCAST_TARGET else None

        current_row = 1
        for u in self.cached_users:
            name = u['username']
            if name != self.client.username:
                badge = " (*)" if name in self.unread_users else ""
                self.user_listbox.insert(tk.END, f"👤 {name} ({u['ip']}){badge}")
                if self.selected_target_user == name:
                    idx_to_reselect = current_row
                current_row += 1

        if idx_to_reselect is not None:
            self.user_listbox.selection_set(idx_to_reselect)

    def _on_user_select(self, event):
        selection = self.user_listbox.curselection()
        if not selection:
            return
        selected_text = self.user_listbox.get(selection[0])
        if "TẤT CẢ" in selected_text:
            new_target = BROADCAST_TARGET
            self.selected_target_display = "TẤT CẢ (Broadcast)"
            self.unread_broadcast = False
        else:
            # Lấy tên username từ chuỗi "👤 alice (127.0.0.1) (*)"
            cleaned = selected_text.replace("👤", "").replace("(*)", "").strip()
            parts = cleaned.split(" ")
            new_target = parts[0]
            self.selected_target_display = f"Người dùng {new_target}"
            self.unread_users.discard(new_target)

        self.selected_target_user = new_target
        self.lbl_chat_target.config(text=f"Đang xem: {self.selected_target_display}")

        # Xóa trắng khung tin nhắn khi đổi đoạn chat
        self.txt_messages.config(state=tk.NORMAL)
        self.txt_messages.delete("1.0", tk.END)
        self.txt_messages.config(state=tk.DISABLED)

        # Cập nhật lại listbox để xóa dấu (*) nếu có
        self._render_user_listbox()

        # Tải lịch sử đoạn chat mới từ Server
        self.client.request_chat_history(self.selected_target_user)

    def _render_chat_history(self, target: str, messages: List[dict]):
        """
        Hiển thị toàn bộ lịch sử tin nhắn của đoạn chat được tải về từ Server.
        """
        # Chỉ cập nhật nếu phản hồi lịch sử đúng cho phòng đang mở
        if target != self.selected_target_user:
            return

        self.txt_messages.config(state=tk.NORMAL)
        self.txt_messages.delete("1.0", tk.END)

        for msg in messages:
            sender = msg.get("sender", "")
            text = msg.get("text", "")
            timestamp = msg.get("timestamp", "")
            is_private = msg.get("is_private", False)

            if sender == self.client.username:
                disp_sender = f"Tôi -> {msg.get('target', '')}" if is_private else "Tôi (Chung)"
            else:
                disp_sender = sender

            self._insert_message_line(disp_sender, text, is_private, timestamp)

        self.txt_messages.config(state=tk.DISABLED)
        self.txt_messages.see(tk.END)

    def _handle_incoming_message(self, sender: str, text: str, is_private: bool, timestamp: str):
        """
        Xử lý tin nhắn thời gian thực gửi từ người khác.
        """
        if not is_private:
            # Tin nhắn broadcast
            if self.selected_target_user == BROADCAST_TARGET:
                self._append_message(sender, text, is_private=False, timestamp=timestamp)
            else:
                self.unread_broadcast = True
                self._render_user_listbox()
        else:
            # Tin nhắn 1-1
            if self.selected_target_user == sender:
                self._append_message(sender, text, is_private=True, timestamp=timestamp)
            else:
                self.unread_users.add(sender)
                self._render_user_listbox()

    def _send_message(self):
        text = self.ent_message.get().strip()
        if not text:
            return

        now_ts = time.strftime("%H:%M:%S")

        if self.selected_target_user == BROADCAST_TARGET:
            self.client.send_broadcast(text)
            self._append_message("Tôi (Chung)", text, is_private=False, timestamp=now_ts)
        else:
            self.client.send_unicast(self.selected_target_user, text)
            self._append_message(f"Tôi -> {self.selected_target_user}", text, is_private=True, timestamp=now_ts)

        self.ent_message.delete(0, tk.END)

    def _append_message(self, sender: str, text: str, is_private: bool, timestamp: str = None):
        self.txt_messages.config(state=tk.NORMAL)
        self._insert_message_line(sender, text, is_private, timestamp)
        self.txt_messages.config(state=tk.DISABLED)
        self.txt_messages.see(tk.END)

    def _insert_message_line(self, sender: str, text: str, is_private: bool, timestamp: str = None):
        tag = "private" if is_private else "public"
        time_prefix = f"[{timestamp}] " if timestamp else ""
        prefix = f"{time_prefix}[{sender}]: "

        self.txt_messages.insert(tk.END, prefix, tag)
        self.txt_messages.insert(tk.END, f"{text}\n")
        self.txt_messages.tag_config("private", foreground="#b30000", font=("Consolas", 10, "bold"))
        self.txt_messages.tag_config("public", foreground="#003366", font=("Consolas", 10, "bold"))

    def _open_file_dialog(self):
        if self.selected_target_user == BROADCAST_TARGET:
            messagebox.showinfo("Chọn người nhận", "Vui lòng chọn một người dùng cụ thể từ danh sách bên trái để gửi file!")
            return

        filepath = filedialog.askopenfilename(title=f"Chọn file gửi cho {self.selected_target_user}")
        if filepath:
            filename = os.path.basename(filepath)
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            self.lbl_progress.config(text=f"Đang xin phép gửi '{filename}' ({size_mb:.2f} MB)...")
            self.client.send_file_request(self.selected_target_user, filepath)

    def _show_file_request(self, sender: str, filename: str, filesize: int, transfer_id: str):
        size_kb = filesize / 1024
        result = messagebox.askyesno(
            "Yêu cầu nhận tệp",
            f"Người dùng '{sender}' muốn gửi tệp:\n\n'{filename}' ({size_kb:.1f} KB)\n\nBạn có đồng ý nhận không?",
        )
        self.client.respond_file_request(transfer_id, accept=result)
        if result:
            self.lbl_progress.config(text=f"Đang nhận tệp '{filename}'...")

    def _update_progress(self, transfer_id: str, percent: float, is_upload: bool):
        action = "Tải lên" if is_upload else "Tải xuống"
        self.progress_bar["value"] = percent
        self.lbl_progress.config(text=f"{action} [ID: {transfer_id}]: {percent:.1f}%")

    def _on_file_done(self, filename: str, path: str):
        self.progress_bar["value"] = 100.0
        self.lbl_progress.config(text=f"Hoàn tất: '{filename}'")
        messagebox.showinfo("Truyền file thành công", f"Tệp '{filename}' đã được truyền và kiểm tra toàn vẹn SHA-256 thành công!\n\nLưu tại: {path}")

    def _on_disconnect_gui(self):
        messagebox.showwarning("Mất kết nối", "Kết nối tới máy chủ đã bị ngắt.")
        self.root.destroy()

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Tự động load danh sách user và tải trước lịch sử broadcast lần đầu
        self.client.refresh_user_list()
        self.client.request_chat_history(BROADCAST_TARGET)
        self.root.mainloop()

    def _on_close(self):
        self.client.disconnect()
        self.root.destroy()
