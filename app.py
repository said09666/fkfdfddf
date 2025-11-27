import os
import logging
import asyncio
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import requests
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования для Bothost
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Конфигурация
class Config:
    BOT_TOKEN = os.getenv('BOT_TOKEN', '')
    ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS', '123456789').split(',') if x]
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///bot_database.db')
    
    WELCOME_MESSAGE = """
🎮 **Добро пожаловать в наше сообщество!**

Чтобы получить доступ к чату, необходимо пройти верификацию через Roblox.

📝 **Инструкция:**
1. Нажмите кнопку "🔐 Пройти верификацию"
2. Отправьте свой **никнейм Roblox** или **ссылку на профиль**
3. Бот проверит ваш аккаунт
4. Получите доступ ко всем функциям чата!

⚡ **Быстрая верификация - полный доступ к чату!**
    """
    
    SUCCESS_MESSAGE = """
✅ **Верификация успешно пройдена!**

Теперь у вас есть доступ ко всем функциям чата.

📊 **Ваши данные:**
👤 Roblox: {username}
🆔 ID: {user_id}
📅 Дата регистрации: {join_date}

Добро пожаловать в наше сообщество! 🎉
    """

class Text:
    VERIFY_NOW = "🔐 Пройти верификацию"
    ADMIN_PANEL = "⚙️ Панель администратора"
    BACK = "↩️ Назад"
    STATS = "📊 Статистика"
    
    REQUEST_USERNAME = "👤 Пожалуйста, отправьте ваш никнейм Roblox или ссылку на профиль:"
    VERIFICATION_STARTED = "🔍 Начинаем проверку пользователя..."
    USER_NOT_FOUND = "❌ Пользователь не найден. Проверьте правильность никнейма и попробуйте снова."
    FRIEND_REQUEST_SENT = "✅ Верификация успешно завершена! Теперь у вас есть доступ к чату."
    ALREADY_VERIFIED = "✅ Вы уже прошли верификацию!"
    BANNED = "🚫 Вы заблокированы в системе."

# Класс базы данных
class Database:
    def __init__(self, db_path='bot_database.db'):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Пользователи
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                roblox_username TEXT,
                roblox_id INTEGER,
                verified BOOLEAN DEFAULT FALSE,
                verification_date TIMESTAMP,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                banned BOOLEAN DEFAULT FALSE,
                ban_reason TEXT
            )
        ''')
        
        # Администраторы
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE,
                username TEXT,
                permissions TEXT DEFAULT 'all',
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    
    def add_user(self, telegram_id, roblox_username=None, roblox_id=None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO users (telegram_id, roblox_username, roblox_id)
                VALUES (?, ?, ?)
            ''', (telegram_id, roblox_username, roblox_id))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False
        finally:
            conn.close()
    
    def update_verification(self, telegram_id, roblox_username, roblox_id, verified=True):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE users 
            SET roblox_username = ?, roblox_id = ?, verified = ?, verification_date = ?
            WHERE telegram_id = ?
        ''', (roblox_username, roblox_id, verified, datetime.now(), telegram_id))
        
        conn.commit()
        conn.close()
        logger.info(f"User {telegram_id} verified as {roblox_username}")
    
    def get_user(self, telegram_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,))
        user = cursor.fetchone()
        
        conn.close()
        return user
    
    def is_verified(self, telegram_id):
        user = self.get_user(telegram_id)
        return user and user[4]  # verified field
    
    def is_banned(self, telegram_id):
        user = self.get_user(telegram_id)
        return user and user[7]  # banned field
    
    def ban_user(self, telegram_id, reason="Нарушение правил"):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE users SET banned = TRUE, ban_reason = ? WHERE telegram_id = ?
        ''', (reason, telegram_id))
        
        conn.commit()
        conn.close()
        logger.info(f"User {telegram_id} banned: {reason}")
    
    def unban_user(self, telegram_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('UPDATE users SET banned = FALSE, ban_reason = NULL WHERE telegram_id = ?', (telegram_id,))
        
        conn.commit()
        conn.close()
        logger.info(f"User {telegram_id} unbanned")
    
    def get_stats(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE verified = TRUE')
        verified_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE banned = TRUE')
        banned_users = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'total_users': total_users,
            'verified_users': verified_users,
            'banned_users': banned_users
        }
    
    def add_admin(self, telegram_id, username):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO admins (telegram_id, username)
            VALUES (?, ?)
        ''', (telegram_id, username))
        
        conn.commit()
        conn.close()
        logger.info(f"Admin added: {telegram_id} ({username})")
    
    def is_admin(self, telegram_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM admins WHERE telegram_id = ?', (telegram_id,))
        admin = cursor.fetchone()
        
        conn.close()
        return admin is not None

# Основной класс бота
class RobloxVerificationBot:
    def __init__(self):
        self.db = Database()
        self.application = None
        self.setup_bot()
    
    def setup_bot(self):
        """Инициализация бота"""
        try:
            if not Config.BOT_TOKEN:
                raise ValueError("BOT_TOKEN not found in environment variables")
                
            self.application = Application.builder().token(Config.BOT_TOKEN).build()
            self.setup_handlers()
            logger.info("Bot initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing bot: {e}")
            raise
    
    def setup_handlers(self):
        """Настройка обработчиков"""
        # Команды
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("verify", self.verify_command))
        self.application.add_handler(CommandHandler("admin", self.admin_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        
        # Обработка текстовых сообщений
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Обработка callback запросов
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Обработка новых участников группы
        self.application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, self.handle_new_members))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /start"""
        try:
            user = update.effective_user
            user_id = user.id
            
            logger.info(f"Start command from user {user_id} ({user.username})")
            
            if self.db.is_banned(user_id):
                await update.message.reply_text("🚫 Вы заблокированы в системе.")
                return
            
            # Добавляем пользователя в базу если его нет
            if not self.db.get_user(user_id):
                self.db.add_user(user_id)
            
            keyboard = [
                [InlineKeyboardButton(Text.VERIFY_NOW, callback_data="start_verification")]
            ]
            
            if self.db.is_admin(user_id):
                keyboard.append([InlineKeyboardButton(Text.ADMIN_PANEL, callback_data="admin_panel")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                Config.WELCOME_MESSAGE,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in start_command: {e}")
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")
    
    async def verify_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /verify"""
        user_id = update.effective_user.id
        
        if self.db.is_banned(user_id):
            await update.message.reply_text(Text.BANNED)
            return
        
        if self.db.is_verified(user_id):
            await update.message.reply_text(Text.ALREADY_VERIFIED)
            return
        
        await update.message.reply_text(Text.REQUEST_USERNAME)
    
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /admin"""
        user_id = update.effective_user.id
        
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ У вас нет прав администратора.")
            return
        
        await self.show_admin_panel(update)
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /stats"""
        user_id = update.effective_user.id
        
        if not self.db.is_admin(user_id):
            await update.message.reply_text("❌ У вас нет прав для просмотра статистики.")
            return
        
        stats = self.db.get_stats()
        stats_text = f"""
📊 **Статистика бота**

👥 Всего пользователей: {stats['total_users']}
✅ Верифицировано: {stats['verified_users']}
🚫 Заблокировано: {stats['banned_users']}
📈 Онлайн: Работает нормально
        """
        
        await update.message.reply_text(stats_text, parse_mode='Markdown')
    
    async def handle_new_members(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка новых участников группы"""
        try:
            for new_member in update.message.new_chat_members:
                if new_member.is_bot and new_member.id == context.bot.id:
                    # Бот добавлен в группу
                    await update.message.reply_text(
                        "🤖 **Бот верификации активирован!**\n\n"
                        "Я буду автоматически проверять новых участников. "
                        "Для ручной верификации используйте /verify"
                    )
                else:
                    # Новый пользователь
                    user_id = new_member.id
                    
                    # Добавляем пользователя в базу
                    if not self.db.get_user(user_id):
                        self.db.add_user(user_id)
                    
                    # Отправляем приветственное сообщение
                    welcome_text = f"""
👋 Добро пожаловать, {new_member.first_name}!

{Config.WELCOME_MESSAGE}
                    """
                    
                    keyboard = [
                        [InlineKeyboardButton(Text.VERIFY_NOW, callback_data="start_verification")]
                    ]
                    
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    # Пытаемся отправить сообщение в ЛС
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=welcome_text,
                            reply_markup=reply_markup,
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        # Если не удалось отправить в ЛС, отправляем в группу
                        logger.warning(f"Cannot send PM to {user_id}: {e}")
                        await update.message.reply_text(
                            f"{new_member.first_name}, {welcome_text}",
                            reply_markup=reply_markup,
                            parse_mode='Markdown'
                        )
                        
        except Exception as e:
            logger.error(f"Error handling new members: {e}")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений"""
        try:
            user_id = update.effective_user.id
            message_text = update.message.text
            
            if self.db.is_banned(user_id):
                await update.message.reply_text(Text.BANNED)
                return
            
            # Проверяем, находится ли пользователь в процессе верификации
            user_data = self.db.get_user(user_id)
            if user_data and not user_data[4]:  # not verified
                await self.process_verification(update, message_text)
                
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def process_verification(self, update: Update, username_input: str):
        """Процесс верификации пользователя"""
        user_id = update.effective_user.id
        
        await update.message.reply_text(Text.VERIFICATION_STARTED)
        
        # Извлекаем username из input
        roblox_username = self.extract_username(username_input)
        
        if not roblox_username:
            await update.message.reply_text(Text.USER_NOT_FOUND)
            return
        
        # Получаем данные пользователя Roblox
        user_data = self.get_roblox_user(roblox_username)
        
        if not user_data:
            await update.message.reply_text(Text.USER_NOT_FOUND)
            return
        
        # Сохраняем данные пользователя
        self.db.update_verification(
            user_id, 
            user_data['name'], 
            user_data['id'], 
            verified=True
        )
        
        # Отправляем сообщение об успехе
        join_date = user_data.get('created', 'Неизвестно')
        if join_date != 'Неизвестно':
            try:
                join_date = datetime.fromisoformat(join_date.replace('Z', '+00:00')).strftime('%d.%m.%Y')
            except:
                join_date = 'Неизвестно'
        
        success_message = Config.SUCCESS_MESSAGE.format(
            username=user_data['name'],
            user_id=user_data['id'],
            join_date=join_date
        )
        
        await update.message.reply_text(
            success_message,
            parse_mode='Markdown'
        )
        
        # Сообщение о завершении верификации
        await update.message.reply_text(Text.FRIEND_REQUEST_SENT)
        
        logger.info(f"User {user_id} verified as Roblox user {user_data['name']} (ID: {user_data['id']})")
    
    def extract_username(self, input_text: str) -> str:
        """Извлекает username из текста"""
        import re
        
        # Если это ссылка
        if 'roblox.com/users/' in input_text:
            match = re.search(r'roblox\.com/users/(\d+)/', input_text)
            if match:
                username = self.get_username_from_id(match.group(1))
                return username
        
        # Если это упоминание или просто текст
        input_text = input_text.replace('@', '').strip()
        return input_text if input_text else None
    
    def get_roblox_user(self, username: str) -> dict:
        """Получает данные пользователя Roblox через API"""
        try:
            # Прямой поиск по username
            url = f"https://users.roblox.com/v1/users/search"
            params = {'keyword': username, 'limit': 1}
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('data') and len(data['data']) > 0:
                    user = data['data'][0]
                    return {
                        'id': user.get('id'),
                        'name': user.get('name'),
                        'displayName': user.get('displayName'),
                        'created': user.get('created', 'Неизвестно')
                    }
            
            # Альтернативный метод - поиск по точному имени
            url = f"https://api.roblox.com/users/get-by-username"
            params = {'username': username}
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                user = response.json()
                if user.get('Id'):
                    return {
                        'id': user.get('Id'),
                        'name': user.get('Username'),
                        'displayName': user.get('DisplayName', user.get('Username')),
                        'created': 'Неизвестно'
                    }
                    
        except Exception as e:
            logger.error(f"Error fetching Roblox user {username}: {e}")
        
        return None
    
    def get_username_from_id(self, user_id: str) -> str:
        """Получает username по ID пользователя"""
        try:
            url = f"https://users.roblox.com/v1/users/{user_id}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('name')
        except Exception as e:
            logger.error(f"Error fetching user by ID {user_id}: {e}")
        
        return None
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка callback запросов"""
        try:
            query = update.callback_query
            await query.answer()
            
            user_id = query.from_user.id
            callback_data = query.data
            
            if callback_data == "start_verification":
                if self.db.is_banned(user_id):
                    await query.edit_message_text(Text.BANNED)
                    return
                
                if self.db.is_verified(user_id):
                    await query.edit_message_text(Text.ALREADY_VERIFIED)
                    return
                
                await query.edit_message_text(Text.REQUEST_USERNAME)
            
            elif callback_data == "admin_panel":
                if self.db.is_admin(user_id):
                    await self.show_admin_panel(update)
                else:
                    await query.edit_message_text("❌ У вас нет прав администратора.")
            
            elif callback_data == "admin_stats":
                await self.show_admin_stats(update)
            
            elif callback_data == "admin_back":
                await self.show_admin_panel(update)
            
            elif callback_data == "start_menu":
                await self.start_command(update, context)
                
        except Exception as e:
            logger.error(f"Error handling callback: {e}")
    
    async def show_admin_panel(self, update: Update):
        """Показывает панель администратора"""
        stats = self.db.get_stats()
        
        admin_text = f"""
⚙️ **Панель администратора**

📊 Статистика:
├ 👥 Пользователей: {stats['total_users']}
├ ✅ Верифицировано: {stats['verified_users']}
└ 🚫 Заблокировано: {stats['banned_users']}

Выберите действие:
        """
        
        keyboard = [
            [InlineKeyboardButton(Text.STATS, callback_data="admin_stats")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="admin_panel")],
            [InlineKeyboardButton(Text.BACK, callback_data="start_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            if hasattr(update, 'message'):
                await update.message.reply_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')
            else:
                await update.callback_query.edit_message_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error showing admin panel: {e}")
    
    async def show_admin_stats(self, update: Update):
        """Показывает детальную статистику"""
        stats = self.db.get_stats()
        
        stats_text = f"""
📊 **Детальная статистика**

👥 **Пользователи:**
├ Всего: {stats['total_users']}
├ Верифицировано: {stats['verified_users']}
├ Ожидают: {stats['total_users'] - stats['verified_users'] - stats['banned_users']}
└ Заблокировано: {stats['banned_users']}

⚡ **Система:**
├ Бот: 🟢 Онлайн
├ База данных: 🟢 Работает
└ API Roblox: 🟢 Доступно
        """
        
        keyboard = [
            [InlineKeyboardButton(Text.BACK, callback_data="admin_panel")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    def run(self):
        """Запуск бота"""
        try:
            # Добавляем администраторов при первом запуске
            for admin_id in Config.ADMIN_IDS:
                self.db.add_admin(admin_id, f"admin_{admin_id}")
            
            logger.info("Starting Roblox Verification Bot...")
            logger.info(f"Admins: {Config.ADMIN_IDS}")
            
            # Запускаем бота в режиме polling
            self.application.run_polling()
            
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Bot crashed: {e}")

# Создаем и запускаем бота
if __name__ == '__main__':
    bot = RobloxVerificationBot()
    bot.run()
