import os
import logging
import sqlite3
import requests
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
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x]

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
                verified_at TIMESTAMP,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                banned BOOLEAN DEFAULT FALSE
            )
        ''')
        
        # Администраторы
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    
    def set_verified(self, telegram_id, roblox_username, roblox_id=None):
        cursor = self.conn.cursor()
        cursor.execute(
            '''UPDATE users SET 
                roblox_username = ?, 
                roblox_id = ?, 
                verified = TRUE, 
                verified_at = ? 
            WHERE telegram_id = ?''',
            (roblox_username, roblox_id, datetime.now(), telegram_id)
        )
        self.conn.commit()
    
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
    
    def ban_user(self, telegram_id):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET banned = TRUE WHERE telegram_id = ?', (telegram_id,))
        self.conn.commit()
    
    def unban_user(self, telegram_id):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET banned = FALSE WHERE telegram_id = ?', (telegram_id,))
        self.conn.commit()
    
    def get_user_stats(self, telegram_id):
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT roblox_username, verified, verified_at FROM users WHERE telegram_id = ?', 
            (telegram_id,)
        )
        return cursor.fetchone()
    
    def get_bot_stats(self):
        cursor = self.conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE verified = TRUE')
        verified_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE banned = TRUE')
        banned_users = cursor.fetchone()[0]
        
        return {
            'total_users': total_users,
            'verified_users': verified_users,
            'banned_users': banned_users
        }
    
    def add_admin(self, telegram_id, username):
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO admins (telegram_id, username) VALUES (?, ?)',
            (telegram_id, username)
        )
        self.conn.commit()
    
    def is_admin(self, telegram_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT 1 FROM admins WHERE telegram_id = ?', (telegram_id,))
        return cursor.fetchone() is not None

class RobloxAPI:
    @staticmethod
    def get_user_info(username):
        """Получает информацию о пользователе Roblox"""
        try:
            # Поиск пользователя
            url = "https://users.roblox.com/v1/users/search"
            params = {'keyword': username, 'limit': 10}
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('data'):
                    for user in data['data']:
                        if user['name'].lower() == username.lower():
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

# Инициализация
db = Database()
roblox_api = RobloxAPI()

# Добавляем администраторов при запуске
for admin_id in ADMIN_IDS:
    db.add_admin(admin_id, f"admin_{admin_id}")

app = Application.builder().token(BOT_TOKEN).build()

# ===== ОСНОВНЫЕ КОМАНДЫ =====
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    db.add_user(user.id, user.username)
    
    if db.is_banned(user.id):
        await update.message.reply_text("🚫 Вы заблокированы в системе.")
        return
    
    keyboard = []
    
    if not db.is_verified(user.id):
        keyboard.append([InlineKeyboardButton("🔐 Пройти верификацию", callback_data="verify")])
    
    if db.is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ Панель администратора", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = """
🎮 **Добро пожаловать в Roblox Verification Bot!**

🤖 **Я помогу вам пройти верификацию через Roblox аккаунт**

📋 **Что я умею:**
✅ Проверять Roblox аккаунты
✅ Вести статистику пользователей  
✅ Работать в группах и каналах
✅ Управлять доступом к чатам

🚀 **Начните с верификации чтобы получить доступ к полному функционалу!**
    """
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /verify"""
    user = update.effective_user
    
    if db.is_banned(user.id):
        await update.message.reply_text("🚫 Вы заблокированы в системе.")
        return
    
    if db.is_verified(user.id):
        await update.message.reply_text("✅ Вы уже прошли верификацию!")
        return
    
    await update.message.reply_text(
        "👤 **Отправьте ваш никнейм Roblox**\n\n"
        "Можно отправить:\n"
        "• Никнейм (например: `AlexRoblox`)\n"
        "• Ссылку на профиль\n"
        "• ID пользователя",
        parse_mode='Markdown'
    )

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /profile"""
    user = update.effective_user
    stats = db.get_user_stats(user.id)
    
    if not stats:
        await update.message.reply_text("❌ Вы еще не зарегистрированы в системе. Используйте /start")
        return
    
    roblox_username, verified, verified_at = stats
    
    if verified:
        profile_text = f"""
📊 **Ваш профиль**

👤 Telegram: @{user.username or 'N/A'}
🆔 ID: `{user.id}`
🎮 Roblox: `{roblox_username}`
✅ Статус: Верифицирован
📅 Дата верификации: {verified_at.split()[0] if verified_at else 'N/A'}
        """
    else:
        profile_text = f"""
📊 **Ваш профиль**

👤 Telegram: @{user.username or 'N/A'}  
🆔 ID: `{user.id}`
❌ Статус: Не верифицирован

💡 Используйте /verify чтобы пройти верификацию
        """
    
    await update.message.reply_text(profile_text, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats"""
    user = update.effective_user
    
    if not db.is_admin(user.id):
        await update.message.reply_text("❌ У вас нет прав для просмотра статистики.")
        return
    
    stats = db.get_bot_stats()
    
    stats_text = f"""
📊 **Статистика бота**

👥 Пользователи:
├ Всего: {stats['total_users']}
├ Верифицировано: {stats['verified_users']} 
├ Ожидают: {stats['total_users'] - stats['verified_users']}
└ Заблокировано: {stats['banned_users']}

⚡ Система:
├ Бот: 🟢 Онлайн
├ База данных: 🟢 Работает
└ Время: {datetime.now().strftime('%H:%M:%S')}
    """
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')

# ===== ОБРАБОТЧИКИ СООБЩЕНИЙ =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    user = update.effective_user
    text = update.message.text
    
    # Игнорируем команды
    if text.startswith('/'):
        return
    
    # Проверяем бан
    if db.is_banned(user.id):
        await update.message.reply_text("🚫 Вы заблокированы в системе.")
        return
    
    # Если пользователь не верифицирован, обрабатываем как попытку верификации
    if not db.is_verified(user.id):
        await process_verification(update, text)
        return
    
    # Если пользователь уже верифицирован
    if db.is_verified(user.id):
        user_stats = db.get_user_stats(user.id)
        if user_stats:
            roblox_username = user_stats[0]
            await update.message.reply_text(
                f"✅ Вы уже верифицированы как `{roblox_username}`\n\n"
                f"Для повторной верификации обратитесь к администратору.",
                parse_mode='Markdown'
            )

async def process_verification(update: Update, text: str):
    """Обработка верификации"""
    user = update.effective_user
    
    # Извлекаем username из текста
    username = extract_username(text)
    
    if not username:
        await update.message.reply_text(
            "❌ Неверный формат. Отправьте:\n"
            "• Никнейм (например: `AlexRoblox`)\n" 
            "• Ссылку на профиль Roblox",
            parse_mode='Markdown'
        )
        return
    
    # Проверяем пользователя через Roblox API
    await update.message.reply_text("🔍 Проверяем аккаунт Roblox...")
    
    user_info = roblox_api.get_user_info(username)
    
    if not user_info['success']:
        await update.message.reply_text(
            f"❌ Ошибка: {user_info['error']}\n\n"
            f"Проверьте правильность никнейма и попробуйте снова."
        )
        return
    
    # Сохраняем верификацию
    db.set_verified(user.id, user_info['username'], user_info['id'])
    
    # Отправляем успешное сообщение
    success_text = f"""
✅ **Верификация успешно пройдена!**

🎮 **Ваши данные:**
├ Roblox: `{user_info['username']}`
├ Display Name: `{user_info['displayName']}`
├ ID: `{user_info['id']}`
└ Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}

🎉 Теперь у вас есть доступ ко всем функциям!

💫 **Что дальше:**
• Вы можете участвовать в чатах
• Получать доступ к закрытым каналам  
• Участвовать в мероприятиях
    """
    
    keyboard = [
        [InlineKeyboardButton("📊 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton("🎮 Проверить другого", callback_data="verify")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    logger.info(f"User {user.id} verified as {user_info['username']}")

def extract_username(text):
    """Извлекает username из текста"""
    import re
    
    text = text.strip()
    
    # Если это ссылка
    if 'roblox.com/users/' in text:
        match = re.search(r'roblox\.com/users/(\d+)/?', text)
        if match:
            return get_username_by_id(match.group(1))
    
    # Если это упоминание
    text = text.replace('@', '')
    
    # Базовая проверка username
    if 3 <= len(text) <= 20 and re.match(r'^[a-zA-Z0-9_]+$', text):
        return text
    
    return None

def get_username_by_id(user_id):
    """Получает username по ID"""
    try:
        url = f"https://users.roblox.com/v1/users/{user_id}"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get('name')
    except:
        pass
    return None

# ===== ОБРАБОТЧИКИ КНОПОК =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    data = query.data
    
    if data == "verify":
        if db.is_verified(user.id):
            await query.edit_message_text("✅ Вы уже верифицированы!")
        else:
            await query.edit_message_text(
                "👤 **Отправьте ваш никнейм Roblox**\n\n"
                "Можно отправить:\n"
                "• Никнейм (например: `AlexRoblox`)\n"
                "• Ссылку на профиль\n"
                "• ID пользователя",
                parse_mode='Markdown'
            )
    
    elif data == "profile":
        await show_profile(query, user)
    
    elif data == "admin_panel":
        if db.is_admin(user.id):
            await show_admin_panel(query)
        else:
            await query.edit_message_text("❌ У вас нет прав администратора.")
    
    elif data == "admin_stats":
        await show_admin_stats(query)
    
    elif data == "admin_back":
        await show_admin_panel(query)

async def show_profile(query, user):
    """Показывает профиль пользователя"""
    stats = db.get_user_stats(user.id)
    
    if not stats:
        profile_text = "❌ Вы еще не зарегистрированы в системе."
    else:
        roblox_username, verified, verified_at = stats
        
        if verified:
            profile_text = f"""
📊 **Ваш профиль**

👤 Telegram: @{user.username or 'N/A'}
🆔 ID: `{user.id}`
🎮 Roblox: `{roblox_username}`
✅ Статус: Верифицирован
📅 Дата: {verified_at.split()[0] if verified_at else 'N/A'}
            """
        else:
            profile_text = f"""
📊 **Ваш профиль**

👤 Telegram: @{user.username or 'N/A'}
🆔 ID: `{user.id}`  
❌ Статус: Не верифицирован

💡 Нажмите кнопку ниже для верификации
            """
    
    keyboard = []
    if not verified:
        keyboard.append([InlineKeyboardButton("🔐 Пройти верификацию", callback_data="verify")])
    keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data="profile")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(profile_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_admin_panel(query):
    """Показывает панель администратора"""
    stats = db.get_bot_stats()
    
    admin_text = f"""
⚙️ **Панель администратора**

📊 Статистика:
├ 👥 Пользователей: {stats['total_users']}
├ ✅ Верифицировано: {stats['verified_users']}
└ 🚫 Заблокировано: {stats['banned_users']}

🛠️ Действия:
    """
    
    keyboard = [
        [InlineKeyboardButton("📊 Подробная статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin_panel")],
        [InlineKeyboardButton("↩️ Назад", callback_data="profile")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_admin_stats(query):
    """Показывает детальную статистику"""
    stats = db.get_bot_stats()
    
    stats_text = f"""
📈 **Детальная статистика**

👥 **Пользователи:**
├ Всего: {stats['total_users']}
├ Верифицировано: {stats['verified_users']}
├ Ожидают: {stats['total_users'] - stats['verified_users'] - stats['banned_users']}
└ Заблокировано: {stats['banned_users']}

📊 **Процент верификации:**
├ Успешно: {(stats['verified_users']/stats['total_users']*100) if stats['total_users'] > 0 else 0:.1f}%
└ Ожидают: {((stats['total_users'] - stats['verified_users'] - stats['banned_users'])/stats['total_users']*100) if stats['total_users'] > 0 else 0:.1f}%

⚡ **Система:**
├ Бот: 🟢 Онлайн
├ База данных: 🟢 Работает
└ Время: {datetime.now().strftime('%H:%M:%S')}
    """
    
    keyboard = [
        [InlineKeyboardButton("↩️ Назад", callback_data="admin_panel")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')

# ===== ЗАПУСК БОТА =====
def main():
    """Основная функция"""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не найден! Проверьте переменные окружения.")
        return
    
    try:
        # Регистрация обработчиков
        app.add_handler(CommandHandler("start", start_command))
        app.add_handler(CommandHandler("verify", verify_command))
        app.add_handler(CommandHandler("profile", profile_command))
        app.add_handler(CommandHandler("stats", stats_command))
        
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_handler(CallbackQueryHandler(button_handler))
        
        # Запуск бота
        logger.info("🤖 Бот запускается...")
        logger.info(f"👑 Администраторы: {ADMIN_IDS}")
        app.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")

if __name__ == '__main__':
    main()
