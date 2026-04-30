import logging
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta

from config import ADMIN_IDS, REQUIRED_CHANNEL
from db import (
    get_pool, register_user, has_accepted_terms, accept_terms, get_user,
    get_operator_price, create_submission, get_setting, update_user_earnings,
    add_crypto_balance, get_operators, count_active_bookings_for_operator
)
from states import SubmitEsim
from utils import validate_phone, normalize_phone, calculate_rank, calculate_volume_points, calculate_regularity_points, calculate_priority
from keyboards.user_keyboards import (
    main_menu, profile_keyboard, booking_menu, back_button,
    subscription_check_button, get_accept_terms_keyboard
)

router = Router()

# Текст условий
TERMS_TEXT = """📄 **Условия работы:**

• Формат сдачи: одним сообщением — QR‑код + номер телефона в формате "79999999999" для каждой eSIM.

• Критерии: оплаченный тариф (минимум 100 минут) и рабочий QR‑код, залитые QR в несколько приёмок не оплачиваем.

• Выплаты: ежедневно, день в день, после 17:00-19:00 (МСК).

• Wi‑Fi‑звонки не требуются! Не сканируйте QR‑код своим устройством - часто он одноразовый, ничего включать не нужно.

⚠ Условия могут меняться без уведомления.
Без принятия условий доступ к функционалу закрыт."""

# ---------- Старт ----------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].split("_")[1])
        except:
            pass
    user = message.from_user
    await register_user(user.id, user.username, user.full_name, referrer_id)

    if await has_accepted_terms(user.id):
        await message.answer("✅ Вы уже приняли условия.", reply_markup=main_menu(user.id in ADMIN_IDS))
    else:
        await message.answer(TERMS_TEXT, parse_mode="Markdown", reply_markup=get_accept_terms_keyboard())

@router.callback_query(F.data == "accept_terms")
async def accept_terms_callback(callback: CallbackQuery):
    await accept_terms(callback.from_user.id)
    await callback.answer("Условия приняты!")
    # Показываем сообщение о необходимости подписки, если канал задан
    if REQUIRED_CHANNEL:
        text = f"✅ Условия приняты!\n\nТеперь подпишитесь на наш канал: {REQUIRED_CHANNEL}\n\nНажмите кнопку ниже после подписки."
        await callback.message.edit_text(text, reply_markup=subscription_check_button())
    else:
        await callback.message.delete()
        await callback.message.answer("🎉 Добро пожаловать!", reply_markup=main_menu(callback.from_user.id in ADMIN_IDS))

@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery, bot: Bot):
    if not REQUIRED_CHANNEL:
        await callback.message.delete()
        await callback.message.answer("🎉 Главное меню:", reply_markup=main_menu(callback.from_user.id in ADMIN_IDS))
        return

    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, callback.from_user.id)
        if member.status in ("left", "kicked"):
            await callback.answer("❌ Вы не подписаны на канал. Подпишитесь и нажмите снова.", show_alert=True)
        else:
            await callback.answer("✅ Подписка подтверждена!")
            await callback.message.delete()
            await callback.message.answer("🎉 Главное меню:", reply_markup=main_menu(callback.from_user.id in ADMIN_IDS))
    except Exception as e:
        logging.error(f"Check subscription error: {e}")
        if "member list is inaccessible" in str(e):
            await callback.answer("⚠️ Бот не может проверить подписку. Добавьте бота в канал и дайте права.", show_alert=True)
        else:
            await callback.answer("⚠️ Ошибка проверки. Попробуйте позже.", show_alert=True)

# ---------- Сдать ESIM (новый интерфейс) ----------
@router.message(F.text == "📱 Сдать ESIM")
async def cmd_sell_esim(message: Message):
    mode = await get_setting("sale_mode", "hold")
    operators = await get_operators()

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Самый популярный оператор за 30 дней
        row = await conn.fetchrow("""
            SELECT operator, COUNT(*) as cnt 
            FROM qr_submissions 
            WHERE status = 'accepted' AND submitted_at >= NOW() - INTERVAL '30 days'
            GROUP BY operator 
            ORDER BY cnt DESC LIMIT 1
        """)
        most_taken = row['operator'] if row else "нет данных"

        # Операторы с минимальным остатком слотов
        low_stock = []
        for op in operators:
            if op['slot_limit'] != -1:
                used = await count_active_bookings_for_operator(op['name'])
                free = op['slot_limit'] - used
                if free <= 2:
                    low_stock.append(op['name'])
        low_stock_text = ", ".join(low_stock) if low_stock else "все слоты свободны"

    mode_text = "БХ 🟢 (мгновенное начисление)" if mode == "bh" else "ХОЛД 🔴 (начисление через 30 минут)"
    mode_short = "БХ 🟢" if mode == "bh" else "ХОЛД 🔴"

    operators_text = ""
    for op in operators:
        price = op['price_bh'] if mode == 'bh' else op['price_hold']
        marker = "🟢" if (op['name'] in low_stock or op['name'] == most_taken) else ""
        operators_text += f"{op['name']} - {price}$ {marker}\n"

    text = (
        f"📱 **Сдать ESIM**\n\n"
        f"Режим сдачи: {mode_text}\n\n"
        f"🔥 Больше всего взято: {most_taken}\n"
        f"⚠️ Минимальный остаток: {low_stock_text}\n\n"
        f"**Операторы и цены:**\n{operators_text}\n"
        f"Для смены режима нажмите кнопку ниже."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔄 Режим сдачи: {mode_short}", callback_data="toggle_mode_from_sell")],
        *[[InlineKeyboardButton(text=f"{op['name']} - {op['price_bh'] if mode == 'bh' else op['price_hold']}$",
                                callback_data=f"select_operator:{op['name']}")] for op in operators],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    await message.answer(text, parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data == "toggle_mode_from_sell")
async def toggle_mode_from_sell(callback: CallbackQuery):
    current = await get_setting("sale_mode", "hold")
    new_mode = "bh" if current == "hold" else "hold"
    from db import set_setting
    await set_setting("sale_mode", new_mode)
    # Обновляем текущее сообщение, перезапуская cmd_sell_esim
    await cmd_sell_esim(callback.message)
    await callback.answer(f"Режим изменён на {'БХ' if new_mode == 'bh' else 'ХОЛД'}")

@router.callback_query(F.data.startswith("select_operator:"))
async def select_operator(callback: CallbackQuery, state: FSMContext):
    operator = callback.data.split(":")[1]
    mode = await get_setting("sale_mode", "hold")
    price = await get_operator_price(operator, mode)
    if price is None:
        await callback.answer("Ошибка: оператор не найден")
        return
    await state.update_data(operator=operator, price=price)
    await state.set_state(SubmitEsim.waiting_for_photo_and_phone)
    await callback.message.delete()
    await callback.message.answer(
        f"📱 Оператор: {operator}\n💰 Стоимость: {price}$ + бонус ранга.\n\n"
        "Отправьте **фото QR-кода** и **номер телефона** в подписи (пример: +79001234567).\n\n"
        "❗ Важно: фото и номер в одном сообщении.\n\nДля отмены нажмите /cancel"
    )
    await callback.answer()

@router.message(SubmitEsim.waiting_for_photo_and_phone, F.photo)
async def receive_photo(message: Message, state: FSMContext):
    if not message.caption:
        await message.answer("❌ Добавьте номер телефона в подпись к фото.")
        return
    phone = message.caption.strip()
    if not validate_phone(phone):
        await message.answer("❌ Неверный номер. Нужно 11 цифр, начинается с 7. Пример: +79001234567")
        return
    phone = normalize_phone(phone)
    data = await state.get_data()
    operator = data['operator']
    price = data['price']
    user_id = message.from_user.id
    photo_file_id = message.photo[-1].file_id

    mode = await get_setting("sale_mode", "hold")
    if mode == "hold":
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM qr_submissions WHERE operator = $1 AND phone = $2 AND submitted_at >= NOW() - INTERVAL '30 minutes'",
                operator, phone
            )
            if row:
                await message.answer("❌ Этот QR уже сдан недавно (режим ХОЛД). Подождите 30 минут.")
                await state.clear()
                return

    submission_id = await create_submission(user_id, operator, price, phone, photo_file_id)
    await message.answer("✅ QR принят на проверку. Ожидайте решения админа.", reply_markup=main_menu(user_id in ADMIN_IDS))
    await state.clear()

    user = await get_user(user_id)
    username = user['username'] or str(user_id)
    qr_count_30d, _ = await get_user_qr_last_30_days(user_id)
    _, bonus = calculate_rank(qr_count_30d)
    text = (
        f"🆕 Новая сдача eSIM\n"
        f"👤 Пользователь: @{username} (ID {user_id})\n"
        f"📱 Оператор: {operator}\n"
        f"💰 Стоимость: {price}$ + бонус {bonus}$\n"
        f"📞 Номер: {phone}\n"
        f"🕒 Время: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"ID заявки: {submission_id}"
    )
    from keyboards.admin_keyboards import pending_actions
    for admin in ADMIN_IDS:
        try:
            await message.bot.send_photo(admin, photo_file_id, caption=text, reply_markup=pending_actions(submission_id))
        except Exception as e:
            logging.error(f"Не удалось отправить уведомление админу {admin}: {e}")

@router.message(SubmitEsim.waiting_for_photo_and_phone)
async def incorrect_input(message: Message):
    await message.answer("❌ Пожалуйста, отправьте **фото** с подписью-номером. Для отмены используйте /cancel")

@router.message(Command("cancel"))
async def cancel_state(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await message.answer("✅ Действие отменено.", reply_markup=main_menu(message.from_user.id in ADMIN_IDS))
    else:
        await message.answer("🤷‍♂️ Нет активного действия для отмены.", reply_markup=main_menu(message.from_user.id in ADMIN_IDS))

# ---------- Профиль ----------
@router.message(F.text == "👤 Профиль")
async def cmd_profile(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала /start")
        return
    qr_count_30d, unique_dates = await get_user_qr_last_30_days(user['user_id'])
    rank_name, bonus = calculate_rank(qr_count_30d)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) FROM qr_submissions WHERE user_id = $1 AND status='accepted' AND DATE(submitted_at) = CURRENT_DATE",
            user['user_id']
        )
        qr_today = row[0] if row else 0

    volume_points = calculate_volume_points(qr_today)
    regularity_points = calculate_regularity_points(len(unique_dates))
    priority = calculate_priority(volume_points, regularity_points)

    text = (
        f"👤 Профиль @{user['username']} · ID {user['user_id']}\n"
        f"🏆 Ранг: {rank_name}\n"
        f"💰 Бонус: +{bonus}$ к QR\n"
        f"📊 Зачтено за месяц: {qr_count_30d}\n"
        f"🔥 Приоритет: {priority:.1f} · {rank_name}\n"
        f"💵 Ожидаемая выплата за сегодня: {user['earned_today']:.2f}$\n"
        f"💰 Крипто-баланс: {user['crypto_balance']:.2f}$\n"
        f"🕒 Всего заработано: {user['total_earned']:.2f}$\n"
        f"👥 Реферальный бонус: {user['referral_earnings']:.2f}$"
    )
    await message.answer(text, reply_markup=profile_keyboard())

@router.callback_query(F.data == "my_numbers")
async def show_my_numbers(callback: CallbackQuery):
    user_id = callback.from_user.id
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT phone FROM qr_submissions WHERE user_id = $1 ORDER BY submitted_at DESC",
            user_id
        )
    if not rows:
        await callback.answer("У вас нет сохранённых номеров.", show_alert=True)
        return
    numbers = [row['phone'] for row in rows]
    text = "📞 Ваши номера:\n" + "\n".join(f"+{num}" for num in numbers)
    await callback.message.answer(text, reply_markup=back_button())
    await callback.answer()

@router.callback_query(F.data == "ref_system")
async def ref_system_callback(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Сначала /start")
        return
    bot_info = await callback.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref_{user['user_id']}"
    text = f"🌟 Реферальная ссылка:\n{link}\n\n💵 Заработано: {user['referral_earnings']:.2f}$"
    await callback.message.answer(text, reply_markup=back_button())
    await callback.answer()

@router.callback_query(F.data == "my_bot")
async def my_bot_callback(callback: CallbackQuery):
    await my_bot_button(callback.message)
    await callback.answer()

@router.callback_query(F.data == "history")
async def show_history(callback: CallbackQuery):
    user_id = callback.from_user.id
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT operator, price, status, submitted_at, earned_amount
            FROM qr_submissions
            WHERE user_id = $1
            ORDER BY submitted_at DESC
            LIMIT 10
        """, user_id)
    if not rows:
        await callback.answer("Нет сдач", show_alert=True)
        return
    text = "📜 Последние 10 сдач:\n\n"
    for row in rows:
        status_emoji = "✅" if row['status'] == "accepted" else "⏳" if row['status'] == "pending" else "❌"
        earned = row['earned_amount'] or 0
        dt = row['submitted_at'].strftime("%Y-%m-%d %H:%M")
        text += f"{status_emoji} {row['operator']} - {row['price']}$ | {dt} | +{earned}$\n"
    await callback.message.edit_text(text, reply_markup=back_button())
    await callback.answer()

@router.callback_query(F.data == "back_to_menu")
async def back_menu_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("Главное меню:", reply_markup=main_menu(callback.from_user.id in ADMIN_IDS))

# ---------- Бронирование ----------
@router.message(F.text == "📅 Бронирование")
async def cmd_booking(message: Message):
    active = await get_active_booking(message.from_user.id)
    if active:
        text = f"📌 Активная бронь: {active['operator']}\n{active['created_at']}"
        await message.answer(text, reply_markup=booking_menu(True))
    else:
        await message.answer("Нет активной брони.", reply_markup=booking_menu(False))

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
        await callback.answer("Нет свободных слотов для бронирования.", show_alert=True)
        return
    from keyboards.user_keyboards import operators_for_booking
    await callback.message.edit_text("Выберите оператора для бронирования:", reply_markup=operators_for_booking(available))

@router.callback_query(F.data.startswith("book:"))
async def create_booking_callback(callback: CallbackQuery):
    operator = callback.data.split(":")[1]
    user_id = callback.from_user.id
    existing = await get_active_booking(user_id)
    if existing:
        await callback.answer("У вас уже есть активная бронь. Отмените её сначала.", show_alert=True)
        return
    op_list = await get_operators()
    op_data = next((op for op in op_list if op['name'] == operator), None)
    if op_data:
        if op_data['slot_limit'] != -1:
            used = await count_active_bookings_for_operator(operator)
            if used >= op_data['slot_limit']:
                await callback.answer("Все слоты заняты.", show_alert=True)
                return
    from db import create_booking
    await create_booking(user_id, operator)
    await callback.message.edit_text(f"✅ Вы забронировали {operator}. Бронь сгорит после сдачи eSIM.", reply_markup=booking_menu(True))
    await callback.answer()

@router.callback_query(F.data == "cancel_booking")
async def cancel_booking_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    from db import get_active_booking, cancel_booking
    booking = await get_active_booking(user_id)
    if not booking:
        await callback.answer("У вас нет активной брони.", show_alert=True)
        return
    await cancel_booking(booking['id'])
    await callback.message.edit_text("Бронь отменена.", reply_markup=booking_menu(False))
    await callback.answer()

@router.callback_query(F.data == "edit_booking")
async def edit_booking_callback(callback: CallbackQuery):
    await cancel_booking_callback(callback)
    await book_operator_list(callback)

# ---------- Бонусы ----------
@router.message(F.text == "🎁 Бонусы")
async def cmd_bonuses(message: Message):
    user_id = message.from_user.id
    qr_count_30d, unique_dates = await get_user_qr_last_30_days(user_id)
    rank_name, bonus = calculate_rank(qr_count_30d)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) FROM qr_submissions WHERE user_id = $1 AND status='accepted' AND DATE(submitted_at) = CURRENT_DATE",
            user_id
        )
        qr_today = row[0] if row else 0

    volume_points = calculate_volume_points(qr_today)
    regularity_points = calculate_regularity_points(len(unique_dates))
    priority = calculate_priority(volume_points, regularity_points)

    text = (
        f"🎁 Бонусы\n\n"
        f"📈 Ранг: {qr_count_30d} / 30 (Профи), /60 (Элита)\n"
        f"🏆 {rank_name} +${bonus}/QR\n"
        f"⭐ Объём: {volume_points}/5 (сегодня {qr_today} QR)\n"
        f"⭐ Регулярность: {regularity_points}/4 ({len(unique_dates)} дней)\n"
        f"🔥 Приоритет: {priority:.1f} / 7"
    )
    await message.answer(text, reply_markup=back_button())

# ---------- Рефералы ----------
@router.message(F.text == "👥 Рефералы")
async def referral_button(message: Message):
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала /start")
        return
    bot_info = await message.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref_{user['user_id']}"
    text = (
        f"🌟 Ваша реферальная ссылка:\n{link}\n\n"
        f"💵 За каждого приглашённого вы получаете $1 на крипто-баланс.\n"
        f"💰 Всего заработано: {user['referral_earnings']:.2f}$"
    )
    await message.answer(text, reply_markup=back_button())

# ---------- Мой бот ----------
@router.message(F.text == "🤖 Мой бот")
async def my_bot_button(message: Message):
    text = (
        "🤖 **Как создать точно такого же бота**\n\n"
        "1. Напишите [@BotFather](https://t.me/botfather) и создайте нового бота командой /newbot.\n"
        "2. Скопируйте полученный токен.\n"
        "3. Пришлите токен сюда командой: `/deploy <токен>`\n"
        "4. Администратор получит уведомление и свяжется с вами.\n\n"
        "⚠️ Исходный код: [ссылка на GitHub]"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=back_button())

@router.message(Command("deploy"))
async def deploy_command(message: Message):
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /deploy <токен_бота>")
        return
    token = args[1]
    for admin in ADMIN_IDS:
        await message.bot.send_message(admin, f"🚀 Запрос на развёртывание бота от @{message.from_user.username} (ID {message.from_user.id})\nТокен: {token}")
    await message.answer("✅ Запрос отправлен администратору.")

# ---------- Выплаты и крипто-баланс ----------
@router.message(Command("pay"))
async def pay_earnings(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    if not user:
        await message.answer("Сначала /start")
        return
    if user['earned_today'] <= 0:
        await message.answer("Нет средств для перевода.")
        return
    amount = user['earned_today']
    await add_crypto_balance(user_id, amount)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET earned_today = 0 WHERE user_id = $1", user_id)
    await message.answer(f"✅ {amount:.2f}$ переведены в крипто-баланс. Теперь можете вывести командой /withdraw")

@router.message(Command("withdraw"))
async def withdraw_cmd(message: Message):
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /withdraw <сумма>")
        return
    try:
        amount = float(args[1])
    except:
        await message.answer("Неверная сумма")
        return
    user_id = message.from_user.id
    # Проверяем баланс
    user = await get_user(user_id)
    if not user:
        await message.answer("Сначала /start")
        return
    if user['crypto_balance'] < amount:
        await message.answer("❌ Недостаточно средств на крипто-балансе.")
        return
    # Уменьшаем баланс
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET crypto_balance = crypto_balance - $1 WHERE user_id = $2", amount, user_id)
    # Уведомляем админов
    for admin in ADMIN_IDS:
        await message.bot.send_message(admin, f"💰 Запрос вывода: @{message.from_user.username} (ID {user_id}) на сумму {amount}$")
    await message.answer(f"✅ Запрос на вывод {amount}$ отправлен администратору.")

# ---------- Вспомогательная функция get_user_qr_last_30_days (используется в profile и bonuses) ----------
async def get_user_qr_last_30_days(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT submitted_at FROM qr_submissions WHERE user_id = $1 AND status = 'accepted' AND submitted_at >= NOW() - INTERVAL '30 days'",
            user_id
        )
        dates = [row['submitted_at'].strftime("%Y-%m-%d") for row in rows]
        return len(rows), list(set(dates))