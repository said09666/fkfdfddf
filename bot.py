import logging
import random
import string
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from database import Database
from config import BOT_TOKEN, ADMIN_IDS, BAN_DURATIONS, MUTE_DURATIONS

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

db = Database()

class RobloxAPI:
    @staticmethod
    def get_user_id(username):
        """Получить ID пользователя Roblox по имени"""
        try:
            response = requests.get(
                f"https://api.roblox.com/users/get-by-username?username={username}",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                return data.get('Id')
        except Exception as e:
            logging.error(f"Error getting Roblox user ID: {e}")
        return None
    
    @staticmethod
    def get_user_description(user_id):
        """Получить описание профиля пользователя Roblox"""
        try:
            response = requests.get(
                f"https://users.roblox.com/v1/users/{user_id}",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                return data.get('description', '')
        except Exception as e:
            logging.error(f"Error getting Roblox user description: {e}")
        return ''

def generate_verification_code():
    """Генерация 9-значного кода верификации"""
    return ''.join(random.choices(string.digits, k=9))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    user = db.get_user_by_telegram_id(user_id)
    
    if user and user[5]:  # is_verified
        await show_profile(update, context)
        return
    
    keyboard = [
        [InlineKeyboardButton("🔐 Начать авторизацию", callback_data="start_auth")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👋 Добро пожаловать! Для доступа к чатам необходимо пройти авторизацию через Roblox.\n\n"
        "Нажмите кнопку ниже чтобы начать процесс авторизации.",
        reply_markup=reply_markup
    )

async def start_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса авторизации"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🔐 **Процесс авторизации**\n\n"
        "**Шаг 1 из 3:**\n"
        "Пожалуйста, введите ваш никнейм в Roblox:"
    )
    
    context.user_data['auth_step'] = 'waiting_username'

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    message_text = update.message.text
    
    # Проверка на авторизацию для новых сообщений в группах
    if update.effective_chat.type in ['group', 'supergroup']:
        user = db.get_user_by_telegram_id(user_id)
        if not user or not user[5]:
            await update.message.delete()
            warning_msg = await update.message.reply_text(
                f"👤 {update.effective_user.first_name}, вы не авторизованы! "
                f"Используйте /start в ЛС с ботом для авторизации."
            )
            # Удалить предупреждение через 10 секунд
            context.job_queue.run_once(
                lambda ctx: ctx.bot.delete_message(update.effective_chat.id, warning_msg.message_id),
                10
            )
            return
        
        # Проверка бана
        if db.is_banned(user[3]):  # roblox_id
            await update.message.delete()
            return
        
        # Проверка мута
        if db.is_muted(user[3]):
            await update.message.delete()
            return
    
    # Обработка процесса авторизации
    if 'auth_step' in context.user_data:
        if context.user_data['auth_step'] == 'waiting_username':
            await process_username(update, context, message_text)
        
        elif context.user_data['auth_step'] == 'waiting_verification':
            await process_verification(update, context, message_text)

async def process_username(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
    """Обработка введенного имени пользователя Roblox"""
    user_id = update.effective_user.id
    
    # Проверяем существование пользователя Roblox
    roblox_id = RobloxAPI.get_user_id(username)
    if not roblox_id:
        await update.message.reply_text(
            "❌ Пользователь с таким именем не найден в Roblox. "
            "Пожалуйста, проверьте правильность написания и попробуйте еще раз:"
        )
        return
    
    # Генерируем код верификации
    verification_code = generate_verification_code()
    
    # Сохраняем пользователя в БД
    db.add_user(user_id, username, roblox_id, verification_code)
    
    context.user_data['auth_step'] = 'waiting_verification'
    context.user_data['roblox_id'] = roblox_id
    
    keyboard = [
        [InlineKeyboardButton("✅ Я добавил код", callback_data="check_verification")],
        [InlineKeyboardButton("🔄 Сгенерировать новый код", callback_data="new_code")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ **Пользователь найден!**\n\n"
        f"**Шаг 2 из 3:**\n"
        f"Добавьте следующий код в описание вашего профиля Roblox:\n\n"
        f"`{verification_code}`\n\n"
        f"**Инструкция:**\n"
        f"1. Откройте Roblox\n"
        f"2. Перейдите в настройки профиля\n"
        f"3. Добавьте код в поле 'Описание'\n"
        f"4. Нажмите кнопку '✅ Я добавил код'",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def check_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка верификации"""
    query = update.callback_query
    await query.answer()
    
    user_data = db.get_user_by_telegram_id(query.from_user.id)
    if not user_data:
        await query.edit_message_text("❌ Ошибка: данные пользователя не найдены.")
        return
    
    roblox_id = user_data[3]  # roblox_id
    verification_code = user_data[6]  # verification_code
    
    # Получаем описание профиля
    description = RobloxAPI.get_user_description(roblox_id)
    
    if verification_code and verification_code in description:
        # Верификация успешна
        db.verify_user(roblox_id)
        
        await query.edit_message_text(
            f"🎉 **Авторизация успешна!**\n\n"
            f"Теперь вы можете писать в чатах, где есть этот бот.\n\n"
            f"📊 **Ваш профиль:**\n"
            f"• Roblox ник: {user_data[2]}\n"
            f"• ID: {roblox_id}\n"
            f"• Дата регистрации: {user_data[7][:10] if user_data[7] else 'Неизвестно'}"
        )
        
        # Оповещаем все группы
        groups = db.get_all_groups()
        for group in groups:
            try:
                await context.bot.send_message(
                    group[0],
                    f"👋 Новый пользователь авторизовался:\n"
                    f"• Имя в Telegram: {query.from_user.first_name}\n"
                    f"• Roblox ник: {user_data[2]}\n"
                    f"• Roblox ID: {roblox_id}"
                )
            except Exception as e:
                logging.error(f"Error sending notification to group {group[0]}: {e}")
    
    else:
        await query.answer("❌ Код не найден в описании профиля. Пожалуйста, добавьте код и попробуйте снова.", show_alert=True)

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать профиль пользователя"""
    user_id = update.effective_user.id
    user = db.get_user_by_telegram_id(user_id)
    
    if not user:
        await update.message.reply_text("❌ Профиль не найден.")
        return
    
    is_banned = db.is_banned(user[3])
    is_muted = db.is_muted(user[3])
    
    status = "✅ Активен"
    if is_banned:
        status = "🚫 Забанен"
    elif is_muted:
        status = "🔇 В муте"
    
    profile_text = (
        f"📊 **Ваш профиль**\n\n"
        f"• Roblox ник: `{user[2]}`\n"
        f"• Roblox ID: `{user[3]}`\n"
        f"• Дата регистрации: `{user[7][:10] if user[7] else 'Неизвестно'}`\n"
        f"• Статус: {status}\n"
        f"• Верификация: {'✅ Подтверждена' if user[5] else '❌ Не подтверждена'}"
    )
    
    await update.message.reply_text(profile_text, parse_mode='Markdown')

# Админ команды
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Панель администратора"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return
    
    keyboard = [
        [InlineKeyboardButton("🚫 Забанить пользователя", callback_data="admin_ban")],
        [InlineKeyboardButton("🔇 Замутить пользователя", callback_data="admin_mute")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 Управление группами", callback_data="admin_groups")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👨‍💻 **Панель администратора**\n\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Бан пользователя"""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет доступа.")
        return
    
    await query.edit_message_text(
        "🚫 **Бан пользователя**\n\n"
        "Введите Roblox ID пользователя и причину бана через пробел:\n"
        "Пример: `123456789 Читинг`",
        parse_mode='Markdown'
    )
    
    context.user_data['admin_action'] = 'ban'

async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий администратора"""
    if 'admin_action' not in context.user_data:
        return
    
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    text = update.message.text
    parts = text.split(' ', 1)
    
    if len(parts) < 2:
        await update.message.reply_text("❌ Неверный формат. Используйте: ID причина")
        return
    
    roblox_id, reason = parts[0], parts[1]
    
    if context.user_data['admin_action'] == 'ban':
        # Создаем клавиатуру для выбора длительности бана
        keyboard = [
            [InlineKeyboardButton("1 час", callback_data=f"ban_duration_1h_{roblox_id}_{reason}")],
            [InlineKeyboardButton("1 день", callback_data=f"ban_duration_1d_{roblox_id}_{reason}")],
            [InlineKeyboardButton("7 дней", callback_data=f"ban_duration_7d_{roblox_id}_{reason}")],
            [InlineKeyboardButton("Навсегда", callback_data=f"ban_duration_permanent_{roblox_id}_{reason}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🚫 **Бан пользователя**\n\n"
            f"Roblox ID: {roblox_id}\n"
            f"Причина: {reason}\n\n"
            f"Выберите длительность бана:",
            reply_markup=reply_markup
        )
    
    elif context.user_data['admin_action'] == 'mute':
        # Аналогично для мута
        pass
    
    context.user_data.pop('admin_action', None)

async def execute_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выполнение бана"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    duration_type = data[2]
    roblox_id = data[3]
    reason = '_'.join(data[4:])
    
    duration = BAN_DURATIONS.get(duration_type)
    is_permanent = duration_type == 'permanent'
    
    db.add_ban(roblox_id, reason, duration, query.from_user.id, is_permanent)
    
    duration_text = "навсегда" if is_permanent else f"на {duration_type}"
    await query.edit_message_text(
        f"✅ **Пользователь забанен**\n\n"
        f"• Roblox ID: {roblox_id}\n"
        f"• Причина: {reason}\n"
        f"• Длительность: {duration_text}\n"
        f"• Забанил: {query.from_user.first_name}"
    )

# Обработчики для групп
async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик сообщений в группах"""
    # Эта функция уже реализована в handle_message
    pass

async def add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление группы в БД"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        return
    
    group_id = update.effective_chat.id
    group_title = update.effective_chat.title
    
    db.add_group(group_id, group_title, update.effective_user.id)
    
    await update.message.reply_text("✅ Группа добавлена в систему модерации!")

def main():
    """Основная функция"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("profile", show_profile))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("add_group", add_group))
    
    # Обработчики callback-запросов
    application.add_handler(CallbackQueryHandler(start_auth, pattern="^start_auth$"))
    application.add_handler(CallbackQueryHandler(check_verification, pattern="^check_verification$"))
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(ban_user, pattern="^admin_ban$"))
    application.add_handler(CallbackQueryHandler(execute_ban, pattern="^ban_duration_"))
    
    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_action))
    
    # Запуск бота
    print("Бот запущен!")
    application.run_polling()

if __name__ == '__main__':
    main()
