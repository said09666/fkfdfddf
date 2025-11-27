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

# Инициализация
db = Database()

# Добавляем владельцев при запуске
for admin_id in ADMIN_IDS:
    db.set_role(admin_id, 'owner')

# ===== ОСНОВНЫЕ КОМАНДЫ =====
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    try:
        user = update.effective_user
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

🚀 **Для начала работы нажмите кнопку ниже:**
        """
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in start_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /profile"""
    try:
        user = update.effective_user
        await show_profile(update, user)
    except Exception as e:
        logger.error(f"Error in profile_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats"""
    try:
        user = update.effective_user
        
        if not db.is_admin(user.id):
            await update.message.reply_text("❌ У вас нет прав для просмотра статистики.")
            return
        
        await show_stats(update)
    except Exception as e:
        logger.error(f"Error in stats_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def roles_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /roles"""
    try:
        user = update.effective_user
        
        if not db.is_admin(user.id):
            await update.message.reply_text("❌ У вас нет прав для управления ролями.")
            return
        
        await show_role_management(update, user)
    except Exception as e:
        logger.error(f"Error in roles_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    try:
        await show_help(update)
    except Exception as e:
        logger.error(f"Error in help_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

# ===== ПОШАГОВАЯ ВЕРИФИКАЦИЯ =====
async def start_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса верификации - Шаг 1"""
    try:
        user = update.effective_user
        
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
        logger.error(f"Error in start_verification: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def verification_step_2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 2 верификации - ввод никнейма"""
    try:
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        
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
        logger.error(f"Error in verification_step_2: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")

async def verification_step_3(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
    """Шаг 3 верификации - проверка кода"""
    try:
        user = update.effective_user
        
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
        await asyncio.sleep(2)  # Имитация проверки
        
        # В реальном боте здесь должна быть проверка через Roblox API
        # Для демонстрации всегда подтверждаем
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
        logger.info(f"User {user.id} verified as {user_info['username']}")
        
    except Exception as e:
        logger.error(f"Error in verification_step_3: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def cancel_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена верификации"""
    try:
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        
        if user.id in USER_STATES:
            del USER_STATES[user.id]
        
        keyboard = [
            [InlineKeyboardButton("🔐 Начать верификацию", callback_data="verify")],
            [InlineKeyboardButton("📊 Мой профиль", callback_data="profile")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "❌ Верификация отменена.\n\n"
            "Вы можете начать процесс верификации в любое время.",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in cancel_verification: {e}")

# ===== СИСТЕМА ВЫДАЧИ РОЛЕЙ =====
async def start_role_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE, role_key=None):
    """Начало процесса выдачи роли"""
    try:
        query = update.callback_query
        user = query.from_user if query else update.effective_user
        
        if not db.is_admin(user.id):
            if query:
                await query.edit_message_text("❌ У вас нет прав для выдачи ролей.")
            else:
                await update.message.reply_text("❌ У вас нет прав для выдачи ролей.")
            return
        
        user_role = db.get_role(user.id)
        
        if role_key and not db.can_manage_role(user_role, role_key):
            if query:
                await query.edit_message_text("❌ У вас нет прав для выдачи этой роли.")
            else:
                await update.message.reply_text("❌ У вас нет прав для выдачи этой роли.")
            return
        
        if role_key:
            # Сохраняем состояние для выдачи конкретной роли
            USER_STATES[user.id] = {'action': 'set_role', 'role': role_key}
            role_name = ROLES[role_key]
            
            keyboard = [
                [InlineKeyboardButton("❌ Отменить", callback_data="cancel_role_assignment")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            text = f"""
🎭 **Выдача роли: {role_name}**

📝 **Отправьте мне один из вариантов:**
• Telegram ID пользователя
• @username пользователя
• Перешлите сообщение пользователя

💡 *Пользователь должен быть зарегистрирован в боте*
            """
            
            if query:
                await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            else:
                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            # Показываем выбор роли для выдачи
            await show_role_selection(update, user)
            
    except Exception as e:
        logger.error(f"Error in start_role_assignment: {e}")
        if update.callback_query:
            await update.callback_query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")
        else:
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def show_role_selection(update, user):
    """Показывает выбор роли для выдачи"""
    try:
        user_role = db.get_role(user.id)
        
        keyboard = []
        for role_key, role_name in ROLES.items():
            if db.can_manage_role(user_role, role_key):
                keyboard.append([InlineKeyboardButton(f"🎭 Выдать {role_name}", callback_data=f"assign_role_{role_key}")])
        
        keyboard.append([InlineKeyboardButton("👥 Все пользователи", callback_data="show_all_users")])
        keyboard.append([InlineKeyboardButton("📊 Управление пользователями", callback_data="user_management")])
        keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data="admin_panel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = """
🎭 **Выдача ролей**

Выберите роль которую хотите выдать:
        """
        
        if hasattr(update, 'message'):
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Error in show_role_selection: {e}")

async def handle_role_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE, user_input: str):
    """Обработка выдачи роли"""
    try:
        user = update.effective_user
        
        if user.id not in USER_STATES or USER_STATES[user.id]['action'] != 'set_role':
            await update.message.reply_text("❌ Сессия выдачи роли устарела. Начните заново.")
            return
        
        target_role = USER_STATES[user.id]['role']
        role_name = ROLES[target_role]
        
        # Парсим ввод пользователя
        target_user_id = await parse_user_input(user_input, update.message)
        
        if not target_user_id:
            await update.message.reply_text(
                "❌ Не удалось распознать пользователя.\n\n"
                "Отправьте:\n"
                "• Telegram ID (цифры)\n"
                "• @username\n"
                "• Перешлите сообщение"
            )
            return
        
        # Проверяем что пользователь существует в базе
        target_user = db.get_user_by_id(target_user_id)
        if not target_user:
            await update.message.reply_text("❌ Пользователь не найден в базе данных.")
            return
        
        # Проверяем права на выдачу роли
        user_role = db.get_role(user.id)
        
        if not db.can_manage_role(user_role, target_role):
            await update.message.reply_text("❌ У вас нет прав для выдачи этой роли.")
            return
        
        # Выдаем роль
        db.set_role(target_user_id, target_role, user.id)
        
        # Удаляем состояние
        del USER_STATES[user.id]
        
        # Отправляем подтверждение
        target_username = target_user['telegram_username'] or f"ID: {target_user_id}"
        success_text = f"""
✅ **Роль успешно выдана!**

🎭 **Пользователь:** @{target_username}
📛 **Роль:** {role_name}
👤 **Выдал:** @{user.username or user.id}
🕐 **Время:** {datetime.now().strftime('%d.%m.%Y %H:%M')}
        """
        
        keyboard = [
            [InlineKeyboardButton("🎭 Выдать еще роль", callback_data="assign_role")],
            [InlineKeyboardButton("⚙️ Панель управления", callback_data="admin_panel")],
            [InlineKeyboardButton("↩️ Главное меню", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')
        
        # Уведомляем целевого пользователя если возможно
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"🎭 **Вам выдана новая роль!**\n\nВаша роль изменена на: **{role_name}**\n\nИзменил: @{user.username or user.id}",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.warning(f"Could not notify user {target_user_id}: {e}")
            
    except Exception as e:
        logger.error(f"Error in handle_role_assignment: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def parse_user_input(user_input: str, message=None):
    """Парсит ввод пользователя и возвращает ID"""
    try:
        # Если это пересланное сообщение
        if message and message.forward_from:
            return message.forward_from.id
        
        # Если это ID (только цифры)
        if user_input.isdigit():
            return int(user_input)
        
        # Если это @username
        if user_input.startswith('@'):
            # В реальном боте здесь нужно получить ID по username через API
            # Для демонстрации возвращаем как есть
            return user_input[1:]  # Убираем @
        
        # Если это просто текст, пробуем как ID
        try:
            return int(user_input)
        except ValueError:
            return None
            
    except Exception as e:
        logger.error(f"Error parsing user input: {e}")
        return None

async def cancel_role_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена выдачи роли"""
    try:
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        
        if user.id in USER_STATES:
            del USER_STATES[user.id]
        
        keyboard = [
            [InlineKeyboardButton("🎭 Выдать роль", callback_data="assign_role")],
            [InlineKeyboardButton("⚙️ Панель управления", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "❌ Выдача роли отменена.",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in cancel_role_assignment: {e}")

# ===== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ =====
async def show_user_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает управление пользователями"""
    try:
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        
        if not db.is_admin(user.id):
            await query.edit_message_text("❌ У вас нет прав для управления пользователями.")
            return
        
        text = """
👥 **Управление пользователями**

Выберите действие:
        """
        
        keyboard = [
            [InlineKeyboardButton("🚫 Забанить пользователя", callback_data="ban_user")],
            [InlineKeyboardButton("✅ Разбанить пользователя", callback_data="unban_user")],
            [InlineKeyboardButton("📋 Все пользователи", callback_data="show_all_users")],
            [InlineKeyboardButton("📊 Логи действий", callback_data="show_action_logs")],
            [InlineKeyboardButton("↩️ Назад", callback_data="admin_panel")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in show_user_management: {e}")

async def start_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса бана пользователя"""
    try:
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        
        if not db.is_admin(user.id):
            await query.edit_message_text("❌ У вас нет прав для бана пользователей.")
            return
        
        USER_STATES[user.id] = {'action': 'ban_user'}
        
        keyboard = [
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_action")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🚫 **Бан пользователя**\n\n"
            "Отправьте Telegram ID или @username пользователя для бана:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in start_ban_user: {e}")

async def start_unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса разбана пользователя"""
    try:
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        
        if not db.is_admin(user.id):
            await query.edit_message_text("❌ У вас нет прав для разбана пользователей.")
            return
        
        USER_STATES[user.id] = {'action': 'unban_user'}
        
        keyboard = [
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_action")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "✅ **Разбан пользователя**\n\n"
            "Отправьте Telegram ID или @username пользователя для разбана:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in start_unban_user: {e}")

async def handle_user_management(update: Update, context: ContextTypes.DEFAULT_TYPE, user_input: str):
    """Обработка управления пользователями"""
    try:
        user = update.effective_user
        
        if user.id not in USER_STATES:
            await update.message.reply_text("❌ Сессия устарела. Начните заново.")
            return
        
        action = USER_STATES[user.id]['action']
        
        # Парсим ввод пользователя
        target_user_id = await parse_user_input(user_input, update.message)
        
        if not target_user_id:
            await update.message.reply_text("❌ Не удалось распознать пользователя.")
            return
        
        # Проверяем что пользователь существует
        target_user = db.get_user_by_id(target_user_id)
        if not target_user:
            await update.message.reply_text("❌ Пользователь не найден в базе данных.")
            return
        
        target_username = target_user['telegram_username'] or f"ID: {target_user_id}"
        
        if action == 'ban_user':
            db.ban_user(target_user_id, user.id)
            success_text = f"✅ Пользователь @{target_username} забанен."
        
        elif action == 'unban_user':
            db.unban_user(target_user_id, user.id)
            success_text = f"✅ Пользователь @{target_username} разбанен."
        
        # Удаляем состояние
        del USER_STATES[user.id]
        
        keyboard = [
            [InlineKeyboardButton("👥 Управление пользователями", callback_data="user_management")],
            [InlineKeyboardButton("⚙️ Панель управления", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(success_text, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Error in handle_user_management: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена действия"""
    try:
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        
        if user.id in USER_STATES:
            del USER_STATES[user.id]
        
        keyboard = [
            [InlineKeyboardButton("👥 Управление пользователями", callback_data="user_management")],
            [InlineKeyboardButton("⚙️ Панель управления", callback_data="admin_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "❌ Действие отменено.",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Error in cancel_action: {e}")

async def show_action_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает логи действий"""
    try:
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        
        if not db.is_admin(user.id):
            await query.edit_message_text("❌ У вас нет прав для просмотра логов.")
            return
        
        logs = db.get_recent_actions(10)
        
        if not logs:
            logs_text = "📝 Логов действий пока нет."
        else:
            logs_text = "📝 **Последние действия:**\n\n"
            for log in logs:
                user_id, user_name, action, target_id, target_name, details, created_at = log
                user_display = f"@{user_name}" if user_name else f"ID:{user_id}"
                target_display = f"@{target_name}" if target_name else f"ID:{target_id}" if target_id else "N/A"
                
                action_map = {
                    'set_role': 'изменил роль',
                    'ban_user': 'забанил',
                    'unban_user': 'разбанил'
                }
                
                action_text = action_map.get(action, action)
                logs_text += f"• {user_display} {action_text} {target_display}\n"
                if details:
                    logs_text += f"  📄 {details}\n"
                logs_text += f"  🕐 {created_at}\n\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data="show_action_logs")],
            [InlineKeyboardButton("↩️ Назад", callback_data="user_management")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(logs_text, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in show_action_logs: {e}")

# ===== ОБРАБОТЧИКИ СООБЩЕНИЙ =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    try:
        user = update.effective_user
        text = update.message.text
        
        # Игнорируем команды
        if text.startswith('/'):
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

# ===== ОБРАБОТЧИКИ КНОПОК =====
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
            
    except Exception as e:
        logger.error(f"Error in button_handler: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка. Попробуйте позже.")

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def get_roblox_user_info(username):
    """Получает информацию о пользователе Roblox"""
    try:
        # Извлекаем чистый username
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
        logger.error(f"Roblox API error: {e}")
        return {'success': False, 'error': 'Ошибка подключения к Roblox'}

def extract_username(text):
    """Извлекает username из текста"""
    import re
    
    text = text.strip()
    
    # Если это ссылка
    if 'roblox.com/users/' in text:
        match = re.search(r'roblox\.com/users/(\d+)/?', text)
        if match:
            # Получаем username по ID
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
    
    # Если это упоминание
    text = text.replace('@', '')
    
    # Базовая проверка username
    if 3 <= len(text) <= 20 and re.match(r'^[a-zA-Z0-9_]+$', text):
        return text
    
    return None

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
        logger.error(f"Error in show_profile: {e}")

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
        logger.error(f"Error in show_admin_panel: {e}")

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
        logger.error(f"Error in show_stats: {e}")

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
🛠️ **Вы можете выдавать роли:**
        """
        
        # Показываем какие роли может выдавать пользователь
        manageable_roles = []
        for role_key, role_name in ROLES.items():
            if db.can_manage_role(user_role, role_key):
                manageable_roles.append(role_name)
        
        if manageable_roles:
            role_text += "\n".join([f"• {role}" for role in manageable_roles])
        else:
            role_text += "\n❌ Нет доступных ролей для выдачи"
        
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
        logger.error(f"Error in show_role_management: {e}")

async def show_role_users(update, user, data):
    """Показывает пользователей с определенной ролью"""
    try:
        role_key = data.replace("role_", "")
        role_name = ROLES[role_key]
        
        users = db.get_users_by_role(role_key)
        
        if not users:
            users_text = f"❌ Пользователей с ролью {role_name} нет"
        else:
            users_text = f"👥 **Пользователи с ролью {role_name}:**\n\n"
            for i, (user_id, tg_username, roblox_username) in enumerate(users[:15], 1):
                username_display = f"@{tg_username}" if tg_username else f"ID: {user_id}"
                roblox_display = f"({roblox_username})" if roblox_username else ""
                users_text += f"{i}. {username_display} {roblox_display}\n"
            
            if len(users) > 15:
                users_text += f"\n... и еще {len(users) - 15} пользователей"
        
        keyboard = [
            [InlineKeyboardButton("🎭 Выдать эту роль", callback_data=f"assign_role_{role_key}")],
            [InlineKeyboardButton("↩️ Назад к ролям", callback_data="role_management")],
            [InlineKeyboardButton("🔄 Обновить", callback_data=f"role_{role_key}")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.edit_message_text(users_text, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in show_role_users: {e}")

async def show_all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает всех пользователей"""
    try:
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        
        if not db.is_admin(user.id):
            await query.edit_message_text("❌ У вас нет прав для просмотра всех пользователей.")
            return
        
        users = db.get_all_users()
        
        if not users:
            users_text = "❌ В базе нет пользователей."
        else:
            users_text = "👥 **Все пользователи:**\n\n"
            
            current_role = None
            for user_data in users:
                telegram_id, tg_username, roblox_username, role, verified = user_data
                role_name = ROLES.get(role, '👤 Пользователь')
                
                if role != current_role:
                    users_text += f"\n**{role_name}:**\n"
                    current_role = role
                
                username_display = f"@{tg_username}" if tg_username else f"ID: {telegram_id}"
                roblox_display = f"({roblox_username})" if roblox_username else ""
                verified_status = "✅" if verified else "❌"
                users_text += f"• {username_display} {roblox_display} {verified_status}\n"
        
        keyboard = [
            [InlineKeyboardButton("🎭 Выдать роль", callback_data="assign_role")],
            [InlineKeyboardButton("↩️ Назад к ролям", callback_data="role_management")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Разбиваем сообщение если оно слишком длинное
        if len(users_text) > 4000:
            parts = [users_text[i:i+4000] for i in range(0, len(users_text), 4000)]
            for part in parts[:-1]:
                await query.message.reply_text(part, parse_mode='Markdown')
            await query.edit_message_text(parts[-1], reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await query.edit_message_text(users_text, reply_markup=reply_markup, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Error in show_all_users: {e}")

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

# ===== ЗАПУСК БОТА =====
async def main():
    """Основная функция"""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не найден! Проверьте переменные окружения.")
        return
    
    try:
        # Создаем приложение
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Регистрация обработчиков
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("profile", profile_command))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("roles", roles_command))
        application.add_handler(CommandHandler("help", help_command))
        
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
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
