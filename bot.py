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
ADMIN_ID = 6863085411 

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher(storage=MemoryStorage())

# --- DATABASE (Synchrone pour l'exemple, aiosqlite recommandé en prod) ---
conn = sqlite3.connect("bot.db")
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, expires_at TEXT)")
conn.commit()

# --- FSM STATES ---
class SearchState(StatesGroup):
    waiting_value = State()

# --- UTILS ---
def is_authorized(uid):
    cursor.execute("SELECT expires_at FROM users WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    return r and datetime.now() < datetime.fromisoformat(r[0])

def get_kb_panel(data: dict):
    builder = InlineKeyboardBuilder()
    
    # Configuration des champs : (ID, Label)
    fields = [
        ("nom", "👤 Nom"), ("prenom", "📝 Prénom"),
        ("annee", "🎂 Année"), ("adresse", "🏠 Adresse"),
        ("cp", "📮 Code postal"), ("ville", "🏙️ Ville"),
        ("email", "📧 Email"), ("tel", "📱 Téléphone")
    ]
    
    for key, label in fields:
        # Ajoute une coche si la donnée existe dans le dictionnaire 'data'
        status = " ✅" if data.get(key) else ""
        builder.button(text=f"{label}{status}", callback_data=f"f_{key}")
    
    builder.adjust(2)
    builder.row(types.InlineKeyboardButton(text="🚀 Lancer recherche", callback_data="run"))
    builder.row(types.InlineKeyboardButton(text="🧹 Effacer", callback_data="clear"))
    builder.row(
        types.InlineKeyboardButton(text="👤 Compte", callback_data="account"),
        types.InlineKeyboardButton(text="🛒 Boutique", callback_data="shop")
    )
    return builder.as_markup()

# --- HANDLERS ---

@dp.message(Command("start"))
async def cmd_start(m: types.Message, state: FSMContext):
    if not is_authorized(m.from_user.id):
        return await m.answer("🔒 **Accès refusé**\n\nActive une clé avec `/claim`.")
    
    # Récupérer les données actuelles du FSM (si elles existent)
    user_data = await state.get_data()
    search_params = user_data.get("search_params", {})
    
    await m.answer(
        f"🔍 **PANEL RECHERCHE | CIVIL**\n\n👤 **Utilisateur :** {m.from_user.full_name}\n🆔 **ID :** `{m.from_user.id}`\n\n**Choisis un champ à remplir :**",
        reply_markup=get_kb_panel(search_params)
    )

@dp.callback_query(F.data.startswith("f_"))
async def ask_field_value(c: types.CallbackQuery, state: FSMContext):
    field = c.data.split("_")[1]
    await state.update_data(editing_field=field) # On stocke quel champ on modifie
    await state.set_state(SearchState.waiting_value)
    
    await c.message.edit_text(f"⌨️ Envoie la valeur pour le champ : **{field.upper()}**")
    await c.answer()

@dp.message(SearchState.waiting_value)
async def receive_field_value(m: types.Message, state: FSMContext):
    user_data = await state.get_data()
    field = user_data.get("editing_field")
    
    # On récupère le dictionnaire des paramètres ou on en crée un
    search_params = user_data.get("search_params", {})
    search_params[field] = m.text
    
    # Mise à jour du FSM
    await state.update_data(search_params=search_params)
    await state.set_state(None) # On libère l'état pour pouvoir cliquer sur d'autres boutons
    
    await m.answer(
        f"✅ **{field.capitalize()}** enregistré : `{m.text}`",
        reply_markup=get_kb_panel(search_params)
    )

@dp.callback_query(F.data == "run")
async def run_search(c: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    params = user_data.get("search_params", {})
    
    if not params:
        return await c.answer("❌ Aucun champ rempli !", show_alert=True)

    msg = await c.message.answer("⚙️ **Interrogation des bases de données...**")
    await asyncio.sleep(2) # Simulation de charge
    
    results = "━━━━━━━━━━━━━━━━━━━━━\n📊 **RÉSULTATS OSINT**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    for k, v in params.items():
        results += f"• **{k.upper()}** : `{v}`\n"
    
    results += "\n✅ Recherche terminée."
    
    await msg.edit_text(results)
    await c.answer()

@dp.callback_query(F.data == "clear")
async def clear_search(c: types.CallbackQuery, state: FSMContext):
    await state.update_data(search_params={}) # Réinitialise les données
    await c.message.edit_text(
        "🧹 Données effacées. Prêt pour une nouvelle recherche.",
        reply_markup=get_kb_panel({})
    )
    await c.answer()

@dp.message(Command("claim"))
async def cmd_claim(m: types.Message):
    # Exemple : /claim TEST-123
    if "TEST" in m.text.upper():
        exp = (datetime.now() + timedelta(days=30)).isoformat()
        cursor.execute("INSERT OR REPLACE INTO users VALUES (?,?)", (m.from_user.id, exp))
        conn.commit()
        await m.answer("✅ Accès Premium activé pour 30 jours !")
    else:
        await m.answer("❌ Clé invalide.")

# --- MAIN ---
async def main():
    print("🚀 Bot OSINT démarré...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
