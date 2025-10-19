import os
import asyncio
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

import aiohttp
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

# Провайдеры
from providers import PROVIDERS

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ENABLED_PROVIDERS = [p.strip() for p in (os.getenv("ENABLED_PROVIDERS") or "defillama").split(",") if p.strip()]
ALERT_CHECK_MINUTES = int(os.getenv("ALERT_CHECK_MINUTES") or "10")
DEFAULT_TOP_N = int(os.getenv("DEFAULT_TOP_N") or "15")

STATE_FILE = "state.json"

@dataclass
class AlertConfig:
    threshold: float  # APY %
    enabled: bool = True

class RateItem(BaseModel):
    platform: str
    chain: str
    symbol: str
    apy: float = Field(ge=-1000, le=100000)
    tvl_usd: float = 0
    source_url: str
    source: str
    notes: str = ""

class State(BaseModel):
    alert: Optional[AlertConfig] = None

def load_state() -> State:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "alert" in data and data["alert"] is not None:
                data["alert"] = AlertConfig(**data["alert"])
            return State(**data)
        except Exception:
            pass
    return State(alert=None)

def save_state(st: State):
    data = st.model_dump()
    if isinstance(data.get("alert"), AlertConfig):
        data["alert"] = data["alert"].__dict__
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

async def fetch_all_providers(session: aiohttp.ClientSession) -> List[RateItem]:
    items: List[RateItem] = []
    for key in ENABLED_PROVIDERS:
        provider_cls = PROVIDERS.get(key)
        if not provider_cls:
            continue
        prov = provider_cls()
        try:
            raw = await prov.fetch(session)
            for r in raw:
                try:
                    items.append(RateItem(**r))
                except ValidationError:
                    continue
        except Exception as e:
            # логгируем в консоль, но не падаем
            print(f"[provider:{key}] error: {e}")
    # дедуп по (platform, chain, source_url)
    seen = set()
    uniq = []
    for it in items:
        k = (it.platform, it.chain, it.source_url)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)
    # сортировка по apy
    uniq.sort(key=lambda x: x.apy, reverse=True)
    return uniq

def fmt_row(i: int, it: RateItem) -> str:
    tvl = f"${it.tvl_usd:,.0f}"
    platform = f"{it.platform} ({it.chain})" if it.chain else it.platform
    return f"{i:>2}. <b>{platform}</b> — <b>{it.apy:.2f}%</b> APY  |  TVL: {tvl}\n{it.source_url}"

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Привет! Я показываю лучшие актуальные ставки по <b>USDC</b>.\n\n"
        "Команды:\n"
        "• /rates [N] — топ N ставок (по умолчанию 15)\n"
        "• /alert set &lt;порог&gt; — алёрт при APY ≥ порога (например <code>/alert set 12</code>)\n"
        "• /alert off — отключить алёрты\n"
        "• /sources — источники/провайдеры\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def cmd_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    enabled = ", ".join(ENABLED_PROVIDERS) or "—"
    await update.message.reply_text(
        f"Подключённые провайдеры: <b>{enabled}</b>\n"
        "Основной: DefiLlama (DeFi доходности). Для CEX можно добавить адаптеры (Binance/OKX/Bybit).",
        parse_mode=ParseMode.HTML
    )

async def cmd_rates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_n = DEFAULT_TOP_N
    if context.args:
        try:
            top_n = max(1, min(50, int(context.args[0])))
        except Exception:
            pass
    await update.message.reply_text("Собираю ставки…")
    async with aiohttp.ClientSession() as session:
        items = await fetch_all_providers(session)
    if not items:
        await update.message.reply_text("Не удалось получить данные. Попробуйте позже.")
        return
    rows = [fmt_row(i+1, it) for i, it in enumerate(items[:top_n])]
    chunks: List[str] = []
    buf = ""
    for row in rows:
        if len(buf) + len(row) > 3500:
            chunks.append(buf)
            buf = ""
        buf += row + "\n\n"
    if buf:
        chunks.append(buf)
    for ch in chunks:
        await update.message.reply_text(ch, parse_mode=ParseMode.HTML, disable_web_page_preview=False)

async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    st = load_state()
    if not context.args:
        if st.alert and st.alert.enabled:
            await update.message.reply_text(f"Алёрт включён: APY ≥ {st.alert.threshold}%")
        else:
            await update.message.reply_text("Алёрты выключены. Включить: /alert set 12")
        return
    sub = context.args[0].lower()
    if sub == "off":
        st.alert = None
        save_state(st)
        await update.message.reply_text("Алёрты отключены.")
        return
    if sub == "set":
        if len(context.args) < 2:
            await update.message.reply_text("Формат: /alert set <порог>, пример: /alert set 12")
            return
        try:
            thr = float(context.args[1])
        except Exception:
            await update.message.reply_text("Неверный порог. Пример: /alert set 10.5")
            return
        st.alert = AlertConfig(threshold=thr, enabled=True)
        save_state(st)
        await update.message.reply_text(f"Готово! Алёрт при APY ≥ {thr}%. Проверяю каждые {ALERT_CHECK_MINUTES} мин.")
        return
    await update.message.reply_text("Команды: /alert set <порог> | /alert off")

async def alert_worker(app: Application):
    chat_ids = set()  # простая реализация: уведомляем только последний чат, где запускали /alert
    # Более продвинуто: хранить chat_id в state.json
    while True:
        await asyncio.sleep(ALERT_CHECK_MINUTES * 60)
        st = load_state()
        if not st.alert or not st.alert.enabled:
            continue
        try:
            async with aiohttp.ClientSession() as session:
                items = await fetch_all_providers(session)
            best = items[0] if items else None
            if best and best.apy >= st.alert.threshold:
                msg = (
                    f"🚨 Найдена ставка по USDC ≥ {st.alert.threshold}%\n\n"
                    f"{fmt_row(1, best)}"
                )
                for cid in list(chat_ids):
                    try:
                        await app.bot.send_message(cid, msg, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
                    except Exception as e:
                        print("alert send error:", e)
        except Exception as e:
            print("alert worker error:", e)

async def track_chat(update: Update, _: ContextTypes.DEFAULT_TYPE):
    # Запоминаем chat_id, откуда звали команды, чтобы присылать алёрты
    app: Application = _.application
    if not hasattr(app, "alert_chats"):
        app.alert_chats = set()
    app.alert_chats.add(update.effective_chat.id)

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN не задан в .env")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("sources", cmd_sources))
    app.add_handler(CommandHandler("rates", cmd_rates))
    app.add_handler(CommandHandler("alert", cmd_alert))

    # общий трекер чатов
    for h in app.handlers.get(0, []):
        pass
    app.add_handler(CommandHandler(["start","rates","alert","sources"], track_chat))

    # фоновой воркер с алёртами
    app.post_init = lambda _: asyncio.create_task(alert_worker(app))

    print("Bot is running…")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
