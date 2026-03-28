import discord
from discord.ext import commands
import aiohttp
import asyncio
import logging
import os
from typing import Optional
from google import genai
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
NASA_API_KEY = os.getenv('NASA_API_KEY', 'DEMO_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_MODEL = 'gemini-1.5-flash'

# Configure LLM client
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Constants
NASA_TIMEOUT = aiohttp.ClientTimeout(total=10)
LLM_SYSTEM_PROMPT = """
You are an enthusiastic astrophysics communicator for high schoolers.
Take the following highly technical description from NASA and summarize it
in 2-3 engaging, easy-to-understand paragraphs. Keep it fun but scientifically accurate.
"""

class AstroBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        self.session: Optional[aiohttp.ClientSession] = None

    async def setup_hook(self) -> None:
        """Initialize aiohttp session on startup."""
        self.session = aiohttp.ClientSession()
        logger.info("Bot session initialized")
        
        # Load the Space Systems Cog
        try:
            await self.load_extension('cogs.space_systems')
            logger.info("Loaded extension: space_systems")
        except Exception as e:
            logger.exception(f"Failed to load extension space_systems: {e}")

    async def close(self) -> None:
        """Gracefully close the session."""
        if self.session:
            await self.session.close()
        await super().close()

    async def on_ready(self) -> None:
        logger.info(f'Logged in as {self.user} (ID: {self.user.id})')

# Instantiate bot
bot = AstroBot()

async def fetch_nasa_data(url: str) -> Optional[dict]:
    """Fetch JSON from NASA API with error handling and timeout."""
    if not bot.session:
        logger.error("Session not initialized")
        return None
    
    try:
        async with bot.session.get(url, timeout=NASA_TIMEOUT) as response:
            if response.status == 200:
                return await response.json()
            else:
                logger.warning(f"NASA API returned {response.status}")
                return None
    except asyncio.TimeoutError:
        logger.error("NASA request timeout")
        return None
    except Exception as e:
        logger.exception(f"Error fetching NASA data: {e}")
        return None

async def simplify_with_llm(technical_text: str) -> str:
    """
    Pass raw text to Gemini for simplification.
    Runs in thread pool to avoid blocking the event loop.
    """
    prompt = f"{LLM_SYSTEM_PROMPT}\n\nRaw text:\n{technical_text}"
    
    try:
        # Run blocking LLM call in thread pool
        response = await asyncio.to_thread(
            gemini_client.models.generate_content,
            model=GEMINI_MODEL,
            contents=prompt,
        )
        return response.text
    except Exception as e:
        logger.exception(f"LLM error: {e}")
        return "Sorry, my AI brain is fuzzy right now. Could not translate the data!"

@bot.command(name='apod')
async def apod_command(ctx: commands.Context) -> None:
    """Fetch and explain the Astronomy Picture of the Day."""
    async with ctx.typing():
        # Fetch data
        url = f"https://api.nasa.gov/planetary/apod?api_key={NASA_API_KEY}"
        nasa_data = await fetch_nasa_data(url)
        
        if not nasa_data:
            await ctx.send("🚨 Houston, we have a problem reaching NASA's databases right now.")
            return
        
        title = nasa_data.get('title', 'Unknown Title')
        raw_explanation = nasa_data.get('explanation', '')
        image_url = nasa_data.get('url', '')
        
        # Simplify via LLM (non-blocking)
        simplified_explanation = await simplify_with_llm(raw_explanation)
        
        # Format output
        embed = discord.Embed(
            title=f"🌌 {title}",
            description=simplified_explanation,
            color=discord.Color.from_rgb(252, 61, 33)  # NASA red
        )
        embed.set_thumbnail(url="https://www.nasa.gov/wp-content/uploads/2023/03/nasa-logo-web-rgb.png")
        embed.set_image(url=image_url)
        embed.set_footer(
            text="Data: NASA APOD API | Translation: Gemini AI",
            icon_url="https://cdn-icons-png.flaticon.com/512/2906/2906496.png"
        )
        
        await ctx.send(embed=embed)

if __name__ == '__main__':
    if not DISCORD_TOKEN:
        logger.error("ERROR: DISCORD_TOKEN not set in .env")
        exit(1)
    
    logger.info("Starting AstroBot...")
    bot.run(DISCORD_TOKEN)