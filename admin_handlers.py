import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from datetime import datetime

from config import ADMIN_IDS
from db import (
    get_pool, get_pending_submissions, get_submission, get_operators,
    update_operator_prices, update_operator_slot_limit, get_setting, set_setting,
    get_today_stats, get_top_users, get_user, add_crypto_balance,
    reject_submission, get_hold_submissions, accept_submission_now
)
from states import AdminSetPrice, AdminSetSlot, BroadcastState
from keyboards.admin_keyboards import (
    admin_main_menu, pending_actions, operators_price_edit,
    operators_slot_edit, mode_buttons, confirm_clear, payout_list
)
from keyboards.user_keyboards import main_menu

router = Router()
DATABASE = "esim_bot.db"  # резерв, не используется, оставлено для совместимости

async def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ---------- Главное меню админа ----------
@router.message(F.text == "👑 Админ панель")
async def admin_panel_button(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ Нет прав")
        return
    await message.answer("👑 Панель администратора", reply_markup=admin_main_menu())

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    await callback.message.edit_text("👑 Панель администратора", reply_markup=admin_main_menu())
    await callback.answer()

# ---------- Непроверенные QR ----------
@router.callback_query(F.data == "admin_pending")
async def list_pending(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    pending = await get_pending_submissions(20)
    if not pending:
        await callback.message.edit_text("Нет непроверенных заявок.", reply_markup=admin_main_menu())
        await callback.answer()
        return
    for sub in pending:
        text = f"ID: {sub['id']}\nОператор: {sub['operator']}\nЦена: {sub['price']}$\nНомер: {sub['phone']}\nВремя: {sub['submitted_at']}"
        await callback.message.answer_photo(sub['photo_file_id'], caption=text, reply_markup=pending_actions(sub['id']))
    await callback.message.delete()
    await callback.answer()

# ---------- Изменение цен (две цены: ХОЛД и БХ) ----------
@router.callback_query(F.data == "admin_prices")
async def edit_prices_menu(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    operators = await get_operators()
    kb = []
    for op in operators:
        kb.append([InlineKeyboardButton(
            text=f"{op['name']} (ХОЛД: {op['price_hold']}$, БХ: {op['price_bh']}$)",
            callback_data=f"edit_price:{op['name']}"
        )])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
    await callback.message.edit_text("Выберите оператора для изменения цен:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@router.callback_query(F.data.startswith("edit_price:"))
async def start_edit_price(callback: CallbackQuery, state: FSMContext):
    operator = callback.data.split(":")[1]
    await state.update_data(edit_operator=operator)
    await state.set_state(AdminSetPrice.waiting_for_price)
    # Получаем текущие цены через прямое обращение к БД
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT price_hold, price_bh FROM operators WHERE name = $1", operator)
        if row:
            current = f"ХОЛД: {row['price_hold']}$, БХ: {row['price_bh']}$"
        else:
            current = "неизвестно"
    await callback.message.edit_text(
        f"Введите новые цены для {operator} в формате:\n`цена_холд цена_бх`\n"
        f"Пример: `15 12`\n\nТекущие: {current}",
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(AdminSetPrice.waiting_for_price)
async def set_new_prices(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await message.answer("Нет прав")
        return
    try:
        parts = message.text.split()
        if len(parts) != 2:
            raise ValueError
        price_hold = float(parts[0].replace(',', '.'))
        price_bh = float(parts[1].replace(',', '.'))
    except:
        await message.answer("❌ Неверный формат. Введите две цены через пробел, например: `15 12`", parse_mode="Markdown")
        return
    data = await state.get_data()
    operator = data['edit_operator']
    await update_operator_prices(operator, price_hold, price_bh)
    await message.answer(f"✅ Цены для {operator} обновлены:\nХОЛД: {price_hold}$, БХ: {price_bh}$")
    await state.clear()

# ---------- Переключение режима ХОЛД/БХ ----------
@router.callback_query(F.data == "admin_toggle_mode")
async def toggle_mode_menu(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    current = await get_setting("sale_mode", "hold")
    await callback.message.edit_text(f"Текущий режим: {'ХОЛД' if current == 'hold' else 'БХ'}", reply_markup=mode_buttons(current))
    await callback.answer()

@router.callback_query(F.data == "toggle_mode_confirm")
async def toggle_mode(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    current = await get_setting("sale_mode", "hold")
    new_mode = "bh" if current == "hold" else "hold"
    await set_setting("sale_mode", new_mode)
    await callback.message.edit_text(f"Режим изменён на: {'БХ' if new_mode == 'bh' else 'ХОЛД'}", reply_markup=admin_main_menu())
    await callback.answer()

# ---------- Управление слотами бронирования ----------
@router.callback_query(F.data == "admin_slots")
async def slots_menu(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    operators = await get_operators()
    await callback.message.edit_text("Выберите оператора для установки лимита слотов:", reply_markup=operators_slot_edit(operators))
    await callback.answer()

@router.callback_query(F.data.startswith("edit_slot:"))
async def start_edit_slot(callback: CallbackQuery, state: FSMContext):
    operator = callback.data.split(":")[1]
    await state.update_data(slot_operator=operator)
    await state.set_state(AdminSetSlot.waiting_for_slot_limit)
    await callback.message.edit_text(f"Введите лимит слотов для {operator} (число, -1 безлимит, 0 недоступно):")
    await callback.answer()

@router.message(AdminSetSlot.waiting_for_slot_limit)
async def set_slot_limit(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    try:
        limit = int(message.text)
    except:
        await message.answer("Введите целое число.")
        return
    data = await state.get_data()
    operator = data['slot_operator']
    await update_operator_slot_limit(operator, limit)
    await message.answer(f"Лимит слотов для {operator} установлен: {limit if limit != -1 else 'безлимит'}")
    await state.clear()

# ---------- Статистика ----------
@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    today_stats = await get_today_stats()
    top_users = await get_top_users(5)
    text = f"📊 Статистика за сегодня:\n✅ Зачтено QR: {today_stats['total_qr']}\n💰 Сумма: {today_stats['total_earned']:.2f}$\n\n🏆 Топ-5 по общему заработку:\n"
    for i, u in enumerate(top_users, 1):
        user = await get_user(u['user_id'])
        name = f"@{user['username']}" if user and user['username'] else f"ID {u['user_id']}"
        text += f"{i}. {name} — {u['total_earned']:.2f}$\n"
    await callback.message.edit_text(text, reply_markup=admin_main_menu())
    await callback.answer()

# ---------- Выплаты (список пользователей с earned_today > 0) ----------
@router.callback_query(F.data == "admin_payouts")
async def payouts_list(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, username, earned_today FROM users WHERE earned_today > 0")
    if not rows:
        await callback.message.edit_text("Нет пользователей для выплаты сегодня.", reply_markup=admin_main_menu())
        return
    # Преобразуем в список словарей для клавиатуры
    users = [{"user_id": r['user_id'], "username": r['username'], "earned_today": r['earned_today']} for r in rows]
    await callback.message.edit_text("💸 Пользователи к выплате:", reply_markup=payout_list(users))
    await callback.answer()

@router.callback_query(F.data.startswith("mark_paid:"))
async def mark_paid(callback: CallbackQuery):
    uid = int(callback.data.split(":")[1])
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET earned_today = 0 WHERE user_id = $1", uid)
    await callback.answer("Пользователь отмечен как выплаченный")
    await callback.message.delete()
    await callback.message.answer("Главное меню админа", reply_markup=admin_main_menu())

# ---------- Очистка всех непроверенных заявок ----------
@router.callback_query(F.data == "admin_clear_pending")
async def confirm_clear(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    await callback.message.edit_text("Вы уверены, что хотите удалить все непроверенные заявки?", reply_markup=confirm_clear())
    await callback.answer()

@router.callback_query(F.data == "confirm_clear_pending")
async def clear_pending(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM qr_submissions WHERE status = 'pending'")
    await callback.message.edit_text("Все непроверенные заявки удалены.", reply_markup=admin_main_menu())
    await callback.answer()

# ---------- Работа с крипто-балансом ----------
@router.message(Command("add_crypto"))
async def add_crypto(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("Нет прав")
        return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Использование: /add_crypto <user_id> <сумма>")
        return
    try:
        uid = int(args[1])
        amount = float(args[2])
    except:
        await message.answer("Неверный формат")
        return
    await add_crypto_balance(uid, amount)
    await message.answer(f"Крипто-баланс пользователя {uid} пополнен на {amount}$")

# ---------- Бэкап и восстановление БД (только для SQLite, здесь не работает, оставлено для совместимости) ----------
# Для PostgreSQL бэкап делается через дамп БД, поэтому команды /backup и /restore можно убрать или оставить заглушку.
# В данном коде они убраны, но если нужны — можно реализовать через subprocess.

# ---------- Рассылка пользователям ----------
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    await state.set_state(BroadcastState.waiting_for_message)
    await callback.message.edit_text(
        "📢 Введите текст сообщения для рассылки всем пользователям.\n\n"
        "Можно отправлять текст, фото, видео, документы — бот отправит всё как есть.\n\n"
        "Для отмены нажмите /cancel"
    )
    await callback.answer()

@router.message(BroadcastState.waiting_for_message)
async def admin_broadcast_send(message: Message, state: FSMContext, bot: Bot):
    if not await is_admin(message.from_user.id):
        await message.answer("Нет прав")
        return

    # Получаем всех пользователей из БД
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
    user_ids = [row['user_id'] for row in rows]

    if not user_ids:
        await message.answer("Нет пользователей для рассылки.")
        await state.clear()
        return

    # Подтверждение перед отправкой
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отправить", callback_data="confirm_broadcast")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")]
    ])
    await state.update_data(broadcast_message=message)
    await message.answer(f"📊 Будет отправлено {len(user_ids)} пользователям.\nНачать рассылку?", reply_markup=kb)

@router.callback_query(F.data == "confirm_broadcast")
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return

    data = await state.get_data()
    original_message: Message = data.get('broadcast_message')
    if not original_message:
        await callback.answer("Сообщение не найдено", show_alert=True)
        return

    # Получаем список пользователей
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
    user_ids = [row['user_id'] for row in rows]

    success = 0
    fail = 0
    for uid in user_ids:
        try:
            if original_message.text:
                await bot.send_message(uid, original_message.text, parse_mode="HTML")
            elif original_message.photo:
                await bot.send_photo(uid, original_message.photo[-1].file_id, caption=original_message.caption)
            elif original_message.video:
                await bot.send_video(uid, original_message.video.file_id, caption=original_message.caption)
            elif original_message.document:
                await bot.send_document(uid, original_message.document.file_id, caption=original_message.caption)
            else:
                # Если сообщение без контента (редко)
                await bot.send_message(uid, "Сообщение от администратора")
            success += 1
        except Exception as e:
            logging.error(f"Не удалось отправить пользователю {uid}: {e}")
            fail += 1

    await callback.message.edit_text(f"✅ Рассылка завершена.\n✅ Успешно: {success}\n❌ Ошибок: {fail}")
    await state.clear()
    await callback.answer()

# ---------- Дополнительные команды для админа (необязательные) ----------
@router.message(Command("pending"))
async def cmd_pending(message: Message):
    """Альтернативная команда /pending — список непроверенных"""
    if not await is_admin(message.from_user.id):
        return
    pending = await get_pending_submissions(10)
    if not pending:
        await message.answer("Нет непроверенных заявок.")
        return
    for sub in pending:
        text = f"ID: {sub['id']}\nОператор: {sub['operator']}\nЦена: {sub['price']}$\nНомер: {sub['phone']}\nВремя: {sub['submitted_at']}"
        await message.answer_photo(sub['photo_file_id'], caption=text, reply_markup=pending_actions(sub['id']))

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Краткая статистика"""
    if not await is_admin(message.from_user.id):
        return
    today = await get_today_stats()
    await message.answer(f"📊 За сегодня: QR: {today['total_qr']}, сумма: {today['total_earned']:.2f}$")