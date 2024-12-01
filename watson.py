# Bot for Sherlock by RocketGod
# Modified for Matrix use by NeedNotApply


import json
import logging
import os
import sys
import asyncio
import re
from nio import (
    AsyncClient,
    MatrixRoom,
    RoomMessageText,
    LoginResponse,
    InviteMemberEvent,
    JoinError,
)
import subprocess

logging.basicConfig(level=logging.INFO)

def load_config():
    try:
        with open('config.json', 'r') as file:
            return json.load(file)
    except Exception as e:
        logging.error(f"Error loading configuration: {e}")
        return None

async def send_message(client, room_id, content):
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

async def execute_sherlock(client, room_id, user_id, username, similar=False):
    if not username:
        await send_message(client, room_id, "Error: No username provided.")
        return

    if not is_valid_username(username):
        await send_message(
            client, room_id,
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
    await send_message(client, room_id, f"Searching {search_type} `{original_username}` for {user_id}")

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
            await send_message(client, room_id, "An error occurred while running Sherlock. Please try again later.")
            return

        # Parse the results from stdout
        results = []
        for line in stdout.splitlines():
            line = line.strip()
            if line and line.startswith("[+]") and "Error" not in line:
                # Extract the URL
                url = line.split(maxsplit=1)[1]
                results.append(url)

        total_results = len(results)

        await send_message(client, room_id, f"[*] Search completed with {total_results} results")

        if results:
            # Prepare the results message
            results_text = "\n".join(results)
            message = (
                f"Results for `{original_username}`:\n"
                f"```\n{results_text}\n```\n"
                f"Total Websites Username Detected On : {total_results}"
            )
            await send_message(client, room_id, message)
        else:
            await send_message(client, room_id, f"No results found for `{original_username}`.")

    except Exception as e:
        logging.error(f"Exception in execute_sherlock: {e}", exc_info=True)
        await send_message(client, room_id, "An internal error occurred while processing your request.")
        return

    await send_message(client, room_id, f"Finished report on `{original_username}` for {user_id}")

async def main():
    config = load_config()
    if not config:
        logging.error("Configuration could not be loaded. Exiting.")
        return

    client = AsyncClient(config["homeserver"], config["username"])
    login_response = await client.login(config["password"])

    if isinstance(login_response, LoginResponse):
        logging.info("Logged in successfully.")
    else:
        logging.error(f"Failed to login: {login_response}")
        return

    # Define the message handler
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
                        await send_message(client, room.room_id, "Usage: !sherlock <username>")
                        return
                    username = args[1]
                    await execute_sherlock(client, room.room_id, sender, username)

                elif message_content.startswith("!sherlock-similar "):
                    args = message_content.split(maxsplit=1)
                    if len(args) < 2:
                        await send_message(client, room.room_id, "Usage: !sherlock-similar <username>")
                        return
                    username = args[1]
                    await execute_sherlock(client, room.room_id, sender, username, similar=True)

                elif message_content.startswith("!help"):
                    help_message = (
                        "Available commands:\n"
                        "- `!sherlock <username>`: Search for the exact username on social networks.\n"
                        "- `!sherlock-similar <username>`: Search for similar usernames on social networks.\n"
                        "- `!help`: Display this help message."
                    )
                    await send_message(client, room.room_id, help_message)
            except Exception as e:
                logging.error(f"Exception in message_callback: {e}", exc_info=True)
                await send_message(client, room.room_id, "An error occurred while processing your command.")

    # Define the invite handler
    async def invite_callback(room, event):
        logging.info(f"Received invite for room {room.room_id} from {event.sender}")
        try:
            await client.join(room.room_id)
            logging.info(f"Joined room {room.room_id}")
        except JoinError as e:
            logging.error(f"Failed to join room {room.room_id}: {e}")

    client.add_event_callback(message_callback, RoomMessageText)
    client.add_event_callback(invite_callback, InviteMemberEvent)

    logging.info("Starting sync loop...")
    try:
        await client.sync_forever(timeout=30000)  # milliseconds
    except Exception as e:
        logging.error(f"An error occurred during sync: {e}", exc_info=True)
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
