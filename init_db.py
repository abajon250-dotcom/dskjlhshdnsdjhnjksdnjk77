import asyncio
from db import init_db, get_pool

async def create_initial_data():
    await init_db()
    pool = await get_pool()
    async with pool.acquire() as conn:
        operators = [
            ("Билайн", 15.0, 12.0, -1),
            ("Газпром", 28.0, 22.0, -1),
            ("МТС", 18.0, 14.0, -1),
            ("Сбер", 12.0, 9.0, -1),
            ("ВТБ", 25.0, 20.0, -1),
            ("Добросвязь", 13.0, 10.0, -1),
            ("Мегафон", 14.0, 11.0, -1),
            ("Т2", 14.0, 11.0, -1)
        ]
        for name, ph, pbh, slots in operators:
            await conn.execute(
                "INSERT INTO operators (name, price_hold, price_bh, slot_limit) VALUES ($1, $2, $3, $4) ON CONFLICT (name) DO NOTHING",
                name, ph, pbh, slots
            )
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES ('sale_mode', 'hold') ON CONFLICT (key) DO NOTHING"
        )
    print("База данных инициализирована (PostgreSQL)")

if __name__ == "__main__":
    asyncio.run(create_initial_data())