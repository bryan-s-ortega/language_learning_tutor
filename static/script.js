const API_URL = 'http://localhost:8000/api';
let userId = localStorage.getItem('user_id');
if (!userId) {
    userId = 'user_' + Math.random().toString(36).substr(2, 9);
    localStorage.setItem('user_id', userId);
}

const chatArea = document.getElementById('chat-area');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const recordBtn = document.getElementById('record-btn');

let mediaRecorder;
let audioChunks = [];
let isRecording = false;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    startSession();
    setupEventListeners();
});

async function startSession() {
    try {
        const response = await fetch(`${API_URL}/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await response.json();
        addMessage(data.message, 'bot');
    } catch (error) {
        console.error('Error starting session:', error);
        addMessage('Error connecting to server.', 'bot');
    }
}

function setupEventListeners() {
    sendBtn.addEventListener('click', sendMessage);
    messageInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });

    recordBtn.addEventListener('click', toggleRecording);

    // Sidebar actions
    document.getElementById('nav-new-task').addEventListener('click', startNewTask);
    document.getElementById('nav-progress').addEventListener('click', getProgress);
}

async function sendMessage() {
    const text = messageInput.value.trim();
    if (!text) return;

    addMessage(text, 'user');
    messageInput.value = '';
    setLoading(true);

    try {
        const formData = new FormData();
        formData.append('user_id', userId);
        formData.append('message', text);

        const response = await fetch(`${API_URL}/chat`, {
            method: 'POST',
            body: formData
        });
        const data = await response.json();
        handleResponse(data);
    } catch (error) {
        console.error('Error sending message:', error);
        addMessage('Error sending message.', 'bot');
    } finally {
        setLoading(false);
    }
}

async function toggleRecording() {
    if (!isRecording) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];

            mediaRecorder.ondataavailable = (event) => {
                audioChunks.push(event.data);
            };

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/ogg' });
                sendVoiceMessage(audioBlob);
            };

            mediaRecorder.start();
            isRecording = true;
            recordBtn.classList.add('recording');
            recordBtn.innerHTML = '<i class="fas fa-stop"></i>';
        } catch (error) {
            console.error('Error accessing microphone:', error);
            alert('Could not access microphone.');
        }
    } else {
        mediaRecorder.stop();
        isRecording = false;
        recordBtn.classList.remove('recording');
        recordBtn.innerHTML = '<i class="fas fa-microphone"></i>';
    }
}

async function sendVoiceMessage(audioBlob) {
    addMessage('🎤 Voice Message Sent', 'user');
    setLoading(true);

    try {
        const formData = new FormData();
        formData.append('user_id', userId);
        formData.append('voice', audioBlob, 'voice.ogg');

        const response = await fetch(`${API_URL}/chat`, {
            method: 'POST',
            body: formData
        });
        const data = await response.json();
        handleResponse(data);
    } catch (error) {
        console.error('Error sending voice:', error);
        addMessage('Error sending voice message.', 'bot');
    } finally {
        setLoading(false);
    }
}

async function startNewTask() {
    setLoading(true);
    try {
        const response = await fetch(`${API_URL}/newtask`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await response.json();

        if (data.options) {
            addMessage(data.message, 'bot');
            showOptions(data.options);
        } else {
            addMessage(data.message || 'Error starting new task', 'bot');
        }
    } catch (error) {
        console.error('Error:', error);
    } finally {
        setLoading(false);
    }
}

async function selectTask(taskType) {
    setLoading(true);
    try {
        const response = await fetch(`${API_URL}/select_task`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, task_type: taskType })
        });
        const data = await response.json();

        if (data.message) {
            addMessage(data.message, 'bot');
        }
    } catch (error) {
        console.error('Error:', error);
    } finally {
        setLoading(false);
    }
}

async function getProgress() {
    setLoading(true);
    try {
        const response = await fetch(`${API_URL}/progress?user_id=${userId}`);
        const data = await response.json();
        addMessage(data.message, 'bot');
    } catch (error) {
        console.error('Error:', error);
    } finally {
        setLoading(false);
    }
}

function handleResponse(data) {
    if (data.message) {
        addMessage(data.message, 'bot');
    }
    if (data.is_correct !== undefined) {
        // Could add specific UI indication for correctness
    }
}

function addMessage(text, sender) {
    const div = document.createElement('div');
    div.className = `message ${sender}`;

    // Simple markdown parsing
    let formattedText = text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');

    div.innerHTML = `<p>${formattedText}</p>`;
    chatArea.appendChild(div);
    chatArea.scrollTop = chatArea.scrollHeight;
}

function showOptions(options) {
    const optionsDiv = document.createElement('div');
    optionsDiv.className = 'options-grid';

    options.forEach(option => {
        const btn = document.createElement('div');
        btn.className = 'option-card';
        btn.textContent = option;
        btn.onclick = () => {
            addMessage(`Selected: ${option}`, 'user');
            selectTask(option);
            optionsDiv.remove();
        };
        optionsDiv.appendChild(btn);
    });

    const messageDiv = document.createElement('div');
    messageDiv.className = 'message bot';
    messageDiv.style.background = 'transparent';
    messageDiv.style.padding = '0';
    messageDiv.appendChild(optionsDiv);
    chatArea.appendChild(messageDiv);
    chatArea.scrollTop = chatArea.scrollHeight;
}

function setLoading(isLoading) {
    sendBtn.disabled = isLoading;
    messageInput.disabled = isLoading;
    if (isLoading) {
        chatArea.style.opacity = '0.7';
    } else {
        chatArea.style.opacity = '1';
    }
}
