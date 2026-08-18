import asyncio
import datetime
import logging
import os
import aiosqlite
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
    KeyboardButton,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
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
    ban_user = State()
    unban_user = State()
    create_promo_name = State()
    create_promo_days = State()
    create_promo_acts = State()
    edit_start_msg = State()


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


# ================= KEYBOARDS =================
def main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="👤 Profil")]],
        resize_keyboard=True
    )


def profile_inline_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Оплатить подписку", callback_data="buy_sub")],
            [
                InlineKeyboardButton(text="👥 Реферальная система", callback_data="ref_system"),
                InlineKeyboardButton(text="🎟 Ввести промокод", callback_data="use_promo"),
            ]
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
            [InlineKeyboardButton(text="➕ Выдать подписку", callback_data="adm_give_sub")],
            [
                InlineKeyboardButton(text="🚫 Бан", callback_data="adm_ban"),
                InlineKeyboardButton(text="✅ Разбан", callback_data="adm_unban"),
            ],
            [InlineKeyboardButton(text="🎟 Создать промокод", callback_data="adm_make_promo")],
            [InlineKeyboardButton(text="✏️ Изменить Start текст", callback_data="adm_edit_start")]
        ]
    )


# ================= USER HANDLERS =================
@dp.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
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
    await message.answer(start_text, reply_markup=main_kb())


@dp.message(F.text == "👤 Profil")
async def profile_menu(message: Message):
    if await is_user_banned(message.from_user.id):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT sub_expires_at FROM users WHERE user_id = ?", (message.from_user.id,)) as cur:
            row = await cur.fetchone()
            sub_status = "Нет активной подписки"
            if row and row[0]:
                exp = datetime.datetime.fromisoformat(row[0])
                if exp > datetime.datetime.now():
                    sub_status = f"Активна до: {exp.strftime('%Y-%m-%d %H:%M')}"

    text = f"👤 <b>Ваш профиль:</b>\n\n🆔 ID: <code>{message.from_user.id}</code>\n💎 Статус подписки: <b>{sub_status}</b>"
    await message.answer(text, reply_markup=profile_inline_kb(), parse_mode="HTML")


@dp.callback_query(F.data == "back_to_profile")
async def back_profile(call: CallbackQuery):
    await call.message.delete()
    await profile_menu(call.message)


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
        description=f"Telegram Business chat bot boshqaruvi ({months} oy uchun)",
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
        await db.execute("UPDATE users SET sub_expires_at = ? WHERE user_id = ?", (new_expires.isoformat(), user_id))

        if referrer_id:
            cut = int(stars_paid * 0.25)
            await db.execute("UPDATE users SET stars_earned = stars_earned + ? WHERE user_id = ?", (cut, referrer_id))
            try:
                await bot.send_message(referrer_id, f"🎉 Ваш реферал оплатил подписку! Вам начислено: {cut} ⭐")
            except Exception:
                pass

        await db.commit()

    await message.answer(f"✅ Оплата прошла успешно! Подписка активна до {new_expires.strftime('%Y-%m-%d %H:%M')}.")


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
        await db.execute("UPDATE users SET sub_expires_at = ? WHERE user_id = ?", (new_expires.isoformat(), user_id))
        await db.execute("UPDATE promo_codes SET activations_left = activations_left - 1 WHERE code = ?", (code,))
        await db.commit()

    await message.answer(f"✅ Промокод активирован! Вам добавлено {days} дней подписки.")
    await state.clear()


# ================= TELEGRAM BUSINESS TRACKING =================
@dp.business_message()
async def track_business_message(message: Message):
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
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('''
            SELECT text_content FROM messages_cache 
            WHERE business_connection_id = ? AND message_id = ?
        ''', (message.business_connection_id, message.message_id)) as cur:
            old_row = await cur.fetchone()

    old_text = old_row[0] if old_row else "Не найдено"
    new_text = message.text or message.caption or ""

    notify_text = (
        f"✏️ <b>Замечено редактирование!</b>\n\n"
        f"<b>Старое:</b> {old_text}\n"
        f"<b>Новое:</b> {new_text}\n\n"
        f"<b>Имя:</b> {message.from_user.full_name} | <b>Юзернейм:</b> @{message.from_user.username or 'yoq'} | <b>ID:</b> <code>{message.from_user.id}</code>"
    )
    try:
        connection = await bot.get_business_connection(message.business_connection_id)
        await bot.send_message(chat_id=connection.user_chat_id, text=notify_text, parse_mode="HTML")
    except Exception:
        pass


@dp.deleted_business_messages()
async def track_deleted_business_messages(event: types.BusinessMessagesDeleted):
    async with aiosqlite.connect(DB_PATH) as db:
        for msg_id in event.message_ids:
            async with db.execute('''
                SELECT from_user_name, from_username, from_user_id, content_type, text_content, file_id 
                FROM messages_cache 
                WHERE business_connection_id = ? AND message_id = ?
            ''', (event.business_connection_id, msg_id)) as cur:
                row = await cur.fetchone()

            if row:
                name, username, uid, c_type, text, file_id = row
                report = (
                    f"🗑 <b>замечено удаление!</b>\n\n"
                    f'сообщение: "{text if text else "[" + c_type + "]"}"\n\n'
                    f"Имя: {name} | Юзернейм: @{username if username else 'yoq'} | ID: <code>{uid}</code>"
                )
                try:
                    conn = await bot.get_business_connection(event.business_connection_id)
                    target_chat = conn.user_chat_id

                    if file_id:
                        if c_type == ContentType.PHOTO:
                            await bot.send_photo(target_chat, photo=file_id, caption=report, parse_mode="HTML")
                        elif c_type == ContentType.VIDEO:
                            await bot.send_video(target_chat, video=file_id, caption=report, parse_mode="HTML")
                        elif c_type == ContentType.VOICE:
                            await bot.send_voice(target_chat, voice=file_id, caption=report, parse_mode="HTML")
                    else:
                        await bot.send_message(target_chat, report, parse_mode="HTML")
                except Exception as e:
                    logging.error(f"Error notifying business delete: {e}")


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
            await db.execute("UPDATE users SET sub_expires_at = ? WHERE user_id = ?", (new_exp.isoformat(), uid))
            await db.commit()
        await message.answer(f"✅ ID {uid} ga {days} kunlik obuna berildi.")
        await state.clear()
    except ValueError:
        await message.answer("Kun sonini to'g'ri kiriting!")


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
        await state.clear()
    except ValueError:
        await message.answer("Faqat son kiriting!")


@dp.callback_query(F.data == "adm_edit_start")
async def adm_edit_start_init(call: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.edit_start_msg)
    await call.message.edit_text("Yangi Start xabarini yuboring:")


@dp.message(AdminStates.edit_start_msg)
async def adm_edit_start_save(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('start_message', ?)", (message.text,))
        await db.commit()
    await message.answer("✅ Start xabari yangilandi.")
    await state.clear()


# ================= RUNNER =================
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
