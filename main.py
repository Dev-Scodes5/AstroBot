import discord
from discord.ext import commands
import aiohttp
import os
from google import genai
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
NASA_API_KEY = os.getenv('NASA_API_KEY', 'DEMO_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Configure the LLM Client
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

class AstroBot(commands.Bot):
    def __init__(self):
        # Set up intents (required by Discord to read messages)
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
        # We will create an aiohttp session when the bot starts
        self.session = None

    async def setup_hook(self):
        "This runs once when the bot starts up. Good for initializing web sessions."
        self.session = aiohttp.ClientSession()

    async def close(self):
        "Ensures the web session closes cleanly if the bot shuts down."
        if self.session:
            await self.session.close()
        await super().close()

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

# Instantiate the bot
bot = AstroBot()

async def fetch_nasa_data(url: str):
    "Handles the asynchronous HTTP request to NASA with error handling."
    try:
        async with bot.session.get(url) as response:
            if response.status == 200:
                return await response.json()
            else:
                return None
    except Exception as e:
        print(f"Network error: {e}")
        return None

def simplify_with_llm(technical_text: str) -> str:
    "Passes the raw text to the LLM for simplification."
    prompt = f"""
    You are an enthusiastic astrophysics communicator for high schoolers. 
    Take the following highly technical description from NASA and summarize it 
    in 2-3 engaging, easy to understand paragraphs. Keep it fun but scientifically accurate.
    
    Raw text: {technical_text}
    """
    try:
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text
    except Exception as e:
        print(f"LLM Error: {e}")
        return "Sorry, my AI brain is a bit fuzzy right now. Could not translate the data!"

# Bot Command to fetch and explain the Astronomy Picture of the Day

@bot.command(name='apod')
async def apod_command(ctx):
    """Fetches the Astronomy Picture of the Day and explains it."""
    # 1. Let the user know the bot is "thinking"
    async with ctx.typing():
        
        # 2. Fetch data from NASA
        url = f"https://api.nasa.gov/planetary/apod?api_key={NASA_API_KEY}"
        nasa_data = await fetch_nasa_data(url)
        
        if not nasa_data:
            await ctx.send("🚨 Houston, we have a problem reaching NASA's databases right now.")
            return

        title = nasa_data.get('title', 'Unknown Title')
        raw_explanation = nasa_data.get('explanation', '')
        image_url = nasa_data.get('url', '')

        # 3. Process the text through the LLM
        simplified_explanation = simplify_with_llm(raw_explanation)

        # 4. Format the output into a clean UI (Discord Embed)
        embed = discord.Embed(
            title=f"🌌 {title}",
            description=simplified_explanation,
            color=discord.Color.blue()
        )
        embed.set_image(url=image_url)
        embed.set_footer(text="Data: NASA APOD API | Translation: AI")

    # 5. Send the final result
    await ctx.send(embed=embed)

# Run the application
if __name__ == '__main__':
    if not DISCORD_TOKEN:
        print("ERROR: Please set your DISCORD_TOKEN in the .env file.")
    else:
        bot.run(DISCORD_TOKEN)