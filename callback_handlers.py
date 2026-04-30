import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from config import ADMIN_IDS
from db import *
from utils import calculate_rank
from user_keyboards import main_menu, booking_menu, operators_for_booking
from admin_keyboards import pending_actions

router = Router()
hold_tasks = {}

async def start_hold_timer(bot: Bot, submission_id: int, base_price: float, user_id: int, delay_seconds: float):
    await asyncio.sleep(delay_seconds)
    sub = await get_submission(submission_id)
    if sub and sub['status'] == 'hold':
        qr_count_30d, _ = await get_user_qr_last_30_days(user_id)
        _, bonus = calculate_rank(qr_count_30d)
        earned = base_price + bonus
        await accept_submission_from_hold(submission_id, earned)
        try:
            await bot.send_message(user_id, f"✅ Ваш QR прошёл холд! Начислено {earned:.2f}$ (цена {base_price}$ + бонус {bonus}$).", reply_markup=main_menu(user_id in ADMIN_IDS))
        except:
            pass
    if submission_id in hold_tasks:
        del hold_tasks[submission_id]

@router.callback_query(F.data.startswith("accept_sub:"))
async def accept_submission_callback(callback: CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    if admin_id not in ADMIN_IDS:
        await callback.answer("Нет прав", show_alert=True)
        return
    submission_id = int(callback.data.split(":")[1])
    sub = await get_submission(submission_id)
    if not sub or sub['status'] != 'pending':
        await callback.answer("Заявка уже обработана", show_alert=True)
        return

    mode = await get_setting("sale_mode", "hold")
    if mode == "bh":
        qr_count_30d, _ = await get_user_qr_last_30_days(sub['user_id'])
        _, bonus = calculate_rank(qr_count_30d)
        earned = sub['price'] + bonus
        await accept_submission_now(submission_id, admin_id, earned)
        try:
            await bot.send_message(sub['user_id'], f"✅ Ваш QR принят! Начислено {earned:.2f}$ (цена {sub['price']}$ + бонус {bonus}$).", reply_markup=main_menu(sub['user_id'] in ADMIN_IDS))
        except:
            pass
        await callback.answer("Заявка принята, средства начислены")
        try:
            new_caption = f"✅ Принято (БХ, начислено) (админ @{callback.from_user.username})\n" + callback.message.caption.split("ID заявки:")[0]
            await callback.message.edit_caption(caption=new_caption, reply_markup=None)
        except:
            pass
    else:
        hold_until = datetime.now() + timedelta(minutes=30)
        await hold_submission(submission_id, admin_id, hold_until)
        delay = 30 * 60
        task = asyncio.create_task(start_hold_timer(bot, submission_id, sub['price'], sub['user_id'], delay))
        hold_tasks[submission_id] = task
        await callback.answer("Заявка переведена в холд на 30 минут")
        try:
            new_caption = f"⏳ Заявка на холде до {hold_until.strftime('%H:%M')} (админ @{callback.from_user.username})\n" + callback.message.caption.split("ID заявки:")[0]
            await callback.message.edit_caption(caption=new_caption, reply_markup=None)
        except:
            pass

@router.callback_query(F.data.startswith("reject_sub:"))
async def reject_submission_callback(callback: CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    if admin_id not in ADMIN_IDS:
        await callback.answer("Нет прав", show_alert=True)
        return
    submission_id = int(callback.data.split(":")[1])
    sub = await get_submission(submission_id)
    if not sub or sub['status'] not in ('pending', 'hold'):
        await callback.answer("Заявка уже обработана", show_alert=True)
        return
    if submission_id in hold_tasks:
        hold_tasks[submission_id].cancel()
        del hold_tasks[submission_id]
    await reject_submission(submission_id, admin_id)
    try:
        await bot.send_message(sub['user_id'], "❌ Ваш QR отклонён.", reply_markup=main_menu(sub['user_id'] in ADMIN_IDS))
    except:
        pass
    try:
        new_caption = f"❌ Отклонено (админ @{callback.from_user.username})\n" + callback.message.caption.split("ID заявки:")[0]
        await callback.message.edit_caption(caption=new_caption, reply_markup=None)
    except:
        pass
    await callback.answer("Заявка отклонена")

# ---------- Бронирование ----------
@router.callback_query(F.data == "book_operator")
async def book_operator_list(callback: CallbackQuery):
    operators = await get_operators()
    available = []
    for op in operators:
        limit = op['slot_limit']
        if limit == -1:
            free = "∞"
            available.append({"name": op['name'], "free_slots": free})
        else:
            used = await count_active_bookings_for_operator(op['name'])
            free_slots = limit - used
            if free_slots > 0:
                available.append({"name": op['name'], "free_slots": free_slots})
    if not available:
        await callback.answer("Нет свободных слотов", show_alert=True)
        return
    await callback.message.edit_text("Выберите оператора:", reply_markup=operators_for_booking(available))
    await callback.answer()

@router.callback_query(F.data.startswith("book:"))
async def create_booking_callback(callback: CallbackQuery):
    operator = callback.data.split(":")[1]
    user_id = callback.from_user.id
    existing = await get_active_booking(user_id)
    if existing:
        await callback.answer("Уже есть бронь", show_alert=True)
        return
    op_list = await get_operators()
    op_data = next((op for op in op_list if op['name'] == operator), None)
    if op_data and op_data['slot_limit'] != -1:
        used = await count_active_bookings_for_operator(operator)
        if used >= op_data['slot_limit']:
            await callback.answer("Слоты заняты", show_alert=True)
            return
    await create_booking(user_id, operator)
    await callback.message.edit_text(f"✅ Вы забронировали {operator}", reply_markup=booking_menu(True))
    await callback.answer()

@router.callback_query(F.data == "cancel_booking")
async def cancel_booking_callback(callback: CallbackQuery):
    booking = await get_active_booking(callback.from_user.id)
    if not booking:
        await callback.answer("Нет брони", show_alert=True)
        return
    await cancel_booking(booking['id'])
    await callback.message.edit_text("Бронь отменена", reply_markup=booking_menu(False))
    await callback.answer()

@router.callback_query(F.data == "edit_booking")
async def edit_booking_callback(callback: CallbackQuery):
    await cancel_booking_callback(callback)
    await book_operator_list(callback)