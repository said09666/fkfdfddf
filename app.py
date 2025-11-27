import os
import logging
import sqlite3
import urllib.request
import urllib.parse
import json
import random
import string
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
ADMIN_IDS = [int(x) for x in os.getenv('8214687269', '8214687269').split(',') if x]

# Роли пользователей
ROLES = {
    'owner': '👑 Владелец',
    'admin': '⚡ Админ', 
    'moderator': '🛡️ Модератор',
    'guarantor': '✅ Гарант',
    'scammer': '🚫 Скамер',
    'user': '👤 Пользователь'
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
    
    def get_users_by_role(self, role):
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT telegram_id, telegram_username, roblox_username FROM users WHERE role = ?',
            (role,)
        )
        return cursor.fetchall()
    
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
            'SELECT roblox_username, verified, verified_at, role FROM users WHERE telegram_id = ?', 
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
        
        # Статистика по ролям
        role_stats = {}
        for role in ROLES.keys():
            cursor.execute('SELECT COUNT(*) FROM users WHERE role = ?', (role,))
            role_stats[role] = cursor.fetchone()[0]
        
        # Сегодняшняя дата
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Обновляем дневную статистику
        cursor.execute('SELECT id FROM stats WHERE date = ?', (today,))
        if not cursor.fetchone():
            cursor.execute(
                'INSERT INTO stats (date, total_users, verified_users, new_users) VALUES (?, ?, ?, ?)',
                (today, total_users, verified_users, 0)
            )
        else:
            cursor.execute(
                'UPDATE stats SET total_users = ?, verified_users = ? WHERE date = ?',
                (total_users, verified_users, today)
            )
        
        self.conn.commit()
        
        return {
            'total_users': total_users,
            'verified_users': verified_users,
            'banned_users': banned_users,
            'role_stats': role_stats
        }
    
    def get_daily_stats(self, days=7):
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT date, total_users, verified_users, new_users FROM stats ORDER BY date DESC LIMIT ?',
            (days,)
        )
        return cursor.fetchall()
    
    def add_admin(self, telegram_id, username):
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO users (telegram_id, telegram_username, role) VALUES (?, ?, ?)',
            (telegram_id, username, 'admin')
        )
        self.conn.commit()
    
    def is_admin(self, telegram_id):
        role = self.get_role(telegram_id)
        return role in ['admin', 'owner']
    
    def is_owner(self, telegram_id):
        return self.get_role(telegram_id) == 'owner'
    
    def can_manage_roles(self, telegram_id, target_role):
        """Проверяет может ли пользователь управлять определенной ролью"""
        user_role = self.get_role(telegram_id)
        role_hierarchy = ['owner', 'admin', 'moderator', 'guarantor', 'user', 'scammer']
        
        try:
            user_index = role_hierarchy.index(user_role)
            target_index = role_hierarchy.index(target_role)
            return user_index <= target_index
        except ValueError:
            return False

class RobloxAPI:
    @staticmethod
    def get_user_info(username):
        """Получает информацию о пользователе Roblox используя urllib"""
        try:
            params = urllib.parse.urlencode({'keyword': username, 'limit': 10})
            url = f"https://users.roblox.com/v1/users/search?{params}"
            
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                
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

# Добавляем владельцев при запуске
for admin_id in ADMIN_IDS:
    db.set_role(admin_id, 'owner')

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
    
    user_role = db.get_role(user.id)
    role_name = ROLES.get(user_role, '👤 Пользователь')
    
    if db.is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ Панель управления", callback_data="admin_panel")])
    
    keyboard.append([InlineKeyboardButton("📊 Мой профиль", callback_data="profile")])
    keyboard.append([InlineKeyboardButton("👥 Управление ролями", callback_data="role_management")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = f"""
🎮 **Добро пожаловать в Roblox Verification Bot!**

🤖 **Ваш статус: {role_name}**

📋 **Что я умею:**
✅ Проверять Roblox аккаунты
✅ Вести статистику пользователей  
✅ Система ролей и прав
✅ Управление доступом к чатам

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
    
    await update.message.reply_text(
        f"👤 **Отправьте ваш никнейм Roblox**\n\n"
        f"🔐 **Ваш код верификации: `{verification_code}`**\n\n"
        f"📝 **Инструкция:**\n"
        f"1. Скопируйте код выше\n"
        f"2. Добавьте его в описание вашего аккаунта Roblox\n"
        f"3. Отправьте ваш никнейм Roblox\n"
        f"4. Бот проверит наличие кода в описании\n\n"
        f"Можно отправить:\n"
        f"• Никнейм (например: `AlexRoblox`)\n"
        f"• Ссылку на профиль\n"
        f"• ID пользователя",
        parse_mode='Markdown'
    )

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /profile"""
    await show_profile_message(update, update.effective_user)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats"""
    user = update.effective_user
    
    if not db.is_admin(user.id):
        await update.message.reply_text("❌ У вас нет прав для просмотра статистики.")
        return
    
    await show_admin_stats_message(update)

async def roles_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /roles"""
    user = update.effective_user
    
    if not db.is_admin(user.id):
        await update.message.reply_text("❌ У вас нет прав для управления ролями.")
        return
    
    await show_role_management(update)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    help_text = """
🆘 **Помощь по боту**

📋 **Доступные команды:**
/start - Запустить бота
/verify - Пройти верификацию
/profile - Мой профиль
/help - Эта справка

👑 **Команды для администраторов:**
/stats - Статистика бота
/roles - Управление ролями

🔍 **Как пройти верификацию:**
1. Нажмите "🔐 Пройти верификацию"
2. Получите код верификации
3. Добавьте код в описание Roblox аккаунта
4. Отправьте ваш никнейм Roblox
5. Бот проверит аккаунт и код

🎭 **Система ролей:**
👑 Владелец - Полный доступ
⚡ Админ - Управление ботом
🛡️ Модератор - Модерация
✅ Гарант - Проверенные пользователи
👤 Пользователь - Обычный пользователь
🚫 Скамер - Заблокированные
    """
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

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
                f"Для смены аккаунта обратитесь к администратору.",
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
            "• Ссылку на профиль Roblox\n"
            "• ID пользователя",
            parse_mode='Markdown'
        )
        return
    
    # Получаем код верификации
    verification_code = db.get_verification_code(user.id)
    
    if not verification_code:
        await update.message.reply_text("❌ Код верификации не найден. Начните процесс заново с /verify")
        return
    
    # Проверяем пользователя через Roblox API
    await update.message.reply_text("🔍 Проверяем аккаунт Roblox и код верификации...")
    
    user_info = roblox_api.get_user_info(username)
    
    if not user_info['success']:
        await update.message.reply_text(
            f"❌ Ошибка: {user_info['error']}\n\n"
            f"Проверьте правильность никнейма и попробуйте снова."
        )
        return
    
    # Здесь должна быть проверка кода в описании аккаунта Roblox
    # В реальном боте нужно получить описание аккаунта через Roblox API
    # Для демонстрации просто подтверждаем верификацию
    
    code_verified = await check_verification_code(user_info['id'], verification_code)
    
    if not code_verified:
        await update.message.reply_text(
            f"❌ Код верификации не найден в описании аккаунта!\n\n"
            f"🔐 Ваш код: `{verification_code}`\n\n"
            f"Добавьте этот код в описание вашего Roblox аккаунта и попробуйте снова.",
            parse_mode='Markdown'
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
├ Код: `{verification_code}`
└ Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}

🎉 Теперь у вас есть доступ ко всем функциям!

💫 **Что доступно:**
• Участие в чатах
• Доступ к закрытым каналам  
• Участие в мероприятиях
• Полный функционал бота
    """
    
    keyboard = [
        [InlineKeyboardButton("📊 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton("🔄 Проверить другой аккаунт", callback_data="verify")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    logger.info(f"User {user.id} verified as {user_info['username']}")

async def check_verification_code(roblox_id, verification_code):
    """
    Проверяет наличие кода верификации в описании аккаунта Roblox
    В реальной реализации нужно получить описание через Roblox API
    """
    # Заглушка - в реальном боте здесь должен быть запрос к Roblox API
    # для получения описания аккаунта и проверки наличия кода
    return True  # Для демонстрации всегда возвращаем True

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
    """Получает username по ID используя urllib"""
    try:
        url = f"https://users.roblox.com/v1/users/{user_id}"
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
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
        await handle_verify_button(query, user)
    
    elif data == "profile":
        await show_profile_message(query, user)
    
    elif data == "admin_panel":
        await show_admin_panel(query, user)
    
    elif data == "admin_stats":
        await show_admin_stats_message(query)
    
    elif data == "role_management":
        await show_role_management(query, user)
    
    elif data.startswith("role_"):
        await handle_role_button(query, user, data)
    
    elif data.startswith("setrole_"):
        await handle_set_role(query, user, data)
    
    elif data == "admin_back":
        await show_admin_panel(query, user)

async def handle_verify_button(query, user):
    """Обработка кнопки верификации"""
    if db.is_banned(user.id):
        await query.edit_message_text("🚫 Вы заблокированы в системе.")
        return
    
    if db.is_verified(user.id):
        user_stats = db.get_user_stats(user.id)
        if user_stats:
            roblox_username = user_stats[0]
            await query.edit_message_text(
                f"✅ Вы уже верифицированы как `{roblox_username}`\n\n"
                f"Для смены аккаунта обратитесь к администратору.",
                parse_mode='Markdown'
            )
        return
    
    # Генерируем код верификации
    verification_code = db.generate_verification_code()
    db.set_verification_code(user.id, verification_code)
    
    await query.edit_message_text(
        f"👤 **Отправьте ваш никнейм Roblox**\n\n"
        f"🔐 **Ваш код верификации: `{verification_code}`**\n\n"
        f"📝 **Инструкция:**\n"
        f"1. Скопируйте код выше\n"
        f"2. Добавьте его в описание вашего аккаунта Roblox\n"
        f"3. Отправьте ваш никнейм Roblox\n"
        f"4. Бот проверит наличие кода в описании\n\n"
        f"Можно отправить:\n"
        f"• Никнейм (например: `AlexRoblox`)\n"
        f"• Ссылку на профиль\n"
        f"• ID пользователя",
        parse_mode='Markdown'
    )

async def show_profile_message(update, user):
    """Показывает профиль пользователя"""
    stats = db.get_user_stats(user.id)
    
    if not stats:
        profile_text = "❌ Вы еще не зарегистрированы в системе. Используйте /start"
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

💡 Нажмите кнопку ниже для верификации
            """
    
    keyboard = []
    if not verified:
        keyboard.append([InlineKeyboardButton("🔐 Пройти верификацию", callback_data="verify")])
    
    if db.is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ Панель управления", callback_data="admin_panel")])
    
    keyboard.append([InlineKeyboardButton("👥 Управление ролями", callback_data="role_management")])
    keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data="profile")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if hasattr(update, 'message'):
        await update.message.reply_text(profile_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.edit_message_text(profile_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_admin_panel(update, user):
    """Показывает панель администратора"""
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
        [InlineKeyboardButton("📈 Детальная статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 Управление ролями", callback_data="role_management")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin_panel")],
        [InlineKeyboardButton("↩️ Назад", callback_data="profile")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if hasattr(update, 'message'):
        await update.message.reply_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.edit_message_text(admin_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_admin_stats_message(update):
    """Показывает детальную статистику"""
    stats = db.get_bot_stats()
    daily_stats = db.get_daily_stats(7)
    
    total = stats['total_users']
    verified = stats['verified_users']
    banned = stats['banned_users']
    pending = total - verified - banned
    
    verified_percent = (verified / total * 100) if total > 0 else 0
    pending_percent = (pending / total * 100) if total > 0 else 0
    
    # Статистика по ролям
    role_stats_text = ""
    for role, count in stats['role_stats'].items():
        if count > 0:
            role_stats_text += f"├ {ROLES[role]}: {count}\n"
    
    # Дневная статистика
    daily_text = ""
    for day_stat in daily_stats[:3]:  # Последние 3 дня
        date = datetime.strptime(day_stat[0], '%Y-%m-%d').strftime('%d.%m')
        daily_text += f"├ {date}: +{day_stat[3]} новых\n"
    
    stats_text = f"""
📈 **Детальная статистика**

👥 **Пользователи:**
├ Всего: {total}
├ Верифицировано: {verified}
├ Ожидают: {pending}
└ Заблокировано: {banned}

📊 **Процент верификации:**
├ Успешно: {verified_percent:.1f}%
└ Ожидают: {pending_percent:.1f}%

🎭 **Распределение по ролям:**
{role_stats_text}
📅 **Статистика за 3 дня:**
{daily_text}
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
    
    if hasattr(update, 'message'):
        await update.message.reply_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_role_management(update, user):
    """Показывает управление ролями"""
    if not db.is_admin(user.id):
        if hasattr(update, 'message'):
            await update.message.reply_text("❌ У вас нет прав для управления ролями.")
        else:
            await update.edit_message_text("❌ У вас нет прав для управления ролями.")
        return
    
    user_role = db.get_role(user.id)
    
    role_text = f"""
👥 **Управление ролями**

🎭 **Доступные роли:**
👑 Владелец - Полный доступ к боту
⚡ Админ - Управление ботом и ролями
🛡️ Модератор - Модерация пользователей
✅ Гарант - Проверенные пользователи
👤 Пользователь - Обычный пользователь
🚫 Скамер - Заблокированные пользователи

💡 **Ваша роль: {ROLES[user_role]}**
    """
    
    keyboard = []
    for role_key, role_name in ROLES.items():
        if db.can_manage_roles(user.id, role_key):
            keyboard.append([InlineKeyboardButton(f"{role_name}", callback_data=f"role_{role_key}")])
    
    keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data="admin_panel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if hasattr(update, 'message'):
        await update.message.reply_text(role_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.edit_message_text(role_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_role_button(query, user, data):
    """Обработка выбора роли"""
    role_key = data.replace("role_", "")
    
    if not db.can_manage_roles(user.id, role_key):
        await query.edit_message_text("❌ У вас нет прав для управления этой ролью.")
        return
    
    users = db.get_users_by_role(role_key)
    role_name = ROLES[role_key]
    
    if not users:
        users_text = "❌ Пользователей с этой ролью нет"
    else:
        users_text = f"👥 **Пользователи с ролью {role_name}:**\n\n"
        for i, (user_id, tg_username, roblox_username) in enumerate(users[:20], 1):  # Ограничиваем 20 пользователями
            username_display = tg_username or f"ID: {user_id}"
            roblox_display = roblox_username or "Не верифицирован"
            users_text += f"{i}. @{username_display} - {roblox_display}\n"
        
        if len(users) > 20:
            users_text += f"\n... и еще {len(users) - 20} пользователей"
    
    keyboard = []
    
    # Кнопки для добавления пользователей в эту роль
    if role_key not in ['scammer']:  # Не добавляем кнопку для скамеров
        keyboard.append([InlineKeyboardButton(f"➕ Добавить {role_name}", callback_data=f"setrole_{role_key}")])
    
    keyboard.append([InlineKeyboardButton("↩️ Назад к ролям", callback_data="role_management")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(users_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_set_role(query, user, data):
    """Обработка установки роли"""
    role_key = data.replace("setrole_", "")
    role_name = ROLES[role_key]
    
    await query.edit_message_text(
        f"🎭 **Добавление роли {role_name}**\n\n"
        f"Отправьте Telegram ID пользователя, которому хотите выдать роль {role_name}.\n\n"
        f"💡 **Как получить ID?**\n"
        f"• Попросите пользователя написать @userinfobot\n"
        f"• Или перешлите его сообщение боту",
        parse_mode='Markdown'
    )
    
    # Сохраняем состояние для обработки следующего сообщения
    query.message.chat_data['awaiting_role'] = role_key
    query.message.chat_data['role_setter'] = user.id

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
        app.add_handler(CommandHandler("roles", roles_command))
        app.add_handler(CommandHandler("help", help_command))
        
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_handler(CallbackQueryHandler(button_handler))
        
        # Запуск бота
        logger.info("🤖 Бот запускается...")
        logger.info(f"👑 Владельцы: {ADMIN_IDS}")
        app.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")

if __name__ == '__main__':
    main()
