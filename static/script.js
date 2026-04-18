const API_URL = '/api';

// State Management
const state = {
    userId: null,
    userEmail: null,
    userDisplayName: null,
    interactionState: 'idle',
    currentTask: null,
    theme: localStorage.getItem('theme') || 'light',
    isSidebarOpen: window.innerWidth > 768,
    isRecording: false,
    mediaRecorder: null,
    audioChunks: [],
    proficiencyData: null,
    streak: 0,
    xp: 0
};

// DOM Elements
const elements = {
    authOverlay: document.getElementById('auth-overlay'),
    authForm: document.getElementById('auth-form'),
    authEmail: document.getElementById('auth-email'),
    authPassword: document.getElementById('auth-password'),
    authToggle: document.getElementById('auth-toggle'),
    btnGoogle: document.getElementById('btn-google'),
    btnEmailSignin: document.getElementById('btn-email-signin'),
    
    sidebar: document.getElementById('sidebar'),
    sidebarOpen: document.getElementById('sidebar-open'),
    sidebarClose: document.getElementById('sidebar-close'),
    chatArea: document.getElementById('chat-area'),
    messageInput: document.getElementById('message-input'),
    sendBtn: document.getElementById('send-btn'),
    recordBtn: document.getElementById('record-btn'),
    themeToggle: document.getElementById('theme-toggle'),
    currentTaskName: document.getElementById('current-task-name'),
    emptyState: document.getElementById('empty-state'),
    overlay: document.getElementById('overlay'),
    overlayBody: document.getElementById('overlay-body'),
    closeOverlay: document.getElementById('close-overlay'),
    navItems: {
        chat: document.getElementById('nav-chat'),
        newTask: document.getElementById('nav-new-task'),
        progress: document.getElementById('nav-progress'),
        settings: document.getElementById('nav-settings')
    },
    stats: {
        streak: document.getElementById('streak-count'),
        xp: document.getElementById('xp-count'),
        xpBar: document.getElementById('xp-bar-fill')
    }
};

// --- Firebase Initialization ---
let firebaseAuth = null;
let isSigningUp = false;

// --- Secure Fetch Wrapper ---
async function secureFetch(url, options = {}) {
    if (!firebaseAuth || !firebaseAuth.currentUser) {
        throw new Error("User not authenticated");
    }

    const token = await firebaseAuth.currentUser.getIdToken();
    const headers = {
        ...options.headers,
        'Authorization': `Bearer ${token}`
    };

    return fetch(url, { ...options, headers });
}

// --- Initialization ---
document.addEventListener('DOMContentLoaded', async () => {
    applyTheme(state.theme);
    setupEventListeners();
    await initAuth(); // Wait for auth to initialize
});

async function initAuth() {
    const { initializeApp, getAuth } = window.firebaseDependencies;
    
    try {
        // Fetch the config from our backend
        const configResp = await fetch(`${API_URL}/firebase-config`);
        const firebaseConfig = await configResp.json();

        // Basic check if config is populated
        if (!firebaseConfig.api_key) {
            console.error("Firebase configuration is missing on the server.");
            alert("Application Error: Firebase is not configured. Please check your .env file on the server.");
            return;
        }

        const authModule = await import("https://www.gstatic.com/firebasejs/10.8.0/firebase-auth.js");
        const app = initializeApp({
            apiKey: firebaseConfig.api_key,
            authDomain: firebaseConfig.auth_domain,
            projectId: firebaseConfig.project_id,
            storageBucket: firebaseConfig.storage_bucket,
            messagingSenderId: firebaseConfig.messaging_sender_id,
            appId: firebaseConfig.app_id
        });
        
        firebaseAuth = getAuth(app);

        authModule.onAuthStateChanged(firebaseAuth, (user) => {
            if (user) {
                console.log("User authenticated:", user.uid);
                state.userId = user.uid;
                state.userEmail = user.email;
                state.userDisplayName = user.displayName;
                elements.authOverlay.classList.add('hidden');
                initApp();
            } else {
                console.log("No user authenticated.");
                state.userId = null;
                elements.authOverlay.classList.remove('hidden');
            }
        });

        // Attach Login Actions
        elements.btnGoogle.onclick = () => {
            const provider = new authModule.GoogleAuthProvider();
            authModule.signInWithPopup(firebaseAuth, provider).catch(err => alert(err.message));
        };

        elements.authForm.onsubmit = (e) => {
            e.preventDefault();
            const email = elements.authEmail.value;
            const password = elements.authPassword.value;

            if (isSigningUp) {
                authModule.createUserWithEmailAndPassword(firebaseAuth, email, password)
                    .catch(err => alert(err.message));
            } else {
                authModule.signInWithEmailAndPassword(firebaseAuth, email, password)
                    .catch(err => alert(err.message));
            }
        };

        elements.authToggle.onclick = (e) => {
            e.preventDefault();
            isSigningUp = !isSigningUp;
            elements.btnEmailSignin.textContent = isSigningUp ? "Create Account" : "Sign In";
            elements.authToggle.textContent = isSigningUp ? "Already have an account? Sign In" : "Don't have an account? Create one";
        };

    } catch (error) {
        console.error("Failed to initialize Firebase:", error);
        alert("Initialization Error: Could not connect to authentication services.");
    }
}

function initApp() {
    if (elements.chatArea.children.length <= 1) {
        addBotMessage(`👋 Welcome back, ${state.userDisplayName || 'Learner'}! I'm your AI English Tutor. Ready to practice?`);
    }
    fetchUserState();
}

async function fetchUserState() {
    try {
        const response = await secureFetch(`${API_URL}/state`);
        const data = await response.json();
        if (data.gamification) {
            updateGamificationUI(data.gamification);
        }
    } catch(e) { console.error("Error fetching state:", e); }
}

function setupEventListeners() {
    elements.sendBtn.addEventListener('click', sendMessage);
    elements.messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    elements.messageInput.addEventListener('input', autoResizeTextarea);

    elements.recordBtn.addEventListener('click', toggleRecording);

    elements.sidebarOpen.addEventListener('click', () => toggleSidebar(true));
    elements.sidebarClose.addEventListener('click', () => toggleSidebar(false));
    elements.themeToggle.addEventListener('click', toggleTheme);

    elements.navItems.chat.addEventListener('click', () => {
        clearChat();
        toggleSidebar(window.innerWidth > 768);
    });
    elements.navItems.newTask.addEventListener('click', showTaskSelection);
    elements.navItems.progress.addEventListener('click', showProgress);
    elements.navItems.settings.addEventListener('click', showSettings);

    elements.closeOverlay.addEventListener('click', hideOverlay);
}

// --- View Actions ---

async function showTaskSelection() {
    setLoading(true);
    try {
        const response = await secureFetch(`${API_URL}/newtask`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json();
        
        if (data.options) {
            addBotMessage(data.message || "Please choose a task type:");
            showTaskOptions(data.options);
            if (window.innerWidth <= 768) toggleSidebar(false);
        }
    } catch (error) {
        console.error('Error fetching tasks:', error);
        addBotMessage("❌ Sorry, I couldn't load the task list. Please try again.");
    } finally {
        setLoading(false);
    }
}

async function selectTask(taskType) {
    setLoading(true);
    elements.currentTaskName.textContent = taskType;
    try {
        const response = await secureFetch(`${API_URL}/select_task`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_type: taskType })
        });
        const data = await response.json();
        if (data.message) {
            addBotMessage(data.message);
            state.interactionState = 'awaiting_answer';
        }
    } catch (error) {
        console.error('Error selecting task:', error);
        addBotMessage("❌ Error starting the task. Please try again.");
    } finally {
        setLoading(false);
    }
}

async function showProgress() {
    setLoading(true);
    try {
        const response = await secureFetch(`${API_URL}/proficiency`);
        const data = await response.json();
        state.proficiencyData = data;
        
        renderProgressOverlay(data);
        showOverlay();
        if (window.innerWidth <= 768) toggleSidebar(false);
    } catch (error) {
        console.error('Error fetching progress:', error);
        alert("Could not load progress data.");
    } finally {
        setLoading(false);
    }
}

function showSettings() {
    renderSettingsOverlay();
    showOverlay();
    if (window.innerWidth <= 768) toggleSidebar(false);
}

// --- Chat Logic ---

async function sendMessage() {
    const text = elements.messageInput.value.trim();
    if (!text && !state.isRecording) return;

    addUserMessage(text);
    elements.messageInput.value = '';
    elements.messageInput.style.height = 'auto';
    setLoading(true);

    try {
        const formData = new FormData();
        formData.append('message', text);

        const response = await secureFetch(`${API_URL}/chat`, {
            method: 'POST',
            body: formData
        });
        const data = await response.json();
        handleBotResponse(data);
    } catch (error) {
        console.error('Error sending message:', error);
        addBotMessage("❌ Sorry, I'm having trouble connecting to the server.");
    } finally {
        setLoading(false);
    }
}

function handleBotResponse(data) {
    if (data.chat_response) {
        addBotMessage(data.chat_response, data.tutor_notes);
    } else if (data.message) {
        addBotMessage(data.message);
    }
    
    if (data.gamification) {
        updateGamificationUI(data.gamification);
    }
}

function updateGamificationUI(stats) {
    state.streak = stats.current_streak || 0;
    state.xp = stats.total_xp || 0;
    
    elements.stats.streak.textContent = state.streak;
    elements.stats.xp.textContent = `${state.xp} XP`;
    
    const xpInLevel = state.xp % 100;
    elements.stats.xpBar.style.width = `${xpInLevel}%`;
}

function addBotMessage(text, tutorNotes = []) {
    hideEmptyState();
    const messageEl = createMessageElement(text, 'bot', tutorNotes);
    elements.chatArea.appendChild(messageEl);
    scrollToBottom();
}

function addUserMessage(text) {
    hideEmptyState();
    const messageEl = createMessageElement(text, 'user');
    elements.chatArea.appendChild(messageEl);
    scrollToBottom();
}

function createMessageElement(text, sender, tutorNotes = []) {
    const div = document.createElement('div');
    div.className = `message ${sender}`;
    
    let formattedText = text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');

    const avatar = sender === 'bot' 
        ? '<div class="avatar"><i class="fas fa-robot"></i></div>'
        : '<div class="avatar"><i class="fas fa-user"></i></div>';

    let notesHtml = '';
    if (tutorNotes && tutorNotes.length > 0) {
        notesHtml = `
            <div class="tutor-notes">
                <div class="tutor-notes-title">
                    <i class="fas fa-magic"></i> Tutor Feedback
                </div>
                ${tutorNotes.map(n => `<div class="note-item">${n}</div>`).join('')}
            </div>
        `;
    }

    div.innerHTML = `
        ${avatar}
        <div class="message-content">
            <p>${formattedText}</p>
            ${notesHtml}
        </div>
    `;
    return div;
}

function showTaskOptions(options) {
    const optionsDiv = document.createElement('div');
    optionsDiv.className = 'options-grid';

    options.forEach(option => {
        const card = document.createElement('div');
        card.className = 'option-card';
        card.textContent = option;
        card.onclick = () => {
            addUserMessage(`I'd like to try: ${option}`);
            selectTask(option);
            optionsDiv.style.opacity = '0.5';
            optionsDiv.style.pointerEvents = 'none';
        };
        optionsDiv.appendChild(card);
    });

    const botMessage = document.createElement('div');
    botMessage.className = 'message bot';
    botMessage.innerHTML = `
        <div class="avatar"><i class="fas fa-robot"></i></div>
        <div class="message-content">
            <div class="options-grid"></div>
        </div>
    `;
    botMessage.querySelector('.options-grid').replaceWith(optionsDiv);
    elements.chatArea.appendChild(botMessage);
    scrollToBottom();
}

// --- Voice Logic ---

async function toggleRecording() {
    if (!state.isRecording) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            state.mediaRecorder = new MediaRecorder(stream);
            state.audioChunks = [];

            state.mediaRecorder.ondataavailable = (event) => {
                state.audioChunks.push(event.data);
            };

            state.mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(state.audioChunks, { type: 'audio/ogg' });
                sendVoiceMessage(audioBlob);
            };

            state.mediaRecorder.start();
            state.isRecording = true;
            elements.recordBtn.classList.add('recording');
            elements.recordBtn.innerHTML = '<i class="fas fa-stop"></i>';
        } catch (error) {
            console.error('Error accessing microphone:', error);
            alert('Could not access microphone.');
        }
    } else {
        state.mediaRecorder.stop();
        state.isRecording = false;
        elements.recordBtn.classList.remove('recording');
        elements.recordBtn.innerHTML = '<i class="fas fa-microphone"></i>';
    }
}

async function sendVoiceMessage(audioBlob) {
    addUserMessage('🎤 [Voice Message]');
    setLoading(true);

    try {
        const formData = new FormData();
        formData.append('voice', audioBlob, 'voice.ogg');

        const response = await secureFetch(`${API_URL}/chat`, {
            method: 'POST',
            body: formData
        });
        const data = await response.json();
        handleBotResponse(data);
    } catch (error) {
        console.error('Error sending voice:', error);
        addBotMessage("❌ Error processing your voice message.");
    } finally {
        setLoading(false);
    }
}

// --- Overlay Rendering ---

function renderProgressOverlay(data) {
    elements.overlayBody.innerHTML = `
        <div class="progress-container">
            <div class="sidebar-header" style="padding:0; margin-bottom:20px;">
                <h2 style="font-size: 1.8rem">Your Growth</h2>
            </div>
            
            <div class="chart-section">
                <h3>Proficiency by Category</h3>
                <canvas id="proficiencyChart"></canvas>
            </div>
        </div>
    `;

    setTimeout(() => {
        const ctx = document.getElementById('proficiencyChart').getContext('2d');
        const categories = Object.keys(data);
        const masteryLevels = categories.map(cat => {
            const items = Object.values(data[cat]);
            if (items.length === 0) return 0;
            const avg = items.reduce((acc, item) => acc + (item.mastery_level || 0), 0) / items.length;
            return Math.round(avg * 100);
        });

        new Chart(ctx, {
            type: 'radar',
            data: {
                labels: categories.map(c => c.replace('_', ' ').toUpperCase()),
                datasets: [{
                    label: 'Mastery %',
                    data: masteryLevels,
                    backgroundColor: 'rgba(99, 102, 241, 0.2)',
                    borderColor: 'rgba(99, 102, 241, 1)',
                    pointBackgroundColor: 'rgba(99, 102, 241, 1)',
                    borderWidth: 2
                }]
            },
            options: {
                scales: {
                    r: {
                        beginAtZero: true,
                        max: 100,
                        ticks: { stepSize: 20 }
                    }
                },
                plugins: {
                    legend: { display: false }
                }
            }
        });
    }, 100);
}

function renderSettingsOverlay() {
    elements.overlayBody.innerHTML = `
        <div class="progress-container">
            <h2 style="margin-bottom:24px; font-size: 1.8rem">Settings</h2>
            
            <div class="chart-section">
                <h3 style="margin-bottom:12px">Correction Sensitivity</h3>
                <p style="color:var(--text-secondary); margin-bottom:16px;">How strict should the tutor be with your errors?</p>
                <div class="options-grid">
                    <div class="option-card" data-key="correction_sensitivity" data-val="casual" onclick="updateConfigFromEl(this)">Casual</div>
                    <div class="option-card" data-key="correction_sensitivity" data-val="standard" onclick="updateConfigFromEl(this)">Standard</div>
                    <div class="option-card" data-key="correction_sensitivity" data-val="strict" onclick="updateConfigFromEl(this)">Strict</div>
                </div>
            </div>

            <div class="chart-section" style="margin-top:24px">
                <h3 style="margin-bottom:12px">Difficulty Level</h3>
                <div class="options-grid">
                    <div class="option-card" data-key="difficulty_level" data-val="beginner" onclick="updateConfigFromEl(this)">Beginner</div>
                    <div class="option-card" data-key="difficulty_level" data-val="intermediate" onclick="updateConfigFromEl(this)">Intermediate</div>
                    <div class="option-card" data-key="difficulty_level" data-val="advanced" onclick="updateConfigFromEl(this)">Advanced</div>
                </div>
            </div>

            <button class="btn-auth" style="margin-top:32px; color:#ef4444;" onclick="logout()">
                <i class="fas fa-sign-out-alt"></i>
                <span>Sign Out</span>
            </button>
        </div>
    `;
}

async function updateConfigFromEl(el) {
    const key = el.dataset.key;
    const val = el.dataset.val;
    await updateConfig({ [key]: val });
}

async function updateConfig(config) {
    try {
        const response = await secureFetch(`${API_URL}/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        const data = await response.json();
        alert(data.message || "Settings updated!");
        hideOverlay();
    } catch (e) {
        console.error(e);
    }
}

function logout() {
    import("https://www.gstatic.com/firebasejs/10.8.0/firebase-auth.js").then(m => {
        m.signOut(firebaseAuth).then(() => {
            clearChat();
            hideOverlay();
        });
    });
}

// --- Utilities ---

function toggleTheme() {
    state.theme = state.theme === 'light' ? 'dark' : 'light';
    localStorage.setItem('theme', state.theme);
    applyTheme(state.theme);
}

function applyTheme(theme) {
    document.body.className = `theme-${theme}`;
    const icon = elements.themeToggle.querySelector('i');
    const text = elements.themeToggle.querySelector('span');
    if (theme === 'dark') {
        icon.className = 'fas fa-sun';
        text.textContent = 'Light Mode';
    } else {
        icon.className = 'fas fa-moon';
        text.textContent = 'Dark Mode';
    }
}

function toggleSidebar(open) {
    state.isSidebarOpen = open;
    elements.sidebar.classList.toggle('open', open);
}

function showOverlay() {
    elements.overlay.classList.remove('hidden');
}

function hideOverlay() {
    elements.overlay.classList.add('hidden');
}

function scrollToBottom() {
    elements.chatArea.scrollTop = elements.chatArea.scrollHeight;
}

function hideEmptyState() {
    elements.emptyState.style.display = 'none';
}

function clearChat() {
    elements.chatArea.innerHTML = '';
    elements.emptyState.style.display = 'flex';
    elements.chatArea.appendChild(elements.emptyState);
    state.interactionState = 'idle';
    elements.currentTaskName.textContent = 'English Practice';
}

function autoResizeTextarea() {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
}

function setLoading(isLoading) {
    elements.sendBtn.disabled = isLoading;
    elements.messageInput.disabled = isLoading;
    elements.recordBtn.disabled = isLoading;
    if (isLoading) {
        elements.sendBtn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i>';
    } else {
        elements.sendBtn.innerHTML = '<i class="fas fa-arrow-up"></i>';
    }
}
