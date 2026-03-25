import asyncio
import sqlite3
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# --- CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
ADMIN_ID = 6863085411  # Ton ID Admin (Jullian)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher(storage=MemoryStorage())

# --- DATABASE ---
conn = sqlite3.connect("bot.db")
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, expires_at TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS blacklist (user_id INTEGER PRIMARY KEY)")
conn.commit()

# --- FSM STATES ---
class SearchState(StatesGroup):
    waiting_value = State()

# --- LOGIQUE DE VALIDATION & NETTOYAGE ---
def validate_and_clean(field: str, value: str):
    val = value.strip()
    if field == "nom": return val.upper(), None
    if field == "prenom": return val.capitalize(), None
    if field == "annee":
        if not val.isdigit() or len(val) != 4: return None, "⚠️ Année invalide (ex: 1995)."
        year = int(val)
        if year < 1920 or year > datetime.now().year: return None, "⚠️ Année hors limites."
        return val, None
    if field == "email":
        if "@" not in val or "." not in val: return None, "⚠️ Email invalide."
        return val.lower(), None
    if field == "tel":
        clean_tel = "".join(filter(str.isdigit, val))
        return (clean_tel, None) if len(clean_tel) >= 10 else (None, "⚠️ Numéro trop court.")
    if field == "cp":
        return (val, None) if (val.isdigit() and len(val) == 5) else (None, "⚠️ CP à 5 chiffres.")
    return val, None

# --- UTILS ---
def is_authorized(uid):
    # L'admin est toujours autorisé
    if uid == ADMIN_ID:
        return True
    
    # Vérifier si banni
    cursor.execute("SELECT 1 FROM blacklist WHERE user_id=?", (uid,))
    if cursor.fetchone():
        return False

    # Vérifier l'abonnement
    cursor.execute("SELECT expires_at FROM users WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    return r and datetime.now() < datetime.fromisoformat(r[0])

def get_kb_panel(data: dict):
    builder = InlineKeyboardBuilder()
    fields = [("nom", "👤 Nom"), ("prenom", "📝 Prénom"), ("annee", "🎂 Année"), 
              ("adresse", "🏠 Adresse"), ("cp", "📮 CP"), ("ville", "🏙️ Ville"), 
              ("email", "📧 Email"), ("tel", "📱 Tél")]
    for key, label in fields:
        status = " ✅" if data.get(key) else ""
        builder.button(text=f"{label}{status}", callback_data=f"f_{key}")
    builder.adjust(2)
    builder.row(types.InlineKeyboardButton(text="🚀 Lancer recherche", callback_data="run"))
    builder.row(types.InlineKeyboardButton(text="🧹 Effacer", callback_data="clear"))
    return builder.as_markup()

# --- HANDLERS ---

@dp.message(Command("start"))
async def cmd_start(m: types.Message, state: FSMContext):
    if not is_authorized(m.from_user.id):
        return await m.answer("🔒 **Accès refusé** ou compte banni.")
    
    data = await state.get_data()
    params = data.get("search_params", {})
    welcome_text = "👋 **Bienvenue Maître**" if m.from_user.id == ADMIN_ID else f"🔍 **PANEL RECHERCHE**"
    await m.answer(f"{welcome_text}\nID: `{m.from_user.id}`", reply_markup=get_kb_panel(params))

@dp.callback_query(F.data.startswith("f_"))
async def ask_field(c: types.CallbackQuery, state: FSMContext):
    field = c.data.split("_")[1]
    await state.update_data(editing_field=field)
    await state.set_state(SearchState.waiting_value)
    await c.message.edit_text(f"⌨️ Valeur pour : **{field.upper()}**")

@dp.message(SearchState.waiting_value)
async def process_input(m: types.Message, state: FSMContext):
    user_data = await state.get_data()
    field = user_data.get("editing_field")
    cleaned_val, error = validate_and_clean(field, m.text)
    if error: return await m.answer(error)

    params = user_data.get("search_params", {})
    params[field] = cleaned_val
    await state.update_data(search_params=params)
    await state.set_state(None)
    await m.answer(f"✅ Enregistré.", reply_markup=get_kb_panel(params))

@dp.callback_query(F.data == "run")
async def run_search(c: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    params = data.get("search_params", {})
    if not params: return await c.answer("❌ Vide !", show_alert=True)

    # Log pour l'admin
    log_text = f"🔔 **LOG RECHERCHE**\n👤 De: {c.from_user.full_name} (`{c.from_user.id}`)\n\n"
    for k, v in params.items(): log_text += f"• {k.upper()}: `{v}`\n"
    await bot.send_message(ADMIN_ID, log_text)

    await c.message.answer("⚙️ Recherche en cours...")
    await asyncio.sleep(1)
    await c.message.answer("✅ **Recherche terminée.**\nLes résultats ont été envoyés à l'admin.")
    await c.answer()

@dp.callback_query(F.data == "clear")
async def clear_data(c: types.CallbackQuery, state: FSMContext):
    await state.update_data(search_params={})
    await c.message.edit_text("🧹 Données effacées.", reply_markup=get_kb_panel({}))

# --- COMMANDES ADMIN ---

@dp.message(Command("ban"))
async def cmd_ban(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        target_id = m.text.split()[1]
        cursor.execute("INSERT OR IGNORE INTO blacklist VALUES (?)", (target_id,))
        conn.commit()
        await m.answer(f"🚫 ID `{target_id}` a été banni.")
    except:
        await m.answer("Usage: `/ban ID`")

@dp.message(Command("unban"))
async def cmd_unban(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        target_id = m.text.split()[1]
        cursor.execute("DELETE FROM blacklist WHERE user_id=?", (target_id,))
        conn.commit()
        await m.answer(f"✅ ID `{target_id}` a été débanni.")
    except:
        await m.answer("Usage: `/unban ID`")

@dp.message(Command("add"))
async def cmd_add(m: types.Message):
    if m.from_user.id != ADMIN_ID: return
    try:
        _, target_id, days = m.text.split()
        exp = (datetime.now() + timedelta(days=int(days))).isoformat()
        cursor.execute("INSERT OR REPLACE INTO users VALUES (?,?)", (target_id, exp))
        conn.commit()
        await m.answer(f"✅ Accès accordé à `{target_id}` pour {days} jours.")
    except:
        await m.answer("Usage: `/add ID JOURS`")

async def main():
    print("🚀 Bot démarré. Accès Admin direct activé.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
