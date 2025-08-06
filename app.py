import os
import json
import logging
import sqlite3
from flask import Flask, Response, request, stream_with_context, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import google.generativeai as genai
from dotenv import load_dotenv

# --- 1. Configuration ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
GEMINI_API_CONFIGURED = False
DATABASE_FILE = 'database.db'

try:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("FATAL ERROR: GEMINI_API_KEY environment variable not set.")
    else:
        genai.configure(api_key=api_key)
        GEMINI_API_CONFIGURED = True
except Exception as e:
    print(f"FATAL ERROR: Could not configure Gemini API. Details: {e}")

# --- 2. Database Setup ---
def get_db_connection():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    # Use IF NOT EXISTS to prevent errors on subsequent runs
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            plan TEXT NOT NULL DEFAULT 'free',
            daily_messages INTEGER NOT NULL DEFAULT 0,
            last_message_date TEXT NOT NULL
        );
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            system_prompt TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            sender TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (chat_id) REFERENCES chats (id) ON DELETE CASCADE
        );
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS site_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    ''')
    # Check if announcement exists, if not, insert it
    if conn.execute("SELECT 1 FROM site_settings WHERE key = 'announcement'").fetchone() is None:
        conn.execute("INSERT INTO site_settings (key, value) VALUES (?, ?)", 
                     ('announcement', 'Welcome to the new Myth AI 2.2!'))

    conn.commit()
    conn.close()


# --- 3. Application Setup ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-very-secret-and-long-random-key-for-myth-ai-v3-sqlite'
login_manager = LoginManager()
login_manager.init_app(app)

@login_manager.unauthorized_handler
def unauthorized():
    return jsonify({"error": "Login required.", "logged_in": False}), 401

# --- 4. User Model and Data Logic ---
class User(UserMixin):
    def __init__(self, id, username, password_hash, role, plan, daily_messages=0, last_message_date=None):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.role = role
        self.plan = plan
        self.daily_messages = daily_messages
        self.last_message_date = last_message_date or datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def get(user_id):
        conn = get_db_connection()
        user_data = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        conn.close()
        if not user_data:
            return None
        return User(**dict(user_data))

    @staticmethod
    def get_by_username(username):
        conn = get_db_connection()
        user_data = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        if not user_data:
            return None
        return User(**dict(user_data))

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

def initialize_app_data():
    init_db() # Ensure tables are created
    # Create a default admin user if one doesn't exist
    if not User.get_by_username('admin'):
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, plan, last_message_date) VALUES (?, ?, ?, ?, ?, ?)",
            ('admin', 'admin', generate_password_hash('admin123'), 'admin', 'pro', datetime.now().strftime("%Y-%m-%d"))
        )
        conn.commit()
        conn.close()
        print("Admin user created.")

# --- 5. HTML and JavaScript Frontend ---
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Myth AI 2.2</title>
    <meta name="description" content="An advanced, feature-rich AI chat application prototype.">
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/marked/4.2.12/marked.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/2.4.1/purify.min.js"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Inter', 'sans-serif'],
                        mono: ['Fira Code', 'monospace'],
                    },
                    animation: {
                        'fade-in': 'fadeIn 0.5s ease-out forwards',
                        'scale-up': 'scaleUp 0.3s ease-out forwards',
                        'slide-in-left': 'slideInLeft 0.5s cubic-bezier(0.25, 1, 0.5, 1) forwards',
                    },
                    keyframes: {
                        fadeIn: { '0%': { opacity: 0 }, '100%': { opacity: 1 } },
                        scaleUp: { '0%': { transform: 'scale(0.95)', opacity: 0 }, '100%': { transform: 'scale(1)', opacity: 1 } },
                        slideInLeft: { '0%': { transform: 'translateX(-100%)', opacity: 0 }, '100%': { transform: 'translateX(0)', opacity: 1 } },
                    }
                }
            }
        }
    </script>
    <style>
        body { background-color: #111827; }
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: #1f2937; }
        ::-webkit-scrollbar-thumb { background: #4b5563; border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: #6b7280; }
        .glassmorphism { background: rgba(31, 41, 55, 0.5); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.1); }
        .brand-gradient { background-image: linear-gradient(to right, #3b82f6, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .message-wrapper { animation: fadeIn 0.4s ease-out forwards; }
        pre { position: relative; }
        .copy-code-btn { position: absolute; top: 0.5rem; right: 0.5rem; background-color: #374151; color: white; border: none; padding: 0.25rem 0.5rem; border-radius: 0.25rem; cursor: pointer; opacity: 0; transition: opacity 0.2s; font-size: 0.75rem; }
        pre:hover .copy-code-btn { opacity: 1; }
        #sidebar.hidden { transform: translateX(-100%); }
    </style>
</head>
<body class="font-sans text-gray-200 antialiased">
    <div id="announcement-banner" class="hidden text-center p-2 bg-indigo-600 text-white text-sm"></div>
    <div id="app-container" class="relative h-screen w-screen overflow-hidden"></div>
    <div id="modal-container"></div>
    <div id="toast-container" class="fixed top-6 right-6 z-[100] flex flex-col gap-2"></div>

    <template id="template-logo"></template>
    <template id="template-auth-page"></template>

    <template id="template-app-wrapper">
        <div class="flex h-full w-full">
            <aside id="sidebar" class="bg-gray-900/70 backdrop-blur-lg w-72 flex-shrink-0 flex flex-col p-2 h-full absolute md:relative z-20 transform transition-transform duration-300 ease-in-out -translate-x-full md:translate-x-0">
                <div class="flex-shrink-0 p-2 mb-2 flex items-center gap-3">
                    <div id="app-logo-container"></div>
                    <h1 class="text-2xl font-bold brand-gradient">Myth AI 2.2</h1>
                </div>
                <div class="flex-shrink-0"><button id="new-chat-btn" class="w-full text-left flex items-center gap-3 p-3 rounded-lg hover:bg-gray-700/50 transition-colors duration-200"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14" /><path d="M5 12h14" /></svg> New Chat</button></div>
                <div id="chat-history-list" class="flex-grow overflow-y-auto my-4 space-y-1 pr-1"></div>
                <div class="flex-shrink-0 border-t border-gray-700 pt-2 space-y-1">
                    <div id="user-info" class="p-3 text-sm space-y-2"></div>
                    <button id="logout-btn" class="w-full text-left flex items-center gap-3 p-3 rounded-lg hover:bg-red-500/20 text-red-400 transition-colors duration-200"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" x2="9" y1="12" y2="12" /></svg> Logout</button>
                </div>
            </aside>
            <main class="flex-1 flex flex-col bg-gray-800 h-full">
                <header class="flex-shrink-0 p-4 flex items-center justify-between border-b border-gray-700/50">
                    <div class="flex items-center gap-2">
                        <button id="menu-toggle-btn" class="p-2 rounded-lg hover:bg-gray-700/50 transition-colors md:hidden"><svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg></button>
                        <h2 id="chat-title" class="text-xl font-semibold truncate">New Chat</h2>
                    </div>
                    <div class="flex items-center gap-4">
                        <button id="export-chat-btn" title="Export Chat" class="p-2 rounded-lg hover:bg-gray-700/50 transition-colors"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" x2="12" y1="15" y2="3" /></svg></button>
                        <button id="rename-chat-btn" title="Rename Chat" class="p-2 rounded-lg hover:bg-gray-700/50 transition-colors"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg></button>
                        <button id="delete-chat-btn" title="Delete Chat" class="p-2 rounded-lg hover:bg-red-500/20 text-red-400 transition-colors"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><line x1="10" y1="11" x2="10" y2="17" /><line x1="14" y1="11" x2="14" y2="17" /></svg></button>
                    </div>
                </header>
                <div id="chat-window" class="flex-1 overflow-y-auto p-4 md:p-6 space-y-6 min-h-0"></div>
                <div class="flex-shrink-0 p-2 md:p-4 md:px-6 border-t border-gray-700/50">
                    <div class="max-w-4xl mx-auto">
                        <div id="stop-generating-container" class="text-center mb-2" style="display: none;"><button id="stop-generating-btn" class="bg-red-600/50 hover:bg-red-600/80 text-white font-semibold py-2 px-4 rounded-lg transition-colors flex items-center gap-2 mx-auto"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" fill="currentColor" viewBox="0 0 16 16"><rect width="10" height="10" x="3" y="3" rx="1"/></svg> Stop Generating</button></div>
                        <div class="relative glassmorphism rounded-2xl shadow-lg">
                            <textarea id="user-input" placeholder="Message Myth AI..." class="w-full bg-transparent p-4 pr-16 resize-none rounded-2xl focus:outline-none focus:ring-2 focus:ring-blue-500 transition-shadow" rows="1"></textarea>
                            <div class="absolute right-3 top-1/2 -translate-y-1/2 flex items-center"><button id="send-btn" class="p-2 rounded-full bg-gradient-to-r from-blue-600 to-indigo-600 hover:opacity-90 transition-opacity disabled:from-gray-500 disabled:to-gray-600 disabled:cursor-not-allowed"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="white"><path d="M2 22l20-10L2 2z"/></svg></button></div>
                        </div>
                         <div class="text-xs text-gray-400 mt-2 text-center" id="message-limit-display"></div>
                    </div>
                </div>
            </main>
        </div>
    </template>

    <template id="template-welcome-screen"></template>
    <template id="template-modal"></template>
    <template id="template-admin-dashboard"></template>

<script>
// --- The entire JavaScript block from the previous version goes here, with one new function `handleUpgradeClick` and updates to `updateUserInfo` and `setupAppEventListeners` ---
/****************************************************************************
 * JAVASCRIPT FRONTEND LOGIC (MYTH AI 2.2)
 ****************************************************************************/
document.addEventListener('DOMContentLoaded', () => {
    const appState = {
        chats: {}, activeChatId: null, isAITyping: false,
        abortController: null, currentUser: null,
    };

    const DOMElements = {
        appContainer: document.getElementById('app-container'),
        modalContainer: document.getElementById('modal-container'),
        toastContainer: document.getElementById('toast-container'),
        announcementBanner: document.getElementById('announcement-banner'),
    };

    function showToast(message, type = 'info') {
        const colors = { info: 'bg-blue-600', success: 'bg-green-600', error: 'bg-red-600' };
        const toast = document.createElement('div');
        toast.className = `toast text-white text-sm py-2 px-4 rounded-lg shadow-lg animate-fade-in ${colors[type]}`;
        toast.textContent = message;
        DOMElements.toastContainer.appendChild(toast);
        setTimeout(() => toast.remove(), 4000);
    }

    // Function to render the logo SVG into a container
    function renderLogo(containerId) { /* Omitted for brevity */ }

    async function apiCall(endpoint, options = {}) {
        try {
            const response = await fetch(endpoint, options);
            const data = await response.json();
            if (!response.ok) {
                if (response.status === 401) handleLogout(false);
                throw new Error(data.error || 'An unknown error occurred.');
            }
            return { success: true, ...data };
        } catch (error) {
            showToast(error.message, 'error');
            return { success: false, error: error.message };
        }
    }

    // Function to open a modal
    function openModal(title, bodyContent, onConfirm, confirmText = 'Confirm') { /* Omitted for brevity */ }

    // Function to close the modal
    function closeModal() { /* Omitted for brevity */ }
    
    // Function to render the login/signup page
    function renderAuthPage(isLogin = true) { /* Omitted for brevity */ }

    async function checkLoginStatus() {
        const result = await apiCall('/api/status');
        if (result.success && result.logged_in) {
            initializeApp(result.user, result.chats, result.settings);
        } else {
            renderAuthPage();
        }
    }

    function initializeApp(user, chats, settings) {
        appState.currentUser = user;
        appState.chats = chats;
        if (settings.announcement) {
            DOMElements.announcementBanner.textContent = settings.announcement;
            DOMElements.announcementBanner.classList.remove('hidden');
        } else {
            DOMElements.announcementBanner.classList.add('hidden');
        }
        if (user.role === 'admin') {
            renderAdminDashboard();
        } else {
            renderAppUI();
        }
    }

    function renderAppUI() {
        const template = document.getElementById('template-app-wrapper');
        DOMElements.appContainer.innerHTML = '';
        DOMElements.appContainer.appendChild(template.content.cloneNode(true));
        renderLogo('app-logo-container');
        const sortedChatIds = Object.keys(appState.chats).sort((a, b) => appState.chats[b].created_at.localeCompare(appState.chats[a].created_at));
        appState.activeChatId = sortedChatIds.length > 0 ? sortedChatIds[0] : null;
        renderChatHistoryList();
        renderActiveChat();
        updateUserInfo();
        setupAppEventListeners();
    }
    
    // Function to render the currently active chat window or welcome screen
    function renderActiveChat() { /* Omitted for brevity */ }
    
    // Function to render the welcome screen in the chat window
    function renderWelcomeScreen(systemPrompt = '') { /* Omitted for brevity */ }

    function renderChatHistoryList() {
        const listEl = document.getElementById('chat-history-list');
        if (!listEl) return;
        listEl.innerHTML = '';
        Object.values(appState.chats)
            .sort((a, b) => b.created_at.localeCompare(a.created_at))
            .forEach(chat => {
                const item = document.createElement('button');
                item.className = `w-full text-left p-3 rounded-lg hover:bg-gray-700/50 transition-colors duration-200 truncate text-sm ${chat.id === appState.activeChatId ? 'bg-blue-600/30 font-semibold' : ''}`;
                item.textContent = chat.title;
                item.onclick = () => {
                    appState.activeChatId = chat.id;
                    renderActiveChat();
                    renderChatHistoryList();
                    const sidebar = document.getElementById('sidebar');
                    if (sidebar && window.innerWidth < 768) {
                         sidebar.classList.add('-translate-x-full');
                    }
                };
                listEl.appendChild(item);
            });
    }

    function updateUserInfo() {
        const userInfoDiv = document.getElementById('user-info');
        if (!userInfoDiv || !appState.currentUser) return;
        const { username, plan } = appState.currentUser;
        const planName = plan.charAt(0).toUpperCase() + plan.slice(1);
        const planColor = plan === 'pro' ? 'text-indigo-400' : 'text-gray-400';
        const avatarColor = `hsl(${username.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0) % 360}, 50%, 60%)`;
        
        let upgradeButtonHTML = '';
        if (plan === 'free') {
            upgradeButtonHTML = `<button id="upgrade-btn" class="w-full text-sm mt-2 text-center bg-yellow-500/20 hover:bg-yellow-500/40 text-yellow-300 font-semibold py-2 px-3 rounded-lg transition-colors">✨ Upgrade to Pro</button>`;
        }

        userInfoDiv.innerHTML = `
            <div class="flex items-center gap-3">
                <div class="flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center font-bold text-white" style="background-color: ${avatarColor};">
                    ${username[0].toUpperCase()}
                </div>
                <div>
                    <div class="font-semibold">${username}</div>
                    <div class="text-xs ${planColor}">${planName} Plan</div>
                </div>
            </div>
            ${upgradeButtonHTML}
        `;
        const limitDisplay = document.getElementById('message-limit-display');
        if(limitDisplay) limitDisplay.textContent = `Daily Messages: ${appState.currentUser.daily_messages} / ${appState.currentUser.message_limit}`;
    }

    // Function to enable/disable buttons based on AI typing state
    function updateUIState() { /* Omitted for brevity */ }

    async function handleSendMessage() { /* Omitted for brevity, same as last fixed version */ }

    // Function to add a message bubble to the DOM
    function addMessageToDOM(msg, isStreaming = false) { /* Omitted for brevity */ }

    async function createNewChat(shouldRender = true) {
        const result = await apiCall('/api/chat/new', { method: 'POST' });
        if (result.success) {
            appState.chats[result.chat.id] = result.chat;
            appState.activeChatId = result.chat.id;
            if (shouldRender) {
                renderActiveChat();
                renderChatHistoryList();
            }
            return true;
        }
        return false;
    }

    // Function to add copy buttons to code blocks
    function renderCodeCopyButtons() { /* Omitted for brevity */ }
    
    // NEW: Function to handle the upgrade process
    function handleUpgradeClick() {
        const modalBody = document.createElement('div');
        modalBody.className = 'text-left';
        modalBody.innerHTML = `
            <p class="text-center mb-4 text-gray-300">You are upgrading to the Pro Plan!</p>
            <div class="p-4 border border-dashed border-gray-600 rounded-lg bg-gray-900/50">
                <h4 class="font-semibold text-white">Pro Plan Benefits:</h4>
                <ul class="list-disc list-inside text-sm text-gray-400 mt-2">
                    <li>Increased daily message limit (50 messages)</li>
                    <li>Access to more powerful models (coming soon)</li>
                    <li>Priority support</li>
                </ul>
            </div>
            <p class="text-xs text-gray-500 text-center mt-6">
                This is a mock payment flow. No real payment will be processed.
            </p>
        `;
        openModal('Confirm Upgrade', modalBody, async () => {
            const upgradeResult = await apiCall('/api/user/upgrade', { method: 'POST' });
            if (upgradeResult.success) {
                showToast('Upgrade successful! Welcome to Pro.', 'success');
                // Refresh user data to reflect the new plan
                const statusResult = await apiCall('/api/status');
                if (statusResult.success) {
                    appState.currentUser = statusResult.user;
                    updateUserInfo(); // Re-render the user info panel
                }
            }
        }, 'Confirm Purchase ($9.99)');
    }

    function setupAppEventListeners() {
        const appContainer = document.getElementById('app-container');
        if (!appContainer) return;
        
        appContainer.onclick = (e) => {
            const target = e.target.closest('button');
            if (!target) return;
            switch (target.id) {
                case 'new-chat-btn': 
                    createNewChat(true);
                    const sidebar = document.getElementById('sidebar');
                    if (sidebar && window.innerWidth < 768) {
                         sidebar.classList.add('-translate-x-full');
                    }
                    break;
                case 'logout-btn': handleLogout(); break;
                case 'send-btn': handleSendMessage(); break;
                case 'stop-generating-btn': appState.abortController?.abort(); break;
                case 'rename-chat-btn': handleRenameChat(); break;
                case 'delete-chat-btn': handleDeleteChat(); break;
                case 'export-chat-btn': handleExportChat(); break;
                case 'menu-toggle-btn': 
                    document.getElementById('sidebar')?.classList.toggle('-translate-x-full');
                    break;
                case 'upgrade-btn': // <-- NEW
                    handleUpgradeClick();
                    break;
            }
        };

        const userInput = document.getElementById('user-input');
        if (userInput) { /* Omitted for brevity */ }
    }

    // All other helper functions like `handleLogout`, `handleDeleteChat`, etc. are omitted for brevity
    // but are the same as the previous correct version.
    async function handleLogout(doApiCall = true) { /* ... */ }
    function handleRenameChat() { /* ... */ }
    function handleDeleteChat() { /* ... */ }
    function handleExportChat() { /* ... */ }
    function renderAdminDashboard() { /* ... */ }
    async function fetchAdminData() { /* ... */ }
    async function handleSetAnnouncement(e) { /* ... */ }
    async function handleAdminTogglePlan(e) { /* ... */ }
    function handleAdminDeleteUser(e) { /* ... */ }

    checkLoginStatus();
});
</script>
</body>
</html>
"""

# --- 6. Backend Logic (Flask Routes) ---

PLAN_CONFIG = {
    "free": {"message_limit": 15, "models": ["gemini-1.5-flash-latest"]},
    "pro": {"message_limit": 50, "models": ["gemini-1.5-flash-latest", "gemini-pro"]}
}

def check_and_reset_daily_limit(user):
    today_str = datetime.now().strftime("%Y-%m-%d")
    if user.last_message_date != today_str:
        conn = get_db_connection()
        conn.execute('UPDATE users SET last_message_date = ?, daily_messages = 0 WHERE id = ?', (today_str, user.id))
        conn.commit()
        conn.close()
        user.last_message_date = today_str
        user.daily_messages = 0

def get_user_data_for_frontend(user):
    if not user: return {}
    check_and_reset_daily_limit(user)
    plan_details = PLAN_CONFIG.get(user.plan, PLAN_CONFIG['free'])
    return {
        "id": user.id, "username": user.username, "role": user.role, "plan": user.plan,
        "daily_messages": user.daily_messages, "message_limit": plan_details["message_limit"]
    }

def get_all_user_chats(user_id):
    conn = get_db_connection()
    chats_cursor = conn.execute('SELECT id, title, system_prompt, created_at FROM chats WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
    chats = {}
    for row in chats_cursor.fetchall():
        chat_id = row['id']
        chats[chat_id] = dict(row)
        messages_cursor = conn.execute('SELECT sender, content FROM messages WHERE chat_id = ? ORDER BY timestamp ASC', (chat_id,))
        chats[chat_id]['messages'] = [dict(msg) for msg in messages_cursor.fetchall()]
    conn.close()
    return chats

@app.route('/')
def index():
    return Response(HTML_CONTENT, mimetype='text/html')

# --- All Auth, Chat, and Admin routes from the previous version are here, with one new route added ---

# NEW: Route to handle user upgrade
@app.route('/api/user/upgrade', methods=['POST'])
@login_required
def upgrade_user():
    conn = get_db_connection()
    conn.execute("UPDATE users SET plan = 'pro' WHERE id = ?", (current_user.id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "User upgraded to Pro."})


# --- The rest of the backend routes are the same as the previous version ---
# ... signup, login, logout, status, chat, new, rename, delete, etc. ...


if __name__ == '__main__':
    initialize_app_data()
    print("======================================================")
    print(" Myth AI 2.2 Server is starting... (Gemini/SQLite Version)")
    if GEMINI_API_CONFIGURED:
        print(" ✓ Gemini API key has been set.")
    else:
        print(" ✗ WARNING: Gemini API key is MISSING.")
    print(f" ✓ Database file is '{DATABASE_FILE}'")
    print(" → Open your browser to http://127.0.0.1:5000")
    print("======================================================")
    app.run(host='0.0.0.0', port=5000, debug=False)

