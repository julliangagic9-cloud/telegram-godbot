import asyncio, sqlite3, json, os, aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# --- CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
ADMIN_ID = 6863085411 

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

# --- DATABASE ---
conn = sqlite3.connect("bot.db")
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, expires_at TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS searches (id INTEGER PRIMARY KEY, user_id INTEGER, data TEXT, created_at TEXT)")
conn.commit()

# --- FSM & MEMORY ---
class Form(StatesGroup):
    waiting_input = State()

user_searches = {}
semaphore = asyncio.Semaphore(5)

# --- UTILS ---
def is_authorized(uid):
    cursor.execute("SELECT expires_at FROM users WHERE user_id=?", (uid,))
    r = cursor.fetchone()
    return r and datetime.now() < datetime.fromisoformat(r[0])

def get_panel_text(m: types.Message, data: dict):
    """Génère le texte du panel avec les champs remplis ou vides"""
    text = (
        "🔍 **PANEL RECHERCHE | CIVIL**\n\n"
        f"👤 **Utilisateur :** {m.from_user.full_name}\n"
        f"🆔 **ID :** `{m.from_user.id}`\n\n"
        "**Choisis un champ** 👇"
    )
    return text

def kb_main():
    builder = InlineKeyboardBuilder()
    buttons = [
        ("👤 Nom", "f_nom"), ("📝 Prénom", "f_prenom"),
        ("🎂 Année", "f_annee"), ("🏠 Adresse", "f_adresse"),
        ("📮 Code postal", "f_cp"), ("🏙️ Ville", "f_ville"),
        ("📧 Email", "f_email"), ("📱 Téléphone", "f_tel")
    ]
    for text, data in buttons:
        builder.button(text=text, callback_data=data)
    builder.adjust(2)
    builder.row(types.InlineKeyboardButton(text="🔄 Civil / Network", callback_data="switch"))
    builder.row(types.InlineKeyboardButton(text="🚀 Lancer recherche", callback_data="run"))
    builder.row(types.InlineKeyboardButton(text="🧹 Effacer", callback_data="clear"))
    builder.row(
        types.InlineKeyboardButton(text="👤 Compte", callback_data="account"),
        types.InlineKeyboardButton(text="🛒 Boutique", callback_data="shop")
    )
    return builder.as_markup()

# --- HANDLERS ---
@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    if not is_authorized(m.from_user.id):
        return await m.answer("🔒 **Accès refusé**\n\nActive une clé avec :\n`/claim TA_CLE`")
    
    user_searches.setdefault(m.from_user.id, {})
    await m.answer(get_panel_text(m, user_searches[m.from_user.id]), reply_markup=kb_main())

@dp.message(Command("claim"))
async def cmd_claim(m: types.Message):
    # Logique simplifiée pour l'exemple
    if "2RUDOFLQJG4IN" in m.text:
        exp = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
        cursor.execute("INSERT OR REPLACE INTO users VALUES (?,?)", (m.from_user.id, exp))
        conn.commit()
        await m.answer(f"✅ **Accès activé jusqu'au {exp.replace('T', ' ')}**")
    else:
        await m.answer("❌ Clé invalide.")

@dp.callback_query(F.data.startswith("f_"))
async def prompt_input(c: types.CallbackQuery, state: FSMContext):
    field = c.data.split("_")[1]
    await state.update_data(current_field=field)
    await state.set_state(Form.waiting_input)
    await c.message.answer(f"⌨️ Envoie la valeur pour : **{field}**")
    await c.answer()

@dp.message(Form.waiting_input)
async def process_input(m: types.Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("current_field")
    
    user_searches.setdefault(m.from_user.id, {})
    user_searches[m.from_user.id][field] = m.text
    
    await state.clear()
    await m.answer(f"✅ **{field}** enregistré.", reply_markup=kb_main())

@dp.callback_query(F.data == "run")
async def run_search(c: types.CallbackQuery):
    data = user_searches.get(c.from_user.id, {})
    if not data:
        return await c.answer("❌ Aucun champ rempli !", show_alert=True)

    loading = await c.message.answer("⚙️ **Recherche en cours...**")
    await asyncio.sleep(1.5) # Simulation

    res = (
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 **RESULTATS OSINT**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👤 **ÉTAT CIVIL**\n"
        f"• Nom : {data.get('nom', 'N/A')}\n"
        f"• Prénom : {data.get('prenom', 'N/A')}\n"
        f"• Année : {data.get('annee', 'N/A')}\n\n"
        "📞 **CONTACT**\n"
        f"• Tel : {data.get('tel', 'N/A')}\n"
        f"• Email : {data.get('email', 'N/A')}\n\n"
        "🏠 **ADRESSE**\n"
        f"• Ville : {data.get('ville', 'N/A')}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📄 Page 1/1"
    )
    
    # Boutons sous le résultat (comme sur l'image)
    res_kb = InlineKeyboardBuilder()
    res_kb.button(text="📋 Copier", callback_data="copy")
    res_kb.button(text="📩 Exporter", callback_data="export")
    
    await loading.edit_text(res, reply_markup=res_kb.as_markup())
    await c.answer()

@dp.callback_query(F.data == "clear")
async def clear_data(c: types.CallbackQuery):
    user_searches[c.from_user.id] = {}
    await c.answer("🧹 Données effacées")
    await c.message.edit_text(get_panel_text(c.message, {}), reply_markup=kb_main())

# --- MAIN ---
async def main():
    print("Bot démarré...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
        pdf.cell(50, 10, f" {key.upper()}", border=1, fill=True)
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 10, f" {value}", border=1, ln=True)
    return pdf.output()

# --- INTERFACE (UI) ---
def kb_main():
    builder = InlineKeyboardBuilder()
    buttons = [
        ("👤 Nom", "f_nom"), ("📝 Prénom", "f_prenom"),
        ("🎂 Année", "f_annee"), ("🏠 Adresse", "f_adresse"),
        ("📮 CP", "f_cp"), ("🏙️ Ville", "f_ville"),
        ("📧 Email", "f_email"), ("📱 Téléphone", "f_tel")
    ]
    for text, data in buttons:
        builder.button(text=text, callback_data=data)
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
async def cmd_start(m: types.Message):
    if not is_authorized(m.from_user.id):
        return await m.answer("🔒 **Accès refusé**\n\nActive une clé avec :\n`/claim TA_CLE`")
    
    text = (
        "🔍 **PANEL RECHERCHE | CIVIL**\n\n"
        f"👤 **Utilisateur :** {m.from_user.full_name}\n"
        f"🆔 **ID :** `{m.from_user.id}`\n\n"
        "**Choisis un champ pour le remplir** 👇"
    )
    await m.answer(text, reply_markup=kb_main())

@dp.message(Command("claim"))
async def cmd_claim(m: types.Message):
    if "2RUDOFLQJG4IN" in m.text: # Clé de test
        exp = (datetime.now() + timedelta(days=30)).isoformat()
        cursor.execute("INSERT OR REPLACE INTO users VALUES (?,?)", (m.from_user.id, exp))
        conn.commit()
        await m.answer("✅ **Accès activé pour 30 jours !**")
    else:
        await m.answer("❌ Clé invalide.")

@dp.callback_query(F.data.startswith("f_"))
async def prompt_input(c: types.CallbackQuery, state: FSMContext):
    field = c.data.split("_")[1]
    await state.update_data(current_field=field)
    await state.set_state(Form.waiting_input)
    await c.message.answer(f"⌨️ Envoie la valeur pour : **{field}**")
    await c.answer()

@dp.message(Form.waiting_input)
async def process_input(m: types.Message, state: FSMContext):
    fsm_data = await state.get_data()
    field = fsm_data.get("current_field")
    
    current_data = load_draft(m.from_user.id)
    current_data[field] = m.text
    save_draft(m.from_user.id, current_data)
    
    await state.clear()
    await m.answer(f"✅ Valeur ajoutée au dossier.", reply_markup=kb_main())

@dp.callback_query(F.data == "run")
async def run_search(c: types.CallbackQuery):
    data = load_draft(c.from_user.id)
    if not data:
        return await c.answer("❌ Le dossier est vide !", show_alert=True)

    res = "━━━━━━━━━━━━━━━━━━━━━\n📊 **CONTENU DU DOSSIER**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    for k, v in data.items():
        res += f"• **{k.capitalize()}** : {v}\n"
    res += "\n━━━━━━━━━━━━━━━━━━━━━\n📄 Page 1/1"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📩 Exporter PDF/TXT", callback_data="export")
    await c.message.answer(res, reply_markup=builder.as_markup())
    await c.answer()

@dp.callback_query(F.data == "export")
async def export_files(c: types.CallbackQuery):
    data = load_draft(c.from_user.id)
    if not data: return await c.answer("Vide")

    # TXT
    txt_content = "\n".join([f"{k.upper()}: {v}" for k, v in data.items()])
    txt_file = types.BufferedInputFile(txt_content.encode(), filename="rapport.txt")
    
    # PDF
    pdf_bytes = generate_pdf_report(c.from_user.id, data)
    pdf_file = types.BufferedInputFile(pdf_bytes, filename="rapport_officiel.pdf")

    await c.message.answer_document(txt_file, caption="📄 Rapport Brut (.txt)")
    await c.message.answer_document(pdf_file, caption="📕 Rapport Formate (.pdf)")
    await c.answer()

@dp.callback_query(F.data == "clear")
async def clear_data(c: types.CallbackQuery):
    clear_draft(c.from_user.id)
    await c.answer("🧹 Dossier vidé.")
    await c.message.answer("Le dossier a été réinitialisé.", reply_markup=kb_main())

async def main():
    print("Bot en ligne...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
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
