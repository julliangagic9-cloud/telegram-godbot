import asyncio, sqlite3, json, os, aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

TOKEN = os.getenv("TOKEN")
ADMIN_ID = 6863085411  # mets ton ID Telegram ici

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

# ---------------- DB ----------------
conn = sqlite3.connect("bot.db")
cursor = conn.cursor()
cursor.execute("""CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, expires_at TEXT)""")
cursor.execute("""CREATE TABLE IF NOT EXISTS searches (id INTEGER PRIMARY KEY, user_id INTEGER, data TEXT, created_at TEXT)""")
conn.commit()

# ---------------- FSM ----------------
class Form(StatesGroup):
    waiting = State()

# ---------------- MEMORY ----------------
user_searches = {}
last_use = {}
semaphore = asyncio.Semaphore(5)

# ---------------- UTILS ----------------
def is_authorized(uid):
    cursor.execute("SELECT expires_at FROM users WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    return r and datetime.now() < datetime.fromisoformat(r[0])

def can_use(uid):
    now = datetime.now().timestamp()
    if uid in last_use and now - last_use[uid] < 2:
        return False
    last_use[uid] = now
    return True

def save_search(uid, data):
    cursor.execute("INSERT INTO searches (user_id,data,created_at) VALUES (?,?,?)",
                   (uid, json.dumps(data), datetime.now().isoformat()))
    conn.commit()

def chunk_text(text, n=4000):
    return [text[i:i+n] for i in range(0,len(text),n)]

def validate_email(email):
    return "@" in email and "." in email

def compute_score(user, api):
    score = 0
    if api and user.get("ville","").lower() in api.get("city","").lower(): score += 40
    if api and user.get("cp") == api.get("postcode"): score += 40
    score += 20
    return min(score,100)

# ---------------- API ----------------
async def api_address(data):
    async with semaphore:
        ville = data.get("ville","")
        if not ville: return None
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api-adresse.data.gouv.fr/search/?q={ville}") as r:
                js = await r.json()
                if js["features"]:
                    return js["features"][0]["properties"]
    return None

async def api_genderize(data):
    prenom = data.get("prenom")
    if not prenom: return {}
    async with semaphore:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.genderize.io?name={prenom}") as r:
                js = await r.json()
                return {"genre_api": js.get("gender","")}

async def api_email_verify(data):
    email = data.get("email")
    if not email: return {}
    async with semaphore:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.eva.pingutil.com/email?email={email}") as r:
                js = await r.json()
                valid = js.get("data",{}).get("valid_syntax", False)
                return {"email_valid": valid}

async def enrich(data, api_addr):
    e = {}
    if api_addr:
        e["ville_api"] = api_addr.get("city")
        e["cp_api"] = api_addr.get("postcode")
        e["label_api"] = api_addr.get("label")

    # APIs supplémentaires
    gender = await api_genderize(data)
    email_v = await api_email_verify(data)

    e.update(gender)
    e.update(email_v)

    # fallback genre
    if data.get("prenom") and not e.get("genre_api"):
        e["genre"] = "F" if data["prenom"].endswith("e") else "M"

    return e

# ---------------- UI ----------------
def kb():
    k = InlineKeyboardBuilder()
    for f in ["nom","prenom","ville","tel","email"]:
        k.button(text=f, callback_data=f"f_{f}")
    k.adjust(2)
    k.row(types.InlineKeyboardButton(text="🚀 Run", callback_data="run"))
    k.row(types.InlineKeyboardButton(text="📁 Export", callback_data="export"))
    k.row(types.InlineKeyboardButton(text="🧹 Reset", callback_data="clear"))
    return k.as_markup()

# ---------------- COMMANDS ----------------
@dp.message(Command("start"))
async def start(m: types.Message):
    if not is_authorized(m.from_user.id):
        return await m.answer("🔒 /claim CLE")
    await m.answer("Panel prêt", reply_markup=kb())

@dp.message(Command("claim"))
async def claim(m: types.Message):
    if m.text.endswith("12345"):
        exp = datetime.now()+timedelta(hours=3)
        cursor.execute("INSERT OR REPLACE INTO users VALUES (?,?)",(m.from_user.id,exp.isoformat()))
        conn.commit()
        await m.answer("✅ accès OK")
    else:
        await m.answer("❌ clé invalide")

@dp.message(Command("stats"))
async def stats(m: types.Message):
    if m.from_user.id != ADMIN_ID:
        return
    u = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    s = cursor.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
    await m.answer(f"👤 {u} users\n🔎 {s} recherches")

@dp.message(Command("history"))
async def history(m: types.Message):
    rows = cursor.execute(
        "SELECT data,created_at FROM searches WHERE user_id=? ORDER BY id DESC LIMIT 20",
        (m.from_user.id,)
    ).fetchall()
    for d,t in rows:
        await m.answer(f"{t[:16]}\n{d}")

# ---------------- FLOW ----------------
@dp.callback_query(F.data.startswith("f_"))
async def select(c: types.CallbackQuery, state: FSMContext):
    field = c.data.split("_")[1]
    await state.update_data(field=field)
    await state.set_state(Form.waiting)
    await c.message.answer(f"Entre {field}")
    await c.answer()

@dp.message(Form.waiting)
async def save(m: types.Message, state: FSMContext):
    if not can_use(m.from_user.id):
        return await m.answer("⏳ trop rapide")

    d = await state.get_data()
    f = d.get("field")

    if f == "email" and not validate_email(m.text):
        return await m.answer("❌ email invalide")

    user_searches.setdefault(m.from_user.id,{})
    user_searches[m.from_user.id][f] = m.text

    await state.clear()
    await m.answer("✅", reply_markup=kb())

@dp.callback_query(F.data=="run")
async def run(c: types.CallbackQuery):
    if not can_use(c.from_user.id):
        return await c.answer("⏳", show_alert=True)

    data = user_searches.get(c.from_user.id,{})
    if not data:
        return await c.answer("vide", show_alert=True)

    msg = await c.message.answer("🧠 analyse...")

    api_addr = await api_address(data)
    enrich_data = await enrich(data, api_addr)
    score = compute_score({**data, **enrich_data}, api_addr)

    save_search(c.from_user.id, {**data, **enrich_data})

    res = "📊 RESULTAT\n\n"
    res += "\n".join([f"{k}: {v}" for k,v in {**data, **enrich_data}.items()])
    if api_addr:
        res += f"\n🌍 {api_addr.get('label')}"
    res += f"\n\n🎯 Score: {score}%"

    for part in chunk_text(res):
        await msg.edit_text(part)

    await c.answer()

@dp.callback_query(F.data=="export")
async def export(c: types.CallbackQuery):
    data = user_searches.get(c.from_user.id,{})
    if not data:
        return await c.answer("vide", show_alert=True)

    txt = "\n".join([f"{k}: {v}" for k,v in data.items()])
    file = types.BufferedInputFile(txt.encode(), filename="data.txt")
    await c.message.answer_document(file)
    await c.answer()

@dp.callback_query(F.data=="clear")
async def clear(c: types.CallbackQuery):
    user_searches[c.from_user.id] = {}
    await c.answer("reset")

# ---------------- AUTO SAVE ----------------
async def auto_save():
    while True:
        for uid, data in user_searches.items():
            save_search(uid, data)
        await asyncio.sleep(600)

# ---------------- MAIN ----------------
async def main():
    asyncio.create_task(auto_save())
    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            print("Erreur:", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
