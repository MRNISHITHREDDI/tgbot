import json
import asyncio
import aiohttp
import time
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command

# ==== CONFIGURATION ====
BOT_TOKEN = "8236256472:AAG8PjNbz7s9dUaTJ2lF0u2D7gRNEkNfDwU"
CHANNEL_ID = "-1002081961222"

# ADMIN CONFIG
ADMIN_IDS = [5976922690, 6808328473]  # Replace with your Telegram user IDs
DEBUG_MODE = True  # Turn off to silence debug logs

# BOT STATE
bot_running = False
loss_streak = 0
last_results = []
current_prediction = None
predictions_chart = []

# API ENDPOINTS
PERIOD_API = "https://draw.ar-lottery01.com/WinGo/WinGo_1M.json"
HISTORY_API = "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json"

HEADERS = {
    "Accept": "*/*",
    "User-Agent": "Thunder Client (https://www.thunderclient.com)"
}

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

session: aiohttp.ClientSession = None

# ===== Helper Functions =====
def log_debug(message):
    if DEBUG_MODE:
        print(f"[DEBUG] {message}")

async def setup_session():
    global session
    if session is None or session.closed:
        session = aiohttp.ClientSession()

async def get_current_period():
    await setup_session()
    ts = int(time.time() * 1000)
    url = f"{PERIOD_API}?ts={ts}"
    try:
        async with session.get(url, headers=HEADERS, timeout=10) as resp:
            text = await resp.text()
            return json.loads(text)
    except Exception as e:
        print(f"Error fetching period data: {e}")
        return None

async def get_history():
    await setup_session()
    try:
        async with session.get(HISTORY_API, headers=HEADERS, timeout=10) as resp:
            text = await resp.text()
            return json.loads(text).get("data", {}).get("list", [])
    except Exception as e:
        print(f"Error parsing history JSON: {e}")
        return []

def get_big_small(num):
    return "SMALL" if int(num) in [0, 1, 2, 3, 4] else "BIG"

# ===== Adaptive Prediction Logic =====
def update_loss_tracker(prediction, actual_result):
    global loss_streak, last_results
    if prediction == actual_result:
        loss_streak = 0
        last_results.append("WIN")
    else:
        loss_streak += 1
        last_results.append("MIS")

    if len(last_results) > 10:
        last_results.pop(0)

def smart_prediction(history):
    global loss_streak

    if not history:  # Protect from empty list
        log_debug("History empty — defaulting to BIG")
        return "BIG"

    if len(history) < 6:
        return "BIG" if int(history[0]['number']) > 4 else "SMALL"

    recent_numbers = [int(h['number']) for h in history[:8]]
    recent_classes = [get_big_small(n) for n in recent_numbers]

    # Weighted recency scoring
    score = {"BIG": 0, "SMALL": 0}
    for i, cls in enumerate(recent_classes):
        weight = len(recent_classes) - i
        score[cls] += weight

    # Detect streak
    streak_len = 1
    last_cls = recent_classes[0]
    for cls in recent_classes[1:]:
        if cls == last_cls:
            streak_len += 1
        else:
            break

    # Detect alternation
    is_alternating = (
        len(set(recent_classes[:4])) == 2 and
        all(recent_classes[i] != recent_classes[i+1] for i in range(3))
    )

    # === Adaptive Logic ===
    if loss_streak >= 4:
        log_debug(f"SAFE MODE: Loss streak {loss_streak} → Forcing reversal")
        return "SMALL" if last_cls == "BIG" else "BIG"

    if loss_streak >= 3:
        log_debug(f"CAUTION MODE: Loss streak {loss_streak} → Following last winner {recent_classes[0]}")
        return recent_classes[0]

    if streak_len >= 3:
        log_debug(f"TREND REVERSAL: {streak_len} in a row ({last_cls}), reversing")
        return "SMALL" if last_cls == "BIG" else "BIG"

    if is_alternating:
        log_debug(f"ALTERNATING PATTERN detected, switching from {recent_classes[0]}")
        return "SMALL" if recent_classes[0] == "BIG" else "BIG"

    final_choice = max(score, key=score.get)
    log_debug(f"NORMAL MODE: Weighted score {score} → Choosing {final_choice}")
    return final_choice

# ===== Bot Output =====
def format_prediction_text(period, prediction):
    text = (
        "🏆 <b>BDG WINGO 1MIN</b> 🏆\n\n"
        f"🔒 <b>PERIOD - {period[-3:]} - {prediction}</b>\n\n"
        "<b>Game link:</b> https://www.bdgin6.com/#/register?invitationCode=5513818006721"
    )
    return text

# ===== Prediction Cycle =====
async def prediction_cycle():
    global current_prediction, predictions_chart

    print("✅ Bot is running in ONE-BY-ONE mode...")

    while bot_running:
        if current_prediction is None:
            # --- Make new prediction ---
            history = await get_history()
            period_data = await get_current_period()
            if not history or not period_data:
                await asyncio.sleep(2)
                continue

            period = period_data.get("current", {}).get("issueNumber")
            if not period:
                await asyncio.sleep(2)
                continue

            prediction = smart_prediction(history)
            current_prediction = {"period": period, "prediction": prediction, "checked": False}

            predictions_chart.append(current_prediction)
            if len(predictions_chart) > 10:
                predictions_chart.pop(0)

            text = format_prediction_text(period, prediction)
            try:
                await bot.send_message(CHANNEL_ID, text)
                print(f"✅ Prediction sent for {period}: {prediction}")
            except Exception as e:
                print(f"Error sending prediction: {e}")

        else:
            # --- Check for result of current prediction ---
            history = await get_history()
            if not history:
                await asyncio.sleep(2)
                continue

            actual = next((h for h in history if h.get("issueNumber") == current_prediction["period"]), None)
            if actual:
                actual_result = get_big_small(actual.get("number"))

                if not current_prediction["checked"]:
                    update_loss_tracker(current_prediction["prediction"], actual_result)
                    current_prediction["result"] = "WIN" if current_prediction["prediction"] == actual_result else "MIS"
                    current_prediction["checked"] = True

                    if current_prediction["result"] == "WIN":
                        # 🎉 WIN → send sticker only
                        try:
                            await bot.send_sticker(
                                CHANNEL_ID,
                                "CAACAgUAAxkBAAE6foBotw4Z1-gdHMwxQWjQVh0kZhCCzAACYg8AApIdYFXAEfFxGoUVvzYE"
                            )
                            print(f"🏆 WIN on {current_prediction['period']}")
                        except Exception as e:
                            print(f"Error sending sticker: {e}")
                        current_prediction = None  # reset for next prediction
                    else:
                        # ❌ LOSS → no sticker, just predict next
                        print(f"❌ LOSS on {current_prediction['period']} → Predicting next immediately...")
                        current_prediction = None

        await asyncio.sleep(2)

# ===== Commands =====
@dp.message(Command("start"))
async def start_command(message: types.Message):
    global bot_running
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("❌ You are not authorized to control this bot.")
        return
    bot_running = True
    await message.reply("✅ Bot started")
    asyncio.create_task(prediction_cycle())

@dp.message(Command("stop"))
async def stop_command(message: types.Message):
    global bot_running
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("❌ You are not authorized to control this bot.")
        return
    bot_running = False
    await message.reply("🛑 Bot stopped")

# ===== MAIN =====
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
