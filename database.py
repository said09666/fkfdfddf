import sqlite3
import json
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path='moderator.db'):
        self.db_path = db_path
        self.init_db()
    
    def __get_connection(self):
        """Получить соединение с базой данных"""
        return sqlite3.connect(self.db_path, check_same_thread=False)
    
    def init_db(self):
        conn = self.__get_connection()
        cursor = conn.cursor()
        
        try:
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE,
                    roblox_username TEXT,
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
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
        finally:
            conn.close()
    
    def add_user(self, telegram_id, roblox_username, roblox_id, verification_code):
        conn = self.__get_connection()
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
            logger.error(f"Error adding user: {e}")
            return False
        finally:
            conn.close()
    
    # ... остальные методы остаются такими же, но с добавлением try/except
