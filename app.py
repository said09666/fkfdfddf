import os
import asyncio
import logging
from bot_main import main

# Настройка логирования для bothost
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def run_bot():
    """Запуск бота для bothost"""
    try:
        await main()
    except Exception as e:
        logging.error(f"Bot crashed: {e}")
        # Перезапуск через 60 секунд при падении
        await asyncio.sleep(60)
        await run_bot()

if __name__ == '__main__':
    # Запуск асинхронно для bothost
    asyncio.run(run_bot())
