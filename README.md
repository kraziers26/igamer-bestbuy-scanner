# iGamer Best Buy Restock Scanner Bot

Telegram bot that scans Best Buy for deals where BB price is LOWER than your inventory cost — giving you restock opportunities with live buy links, delivered as an Excel report.

---

## Files

| File | Purpose |
|------|---------|
| bot.py | Main Telegram bot — all conversation steps |
| excel_parser.py | Reads your iGamer Excel price list |
| bestbuy_scanner.py | Calls Best Buy API and calculates savings |
| report_builder.py | Builds the Excel output report |
| requirements.txt | Python dependencies |
| Procfile | Railway deployment config |

---

## Step-by-Step Setup

### Step 1 — Get Your Telegram Bot Token
You said you already have your bot created via @BotFather.
Just make sure you have the token saved — it looks like:
  7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

### Step 2 — Get Your Best Buy API Key
You already have this from developer.bestbuy.com.
Save it somewhere handy — you'll paste it into Railway.

### Step 3 — Create a New GitHub Repo
1. Go to github.com
2. Click "New repository"
3. Name it something like: igamer-bestbuy-scanner
4. Set it to Private
5. Click "Create repository"
6. Upload all 6 files from this folder into the repo root
   (drag and drop them all at once on the GitHub page)
7. Click "Commit changes"

### Step 4 — Deploy on Railway
1. Go to railway.app and log in
2. Click "New Project" (top right)
3. Select "Deploy from GitHub repo"
4. Find and select your new igamer-bestbuy-scanner repo
5. Railway will detect the project — click "Deploy"
6. Once deployed, click on your service to open it
7. Go to the "Variables" tab
8. Add these two environment variables:

   Variable name: TELEGRAM_TOKEN
   Value: (paste your BotFather token)

   Variable name: BESTBUY_API_KEY
   Value: (paste your Best Buy API key)

9. Click "Deploy" again to restart with the variables active
10. Check the "Logs" tab — you should see:
    "iGamer Best Buy Scanner bot started."

That's it — your bot is live 24/7.

---

## How to Use the Bot

1. Open your bot in Telegram
2. Send /start
3. Upload your Excel price list (.xlsx)
4. The bot walks you through 4 steps:

   Step 1 — Brand Filter
   Tap to select which brands to scan
   (Dell, HP, Lenovo, Apple, Acer, ASUS, MSI)

   Step 2 — Category Filter
   Tap to select product types
   (Gaming Laptop, Laptop, Desktop, etc.)
   Only shows categories actually in your Excel

   Step 3 — Scan Mode
   Exact models only — searches by your model number
   Similar spec matches — searches by specs (CPU/RAM/Storage)
   Both — tries exact first, falls back to similar

   Step 4 — Savings Threshold
   Only show deals where BB is X% cheaper than your cost
   Optional: also set a minimum dollar saving

5. Tap "Start Scan"
6. Bot scans Best Buy and sends back an Excel report

---

## Understanding the Excel Report

Your original columns are preserved exactly (Qty, Category, Description, Status, Your Cost)
5 new columns are added to the right:

  BB Price     — what Best Buy is selling it for right now
  You Save $   — how much cheaper per unit vs your cost
  You Save %   — percentage cheaper
  Match Type   — Exact match or Similar spec match
  Buy Link     — clickable link straight to Best Buy product page

Color coding:
  Green row  = BB is 15%+ cheaper — strong restock opportunity
  Yellow row = BB is 5-14% cheaper — worth considering
  Grey row   = no match found or BB is more expensive

---

## Commands

/start   — Welcome message
/scan    — Re-run scan using last uploaded Excel
/status  — Show currently loaded inventory details
/help    — How to use the bot
/cancel  — Cancel current scan setup

---

## Notes

- The bot remembers your last uploaded Excel until you upload a new one
- Use /scan to re-run with different filters without re-uploading
- Best Buy API is free with no usage limits for this scale
- Railway Hobby plan ($5/month) keeps the bot running 24/7
