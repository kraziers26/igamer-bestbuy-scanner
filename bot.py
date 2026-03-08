import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters, ConversationHandler
)
from excel_parser import parse_excel
from bestbuy_scanner import BestBuyScanner
from report_builder import build_report

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
BESTBUY_API_KEY = os.environ.get("BESTBUY_API_KEY")

# Conversation states
STEP_BRANDS, STEP_CATEGORIES, STEP_MODE, STEP_SAVINGS, STEP_DOLLAR, STEP_CONFIRM = range(6)

PREFERRED_BRANDS = ["Dell", "HP", "Lenovo", "Apple", "Acer", "ASUS", "MSI"]

# All possible categories from your Excel — normalized for display
ALL_CATEGORIES = [
    "GAMING Laptop",
    "Laptop",
    "2-in-1 Laptop",
    "Dual Screen",
    "Desktop",
    "All-in-One Desktop",
    "Gaming Desktop",
    "Consoles",
    "Other",
]

# Map display categories to keywords that appear in your Excel category column
CATEGORY_KEYWORDS = {
    "GAMING Laptop":     ["gaming"],
    "Laptop":            ["laptop"],
    "2-in-1 Laptop":     ["2-in-1", "2 in 1"],
    "Dual Screen":       ["dual screen"],
    "Desktop":           ["desktop"],
    "All-in-One Desktop":["all in one", "all-in-one"],
    "Gaming Desktop":    ["gaming desktop"],
    "Consoles":          ["consoles", "console"],
    "Other":             [],  # catch-all
}

scanner = BestBuyScanner(BESTBUY_API_KEY)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_categories_in_inventory(inventory: list[dict]) -> list[str]:
    """Return only categories that actually exist in the loaded inventory."""
    found = set()
    for p in inventory:
        cat = p.get("category", "").strip().lower()
        matched = False
        for display_cat, keywords in CATEGORY_KEYWORDS.items():
            if display_cat == "Other":
                continue
            for kw in keywords:
                if kw in cat:
                    found.add(display_cat)
                    matched = True
                    break
            if matched:
                break
        if not matched and cat:
            found.add("Other")
    # Return in defined order
    return [c for c in ALL_CATEGORIES if c in found]

def filter_inventory(inventory, brands, categories):
    """Filter inventory by selected brands AND categories."""
    brands_lower = [b.lower() for b in brands]
    result = []
    for p in inventory:
        # Brand filter
        if p.get("brand", "").lower() not in brands_lower:
            continue
        # Category filter
        cat = p.get("category", "").strip().lower()
        cat_match = False
        for display_cat in categories:
            if display_cat == "Other":
                # Other = anything not matched by known keywords
                known = False
                for dc, kws in CATEGORY_KEYWORDS.items():
                    if dc == "Other":
                        continue
                    for kw in kws:
                        if kw in cat:
                            known = True
                            break
                if not known:
                    cat_match = True
                    break
            else:
                for kw in CATEGORY_KEYWORDS.get(display_cat, []):
                    if kw in cat:
                        cat_match = True
                        break
            if cat_match:
                break
        if cat_match:
            result.append(p)
    return result


# ─── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to *iGamer Best Buy Scanner*\n\n"
        "📤 Upload your Excel price list to scan Best Buy for restock opportunities.\n\n"
        "Commands:\n"
        "/scan — Re-run scan on last uploaded Excel\n"
        "/status — Show loaded inventory info\n"
        "/help — How to use this bot\n"
        "/cancel — Cancel current scan",
        parse_mode="Markdown"
    )

# ─── /help ────────────────────────────────────────────────────────────────────

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How to use this bot:*\n\n"
        "1️⃣ Upload your Excel (.xlsx) price list\n"
        "2️⃣ Select brands to scan\n"
        "3️⃣ Select product categories\n"
        "4️⃣ Choose match mode (exact / similar / both)\n"
        "5️⃣ Set minimum savings % threshold\n"
        "6️⃣ Optionally set minimum dollar saving\n"
        "7️⃣ Confirm and get your Excel report with live buy links\n\n"
        "/scan — Re-run scan on last uploaded Excel\n"
        "/status — Show current loaded inventory",
        parse_mode="Markdown"
    )

# ─── /status ──────────────────────────────────────────────────────────────────

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inventory = context.bot_data.get("inventory")
    filename = context.bot_data.get("filename", "None")
    if not inventory:
        await update.message.reply_text("⚠️ No Excel loaded yet. Upload a price list to get started.")
        return
    cats = get_categories_in_inventory(inventory)
    await update.message.reply_text(
        f"📊 *Current Inventory Loaded*\n\n"
        f"📁 File: `{filename}`\n"
        f"📦 Models: {len(inventory)}\n"
        f"🏷️ Brands: {', '.join(sorted(set(p.get('brand','?') for p in inventory)))}\n"
        f"📂 Categories: {', '.join(cats)}",
        parse_mode="Markdown"
    )

# ─── Excel Upload ──────────────────────────────────────────────────────────────

async def handle_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith((".xlsx", ".xls")):
        await update.message.reply_text("⚠️ Please upload an Excel file (.xlsx or .xls)")
        return

    await update.message.reply_text("📥 Receiving your Excel file...")

    file = await doc.get_file()
    file_path = f"/tmp/{doc.file_name}"
    await file.download_to_drive(file_path)

    try:
        inventory = parse_excel(file_path)
        context.bot_data["inventory"] = inventory
        context.bot_data["filename"] = doc.file_name
        cats = get_categories_in_inventory(inventory)

        await update.message.reply_text(
            f"✅ *Excel loaded successfully!*\n\n"
            f"📦 {len(inventory)} models found\n"
            f"🏷️ Brands: {', '.join(sorted(set(p.get('brand','?') for p in inventory)))}\n"
            f"📂 Categories: {', '.join(cats)}\n\n"
            "Let's set up your scan...",
            parse_mode="Markdown"
        )
        return await ask_brands(update, context)

    except Exception as e:
        logger.error(f"Excel parse error: {e}")
        await update.message.reply_text(f"❌ Error reading Excel: {str(e)}")

# ─── /scan command ─────────────────────────────────────────────────────────────

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.bot_data.get("inventory"):
        await update.message.reply_text("⚠️ No Excel loaded yet. Please upload your price list first.")
        return
    return await ask_brands(update, context)


# ─── Step 1: Brand Selection ───────────────────────────────────────────────────

async def ask_brands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["selected_brands"] = list(PREFERRED_BRANDS)

    keyboard = _build_brand_keyboard(list(PREFERRED_BRANDS))
    msg = update.message if update.message else update.callback_query.message
    await msg.reply_text(
        "🏷️ *Step 1 of 4 — Brand Filter*\n\n"
        "Which brands should I scan on Best Buy?\n"
        "_(All selected by default — tap to deselect)_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return STEP_BRANDS

def _build_brand_keyboard(selected):
    keyboard = []
    row = []
    for i, brand in enumerate(PREFERRED_BRANDS):
        tick = "✅" if brand in selected else "🔲"
        row.append(InlineKeyboardButton(f"{tick} {brand}", callback_data=f"brand_{brand}"))
        if len(row) == 3 or i == len(PREFERRED_BRANDS) - 1:
            keyboard.append(row)
            row = []
    keyboard.append([
        InlineKeyboardButton("☑️ All", callback_data="brands_all"),
        InlineKeyboardButton("🔲 None", callback_data="brands_none"),
        InlineKeyboardButton("✅ Confirm →", callback_data="brands_confirm"),
    ])
    return keyboard

async def brand_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    selected = context.user_data.get("selected_brands", list(PREFERRED_BRANDS))

    if data == "brands_all":
        selected = list(PREFERRED_BRANDS)
    elif data == "brands_none":
        selected = []
    elif data == "brands_confirm":
        if not selected:
            await query.answer("⚠️ Please select at least one brand.", show_alert=True)
            return STEP_BRANDS
        context.user_data["selected_brands"] = selected
        return await ask_categories(update, context)
    else:
        brand = data.replace("brand_", "")
        if brand in selected:
            selected.remove(brand)
        else:
            selected.append(brand)

    context.user_data["selected_brands"] = selected
    await query.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup(_build_brand_keyboard(selected))
    )
    return STEP_BRANDS


# ─── Step 2: Category Selection ───────────────────────────────────────────────

async def ask_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inventory = context.bot_data.get("inventory", [])
    available_cats = get_categories_in_inventory(inventory)
    context.user_data["available_categories"] = available_cats
    context.user_data["selected_categories"] = list(available_cats)  # all on by default

    brands = context.user_data.get("selected_brands", [])
    keyboard = _build_category_keyboard(available_cats, list(available_cats))

    await update.callback_query.edit_message_text(
        f"✅ Brands: *{', '.join(brands)}*\n\n"
        "📂 *Step 2 of 4 — Category Filter*\n\n"
        "Which product categories should I scan?\n"
        "_(All selected by default — tap to deselect)_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return STEP_CATEGORIES

def _build_category_keyboard(available, selected):
    keyboard = []
    for cat in available:
        tick = "✅" if cat in selected else "🔲"
        keyboard.append([InlineKeyboardButton(f"{tick} {cat}", callback_data=f"cat_{cat}")])
    keyboard.append([
        InlineKeyboardButton("☑️ All", callback_data="cats_all"),
        InlineKeyboardButton("🔲 None", callback_data="cats_none"),
        InlineKeyboardButton("✅ Confirm →", callback_data="cats_confirm"),
    ])
    return keyboard

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    available = context.user_data.get("available_categories", [])
    selected = context.user_data.get("selected_categories", list(available))

    if data == "cats_all":
        selected = list(available)
    elif data == "cats_none":
        selected = []
    elif data == "cats_confirm":
        if not selected:
            await query.answer("⚠️ Please select at least one category.", show_alert=True)
            return STEP_CATEGORIES
        context.user_data["selected_categories"] = selected
        return await ask_mode(update, context)
    else:
        cat = data.replace("cat_", "", 1)
        if cat in selected:
            selected.remove(cat)
        else:
            selected.append(cat)

    context.user_data["selected_categories"] = selected
    await query.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup(_build_category_keyboard(available, selected))
    )
    return STEP_CATEGORIES


# ─── Step 3: Scan Mode ────────────────────────────────────────────────────────

async def ask_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cats = context.user_data.get("selected_categories", [])
    keyboard = [
        [InlineKeyboardButton("🎯 Exact models only", callback_data="mode_exact")],
        [InlineKeyboardButton("🔍 Similar spec matches", callback_data="mode_similar")],
        [InlineKeyboardButton("⚡ Both (recommended)", callback_data="mode_both")],
    ]
    await update.callback_query.edit_message_text(
        f"✅ Categories: *{', '.join(cats)}*\n\n"
        "🔎 *Step 3 of 4 — Scan Mode*\n\n"
        "How should I match your models on Best Buy?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return STEP_MODE

async def mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["scan_mode"] = query.data.replace("mode_", "")
    return await ask_savings(update, context)


# ─── Step 4: Savings Threshold ────────────────────────────────────────────────

async def ask_savings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode_labels = {"exact": "Exact only", "similar": "Similar", "both": "Both"}
    mode = context.user_data.get("scan_mode", "both")
    keyboard = [
        [
            InlineKeyboardButton("5%+",  callback_data="savings_5"),
            InlineKeyboardButton("10%+", callback_data="savings_10"),
            InlineKeyboardButton("15%+", callback_data="savings_15"),
            InlineKeyboardButton("20%+", callback_data="savings_20"),
        ],
        [InlineKeyboardButton("✏️ Custom %", callback_data="savings_custom")],
    ]
    await update.callback_query.edit_message_text(
        f"✅ Mode: *{mode_labels.get(mode)}*\n\n"
        "💰 *Step 4 of 4 — Savings Threshold*\n\n"
        "Only show deals where Best Buy is cheaper by at least:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return STEP_SAVINGS

async def savings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "savings_custom":
        await query.edit_message_text(
            "✏️ Enter your minimum savings % (e.g. `12` for 12%+):",
            parse_mode="Markdown"
        )
        return STEP_SAVINGS

    pct = int(data.replace("savings_", ""))
    context.user_data["min_savings_pct"] = pct
    return await ask_dollar(update, context)

async def savings_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text.strip().replace("%", ""))
        context.user_data["min_savings_pct"] = val
        return await ask_dollar_msg(update, context)
    except ValueError:
        await update.message.reply_text("⚠️ Please enter a number only, e.g. `12`", parse_mode="Markdown")
        return STEP_SAVINGS


# ─── Step 4b: Dollar Threshold ────────────────────────────────────────────────

async def ask_dollar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pct = context.user_data.get("min_savings_pct", 10)
    keyboard = [
        [
            InlineKeyboardButton("$50+",  callback_data="dollar_50"),
            InlineKeyboardButton("$100+", callback_data="dollar_100"),
            InlineKeyboardButton("$150+", callback_data="dollar_150"),
            InlineKeyboardButton("$200+", callback_data="dollar_200"),
        ],
        [InlineKeyboardButton("⏭️ Skip — % only", callback_data="dollar_skip")],
    ]
    await update.callback_query.edit_message_text(
        f"✅ Min savings: *{pct}%+*\n\n"
        "💵 *Optional — Minimum Dollar Saving*\n\n"
        "Also require a minimum dollar saving per unit?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return STEP_DOLLAR

async def ask_dollar_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pct = context.user_data.get("min_savings_pct", 10)
    keyboard = [
        [
            InlineKeyboardButton("$50+",  callback_data="dollar_50"),
            InlineKeyboardButton("$100+", callback_data="dollar_100"),
            InlineKeyboardButton("$150+", callback_data="dollar_150"),
            InlineKeyboardButton("$200+", callback_data="dollar_200"),
        ],
        [InlineKeyboardButton("⏭️ Skip — % only", callback_data="dollar_skip")],
    ]
    await update.message.reply_text(
        f"✅ Min savings: *{pct}%+*\n\n"
        "💵 *Optional — Minimum Dollar Saving*\n\n"
        "Also require a minimum dollar saving per unit?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return STEP_DOLLAR

async def dollar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    context.user_data["min_savings_dollar"] = 0 if data == "dollar_skip" else int(data.replace("dollar_", ""))
    return await show_confirm(update, context)


# ─── Confirm & Launch ─────────────────────────────────────────────────────────

async def show_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    brands     = ud.get("selected_brands", [])
    categories = ud.get("selected_categories", [])
    mode       = ud.get("scan_mode", "both")
    pct        = ud.get("min_savings_pct", 10)
    dollar     = ud.get("min_savings_dollar", 0)
    inventory  = context.bot_data.get("inventory", [])

    mode_labels = {"exact": "Exact only", "similar": "Similar matches", "both": "Both"}
    dollar_str  = f" + ${dollar}+ saving" if dollar else ""
    filtered    = filter_inventory(inventory, brands, categories)

    keyboard = [[
        InlineKeyboardButton("🚀 Start Scan", callback_data="scan_start"),
        InlineKeyboardButton("❌ Cancel",     callback_data="scan_cancel"),
    ]]

    await update.callback_query.edit_message_text(
        f"✅ *Ready to Scan Best Buy*\n\n"
        f"🏷️ Brands: *{', '.join(brands)}*\n"
        f"📂 Categories: *{', '.join(categories)}*\n"
        f"🔎 Mode: *{mode_labels.get(mode)}*\n"
        f"💰 Min savings: *{pct}%+{dollar_str}*\n"
        f"📦 Models queued: *{len(filtered)}*\n\n"
        f"_Estimated time: ~{max(5, len(filtered) // 3)} seconds_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return STEP_CONFIRM

async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "scan_cancel":
        await query.edit_message_text("❌ Scan cancelled.")
        return ConversationHandler.END

    await query.edit_message_text(
        "🔍 *Scanning Best Buy...*\n\nThis may take a moment, please wait.",
        parse_mode="Markdown"
    )

    ud          = context.user_data
    inventory   = context.bot_data.get("inventory", [])
    brands      = ud.get("selected_brands", [])
    categories  = ud.get("selected_categories", [])
    mode        = ud.get("scan_mode", "both")
    min_pct     = ud.get("min_savings_pct", 10)
    min_dollar  = ud.get("min_savings_dollar", 0)

    filtered = filter_inventory(inventory, brands, categories)

    try:
        results = await scanner.scan(filtered, mode=mode)

        # Keep only results where BB is genuinely cheaper by threshold
        qualified = []
        for r in results:
            if r.get("savings_pct", 0) >= min_pct and r.get("savings_dollar", 0) >= min_dollar:
                qualified.append(r)

        qualified.sort(key=lambda x: x["savings_pct"], reverse=True)

        scan_params = {
            "brands": brands,
            "categories": categories,
            "mode": mode,
            "min_savings_pct": min_pct,
            "min_savings_dollar": min_dollar,
        }
        report_path = build_report(filtered, qualified, scan_params)

        deal_count = len(qualified)
        total      = len(filtered)

        if deal_count == 0:
            summary = (
                f"🔍 *Scan complete* — {total} models checked\n\n"
                f"😔 No deals found where Best Buy is {min_pct}%+ cheaper than your cost"
                + (f" with ${min_dollar}+ saving" if min_dollar else "") +
                "\n\nTry lowering your threshold or switching to 'Both' mode.\n\n"
                "📊 Full results Excel attached — all models shown."
            )
        else:
            savings = [r["savings_pct"] for r in qualified]
            summary = (
                f"✅ *Scan Complete!*\n\n"
                f"📦 Models scanned: *{total}*\n"
                f"🛒 Restock deals found: *{deal_count}*\n"
                f"📈 Best saving: *{max(savings):.1f}%*\n"
                f"📊 Avg saving: *{sum(savings)/len(savings):.1f}%*\n\n"
                f"_Excel report attached — sorted by best savings, with live Buy links._"
            )

        await query.message.reply_text(summary, parse_mode="Markdown")
        with open(report_path, "rb") as f:
            await query.message.reply_document(
                document=f,
                filename="BB_Restock_Scan.xlsx",
                caption="📊 iGamer Restock Report — tap any 🛒 Buy link to purchase directly on Best Buy."
            )

        try:
            os.remove(report_path)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Scan error: {e}")
        await query.message.reply_text(f"❌ Scan failed: {str(e)}")

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Scan cancelled.")
    return ConversationHandler.END


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Document.ALL, handle_excel),
            CommandHandler("scan", scan_cmd),
        ],
        states={
            STEP_BRANDS: [
                CallbackQueryHandler(brand_callback, pattern="^(brand_|brands_)"),
            ],
            STEP_CATEGORIES: [
                CallbackQueryHandler(category_callback, pattern="^(cat_|cats_)"),
            ],
            STEP_MODE: [
                CallbackQueryHandler(mode_callback, pattern="^mode_"),
            ],
            STEP_SAVINGS: [
                CallbackQueryHandler(savings_callback, pattern="^savings_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, savings_text_input),
            ],
            STEP_DOLLAR: [
                CallbackQueryHandler(dollar_callback, pattern="^dollar_"),
            ],
            STEP_CONFIRM: [
                CallbackQueryHandler(confirm_callback, pattern="^scan_"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(conv)

    logger.info("iGamer Best Buy Scanner bot started.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
