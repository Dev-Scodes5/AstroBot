# AstroBot
AstroBot is an interactive Discord bot that makes complex aerospace data accessible. It fetches real-time telemetry and imagery from NASA's public APIs and uses an LLM to translate raw, technical jargon into engaging, easy to understand educational summaries for high school students and casual space enthusiasts.
---
# How to use

First of all, you need **Python 3.10** or newer, preferably *3.12*.
You can download Python here: [Download](https://www.python.org/downloads/)

## NOTES:
When installing:
- Check "**Add Python to PATH**"
- Choose "Install for all users"
---
Also install git, you can get it here: [Git](https://git-scm.com/install).

Clone the repository:

```bash
git clone https://github.com/Dev-Scodes5/AstroBot.git
```

enter the directory:
```bash
cd AstroBot
```
install the required libraries:
```bash
pip install -r requirements.txt
```


Inside the directory, create a new file called:
```bash
.env
```
paste this inside:
DISCORD_TOKEN=YOUR_DISCORD_BOT_TOKEN
NASA_API_KEY=YOUR_NASA_API_KEY
GEMINI_API_KEY=YOUR_GEMINI_API_KEY

## Where to get the keys

| Key                | Where to Get It                                           |
|--------------------|-----------------------------------------------------------|
| Discord Bot Token  | https://discord.com/developers/applications              |
| NASA API Key       | https://api.nasa.gov                                     |
| Gemini API Key     | https://aistudio.google.com                              |

## Invite the bot to Your Server
Go to the Discord Developer Portal > AstroBot > OAuth2 > URL Generator.
Select:
- bot
- applications.commands
Bot permissions:
- Send Messages
- Embed Links
- Read Message History
Copy the generated URL and open it in your browser to invite the bot.
---

## Run the Bot
In your terminal:
```bash
python main.py
```
If everything worked, you'll see:
```bash
Logged in as AstroBot
```

## Extra: Use the Commands
In your Discord server:

### Get today’s APOD:
```
!apod
```

### Get multiple APODs:
```
!apod 5
```

### Save an APOD:
```
!save_apod 2024-01-01
```

### View favorites:
```
!my_favorites
```

### Remove a favorite:
```
!remove_favorite 2024-01-01
```

### Clear all favorites:
```
!clear_favorites
```

### Track near-Earth asteroids:
```
!asteroids
```

### Calculate asteroid impact energy:
```
!impact Apophis
```