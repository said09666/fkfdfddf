import logging
import random
import string
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from database import Database
from config import BOT_TOKEN, ADMIN_IDS, BAN_DURATIONS, MUTE_DURATIONS

# Настройка логирования для bothost
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)
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
            else:
                logger.warning(f"Roblox API returned status {response.status_code} for username {username}")
        except Exception as e:
            logger.error(f"Error getting Roblox user ID: {e}")
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
            else:
                logger.warning(f"Roblox API returned status {response.status_code} for user_id {user_id}")
        except Exception as e:
            logger.error(f"Error getting Roblox user description: {e}")
        return ''

def generate_verification_code():
    """Генерация 9-значного кода верификации"""
    return ''.join(random.choices(string.digits, k=9))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    try:
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
    except Exception as e:
        logger.error(f"Error in start command: {e}")

async def start_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса авторизации"""
    try:
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "🔐 **Процесс авторизации**\n\n"
            "**Шаг 1 из 3:**\n"
            "Пожалуйста, введите ваш никнейм в Roblox:"
        )
        
        context.user_data['auth_step'] = 'waiting_username'
    except Exception as e:
        logger.error(f"Error in start_auth: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    try:
        user_id = update.effective_user.id
        
        # Проверка на авторизацию для новых сообщений в группах
        if update.effective_chat.type in ['group', 'supergroup']:
            user = db.get_user_by_telegram_id(user_id)
            if not user or not user[5]:
                try:
                    await update.message.delete()
                except:
                    pass  # Если не удалось удалить сообщение
                
                warning_msg = await update.message.reply_text(
                    f"👤 {update.effective_user.first_name}, вы не авторизованы! "
                    f"Используйте /start в ЛС с ботом для авторизации."
                )
                # Удалить предупреждение через 10 секунд
                asyncio.create_task(delete_message_after_delay(context, update.effective_chat.id, warning_msg.message_id, 10))
                return
            
            # Проверка бана
            if db.is_banned(user[3]):  # roblox_id
                try:
                    await update.message.delete()
                except:
                    pass
                return
            
            # Проверка мута
            if db.is_muted(user[3]):
                try:
                    await update.message.delete()
                except:
                    pass
                return
        
        # Обработка процесса авторизации
        if 'auth_step' in context.user_data:
            if context.user_data['auth_step'] == 'waiting_username':
                await process_username(update, context, update.message.text)
            
            elif context.user_data['auth_step'] == 'waiting_verification':
                await process_verification(update, context, update.message.text)
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")

async def delete_message_after_delay(context, chat_id, message_id, delay):
    """Удалить сообщение через указанное время"""
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id, message_id)
    except:
        pass

async def process_username(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
    """Обработка введенного имени пользователя Roblox"""
    try:
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
        success = db.add_user(user_id, username, roblox_id, verification_code)
        if not success:
            await update.message.reply_text("❌ Ошибка при сохранении данных. Попробуйте еще раз.")
            return
        
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
    except Exception as e:
        logger.error(f"Error in process_username: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте еще раз.")

async def process_verification(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str):
    """Обработка проверки верификации"""
    # Этот метод может быть использован для ручного ввода кода
    await update.message.reply_text("Пожалуйста, используйте кнопку '✅ Я добавил код' для проверки.")

async def check_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка верификации"""
    try:
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
                    logger.error(f"Error sending notification to group {group[0]}: {e}")
        
        else:
            await query.answer("❌ Код не найден в описании профиля. Пожалуйста, добавьте код и попробуйте снова.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in check_verification: {e}")
        await query.edit_message_text("❌ Произошла ошибка при проверке. Попробуйте еще раз.")

async def new_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерация нового кода верификации"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_data = db.get_user_by_telegram_id(query.from_user.id)
        if not user_data:
            await query.edit_message_text("❌ Ошибка: данные пользователя не найдены.")
            return
        
        new_verification_code = generate_verification_code()
        
        # Обновляем код в базе данных
        conn = db._Database__get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET verification_code = ? WHERE telegram_id = ?',
            (new_verification_code, query.from_user.id)
        )
        conn.commit()
        conn.close()
        
        keyboard = [
            [InlineKeyboardButton("✅ Я добавил код", callback_data="check_verification")],
            [InlineKeyboardButton("🔄 Сгенерировать новый код", callback_data="new_code")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🔄 **Новый код сгенерирован!**\n\n"
            f"Добавьте этот код в описание вашего профиля Roblox:\n\n"
            f"`{new_verification_code}`\n\n"
            f"Нажмите '✅ Я добавил код' после добавления:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in new_code: {e}")

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать профиль пользователя"""
    try:
        user_id = update.effective_user.id
        user = db.get_user_by_telegram_id(user_id)
        
        if not user:
            await update.message.reply_text("❌ Профиль не найден. Используйте /start для авторизации.")
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
    except Exception as e:
        logger.error(f"Error in show_profile: {e}")

# Админ команды
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Панель администратора"""
    try:
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
    except Exception as e:
        logger.error(f"Error in admin_panel: {e}")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Бан пользователя"""
    try:
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
    except Exception as e:
        logger.error(f"Error in ban_user: {e}")

async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий администратора"""
    try:
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
                [InlineKeyboardButton("1 час", callback_data=f"ban_1h_{roblox_id}_{reason}")],
                [InlineKeyboardButton("1 день", callback_data=f"ban_1d_{roblox_id}_{reason}")],
                [InlineKeyboardButton("7 дней", callback_data=f"ban_7d_{roblox_id}_{reason}")],
                [InlineKeyboardButton("Навсегда", callback_data=f"ban_permanent_{roblox_id}_{reason}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"🚫 **Бан пользователя**\n\n"
                f"Roblox ID: {roblox_id}\n"
                f"Причина: {reason}\n\n"
                f"Выберите длительность бана:",
                reply_markup=reply_markup
            )
        
        context.user_data.pop('admin_action', None)
    except Exception as e:
        logger.error(f"Error in handle_admin_action: {e}")

async def execute_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выполнение бана"""
    try:
        query = update.callback_query
        await query.answer()
        
        data = query.data.split('_')
        duration_type = data[1]
        roblox_id = data[2]
        reason = '_'.join(data[3:])
        
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
    except Exception as e:
        logger.error(f"Error in execute_ban: {e}")

# Обработчики для групп
async def add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление группы в БД"""
    try:
        if update.effective_chat.type not in ['group', 'supergroup']:
            return
        
        group_id = update.effective_chat.id
        group_title = update.effective_chat.title
        
        db.add_group(group_id, group_title, update.effective_user.id)
        
        await update.message.reply_text("✅ Группа добавлена в систему модерации!")
    except Exception as e:
        logger.error(f"Error in add_group: {e}")

async def main():
    """Основная функция для bothost"""
    try:
        # Создаем Application с более стабильными настройками для хостинга
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Обработчики команд
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("profile", show_profile))
        application.add_handler(CommandHandler("admin", admin_panel))
        application.add_handler(CommandHandler("add_group", add_group))
        
        # Обработчики callback-запросов
        application.add_handler(CallbackQueryHandler(start_auth, pattern="^start_auth$"))
        application.add_handler(CallbackQueryHandler(check_verification, pattern="^check_verification$"))
        application.add_handler(CallbackQueryHandler(new_code, pattern="^new_code$"))
        application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
        application.add_handler(CallbackQueryHandler(ban_user, pattern="^admin_ban$"))
        application.add_handler(CallbackQueryHandler(execute_ban, pattern="^ban_"))
        
        # Обработчики сообщений
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_action))
        
        # Запуск бота с обработкой ошибок
        logger.info("Бот запускается на bothost...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            timeout=30,
            poll_interval=1.0
        )
        
        # Бесконечный цикл для поддержания работы
        while True:
            await asyncio.sleep(3600)  # Спим 1 час
            
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        raise

if __name__ == '__main__':
    # Для локального тестирования
    asyncio.run(main())
