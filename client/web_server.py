"""
Module web_server: Local Web Gateway phục vụ giao diện HTML/CSS/JS
và cung cấp REST API + Server-Sent Events (SSE) cho Client phân tán.
"""


import cgi
import json
import logging
import os
import queue
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

logger = logging.getLogger("WebServer")

# Hàng đợi SSE Thread-safe cho các kết nối Web UI đang mở
sse_queues = []
sse_lock = threading.Lock()

def broadcast_sse(event_type: str, data: dict):
    """Đẩy sự kiện JSON xuống tất cả các tab trình duyệt đang mở của Client này."""
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    with sse_lock:
        for q in sse_queues:
            q.put(payload)

def bind_client_events(client):
    """Đăng ký callback từ core_client để chuyển tiếp thành sự kiện SSE."""
    client.on_login_result = lambda success, msg: broadcast_sse("login_result", {"success": success, "message": msg})
    client.on_register_result = lambda success, msg: broadcast_sse("register_result", {"success": success, "message": msg})
    client.on_message_received = lambda sender, text, is_private, timestamp="": broadcast_sse("message_received", {
        "sender": sender, "text": text, "is_private": is_private, "timestamp": timestamp
    })
    client.on_user_list_updated = lambda users: broadcast_sse("user_list_updated", {"users": users})
    client.on_user_joined = lambda u: broadcast_sse("user_joined", {"username": u})
    client.on_user_left = lambda u: broadcast_sse("user_left", {"username": u})
    client.on_chat_history_received = lambda target, messages: broadcast_sse("chat_history", {"target": target, "messages": messages})
    client.on_file_request_received = lambda sender, name, size, tid: broadcast_sse("file_request", {
        "sender": sender, "filename": name, "filesize": size, "transfer_id": tid
    })
    client.on_file_progress = lambda tid, percent, is_up: broadcast_sse("file_progress", {
        "transfer_id": tid, "percent": percent, "is_upload": is_up
    })
    client.on_file_complete = lambda tid, name, path: broadcast_sse("file_complete", {
        "transfer_id": tid, "filename": name, "filepath": path
    })
    client.on_error = lambda msg: broadcast_sse("error", {"message": msg})


class WebGatewayHandler(SimpleHTTPRequestHandler):
    client = None  # Sẽ được inject vào class trước khi chạy

    def __init__(self, *args, **kwargs):
        # Chỉ định thư mục gốc phục vụ file tĩnh là client/ui/web/
        web_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "ui"))
        super().__init__(*args, directory=web_dir, **kwargs)

    def handle(self):
        """Bắt và bỏ qua lỗi khi trình duyệt chủ động ngắt kết nối đột ngột (chuyển trang, f5)"""
        try:
            super().handle()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # Client đã đóng socket, không cần xử lý thêm

    def do_GET(self):
        parsed_path = urlparse(self.path)
        
        # Tự động điều hướng trang chủ về màn hình đăng nhập
        if parsed_path.path == "/":
            self.send_response(302)
            self.send_header("Location", "/login.html")
            self.end_headers()
            return
            
        # Bỏ qua lỗi tìm kiếm favicon của trình duyệt để tránh rác log
        if parsed_path.path == "/favicon.ico":
            self.send_response(204) # No Content
            self.end_headers()
            return

        if parsed_path.path == "/api/events":
            self.handle_sse_stream()
        else:
            super().do_GET()

        if parsed_path.path == "/api/events":
            self.handle_sse_stream()
        elif parsed_path.path == "/api/users":
            users = getattr(self.client, "cached_users", [])
            self.send_json_response(200, {"users": users})
        else:
            super().do_GET()

    def do_POST(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        if path == "/api/upload_temp":
            self.handle_file_upload()
            return

        # Xử lý các REST API truyền JSON
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self.send_json_response(400, {"success": False, "message": "Invalid JSON"})
            return

        if path == "/api/login":
            self.client.login(data.get("username", ""), data.get("password", ""))
            self.send_json_response(200, {"success": True, "message": "Đã gửi yêu cầu đăng nhập"})
            
        elif path == "/api/register":
            self.client.register(data.get("username", ""), data.get("password", ""))
            self.send_json_response(200, {"success": True, "message": "Đã gửi yêu cầu đăng ký"})

        elif path == "/api/send_message":
            target = data.get("target")
            text = data.get("text", "")
            if data.get("is_private"):
                self.client.send_unicast(target, text)
            else:
                self.client.send_broadcast(text)
            self.send_json_response(200, {"success": True})

        elif path == "/api/refresh_users":
            self.client.refresh_user_list()
            self.send_json_response(200, {"success": True})

        elif path == "/api/chat_history":
            self.client.request_chat_history(data.get("target"))
            self.send_json_response(200, {"success": True})

        elif path == "/api/send_file":
            filepath = data.get("filepath")
            if filepath and os.path.exists(filepath):
                self.client.send_file_request(data.get("target_user"), filepath)
                self.send_json_response(200, {"success": True})
            else:
                self.send_json_response(404, {"success": False, "message": "Không tìm thấy file trên đĩa"})

        elif path == "/api/respond_file":
            self.client.respond_file_request(data.get("transfer_id"), data.get("accept", False))
            self.send_json_response(200, {"success": True})

        else:
            self.send_json_response(404, {"success": False, "message": "Endpoint not found"})

    def handle_sse_stream(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()

        q = queue.Queue()
        with sse_lock:
            sse_queues.append(q)

        # Đẩy ngay danh sách user đang có trong cache cho tab vừa mở
        if hasattr(self.client, "cached_users") and self.client.cached_users:
            init_payload = f"event: user_list_updated\ndata: {json.dumps({'users': self.client.cached_users})}\n\n"
            q.put(init_payload)

        # Yêu cầu Server cập nhật bản mới nhất
        if self.client:
            self.client.refresh_user_list()

        try:
            while True:
                event_data = q.get()
                self.wfile.write(event_data.encode('utf-8'))
                self.wfile.flush()
        except Exception:
            pass
        finally:
            with sse_lock:
                if q in sse_queues:
                    sse_queues.remove(q)

    def handle_file_upload(self):
        """Xử lý nhận file upload từ trình duyệt và lưu vào thư mục uploads/ cục bộ."""
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': self.headers['Content-Type']}
            )
            if 'file' not in form:
                self.send_json_response(400, {"success": False, "message": "No file uploaded"})
                return

            file_item = form['file']
            filename = os.path.basename(file_item.filename)
            upload_dir = os.path.abspath("./uploads")
            os.makedirs(upload_dir, exist_ok=True)
            filepath = os.path.join(upload_dir, filename)

            with open(filepath, 'wb') as f:
                f.write(file_item.file.read())

            self.send_json_response(200, {"success": True, "filepath": filepath})
        except Exception as e:
            logger.error(f"Lỗi upload file: {e}")
            self.send_json_response(500, {"success": False, "message": str(e)})

    def send_json_response(self, status_code, payload):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode('utf-8'))

    def log_message(self, format, *args):
        # Format toàn bộ chuỗi log trước khi kiểm tra
        msg = format % args
        # Tắt bớt log request GET tĩnh để tránh rác màn hình terminal
        if "GET /api/events" not in msg and "GET /favicon.ico" not in msg:
            logger.debug(f"{self.address_string()} - {msg}")


def run_web_server(client, host="0.0.0.0", port=5000):
    bind_client_events(client)
    WebGatewayHandler.client = client
    server = ThreadingHTTPServer((host, port), WebGatewayHandler)
    server.serve_forever()