let currentMode = 'login'; // Auth state
let currentTarget = '__BROADCAST__';
let currentUser = sessionStorage.getItem('username') || '';
let pendingTransferId = '';
const unreadUsers = new Set();
const authForm = document.getElementById('auth-form');
const chatMessages = document.getElementById('chat-messages');

// ================= AUTH LOGIC =================
function switchTab(mode) {
    currentMode = mode;
    document.getElementById('tab-login').classList.toggle('active', mode === 'login');
    document.getElementById('tab-register').classList.toggle('active', mode === 'register');
    document.getElementById('submit-btn').innerText = mode === 'login' ? 'Đăng Nhập' : 'Đăng Ký';
    document.getElementById('auth-msg').innerText = '';
}

async function handleAuth(e) {
    e.preventDefault();
    const user = document.getElementById('username').value;
    const pass = document.getElementById('password').value;
    currentUser = user;
    sessionStorage.setItem('username', user);
    
    await fetch(`/api/${currentMode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: user, password: pass })
    });
}

// ================= SSE CONNECTION =================
const evtSource = new EventSource('/api/events');

evtSource.addEventListener('login_result', (e) => {
    const data = JSON.parse(e.data);
    if (!authForm) return; 
    if (data.success) window.location.href = '/index.html';
    else document.getElementById('auth-msg').innerText = data.message;
});

evtSource.addEventListener('register_result', (e) => {
    const data = JSON.parse(e.data);
    if (authForm) document.getElementById('auth-msg').innerText = data.message;
});

evtSource.addEventListener('user_list_updated', (e) => {
    if (!chatMessages) return;
    const users = JSON.parse(e.data).users;
    const list = document.getElementById('user-list');
    list.innerHTML = '';
    users.forEach(u => {
        // Trích xuất username nếu u là object
        const username = typeof u === 'object' && u !== null ? u.username : u;
        if (username === currentUser) return;

        const div = document.createElement('div');
        div.className = `peer-item ${currentTarget === username ? 'active' : ''}`;
        div.id = `peer-${username}`;
        div.innerText = username;
        div.onclick = () => selectTarget(username);
        list.appendChild(div);
        if (unreadUsers.has(username)) {
            const dot = document.createElement('span');
            dot.className = 'unread-dot';
            div.appendChild(dot);
        }
    });
});

evtSource.addEventListener('message_received', (e) => {
    if (!chatMessages) return;
    const data = JSON.parse(e.data);
    const isBroadcast = !data.is_private;
    const intendedTarget = isBroadcast ? '__BROADCAST__' : (data.sender === currentUser ? data.target : data.sender);
    
    if (currentTarget === intendedTarget) {
        appendMessage(data.sender, data.text, data.sender === currentUser ? 'self' : 'other');
    } else {
        unreadUsers.add(intendedTarget);
        const peerElement = document.getElementById(`peer-${intendedTarget}`);
        if (peerElement && !peerElement.querySelector('.unread-dot')) {
            const dot = document.createElement('span');
            dot.className = 'unread-dot';
            peerElement.appendChild(dot);
        }
    }
});

evtSource.addEventListener('chat_history', (e) => {
    if (!chatMessages) return;
    chatMessages.innerHTML = '';
    JSON.parse(e.data).messages.forEach(msg => {
        appendMessage(msg.sender, msg.text, msg.sender === currentUser ? 'self' : 'other');
    });
});

// ================= FILE TRANSFER LOGIC =================
evtSource.addEventListener('file_request', (e) => {
    if (!chatMessages) return;
    const data = JSON.parse(e.data);
    pendingTransferId = data.transfer_id;
    document.getElementById('file-modal-desc').innerText = `${data.sender} muốn gửi file: ${data.filename}\nKích thước: ${(data.filesize/1024).toFixed(1)} KB`;
    document.getElementById('file-modal').classList.remove('hidden');
});

evtSource.addEventListener('file_progress', (e) => {
    if (!chatMessages) return;
    const data = JSON.parse(e.data);
    document.getElementById('progress-box').classList.remove('hidden');
    document.getElementById('progress-text').innerText = data.is_upload ? '📤 Đang tải lên...' : '📥 Đang tải về...';
    document.getElementById('progress-bar').style.width = `${data.percent}%`;
    
    // Chunk count display logic
    if (data.total_chunks) {
        document.getElementById('progress-detail').innerText = `Chunk ${data.current_chunk || Math.floor(data.total_chunks * data.percent / 100)} / ${data.total_chunks}`;
    } else {
        document.getElementById('progress-detail').innerText = `${data.percent.toFixed(1)}%`;
    }
});

evtSource.addEventListener('file_complete', (e) => {
    if (!chatMessages) return;
    document.getElementById('progress-box').classList.add('hidden');
    appendMessage('Hệ thống', `File ${JSON.parse(e.data).filename} đã chuyển thành công.`, 'sys');
});

async function respondFile(accept) {
    document.getElementById('file-modal').classList.add('hidden');
    await fetch('/api/respond_file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transfer_id: pendingTransferId, accept: accept })
    });
}

async function sendFile() {
    const fileInput = document.getElementById('file-input');
    if (!fileInput.files.length) return;
    
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    
    const res = await fetch('/api/upload_temp', { method: 'POST', body: formData });
    const data = await res.json();
    
    if (data.success) {
        await fetch('/api/send_file', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_user: currentTarget, filepath: data.filepath })
        });
    }
    fileInput.value = '';
}

// ================= CHAT LOGIC =================
function selectTarget(target) {
    currentTarget = target;
    document.querySelectorAll('.room-btn, .peer-item').forEach(el => el.classList.remove('active'));
    
    const targetElement = document.getElementById(`peer-${target}`);
    targetElement.classList.add('active');
    
    unreadUsers.delete(target); 
    // Xóa dấu chấm đỏ báo tin nhắn mới
    const dot = targetElement.querySelector('.unread-dot');
    if (dot) dot.remove();

    document.getElementById('chat-title').innerText = target === '__BROADCAST__' ? 'Phòng Chat Chung' : `Chat riêng với: ${target}`;
    
    fetch('/api/chat_history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target: target })
    });
}

async function sendMessage() {
    const input = document.getElementById('msg-input');
    const text = input.value.trim();
    if (!text) return;
    
    // 1. Hiển thị ngay lập tức tin nhắn của chính mình lên giao diện (màu xanh bên phải)
    appendMessage(currentUser || 'Tôi', text, 'self');
    
    // 2. Xóa ô nhập tin nhắn
    input.value = '';
    
    // 3. Gửi tin nhắn qua Web Gateway tới Server
    try {
        await fetch('/api/send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                target: currentTarget, 
                text: text, 
                is_private: currentTarget !== '__BROADCAST__' 
            })
        });
    } catch (err) {
        console.error("Lỗi gửi tin nhắn:", err);
    }
}

function appendMessage(sender, text, type) {
    const div = document.createElement('div');
    div.className = `msg-bubble msg-${type}`;
    if (type !== 'sys') div.innerHTML = `<div class="msg-sender">${sender}</div>${text}`;
    else div.innerText = text;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function renderUserList(users) {
    if (!chatMessages) return;
    const list = document.getElementById('user-list');
    if (!list) return;
    list.innerHTML = '';
    
    users.forEach(u => {
        const username = typeof u === 'object' && u !== null ? u.username : u;
        if (username === currentUser) return;
        const div = document.createElement('div');
        div.className = `peer-item ${currentTarget === username ? 'active' : ''}`;
        div.id = `peer-${username}`;
        div.innerText = username;
        if (unreadUsers.has(username)) {
            const dot = document.createElement('span');
            dot.className = 'unread-dot';
            div.appendChild(dot);
        }
        div.onclick = () => selectTarget(username);
        list.appendChild(div);
    });
}

async function loadUserList() {
    try {
        const res = await fetch('/api/users');
        const data = await res.json();
        if (data.users && data.users.length > 0) {
            renderUserList(data.users);
        }
    } catch (e) {
        console.error("Lỗi tải danh sách người dùng:", e);
    }
}

evtSource.onopen = () => {
    if (chatMessages) {
        fetch('/api/refresh_users', { method: 'POST' });
    }
};

// Initialize Dashboard
if (chatMessages) {
    document.getElementById('current-user-display').innerText = currentUser;
    loadUserList();
    setTimeout(() => selectTarget('__BROADCAST__'), 500);
}