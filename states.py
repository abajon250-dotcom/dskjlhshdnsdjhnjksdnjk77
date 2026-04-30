from aiogram.fsm.state import State, StatesGroup

class SubmitEsim(StatesGroup):
    waiting_for_photo_and_phone = State()

class AdminSetPrice(StatesGroup):
    waiting_for_price = State()

class AdminSetSlot(StatesGroup):
    waiting_for_slot_limit = State()

class BroadcastState(StatesGroup):
    waiting_for_message = State()