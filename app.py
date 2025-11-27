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

# Конфигурация - ваш ID установлен как владелец
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

# Иерархия ролей (кто кого может назначать)
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

# Настройки для групп
GROUP_SETTINGS = {
    'welcome_message': True,
    'auto_verification_check': True,
    'delete_unverified_messages': True,
    'welcome_timeout': 300  # 5 минут
}

class Database:
    def __init__(self):
        self.conn = sqlite3.connect('bot.db', check_same_thread=False)
        self.init_db()
    
    def init_db(self):
        cursor = self.conn.cursor()
        
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
                date TEXT,
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
        
        self.conn.commit()
        logger.info("✅ База данных инициализирована")
    
    def add_user(self, telegram_id, telegram_username=None):
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT OR IGNORE INTO users (telegram_id, telegram_username) VALUES (?, ?)',
            (telegram_id, telegram_username)
        )
        self.conn.commit()
    
    def generate_verification_code(self):
        """Генерирует 6-значный буквенный код"""
        return ''.join(random.choices(string.ascii_uppercase, k=6))
    
    def set_verification_code(self, telegram_id, code):
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE users SET verification_code = ? WHERE telegram_id = ?',
            (code, telegram_id)
        )
        self.conn.commit()
    
    def set_verified(self, telegram_id, roblox_username, roblox_id=None):
        cursor = self.conn.cursor()
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
        self.conn.commit()
    
    def get_verification_code(self, telegram_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT verification_code FROM users WHERE telegram_id = ?', (telegram_id,))
        result = cursor.fetchone()
        return result[0] if result else None
    
    def is_verified(self, telegram_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT verified FROM users WHERE telegram_id = ?', (telegram_id,))
        result = cursor.fetchone()
        return result and result[0]
    
    def is_banned(self, telegram_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT banned FROM users WHERE telegram_id = ?', (telegram_id,))
        result = cursor.fetchone()
        return result and result[0]
    
    def get_role(self, telegram_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT role FROM users WHERE telegram_id = ?', (telegram_id,))
        result = cursor.fetchone()
        return result[0] if result else 'user'
    
    def set_role(self, telegram_id, role, added_by=None):
        cursor = self.conn.cursor()
        cursor.execute(
            'UPDATE users SET role = ?, added_by = ? WHERE telegram_id = ?',
            (role, added_by, telegram_id)
        )
        self.conn.commit()
        logger.info(f"User {telegram_id} role set to {role} by {added_by}")
        
        # Логируем действие
        self.log_action(added_by, 'set_role', telegram_id, f"Role changed to {role}")
    
    def get_user_by_id(self, telegram_id):
        cursor = self.conn.cursor()
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
                'verified': result[4]
            }
        return None
    
    def get_users_by_role(self, role):
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT telegram_id, telegram_username, roblox_username FROM users WHERE role = ?',
            (role,)
        )
        return cursor.fetchall()
    
    def get_all_users(self):
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT telegram_id, telegram_username, roblox_username, role, verified FROM users ORDER BY role, telegram_id'
        )
        return cursor.fetchall()
    
    def ban_user(self, telegram_id, banned_by=None):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET banned = TRUE WHERE telegram_id = ?', (telegram_id,))
        self.conn.commit()
        if banned_by:
            self.log_action(banned_by, 'ban_user', telegram_id, "User banned")
    
    def unban_user(self, telegram_id, unbanned_by=None):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET banned = FALSE WHERE telegram_id = ?', (telegram_id,))
        self.conn.commit()
        if unbanned_by:
            self.log_action(unbanned_by, 'unban_user', telegram_id, "User unbanned")
    
    def get_user_stats(self, telegram_id):
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT roblox_username, verified, verified_at, role FROM users WHERE telegram_id = ?', 
            (telegram_id,)
        )
        result = cursor.fetchone()
        if result:
            return result
        return None
    
    def get_bot_stats(self):
        cursor = self.conn.cursor()
        
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
        
        self.conn.commit()
        
        return {
            'total_users': total_users,
            'verified_users': verified_users,
            'banned_users': banned_users,
            'role_stats': role_stats
        }
    
    def can_manage_role(self, user_role, target_role):
        """Проверяет может ли пользователь управлять определенной ролью"""
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
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO action_logs (user_id, action, target_user_id, details) VALUES (?, ?, ?, ?)',
            (user_id, action, target_user_id, details)
        )
        self.conn.commit()
    
    def get_recent_actions(self, limit=10):
        """Получает последние действия"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT al.user_id, u1.telegram_username, al.action, al.target_user_id, u2.telegram_username, al.details, al.created_at
            FROM action_logs al
            LEFT JOIN users u1 ON al.user_id = u1.telegram_id
            LEFT JOIN users u2 ON al.target_user_id = u2.telegram_id
            ORDER BY al.created_at DESC LIMIT ?
        ''', (limit,))
        return cursor.fetchall()
    
    # Методы для работы с группами
    def get_group_settings(self, chat_id):
        """Получает настройки группы"""
        cursor = self.conn.cursor()
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
    
    def set_group_settings(self, chat_id, welcome_message=True, auto_verification_check=True, 
                          delete_unverified_messages=True, welcome_timeout=300):
        """Устанавливает настройки группы"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO group_settings 
            (chat_id, welcome_message, auto_verification_check, delete_unverified_messages, welcome_timeout)
            VALUES (?, ?, ?, ?, ?)
        ''', (chat_id, welcome_message, auto_verification_check, delete_unverified_messages, welcome_timeout))
        self.conn.commit()
    
    def is_group_registered(self, chat_id):
        """Проверяет зарегистрирована ли группа"""
        return self.get_group_settings(chat_id) is not None

# Инициализация
db = Database()

# Добавляем владельцев при запуске
for admin_id in ADMIN_IDS:
    db.set_role(admin_id, 'owner')

# ===== ФУНКЦИИ ДЛЯ РАБОТЫ В ГРУППАХ =====
async def handle_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка новых участников в группе"""
    try:
        chat = update.effective_chat
        new_members = update.message.new_chat_members
        
        # Проверяем настройки группы
        group_settings = db.get_group_settings(chat.id)
        if not group_settings or not group_settings['welcome_message']:
            return
        
        for member in new_members:
            # Игнорируем самого бота
            if member.id == context.bot.id:
                await update.message.reply_text(
                    "🤖 **Бот верификации активирован!**\n\n"
                    "Я буду проверять верификацию новых участников. "
                    "Для настройки используйте /settings в личных сообщениях с ботом."
                )
                continue
            
            # Добавляем пользователя в базу
            db.add_user(member.id, member.username)
            
            # Проверяем верификацию
            if not db.is_verified(member.id):
                welcome_text = f"""
👋 Добро пожаловать, {member.first_name}!

📋 **Для доступа к чату необходимо пройти верификацию**

🔐 **Процесс верификации:**
1. Нажмите кнопку ниже чтобы начать
2. Добавьте код в описание Roblox аккаунта
3. Введите ваш никнейм Roblox
4. Получите доступ к чату!

🚫 *Сообщения от непроверенных пользователей будут удаляться*
                """
                
                keyboard = [
                    [InlineKeyboardButton("🔐 Начать верификацию", url=f"https://t.me/{(await context.bot.get_me()).username}?start=verify")],
                    [InlineKeyboardButton("📋 Инструкция", url=f"https://t.me/{(await context.bot.get_me()).username}?start=help")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                welcome_msg = await update.message.reply_text(
                    welcome_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
                # Устанавливаем таймер для удаления приветственного сообщения
                if group_settings['welcome_timeout'] > 0:
                    await asyncio.sleep(group_settings['welcome_timeout'])
                    try:
                        await welcome_msg.delete()
                    except Exception as e:
                        logger.warning(f"Could not delete welcome message: {e}")
            else:
                # Пользователь уже верифицирован
                user_stats = db.get_user_stats(member.id)
                if user_stats:
                    roblox_username = user_stats[0]
                    await update.message.reply_text(
                        f"✅ {member.first_name} уже верифицирован как `{roblox_username}`",
                        parse_mode='Markdown'
                    )
                    
    except Exception as e:
        logger.error(f"Error in handle_new_chat_members: {e}")

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений в группе"""
    try:
        chat = update.effective_chat
        user = update.effective_user
        message = update.message
        
        # Игнорируем сообщения от самого бота
        if user.id == context.bot.id:
            return
        
        # Игнорируем команды
        if message.text and message.text.startswith('/'):
            return
        
        # Проверяем настройки группы
        group_settings = db.get_group_settings(chat.id)
        if not group_settings or not group_settings['auto_verification_check']:
            return
        
        # Проверяем верификацию пользователя
        if not db.is_verified(user.id):
            # Проверяем, нужно ли удалять сообщения
            if group_settings['delete_unverified_messages']:
                try:
                    await message.delete()
                    
                    # Отправляем предупреждение
                    warning_msg = await message.reply_text(
                        f"🚫 {user.first_name}, вы не прошли верификацию!\n\n"
                        f"Для отправки сообщений в этот чат необходимо пройти верификацию Roblox.\n"
                        f"Напишите мне в личные сообщения: @{(await context.bot.get_me()).username}",
                        parse_mode='Markdown'
                    )
                    
                    # Удаляем предупреждение через 10 секунд
                    await asyncio.sleep(10)
                    await warning_msg.delete()
                    
                except Exception as e:
                    logger.warning(f"Could not delete message from unverified user: {e}")
            
        # Проверяем бан пользователя
        elif db.is_banned(user.id):
            try:
                await message.delete()
                await message.reply_text(
                    f"🚫 {user.first_name}, вы заблокированы в системе.",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.warning(f"Could not delete message from banned user: {e}")
                
    except Exception as e:
        logger.error(f"Error in handle_group_message: {e}")

async def group_settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для настройки группы"""
    try:
        chat = update.effective_chat
        user = update.effective_user
        
        # Проверяем права пользователя
        if not await is_user_admin(update, context, user.id):
            await update.message.reply_text("❌ Только администраторы могут настраивать группу.")
            return
        
        # Получаем текущие настройки
        group_settings = db.get_group_settings(chat.id)
        if not group_settings:
            # Создаем настройки по умолчанию
            db.set_group_settings(chat.id)
            group_settings = db.get_group_settings(chat.id)
        
        settings_text = f"""
⚙️ **Настройки группы**

📋 **Текущие настройки:**
├ Приветственное сообщение: {'✅ Включено' if group_settings['welcome_message'] else '❌ Выключено'}
├ Проверка верификации: {'✅ Включена' if group_settings['auto_verification_check'] else '❌ Выключена'}
├ Удаление сообщений: {'✅ Включено' if group_settings['delete_unverified_messages'] else '❌ Выключено'}
└ Таймаут приветствия: {group_settings['welcome_timeout']} сек.

🛠️ **Выберите настройку для изменения:**
        """
        
        keyboard = [
            [
                InlineKeyboardButton("👋 Приветствие", callback_data=f"group_toggle_welcome_{chat.id}"),
                InlineKeyboardButton("🔐 Проверка", callback_data=f"group_toggle_check_{chat.id}")
            ],
            [
                InlineKeyboardButton("🗑️ Удаление сообщений", callback_data=f"group_toggle_delete_{chat.id}"),
                InlineKeyboardButton("⏰ Таймаут", callback_data=f"group_set_timeout_{chat.id}")
            ],
            [
                InlineKeyboardButton("🔄 Сбросить настройки", callback_data=f"group_reset_{chat.id}"),
                InlineKeyboardButton("❌ Закрыть", callback_data="close_settings")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(settings_text, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in group_settings_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def is_user_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Проверяет является ли пользователь администратором группы"""
    try:
        chat = update.effective_chat
        chat_member = await context.bot.get_chat_member(chat.id, user_id)
        return chat_member.status in ['administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

async def handle_group_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка callback для настроек группы"""
    try:
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        data = query.data
        
        if data == "close_settings":
            await query.edit_message_text("⚙️ Настройки закрыты.")
            return
        
        # Получаем ID чата из callback data
        if data.startswith("group_toggle_welcome_"):
            chat_id = int(data.replace("group_toggle_welcome_", ""))
            await toggle_group_setting(query, chat_id, 'welcome_message', user)
        
        elif data.startswith("group_toggle_check_"):
            chat_id = int(data.replace("group_toggle_check_", ""))
            await toggle_group_setting(query, chat_id, 'auto_verification_check', user)
        
        elif data.startswith("group_toggle_delete_"):
            chat_id = int(data.replace("group_toggle_delete_", ""))
            await toggle_group_setting(query, chat_id, 'delete_unverified_messages', user)
        
        elif data.startswith("group_set_timeout_"):
            chat_id = int(data.replace("group_set_timeout_", ""))
            await set_group_timeout(query, chat_id, user)
        
        elif data.startswith("group_reset_"):
            chat_id = int(data.replace("group_reset_", ""))
            await reset_group_settings(query, chat_id, user)
            
    except Exception as e:
        logger.error(f"Error in handle_group_settings_callback: {e}")

async def toggle_group_setting(query, chat_id, setting_name, user):
    """Переключает настройку группы"""
    try:
        # Проверяем права пользователя
        chat_member = await query.bot.get_chat_member(chat_id, user.id)
        if chat_member.status not in ['administrator', 'creator']:
            await query.edit_message_text("❌ Только администраторы могут изменять настройки группы.")
            return
        
        # Получаем текущие настройки
        group_settings = db.get_group_settings(chat_id)
        if not group_settings:
            group_settings = {
                'welcome_message': True,
                'auto_verification_check': True,
                'delete_unverified_messages': True,
                'welcome_timeout': 300
            }
        
        # Переключаем настройку
        group_settings[setting_name] = not group_settings[setting_name]
        
        # Сохраняем настройки
        db.set_group_settings(
            chat_id,
            group_settings['welcome_message'],
            group_settings['auto_verification_check'],
            group_settings['delete_unverified_messages'],
            group_settings['welcome_timeout']
        )
        
        # Обновляем сообщение
        settings_text = f"""
⚙️ **Настройки группы**

📋 **Текущие настройки:**
├ Приветственное сообщение: {'✅ Включено' if group_settings['welcome_message'] else '❌ Выключено'}
├ Проверка верификации: {'✅ Включена' if group_settings['auto_verification_check'] else '❌ Выключена'}
├ Удаление сообщений: {'✅ Включено' if group_settings['delete_unverified_messages'] else '❌ Выключено'}
└ Таймаут приветствия: {group_settings['welcome_timeout']} сек.

🛠️ **Выберите настройку для изменения:**
        """
        
        keyboard = [
            [
                InlineKeyboardButton("👋 Приветствие", callback_data=f"group_toggle_welcome_{chat_id}"),
                InlineKeyboardButton("🔐 Проверка", callback_data=f"group_toggle_check_{chat_id}")
            ],
            [
                InlineKeyboardButton("🗑️ Удаление сообщений", callback_data=f"group_toggle_delete_{chat_id}"),
                InlineKeyboardButton("⏰ Таймаут", callback_data=f"group_set_timeout_{chat_id}")
            ],
            [
                InlineKeyboardButton("🔄 Сбросить настройки", callback_data=f"group_reset_{chat_id}"),
                InlineKeyboardButton("❌ Закрыть", callback_data="close_settings")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(settings_text, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in toggle_group_setting: {e}")

async def set_group_timeout(query, chat_id, user):
    """Устанавливает таймаут приветственного сообщения"""
    try:
        # Проверяем права пользователя
        chat_member = await query.bot.get_chat_member(chat_id, user.id)
        if chat_member.status not in ['administrator', 'creator']:
            await query.edit_message_text("❌ Только администраторы могут изменять настройки группы.")
            return
        
        await query.edit_message_text(
            "⏰ **Установите таймаут приветственного сообщения**\n\n"
            "Отправьте число секунд (0 = не удалять):",
            parse_mode='Markdown'
        )
        
        # Сохраняем состояние
        USER_STATES[user.id] = {
            'action': 'set_group_timeout',
            'chat_id': chat_id
        }
        
    except Exception as e:
        logger.error(f"Error in set_group_timeout: {e}")

async def reset_group_settings(query, chat_id, user):
    """Сбрасывает настройки группы к значениям по умолчанию"""
    try:
        # Проверяем права пользователя
        chat_member = await query.bot.get_chat_member(chat_id, user.id)
        if chat_member.status not in ['administrator', 'creator']:
            await query.edit_message_text("❌ Только администраторы могут изменять настройки группы.")
            return
        
        # Сбрасываем настройки
        db.set_group_settings(chat_id)
        
        await query.edit_message_text(
            "✅ Настройки группы сброшены к значениям по умолчанию.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in reset_group_settings: {e}")

async def handle_group_timeout_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка установки таймаута группы"""
    try:
        user = update.effective_user
        
        if user.id not in USER_STATES or USER_STATES[user.id]['action'] != 'set_group_timeout':
            return
        
        timeout_input = update.message.text
        
        if not timeout_input.isdigit():
            await update.message.reply_text("❌ Пожалуйста, введите число секунд.")
            return
        
        timeout = int(timeout_input)
        chat_id = USER_STATES[user.id]['chat_id']
        
        # Обновляем настройки
        group_settings = db.get_group_settings(chat_id)
        if group_settings:
            db.set_group_settings(
                chat_id,
                group_settings['welcome_message'],
                group_settings['auto_verification_check'],
                group_settings['delete_unverified_messages'],
                timeout
            )
        
        # Удаляем состояние
        del USER_STATES[user.id]
        
        await update.message.reply_text(
            f"✅ Таймаут приветственного сообщения установлен на {timeout} секунд.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in handle_group_timeout_setting: {e}")

# ===== ОБНОВЛЕННЫЕ ОБРАБОТЧИКИ СООБЩЕНИЙ =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    try:
        # Игнорируем сообщения из групп (они обрабатываются отдельно)
        if update.effective_chat.type in ['group', 'supergroup']:
            return
            
        user = update.effective_user
        text = update.message.text
        
        # Игнорируем команды
        if text and text.startswith('/'):
            return
        
        # Проверяем бан
        if db.is_banned(user.id):
            await update.message.reply_text("🚫 Вы заблокированы в системе.")
            return
        
        # Проверяем состояние выдачи роли
        if user.id in USER_STATES and USER_STATES[user.id]['action'] == 'set_role':
            await handle_role_assignment(update, context, text)
            return
        
        # Проверяем состояние управления пользователями
        if user.id in USER_STATES and USER_STATES[user.id]['action'] in ['ban_user', 'unban_user']:
            await handle_user_management(update, context, text)
            return
        
        # Проверяем состояние верификации
        if user.id in USER_STATES and USER_STATES[user.id].get('step') == 2:
            await verification_step_3(update, context, text)
            return
        
        # Проверяем состояние настройки таймаута группы
        if user.id in USER_STATES and USER_STATES[user.id]['action'] == 'set_group_timeout':
            await handle_group_timeout_setting(update, context)
            return
        
        # Если пользователь уже верифицирован
        if db.is_verified(user.id):
            user_stats = db.get_user_stats(user.id)
            if user_stats:
                roblox_username = user_stats[0]
                await update.message.reply_text(
                    f"✅ Вы уже верифицированы как `{roblox_username}`\n\n"
                    f"Для смены аккаунта обратитесь к администратору.",
                    parse_mode='Markdown'
                )
                
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

# ===== ОБНОВЛЕННЫЙ START COMMAND =====
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    try:
        user = update.effective_user
        chat = update.effective_chat
        
        # Если команда вызвана в группе
        if chat.type in ['group', 'supergroup']:
            await group_settings_command(update, context)
            return
            
        db.add_user(user.id, user.username)
        
        if db.is_banned(user.id):
            await update.message.reply_text("🚫 Вы заблокированы в системе.")
            return
        
        user_role = db.get_role(user.id)
        role_name = ROLES.get(user_role, '👤 Пользователь')
        
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
🏠 **Работа в группах:**
• Автоматическая проверка верификации
• Приветственные сообщения
• Защита от непроверенных пользователей

🚀 **Для начала работы нажмите кнопку ниже:**
        """
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in start_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

# ===== ОБНОВЛЕННЫЙ HELP COMMAND =====
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

👥 **Управление пользователями:**
• Бан/разбан пользователей
• Просмотр всех пользователей
• Логи действий

🏠 **Работа в группах:**
/settings - Настройки группы (для админов)
• Автоматическая проверка верификации
• Приветственные сообщения для новых участников
• Удаление сообщений от непроверенных пользователей

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
        logger.error(f"Error in show_help: {e}")

# ===== ОБНОВЛЕННЫЙ BUTTON HANDLER =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки"""
    try:
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        data = query.data
        
        if data == "verify":
            await start_verification(update, context)
        
        elif data == "verification_step_2":
            await verification_step_2(update, context)
        
        elif data == "cancel_verification":
            await cancel_verification(update, context)
        
        elif data == "profile":
            await show_profile(query, user)
        
        elif data == "admin_panel":
            await show_admin_panel(query, user)
        
        elif data == "stats":
            await show_stats(query)
        
        elif data == "role_management":
            await show_role_management(query, user)
        
        elif data == "user_management":
            await show_user_management(update, context)
        
        elif data == "assign_role":
            await start_role_assignment(update, context)
        
        elif data.startswith("assign_role_"):
            role_key = data.replace("assign_role_", "")
            await start_role_assignment(update, context, role_key)
        
        elif data == "show_all_users":
            await show_all_users(update, context)
        
        elif data == "cancel_role_assignment":
            await cancel_role_assignment(update, context)
        
        elif data == "ban_user":
            await start_ban_user(update, context)
        
        elif data == "unban_user":
            await start_unban_user(update, context)
        
        elif data == "cancel_action":
            await cancel_action(update, context)
        
        elif data == "show_action_logs":
            await show_action_logs(update, context)
        
        elif data.startswith("role_"):
            await show_role_users(query, user, data)
        
        elif data == "help":
            await show_help(query)
        
        elif data == "back_to_main":
            await start_command(update, context)
        
        # Обработка callback для настроек группы
        elif data.startswith("group_"):
            await handle_group_settings_callback(update, context)
        
        elif data == "close_settings":
            await query.edit_message_text("⚙️ Настройки закрыты.")
            
    except Exception as e:
        logger.error(f"Error in button_handler: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")

# ===== ЗАПУСК БОТА =====
async def main():
    """Основная функция"""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не найден! Проверьте переменные окружения.")
        return
    
    try:
        # Создаем приложение
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Регистрация обработчиков для личных сообщений
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("profile", profile_command))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("roles", roles_command))
        application.add_handler(CommandHandler("help", help_command))
        
        # Обработчики для групп
        application.add_handler(CommandHandler("settings", group_settings_command))
        application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_chat_members))
        application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, handle_group_message))
        
        # Общие обработчики сообщений
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_message))
        application.add_handler(CallbackQueryHandler(button_handler))
        
        # Запуск бота с обработкой ошибок
        logger.info("🤖 Бот запускается...")
        logger.info(f"👑 Владелец: {ADMIN_IDS[0]}")
        
        # Очищаем webhook перед запуском polling
        await application.bot.delete_webhook()
        
        # Запускаем polling
        await application.run_polling()
        
    except Conflict as e:
        logger.error(f"❌ Конфликт: Уже запущен другой экземпляр бота. Остановите другие экземпляры.")
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")

if __name__ == '__main__':
    asyncio.run(main())
