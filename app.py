import os
import json
import logging
import sqlite3
import sys
from flask import Flask, Response, request, stream_with_context, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import google.generativeai as genai
from dotenv import load_dotenv

# --- 1. Configuration ---
load_dotenv()
logging.basicConfig(level=logging.INFO, stream=sys.stdout) # Log to standard output
GEMINI_API_CONFIGURED = False
DATABASE_FILE = 'database.db'

try:
    api_key = os.environ.get("GEMINI_API_KEY")
    # MODIFIED: This will now cause a hard crash if the key is missing, which is easier to debug on Render.
    if not api_key:
        logging.critical("FATAL ERROR: GEMINI_API_KEY environment variable is not set on the server.")
        raise ValueError("GEMINI_API_KEY not found. The application cannot start.")
    
    genai.configure(api_key=api_key)
    GEMINI_API_CONFIGURED = True
    logging.info("Gemini API configured successfully.")
except Exception as e:
    logging.critical(f"FATAL ERROR during startup: {e}")
    raise

# --- The rest of the file is identical to the last version ---

# --- 2. Database Setup ---
def get_db_connection():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user', plan TEXT NOT NULL DEFAULT 'free',
            daily_messages INTEGER NOT NULL DEFAULT 0, last_message_date TEXT NOT NULL
        );
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
            system_prompt TEXT, created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, sender TEXT NOT NULL,
            content TEXT NOT NULL, timestamp TEXT NOT NULL,
            FOREIGN KEY (chat_id) REFERENCES chats (id) ON DELETE CASCADE
        );
    ''')
    conn.execute("CREATE TABLE IF NOT EXISTS site_settings (key TEXT PRIMARY KEY, value TEXT);")
    if conn.execute("SELECT 1 FROM site_settings WHERE key = 'announcement'").fetchone() is None:
        conn.execute("INSERT INTO site_settings (key, value) VALUES (?, ?)", ('announcement', 'Welcome to the new Myth AI 2.2!'))
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
        self.id, self.username, self.password_hash, self.role, self.plan = id, username, password_hash, role, plan
        self.daily_messages = daily_messages
        self.last_message_date = last_message_date or datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def get(user_id):
        conn = get_db_connection()
        user_data = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        conn.close()
        return User(**dict(user_data)) if user_data else None

    @staticmethod
    def get_by_username(username):
        conn = get_db_connection()
        user_data = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        return User(**dict(user_data)) if user_data else None

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

def initialize_app_data():
    init_db()
    if not User.get_by_username('admin'):
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, plan, last_message_date) VALUES (?, ?, ?, ?, ?, ?)",
            ('admin', 'admin', generate_password_hash('admin123'), 'admin', 'pro', datetime.now().strftime("%Y-%m-%d"))
        )
        conn.commit()
        conn.close()
        logging.info("Admin user created.")

HTML_CONTENT = """
<!DOCTYPE html>
"""

# --- 6. Backend Logic (Flask Routes) ---
PLAN_CONFIG = {
    "free": {"message_limit": 15},
    "pro": {"message_limit": 50}
}
# ... All Flask routes (@app.route(...)) are omitted for brevity but are identical to the previous version.

if __name__ == '__main__':
    initialize_app_data()
    print("Starting Flask server...")
    app.run(host='0.0.0.0', port=5000, debug=False)
