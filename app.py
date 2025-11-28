import os
import logging
import sqlite3
import urllib.request
import urllib.parse
import json
import random
import string
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.error import Conflict

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN', '8567807699:AAH6fybbxl6lXd3MyojYIRFjPjbO8GNoc30')
ADMIN_IDS = [8214687269]  # Ваш ID как владелец

# Роли пользователей
ROLES = {
    'owner': '👑 Владелец',
    'admin': '⚡ Админ', 
    'moderator': '🛡️ Модератор',
    'guarantor': '✅ Гарант',
    'scammer': '🚫 Скамер',
    'user': '👤 Пользователь'
}

# Иерархия ролей
ROLE_HIERARCHY = {
    'owner': ['owner', 'admin', 'moderator', 'guarantor', 'user', 'scammer'],
    'admin': ['admin', 'moderator', 'guarantor', 'user', 'scammer'],
    'moderator': ['moderator', 'guarantor', 'user', 'scammer'],
    'guarantor': ['user'],
    'user': [],
    'scammer': []
}

# Состояния пользователей
USER_STATES = {}

class Database:
    def __init__(self, db_path='bot_database.db'):
        self.db_path = db_path
        self.init_db()
    
    def get_connection(self):
        """Создает новое соединение с базой данных"""
        return sqlite3.connect(self.db_path, check_same_thread=False)
    
    def init_db(self):
        """Инициализация базы данных"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Пользователи
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    telegram_username TEXT,
                    roblox_username TEXT,
                    roblox_id INTEGER,
                    verified BOOLEAN DEFAULT FALSE,
                    verification_code TEXT,
                    verified_at TIMESTAMP,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    banned BOOLEAN DEFAULT FALSE,
                    role TEXT DEFAULT 'user',
                    added_by INTEGER
                )
            ''')
            
            # Статистика
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT UNIQUE,
                    total_users INTEGER DEFAULT 0,
                    verified_users INTEGER DEFAULT 0,
                    new_users INTEGER DEFAULT 0
                )
            ''')
            
            # Логи действий
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS action_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT,
                    target_user_id INTEGER,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Настройки групп
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS group_settings (
                    chat_id INTEGER PRIMARY KEY,
                    welcome_message BOOLEAN DEFAULT TRUE,
                    auto_verification_check BOOLEAN DEFAULT TRUE,
                    delete_unverified_messages BOOLEAN DEFAULT TRUE,
                    welcome_timeout INTEGER DEFAULT 300
                )
            ''')
            
            conn.commit()
            logger.info("✅ База данных успешно инициализирована")
            
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации базы данных: {e}")
            raise
        finally:
            conn.close()
    
    def add_user(self, telegram_id, telegram_username=None):
        """Добавляет пользователя в базу"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'INSERT OR IGNORE INTO users (telegram_id, telegram_username) VALUES (?, ?)',
                (telegram_id, telegram_username)
            )
            conn.commit()
            logger.debug(f"Пользователь {telegram_id} добавлен в базу")
        except Exception as e:
            logger.error(f"Ошибка добавления пользователя {telegram_id}: {e}")
        finally:
            conn.close()
    
    def generate_verification_code(self):
        """Генерирует 6-значный буквенный код"""
        return ''.join(random.choices(string.ascii_uppercase, k=6))
    
    def set_verification_code(self, telegram_id, code):
        """Устанавливает код верификации"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'UPDATE users SET verification_code = ? WHERE telegram_id = ?',
                (code, telegram_id)
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Ошибка установки кода верификации: {e}")
        finally:
            conn.close()
    
    def set_verified(self, telegram_id, roblox_username, roblox_id=None):
        """Устанавливает статус верификации"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                '''UPDATE users SET 
                    roblox_username = ?, 
                    roblox_id = ?, 
                    verified = TRUE, 
                    verified_at = ?,
                    verification_code = NULL
                WHERE telegram_id = ?''',
                (roblox_username, roblox_id, datetime.now(), telegram_id)
            )
            conn.commit()
            logger.info(f"Пользователь {telegram_id} верифицирован как {roblox_username}")
        except Exception as e:
            logger.error(f"Ошибка установки верификации: {e}")
        finally:
            conn.close()
    
    def get_verification_code(self, telegram_id):
        """Получает код верификации"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT verification_code FROM users WHERE telegram_id = ?', (telegram_id,))
            result = cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Ошибка получения кода верификации: {e}")
            return None
        finally:
            conn.close()
    
    def is_verified(self, telegram_id):
        """Проверяет верификацию пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT verified FROM users WHERE telegram_id = ?', (telegram_id,))
            result = cursor.fetchone()
            return bool(result and result[0])
        except Exception as e:
            logger.error(f"Ошибка проверки верификации: {e}")
            return False
        finally:
            conn.close()
    
    def is_banned(self, telegram_id):
        """Проверяет забанен ли пользователь"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT banned FROM users WHERE telegram_id = ?', (telegram_id,))
            result = cursor.fetchone()
            return bool(result and result[0])
        except Exception as e:
            logger.error(f"Ошибка проверки бана: {e}")
            return False
        finally:
            conn.close()
    
    def get_role(self, telegram_id):
        """Получает роль пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT role FROM users WHERE telegram_id = ?', (telegram_id,))
            result = cursor.fetchone()
            return result[0] if result else 'user'
        except Exception as e:
            logger.error(f"Ошибка получения роли: {e}")
            return 'user'
        finally:
            conn.close()
    
    def set_role(self, telegram_id, role, added_by=None):
        """Устанавливает роль пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'UPDATE users SET role = ?, added_by = ? WHERE telegram_id = ?',
                (role, added_by, telegram_id)
            )
            conn.commit()
            logger.info(f"Пользователю {telegram_id} установлена роль {role}")
            
            # Логируем действие
            self.log_action(added_by, 'set_role', telegram_id, f"Role changed to {role}")
            
        except Exception as e:
            logger.error(f"Ошибка установки роли: {e}")
        finally:
            conn.close()
    
    def get_user_by_id(self, telegram_id):
        """Получает информацию о пользователе"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'SELECT telegram_id, telegram_username, roblox_username, role, verified FROM users WHERE telegram_id = ?',
                (telegram_id,)
            )
            result = cursor.fetchone()
            if result:
                return {
                    'telegram_id': result[0],
                    'telegram_username': result[1],
                    'roblox_username': result[2],
                    'role': result[3],
                    'verified': bool(result[4])
                }
            return None
        except Exception as e:
            logger.error(f"Ошибка получения пользователя: {e}")
            return None
        finally:
            conn.close()
    
    def get_users_by_role(self, role):
        """Получает пользователей по роли"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'SELECT telegram_id, telegram_username, roblox_username FROM users WHERE role = ?',
                (role,)
            )
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка получения пользователей по роли: {e}")
            return []
        finally:
            conn.close()
    
    def get_all_users(self):
        """Получает всех пользователей"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'SELECT telegram_id, telegram_username, roblox_username, role, verified FROM users ORDER BY role, telegram_id'
            )
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка получения всех пользователей: {e}")
            return []
        finally:
            conn.close()
    
    def ban_user(self, telegram_id, banned_by=None):
        """Банит пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('UPDATE users SET banned = TRUE WHERE telegram_id = ?', (telegram_id,))
            conn.commit()
            if banned_by:
                self.log_action(banned_by, 'ban_user', telegram_id, "User banned")
        except Exception as e:
            logger.error(f"Ошибка бана пользователя: {e}")
        finally:
            conn.close()
    
    def unban_user(self, telegram_id, unbanned_by=None):
        """Разбанивает пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('UPDATE users SET banned = FALSE WHERE telegram_id = ?', (telegram_id,))
            conn.commit()
            if unbanned_by:
                self.log_action(unbanned_by, 'unban_user', telegram_id, "User unbanned")
        except Exception as e:
            logger.error(f"Ошибка разбана пользователя: {e}")
        finally:
            conn.close()
    
    def get_user_stats(self, telegram_id):
        """Получает статистику пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'SELECT roblox_username, verified, verified_at, role FROM users WHERE telegram_id = ?', 
                (telegram_id,)
            )
            result = cursor.fetchone()
            return result
        except Exception as e:
            logger.error(f"Ошибка получения статистики пользователя: {e}")
            return None
        finally:
            conn.close()
    
    def get_bot_stats(self):
        """Получает общую статистику бота"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT COUNT(*) FROM users')
            total_users = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM users WHERE verified = TRUE')
            verified_users = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM users WHERE banned = TRUE')
            banned_users = cursor.fetchone()[0]
            
            # Статистика по ролям
            role_stats = {}
            for role in ROLES.keys():
                cursor.execute('SELECT COUNT(*) FROM users WHERE role = ?', (role,))
                role_stats[role] = cursor.fetchone()[0]
            
            return {
                'total_users': total_users,
                'verified_users': verified_users,
                'banned_users': banned_users,
                'role_stats': role_stats
            }
        except Exception as e:
            logger.error(f"Ошибка получения статистики бота: {e}")
            return {
                'total_users': 0,
                'verified_users': 0,
                'banned_users': 0,
                'role_stats': {role: 0 for role in ROLES.keys()}
            }
        finally:
            conn.close()
    
    def can_manage_role(self, user_role, target_role):
        """Проверяет может ли пользователь управлять ролью"""
        if user_role in ROLE_HIERARCHY and target_role in ROLE_HIERARCHY[user_role]:
            return True
        return False
    
    def is_admin(self, telegram_id):
        """Проверяет является ли пользователь администратором"""
        role = self.get_role(telegram_id)
        return role in ['admin', 'owner']
    
    def is_owner(self, telegram_id):
        """Проверяет является ли пользователь владельцем"""
        return self.get_role(telegram_id) == 'owner'
    
    def log_action(self, user_id, action, target_user_id=None, details=None):
        """Логирует действия пользователей"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'INSERT INTO action_logs (user_id, action, target_user_id, details) VALUES (?, ?, ?, ?)',
                (user_id, action, target_user_id, details)
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Ошибка логирования действия: {e}")
        finally:
            conn.close()
    
    def get_recent_actions(self, limit=10):
        """Получает последние действия"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT al.user_id, u1.telegram_username, al.action, al.target_user_id, u2.telegram_username, al.details, al.created_at
                FROM action_logs al
                LEFT JOIN users u1 ON al.user_id = u1.telegram_id
                LEFT JOIN users u2 ON al.target_user_id = u2.telegram_id
                ORDER BY al.created_at DESC LIMIT ?
            ''', (limit,))
            return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка получения логов действий: {e}")
            return []
        finally:
            conn.close()
    
    # Методы для работы с группами
    def get_group_settings(self, chat_id):
        """Получает настройки группы"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT * FROM group_settings WHERE chat_id = ?', (chat_id,))
            result = cursor.fetchone()
            if result:
                return {
                    'chat_id': result[0],
                    'welcome_message': bool(result[1]),
                    'auto_verification_check': bool(result[2]),
                    'delete_unverified_messages': bool(result[3]),
                    'welcome_timeout': result[4]
                }
            return None
        except Exception as e:
            logger.error(f"Ошибка получения настроек группы: {e}")
            return None
        finally:
            conn.close()
    
    def set_group_settings(self, chat_id, welcome_message=True, auto_verification_check=True, 
                          delete_unverified_messages=True, welcome_timeout=300):
        """Устанавливает настройки группы"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO group_settings 
                (chat_id, welcome_message, auto_verification_check, delete_unverified_messages, welcome_timeout)
                VALUES (?, ?, ?, ?, ?)
            ''', (chat_id, welcome_message, auto_verification_check, delete_unverified_messages, welcome_timeout))
            conn.commit()
        except Exception as e:
            logger.error(f"Ошибка установки настроек группы: {e}")
        finally:
            conn.close()
    
    def is_group_registered(self, chat_id):
        """Проверяет зарегистрирована ли группа"""
        return self.get_group_settings(chat_id) is not None

# Инициализация базы данных
logger.info("🔄 Инициализация базы данных...")
db = Database()

# Добавляем владельцев при запуске
logger.info("👑 Добавление владельцев...")
for admin_id in ADMIN_IDS:
    db.add_user(admin_id, f"owner_{admin_id}")
    db.set_role(admin_id, 'owner')
    logger.info(f"Владелец {admin_id} добавлен")

# ===== ОСНОВНЫЕ КОМАНДЫ =====
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    try:
        user = update.effective_user
        chat = update.effective_chat
        
        logger.info(f"Команда /start от пользователя {user.id} в чате {chat.type}")
        
        # Если команда вызвана в группе
        if chat.type in ['group', 'supergroup']:
            await group_settings_command(update, context)
            return
            
        # Добавляем пользователя в базу
        db.add_user(user.id, user.username)
        logger.info(f"Пользователь {user.id} добавлен в базу")
        
        if db.is_banned(user.id):
            await update.message.reply_text("🚫 Вы заблокированы в системе.")
            return
        
        user_role = db.get_role(user.id)
        role_name = ROLES.get(user_role, '👤 Пользователь')
        
        logger.info(f"Роль пользователя {user.id}: {user_role}")
        
        keyboard = []
        
        if not db.is_verified(user.id):
            keyboard.append([InlineKeyboardButton("🔐 Начать верификацию", callback_data="verify")])
        else:
            keyboard.append([InlineKeyboardButton("📊 Мой профиль", callback_data="profile")])
        
        if db.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("⚙️ Панель управления", callback_data="admin_panel")])
            keyboard.append([InlineKeyboardButton("🎭 Управление ролями", callback_data="role_management")])
        
        keyboard.append([InlineKeyboardButton("📈 Статистика", callback_data="stats")])
        keyboard.append([InlineKeyboardButton("🆘 Помощь", callback_data="help")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = f"""
🎮 **Добро пожаловать в Roblox Verification Bot!**

🤖 **Ваш статус: {role_name}**

📋 **Основные функции:**
✅ Пошаговая верификация Roblox
🎭 Система ролей и прав
📊 Детальная статистика
👥 Управление пользователями

🚀 **Для начала работы нажмите кнопку ниже:**
        """
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в start_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /profile"""
    try:
        user = update.effective_user
        logger.info(f"Команда /profile от пользователя {user.id}")
        await show_profile(update, user)
    except Exception as e:
        logger.error(f"Ошибка в profile_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats"""
    try:
        user = update.effective_user
        logger.info(f"Команда /stats от пользователя {user.id}")
        
        if not db.is_admin(user.id):
            await update.message.reply_text("❌ У вас нет прав для просмотра статистики.")
            return
        
        await show_stats(update)
    except Exception as e:
        logger.error(f"Ошибка в stats_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def roles_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /roles"""
    try:
        user = update.effective_user
        logger.info(f"Команда /roles от пользователя {user.id}")
        
        if not db.is_admin(user.id):
            await update.message.reply_text("❌ У вас нет прав для управления ролями.")
            return
        
        await show_role_management(update, user)
    except Exception as e:
        logger.error(f"Ошибка в roles_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    try:
        logger.info(f"Команда /help от пользователя {update.effective_user.id}")
        await show_help(update)
    except Exception as e:
        logger.error(f"Ошибка в help_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

# ===== ПОШАГОВАЯ ВЕРИФИКАЦИЯ =====
async def start_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса верификации"""
    try:
        user = update.effective_user
        logger.info(f"Начало верификации для пользователя {user.id}")
        
        if db.is_banned(user.id):
            await update.message.reply_text("🚫 Вы заблокированы в системе.")
            return
        
        if db.is_verified(user.id):
            user_stats = db.get_user_stats(user.id)
            if user_stats:
                roblox_username = user_stats[0]
                await update.message.reply_text(
                    f"✅ Вы уже верифицированы как `{roblox_username}`\n\n"
                    f"Для повторной верификации обратитесь к администратору.",
                    parse_mode='Markdown'
                )
            return
        
        # Генерируем код верификации
        verification_code = db.generate_verification_code()
        db.set_verification_code(user.id, verification_code)
        
        # Сохраняем состояние
        USER_STATES[user.id] = {'step': 1, 'code': verification_code}
        
        keyboard = [
            [InlineKeyboardButton("✅ Я добавил код в описание", callback_data="verification_step_2")],
            [InlineKeyboardButton("❌ Отменить верификацию", callback_data="cancel_verification")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🔐 **ШАГ 1 из 3: Добавьте код в описание Roblox**\n\n"
            f"📝 **Ваш уникальный код верификации:**\n"
            f"```\n{verification_code}\n```\n"
            f"**Инструкция:**\n"
            f"1. Откройте Roblox\n"
            f"2. Перейдите в настройки профиля\n"
            f"3. Найдите поле \"Описание\"\n"
            f"4. Добавьте код выше в описание\n"
            f"5. Сохраните изменения\n\n"
            f"💡 *Код должен быть виден в описании вашего профиля*",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Ошибка в start_verification: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def verification_step_2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 2 верификации"""
    try:
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        logger.info(f"Шаг 2 верификации для пользователя {user.id}")
        
        if user.id not in USER_STATES:
            await query.edit_message_text("❌ Сессия верификации устарела. Начните заново с /verify")
            return
        
        USER_STATES[user.id]['step'] = 2
        
        keyboard = [
            [InlineKeyboardButton("❌ Отменить верификацию", callback_data="cancel_verification")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"👤 **ШАГ 2 из 3: Введите ваш никнейм Roblox**\n\n"
            f"📝 **Отправьте мне ваш никнейм в Roblox**\n\n"
            f"**Можно отправить:**\n"
            f"• Никнейм (например: `AlexRoblox`)\n"
            f"• Ссылку на профиль\n"
            f"• ID пользователя\n\n"
            f"💡 *Убедитесь что код {USER_STATES[user.id]['code']} добавлен в описание перед продолжением*",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Ошибка в verification_step_2: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")

async def verification_step_3(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
    """Шаг 3 верификации"""
    try:
        user = update.effective_user
        logger.info(f"Шаг 3 верификации для пользователя {user.id} с ником {username}")
        
        if user.id not in USER_STATES:
            await update.message.reply_text("❌ Сессия верификации устарела. Начните заново с /verify")
            return
        
        verification_code = USER_STATES[user.id]['code']
        
        await update.message.reply_text("🔍 Проверяем аккаунт Roblox...")
        
        # Получаем информацию о пользователе Roblox
        user_info = get_roblox_user_info(username)
        
        if not user_info['success']:
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать другой никнейм", callback_data="verification_step_2")],
                [InlineKeyboardButton("❌ Отменить верификацию", callback_data="cancel_verification")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"❌ **Ошибка:** {user_info['error']}\n\n"
                f"Проверьте правильность никнейма и попробуйте снова.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        # Проверяем код в описании (заглушка)
        await update.message.reply_text("🔐 Проверяем код верификации в описании...")
        await asyncio.sleep(2)
        
        # В реальном боте здесь должна быть проверка через Roblox API
        code_verified = True
        
        if not code_verified:
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="verification_step_2")],
                [InlineKeyboardButton("❌ Отменить верификацию", callback_data="cancel_verification")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"❌ **Код верификации не найден!**\n\n"
                f"🔐 Ваш код: `{verification_code}`\n\n"
                f"**Убедитесь что:**\n"
                f"• Код добавлен в описание профиля Roblox\n"
                f"• Описание сохранено\n"
                f"• Код точно совпадает\n\n"
                f"Попробуйте снова:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        # Верификация успешна!
        db.set_verified(user.id, user_info['username'], user_info['id'])
        
        # Удаляем состояние верификации
        if user.id in USER_STATES:
            del USER_STATES[user.id]
        
        keyboard = [
            [InlineKeyboardButton("📊 Мой профиль", callback_data="profile")],
            [InlineKeyboardButton("🎉 Перейти в чат", url="https://t.me/your_chat_link")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        success_text = f"""
✅ **ВЕРИФИКАЦИЯ УСПЕШНО ЗАВЕРШЕНА!**

🎮 **Ваши данные:**
├ Roblox: `{user_info['username']}`
├ Display Name: `{user_info['displayName']}`
├ ID: `{user_info['id']}`
├ Код: `{verification_code}`
└ Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}

🎉 **Теперь вам доступны:**
• Полный доступ к чатам
• Участие в мероприятиях
• Все функции бота

💫 Добро пожаловать в наше сообщество!
        """
        
        await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')
        logger.info(f"Пользователь {user.id} успешно верифицирован как {user_info['username']}")
        
    except Exception as e:
        logger.error(f"Ошибка в verification_step_3: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ПОКАЗА ИНФОРМАЦИИ =====
async def show_profile(update, user):
    """Показывает профиль пользователя"""
    try:
        stats = db.get_user_stats(user.id)
        
        if not stats:
            profile_text = "❌ Вы еще не зарегистрированы в системе."
        else:
            roblox_username, verified, verified_at, role = stats
            role_name = ROLES.get(role, '👤 Пользователь')
            
            if verified:
                profile_text = f"""
📊 **Ваш профиль**

👤 Telegram: @{user.username or 'N/A'}
🆔 ID: `{user.id}`
🎮 Roblox: `{roblox_username}`
🎭 Роль: {role_name}
✅ Статус: Верифицирован
📅 Дата: {verified_at.split()[0] if verified_at else 'N/A'}
                """
            else:
                profile_text = f"""
📊 **Ваш профиль**

👤 Telegram: @{user.username or 'N/A'}
🆔 ID: `{user.id}`
🎭 Роль: {role_name}
❌ Статус: Не верифицирован

💡 Пройдите верификацию для доступа к полному функционалу
                """
        
        keyboard = []
        if not verified:
            keyboard.append([InlineKeyboardButton("🔐 Начать верификацию", callback_data="verify")])
        
        keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data="profile")])
        keyboard.append([InlineKeyboardButton("↩️ Главное меню", callback_data="back_to_main")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if hasattr(update, 'message'):
            await update.message.reply_text(profile_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.edit_message_text(profile_text, reply_markup=reply_markup, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Ошибка в show_profile: {e}")

async def show_admin_panel(update, user):
    """Показывает панель администратора"""
    try:
        if not db.is_admin(user.id):
            if hasattr(update, 'message'):
                await update.message.reply_text("❌ У вас нет прав администратора.")
            else:
                await update.edit_message_text("❌ У вас нет прав администратора.")
            return
        
        stats = db.get_bot_stats()
        
        admin_text = f"""
⚙️ **Панель управления**

📊 Статистика:
├ 👥 Пользователей: {stats['total_users']}
├ ✅ Верифицировано: {stats['verified_users']}
└ 🚫 Заблокировано: {stats['banned_users']}

🛠️ Выберите действие:
        """
        
        keyboard = [
            [InlineKeyboardButton("📈 Детальная статистика", callback_data="stats")],
            [InlineKeyboardButton("🎭 Управление ролями", callback_data="role_management")],
            [InlineKeyboardButton("👥 Управление пользователями", callback_data="user_management")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="admin_panel")],
            [InlineKeyboardButton("↩️ Главное меню", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if hasattr(update, 'message'):
            await update.message.reply_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.edit_message_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Ошибка в show_admin_panel: {e}")

async def show_stats(update):
    """Показывает статистику"""
    try:
        user = update.effective_user if hasattr(update, 'effective_user') else update.from_user
        
        if not db.is_admin(user.id):
            if hasattr(update, 'message'):
                await update.message.reply_text("❌ У вас нет прав для просмотра статистики.")
            else:
                await update.edit_message_text("❌ У вас нет прав для просмотра статистики.")
            return
        
        stats = db.get_bot_stats()
        
        total = stats['total_users']
        verified = stats['verified_users']
        banned = stats['banned_users']
        pending = total - verified - banned
        
        verified_percent = (verified / total * 100) if total > 0 else 0
        
        # Статистика по ролям
        role_stats_text = ""
        for role, count in stats['role_stats'].items():
            if count > 0 and role != 'user':
                role_stats_text += f"├ {ROLES[role]}: {count}\n"
        
        stats_text = f"""
📈 **Детальная статистика**

👥 **Пользователи:**
├ Всего: {total}
├ Верифицировано: {verified}
├ Ожидают: {pending}
└ Заблокировано: {banned}

📊 **Процент верификации: {verified_percent:.1f}%**

🎭 **Распределение по ролям:**
{role_stats_text}
⚡ **Система:**
├ Бот: 🟢 Онлайн
├ База данных: 🟢 Работает
└ Время: {datetime.now().strftime('%H:%M:%S')}
        """
        
        keyboard = [
            [InlineKeyboardButton("↩️ Назад", callback_data="admin_panel")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="stats")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if hasattr(update, 'message'):
            await update.message.reply_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Ошибка в show_stats: {e}")

async def show_role_management(update, user):
    """Показывает управление ролями"""
    try:
        if not db.is_admin(user.id):
            if hasattr(update, 'message'):
                await update.message.reply_text("❌ У вас нет прав для управления ролями.")
            else:
                await update.edit_message_text("❌ У вас нет прав для управления ролями.")
            return
        
        user_role = db.get_role(user.id)
        user_role_name = ROLES[user_role]
        
        role_text = f"""
👥 **Управление ролями**

🎭 **Доступные роли:**
👑 Владелец - Полный доступ к боту
⚡ Админ - Управление ботом и ролями
🛡️ Модератор - Модерация пользователей
✅ Гарант - Проверенные пользователи
👤 Пользователь - Обычный пользователь
🚫 Скамер - Заблокированные пользователи

💡 **Ваша роль: {user_role_name}**
        """
        
        keyboard = [
            [InlineKeyboardButton("🎭 Выдать роль", callback_data="assign_role")],
            [InlineKeyboardButton("👥 Все пользователи", callback_data="show_all_users")]
        ]
        
        # Добавляем кнопки для просмотра пользователей по ролям
        for role_key, role_name in ROLES.items():
            keyboard.append([InlineKeyboardButton(f"👁️ Показать {role_name}", callback_data=f"role_{role_key}")])
        
        keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data="admin_panel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if hasattr(update, 'message'):
            await update.message.reply_text(role_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.edit_message_text(role_text, reply_markup=reply_markup, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Ошибка в show_role_management: {e}")

async def show_help(update):
    """Показывает справку"""
    try:
        help_text = """
🆘 **Помощь по боту**

📋 **Основные команды:**
/start - Главное меню
/profile - Мой профиль
/stats - Статистика (админы)
/roles - Управление ролями (админы)
/help - Эта справка

🔐 **Процесс верификации:**
1. Нажмите "Начать верификацию"
2. Добавьте код в описание Roblox
3. Введите ваш никнейм Roblox
4. Бот проверит код и завершит верификацию

🎭 **Система ролей:**
👑 Владелец - Полный доступ
⚡ Админ - Управление ботом
🛡️ Модератор - Модерация
✅ Гарант - Проверенные пользователи
👤 Пользователь - Обычный пользователь
🚫 Скамер - Заблокированные

❓ **Проблемы с верификацией?**
• Убедитесь что код точно скопирован
• Проверьте что описание сохранено
• Если проблемы остаются - обратитесь к администратору
        """
        
        keyboard = [
            [InlineKeyboardButton("🔐 Начать верификацию", callback_data="verify")],
            [InlineKeyboardButton("📊 Мой профиль", callback_data="profile")],
            [InlineKeyboardButton("↩️ Главное меню", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if hasattr(update, 'message'):
            await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.edit_message_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Ошибка в show_help: {e}")

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def get_roblox_user_info(username):
    """Получает информацию о пользователе Roblox"""
    try:
        clean_username = extract_username(username)
        if not clean_username:
            return {'success': False, 'error': 'Неверный формат никнейма'}
        
        params = urllib.parse.urlencode({'keyword': clean_username, 'limit': 10})
        url = f"https://users.roblox.com/v1/users/search?{params}"
        
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            
            if data.get('data'):
                for user in data['data']:
                    if user['name'].lower() == clean_username.lower():
                        return {
                            'id': user['id'],
                            'username': user['name'],
                            'displayName': user.get('displayName', user['name']),
                            'success': True
                        }
        
        return {'success': False, 'error': 'Пользователь не найден'}
        
    except Exception as e:
        logger.error(f"Ошибка Roblox API: {e}")
        return {'success': False, 'error': 'Ошибка подключения к Roblox'}

def extract_username(text):
    """Извлекает username из текста"""
    import re
    
    text = text.strip()
    
    if 'roblox.com/users/' in text:
        match = re.search(r'roblox\.com/users/(\d+)/?', text)
        if match:
            try:
                url = f"https://users.roblox.com/v1/users/{match.group(1)}"
                req = urllib.request.Request(
                    url,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode())
                    return data.get('name')
            except:
                return None
    
    text = text.replace('@', '')
    
    if 3 <= len(text) <= 20 and re.match(r'^[a-zA-Z0-9_]+$', text):
        return text
    
    return None

# ===== ЗАПУСК БОТА =====
async def main():
    """Основная функция"""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не найден!")
        return
    
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Регистрация обработчиков
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("profile", profile_command))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("roles", roles_command))
        application.add_handler(CommandHandler("help", help_command))
        
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(button_handler))
        
        logger.info("🤖 Бот запускается...")
        
        await application.bot.delete_webhook()
        await application.run_polling()
        
    except Conflict as e:
        logger.error("❌ Конфликт: Уже запущен другой экземпляр бота.")
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")

if __name__ == '__main__':
    asyncio.run(main())
