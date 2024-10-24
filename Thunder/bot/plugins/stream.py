import asyncio
import logging
import time
from urllib.parse import quote_plus

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from Thunder.bot import StreamBot
from Thunder.utils.database import Database
from Thunder.utils.file_properties import get_hash, get_media_file_size, get_name
from Thunder.utils.human_readable import humanbytes
from Thunder.vars import Var

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize databases
db = Database(Var.DATABASE_URL, Var.name)
pass_db = Database(Var.DATABASE_URL, "ag_passwords")

# Define constants
CACHE = {}  # Cache dictionary to store links
CACHE_EXPIRY = 86400  # 24 hours in seconds

async def handle_flood_wait(e: FloodWait) -> None:
    """Handle FloodWait exceptions by sleeping for the required duration."""
    logger.warning(f"FloodWait encountered. Sleeping for {e.x} seconds.")
    await asyncio.sleep(e.x)

async def notify_owner(client: Client, text: str):
    """Send a notification message to the owner and log to BIN_CHANNEL."""
    try:
        await client.send_message(chat_id=Var.OWNER_ID, text=text)
        await client.send_message(chat_id=Var.BIN_CHANNEL, text=text)
    except Exception as e:
        logger.error(f"Failed to send message to owner or BIN_CHANNEL: {e}", exc_info=True)

async def handle_user_error(message: Message, error_msg: str):
    """Send a standardized error message to the user."""
    try:
        await message.reply_text(f"❌ {error_msg}\nPlease try again or contact support.", quote=True)
    except Exception as e:
        logger.error(f"Failed to send error message to user: {e}", exc_info=True)

async def forward_media(media_message: Message) -> Message:
    """Forward the media message to the BIN channel."""
    try:
        return await media_message.forward(chat_id=Var.BIN_CHANNEL)
    except Exception as e:
        error_text = f"Error forwarding media message: {e}"
        logger.error(error_text, exc_info=True)
        await notify_owner(media_message._client, error_text)
        raise

async def generate_media_links(log_msg: Message) -> tuple:
    """Generate stream and download links for media."""
    try:
        base_url = Var.URL.rstrip("/")
        file_id = log_msg.id
        file_name = quote_plus(get_name(log_msg))
        hash_value = get_hash(log_msg)
        stream_link = f"{base_url}/watch/{file_id}/{file_name}?hash={hash_value}"
        online_link = f"{base_url}/{file_id}/{file_name}?hash={hash_value}"
        return stream_link, online_link
    except Exception as e:
        error_text = f"Error generating media links: {e}"
        logger.error(error_text, exc_info=True)
        await notify_owner(log_msg._client, error_text)
        raise

async def send_links_to_user(client: Client, command_message: Message, media_name: str,
                             media_size: str, stream_link: str, online_link: str):
    """Send the generated links to the user."""
    msg_text = (
        "🔗 <b>Your Links are Ready!</b>\n\n"
        f"📄 <b>File Name:</b> <i>{media_name}</i>\n"
        f"📂 <b>File Size:</b> <i>{media_size}</i>\n\n"
        f"📥 <b>Download Link:</b>\n<code>{online_link}</code>\n\n"
        f"🖥️ <b>Watch Now:</b>\n<code>{stream_link}</code>\n\n"
        "⏰ <b>Note:</b> Links are available as long as the bot is active."
    )
    try:
        await command_message.reply_text(
            msg_text,
            quote=True,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🖥️ Watch Now", url=stream_link),
                 InlineKeyboardButton("📥 Download", url=online_link)]
            ])
        )
    except Exception as e:
        error_text = f"Error sending links to user: {e}"
        logger.error(error_text, exc_info=True)
        await notify_owner(client, error_text)
        raise

async def log_request(log_msg: Message, user, stream_link: str, online_link: str):
    """Log the request details in the BIN channel."""
    try:
        await log_msg.reply_text(
            f"👤 <b>Requested by:</b> [{user.first_name}](tg://user?id={user.id})\n"
            f"🆔 <b>User ID:</b> `{user.id}`\n\n"
            f"📥 <b>Download Link:</b> <code>{online_link}</code>\n"
            f"🖥️ <b>Watch Now Link:</b> <code>{stream_link}</code>",
            disable_web_page_preview=True,
            quote=True
        )
    except Exception as e:
        error_text = f"Error logging request: {e}"
        logger.error(error_text, exc_info=True)
        # Not critical, so no need to notify owner

async def check_admin_privileges(client: Client, chat_id: int) -> bool:
    """Check if the bot is an admin in the chat; skip for private chats."""
    try:
        chat = await client.get_chat(chat_id)
        if chat.type == 'private':
            return True  # Admin check not needed in private chats
        member = await client.get_chat_member(chat_id, client.me.id)
        return member.status in ("administrator", "creator")
    except Exception as e:
        error_text = f"Error checking admin privileges: {e}"
        logger.error(error_text, exc_info=True)
        await notify_owner(client, error_text)
        return False

@StreamBot.on_message(filters.command("link") & ~filters.private)
async def link_handler(client: Client, message: Message):
    """Handle the /link command when replying to a file in groups."""
    user_id = message.from_user.id

    # Check if the user is registered (i.e., has started the bot in DM)
    if not await db.is_user_exist(user_id):
        # User is not registered; prompt to start the bot in DM
        try:
            invite_link = f"tg://resolve?domain={client.me.username}"
            await message.reply_text(
                "⚠️ You need to start the bot in private first to use this command.\n"
                f"👉 [Click here]({invite_link}) to start a private chat.",
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📩 Start Chat", url=invite_link)]
                ])
            )
        except Exception as e:
            error_text = f"Error sending start prompt to user: {e}"
            logger.error(error_text, exc_info=True)
            await notify_owner(client, error_text)
            await message.reply_text(
                "⚠️ Please start the bot in private by sending /start to me."
            )
        return

    # Ensure the /link command is used in reply to a message
    if not message.reply_to_message:
        await message.reply_text(
            "⚠️ Please use the /link command in reply to a file.",
            quote=True
        )
        return

    reply_msg = message.reply_to_message

    # Ensure the replied message contains a file
    if not (reply_msg.media or reply_msg.document):
        await message.reply_text(
            "⚠️ The message you're replying to does not contain any file.",
            quote=True
        )
        return

    # Check for admin privileges if in a group
    if message.chat.type in ['group', 'supergroup']:
        is_admin = await check_admin_privileges(client, message.chat.id)
        if not is_admin:
            await message.reply_text(
                "🔒 The bot needs admin rights in this group to function properly.",
                quote=True
            )
            return

    await process_media_message(client, message, reply_msg)

@StreamBot.on_message(filters.private & filters.incoming & (filters.document | filters.video | filters.photo), group=4)
async def private_receive_handler(client: Client, message: Message):
    """Handle direct file uploads in private chat."""
    await process_media_message(client, message, message)

async def process_media_message(client: Client, command_message: Message, media_message: Message):
    """Process the media message and generate streaming and download links."""
    try:
        # Generate a unique cache key based on file_unique_id
        cache_key = media_message.file_unique_id

        # Check if links are already cached and not expired
        cached_data = CACHE.get(cache_key)
        if cached_data and (time.time() - cached_data['timestamp'] < CACHE_EXPIRY):
            await send_links_to_user(
                client,
                command_message,
                cached_data['media_name'],
                cached_data['media_size'],
                cached_data['stream_link'],
                cached_data['online_link']
            )
            return

        # Forward media to BIN channel
        log_msg = await forward_media(media_message)

        # Generate links
        stream_link, online_link = await generate_media_links(log_msg)
        media_name = get_name(log_msg)
        media_size = humanbytes(get_media_file_size(media_message))

        # Cache the generated links
        CACHE[cache_key] = {
            'media_name': media_name,
            'media_size': media_size,
            'stream_link': stream_link,
            'online_link': online_link,
            'timestamp': time.time()
        }

        # Send links to user
        await send_links_to_user(client, command_message, media_name, media_size, stream_link, online_link)

        # Log the request
        await log_request(log_msg, command_message.from_user, stream_link, online_link)

    except FloodWait as e:
        await handle_flood_wait(e)
        # Retry processing after waiting
        await process_media_message(client, command_message, media_message)
    except Exception as e:
        error_text = f"Error processing media message: {e}"
        logger.error(error_text, exc_info=True)
        await handle_user_error(command_message, "An unexpected error occurred.")
        # Notify the owner about the critical error
        await notify_owner(client, f"⚠️ Critical error occurred:\n{e}")

@StreamBot.on_message(filters.channel & filters.incoming & (filters.document | filters.video | filters.photo) & ~filters.forwarded, group=-1)
async def channel_receive_handler(client: Client, broadcast: Message):
    """Handle media shared in a channel."""
    try:
        if int(broadcast.chat.id) in Var.BANNED_CHANNELS:
            await client.leave_chat(broadcast.chat.id)
            logger.info(f"Left banned channel: {broadcast.chat.id}")
            return

        # Forward media to BIN channel
        log_msg = await forward_media(broadcast)

        # Generate links
        stream_link, online_link = await generate_media_links(log_msg)

        # Log the broadcast details
        await log_request(log_msg, broadcast.chat, stream_link, online_link)

        # Edit the original broadcast message with links
        await client.edit_message_reply_markup(
            chat_id=broadcast.chat.id,
            message_id=broadcast.id,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🖥️ Watch Now", url=stream_link),
                 InlineKeyboardButton("📥 Download", url=online_link)]
            ])
        )

    except FloodWait as e:
        await handle_flood_wait(e)
        # Retry processing after waiting
        await channel_receive_handler(client, broadcast)
    except Exception as e:
        error_text = f"Error editing broadcast message: {e}"
        logger.error(error_text, exc_info=True)
        # Notify the owner about the critical error
        await notify_owner(client, f"⚠️ Critical error occurred in channel handler:\n{e}")

async def clean_cache():
    """Periodically clean up old cache entries."""
    while True:
        await asyncio.sleep(3600)  # Run every hour
        current_time = time.time()
        keys_to_delete = [key for key, value in CACHE.items() if current_time - value['timestamp'] > CACHE_EXPIRY]
        for key in keys_to_delete:
            del CACHE[key]
        if keys_to_delete:
            logger.info(f"Cache cleaned up. Removed {len(keys_to_delete)} entries.")

# Start the cache cleaning task
StreamBot.loop.create_task(clean_cache())
