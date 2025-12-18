# Bot for Sherlock by RocketGod
# Modified for Matrix use by NeedNotApply


import json
import logging
import os
import sys
import asyncio
import re
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlsplit

import discord
from discord import app_commands
from discord.ext import commands
from nio import (
    AsyncClient,
    RoomMessageText,
    LoginResponse,
    InviteMemberEvent,
    JoinError,
)

logging.basicConfig(level=logging.INFO)

SendFunc = Callable[[str], Awaitable[None]]


def load_config():
    script_dir = Path(__file__).resolve().parent
    configured_path = os.environ.get("WATSON_CONFIG")

    candidate_paths = []
    if configured_path:
        candidate_paths.append(Path(configured_path))

    candidate_paths.append(script_dir / "config.json")

    cwd_path = Path.cwd() / "config.json"
    if cwd_path not in candidate_paths:
        candidate_paths.append(cwd_path)

    for path in candidate_paths:
        try:
            with path.open('r') as file:
                logging.info(f"Loading configuration from {path}")
                return json.load(file)
        except FileNotFoundError:
            continue
        except Exception as e:
            logging.error(f"Error loading configuration from {path}: {e}")
            return None

    logging.error(
        "Error loading configuration. Tried: "
        + ", ".join(str(path) for path in candidate_paths)
    )
    return None


async def send_matrix_message(client, room_id, content):
    await client.room_send(
        room_id=room_id,
        message_type="m.room.message",
        content={
            "msgtype": "m.text",
            "body": content
        }
    )


def is_valid_username(username):
    # Define allowed characters: letters, numbers, underscores, hyphens, periods
    pattern = re.compile(r'^[A-Za-z0-9_\-\.]+$')
    return bool(pattern.match(username))

async def run_sherlock_process(args, timeout=300):
    sherlock_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sherlock_script = os.path.join(sherlock_dir, "sherlock.py")
    env = os.environ.copy()
    env["PYTHONPATH"] = sherlock_dir

    process = await asyncio.create_subprocess_exec(
        sys.executable, sherlock_script, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=sherlock_dir,
        env=env
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
        stdout = stdout_bytes.decode('utf-8', errors='replace')
        stderr = stderr_bytes.decode('utf-8', errors='replace')
        returncode = process.returncode

        return stdout, stderr, returncode
    except asyncio.TimeoutError:
        process.kill()
        return "", "Process timed out", -1
    except Exception as e:
        logging.error(f"Exception in run_sherlock_process: {e}", exc_info=True)
        return "", "An internal error occurred while running Sherlock.", -1

async def execute_sherlock(user_id, username, send_func: SendFunc, similar=False, platform: str = "matrix"):
    if not username:
        await send_func("Error: No username provided.")
        return

    if not is_valid_username(username):
        await send_func(
            "Error: The username contains invalid characters. "
            "Allowed characters are letters, numbers, underscores (_), hyphens (-), and periods (.)"
        )
        return

    sherlock_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result_file = os.path.join(sherlock_dir, f"{username}.txt")

    original_username = username  # Keep the original for messages

    if similar:
        # Replace '_', '-', '.' with '{?}' to search for similar usernames
        username = username.replace('_', '{?}').replace('-', '{?}').replace('.', '{?}')

    search_type = "similar usernames of" if similar else "username"
    await send_func(f"Searching {search_type} `{original_username}` for {user_id}")

    sherlock_args = [
        username,
        '--nsfw',
        '--print-found',
        '--no-color',
        '--timeout', '5',
        '--output', result_file,
        '--local',
    ]

    try:
        stdout, stderr, returncode = await run_sherlock_process(sherlock_args)

        if returncode != 0:
            logging.error(f"Sherlock exited with code {returncode}. Stderr: {stderr}")
            await send_func("An error occurred while running Sherlock. Please try again later.")
            return

        # Parse the results from stdout
        results = []
        for line in stdout.splitlines():
            line = line.strip()
            if line and line.startswith("[+]") and "Error" not in line:
                # Extract the platform name and URL (format: "[+] platform: url")
                content = line.split(maxsplit=1)[1]
                platform_label, _, url = content.partition(": ")
                platform_label = platform_label.strip()
                url = (url or content).strip()
                results.append((platform_label, url))

        total_results = len(results)

        if results:
            await send_func(f"Found {total_results} result(s) for `{original_username}`:")

            chunk = []
            current_length = 0
            max_chunk_size = 1900

            def format_line(platform_label: str, url: str) -> str:
                if platform == "discord":
                    link_text = platform_label or (urlsplit(url).netloc or url)
                    return f"- [{link_text}]({url})\n"

                return url + "\n"

            for platform_label, url in results:
                line = format_line(platform_label, url)
                if current_length + len(line) > max_chunk_size:
                    await send_func("".join(chunk))
                    chunk = []
                    current_length = 0

                chunk.append(line)
                current_length += len(line)

            if chunk:
                await send_func("".join(chunk))
        else:
            await send_func(f"No results found for `{original_username}`.")

    except Exception as e:
        logging.error(f"Exception in execute_sherlock: {e}", exc_info=True)
        await send_func("An internal error occurred while processing your request.")
        return


async def start_matrix_bot(config):
    matrix_cfg = config.get("matrix", {})
    homeserver = matrix_cfg.get("homeserver") or config.get("homeserver")
    username = matrix_cfg.get("username") or config.get("username")
    password = matrix_cfg.get("password") or config.get("password")

    if not all([homeserver, username, password]):
        logging.info("Matrix configuration incomplete. Skipping Matrix bot startup.")
        return

    client = AsyncClient(homeserver, username)
    login_response = await client.login(password)

    if isinstance(login_response, LoginResponse):
        logging.info("Logged in to Matrix successfully.")
    else:
        logging.error(f"Failed to login to Matrix: {login_response}")
        return

    async def message_callback(room, event):
        if event.sender == client.user:
            return  # Ignore messages from ourselves

        if isinstance(event, RoomMessageText):
            message_content = event.body.strip()
            sender = event.sender

            try:
                if message_content.startswith("!sherlock "):
                    args = message_content.split(maxsplit=1)
                    if len(args) < 2:
                        await send_matrix_message(client, room.room_id, "Usage: !sherlock <username>")
                        return
                    username_arg = args[1]
                    await execute_sherlock(sender, username_arg, lambda m: send_matrix_message(client, room.room_id, m))

                elif message_content.startswith("!sherlock-similar "):
                    args = message_content.split(maxsplit=1)
                    if len(args) < 2:
                        await send_matrix_message(client, room.room_id, "Usage: !sherlock-similar <username>")
                        return
                    username_arg = args[1]
                    await execute_sherlock(
                        sender,
                        username_arg,
                        lambda m: send_matrix_message(client, room.room_id, m),
                        similar=True,
                    )

                elif message_content.startswith("!help"):
                    help_message = (
                        "Available commands:\n"
                        "- `!sherlock <username>`: Search for the exact username on social networks.\n"
                        "- `!sherlock-similar <username>`: Search for similar usernames on social networks.\n"
                        "- `!help`: Display this help message."
                    )
                    await send_matrix_message(client, room.room_id, help_message)
            except Exception as e:
                logging.error(f"Exception in Matrix message_callback: {e}", exc_info=True)
                await send_matrix_message(client, room.room_id, "An error occurred while processing your command.")

    async def invite_callback(room, event):
        logging.info(f"Received invite for room {room.room_id} from {event.sender}")
        try:
            await client.join(room.room_id)
            logging.info(f"Joined room {room.room_id}")
        except JoinError as e:
            logging.error(f"Failed to join room {room.room_id}: {e}")

    client.add_event_callback(message_callback, RoomMessageText)
    client.add_event_callback(invite_callback, InviteMemberEvent)

    logging.info("Starting Matrix sync loop...")
    try:
        await client.sync_forever(timeout=30000)  # milliseconds
    except asyncio.CancelledError:
        logging.info("Matrix bot task cancelled. Shutting down Matrix client.")
    except Exception as e:
        logging.error(f"An error occurred during Matrix sync: {e}", exc_info=True)
    finally:
        await client.close()


async def start_discord_bot(config):
    discord_cfg = config.get("discord", {})
    token = discord_cfg.get("token") or config.get("discord_token")

    if not token:
        logging.info("Discord token not provided. Skipping Discord bot startup.")
        return

    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents, help_command=None)

    @bot.event
    async def on_ready():
        try:
            synced = await bot.tree.sync()
            logging.info(f"Logged in to Discord as {bot.user}. Synced {len(synced)} slash commands.")
        except Exception as sync_error:
            logging.error(f"Logged in to Discord as {bot.user} but failed to sync commands: {sync_error}")

    async def run_sherlock(interaction: discord.Interaction, username_arg: str | None, similar: bool = False):
        if not username_arg:
            command_name = "sherlock-similar" if similar else "sherlock"
            await interaction.response.send_message(
                f"Usage: /{command_name} <username>",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        async def send_followup(message: str):
            await interaction.followup.send(message)

        await execute_sherlock(
            interaction.user.mention,
            username_arg,
            send_followup,
            similar=similar,
            platform="discord",
        )

    @bot.tree.command(name="sherlock", description="Search for an exact username on social networks.")
    @app_commands.describe(username="The username to search for.")
    async def sherlock_command(interaction: discord.Interaction, username: str):
        await run_sherlock(interaction, username)

    @bot.tree.command(name="sherlock-similar", description="Search for similar usernames on social networks.")
    @app_commands.describe(username="The username to search for similar matches.")
    async def sherlock_similar_command(interaction: discord.Interaction, username: str):
        await run_sherlock(interaction, username, similar=True)

    @bot.tree.command(name="help", description="List available Watson commands.")
    async def help_command(interaction: discord.Interaction):
        help_message = (
            "Available commands:\n"
            "- `/sherlock <username>`: Search for the exact username on social networks.\n"
            "- `/sherlock-similar <username>`: Search for similar usernames on social networks.\n"
            "- `/help`: Display this help message."
        )
        await interaction.response.send_message(help_message, ephemeral=True)

    await bot.start(token)


async def main():
    config = load_config()
    if not config:
        logging.error("Configuration could not be loaded. Exiting.")
        return

    matrix_cfg = config.get("matrix", {})
    has_matrix = all(
        matrix_cfg.get(key)
        or config.get(key)
        for key in ["homeserver", "username", "password"]
    )

    discord_cfg = config.get("discord", {})
    has_discord = bool(discord_cfg.get("token") or config.get("discord_token"))

    tasks = []
    if has_matrix:
        tasks.append(asyncio.create_task(start_matrix_bot(config)))
    else:
        logging.info("Matrix configuration missing. Provide homeserver, username, and password to enable Matrix support.")

    if has_discord:
        tasks.append(asyncio.create_task(start_discord_bot(config)))
    else:
        logging.info("Discord configuration missing. Provide discord_token to enable Discord support.")

    if not tasks:
        logging.error("No bot services configured. Please provide Matrix and/or Discord credentials in config.json.")
        return

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
