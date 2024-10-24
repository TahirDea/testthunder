import logging
import time
from typing import Tuple
from urllib.parse import quote_plus

from pyrogram import Client, filters
from pyrogram.errors import RPCError
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from Thunder.bot import StreamBot
from Thunder.vars import Var
from Thunder.utils import database, human_readable
from Thunder.utils.file_properties import get_hash, get_media_file_size, get_name

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize the database
db = database.Database(Var.DATABASE_URL, Var.name)

# Constants for messages
INVALID_ARG_MSG = (
    "❌ Invalid argument. Please provide a valid Telegram User ID or username "
    "(e.g., /dc 123456789 or /dc @username)."
)
FAILED_USER_INFO_MSG = (
    "❌ Failed to retrieve user information. Please ensure the User ID/username "
    "is correct and the user has interacted with the bot or is accessible."
)
REPLY_DOES_NOT_CONTAIN_USER_MSG = "❌ The replied message does not contain a user."
MEDIA_DC_NOT_FOUND_MSG = "❌ Couldn't retrieve DC information from the file."

async def notify_owner(bot: Client, text: str):
    """Send a notification message to the BIN_CHANNEL."""
    try:
        if hasattr(Var, 'BIN_CHANNEL') and isinstance(Var.BIN_CHANNEL, int) and Var.BIN_CHANNEL != 0:
            await bot.send_message(chat_id=Var.BIN_CHANNEL, text=text)
    except Exception as e:
        logger.error(f"Failed to send message to BIN_CHANNEL: {e}", exc_info=True)

async def handle_user_error(message: Message, error_msg: str):
    """Send a standardized error message to the user."""
    try:
        await message.reply_text(f"{error_msg}", quote=True)
    except Exception as e:
        logger.error(f"Failed to send error message to user: {e}", exc_info=True)

async def log_new_user(bot: Client, user_id: int, first_name: str):
    """
    Log a new user and send a notification to the BIN_CHANNEL if the user is new.
    Does not inform the owner in direct messages.
    """
    try:
        if not await db.is_user_exist(user_id):
            await db.add_user(user_id)
            # Notify in BIN_CHANNEL without sending a DM to the owner
            await bot.send_message(
                Var.BIN_CHANNEL,
                f"👋 **New User Alert!**\n\n"
                f"✨ **Name:** [{first_name}](tg://user?id={user_id})\n"
                f"🆔 **User ID:** `{user_id}`\n\n"
                "has started the bot!"
            )
    except Exception as e:
        error_text = f"Error logging new user {user_id}: {e}"
        logger.error(error_text, exc_info=True)
        # Do not notify the owner in DM about the error
        # You can choose to log the error or send it to BIN_CHANNEL if desired

async def generate_media_links(log_msg: Message) -> Tuple[str, str]:
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

async def generate_dc_text(user) -> str:
    """Generate formatted DC information text for a user."""
    dc_id = user.dc_id if user.dc_id is not None else "Unknown"
    return (
        f"🌐 **Data Center Information**\n\n"
        f"👤 **User:** [{user.first_name or 'User'}](tg://user?id={user.id})\n"
        f"🆔 **User ID:** `{user.id}`\n"
        f"🌐 **Data Center:** `{dc_id}`\n\n"
        "This is the data center where the specified user is hosted."
    )

@StreamBot.on_message(filters.command("start") & filters.private)
async def start_command(bot: Client, message: Message):
    """Handle /start command."""
    try:
        await log_new_user(bot, message.from_user.id, message.from_user.first_name)
        args = message.text.strip().split("_")

        if len(args) == 1 or args[-1].lower() == "start":
            welcome_text = (
                "👋 **Welcome to the File to Link Bot!**\n\n"
                "I'm here to help you generate direct download and streaming links for your files.\n"
                "Simply send me any file, and I'll provide you with links to share with others.\n\n"
                "🔹 **Available Commands:**\n"
                "/help - How to use the bot\n"
                "/about - About the bot\n"
                "/ping - Check bot's response time\n\n"
                "Enjoy using the bot, and feel free to share your feedback!"
            )
            await message.reply_text(text=welcome_text)
        else:
            msg_id = int(args[-1])
            get_msg = await bot.get_messages(chat_id=Var.BIN_CHANNEL, message_ids=msg_id)
            file_name = get_name(get_msg)
            file_size = human_readable.humanbytes(get_media_file_size(get_msg))
            stream_link, online_link = await generate_media_links(get_msg)

            if file_name and file_size:
                await message.reply_text(
                    text=(
                        f"🔗 **Your Links are Ready!**\n\n"
                        f"📄 **File Name:** `{file_name}`\n"
                        f"📂 **File Size:** `{file_size}`\n\n"
                        f"📥 **Download Link:**\n{online_link}\n\n"
                        f"🖥️ **Watch Now:**\n{stream_link}\n\n"
                        "⏰ **Note:** Links are available as long as the bot is active."
                    ),
                    disable_web_page_preview=True,
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("🖥️ Watch Now", url=stream_link),
                            InlineKeyboardButton("📥 Download", url=online_link)
                        ]
                    ])
                )
            else:
                await handle_user_error(message, "Failed to retrieve file information.")
    except Exception as e:
        error_text = f"Error in start_command: {e}"
        logger.error(error_text, exc_info=True)
        await handle_user_error(message, "An unexpected error occurred.")
        await notify_owner(bot, error_text)

@StreamBot.on_message(filters.command("help") & filters.private)
async def help_command(bot: Client, message: Message):
    """Handle /help command."""
    try:
        await log_new_user(bot, message.from_user.id, message.from_user.first_name)
        help_text = (
            "ℹ️ **How to Use the File to Link Bot**\n\n"
            "🔹 **Generate Links:** Send me any file, and I'll provide you with direct download and streaming links.\n"
            "🔹 **In Groups:** Reply to a file with /link to get the download and streaming links.\n"
            "🔹 **In Channels:** Add me to your channel, and I'll automatically generate links for new posts.\n\n"
            "🔸 **Additional Commands:**\n"
            "/about - Learn more about the bot\n"
            "/ping - Check the bot's response time\n\n"
            "If you have any questions or need support, feel free to reach out!"
        )
        await message.reply_text(text=help_text, disable_web_page_preview=True)
    except Exception as e:
        error_text = f"Error in help_command: {e}"
        logger.error(error_text, exc_info=True)
        await handle_user_error(message, "An unexpected error occurred.")
        await notify_owner(bot, error_text)

@StreamBot.on_message(filters.command("about") & filters.private)
async def about_command(bot: Client, message: Message):
    """Handle /about command."""
    try:
        await log_new_user(bot, message.from_user.id, message.from_user.first_name)
        about_text = (
            "🤖 **About the File to Link Bot**\n\n"
            "This bot helps you generate direct download and streaming links for any file.\n\n"
            "🔹 **Features:**\n"
            " - Generate direct links for files\n"
            " - Support for all file types\n"
            " - Easy to use in private chats and groups\n\n"
            "Feel free to reach out if you have any questions or suggestions!"
        )
        await message.reply_text(text=about_text, disable_web_page_preview=True)
    except Exception as e:
        error_text = f"Error in about_command: {e}"
        logger.error(error_text, exc_info=True)
        await handle_user_error(message, "An unexpected error occurred.")
        await notify_owner(bot, error_text)

@StreamBot.on_message(filters.command("dc"))
async def dc_command(bot: Client, message: Message):
    """Handle /dc command with multiple functionalities."""
    try:
        # Log the user
        await log_new_user(bot, message.from_user.id, message.from_user.first_name)

        # Extract arguments
        args = message.text.strip().split(maxsplit=1)

        if len(args) > 1:
            # Argument provided (username or TGID)
            query = args[1].strip()

            if query.startswith('@'):
                # Handle username
                username = query[1:]
                try:
                    user = await bot.get_users(username)
                    dc_text = await generate_dc_text(user)

                    # Inline keyboard
                    dc_keyboard = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("🔍 View Profile", url=f"tg://user?id={user.id}")
                        ]
                    ])

                    await message.reply_text(dc_text, disable_web_page_preview=True, reply_markup=dc_keyboard, quote=True)
                except Exception as e:
                    await handle_user_error(message, FAILED_USER_INFO_MSG)
                    logger.error(f"Failed to get user info for username {username}: {e}", exc_info=True)
                return

            elif query.isdigit():
                # Handle TGID (Telegram User ID)
                user_id_arg = int(query)
                try:
                    user = await bot.get_users(user_id_arg)
                    dc_text = await generate_dc_text(user)

                    # Inline keyboard
                    dc_keyboard = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("🔍 View Profile", url=f"tg://user?id={user.id}")
                        ]
                    ])

                    await message.reply_text(dc_text, disable_web_page_preview=True, reply_markup=dc_keyboard, quote=True)
                except Exception as e:
                    await handle_user_error(message, FAILED_USER_INFO_MSG)
                    logger.error(f"Failed to get user info for TGID {user_id_arg}: {e}", exc_info=True)
                return
            else:
                await handle_user_error(message, INVALID_ARG_MSG)
                return

        # Check if the command is a reply to a message
        if message.reply_to_message:
            replied_msg = message.reply_to_message
            # Check if the replied message has media
            media = (
                replied_msg.photo or
                replied_msg.document or
                replied_msg.video or
                replied_msg.audio or
                replied_msg.voice or
                replied_msg.animation
            )
            if media:
                # Get the file_id from the media
                file_id = media.file_id
                # Get the file info
                file_info = await bot.get_file(file_id)
                dc_id = file_info.dc_id
                dc_text = f"🌐 **The media file's Data Center is:** `{dc_id}`"
                await message.reply_text(dc_text, quote=True)
            elif replied_msg.from_user:
                user = replied_msg.from_user
                dc_text = await generate_dc_text(user)
                # Inline keyboard
                dc_keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🔍 View Profile", url=f"tg://user?id={user.id}")
                    ]
                ])
                await message.reply_text(dc_text, disable_web_page_preview=True, reply_markup=dc_keyboard, quote=True)
            else:
                await handle_user_error(message, REPLY_DOES_NOT_CONTAIN_USER_MSG)
            return

        # Default case: No arguments and not a reply, return the DC of the command issuer
        user = message.from_user
        dc_text = await generate_dc_text(user)

        # Inline keyboard
        dc_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔍 View Profile", url=f"tg://user?id={user.id}")
            ]
        ])

        await message.reply_text(dc_text, disable_web_page_preview=True, reply_markup=dc_keyboard, quote=True)

    except Exception as e:
        error_text = f"Error in dc_command: {e}"
        logger.error(error_text, exc_info=True)
        await handle_user_error(message, "An unexpected error occurred.")
        # Do not notify the owner in DM

@StreamBot.on_message(filters.command("ping") & filters.private)
async def ping_command(bot: Client, message: Message):
    """Handle /ping command."""
    try:
        start_time = time.time()
        response = await message.reply_text("🏓 Pong!")
        end_time = time.time()
        time_taken_ms = (end_time - start_time) * 1000
        await response.edit(f"🏓 **Pong!**\n⏱ **Response Time:** `{time_taken_ms:.3f} ms`")
    except Exception as e:
        error_text = f"Error in ping_command: {e}"
        logger.error(error_text, exc_info=True)
        await handle_user_error(message, "An unexpected error occurred.")
        await notify_owner(bot, error_text)
