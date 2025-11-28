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

# Состояния пользователей
USER_STATES = {}

class Database:
    def __init__(self, db_path='bot_database.db'):
        self.db_path = db_path
        self.init_db()
    
    def get_connection(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)
    
    def init_db(self):
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
                    role TEXT DEFAULT 'user'
                )
            ''')
            
            # Добавляем владельцев
            for admin_id in ADMIN_IDS:
                cursor.execute(
                    'INSERT OR REPLACE INTO users (telegram_id, role) VALUES (?, ?)',
                    (admin_id, 'owner')
                )
            
            conn.commit()
            logger.info("✅ База данных инициализирована")
            
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации БД: {e}")
        finally:
            conn.close()
    
    def add_user(self, telegram_id, telegram_username=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'INSERT OR IGNORE INTO users (telegram_id, telegram_username) VALUES (?, ?)',
                (telegram_id, telegram_username)
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Ошибка добавления пользователя: {e}")
        finally:
            conn.close()
    
    def is_verified(self, telegram_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT verified FROM users WHERE telegram_id = ?', (telegram_id,))
            result = cursor.fetchone()
            return result and result[0] == 1
        except Exception as e:
            logger.error(f"Ошибка проверки верификации: {e}")
            return False
        finally:
            conn.close()
    
    def is_banned(self, telegram_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT banned FROM users WHERE telegram_id = ?', (telegram_id,))
            result = cursor.fetchone()
            return result and result[0] == 1
        except Exception as e:
            logger.error(f"Ошибка проверки бана: {e}")
            return False
        finally:
            conn.close()
    
    def get_role(self, telegram_id):
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
    
    def is_admin(self, telegram_id):
        role = self.get_role(telegram_id)
        return role in ['admin', 'owner']
    
    def is_owner(self, telegram_id):
        return self.get_role(telegram_id) == 'owner'
    
    def get_user_stats(self, telegram_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'SELECT roblox_username, verified, verified_at, role FROM users WHERE telegram_id = ?', 
                (telegram_id,)
            )
            return cursor.fetchone()
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return None
        finally:
            conn.close()
    
    def generate_verification_code(self):
        return ''.join(random.choices(string.ascii_uppercase, k=6))
    
    def set_verification_code(self, telegram_id, code):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'UPDATE users SET verification_code = ? WHERE telegram_id = ?',
                (code, telegram_id)
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Ошибка установки кода: {e}")
        finally:
            conn.close()
    
    def set_verified(self, telegram_id, roblox_username, roblox_id=None):
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
        except Exception as e:
            logger.error(f"Ошибка установки верификации: {e}")
        finally:
            conn.close()
    
    def get_verification_code(self, telegram_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT verification_code FROM users WHERE telegram_id = ?', (telegram_id,))
            result = cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Ошибка получения кода: {e}")
            return None
        finally:
            conn.close()
    
    def set_role(self, telegram_id, role):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'UPDATE users SET role = ? WHERE telegram_id = ?',
                (role, telegram_id)
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Ошибка установки роли: {e}")
        finally:
            conn.close()
    
    def get_bot_stats(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT COUNT(*) FROM users')
            total_users = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM users WHERE verified = TRUE')
            verified_users = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM users WHERE banned = TRUE')
            banned_users = cursor.fetchone()[0]
            
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
            logger.error(f"Ошибка получения статистики: {e}")
            return {
                'total_users': 0,
                'verified_users': 0,
                'banned_users': 0,
                'role_stats': {role: 0 for role in ROLES.keys()}
            }
        finally:
            conn.close()

# Инициализация базы данных
db = Database()

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
        
        keyboard.append([InlineKeyboardButton("📊 Мой профиль", callback_data="profile")])
        
        if db.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("⚙️ Панель управления", callback_data="admin_panel")])
        
        keyboard.append([InlineKeyboardButton("🆘 Помощь", callback_data="help")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = f"""
🎮 **Добро пожаловать в Roblox Verification Bot!**

🤖 **Ваш статус: {role_name}**

📋 **Основные функции:**
✅ Пошаговая верификация Roblox
🎭 Система ролей и прав
📊 Детальная статистика

🚀 **Выберите действие:**
        """
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в start_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка.")

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /profile"""
    try:
        user = update.effective_user
        await show_profile(update, user)
    except Exception as e:
        logger.error(f"Ошибка в profile_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats"""
    try:
        user = update.effective_user
        
        if not db.is_admin(user.id):
            await update.message.reply_text("❌ У вас нет прав для просмотра статистики.")
            return
        
        await show_stats(update)
    except Exception as e:
        logger.error(f"Ошибка в stats_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка.")

async def roles_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /roles"""
    try:
        user = update.effective_user
        
        if not db.is_admin(user.id):
            await update.message.reply_text("❌ У вас нет прав для управления ролями.")
            return
        
        await show_role_management(update, user)
    except Exception as e:
        logger.error(f"Ошибка в roles_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    try:
        await show_help(update)
    except Exception as e:
        logger.error(f"Ошибка в help_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка.")

# ===== ВЕРИФИКАЦИЯ =====
async def start_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало верификации"""
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
                    f"✅ Вы уже верифицированы как `{roblox_username}`",
                    parse_mode='Markdown'
                )
            return
        
        verification_code = db.generate_verification_code()
        db.set_verification_code(user.id, verification_code)
        
        USER_STATES[user.id] = {'step': 1, 'code': verification_code}
        
        keyboard = [
            [InlineKeyboardButton("✅ Я добавил код в описание", callback_data="verification_step_2")],
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_verification")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🔐 **ШАГ 1 из 3: Добавьте код в описание Roblox**\n\n"
            f"📝 **Ваш код:** `{verification_code}`\n\n"
            f"**Инструкция:**\n"
            f"1. Откройте Roblox\n"
            f"2. Добавьте код в описание профиля\n"
            f"3. Сохраните изменения\n"
            f"4. Нажмите кнопку ниже",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Ошибка в start_verification: {e}")
        await update.message.reply_text("❌ Произошла ошибка.")

async def verification_step_2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 2 верификации"""
    try:
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        
        if user.id not in USER_STATES:
            await query.edit_message_text("❌ Сессия устарела. Начните заново.")
            return
        
        USER_STATES[user.id]['step'] = 2
        
        keyboard = [
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_verification")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"👤 **ШАГ 2 из 3: Введите ваш никнейм Roblox**\n\n"
            f"📝 **Отправьте ваш никнейм:**\n"
            f"• Никнейм (например: `AlexRoblox`)\n"
            f"• Ссылку на профиль\n"
            f"• ID пользователя\n\n"
            f"💡 Код: `{USER_STATES[user.id]['code']}`",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Ошибка в verification_step_2: {e}")

async def verification_step_3(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
    """Шаг 3 верификации"""
    try:
        user = update.effective_user
        
        if user.id not in USER_STATES:
            await update.message.reply_text("❌ Сессия устарела. Начните заново.")
            return
        
        verification_code = USER_STATES[user.id]['code']
        
        await update.message.reply_text("🔍 Проверяем аккаунт...")
        
        user_info = get_roblox_user_info(username)
        
        if not user_info['success']:
            await update.message.reply_text(
                f"❌ Ошибка: {user_info['error']}\n\nПопробуйте снова.",
                parse_mode='Markdown'
            )
            return
        
        # Заглушка проверки кода
        await update.message.reply_text("🔐 Проверяем код...")
        await asyncio.sleep(2)
        
        code_verified = True
        
        if not code_verified:
            await update.message.reply_text(
                f"❌ Код не найден!\n\nКод: `{verification_code}`\n\nПроверьте и попробуйте снова.",
                parse_mode='Markdown'
            )
            return
        
        # Верификация успешна
        db.set_verified(user.id, user_info['username'], user_info['id'])
        
        if user.id in USER_STATES:
            del USER_STATES[user.id]
        
        keyboard = [
            [InlineKeyboardButton("📊 Мой профиль", callback_data="profile")],
            [InlineKeyboardButton("🎉 Главное меню", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        success_text = f"""
✅ **ВЕРИФИКАЦИЯ УСПЕШНА!**

🎮 **Ваши данные:**
├ Roblox: `{user_info['username']}`
├ ID: `{user_info['id']}`
└ Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}

🎉 Теперь вам доступны все функции!
        """
        
        await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в verification_step_3: {e}")
        await update.message.reply_text("❌ Произошла ошибка.")

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
            "❌ Верификация отменена.",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Ошибка в cancel_verification: {e}")

# ===== ОБРАБОТЧИКИ СООБЩЕНИЙ =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    try:
        user = update.effective_user
        text = update.message.text
        
        if text.startswith('/'):
            return
        
        if db.is_banned(user.id):
            await update.message.reply_text("🚫 Вы заблокированы в системе.")
            return
        
        if user.id in USER_STATES and USER_STATES[user.id].get('step') == 2:
            await verification_step_3(update, context, text)
            return
        
        if db.is_verified(user.id):
            user_stats = db.get_user_stats(user.id)
            if user_stats:
                roblox_username = user_stats[0]
                await update.message.reply_text(
                    f"✅ Вы верифицированы как `{roblox_username}`\n\nИспользуйте команды или кнопки.",
                    parse_mode='Markdown'
                )
                
    except Exception as e:
        logger.error(f"Ошибка в handle_message: {e}")

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
        
        elif data == "help":
            await show_help(query)
        
        elif data == "back_to_main":
            await start_command(update, context)
            
    except Exception as e:
        logger.error(f"Ошибка в button_handler: {e}")
        await update.callback_query.edit_message_text("❌ Произошла ошибка.")

# ===== ФУНКЦИИ ПОКАЗА ИНФОРМАЦИИ =====
async def show_profile(update, user):
    """Показывает профиль пользователя"""
    try:
        stats = db.get_user_stats(user.id)
        
        if not stats:
            profile_text = "❌ Вы не зарегистрированы."
        else:
            roblox_username, verified, verified_at, role = stats
            role_name = ROLES.get(role, '👤 Пользователь')
            
            if verified:
                profile_text = f"""
📊 **Ваш профиль**

👤 Telegram: @{user.username or 'N/A'}
🆔 ID: `{user.id}`
🎮 Roblox: `{roblox_username or 'N/A'}`
🎭 Роль: {role_name}
✅ Статус: Верифицирован
                """
            else:
                profile_text = f"""
📊 **Ваш профиль**

👤 Telegram: @{user.username or 'N/A'}
🆔 ID: `{user.id}`
🎭 Роль: {role_name}
❌ Статус: Не верифицирован

💡 Пройдите верификацию
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
            [InlineKeyboardButton("📈 Статистика", callback_data="stats")],
            [InlineKeyboardButton("🎭 Управление ролями", callback_data="role_management")],
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
        
        role_stats_text = ""
        for role, count in stats['role_stats'].items():
            if count > 0:
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
👑 Владелец - Полный доступ
⚡ Админ - Управление ботом
🛡️ Модератор - Модерация
✅ Гарант - Проверенные пользователи
👤 Пользователь - Обычный пользователь
🚫 Скамер - Заблокированные

💡 **Ваша роль: {user_role_name}**

🛠️ **Функции управления ролями скоро будут добавлены**
        """
        
        keyboard = [
            [InlineKeyboardButton("↩️ Назад", callback_data="admin_panel")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="role_management")]
        ]
        
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
4. Получите доступ к функциям

🎭 **Система ролей:**
👑 Владелец - Полный доступ
⚡ Админ - Управление ботом
🛡️ Модератор - Модерация
✅ Гарант - Проверенные пользователи
👤 Пользователь - Обычный пользователь
🚫 Скамер - Заблокированные

❓ **Проблемы?**
• Убедитесь что код точно скопирован
• Проверьте что описание сохранено
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
        import re
        
        text = username.strip()
        
        if 'roblox.com/users/' in text:
            match = re.search(r'roblox\.com/users/(\d+)/?', text)
            if match:
                try:
                    url = f"https://users.roblox.com/v1/users/{match.group(1)}"
                    req = urllib.request.Request(url)
                    with urllib.request.urlopen(req, timeout=5) as response:
                        data = json.loads(response.read().decode())
                        return {
                            'id': data.get('id'),
                            'username': data.get('name'),
                            'displayName': data.get('displayName', data.get('name')),
                            'success': True
                        }
                except:
                    return {'success': False, 'error': 'Ошибка получения данных'}
        
        text = text.replace('@', '')
        
        if 3 <= len(text) <= 20 and re.match(r'^[a-zA-Z0-9_]+$', text):
            try:
                params = urllib.parse.urlencode({'keyword': text, 'limit': 10})
                url = f"https://users.roblox.com/v1/users/search?{params}"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read().decode())
                    if data.get('data'):
                        for user in data['data']:
                            if user['name'].lower() == text.lower():
                                return {
                                    'id': user['id'],
                                    'username': user['name'],
                                    'displayName': user.get('displayName', user['name']),
                                    'success': True
                                }
            except:
                pass
        
        return {'success': False, 'error': 'Пользователь не найден'}
        
    except Exception as e:
        logger.error(f"Ошибка Roblox API: {e}")
        return {'success': False, 'error': 'Ошибка подключения'}

# ===== ЗАПУСК БОТА =====
async def main():
    """Основная функция"""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не найден!")
        return
    
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Регистрация обработчиков команд
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("profile", profile_command))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("roles", roles_command))
        application.add_handler(CommandHandler("help", help_command))
        
        # Обработчики сообщений
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(button_handler))
        
        logger.info("🤖 Бот запускается...")
        
        await application.bot.delete_webhook()
        await application.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")

if __name__ == '__main__':
    asyncio.run(main())
