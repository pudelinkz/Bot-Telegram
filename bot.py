import asyncio
import logging
import os
import re
import time
from collections import defaultdict, deque
from datetime import timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ChatPermissions
from dotenv import load_dotenv

from database import (
    init_db, get_settings, add_violation, increment_warning,
    get_warning_count, clear_warnings
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN or TOKEN == "PASTE_TELEGRAM_BOT_TOKEN_HERE":
    raise RuntimeError("BOT_TOKEN belum diatur. Salin .env.example menjadi .env dan isi token.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
dp = Dispatcher()

message_times = defaultdict(deque)
recent_texts = defaultdict(lambda: deque(maxlen=8))
last_notice = {}

URL_RE = re.compile(r"(?i)(https?://|www\.|t\.me/|telegram\.me/|tg://|(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?)")

def extract_text(message: Message) -> str:
    return (message.text or message.caption or "").strip()

def contains_disallowed_link(text: str, allowed_domains: list[str]) -> bool:
    settings = get_settings()
    if not settings.get("anti_link", True):
        return False
    allowed = [d.lower().strip().removeprefix("@") for d in allowed_domains if d.strip()]
    candidates = URL_RE.findall(text)
    if not candidates:
        return False
    # Periksa domain dalam teks secara konservatif; link yang tidak jelas dianggap tidak diizinkan.
    urls = re.findall(r"(?i)(?:(?:https?://|www\.)\S+|(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?|t\.me/\S+)", text)
    for raw in urls:
        value = raw.lower().rstrip(".,!?);]")
        value = re.sub(r"^https?://", "", value)
        value = value.removeprefix("www.")
        domain = value.split("/")[0].split(":")[0]
        if not any(domain == d or domain.endswith("." + d) for d in allowed):
            return True
    return False

async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Check whether a Telegram user is a group admin."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except Exception:
        logging.exception("Gagal memeriksa status admin untuk user_id=%s chat_id=%s", user_id, chat_id)
        return False


async def is_admin_actor(message: Message, bot: Bot) -> bool:
    """Recognize regular admins and messages sent anonymously on behalf of this group."""
    if not message.chat:
        return False

    # Telegram represents an anonymous group admin as sender_chat=the group itself.
    # This identity is available only for messages sent on behalf of the current group.
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        return True

    if message.from_user:
        return await is_admin(bot, message.chat.id, message.from_user.id)

    return False

async def log_and_warn(message: Message, reason: str, text: str, bot: Bot):
    user = message.from_user
    if not user or not message.chat:
        return
    try:
        await message.delete()
    except Exception:
        logging.warning("Tidak bisa menghapus pesan; cek izin Delete messages.")

    add_violation(message.chat.id, user.id, user.username, reason, text)
    count = increment_warning(message.chat.id, user.id)
    settings = get_settings()
    before_ban = int(settings.get("warnings_before_ban", 4))
    before_mute = int(settings.get("warnings_before_mute", 2))
    mute_minutes = max(1, int(settings.get("mute_minutes", 10)))
    name = user.full_name

    try:
        if count >= before_ban:
            await bot.ban_chat_member(message.chat.id, user.id)
            await message.answer(f"🚫 {name} diblokir dari grup karena {count} pelanggaran.")
            return
        if count >= before_mute:
            until = __import__("datetime").datetime.now(__import__("datetime").timezone.utc) + timedelta(minutes=mute_minutes)
            await bot.restrict_chat_member(
                message.chat.id, user.id, permissions=ChatPermissions(can_send_messages=False),
                until_date=until
            )
            await message.answer(
                f"🔇 {name} dibisukan selama {mute_minutes} menit. Peringatan {count}/{before_ban}."
            )
            return
        await message.answer(f"⚠️ {name}, pesan dihapus: {reason}. Peringatan {count}/{before_ban}.")
    except Exception:
        logging.exception("Aksi moderasi gagal. Pastikan bot admin dengan izin yang benar.")

@dp.message(Command("start", "help"))
async def start_help(message: Message):
    await message.answer(
        "🛡️ <b>Bot Anti-Spam</b>\n"
        "Saya memeriksa flood, pesan berulang, link yang tidak diizinkan, dan kata terlarang.\n\n"
        "Perintah admin (gunakan dengan membalas pesan anggota):\n"
        "/warn — tambah peringatan\n/mute 10 — mute 10 menit\n"
        "/ban — ban anggota\n/unmute — buka mute\n/unban USER_ID — buka ban\n"
        "/stats — statistik pelanggaran\n"
        "Pengaturan lebih lengkap tersedia di dashboard admin.",
        parse_mode="HTML"
    )

@dp.message(Command("stats"))
async def cmd_stats(message: Message, bot: Bot):
    if not await is_admin_actor(message, bot):
        return
    from database import stats
    s = stats()
    await message.answer(f"📊 Statistik\nTotal pelanggaran: {s['total']}\nHari ini (UTC): {s['today']}")

async def get_replied_target(message: Message, bot: Bot):
    if not await is_admin_actor(message, bot):
        await message.reply("Perintah ini hanya untuk admin grup. Jika memakai mode anonim, pastikan pesan dikirim sebagai identitas grup.")
        return None

    replied = message.reply_to_message
    if not replied or not replied.from_user:
        await message.reply(
            "Balas pesan langsung dari anggota yang ingin dimoderasi. "
            "Pesan channel/forward tertentu tidak selalu menyediakan ID pengguna."
        )
        return None

    target = replied.from_user
    if target.is_bot:
        await message.reply("Saya tidak bisa memoderasi bot melalui perintah ini.")
        return None
    if await is_admin(bot, message.chat.id, target.id):
        await message.reply("Saya tidak akan memoderasi admin grup.")
        return None
    return target

@dp.message(Command("warn"))
async def cmd_warn(message: Message, bot: Bot):
    target = await get_replied_target(message, bot)
    if not target: return
    count = increment_warning(message.chat.id, target.id)
    add_violation(message.chat.id, target.id, target.username, "manual_warning", "")
    settings = get_settings()
    await message.answer(f"⚠️ {target.full_name} mendapat peringatan {count}/{settings['warnings_before_ban']}.")

@dp.message(Command("mute"))
async def cmd_mute(message: Message, bot: Bot, command: CommandObject):
    target = await get_replied_target(message, bot)
    if not target: return
    try: minutes = max(1, min(10080, int((command.args or "10").split()[0])))
    except ValueError: minutes = 10
    until = __import__("datetime").datetime.now(__import__("datetime").timezone.utc) + timedelta(minutes=minutes)
    try:
        await bot.restrict_chat_member(message.chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=False), until_date=until)
        await message.answer(f"🔇 {target.full_name} dimute selama {minutes} menit.")
    except Exception:
        await message.answer("Gagal mute. Pastikan grup berupa supergroup dan bot punya izin Restrict members.")

@dp.message(Command("ban"))
async def cmd_ban(message: Message, bot: Bot):
    target = await get_replied_target(message, bot)
    if not target: return
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await message.answer(f"🚫 {target.full_name} telah di-ban.")
    except Exception:
        await message.answer("Gagal ban. Pastikan bot punya izin Restrict members.")

@dp.message(Command("unmute"))
async def cmd_unmute(message: Message, bot: Bot):
    target = await get_replied_target(message, bot)
    if not target: return
    try:
        await bot.restrict_chat_member(message.chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=True, can_send_audios=True,
                can_send_documents=True, can_send_photos=True, can_send_videos=True,
                can_send_video_notes=True, can_send_voice_notes=True, can_send_polls=True,
                can_send_other_messages=True, can_add_web_page_previews=True,
                can_invite_users=True, can_pin_messages=True, can_change_info=True))
        clear_warnings(message.chat.id, target.id)
        await message.answer(f"🔊 Pembatasan {target.full_name} dicabut dan peringatannya direset.")
    except Exception:
        await message.answer("Gagal membuka mute. Periksa izin bot.")

@dp.message(Command("unban"))
async def cmd_unban(message: Message, bot: Bot, command: CommandObject):
    if not await is_admin_actor(message, bot):
        await message.reply("Perintah ini hanya untuk admin grup.")
        return
    try:
        user_id = int((command.args or "").strip())
    except ValueError:
        await message.reply("Gunakan: /unban USER_ID")
        return
    try:
        await bot.unban_chat_member(message.chat.id, user_id, only_if_banned=True)
        await message.answer(f"Ban untuk ID {user_id} telah dicabut.")
    except Exception:
        await message.answer("Gagal unban. Periksa ID dan izin bot.")

@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def moderate_group_messages(message: Message, bot: Bot):
    user = message.from_user
    if not user or user.is_bot:
        return
    if await is_admin(bot, message.chat.id, user.id):
        return

    text = extract_text(message)
    now = time.monotonic()
    key = (message.chat.id, user.id)
    settings = get_settings()

    times = message_times[key]
    times.append(now)
    window = max(2, int(settings.get("flood_window_seconds", 8)))
    while times and now - times[0] > window:
        times.popleft()
    max_messages = max(2, int(settings.get("flood_max_messages", 6)))
    if len(times) > max_messages:
        times.clear()
        await log_and_warn(message, "flood", text, bot)
        return

    if text:
        normalized = re.sub(r"\s+", " ", text.casefold()).strip()
        history = recent_texts[key]
        history.append((now, normalized))
        duplicate_limit = max(2, int(settings.get("duplicate_limit", 3)))
        repeated = sum(1 for ts, old in history if now - ts <= 30 and old == normalized)
        if len(normalized) >= 4 and repeated >= duplicate_limit:
            history.clear()
            await log_and_warn(message, "pesan berulang", text, bot)
            return

        words = [str(w).casefold().strip() for w in settings.get("banned_words", []) if str(w).strip()]
        if any(word in normalized for word in words):
            await log_and_warn(message, "kata terlarang", text, bot)
            return

        if contains_disallowed_link(text, settings.get("allowed_domains", [])):
            await log_and_warn(message, "link tidak diizinkan", text, bot)
            return

async def main():
    init_db()
    bot = Bot(TOKEN)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())