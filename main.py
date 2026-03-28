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
logger = logging.getLogger(__name__)  # ✓ FIXED: __name__

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
    RATE_LIMIT_SECONDS = 5  # Per-user cooldown
    MAX_APOD_COUNT = 30  # Safety limit for bulk requests

    # Prompts
    LLM_SYSTEM_PROMPT = """
You are an enthusiastic astrophysics communicator for high schoolers.
Take the following highly technical description from NASA and summarize it
in 2-3 engaging, easy-to-understand paragraphs. Keep it fun but scientifically accurate.
"""

    @staticmethod
    def validate() -> bool:
        """Validate required env vars."""
        if not Config.DISCORD_TOKEN:
            logger.error("DISCORD_TOKEN not set")
            return False
        if not Config.GEMINI_API_KEY:
            logger.error("GEMINI_API_KEY not set")
            return False
        return True

class APIError(Exception):
    """NASA API error."""
    pass

class LLMError(Exception):
    """Gemini LLM error."""
    pass

class RateLimitError(Exception):
    """User hit rate limit."""
    pass

class APODPaginationView(View):
    """Navigation buttons for browsing multiple APOD images."""

    def __init__(self, apods: list, owner_id: int, timeout: int = 300):
        """
        Args:
            apods: List of APOD dictionaries from NASA
            owner_id: Discord user ID (only they can click buttons)
            timeout: Inactivity timeout in seconds
        """
        super().__init__(timeout=timeout)
        self.apods = apods
        self.owner_id = owner_id
        self.current_index = 0

    def get_embed(self) -> discord.Embed:
        """Generate embed for current image."""
        apod = self.apods[self.current_index]

        title = apod.get('title', 'Unknown Title')
        raw_explanation = apod.get('explanation', '')
        image_url = apod.get('url', '')
        date = apod.get('date', 'Unknown')

        # We already have simplified text, so use raw for now
        # (In production, you'd cache this per image)
        embed = discord.Embed(
            title=f"🌌 {title}",
            description=raw_explanation[:400] + "..." if len(raw_explanation) > 400 else raw_explanation,
            color=discord.Color.from_rgb(252, 61, 33)
        )
        embed.set_image(url=image_url)
        embed.add_field(name="Date", value=date, inline=True)
        embed.add_field(
            name="Page",
            value=f"{self.current_index + 1}/{len(self.apods)}",
            inline=True
        )
        embed.set_footer(text="Data: NASA APOD | Simplified: Gemini AI")

        return embed

    def update_buttons(self) -> None:
        """Enable/disable buttons based on current position."""
        # Disable Prev if on first image
        self.prev_button.disabled = (self.current_index == 0)
        # Disable Next if on last image
        self.next_button.disabled = (self.current_index == len(self.apods) - 1)

    @discord.ui.button(label="◀️ Prev", style=discord.ButtonStyle.primary)
    async def prev_button(self, interaction: discord.Interaction, button: Button) -> None:
        """Go to previous image."""
        # Only owner can click
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ You can't control someone else's pagination!",
                ephemeral=True
            )
            return

        if self.current_index > 0:
            self.current_index -= 1
            self.update_buttons()
            await interaction.response.edit_message(
                embed=self.get_embed(),
                view=self
            )
        else:
            await interaction.response.send_message(
                "⏪ Already at first image!",
                ephemeral=True
            )

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: Button) -> None:
        """Go to next image."""
        # Only owner can click
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ You can't control someone else's pagination!",
                ephemeral=True
            )
            return

        if self.current_index < len(self.apods) - 1:
            self.current_index += 1
            self.update_buttons()
            await interaction.response.edit_message(
                embed=self.get_embed(),
                view=self
            )
        else:
            await interaction.response.send_message(
                "⏩ Already at last image!",
                ephemeral=True
            )

class CacheManager:
    """Simple in-memory cache with TTL."""
    def __init__(self, ttl_hours: int = 24):
        self.cache: Dict[str, tuple[Any, datetime]] = {}
        self.ttl = timedelta(hours=ttl_hours)

    def get(self, key: str) -> Optional[Any]:
        """Retrieve from cache if not expired."""
        if key not in self.cache:
            return None
        value, timestamp = self.cache[key]
        if datetime.now() - timestamp > self.ttl:
            del self.cache[key]
            return None
        logger.debug(f"Cache hit: {key}")
        return value

    def set(self, key: str, value: Any) -> None:
        """Store in cache."""
        self.cache[key] = (value, datetime.now())
        logger.debug(f"Cache set: {key}")

    def clear(self) -> None:
        """Clear all cache."""
        self.cache.clear()

class RateLimiter:
    """Per-user cooldown tracker."""
    def __init__(self, cooldown_seconds: int = 5):
        self.cooldowns: Dict[int, datetime] = {}
        self.cooldown = timedelta(seconds=cooldown_seconds)

    def is_on_cooldown(self, user_id: int) -> bool:
        """Check if user is rate-limited."""
        if user_id not in self.cooldowns:
            return False
        if datetime.now() - self.cooldowns[user_id] > self.cooldown:
            del self.cooldowns[user_id]
            return False
        return True

    def apply(self, user_id: int) -> None:
        """Mark user as used."""
        self.cooldowns[user_id] = datetime.now()

    def remaining(self, user_id: int) -> float:
        """Seconds until user can use command."""
        if user_id not in self.cooldowns:
            return 0
        remaining = self.cooldown - (datetime.now() - self.cooldowns[user_id])
        return max(0, remaining.total_seconds())

def with_rate_limit(limiter: RateLimiter):
    """Decorator to enforce per-user rate limiting (fixed for functions, not methods)."""
    def decorator(func):
        @wraps(func)
        async def wrapper(ctx: commands.Context, *args, **kwargs):  # ✓ FIXED: No 'self'
            user_id = ctx.author.id
            if limiter.is_on_cooldown(user_id):
                remaining = limiter.remaining(user_id)
                await ctx.send(
                    f"⏱️ Slow down! Try again in {remaining:.1f} seconds.",
                    delete_after=5
                )
                return  # Don't raise, just return
            limiter.apply(user_id)
            return await func(ctx, *args, **kwargs)
        return wrapper
    return decorator

async def retry_with_backoff(coro, max_retries: int = 3, base_delay: float = 1.0):
    """Exponential backoff retry logic."""
    for attempt in range(max_retries):
        try:
            return await coro
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Attempt {attempt + 1} failed, retrying in {delay}s: {e}")
            await asyncio.sleep(delay)

class AstroBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)  # ✓ FIXED: __init__
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = CacheManager(Config.CACHE_TTL_HOURS)
        self.rate_limiter = RateLimiter(Config.RATE_LIMIT_SECONDS)

    async def setup_hook(self) -> None:
        """Initialize session and load cogs."""
        self.session = aiohttp.ClientSession()
        logger.info("✓ Session initialized")

        try:
            await self.load_extension('cogs.space_systems')
            logger.info("✓ Loaded extension: space_systems")
        except Exception as e:
            logger.exception(f"Failed to load cogs.space_systems: {e}")

    async def close(self) -> None:
        """Gracefully close session."""
        if self.session:
            await self.session.close()
        self.cache.clear()
        logger.info("✓ Bot shutdown complete")
        await super().close()

    async def on_ready(self) -> None:
        logger.info(f'✓ Logged in as {self.user} (ID: {self.user.id})')

bot = AstroBot()
gemini_client = genai.Client(api_key=Config.GEMINI_API_KEY)

# NASA Api Wrapper
async def fetch_nasa_data(url: str, use_cache: bool = True) -> Optional[dict]:
    """
    Fetch JSON from NASA API with caching, timeout, and retry.

    Args:
        url: Full NASA API URL
        use_cache: Whether to use cache

    Returns:
        Parsed JSON or None

    Raises:
        APIError: If all retries exhausted
    """
    if not bot.session:
        logger.error("Session not initialized")
        raise APIError("Session not ready")

    # Check cache first
    if use_cache:
        cached = bot.cache.get(url)
        if cached:
            return cached

    async def _fetch():
        async with bot.session.get(url, timeout=Config.NASA_TIMEOUT) as response:
            if response.status == 200:
                data = await response.json()
                if use_cache:
                    bot.cache.set(url, data)
                return data
            else:
                raise APIError(f"NASA API returned {response.status}")

    try:
        return await retry_with_backoff(_fetch(), max_retries=3)
    except asyncio.TimeoutError:
        raise APIError("NASA request timeout after retries")
    except Exception as e:
        logger.exception(f"Failed to fetch NASA data: {e}")
        raise APIError(str(e))

async def simplify_with_llm(technical_text: str, fallback: Optional[str] = None) -> str:
    """
    Summarize technical text via Gemini.

    Args:
        technical_text: Raw explanation from NASA
        fallback: Fallback text if LLM fails

    Returns:
        Simplified explanation or fallback
    """
    # Check if we've already simplified this
    cache_key = f"llm:{hash(technical_text)}"
    cached = bot.cache.get(cache_key)
    if cached:
        return cached

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
        logger.exception(f"LLM error: {e}")
        if fallback:
            return fallback
        return "🔧 AI summary unavailable. Here's the raw explanation:\n" + technical_text[:500] + "..."

@bot.command(name='apod')
@with_rate_limit(bot.rate_limiter)
async def apod_command(ctx: commands.Context, count: int = 1) -> None:
    """
    Fetch and explain the Astronomy Picture of the Day.

    Usage:
        !apod              # Today's APOD
        !apod 7            # Last 7 days (with navigation buttons)
    """
    # Validate count
    if count < 1 or count > Config.MAX_APOD_COUNT:
        await ctx.send(
            f"⚠️ Count must be 1–{Config.MAX_APOD_COUNT}. Using count=1.",
            delete_after=5
        )
        count = 1

    async with ctx.typing():
        try:
            url = f"https://api.nasa.gov/planetary/apod?api_key={Config.NASA_API_KEY}&count={count}"
            nasa_data = await fetch_nasa_data(url)

            if not nasa_data:
                raise APIError("No data returned from NASA")

            # Handle list vs single object
            if isinstance(nasa_data, list):
                apods = nasa_data
            else:
                apods = [nasa_data]

            if not apods:
                await ctx.send("❌ No APOD data found for the requested dates.")
                return

            # Get first APOD
            apod = apods[0]
            title = apod.get('title', 'Unknown Title')
            raw_explanation = apod.get('explanation', '')
            image_url = apod.get('url', '')
            date = apod.get('date', 'Unknown')

            # Simplify via LLM (cached if available)
            simplified = await simplify_with_llm(raw_explanation)

            embed = discord.Embed(
                title=f"🌌 {title}",
                description=simplified,
                color=discord.Color.from_rgb(252, 61, 33)
            )
            embed.set_thumbnail(
                url="https://www.nasa.gov/wp-content/uploads/2023/03/nasa-logo-web-rgb.png"
            )
            embed.set_image(url=image_url)
            embed.add_field(name="Date", value=date, inline=True)

            # Create pagination view if multiple APODs
            view = None
            if len(apods) > 1:
                embed.add_field(
                    name="Pages",
                    value=f"1 of {len(apods)}",
                    inline=True
                )
                view = APODPaginationView(apods, ctx.author.id)
                view.update_buttons()  # Initialize button states

            embed.set_footer(
                text="Data: NASA APOD | Simplified: Gemini AI"
            )

            await ctx.send(embed=embed, view=view)

        except APIError as e:
            await ctx.send(f"🚨 NASA error: {e}")
        except LLMError as e:
            await ctx.send(f"🔧 LLM error: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error in apod_command: {e}")
            await ctx.send("❌ Something went wrong. Check logs.")

@bot.command(name='cache')
@commands.is_owner()  # Admin-only
async def cache_command(ctx: commands.Context, action: str = "info") -> None:
    """
    Manage bot cache (owner only).

    Usage:
        !cache info       # Show cache stats
        !cache clear      # Clear all cache
    """
    if action == "clear":
        bot.cache.clear()
        await ctx.send("✓ Cache cleared")
    elif action == "info":
        size = len(bot.cache.cache)
        await ctx.send(f"📊 Cache entries: {size}")
    else:
        await ctx.send("⚠️ Unknown action. Use: info, clear")

if __name__ == '__main__':
    if not Config.validate():
        logger.error("Configuration validation failed")
        exit(1)

    logger.info("🚀 Starting AstroBot...")
    bot.run(Config.DISCORD_TOKEN)
