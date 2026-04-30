import asyncio
from db import init_db
import aiosqlite

async def create_initial_data():
    await init_db()
    async with aiosqlite.connect("esim_bot.db") as db:
        operators = [
            ("Билайн", 15.0, 12.0, -1),   # (name, price_hold, price_bh, slot_limit)
            ("Газпром", 28.0, 22.0, -1),
            ("МТС", 18.0, 14.0, -1),
            ("Сбер", 12.0, 9.0, -1),
            ("ВТБ", 25.0, 20.0, -1),
            ("Добросвязь", 13.0, 10.0, -1),
            ("Мегафон", 14.0, 11.0, -1),
            ("Т2", 14.0, 11.0, -1)
        ]
        for name, price_hold, price_bh, slots in operators:
            await db.execute(
                "INSERT OR IGNORE INTO operators (name, price_hold, price_bh, slot_limit) VALUES (?, ?, ?, ?)",
                (name, price_hold, price_bh, slots)
            )
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('sale_mode', 'hold')")
        await db.commit()
    print("База данных инициализирована (две цены: ХОЛД и БХ)")

if __name__ == "__main__":
    asyncio.run(create_initial_data())