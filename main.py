import discord
from discord.ext import commands
import aiohttp
import asyncio
import logging
import os
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from functools import wraps
from google import genai
from dotenv import load_dotenv
from discord.ui import Button, View

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

class Config:
    """Centralized config. Easy to audit and override."""
    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
    NASA_API_KEY = os.getenv('NASA_API_KEY', 'DEMO_KEY')
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    GEMINI_MODEL = 'gemini-2.5-flash'

    # Timeouts & Limits
    NASA_TIMEOUT = aiohttp.ClientTimeout(total=10)
    CACHE_TTL_HOURS = 24
    RATE_LIMIT_SECONDS = 5
    MAX_APOD_COUNT = 30

    # Prompts
    LLM_SYSTEM_PROMPT = """
You are an enthusiastic astrophysics communicator for high schoolers.
Take the following highly technical description from NASA and summarize it
in 2-3 engaging, easy-to-understand paragraphs. Keep it fun but scientifically accurate.
"""

    @staticmethod
    def validate() -> bool:
        if not Config.DISCORD_TOKEN:
            logger.error("DISCORD_TOKEN not set")
            return False
        if not Config.GEMINI_API_KEY:
            logger.error("GEMINI_API_KEY not set")
            return False
        return True

class APIError(Exception): pass
class LLMError(Exception): pass
class RateLimitError(Exception): pass

# ==================== UI VIEWS ====================
class PaginationView(View):
    """Generic navigation buttons for browsing multiple Embeds."""
    def __init__(self, embeds: list, owner_id: int, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.owner_id = owner_id
        self.current_index = 0

    def update_buttons(self) -> None:
        self.prev_button.disabled = (self.current_index == 0)
        self.next_button.disabled = (self.current_index == len(self.embeds) - 1)

    @discord.ui.button(label="◀️ Prev", style=discord.ButtonStyle.primary)
    async def prev_button(self, interaction: discord.Interaction, button: Button) -> None:
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ You can't control someone else's pagination!", ephemeral=True)
        if self.current_index > 0:
            self.current_index -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current_index], view=self)

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: Button) -> None:
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ You can't control someone else's pagination!", ephemeral=True)
        if self.current_index < len(self.embeds) - 1:
            self.current_index += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embeds[self.current_index], view=self)

class APODPaginationView(View):
    """Navigation buttons for browsing multiple APOD images."""
    def __init__(self, apods: list, owner_id: int, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.apods = apods
        self.owner_id = owner_id
        self.current_index = 0

    def get_embed(self) -> discord.Embed:
        apod = self.apods[self.current_index]
        title = apod.get('title', 'Unknown Title')
        raw_explanation = apod.get('explanation', '')
        image_url = apod.get('url', '')
        date = apod.get('date', 'Unknown')

        embed = discord.Embed(
            title=f"🌌 {title}",
            description=raw_explanation[:400] + "..." if len(raw_explanation) > 400 else raw_explanation,
            color=discord.Color.from_rgb(252, 61, 33)
        )
        embed.set_image(url=image_url)
        embed.add_field(name="Date", value=date, inline=True)
        embed.add_field(name="Page", value=f"{self.current_index + 1}/{len(self.apods)}", inline=True)
        embed.set_footer(text="Data: NASA APOD | Simplified: Gemini AI")
        return embed

    def update_buttons(self) -> None:
        self.prev_button.disabled = (self.current_index == 0)
        self.next_button.disabled = (self.current_index == len(self.apods) - 1)

    @discord.ui.button(label="◀️ Prev", style=discord.ButtonStyle.primary)
    async def prev_button(self, interaction: discord.Interaction, button: Button) -> None:
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ You can't control someone else's pagination!", ephemeral=True)
        if self.current_index > 0:
            self.current_index -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: Button) -> None:
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ You can't control someone else's pagination!", ephemeral=True)
        if self.current_index < len(self.apods) - 1:
            self.current_index += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

# ==================== DATA & UTILS ====================
class CacheManager:
    def __init__(self, ttl_hours: int = 24):
        self.cache: Dict[str, tuple[Any, datetime]] = {}
        self.ttl = timedelta(hours=ttl_hours)

    def get(self, key: str) -> Optional[Any]:
        if key not in self.cache: return None
        value, timestamp = self.cache[key]
        if datetime.now() - timestamp > self.ttl:
            del self.cache[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self.cache[key] = (value, datetime.now())

    def clear(self) -> None:
        self.cache.clear()

class RateLimiter:
    def __init__(self, cooldown_seconds: int = 5):
        self.cooldowns: Dict[int, datetime] = {}
        self.cooldown = timedelta(seconds=cooldown_seconds)

    def is_on_cooldown(self, user_id: int) -> bool:
        if user_id not in self.cooldowns: return False
        if datetime.now() - self.cooldowns[user_id] > self.cooldown:
            del self.cooldowns[user_id]
            return False
        return True

    def apply(self, user_id: int) -> None:
        self.cooldowns[user_id] = datetime.now()

    def remaining(self, user_id: int) -> float:
        if user_id not in self.cooldowns: return 0
        remaining = self.cooldown - (datetime.now() - self.cooldowns[user_id])
        return max(0, remaining.total_seconds())

def with_rate_limit(limiter: RateLimiter):
    def decorator(func):
        @wraps(func)
        async def wrapper(ctx: commands.Context, *args, **kwargs):
            user_id = ctx.author.id
            if limiter.is_on_cooldown(user_id):
                remaining = limiter.remaining(user_id)
                await ctx.send(f"⏱️ Slow down! Try again in {remaining:.1f} seconds.", delete_after=5)
                raise RateLimitError(f"User {user_id} rate-limited")
            limiter.apply(user_id)
            return await func(ctx, *args, **kwargs)
        return wrapper
    return decorator

async def retry_with_backoff(func, *args, max_retries: int = 3, base_delay: float = 1.0, **kwargs):
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries - 1: raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Attempt {attempt + 1} failed, retrying in {delay}s: {e}")
            await asyncio.sleep(delay)

# ==================== BOT ====================
class AstroBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = CacheManager(Config.CACHE_TTL_HOURS)
        self.rate_limiter = RateLimiter(Config.RATE_LIMIT_SECONDS)

    async def setup_hook(self) -> None:
        self.session = aiohttp.ClientSession()
        try:
            await self.load_extension('cogs.space_systems')
        except Exception as e:
            logger.exception(f"Failed to load cogs.space_systems: {e}")

    async def close(self) -> None:
        if self.session: await self.session.close()
        self.cache.clear()
        await super().close()

    async def on_ready(self) -> None:
        logger.info(f'Logged in as {self.user}')

bot = AstroBot()
bot.help_command = None 
gemini_client = genai.Client(api_key=Config.GEMINI_API_KEY)

async def fetch_nasa_data(url: str, use_cache: bool = True) -> Optional[dict]:
    if not bot.session: raise APIError("Session not ready")
    if use_cache:
        cached = bot.cache.get(url)
        if cached: return cached

    async def _fetch():
        async with bot.session.get(url, timeout=Config.NASA_TIMEOUT) as response:
            if response.status == 200:
                data = await response.json()
                if use_cache: bot.cache.set(url, data)
                return data
            raise APIError(f"NASA API returned {response.status}")
    try:
        return await retry_with_backoff(_fetch, max_retries=3)
    except asyncio.TimeoutError:
        raise APIError("NASA request timeout after retries")
    except Exception as e:
        raise APIError(str(e))

async def simplify_with_llm(technical_text: str, fallback: Optional[str] = None) -> str:
    cache_key = f"llm:{hash(technical_text)}"
    cached = bot.cache.get(cache_key)
    if cached: return cached

    prompt = f"{Config.LLM_SYSTEM_PROMPT}\n\nRaw text:\n{technical_text}"
    try:
        response = await asyncio.to_thread(
            gemini_client.models.generate_content,
            model=Config.GEMINI_MODEL,
            contents=prompt,
        )
        result = response.text
        bot.cache.set(cache_key, result)
        return result
    except Exception as e:
        if fallback: return fallback
        return "🔧 AI summary unavailable. Here's the raw explanation:\n" + technical_text[:500] + "..."

# ==================== COMMANDS ====================
@bot.command(name='apod')
@with_rate_limit(bot.rate_limiter)
async def apod_command(ctx: commands.Context, count: int = 1) -> None:
    if count < 1 or count > Config.MAX_APOD_COUNT:
        await ctx.send(f"⚠️ Count must be 1–{Config.MAX_APOD_COUNT}. Using count=1.", delete_after=5)
        count = 1

    async with ctx.typing():
        try:
            url = f"https://api.nasa.gov/planetary/apod?api_key={Config.NASA_API_KEY}&count={count}"
            nasa_data = await fetch_nasa_data(url)
            if not nasa_data: raise APIError("No data returned from NASA")

            apods = nasa_data if isinstance(nasa_data, list) else [nasa_data]
            if not apods: return await ctx.send("❌ No APOD data found.")

            apod = apods[0]
            simplified = await simplify_with_llm(apod.get('explanation', ''))

            embed = discord.Embed(
                title=f"🌌 {apod.get('title', 'Unknown Title')}",
                description=simplified,
                color=discord.Color.from_rgb(252, 61, 33)
            )
            embed.set_thumbnail(url="https://www.nasa.gov/wp-content/uploads/2023/03/nasa-logo-web-rgb.png")
            embed.set_image(url=apod.get('url', ''))
            embed.add_field(name="Date", value=apod.get('date', 'Unknown'), inline=True)

            view = None
            if len(apods) > 1:
                embed.add_field(name="Pages", value=f"1 of {len(apods)}", inline=True)
                view = APODPaginationView(apods, ctx.author.id)
                view.update_buttons()

            embed.set_footer(text="Data: NASA APOD | Simplified: Gemini AI")
            await ctx.send(embed=embed, view=view)

        except Exception as e:
            await ctx.send(f"❌ Error: {e}")

@bot.command(name='save_apod')
async def save_apod_command(ctx: commands.Context, date: str = None) -> None:
    async with ctx.typing():
        try:
            if not date: date = datetime.now().strftime('%Y-%m-%d')
            url = f"https://api.nasa.gov/planetary/apod?api_key={Config.NASA_API_KEY}&date={date}"
            apod = await fetch_nasa_data(url)
            if not apod: return await ctx.send(f"❌ Could not fetch APOD for {date}")

            added = favorites_manager.add_favorite(ctx.author.id, apod)
            if added:
                await ctx.send(f"✅ Saved **{apod.get('title', 'Unknown')}** ({date}) to favorites!")
            else:
                await ctx.send(f"⚠️ This APOD is already in your favorites.")
        except Exception as e:
            await ctx.send("❌ Something went wrong.")

@bot.command(name='my_favorites')
async def my_favorites_command(ctx: commands.Context) -> None:
    async with ctx.typing():
        try:
            favorites = favorites_manager.get_favorites(ctx.author.id)
            if not favorites:
                return await ctx.send("📭 You don't have any saved APODs yet.")

            embeds = []
            for fav in favorites:
                embed = discord.Embed(title=f"⭐ {fav.get('title', 'Unknown')}", color=discord.Color.from_rgb(255, 215, 0))
                embed.add_field(name="Date", value=fav.get('date'), inline=False)
                embed.add_field(name="Saved At", value=fav.get('favorited_at', 'Unknown').split('T')[0], inline=False)
                embed.set_image(url=fav.get('url'))
                embeds.append(embed)

            if len(embeds) == 1:
                await ctx.send(embed=embeds[0])
            else:
                view = PaginationView(embeds, ctx.author.id)
                view.update_buttons()
                await ctx.send(embed=embeds[0], view=view)

        except Exception as e:
            await ctx.send("❌ Something went wrong.")

@bot.command(name='remove_favorite')
async def remove_favorite_command(ctx: commands.Context, date: str) -> None:
    async with ctx.typing():
        try:
            removed = favorites_manager.remove_favorite(ctx.author.id, date)
            if removed: await ctx.send(f"✅ Removed APOD from {date} from favorites.")
            else: await ctx.send(f"❌ APOD from {date} not found in your favorites.")
        except Exception as e:
            await ctx.send("❌ Something went wrong.")

@bot.command(name='clear_favorites')
async def clear_favorites_command(ctx: commands.Context) -> None:
    async with ctx.typing():
        try:
            count = favorites_manager.clear_favorites(ctx.author.id)
            await ctx.send(f"🗑️ Cleared {count} APODs from your favorites.")
        except Exception as e:
            await ctx.send("❌ Something went wrong.")

@bot.command(name='cache')
@commands.is_owner()
async def cache_command(ctx: commands.Context, action: str = "info") -> None:
    if action == "clear":
        bot.cache.clear()
        await ctx.send("✓ Cache cleared")
    elif action == "info":
        await ctx.send(f"📊 Cache entries: {len(bot.cache.cache)}")
    else:
        await ctx.send("⚠️ Unknown action. Use: info, clear")

@bot.command(name='help')
async def help_command(ctx: commands.Context, topic: str = None) -> None:
    embed = discord.Embed(title="🚀 AstroBot Help", color=discord.Color.from_rgb(70, 130, 180))
    if not topic:
        embed.description = "Explore space with NASA data!"
        embed.add_field(name="📡 APOD", value="`!apod`", inline=False)
        embed.add_field(name="⭐ Favorites", value="`!save_apod`, `!my_favorites`, `!clear_favorites`", inline=False)
    else:
        embed.description = f"Help topic for: {topic}"
    await ctx.send(embed=embed)

@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandNotFound): return
    if isinstance(error, RateLimitError): return # We already sent a message in the decorator
    await ctx.send("❌ An error occurred with your command. Check usage with `!help`.", delete_after=5)

if __name__ == '__main__':
    if not Config.validate(): exit(1)
    bot.run(Config.DISCORD_TOKEN)