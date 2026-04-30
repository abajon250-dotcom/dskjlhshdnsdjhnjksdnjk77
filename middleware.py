from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable
from config import ADMIN_IDS, REQUIRED_CHANNEL
from db import has_accepted_terms
import logging

class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        # Пропускаем команды /start и /cancel, а также важные callback'и
        if isinstance(event, Message):
            if event.text and event.text.startswith(("/start", "/cancel")):
                return await handler(event, data)
        if isinstance(event, CallbackQuery):
            if event.data in ("accept_terms", "check_subscription", "toggle_mode_from_sell"):
                return await handler(event, data)

        # Проверяем, принял ли условия
        if not await has_accepted_terms(user.id):
            if isinstance(event, Message):
                await event.answer("❌ Сначала примите условия через /start")
            elif isinstance(event, CallbackQuery):
                await event.answer("❌ Сначала примите условия через /start", show_alert=True)
            return

        # Проверка подписки на канал (если канал задан)
        if REQUIRED_CHANNEL:
            try:
                member = await data["bot"].get_chat_member(REQUIRED_CHANNEL, user.id)
                if member.status in ("left", "kicked"):
                    from keyboards.user_keyboards import subscription_check_button
                    text = f"❌ Вы не подписаны на канал {REQUIRED_CHANNEL}. Подпишитесь и нажмите кнопку."
                    if isinstance(event, Message):
                        await event.answer(text, reply_markup=subscription_check_button())
                    elif isinstance(event, CallbackQuery):
                        await event.message.edit_text(text, reply_markup=subscription_check_button())
                    return
            except Exception as e:
                logging.warning(f"Subscription check error: {e}")
                # Не блокируем пользователя, но предупреждаем
                from keyboards.user_keyboards import subscription_check_button
                text = f"⚠️ Не удалось проверить подписку на канал {REQUIRED_CHANNEL}.\n\nПожалуйста, убедитесь, что бот добавлен в канал, и нажмите кнопку."
                if isinstance(event, Message):
                    await event.answer(text, reply_markup=subscription_check_button())
                elif isinstance(event, CallbackQuery):
                    await event.message.edit_text(text, reply_markup=subscription_check_button())
                return

        return await handler(event, data)