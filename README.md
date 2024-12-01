# Watson - A Matrix Bot for Sherlock

Watson is a Matrix bot designed to interface with the [Sherlock project](https://github.com/sherlock-project/sherlock). It allows users to search for usernames on various social networks directly from Matrix using the power of Sherlock.  

Created by [RocketGod](https://github.com/rocketgot-git/)  
Modified for Matrix ecosystem by [NeedNotApply](https://github.com/neednotapply/)  

## Setup

### Prerequisites

This bot requires the Sherlock project to function. If you haven't already cloned the Sherlock repository, you can do so with the following command:

```bash
git clone https://github.com/sherlock-project/sherlock
```

### Installation

1. Navigate to the `sherlock_project` directory:

```bash
cd sherlock
cd sherlock_project
```

2. Clone the Watson repository into the `sherlock_project` directory:

```bash
git clone https://github.com/neednotapply/watson-matrix
```

3. Update the `config.json` file with your bot's username and password.  
   Optionally, change your bot's homeserver (where appropriate).  
   Your `config.json` should look like this:

```json
{
    "homeserver": "https://matrix.org",
    "username": "@your_bot:matrix.org",
    "password": "your_bot_password"
}
```

### Install the Prerequisites in Python

```bash
pip install matrix-nio aiohttp
```

### Run the Bot

- Execute the `watson.py` script:

```bash
py watson.py
```


## Usage

Once the bot is running, you can utilize the following commands on your Matrix Room:

- `!sherlock [username]`: Search for a specific username.
- `!sherlock-similar`: Check for similar usernames by replacing them with variations (e.g., '_', '-', '.').
- `!help`: Displays a list of available commands and their descriptions.

---

Thank you for using Watson! If you find any issues or have any feedback, feel free to contribute to the [Watson repository](https://github.com/RocketGod-git/watson).

![RocketGod](https://github.com/RocketGod-git/)  
![NeedNotApply](https://github.com/neednotapply/)
