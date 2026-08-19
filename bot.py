import asyncio
import datetime
import logging
import os
import aiohttp
import aiosqlite
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ContentType
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardRemove
)

# ================= CONFIGURATION =================
BOT_TOKEN = "8640036196:AAFJMQcClr754GmYjkuygNt85TF8eGGfig8"
ADMIN_SECRET = "ayubxon293929"
DB_PATH = "bot_database.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ================= DATABASE SETUP =================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                referrer_id INTEGER,
                sub_expires_at TEXT,
                is_banned INTEGER DEFAULT 0,
                stars_earned INTEGER DEFAULT 0
            )
        ''')
        
        try:
            await db.execute("ALTER TABLE users ADD COLUMN notified_1d INTEGER DEFAULT 0")
        except Exception:
            pass

        await db.execute('''
            CREATE TABLE IF NOT EXISTS messages_cache (
                business_connection_id TEXT,
                message_id INTEGER,
                chat_id INTEGER,
                from_user_id INTEGER,
                from_user_name TEXT,
                from_username TEXT,
                content_type TEXT,
                text_content TEXT,
                file_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (business_connection_id, message_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                days INTEGER,
                activations_left INTEGER
            )
        ''')
        await db.execute('''
            INSERT OR IGNORE INTO settings (key, value)
            VALUES ('start_message', 'Assalomu Aleykum botimizga xush kelibsiz. Bu bot orqali chatlarni boshqaring.')
        ''')
        await db.commit()


# ================= FSM STATES =================
class AdminStates(StatesGroup):
    auth = State()
    set_sub_user = State()
    set_sub_days = State()
    remove_sub_user = State()
    ban_user = State()
    unban_user = State()
    create_promo_name = State()
    create_promo_days = State()
    create_promo_acts = State()
    edit_start_msg = State()
    broadcast_msg = State()
    view_user_id = State()
    view_user_give_days = State()


class UserStates(StatesGroup):
    entering_promo = State()


# ================= HELPER FUNCTIONS =================
async def get_setting(key: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else ""

async def is_user_banned(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return bool(row and row[0] == 1)

async def has_active_sub(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT sub_expires_at, is_banned FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if not row: return False
            if row[1] == 1: return False
            if not row[0]: return False
            exp = datetime.datetime.fromisoformat(row[0])
            return exp > datetime.datetime.now()

async def get_subscribed_owner_id(business_connection_id: str, event_name: str):
    """
    Business ulanishning egasini (owner_id) topadi va uning FAOL OBUNASI bor-yo'qligini tekshiradi.
    Faol obuna bo'lmasa None qaytaradi -- shunda hech qanday xabar hech kimga yuborilmaydi.
    Barcha business_message / edited / deleted handlerlar FAQAT shu funksiya orqali ishlaydi,
    shunday qilib tekshiruv mantig'i bitta joyda va hech qachon chetlab o'tilmaydi.
    """
    try:
        conn = await bot.get_business_connection(business_connection_id)
        owner_id = conn.user_chat_id
    except Exception as e:
        logging.error(f"[{event_name}] business_connection topilmadi: {e}")
        return None

    active = await has_active_sub(owner_id)
    if not active:
        logging.info(f"[{event_name}] BLOKLANDI: owner_id={owner_id} da faol obuna yo'q")
        return None

    logging.info(f"[{event_name}] RUXSAT: owner_id={owner_id} da faol obuna bor")
    return owner_id

async def get_profile_text(user_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT sub_expires_at FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            sub_status = "Нет активной подписки"
            if row and row[0]:
                exp = datetime.datetime.fromisoformat(row[0])
                if exp > datetime.datetime.now():
                    sub_status = f"Активна до: {exp.strftime('%Y-%m-%d %H:%M')}"
    return (
        "👤 <b>Ваш профиль:</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💎 Статус подписки: <b>{sub_status}</b>"
    )


# ================= BACKGROUND TASKS =================
async def check_subscriptions_task():
    while True:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT user_id, sub_expires_at FROM users WHERE sub_expires_at IS NOT NULL AND notified_1d = 0 AND is_banned = 0") as cur:
                    rows = await cur.fetchall()
                    now = datetime.datetime.now()
                    
                    for user_id, exp_str in rows:
                        exp = datetime.datetime.fromisoformat(exp_str)
                        time_left = exp - now
                        
                        if datetime.timedelta(0) < time_left <= datetime.timedelta(days=1):
                            text = (
                                "⏳ <b>Подписка скоро закончится!</b>\n"
                                "Осталось 1 дня до конца подписки.\n"
                                "Продли её, чтобы бот продолжал работать дальше."
                            )
                            kb = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="Продлить Подписку", callback_data="buy_sub")]
                            ])
                            try:
                                await bot.send_message(user_id, text, reply_markup=kb, parse_mode="HTML")
                                await db.execute("UPDATE users SET notified_1d = 1 WHERE user_id = ?", (user_id,))
                                await db.commit()
                            except Exception:
                                pass
        except Exception as e:
            logging.error(f"Error in sub checker: {e}")
        
        await asyncio.sleep(3600)

async def keep_awake_task():
    # Render avtomatik RENDER_EXTERNAL_URL beradi (masalan https://sizning-bot.onrender.com)
    external_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not external_url:
        logging.warning("RENDER_EXTERNAL_URL topilmadi, keep_awake_task o'chirilgan.")
        return

    while True:
        await asyncio.sleep(600)  # 10 daqiqada bir marta (Render 15 daq harakatsizlikdan keyin uxlatadi)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{external_url}/health", timeout=aiohttp.ClientTimeout(total=15)) as response:
                    logging.info(f"Keep-awake ping status: {response.status}")
        except Exception as e:
            logging.warning(f"Keep-awake ping failed: {e}")


# ================= KEYBOARDS =================
def start_inline_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Профиль", callback_data="profile_menu")],
            [InlineKeyboardButton(text="ℹ️ Информация", callback_data="info_menu")],
            [InlineKeyboardButton(text="🛠 Support", url="https://t.me/ayubkhan_533")]
        ]
    )

def profile_inline_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Оплатить подписку", callback_data="buy_sub")],
            [
                InlineKeyboardButton(text="👥 Реферальная система", callback_data="ref_system"),
                InlineKeyboardButton(text="🎟 Ввести промокод", callback_data="use_promo"),
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_start")]
        ]
    )

def sub_plans_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="1 месяц — 10 ⭐", callback_data="sub_1_10")],
            [InlineKeyboardButton(text="3 месяца — 30 ⭐", callback_data="sub_3_30")],
            [InlineKeyboardButton(text="6 месяцев — 60 ⭐", callback_data="sub_6_60")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_profile")]
        ]
    )

def admin_panel_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👤 Foydalanuvchilar", callback_data="adm_view_user")],
            [InlineKeyboardButton(text="➕ Выдать подписку", callback_data="adm_give_sub"),
             InlineKeyboardButton(text="➖ Убрать подписку", callback_data="adm_remove_sub")],
            [
                InlineKeyboardButton(text="🚫 Бан", callback_data="adm_ban"),
                InlineKeyboardButton(text="✅ Разбан", callback_data="adm_unban"),
            ],
            [InlineKeyboardButton(text="🎟 Создать промокод", callback_data="adm_make_promo")],
            [InlineKeyboardButton(text="✏️ Изменить Start текст", callback_data="adm_edit_start")],
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm_broadcast")]
        ]
    )


def user_view_kb(uid: int, is_banned: bool):
    ban_btn = (
        InlineKeyboardButton(text="✅ Unban", callback_data=f"uv_unban_{uid}")
        if is_banned else
        InlineKeyboardButton(text="🚫 Ban", callback_data=f"uv_ban_{uid}")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [ban_btn],
            [
                InlineKeyboardButton(text="➕ Выдать подписку", callback_data=f"uv_givesub_{uid}"),
                InlineKeyboardButton(text="➖ Убрать подписку", callback_data=f"uv_removesub_{uid}"),
            ],
            [InlineKeyboardButton(text="◀️ Admin panel", callback_data="uv_back_to_admin")]
        ]
    )


async def build_user_view(uid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT sub_expires_at, is_banned, username, full_name FROM users WHERE user_id = ?", (uid,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        return f"❌ ID <code>{uid}</code> bazada topilmadi. Foydalanuvchi botni /start qilmagan bo'lishi mumkin.", None

    exp_str, is_banned, username, full_name = row
    sub_status = "Yo'q"
    if exp_str:
        exp = datetime.datetime.fromisoformat(exp_str)
        if exp > datetime.datetime.now():
            sub_status = f"Faol, {exp.strftime('%Y-%m-%d %H:%M')} gacha"
        else:
            sub_status = f"Muddati o'tgan ({exp.strftime('%Y-%m-%d %H:%M')})"

    text = (
        "👤 <b>Foydalanuvchi ma'lumoti</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"👤 Ism: {full_name or '-'}\n"
        f"🔗 Username: @{username if username else 'yoq'}\n"
        f"💎 Obuna: {sub_status}\n"
        f"🚫 Ban holati: {'Ha, banlangan' if is_banned else 'Yoq'}"
    )
    return text, user_view_kb(uid, bool(is_banned))


# ================= USER HANDLERS =================
@dp.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    tmp_msg = await message.answer("🔄", reply_markup=ReplyKeyboardRemove())
    await tmp_msg.delete()

    user_id = message.from_user.id
    if await is_user_banned(user_id):
        return

    referrer = None
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            potential_ref = int(args[1].replace("ref_", ""))
            if potential_ref != user_id:
                referrer = potential_ref
        except ValueError:
            pass

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT OR IGNORE INTO users (user_id, username, full_name, referrer_id)
            VALUES (?, ?, ?, ?)
        ''', (user_id, message.from_user.username or "", message.from_user.full_name, referrer))
        await db.commit()

    start_text = await get_setting("start_message")
    await message.answer(start_text, reply_markup=start_inline_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "back_to_start")
async def back_to_start_call(call: CallbackQuery, state: FSMContext):
    await state.clear()
    start_text = await get_setting("start_message")
    await call.message.edit_text(start_text, reply_markup=start_inline_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "info_menu")
async def info_menu_call(call: CallbackQuery):
    text = (
        "ℹ️ <b>Информация и подключение</b>\n\n"
        "Этот бот позволяет перехватывать удаленные и измененные сообщения, фото и видео в ваших личных чатах.\n\n"
        "<b>Как подключить бота:</b>\n"
        "1. Убедитесь, что у вас есть <b>Telegram Premium</b>.\n"
        "2. Перейдите в <b>Настройки</b> Telegram.\n"
        "3. Выберите <b>Telegram Business</b> -> <b>Чат-боты</b>.\n"
        "4. Вставьте юзернейм этого бота и разрешите доступ к сообщениям.\n\n"
        "❗️ <i>Бот будет обрабатывать перехваченные сообщения только при наличии активной подписки!</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_start")]])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "profile_menu")
async def profile_menu_call(call: CallbackQuery):
    if await is_user_banned(call.from_user.id):
        await call.answer("Вы забанены.", show_alert=True)
        return
    text = await get_profile_text(call.from_user.id)
    await call.message.edit_text(text, reply_markup=profile_inline_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "back_to_profile")
async def back_profile(call: CallbackQuery):
    text = await get_profile_text(call.from_user.id)
    await call.message.edit_text(text, reply_markup=profile_inline_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "buy_sub")
async def show_sub_plans(call: CallbackQuery):
    await call.message.edit_text("Оплата подписки\n\nВыбери срок подписки:", reply_markup=sub_plans_kb())

@dp.callback_query(F.data.startswith("sub_"))
async def process_stars_invoice(call: CallbackQuery):
    _, months_str, stars_str = call.data.split("_")
    months = int(months_str)
    stars = int(stars_str)

    prices = [LabeledPrice(label=f"Подписка на {months} мес.", amount=stars)]
    await bot.send_invoice(
        chat_id=call.message.chat.id,
        title=f"Подписка на {months} мес.",
        description=f"Telegram Business chat bot boshqaruvi ({months} oy учун)",
        payload=f"sub_{months}_{stars}",
        currency="XTR",
        prices=prices,
        provider_token=""
    )
    await call.answer()

@dp.pre_checkout_query()
async def on_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.content_type == ContentType.SUCCESSFUL_PAYMENT)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    months = int(payload.split("_")[1])
    stars_paid = int(payload.split("_")[2])
    user_id = message.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT sub_expires_at, referrer_id FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            curr_exp = row[0] if row else None
            referrer_id = row[1] if row else None

        now = datetime.datetime.now()
        base_time = now
        if curr_exp:
            exp_date = datetime.datetime.fromisoformat(curr_exp)
            if exp_date > now:
                base_time = exp_date

        new_expires = base_time + datetime.timedelta(days=months * 30)
        await db.execute("UPDATE users SET sub_expires_at = ?, notified_1d = 0 WHERE user_id = ?", (new_expires.isoformat(), user_id))

        if referrer_id:
            cut = int(stars_paid * 0.25)
            await db.execute("UPDATE users SET stars_earned = stars_earned + ? WHERE user_id = ?", (cut, referrer_id))
            try:
                await bot.send_message(referrer_id, f"🎉 Ваш реферал оплатил подписку! Вам начислено: {cut} ⭐")
            except Exception:
                pass

        await db.commit()

    await message.answer(f"✅ Оплата прошла успешно! Подписка активна до {new_expires.strftime('%Y-%m-%d %H:%M')}.")
    text = await get_profile_text(user_id)
    await message.answer(text, reply_markup=profile_inline_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "ref_system")
async def ref_system_info(call: CallbackQuery):
    user_id = call.from_user.id
    bot_info = await bot.get_me()
    reflink = f"https://t.me/{bot_info.username}?start=ref_{user_id}"

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,)) as cur:
            invited = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ? AND sub_expires_at IS NOT NULL", (user_id,)) as cur:
            paid_count = (await cur.fetchone())[0]
        async with db.execute("SELECT stars_earned FROM users WHERE user_id = ?", (user_id,)) as cur:
            stars_earned = (await cur.fetchone())[0] or 0

    text = (
        f"Твоя реферальная ссылка:\n<code>{reflink}</code>\n\n"
        f"Текущий процент отчисления: 25%.\n"
        f"Приведено пользователей: {invited}\n"
        f"Из них оплатили подписку: {paid_count}\n"
        f"Всего заработано: {stars_earned} ⭐"
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_profile")]]
    ))

@dp.callback_query(F.data == "use_promo")
async def promo_ask(call: CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.entering_promo)
    await call.message.edit_text("Отправь промокод одним сообщением.\n\nПример: <code>UZBLOAD100</code>", parse_mode="HTML")

@dp.message(UserStates.entering_promo)
async def promo_process(message: Message, state: FSMContext):
    code = message.text.strip()
    user_id = message.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT days, activations_left FROM promo_codes WHERE code = ?", (code,)) as cur:
            promo = await cur.fetchone()

        if not promo or promo[1] <= 0:
            await message.answer("❌ Неверный или истекший промокод.")
            await state.clear()
            return

        days, acts = promo[0], promo[1]
        now = datetime.datetime.now()
        async with db.execute("SELECT sub_expires_at FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            curr_exp = row[0] if row else None

        base_time = now
        if curr_exp:
            exp_date = datetime.datetime.fromisoformat(curr_exp)
            if exp_date > now:
                base_time = exp_date

        new_expires = base_time + datetime.timedelta(days=days)
        await db.execute("UPDATE users SET sub_expires_at = ?, notified_1d = 0 WHERE user_id = ?", (new_expires.isoformat(), user_id))
        await db.execute("UPDATE promo_codes SET activations_left = activations_left - 1 WHERE code = ?", (code,))
        await db.commit()

    await message.answer(f"✅ Промокод активирован! Вам добавлено {days} дней подписки.")
    text = await get_profile_text(user_id)
    await message.answer(text, reply_markup=profile_inline_kb(), parse_mode="HTML")
    await state.clear()


# ================= TELEGRAM BUSINESS TRACKING =================
def connect_notice_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⭐ Оплатить подписку", callback_data="buy_sub")]]
    )

@dp.business_connection()
async def on_business_connection(business_connection: types.BusinessConnection):
    owner_id = business_connection.user_chat_id
    try:
        if business_connection.is_enabled:
            active = await has_active_sub(owner_id)
            logging.info(f"Business connection ENABLED for owner_id={owner_id}, has_active_sub={active}")
            await bot.send_message(
                owner_id,
                "✅ Ваш бот подключён на вашем чат управления.",
                reply_markup=connect_notice_kb()
            )
            if not active:
                await bot.send_message(
                    owner_id,
                    "⚠️ У вас нет активной подписки. Бот отслеживает удалённые/изменённые сообщения "
                    "только при оплаченной подписке. Оплатите, чтобы бот начал работать."
                )
        else:
            logging.info(f"Business connection DISABLED for owner_id={owner_id}")
            await bot.send_message(owner_id, "⚠️ Бот отключён от аккаунта, поэтому он больше не сможет отслеживать изменения.")
    except Exception as e:
        logging.error(f"Error notifying business connection change: {e}")


@dp.business_message()
async def track_business_message(message: Message):
    owner_id = await get_subscribed_owner_id(message.business_connection_id, "business_message")
    if owner_id is None:
        return

    file_id = None
    text_content = message.text or message.caption or ""

    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.video:
        file_id = message.video.file_id
    elif message.voice:
        file_id = message.voice.file_id

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT OR REPLACE INTO messages_cache 
            (business_connection_id, message_id, chat_id, from_user_id, from_user_name, from_username, content_type, text_content, file_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            message.business_connection_id,
            message.message_id,
            message.chat.id,
            message.from_user.id,
            message.from_user.full_name,
            message.from_user.username or "",
            message.content_type,
            text_content,
            file_id
        ))
        await db.commit()


@dp.edited_business_message()
async def track_edited_business_message(message: Message):
    owner_id = await get_subscribed_owner_id(message.business_connection_id, "edited_business_message")
    if owner_id is None:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('''
            SELECT text_content FROM messages_cache 
            WHERE business_connection_id = ? AND message_id = ?
        ''', (message.business_connection_id, message.message_id)) as cur:
            old_row = await cur.fetchone()

    old_text = old_row[0] if old_row else "Не найдено"
    new_text = message.text or message.caption or ""

    notify_text = (
        "✏️ <b>Замечено редактирование!</b>\n\n"
        f"<b>Старое:</b> {old_text}\n"
        f"<b>Новое:</b> {new_text}\n\n"
        f"<b>Имя:</b> {message.from_user.full_name} | <b>Юзернейм:</b> @{message.from_user.username or 'yoq'} | <b>ID:</b> <code>{message.from_user.id}</code>"
    )
    
    try:
        await bot.send_message(chat_id=owner_id, text=notify_text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Error sending edit notice: {e}")


@dp.deleted_business_messages()
async def track_deleted_business_messages(event: types.BusinessMessagesDeleted):
    owner_id = await get_subscribed_owner_id(event.business_connection_id, "deleted_business_messages")
    if owner_id is None:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        for msg_id in event.message_ids:
            async with db.execute('''
                SELECT from_user_name, from_username, from_user_id, content_type, text_content, file_id, chat_id 
                FROM messages_cache 
                WHERE business_connection_id = ? AND message_id = ?
            ''', (event.business_connection_id, msg_id)) as cur:
                row = await cur.fetchone()

            if row:
                name, username, uid, c_type, text, file_id, chat_id = row
                report = (
                    "🗑 <b>замечено удаление!</b>\n\n"
                    f'сообщение: "{text if text else "[" + c_type + "]"}"\n\n'
                    f"Имя: {name} | Юзернейм: @{username if username else 'yoq'} | ID: <code>{uid}</code>"
                )
                try:
                    if file_id:
                        if c_type == ContentType.PHOTO:
                            await bot.send_photo(chat_id=owner_id, photo=file_id, caption=report, parse_mode="HTML")
                        elif c_type == ContentType.VIDEO:
                            await bot.send_video(chat_id=owner_id, video=file_id, caption=report, parse_mode="HTML")
                        elif c_type == ContentType.VOICE:
                            await bot.send_voice(chat_id=owner_id, voice=file_id, caption=report, parse_mode="HTML")
                    else:
                        await bot.send_message(chat_id=owner_id, text=report, parse_mode="HTML")
                except Exception as e:
                    logging.error(f"Error notifying delete: {e}")


# ================= ADMIN PANEL =================
@dp.message(Command("admin"))
async def admin_auth(message: Message, state: FSMContext):
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1] == ADMIN_SECRET:
        await message.answer("👑 Admin panelga xush kelibsiz:", reply_markup=admin_panel_kb())
    else:
        await state.set_state(AdminStates.auth)
        await message.answer("🔑 Admin parolini kiriting:")

@dp.message(AdminStates.auth)
async def admin_password_check(message: Message, state: FSMContext):
    if message.text.strip() == ADMIN_SECRET:
        await state.clear()
        await message.answer("👑 Admin panelga xush kelibsiz:", reply_markup=admin_panel_kb())
    else:
        await message.answer("❌ Noto'g'ri parol!")
        await state.clear()

# ---- Foydalanuvchi ko'rish (Ban/Unban/Obuna) ----
@dp.callback_query(F.data == "adm_view_user")
async def adm_view_user_init(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.view_user_id)
    await call.message.edit_text("Foydalanuvchi Telegram ID sini yuboring:")

@dp.message(AdminStates.view_user_id)
async def adm_view_user_show(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("ID faqat sonlardan iborat bo'lishi kerak!")
        return
    await state.clear()
    text, kb = await build_user_view(uid)
    if kb is None:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Admin panel", callback_data="uv_back_to_admin")]])
        await message.answer(text, parse_mode="HTML", reply_markup=back_kb)
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "uv_back_to_admin")
async def uv_back_to_admin(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("👑 Admin panel:", reply_markup=admin_panel_kb())

@dp.callback_query(F.data.startswith("uv_ban_"))
async def uv_ban(call: CallbackQuery):
    uid = int(call.data.split("_")[-1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (uid,))
        await db.commit()
    text, kb = await build_user_view(uid)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await call.answer("🚫 Banlandi")

@dp.callback_query(F.data.startswith("uv_unban_"))
async def uv_unban(call: CallbackQuery):
    uid = int(call.data.split("_")[-1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (uid,))
        await db.commit()
    text, kb = await build_user_view(uid)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await call.answer("✅ Bandan olindi")

@dp.callback_query(F.data.startswith("uv_removesub_"))
async def uv_removesub(call: CallbackQuery):
    uid = int(call.data.split("_")[-1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET sub_expires_at = NULL WHERE user_id = ?", (uid,))
        await db.commit()
    text, kb = await build_user_view(uid)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await call.answer("➖ Obuna olib tashlandi")

@dp.callback_query(F.data.startswith("uv_givesub_"))
async def uv_givesub_init(call: CallbackQuery, state: FSMContext):
    uid = int(call.data.split("_")[-1])
    await state.update_data(view_uid=uid)
    await state.set_state(AdminStates.view_user_give_days)
    await call.message.edit_text(f"ID <code>{uid}</code> uchun necha kunlik obuna berilsin? (Masalan: 30)", parse_mode="HTML")

@dp.message(AdminStates.view_user_give_days)
async def uv_givesub_save(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = data["view_uid"]
    try:
        days = int(message.text.strip())
    except ValueError:
        await message.answer("Kun sonini to'g'ri kiriting!")
        return
    now = datetime.datetime.now()
    new_exp = now + datetime.timedelta(days=days)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET sub_expires_at = ?, notified_1d = 0 WHERE user_id = ?", (new_exp.isoformat(), uid))
        await db.commit()
    await state.clear()
    text, kb = await build_user_view(uid)
    await message.answer(f"✅ ID {uid} ga {days} kunlik obuna berildi.")
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "adm_give_sub")
async def adm_give_sub(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.set_sub_user)
    await call.message.edit_text("Foydalanuvchi Telegram ID sini yuboring:")

@dp.message(AdminStates.set_sub_user)
async def adm_sub_get_user(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        await state.update_data(sub_uid=uid)
        await state.set_state(AdminStates.set_sub_days)
        await message.answer("Tarifni tanlang yoki kun miqdorini yozing (Masalan: 30, 90, 180):")
    except ValueError:
        await message.answer("ID faqat sonlardan iborat bo'lishi kerak!")

@dp.message(AdminStates.set_sub_days)
async def adm_sub_get_days(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = data["sub_uid"]
    try:
        days = int(message.text.strip())
        now = datetime.datetime.now()
        new_exp = now + datetime.timedelta(days=days)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET sub_expires_at = ?, notified_1d = 0 WHERE user_id = ?", (new_exp.isoformat(), uid))
            await db.commit()
        await message.answer(f"✅ ID {uid} ga {days} kunlik obuna berildi.")
        await message.answer("👑 Admin panel:", reply_markup=admin_panel_kb())
        await state.clear()
    except ValueError:
        await message.answer("Kun sonini to'g'ri kiriting!")

@dp.callback_query(F.data == "adm_remove_sub")
async def adm_remove_sub_init(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.remove_sub_user)
    await call.message.edit_text("Foydalanuvchi Telegram ID sini yuboring (Obunani bekor qilish uchun):")

@dp.message(AdminStates.remove_sub_user)
async def adm_remove_sub_proc(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET sub_expires_at = NULL WHERE user_id = ?", (uid,))
            await db.commit()
        await message.answer(f"✅ ID {uid} dan obuna muvaffaqiyatli olib tashlandi.")
        await message.answer("👑 Admin panel:", reply_markup=admin_panel_kb())
        await state.clear()
    except ValueError:
        await message.answer("ID faqat sonlardan iborat bo'lishi kerak!")

@dp.callback_query(F.data == "adm_ban")
async def adm_ban_init(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.ban_user)
    await call.message.edit_text("Ban berish uchun foydalanuvchi ID sini yozing:")

@dp.message(AdminStates.ban_user)
async def adm_ban_proc(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (uid,))
            await db.commit()
        await message.answer(f"🚫 ID {uid} muvaffaqiyatli banlandi.")
        await message.answer("👑 Admin panel:", reply_markup=admin_panel_kb())
        await state.clear()
    except ValueError:
        await message.answer("ID son bo'lishi kerak!")

@dp.callback_query(F.data == "adm_unban")
async def adm_unban_init(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.unban_user)
    await call.message.edit_text("Bandan olish uchun foydalanuvchi ID sini yozing:")

@dp.message(AdminStates.unban_user)
async def adm_unban_proc(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (uid,))
            await db.commit()
        await message.answer(f"✅ ID {uid} bandan olindi.")
        await message.answer("👑 Admin panel:", reply_markup=admin_panel_kb())
        await state.clear()
    except ValueError:
        await message.answer("ID son bo'lishi kerak!")

@dp.callback_query(F.data == "adm_make_promo")
async def adm_promo_step1(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.create_promo_name)
    await call.message.edit_text("Promokod nomini yozing (Masalan: UZBLOAD100):")

@dp.message(AdminStates.create_promo_name)
async def adm_promo_step2(message: Message, state: FSMContext):
    await state.update_data(promo_name=message.text.strip())
    await state.set_state(AdminStates.create_promo_days)
    await message.answer("Promokod necha kunga berilsin? (Masalan: 30):")

@dp.message(AdminStates.create_promo_days)
async def adm_promo_step3(message: Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        await state.update_data(promo_days=days)
        await state.set_state(AdminStates.create_promo_acts)
        await message.answer("Nechta aktivatsiya bo'lsin? (Masalan: 10):")
    except ValueError:
        await message.answer("Faqat son kiriting!")

@dp.message(AdminStates.create_promo_acts)
async def adm_promo_save(message: Message, state: FSMContext):
    data = await state.get_data()
    name = data["promo_name"]
    days = data["promo_days"]
    try:
        acts = int(message.text.strip())
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO promo_codes (code, days, activations_left) VALUES (?, ?, ?)",
                (name, days, acts)
            )
            await db.commit()
        await message.answer(f"✅ Promokod yaratildi:\nKod: <code>{name}</code>\nKun: {days}\nAktivatsiyalar: {acts}", parse_mode="HTML")
        await message.answer("👑 Admin panel:", reply_markup=admin_panel_kb())
        await state.clear()
    except ValueError:
        await message.answer("Faqat son kiriting!")

@dp.callback_query(F.data == "adm_edit_start")
async def adm_edit_start_init(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.edit_start_msg)
    await call.message.edit_text("Yangi Start xabarini yuboring:")

@dp.message(AdminStates.edit_start_msg)
async def adm_edit_start_save(message: Message, state: FSMContext):
    text_to_save = message.html_text or message.text or ""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('start_message', ?)", (text_to_save,))
        await db.commit()
    await message.answer("✅ Start xabari yangilandi.")
    await message.answer("👑 Admin panel:", reply_markup=admin_panel_kb())
    await state.clear()


@dp.callback_query(F.data == "adm_broadcast")
async def adm_broadcast_init(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.broadcast_msg)
    await call.message.edit_text("Barcha foydalanuvchilarga yuboriladigan xabarni (matn, rasm, video) jo'nating:")

@dp.message(AdminStates.broadcast_msg)
async def adm_broadcast_proc(message: Message, state: FSMContext):
    succ = 0
    err = 0
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            rows = await cur.fetchall()
            
    status_msg = await message.answer("⏳ Tarqatish boshlandi, kuting...")
    
    for row in rows:
        uid = row[0]
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
            succ += 1
        except Exception:
            err += 1
        await asyncio.sleep(0.05)
        
    await status_msg.edit_text(f"✅ Xabar barchaga yuborildi!\n\nMuvaffaqiyatli: {succ}\nXatolik/Botni bloklaganlar: {err}")
    await message.answer("👑 Admin panel:", reply_markup=admin_panel_kb())
    await state.clear()


# ================= HEALTH CHECK (RENDER UCHUN) =================
async def health_check(request):
    return web.Response(text="Bot is Live and Running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Health check server running on port {port}")


# ================= RUNNER =================
async def main():
    await start_web_server()  # Portni birinchi navbatda ochamiz, Render tezroq "live" deb bilsin
    await init_db()
    asyncio.create_task(check_subscriptions_task())
    asyncio.create_task(keep_awake_task())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
