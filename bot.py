import os
import re
import math
import sqlite3
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==== НАСТРОЙКИ ====
TOKEN = os.getenv("BOT_TOKEN", "8972359654:AAErw32yM2IrmSZkKEwXl6yM6woiQV7OnWg")
DB_PATH = os.path.join(os.path.dirname(__file__), "bot.db")
PER_PAGE = 5

MENU_TEXT = "📚 Привет это все меню"

# ==== БАЗА ДАННЫХ ====

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            chat_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_id INTEGER,
            replier_username TEXT,
            replier_id INTEGER,
            text TEXT,
            date TEXT,
            chat_title TEXT
        );

        CREATE TABLE IF NOT EXISTS muted (
            target_id INTEGER,
            muted_username TEXT,
            PRIMARY KEY (target_id, muted_username)
        );
        """
    )
    conn.commit()
    conn.close()


def register_user(user_id, username, chat_id):
    conn = get_conn()
    conn.execute(
        "INSERT INTO users (user_id, username, chat_id) VALUES (?, ?, ?)"
        " ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, chat_id=excluded.chat_id",
        (user_id, username, chat_id),
    )
    conn.commit()
    conn.close()


def get_user(user_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row


def add_reply(target_id, replier_username, replier_id, text, date, chat_title):
    conn = get_conn()
    conn.execute(
        "INSERT INTO replies (target_id, replier_username, replier_id, text, date, chat_title)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (target_id, replier_username, replier_id, text, date, chat_title),
    )
    conn.commit()
    conn.close()


def count_replies(target_id):
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM replies WHERE target_id=?", (target_id,)).fetchone()[0]
    conn.close()
    return n


def get_replies(target_id, page, per_page=PER_PAGE):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM replies WHERE target_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
        (target_id, per_page, (page - 1) * per_page),
    ).fetchall()
    conn.close()
    return rows


def search_replies(target_id, username):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM replies WHERE target_id=? AND LOWER(replier_username)=LOWER(?)"
        " ORDER BY id DESC LIMIT 20",
        (target_id, username),
    ).fetchall()
    conn.close()
    return rows


def mute_user(target_id, username):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO muted (target_id, muted_username) VALUES (?, LOWER(?))",
        (target_id, username),
    )
    conn.commit()
    conn.close()


def is_muted(target_id, username):
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM muted WHERE target_id=? AND muted_username=LOWER(?)",
        (target_id, username or ""),
    ).fetchone()
    conn.close()
    return row is not None


# ==== ФОРМАТИРОВАНИЕ ====

def escape_md(text):
    if not text:
        return ""
    return re.sub(r"([_*`\[\]])", r"\\\1", text)


def format_entry(username, text, date, chat):
    u = escape_md(username or "неизвестно")
    t = escape_md(text or "")
    c = escape_md(chat or "")
    return (
        f'👤: "{u}"\n'
        f'  *"{t}"*\n'
        f'⌚ "{date}"\n'
        f'   📝 "{c}"'
    )


def main_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📋 Последние ответы", callback_data="list:1")],
            [InlineKeyboardButton("🔍 Поиск по последним ответам", callback_data="search:start")],
        ]
    )


def nav_keyboard(page, total_pages):
    row = []
    if page > 1:
        row.append(InlineKeyboardButton("⬅️", callback_data=f"list:{page-1}"))
    row.append(InlineKeyboardButton(f"Лист({page}/{total_pages})", callback_data=f"list:{page}"))
    if page < total_pages:
        row.append(InlineKeyboardButton("➡️", callback_data=f"list:{page+1}"))
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("🔙 Назад", callback_data="menu:back")]])


def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="menu:back")]])


# ==== ХЭНДЛЕРЫ ====

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username or user.first_name, update.effective_chat.id)
    await update.message.reply_text(MENU_TEXT, reply_markup=main_menu_keyboard())


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username or user.first_name, update.effective_chat.id)
    await update.message.reply_text(MENU_TEXT, reply_markup=main_menu_keyboard())


async def show_list_page(query, user_id, page):
    total = count_replies(user_id)
    total_pages = max(1, math.ceil(total / PER_PAGE))
    page = max(1, min(page, total_pages))
    rows = get_replies(user_id, page)
    if not rows:
        text = "Пока нет ответов 🤷"
    else:
        text = "\n\n".join(
            format_entry(r["replier_username"], r["text"], r["date"], r["chat_title"]) for r in rows
        )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=nav_keyboard(page, total_pages))


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()

    if data.startswith("list:"):
        page = int(data.split(":")[1])
        await show_list_page(query, user_id, page)

    elif data == "search:start":
        context.user_data["awaiting_search"] = True
        await query.edit_message_text(
            "🌐 Напиши юзернейм и я скину пользователя", reply_markup=back_keyboard()
        )

    elif data == "menu:back":
        context.user_data["awaiting_search"] = False
        await query.edit_message_text(MENU_TEXT, reply_markup=main_menu_keyboard())

    elif data.startswith("mute:"):
        username = data.split(":", 1)[1]
        mute_user(user_id, username)
        await query.edit_message_text(
            f"🔇 Пользователь \"{username}\" замучен. Его ответы больше не будут приходить.",
            reply_markup=back_keyboard(),
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_search"):
        return
    context.user_data["awaiting_search"] = False

    user_id = update.effective_user.id
    username = update.message.text.strip().lstrip("@")

    rows = search_replies(user_id, username)
    if not rows:
        await update.message.reply_text(
            f'Ответов от "{username}" не найдено.', reply_markup=main_menu_keyboard()
        )
        return

    text = "\n\n".join(
        format_entry(r["replier_username"], r["text"], r["date"], r["chat_title"]) for r in rows
    )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔇 Замутить", callback_data=f"mute:{username}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="menu:back")],
        ]
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def on_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Срабатывает, когда в группе кто-то отвечает на чьё-то сообщение."""
    msg = update.message
    if not msg or not msg.reply_to_message:
        return

    target_user = msg.reply_to_message.from_user
    if not target_user or target_user.is_bot:
        return

    target = get_user(target_user.id)
    if not target:
        # этот человек ещё не запускал бота в личке -> некому слать уведомление
        return

    replier = msg.from_user
    if replier.id == target_user.id:
        return  # сам себе не отвечает

    replier_username = replier.username or replier.first_name

    if is_muted(target_user.id, replier_username):
        return

    text = msg.text or msg.caption or "(медиа без текста)"
    date_str = msg.date.strftime("%d.%m.%Y %H:%M")
    chat_title = msg.chat.title or "Личные сообщения"

    add_reply(target_user.id, replier_username, replier.id, text, date_str, chat_title)

    entry = format_entry(replier_username, text, date_str, chat_title)
    try:
        await context.bot.send_message(
            chat_id=target["chat_id"],
            text=f"🔔 Новый ответ!\n\n{entry}",
            parse_mode="Markdown",
        )
    except Exception:
        pass


def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(
        MessageHandler(filters.REPLY & filters.ChatType.GROUPS & ~filters.COMMAND, on_reply)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, text_handler)
    )

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
