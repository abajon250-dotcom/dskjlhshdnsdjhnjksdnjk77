import asyncpg
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
from config import DATABASE_URL

_pool: Optional[asyncpg.Pool] = None

async def init_db_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    return _pool

async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        await init_db_pool()
    return _pool

# ---------- Инициализация таблиц ----------
async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        # users
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                registered_at TIMESTAMP,
                total_earned REAL DEFAULT 0,
                earned_today REAL DEFAULT 0,
                total_qr INTEGER DEFAULT 0,
                crypto_balance REAL DEFAULT 0,
                referrer_id BIGINT,
                referral_earnings REAL DEFAULT 0,
                terms_accepted BOOLEAN DEFAULT FALSE
            )
        """)
        # qr_submissions
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS qr_submissions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                operator TEXT,
                price REAL,
                phone TEXT,
                photo_file_id TEXT,
                status TEXT DEFAULT 'pending',
                submitted_at TIMESTAMP,
                reviewed_at TIMESTAMP,
                admin_id BIGINT,
                earned_amount REAL DEFAULT 0,
                hold_until TIMESTAMP
            )
        """)
        # operators
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS operators (
                name TEXT PRIMARY KEY,
                price_hold REAL,
                price_bh REAL,
                slot_limit INTEGER DEFAULT -1
            )
        """)
        # bookings
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                operator TEXT,
                created_at TIMESTAMP,
                used BOOLEAN DEFAULT FALSE
            )
        """)
        # settings
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # daily_stats
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                date DATE PRIMARY KEY,
                total_qr INTEGER DEFAULT 0,
                total_earned REAL DEFAULT 0
            )
        """)
        # indexes
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_user ON qr_submissions(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_submissions_status ON qr_submissions(status)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id)")

# ---------- Users ----------
async def register_user(user_id: int, username: str, full_name: str, referrer_id: int = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id, username, full_name, registered_at, referrer_id, terms_accepted) VALUES ($1, $2, $3, $4, $5, FALSE) ON CONFLICT (user_id) DO NOTHING",
            user_id, username, full_name, datetime.now(), referrer_id
        )
        if referrer_id and referrer_id != user_id:
            await update_user_earnings(referrer_id, 1.0, is_referral_bonus=True)

async def accept_terms(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET terms_accepted = TRUE WHERE user_id = $1", user_id)

async def has_accepted_terms(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT terms_accepted FROM users WHERE user_id = $1", user_id)
        return row[0] if row else False

async def get_user(user_id: int) -> Optional[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        return dict(row) if row else None

async def update_user_earnings(user_id: int, amount: float, is_referral_bonus=False):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if is_referral_bonus:
            await conn.execute(
                "UPDATE users SET referral_earnings = referral_earnings + $1, crypto_balance = crypto_balance + $1 WHERE user_id = $2",
                amount, user_id
            )
        else:
            await conn.execute(
                "UPDATE users SET total_earned = total_earned + $1, earned_today = earned_today + $1 WHERE user_id = $2",
                amount, user_id
            )

async def add_crypto_balance(user_id: int, amount: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET crypto_balance = crypto_balance + $1 WHERE user_id = $2", amount, user_id)

async def reset_daily_earnings():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET earned_today = 0")

async def increment_total_qr(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET total_qr = total_qr + 1 WHERE user_id = $1", user_id)

# ---------- Submissions ----------
async def create_submission(user_id: int, operator: str, price: float, phone: str, photo_file_id: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO qr_submissions (user_id, operator, price, phone, photo_file_id, submitted_at, status) VALUES ($1, $2, $3, $4, $5, $6, 'pending') RETURNING id",
            user_id, operator, price, phone, photo_file_id, datetime.now()
        )
        return row['id']

async def get_pending_submissions(limit: int = 20) -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM qr_submissions WHERE status = 'pending' ORDER BY submitted_at DESC LIMIT $1",
            limit
        )
        return [dict(row) for row in rows]

async def get_submission(submission_id: int) -> Optional[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM qr_submissions WHERE id = $1", submission_id)
        return dict(row) if row else None

async def hold_submission(submission_id: int, admin_id: int, hold_until: datetime):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE qr_submissions SET status = 'hold', reviewed_at = $1, admin_id = $2, hold_until = $3 WHERE id = $4",
            datetime.now(), admin_id, hold_until, submission_id
        )

async def accept_submission_now(submission_id: int, admin_id: int, earned_amount: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE qr_submissions SET status = 'accepted', reviewed_at = $1, admin_id = $2, earned_amount = $3 WHERE id = $4",
            datetime.now(), admin_id, earned_amount, submission_id
        )
        sub = await get_submission(submission_id)
        if sub:
            await update_user_earnings(sub['user_id'], earned_amount)
            await increment_total_qr(sub['user_id'])

async def accept_submission_from_hold(submission_id: int, earned_amount: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE qr_submissions SET status = 'accepted', earned_amount = $1 WHERE id = $2",
            earned_amount, submission_id
        )
        sub = await get_submission(submission_id)
        if sub:
            await update_user_earnings(sub['user_id'], earned_amount)
            await increment_total_qr(sub['user_id'])

async def reject_submission(submission_id: int, admin_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE qr_submissions SET status = 'rejected', reviewed_at = $1, admin_id = $2 WHERE id = $3",
            datetime.now(), admin_id, submission_id
        )

async def get_hold_submissions() -> List[Dict]:
    pool = await get_pool()
    now = datetime.now()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM qr_submissions WHERE status = 'hold' AND hold_until > $1",
            now
        )
        return [dict(row) for row in rows]

# ---------- Operators ----------
async def get_operators() -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM operators ORDER BY name")
        return [dict(row) for row in rows]

async def get_operator_price(operator: str, mode: str) -> Optional[float]:
    pool = await get_pool()
    column = "price_hold" if mode == "hold" else "price_bh"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(f"SELECT {column} FROM operators WHERE name = $1", operator)
        return row[0] if row else None

async def update_operator_prices(operator: str, price_hold: float, price_bh: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE operators SET price_hold = $1, price_bh = $2 WHERE name = $3",
            price_hold, price_bh, operator
        )

async def update_operator_slot_limit(operator: str, limit: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE operators SET slot_limit = $1 WHERE name = $2", limit, operator)

# ---------- Bookings ----------
async def create_booking(user_id: int, operator: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO bookings (user_id, operator, created_at) VALUES ($1, $2, $3) RETURNING id",
            user_id, operator, datetime.now()
        )
        return row['id']

async def get_active_booking(user_id: int) -> Optional[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM bookings WHERE user_id = $1 AND used = FALSE ORDER BY created_at DESC LIMIT 1",
            user_id
        )
        return dict(row) if row else None

async def use_booking(booking_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE bookings SET used = TRUE WHERE id = $1", booking_id)

async def cancel_booking(booking_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM bookings WHERE id = $1", booking_id)

async def count_active_bookings_for_operator(operator: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT COUNT(*) FROM bookings WHERE operator = $1 AND used = FALSE", operator)
        return row[0] if row else 0

# ---------- Settings ----------
async def get_setting(key: str, default: str = None) -> Optional[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM settings WHERE key = $1", key)
        return row[0] if row else default

async def set_setting(key: str, value: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2", key, value)

# ---------- Stats ----------
async def get_user_qr_last_30_days(user_id: int) -> Tuple[int, List[str]]:
    pool = await get_pool()
    since = datetime.now() - timedelta(days=30)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT submitted_at FROM qr_submissions WHERE user_id = $1 AND status = 'accepted' AND submitted_at >= $2",
            user_id, since
        )
        dates = [r[0].strftime("%Y-%m-%d") for r in rows]
        return len(rows), list(set(dates))

async def get_today_stats() -> Dict:
    today = datetime.now().date()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*), COALESCE(SUM(earned_amount), 0) FROM qr_submissions WHERE status = 'accepted' AND DATE(submitted_at) = $1",
            today
        )
        return {"total_qr": row[0] or 0, "total_earned": row[1] or 0.0}

async def get_top_users(limit: int = 10) -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, total_earned FROM users ORDER BY total_earned DESC LIMIT $1",
            limit
        )
        return [{"user_id": r[0], "total_earned": r[1]} for r in rows]