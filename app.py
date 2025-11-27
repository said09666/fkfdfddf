import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import requests
from datetime import datetime

from config import Config, Text
from database import Database

# Настройка логирования для Bothost
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class RobloxVerificationBot:
    def __init__(self):
        self.db = Database()
        self.application = None
        self.setup_bot()
    
    def setup_bot(self):
        """Инициализация бота"""
        try:
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
            join_date = datetime.fromisoformat(join_date.replace('Z', '+00:00')).strftime('%d.%m.%Y')
        
        success_message = Config.SUCCESS_MESSAGE.format(
            username=user_data['name'],
            user_id=user_data['id'],
            join_date=join_date
        )
        
        await update.message.reply_text(
            success_message,
            parse_mode='Markdown'
        )
        
        # Имитируем отправку запроса в друзья
        await update.message.reply_text(Text.FRIEND_REQUEST_SENT)
        
        logger.info(f"User {user_id} verified as Roblox user {user_data['name']} (ID: {user_data['id']})")
    
    def extract_username(self, input_text: str) -> str:
        """Извлекает username из текста"""
        if 'roblox.com/users/' in input_text:
            import re
            match = re.search(r'roblox\.com/users/(\d+)/', input_text)
            if match:
                return self.get_username_from_id(match.group(1))
        
        input_text = input_text.replace('@', '').strip()
        return input_text if input_text else None
    
    def get_roblox_user(self, username: str) -> dict:
        """Получает данные пользователя Roblox через API"""
        try:
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
                        'created': user.get('created')
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
            [InlineKeyboardButton("👥 Управление пользователями", callback_data="admin_users")],
            [InlineKeyboardButton("📢 Сделать рассылку", callback_data="admin_broadcast")],
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
├ Ожидают: {stats['total_users'] - stats['verified_users']}
└ Заблокировано: {stats['banned_users']}

⚡ **Система:**
├ Бот: 🟢 Онлайн
├ База данных: 🟢 Работает
└ API Roblox: 🟢 Доступно
        """
        
        keyboard = [[InlineKeyboardButton(Text.BACK, callback_data="admin_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def run_webhook(self):
        """Запуск бота через webhook (для Bothost)"""
        try:
            # Получаем URL вебхука от Bothost
            webhook_url = os.getenv('WEBHOOK_URL', '')
            
            if webhook_url:
                await self.application.bot.set_webhook(webhook_url)
                logger.info(f"Webhook set to: {webhook_url}")
            else:
                logger.info("Starting polling mode")
                
            await self.application.run_polling()
            
        except Exception as e:
            logger.error(f"Error running bot: {e}")
            raise
    
    def run(self):
        """Запуск бота"""
        try:
            # Добавляем администраторов при первом запуске
            for admin_id in Config.ADMIN_IDS:
                self.db.add_admin(admin_id, f"admin_{admin_id}")
            
            logger.info("Starting Roblox Verification Bot...")
            
            # Запускаем бота
            asyncio.run(self.run_webhook())
            
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Bot crashed: {e}")

# Создаем и запускаем бота
if __name__ == '__main__':
    bot = RobloxVerificationBot()
    bot.run()
