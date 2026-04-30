from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def main_menu(is_admin: bool = False):
    buttons = [
        [KeyboardButton(text="📱 Сдать ESIM")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📅 Бронирование")],
        [KeyboardButton(text="🎁 Бонусы"), KeyboardButton(text="👥 Рефералы")],
        [KeyboardButton(text="🤖 Мой бот")]
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="👑 Админ панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_accept_terms_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ПРИНЯТЬ УСЛОВИЯ", callback_data="accept_terms")]
    ])

def subscription_check_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription")]
    ])

def profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Полезное", url="https://t.me/esim_info"),
         InlineKeyboardButton(text="🤖 Мой бот", callback_data="my_bot")],
        [InlineKeyboardButton(text="📞 Мои номера", callback_data="my_numbers"),
         InlineKeyboardButton(text="👥 Рефералы", callback_data="ref_system")],
        [InlineKeyboardButton(text="📜 История сдач", callback_data="history")]
    ])

def booking_menu(has_booking: bool):
    if has_booking:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Забронировать", callback_data="book_operator")],
            [InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_booking"),
             InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_booking")]
        ])
    else:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Забронировать", callback_data="book_operator")]
        ])

def operators_for_booking(operators):
    kb = []
    for op in operators:
        kb.append([InlineKeyboardButton(text=f"{op['name']} (свободно {op['free_slots']})", callback_data=f"book:{op['name']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def back_button():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]])