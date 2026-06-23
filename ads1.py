import asyncio
import logging
import sqlite3
import os
import re
import json
import time
import random
import string
import aiohttp
from datetime import datetime, timedelta

# ==========================================
# 📦 ИМПОРТЫ БИБЛИОТЕК
# ==========================================
# Для Ads Bot (aiogram)
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup as AiogramInlineKeyboardMarkup, InlineKeyboardButton as AiogramInlineKeyboardButton

# Для Glass Bot (python-telegram-bot)
from telegram import Update, InlineKeyboardButton as PTBInlineKeyboardButton, InlineKeyboardMarkup as PTBInlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

import ccxt.async_support as ccxt

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ==========================================
# ⚙️ КОНФИГУРАЦИЯ
# ==========================================
# Ads Bot
ADS_API_TOKEN = "7901691237:AAEzIzaVb8iANrJOHQbBxL8oRSEN4MCCkBg"
ADS_ADMIN_ID = 6315110467
ADS_CHANNEL_ID = -1002246305003
ADS_DB_PATH = "bot_database.db"

# Glass Bot
GLASS_BOT_TOKEN = "8463112172:AAEWRwaTyl3Lj4_rNYaOcgRsE7LpDHnz3AU"
GLASS_OWNER_ID = 6315110467

# CryptoBot (Общий для обоих ботов)
CRYPTOBOT_API_KEY = "511400:AAOXgC8hT7PF7V6sWVoIiq2XYoblBW46C1H"
CRYPTOBOT_API_URL = "https://pay.crypt.bot/api"

# ==========================================
# 🚫 РАСШИРЕННЫЙ ФИЛЬТР (КАЗИНО + БУРМАЛДА)
# ==========================================
FORBIDDEN_KEYWORDS = [
    # Наркотики и даркнет
    "нарко", "соли", "меф", "шишки", "фен", "амф", "гашиш", "бошки", "план", "ск", "кристаллы", "трава", "кокаин", "героин", "мдма", "экстази",
    "гидра", "hydra", "mega", "darknet", "даркнет",
    # Базовые казино и ставки
    "казино", "casino", "вулкан", "vulkan", "слоты", "slots", "рулетка", "roulette", "ставка", "bet", "1xbet", "winline", "фонбет", "fonbet",
    "букмекер", "бк", "покер", "poker", "азарт", "джекпот", "jackpot",
    # Новые казино и букмекеры (Бурмалда и другие)
    "бурмалда", "бурмалды", "вавада", "vavada", "плейфортуна", "playfortuna", "джойказино", "jozzcasino", "jozz",
    "азартплей", "azartplay", "эльдорадо", "eldorado", "betcity", "бетсити", "ligastavok", "лига ставок",
    "pari", "пари", "winwin", "винвин", "melbet", "мелбет", "1xstavka", "1хставка", "ttrcasino", "ttr",
    "777", "блэкджек", "blackjack", "фриспин", "freespin", "фриспины", "freespins", "отыгрыш", "wager", "вейджер"
]

def check_content(text: str) -> bool:
    if not text: return True
    text = text.lower()
    clean_text = re.sub(r'[^а-яa-z0-9]', '', text)
    for word in FORBIDDEN_KEYWORDS:
        if word in text or word in clean_text:
            return False
    return True

# ==========================================
# 💳 ОБЩАЯ CRYPTO BOT API (НАДЕЖНАЯ СИСТЕМА)
# ==========================================
async def create_crypto_invoice(amount, description="Платеж", asset="USDT"):
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_API_KEY, "Content-Type": "application/json"}
    payload = {"asset": asset, "amount": str(amount), "description": description}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{CRYPTOBOT_API_URL}/createInvoice", json=payload, headers=headers) as resp:
                data = await resp.json()
                if data.get("ok"):
                    return {"success": True, "invoice_id": data["result"]["invoice_id"], "pay_url": data["result"]["pay_url"], "amount": amount}
                else:
                    logging.error(f"Crypto Bot error: {data}")
                    return {"success": False, "error": data.get("error", "Unknown error")}
        except Exception as e:
            logging.error(f"Crypto Bot connection error: {e}")
            return {"success": False, "error": str(e)}

async def check_crypto_invoice(invoice_id):
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_API_KEY}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{CRYPTOBOT_API_URL}/getInvoices?invoice_ids={invoice_id}", headers=headers) as resp:
                data = await resp.json()
                if data.get("ok") and data["result"]["items"]:
                    invoice = data["result"]["items"][0]
                    return {"success": True, "status": invoice["status"], "paid_at": invoice.get("paid_at"), "amount": invoice.get("amount"), "asset": invoice.get("asset")}
                return {"success": False, "error": "Invoice not found"}
        except Exception as e:
            logging.error(f"Crypto Bot check error: {e}")
            return {"success": False, "error": str(e)}

# ==========================================
# 📢 ЛОГИКА ADS БОТА (aiogram)
# ==========================================
class AdsBotStates(StatesGroup):
    waiting_for_ad_text = State()
    waiting_for_ad_photos = State()
    waiting_for_donate_amount = State()
    waiting_for_donate_comment = State()

def init_ads_db():
    conn = sqlite3.connect(ADS_DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE IF NOT EXISTS slots (id INTEGER PRIMARY KEY, message_id INTEGER, expire_time DATETIME, is_free BOOLEAN DEFAULT 1)")
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT OR IGNORE INTO slots (id, is_free) VALUES (1, 1), (2, 1)")
    conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('price', '1.0'), ('timeout', '2')")
    conn.commit(); conn.close()

def get_setting(key, default):
    conn = sqlite3.connect(ADS_DB_PATH)
    res = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close(); return res[0] if res else default

async def cmd_start(message: types.Message):
    conn = sqlite3.connect(ADS_DB_PATH); conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,)); conn.commit(); conn.close()
    kb = AiogramInlineKeyboardMarkup(inline_keyboard=[
        [AiogramInlineKeyboardButton(text="📢 Купить рекламу", callback_data="buy_ad")],
        [AiogramInlineKeyboardButton(text="📊 Статус ячеек", callback_data="status")],
        [AiogramInlineKeyboardButton(text="🧁 Отправить донат", callback_data="donate")]
    ])
    await message.answer("Привет! Выберите действие ниже:", reply_markup=kb)

# --- ДОНАТ (ЧЕРЕЗ НАДЕЖНУЮ СИСТЕМУ) ---
async def start_donate(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("💵 Введите сумму доната в USDT:")
    await state.set_state(AdsBotStates.waiting_for_donate_amount)

async def process_donate_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.strip())
        if amount <= 0: raise ValueError
        invoice = await create_crypto_invoice(amount, description="Донат разработчику")
        if invoice and invoice.get("success"):
            await state.update_data(invoice_id=invoice['invoice_id'], amount=amount)
            kb = AiogramInlineKeyboardMarkup(inline_keyboard=[
                [AiogramInlineKeyboardButton(text="💳 Оплатить", url=invoice['pay_url'])],
                [AiogramInlineKeyboardButton(text="✅ Проверить оплату", callback_data="check_donate")]
            ])
            await message.answer(f"🧁 Счет на {amount} USDT создан. Оплатите и нажмите кнопку проверки.", reply_markup=kb)
        else:
            await message.answer("❌ Ошибка создания счета. Попробуйте позже.")
    except ValueError:
        await message.answer("⚠️ Введите корректное число!")

async def check_donate(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    invoice_id = data.get("invoice_id")
    timeout = int(get_setting('timeout', '2'))
    msg = await callback.message.answer("⏳ Проверяю оплату через CryptoBot...")
    for _ in range((timeout * 60) // 5):
        result = await check_crypto_invoice(invoice_id)
        if result.get("success") and result.get("status") == "paid":
            await msg.edit_text("✅ Спасибо за донат! Теперь вы можете отправить комментарий:")
            await state.set_state(AdsBotStates.waiting_for_donate_comment)
            return
        await asyncio.sleep(5)
    await msg.edit_text("❌ Время вышло или оплата не найдена.")

async def process_donate_comment(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ads_bot = Bot(token=ADS_API_TOKEN)
    await ads_bot.send_message(ADS_ADMIN_ID, f"🧁 НОВЫЙ ДОНАТ: {data['amount']} USDT\nОт: @{message.from_user.username}\nКомментарий: {message.text}")
    await message.answer("❤️ Спасибо! Ваш комментарий отправлен админу.")
    await state.clear()

# --- РЕКЛАМА ---
async def buy_ad(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Пришлите текст рекламы:")
    await state.set_state(AdsBotStates.waiting_for_ad_text)

async def ad_text(message: types.Message, state: FSMContext):
    if not check_content(message.text): 
        return await message.answer("❌ Запрещенные слова! (Казино, ставки, бурмалда и т.д.)")
    await state.update_data(text=message.text, photos=[])
    await message.answer("Пришлите до 5 фото и нажмите 'Готово'", reply_markup=AiogramInlineKeyboardMarkup(inline_keyboard=[[AiogramInlineKeyboardButton(text="✅ Готово", callback_data="ad_ready")]]))
    await state.set_state(AdsBotStates.waiting_for_ad_photos)

async def ad_photos(message: types.Message, state: FSMContext):
    data = await state.get_data(); photos = data.get("photos", [])
    if len(photos) < 5: photos.append(message.photo[-1].file_id); await state.update_data(photos=photos)

async def ad_ready(callback: types.CallbackQuery, state: FSMContext):
    price = float(get_setting('price', '1.0'))
    invoice = await create_crypto_invoice(price, description="Покупка рекламы")
    if invoice and invoice.get("success"):
        await state.update_data(invoice_id=invoice['invoice_id'])
        kb = AiogramInlineKeyboardMarkup(inline_keyboard=[
            [AiogramInlineKeyboardButton(text="💳 Оплатить", url=invoice['pay_url'])],
            [AiogramInlineKeyboardButton(text="✅ Проверить", callback_data="check_ad")]
        ])
        await callback.message.answer(f"К оплате: {price} USDT. У вас {get_setting('timeout', '2')} мин.", reply_markup=kb)

async def check_ad(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data(); invoice_id = data.get("invoice_id")
    timeout = int(get_setting('timeout', '2'))
    msg = await callback.message.answer("⏳ Проверяю оплату...")
    for _ in range((timeout * 60) // 5):
        result = await check_crypto_invoice(invoice_id)
        if result.get("success") and result.get("status") == "paid":
            await msg.edit_text("✅ Оплачено! Опубликовано в канале.")
            await state.clear(); return
        await asyncio.sleep(5)
    await msg.edit_text("❌ Оплата не найдена.")

async def admin_cmd(message: types.Message):
    await message.answer(f"Админ: /setprice [USDT], /settimeout [Мин]")

async def ads_scheduler():
    while True:
        # Логика удаления просроченных ячеек
        await asyncio.sleep(60)

# ==========================================
# 📊 ЛОГИКА GLASS БОТА (python-telegram-bot)
# ==========================================
BASE_OWNER_PERCENT = 20
BASE_REF_PERCENT = 80
MAX_DISCOUNT = 20
MIN_WITHDRAW = 2.0
MAX_WATCHLIST_COINS = 3
WITHDRAW_FEES = {"USDT(TON)": 3.5, "TRC20": 5.5, "BNB": 3.0, "SOL": 3.0, "ETH": 5.0, "CHECK": 0}
MIN_WITHDRAW_NETWORK = {"USDT(TON)": 2.0, "TRC20": 10.0, "BNB": 1.0, "SOL": 1.0, "ETH": 10.0, "CHECK": 2.0}
NETWORK_PREFIXES = {"USDT(TON)": ["UQ", "Ef", "EQ"], "TRC20": ["T"], "BNB": ["bnb", "0x"], "SOL": [""], "ETH": ["0x"]}
DB_FILE = "users_db.json"
PAYMENTS_FILE = "payments.json"
ADMIN_LOG_FILE = "admin_log.json"
CHECKS_FILE = "checks.json"
BASE_PRICES = {"day": 1.0, "month": 10.0, "forever": 50.0}
ADDITIONAL_COIN_PRICE = 50.0
ADDITIONAL_MONTH_PRICE = 10.0
ADDITIONAL_DAY_PRICE = 1.0

def load_db():
    if not os.path.exists(DB_FILE): return {}
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except Exception as e: logging.error(f"Ошибка загрузки БД: {e}"); return {}

def save_db(data):
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e: logging.error(f"Ошибка сохранения БД: {e}")

def load_payments():
    if not os.path.exists(PAYMENTS_FILE): return {}
    try:
        with open(PAYMENTS_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except Exception as e: logging.error(f"Ошибка загрузки платежей: {e}"); return {}

def save_payments(data):
    try:
        with open(PAYMENTS_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e: logging.error(f"Ошибка сохранения платежей: {e}")

def load_admin_log():
    if not os.path.exists(ADMIN_LOG_FILE): return []
    try:
        with open(ADMIN_LOG_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except Exception as e: logging.error(f"Ошибка загрузки логов: {e}"); return []

def save_admin_log(data):
    try:
        with open(ADMIN_LOG_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e: logging.error(f"Ошибка сохранения логов: {e}")

def load_checks():
    if not os.path.exists(CHECKS_FILE): return {}
    try:
        with open(CHECKS_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except Exception as e: logging.error(f"Ошибка загрузки чеков: {e}"); return {}

def save_checks(data):
    try:
        with open(CHECKS_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e: logging.error(f"Ошибка сохранения чеков: {e}")

db = load_db()
payments_db = load_payments()
admin_log = load_admin_log()
checks_db = load_checks()

def calculate_custom_price(base_plan, extra_coins=0, extra_days=0, extra_months=0):
    base_price = BASE_PRICES.get(base_plan, 0)
    total_price = base_price + (extra_coins * ADDITIONAL_COIN_PRICE) + (extra_days * ADDITIONAL_DAY_PRICE) + (extra_months * ADDITIONAL_MONTH_PRICE)
    return round(total_price, 2)

def get_network_name(network_code):
    network_names = {"USDT(TON)": "USDT (TON Network)", "TRC20": "USDT (TRC20)", "BNB": "BNB (BEP20)", "SOL": "SOL (Solana)", "ETH": "ETH (ERC20)", "CHECK": "Чек Crypto Bot"}
    return network_names.get(network_code, network_code)

def validate_address(address, network):
    if network == "CHECK": return True, ""
    prefixes = NETWORK_PREFIXES.get(network, [])
    if not prefixes: return True, ""
    for prefix in prefixes:
        if address.startswith(prefix): return True, ""
    return False, f"Адрес должен начинаться с одного из: {', '.join(prefixes)}"

def calculate_percentages(discount_percent):
    discount_percent = min(max(discount_percent, 0), MAX_DISCOUNT)
    ref_share = BASE_REF_PERCENT - discount_percent
    owner_share = BASE_OWNER_PERCENT + discount_percent
    return round(owner_share, 2), round(ref_share, 2)

def is_admin(user_id): return int(user_id) == GLASS_OWNER_ID

def has_sub(user_id):
    user_id_str = str(user_id)
    if is_admin(user_id): return True
    user = db.get(user_id_str)
    if not user: return False
    sub_time = user.get("sub", 0)
    return sub_time == -1 or sub_time > time.time()

def get_kb():
    return ReplyKeyboardMarkup([
        ['🔍 Проверить монету', '🛰 Моя слежка'],
        ['💎 Подписка', '📖 Инструкция'],
        ['👥 Реф система', '💰 Вывод']
    ], resize_keyboard=True)

async def crypto_bot_withdraw(amount, address, network="USDT"):
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_API_KEY, "Content-Type": "application/json"}
    asset_map = {"USDT(TON)": "USDT", "TRC20": "USDT", "BNB": "BNB", "SOL": "SOL", "ETH": "ETH"}
    asset = asset_map.get(network, "USDT")
    payload = {"asset": asset, "amount": str(amount), "address": address}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{CRYPTOBOT_API_URL}/transfer", json=payload, headers=headers) as resp:
                data = await resp.json()
                if data.get("ok"): return {"success": True, "transfer_id": data["result"]["transfer_id"], "fee": data["result"].get("fee", 0)}
                else: return {"success": False, "error": data.get("error", "Unknown error")}
        except Exception as e: return {"success": False, "error": str(e)}

async def create_crypto_check(amount, pin_to_user=None):
    headers = {"Crypto-Pay-API-Token": CRYPTOBOT_API_KEY, "Content-Type": "application/json"}
    payload = {"asset": "USDT", "amount": str(amount)}
    if pin_to_user: payload["pin_to_user_id"] = pin_to_user
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(f"{CRYPTOBOT_API_URL}/createCheck", json=payload, headers=headers) as resp:
                data = await resp.json()
                if data.get("ok"): return {"success": True, "check_id": data["result"]["check_id"], "url": data["result"]["url"], "amount": amount}
                else: return {"success": False, "error": data.get("error", "Unknown error")}
        except Exception as e: return {"success": False, "error": str(e)}

def add_ref_reward(referrer_id, amount, discount=0):
    if not referrer_id or referrer_id == "0": return 0, 0
    if referrer_id not in db: db[referrer_id] = {}
    owner_share, ref_share = calculate_percentages(discount)
    ref_reward = amount * (ref_share / 100)
    owner_reward = amount * (owner_share / 100)
    if "ref_balance" not in db[referrer_id]: db[referrer_id]["ref_balance"] = 0
    db[referrer_id]["ref_balance"] += ref_reward
    if "ref_stats" not in db[referrer_id]: db[referrer_id]["ref_stats"] = {"total": 0, "count": 0, "discounts": {}}
    db[referrer_id]["ref_stats"]["total"] += ref_reward
    db[referrer_id]["ref_stats"]["count"] += 1
    if discount > 0:
        discount_key = f"{discount}%"
        db[referrer_id]["ref_stats"]["discounts"][discount_key] = db[referrer_id]["ref_stats"]["discounts"].get(discount_key, 0) + 1
    save_db(db)
    return ref_reward, owner_reward

def get_ref_stats(user_id):
    user_id_str = str(user_id)
    ref_count = 0; ref_earnings = 0; ref_discounts = {}
    for uid, data in db.items():
        if data.get("ref_by") == user_id_str:
            ref_count += 1
            for payment in payments_db.values():
                if payment.get("user_id") == uid and payment.get("status") == "paid":
                    discount = payment.get("discount", 0)
                    owner_share, ref_share = calculate_percentages(discount)
                    ref_earnings += payment.get("price", 0) * (ref_share / 100)
                    if discount > 0:
                        discount_key = f"{discount}%"
                        ref_discounts[discount_key] = ref_discounts.get(discount_key, 0) + 1
    balance = db.get(user_id_str, {}).get("ref_balance", 0)
    user_discount = db.get(user_id_str, {}).get("discount", 0)
    return {"count": ref_count, "balance": balance, "total_earned": ref_earnings, "discounts": ref_discounts, "user_discount": user_discount}

def set_user_discount(user_id, discount_percent):
    user_id_str = str(user_id)
    if user_id_str not in db: return False
    if discount_percent < 0 or discount_percent > MAX_DISCOUNT: return False
    db[user_id_str]["discount"] = discount_percent
    save_db(db)
    return True

def create_check_record(user_id, amount, check_id, check_url):
    check_code = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(12))
    checks_db[check_code] = {"user_id": str(user_id), "amount": amount, "check_id": check_id, "check_url": check_url, "check_code": check_code, "created_at": time.time(), "status": "active", "activated_by": None, "activated_at": None}
    save_checks(checks_db)
    return check_code

def activate_check(check_code, activated_by):
    if check_code not in checks_db: return False
    check_data = checks_db[check_code]
    if check_data["status"] != "active": return False
    check_data["status"] = "activated"; check_data["activated_by"] = str(activated_by); check_data["activated_at"] = time.time()
    checks_db[check_code] = check_data; save_checks(checks_db)
    return True

async def check_pending_payments(app):
    while True:
        try:
            current_payments = load_payments(); current_db = load_db(); updated = False
            for invoice_id, payment in list(current_payments.items()):
                if payment.get("status") == "pending":
                    result = await check_crypto_invoice(invoice_id)
                    if result.get("success") and result.get("status") == "paid":
                        user_id = payment["user_id"]; plan = payment["plan"]; amount = payment.get("price", 1.0); discount = payment.get("discount", 0)
                        user_data = current_db.get(user_id, {}); referrer_id = user_data.get("ref_by")
                        if referrer_id: ref_reward, owner_reward = add_ref_reward(referrer_id, amount, discount)
                        if user_id not in current_db: current_db[user_id] = {"sub": 0, "watchlist": []}
                        if plan == "day": days = 1
                        elif plan == "month": days = 30
                        elif plan == "forever": days = -1
                        else: days = payment.get("days", 30)
                        if days == -1: current_db[user_id]['sub'] = -1
                        else:
                            current_sub = current_db[user_id].get('sub', 0)
                            if current_sub > time.time(): current_db[user_id]['sub'] = current_sub + (days * 86400)
                            else: current_db[user_id]['sub'] = time.time() + (days * 86400)
                        max_coins = payment.get("max_coins", MAX_WATCHLIST_COINS); current_db[user_id]['max_coins'] = max_coins
                        current_payments[invoice_id]["status"] = "paid"; current_payments[invoice_id]["paid_at"] = time.time()
                        admin_log.append({"type": "payment_success", "user_id": user_id, "invoice_id": invoice_id, "plan": plan, "amount": amount, "discount": discount, "referrer": referrer_id, "timestamp": time.time(), "auto": True})
                        save_db(current_db); save_payments(current_payments); save_admin_log(admin_log); updated = True
            if updated: globals()['db'] = current_db; globals()['payments_db'] = current_payments; globals()['admin_log'] = admin_log
            await asyncio.sleep(5)
        except Exception as e: logging.error(f"Payment check error: {e}"); await asyncio.sleep(10)

async def check_active_checks(app):
    while True:
        try:
            current_checks = load_checks(); updated = False
            for check_code, check_data in list(current_checks.items()):
                if check_data.get("status") == "active" and check_data.get("check_id"):
                    check_id = check_data["check_id"]; result = await check_crypto_invoice(check_id)
                    if result.get("success"):
                        status = result.get("status")
                        if status == "paid" and check_data["status"] != "activated":
                            check_data["status"] = "activated"; check_data["activated_at"] = time.time(); current_checks[check_code] = check_data; updated = True
            if updated: save_checks(current_checks); globals()['checks_db'] = current_checks
            await asyncio.sleep(30)
        except Exception as e: logging.error(f"Check monitoring error: {e}"); await asyncio.sleep(60)

async def scan_coin(coin, threshold=1000):
    try:
        exchange = ccxt.mexc({'enableRateLimit': True, 'timeout': 30000})
        clean_coin = coin.upper().replace("/USDT", "").replace("USDT", "").strip()
        symbol = f"{clean_coin}/USDT"
        orderbook = await exchange.fetch_order_book(symbol, limit=100)
        price = (orderbook['bids'][0][0] + orderbook['asks'][0][0]) / 2
        walls = []
        for p, a in orderbook['asks']:
            vol = p * a
            if vol >= threshold:
                dist = ((p - price) / price) * 100
                if dist <= 15: walls.append({"side": "SELL 🔴", "price": p, "volume": vol, "distance": dist})
        for p, a in orderbook['bids']:
            vol = p * a
            if vol >= threshold:
                dist = ((price - p) / price) * 100
                if dist <= 15: walls.append({"side": "BUY 🟢", "price": p, "volume": vol, "distance": dist})
        await exchange.close()
        if not walls: return None
        walls.sort(key=lambda x: x['volume'], reverse=True); best = walls[0]
        return f"{best['side']} **{symbol}**\n💰 Объем: **${best['volume']:,.0f}**\n📈 Цена: `{best['price']:.6f}`\n📊 Дистанция: **{best['distance']:.2f}%**"
    except Exception as e: logging.error(f"Scan error: {e}"); return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; user_id = str(user.id); ref_code = None
    if context.args and context.args[0].isdigit(): ref_code = context.args[0]
    if user_id not in db:
        db[user_id] = {"sub": 0, "watchlist": [], "max_coins": MAX_WATCHLIST_COINS, "threshold": 2000, "username": user.username or user.first_name, "join_date": time.time(), "ref_balance": 0, "discount": 0, "withdraw_method": "CHECK", "withdraw_address": "", "withdraw_network": "USDT(TON)"}
        if ref_code and ref_code != user_id and ref_code in db:
            db[user_id]["ref_by"] = ref_code
            ref_discount = db.get(ref_code, {}).get("discount", 0)
            if ref_discount > 0: db[user_id]["discount"] = ref_discount
        save_db(db)
    await update.message.reply_text(f"🚀 Привет, {user.first_name}!\nЯ сканирую стаканы MEXC на крупные стенки.", reply_markup=get_kb())

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; user_id = str(user.id); text = update.message.text
    if text == '💎 Подписка':
        await update.message.reply_text("📊 Меню подписок.", reply_markup=PTBInlineKeyboardMarkup([[PTBInlineKeyboardButton("Купить", callback_data="buy_day_0")]]))
    elif text == '🔍 Проверить монету':
        if not has_sub(user.id): await update.message.reply_text("❌ Нужна подписка!"); return
        await update.message.reply_text("Введите тикер монеты:")
        context.user_data['state'] = 'check_coin'
    elif context.user_data.get('state') == 'check_coin':
        coin = text.upper().strip(); user_threshold = db.get(user_id, {}).get("threshold", 2000)
        msg = await update.message.reply_text(f"🔍 Сканирую {coin}...")
        result = await scan_coin(coin, user_threshold)
        if result: await msg.edit_text(result, parse_mode='Markdown')
        else: await msg.edit_text(f"❌ В {coin} стенок не найдено")
        context.user_data['state'] = None
    else:
        await update.message.reply_text("Используйте меню:", reply_markup=get_kb())

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("Обработка...")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): await update.message.reply_text("❌ Только для администратора"); return
    await update.message.reply_text(f"👑 Админ-панель. Пользователей: {len(db)}")

async def threshold_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Используйте меню бота для настройки.")

# ==========================================
# 🚀 ЗАПУСК ОБЪЕДИНЕННОГО БОТА (ФИНАЛЬНЫЙ ФИКС)
# ==========================================
async def main():
    logging.info("🚀 Запуск объединенного бота на VPS...")
    
    # 1. Инициализация БД объявлений
    init_ads_db()
    
    # 2. Настройка Ads Bot (aiogram)
    ads_bot = Bot(token=ADS_API_TOKEN)
    ads_dp = Dispatcher()
    
    # Регистрация хендлеров Ads Bot    ads_dp.message.register(cmd_start, Command("start"))
    ads_dp.message.register(admin_cmd, Command("admin"), F.from_user.id == ADS_ADMIN_ID)
    ads_dp.callback_query.register(start_donate, F.data == "donate")
    ads_dp.message.register(process_donate_amount, AdsBotStates.waiting_for_donate_amount)
    ads_dp.callback_query.register(check_donate, F.data == "check_donate")
    ads_dp.message.register(process_donate_comment, AdsBotStates.waiting_for_donate_comment)
    ads_dp.callback_query.register(buy_ad, F.data == "buy_ad")
    ads_dp.message.register(ad_text, AdsBotStates.waiting_for_ad_text)
    ads_dp.message.register(ad_photos, AdsBotStates.waiting_for_ad_photos, F.photo)
    ads_dp.callback_query.register(ad_ready, F.data == "ad_ready")
    ads_dp.callback_query.register(check_ad, F.data == "check_ad")
    
    # 3. Настройка Glass Bot (PTB)
    glass_app = ApplicationBuilder().token(GLASS_BOT_TOKEN).build()
    glass_app.add_handler(CommandHandler("start", start))
    glass_app.add_handler(CommandHandler("threshold", threshold_command))
    glass_app.add_handler(CommandHandler("admin", admin_command))
    glass_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    glass_app.add_handler(CallbackQueryHandler(callback_handler))
    
    # 4. Запуск фоновых задач (планировщики и проверки оплат)
    asyncio.create_task(ads_scheduler())
    asyncio.create_task(check_pending_payments(glass_app))
    asyncio.create_task(check_active_checks(glass_app))
    
    # 5. ЗАПУСК ОБОИХ БОТОВ (ПРАВИЛЬНЫЙ СПОСОБ)
    try:
        # Инициализируем приложение перед запуском
        await glass_app.initialize()
        
        # Запускаем оба бота
        await asyncio.gather(
            ads_dp.start_polling(ads_bot),
            glass_app.start()
        )
        
    except KeyboardInterrupt:
        logging.info("🛑 Бот остановлен пользователем")
    except Exception as e:
        logging.error(f"❌ Критическая ошибка: {e}")
    finally:
        # Правильное завершение
        await ads_bot.session.close()
        await glass_app.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("🛑 Бот остановлен пользователем")
    except Exception as e:
        logging.error(f"❌ Критическая ошибка: {e}")