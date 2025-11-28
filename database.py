import sqlite3
import json
from datetime import datetime, timedelta

class Database:
    def __init__(self, db_path='moderator.db'):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                telegram_id INTEGER UNIQUE,
                roblox_username TEXT UNIQUE,
                roblox_id INTEGER UNIQUE,
                registration_date TEXT,
                is_verified BOOLEAN DEFAULT FALSE,
                verification_code TEXT,
                created_at TEXT
            )
        ''')
        
        # Таблица банов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                roblox_id INTEGER,
                reason TEXT,
                duration INTEGER,
                banned_by INTEGER,
                banned_at TEXT,
                expires_at TEXT,
                is_permanent BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица мутов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mutes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                roblox_id INTEGER,
                reason TEXT,
                duration INTEGER,
                muted_by INTEGER,
                muted_at TEXT,
                expires_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Таблица групп
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                group_id INTEGER PRIMARY KEY,
                group_title TEXT,
                added_by INTEGER,
                added_at TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_user(self, telegram_id, roblox_username, roblox_id, verification_code):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (telegram_id, roblox_username, roblox_id, verification_code, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (telegram_id, roblox_username, roblox_id, verification_code, datetime.now().isoformat()))
            
            conn.commit()
            return True
        except Exception as e:
            print(f"Error adding user: {e}")
            return False
        finally:
            conn.close()
    
    def verify_user(self, roblox_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE users 
            SET is_verified = TRUE, verification_code = NULL 
            WHERE roblox_id = ?
        ''', (roblox_id,))
        
        conn.commit()
        conn.close()
    
    def get_user_by_telegram_id(self, telegram_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
        user = cursor.fetchone()
        
        conn.close()
        return user
    
    def get_user_by_roblox_id(self, roblox_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE roblox_id = ?', (roblox_id,))
        user = cursor.fetchone()
        
        conn.close()
        return user
    
    def get_user_by_verification_code(self, code):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE verification_code = ?', (code,))
        user = cursor.fetchone()
        
        conn.close()
        return user
    
    def add_ban(self, roblox_id, reason, duration, banned_by, is_permanent=False):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        banned_at = datetime.now()
        expires_at = None if is_permanent else banned_at + timedelta(seconds=duration)
        
        cursor.execute('''
            INSERT INTO bans (roblox_id, reason, duration, banned_by, banned_at, expires_at, is_permanent)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (roblox_id, reason, duration, banned_by, banned_at.isoformat(), 
              expires_at.isoformat() if expires_at else None, is_permanent))
        
        conn.commit()
        conn.close()
    
    def add_mute(self, roblox_id, reason, duration, muted_by):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        muted_at = datetime.now()
        expires_at = muted_at + timedelta(seconds=duration)
        
        cursor.execute('''
            INSERT INTO mutes (roblox_id, reason, duration, muted_by, muted_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (roblox_id, reason, duration, muted_by, muted_at.isoformat(), expires_at.isoformat()))
        
        conn.commit()
        conn.close()
    
    def is_banned(self, roblox_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM bans 
            WHERE roblox_id = ? AND (is_permanent = TRUE OR expires_at > ?)
        ''', (roblox_id, datetime.now().isoformat()))
        
        ban = cursor.fetchone()
        conn.close()
        return ban is not None
    
    def is_muted(self, roblox_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM mutes 
            WHERE roblox_id = ? AND expires_at > ?
        ''', (roblox_id, datetime.now().isoformat()))
        
        mute = cursor.fetchone()
        conn.close()
        return mute is not None
    
    def add_group(self, group_id, group_title, added_by):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO groups (group_id, group_title, added_by, added_at)
            VALUES (?, ?, ?, ?)
        ''', (group_id, group_title, added_by, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
    
    def get_all_groups(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM groups')
        groups = cursor.fetchall()
        
        conn.close()
        return groups
