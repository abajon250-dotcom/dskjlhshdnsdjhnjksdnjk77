import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from datetime import datetime

from config import BOT_TOKEN
from handlers import user_handlers, admin_handlers, callback_handlers
from middleware import SubscriptionMiddleware
from db import get_hold_submissions
from handlers.callback_handlers import start_hold_timer

async def restore_holds(bot: Bot):
    submissions = await get_hold_submissions()
    for sub in submissions:
        hold_until = datetime.fromisoformat(sub['hold_until'])
        delay = (hold_until - datetime.now()).total_seconds()
        if delay > 0:
            asyncio.create_task(start_hold_timer(bot, sub['id'], sub['price'], sub['user_id'], delay))

async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    dp.include_router(user_handlers.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(callback_handlers.router)

    await bot.delete_webhook(drop_pending_updates=True)
    await restore_holds(bot)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())