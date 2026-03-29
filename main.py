"""
Astrobot , NASAS Data Bot
=========================

## OVERVIEW ####################################################################

This module implements AstroBot, a Discord bot designed to:

- Retrive NASA APOD data
- cache results to reduce API load
- Use Gemini LLM to simplify technical explanations
- Provide interactive UI (pagination)
- Allow users to save and manage favorites

## DESIGN PRINCIPLES ############################################################

-- This is up to the owner of the AstroBot(Dev-Scodes5) to decide. I tried to keep my-
   code as clean and consistent as possible! ~ Noah





## IMPORTANT #####################################################################

## Lines beginning with '##' are documentation comments.
## These describe intent and should preferably not be removed lightly.

## Lines beginning with '#' are implementation notes or optional toggles.

"""

# =============================================================================
# imports
# =============================================================================

import discord
from discord.ext import commands
from discord.ui import Button, View

import aiohttp
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from functools import wraps

from google import genai
from dotenv import load_dotenv


# =============================================================================
# LOGGING SETUP
# =============================================================================

## Centralized logging config
## This ensures consistent logs across all modules

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)

logger = logging.getLogger(__name__)


# =============================================================================
# Environment / Config
# =============================================================================

load_dotenv()


class Config:
    """
    Centralized config.
    
    ## PURPOSE ######################################
    # 
    - Avoid magic values
    - allow environment overrides
    - provide a single audit point for system settings
    """

    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
    NASA_API_KEY = os.getenv('NASA_API_KEY', 'DEMO_KEY')
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

    GEMINI_MODEL = 'gemini-2.5-flash'

    ## NETWORK // LIMITS

    NASA_TIMEOUT = aiohttp.ClientTimeout(total=10)
    CACHE_TTL_HOURS = 24
    RATE_LIMIT_SECONDS = 5
    MAX_APOD_COUNT = 30

    ## LLM PROMPT

    LLM_SYSTEM_PROMPT = """
You are an astrophysics educator for high school students.

Rewrite the following NASA explanation so that:
- It is easy to understand
- It remains scientifically accurate
- It is engaging but not exaggerated

Limit to 2-3 paragraphs.
"""

    @staticmethod
    def validate() -> bool:
        """
        Validate required environment variables.
        
        ## IMPORTANT
        # 
        # This prevents runtime failures due to missing credentials.
        """

        if not Config.DISCORD_TOKEN:
            logger.error("Missing DISCORD_TOKEN")
            return False
        
        if not Config.GEMINI_API_KEY:
            logger.error("Missing GEMINI_API_KEY")
            return Fasle
        
        return True
    

# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class APIError(Exception):
    """Raised when external API calls fail."""


class LLMError(Exception):
    """Raised when LLM processing fails."""


class RateLimitError(Exception):
    """Raised when user hits cooldown."""


# =============================================================================
# Cache system
# =============================================================================

class CacheManager:
    """
    In-memory TTL cache.

    ## DESIGN NOTES #############################################################

    - Stores (value, timestamp)
    - Evicts expired entries on access
    - No background cleanup thread (intentional simplicity)
    """

    def __init__(self, ttl_hours: int):
        self.cache: Dict[str, Tuple[Any, datetime]] = {}
        self.ttl = timedelta(hours=ttl_hours)

    def get(self, key: str) -> Optional[Any]:
        entry = self.cache.get(key)

        if not entry:
            return None

        value, timestamp = entry

        if datetime.now() - timestamp > self.ttl:
            del self.cache[key]
            return None

        return value

    def set(self, key: str, value: Any) -> None:
        self.cache[key] = (value, datetime.now())

    def clear(self) -> None:
        self.cache.clear()


# =============================================================================
# RATE LIMITING
# =============================================================================

class RateLimiter:
    """
    Simple per-user cooldown system.

    ## PURPOSE ##################################################################

    - Prevent API abuse
    - Protect rate-limited endpoints
    """

    def __init__(self, cooldown_seconds: int):
        self.cooldowns: Dict[int, datetime] = {}
        self.cooldown = timedelta(seconds=cooldown_seconds)

    def is_on_cooldown(self, user_id: int) -> bool:
        last = self.cooldowns.get(user_id)

        if not last:
            return False

        if datetime.now() - last > self.cooldown:
            del self.cooldowns[user_id]
            return False

        return True

    def apply(self, user_id: int) -> None:
        self.cooldowns[user_id] = datetime.now()

    def remaining(self, user_id: int) -> float:
        last = self.cooldowns.get(user_id)
        if not last:
            return 0

        remaining = self.cooldown - (datetime.now() - last)
        return max(0, remaining.total_seconds())


def with_rate_limit(limiter: RateLimiter):
    """
    Decorator to enforce per-user cooldown.

    ## IMPORTANT ###############################################################

    - Sends user-facing message
    - Raises RateLimitError to stop execution
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(ctx: commands.Context, *args, **kwargs):

            user_id = ctx.author.id

            if limiter.is_on_cooldown(user_id):
                remaining = limiter.remaining(user_id)

                await ctx.send(
                    f"⏱️ Please wait {remaining:.1f}s before using this command again.",
                    delete_after=5
                )

                raise RateLimitError()

            limiter.apply(user_id)

            return await func(ctx, *args, **kwargs)

        return wrapper
    return decorator


# =============================================================================
# NASA API ACCESS
# =============================================================================

async def fetch_nasa_data(url: str, session: aiohttp.ClientSession, cache: CacheManager) -> Dict[str, Any]:
    """
    Fetch data from NASA API with caching + retry.

    ## FLOW ####################################################################

    1. Check cache
    2. Perform HTTP request
    3. Retry on failure
    4. Cache result
    """

    cached = cache.get(url)
    if cached:
        return cached

    for attempt in range(3):
        try:
            async with session.get(url, timeout=Config.NASA_TIMEOUT) as resp:

                if resp.status != 200:
                    raise APIError(f"NASA returned {resp.status}")

                data = await resp.json()
                cache.set(url, data)
                return data

        except Exception as e:
            if attempt == 2:
                raise APIError(str(e))

            await asyncio.sleep(2 ** attempt)


# =============================================================================
# LLM SERVICE
# =============================================================================

async def simplify_with_llm(text: str, cache: CacheManager, client) -> str:
    """
    Simplify technical text using Gemini.

    ## SAFETY ##################################################################

    - Cached to reduce cost
    - Graceful fallback on failure
    """

    cache_key = f"llm:{hash(text)}"
    cached = cache.get(cache_key)

    if cached:
        return cached

    prompt = f"{Config.LLM_SYSTEM_PROMPT}\n\n{text}"

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=Config.GEMINI_MODEL,
            contents=prompt,
        )

        result = response.text
        cache.set(cache_key, result)

        return result

    except Exception:
        return text[:500] + "..."


# =============================================================================
# PAGINATION UI
# =============================================================================

class APODPaginationView(View):
    """
    UI for navigating APOD results.

    ## BEHAVIOR ################################################################

    - Only original user can interact
    - Maintains current index state
    """

    def __init__(self, apods, owner_id):
        super().__init__(timeout=300)

        self.apods = apods
        self.owner_id = owner_id
        self.index = 0

    def build_embed(self) -> discord.Embed:
        apod = self.apods[self.index]

        embed = discord.Embed(
            title=apod.get("title"),
            description=apod.get("explanation")[:300],
            color=discord.Color.orange()
        )

        embed.set_image(url=apod.get("url"))
        embed.set_footer(text=f"{self.index+1}/{len(self.apods)}")

        return embed

    @discord.ui.button(label="Prev")
    async def prev(self, i, b):
        if i.user.id != self.owner_id:
            return
        self.index = max(0, self.index - 1)
        await i.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next")
    async def next(self, i, b):
        if i.user.id != self.owner_id:
            return
        self.index = min(len(self.apods)-1, self.index + 1)
        await i.response.edit_message(embed=self.build_embed(), view=self)


# =============================================================================
# BOT CLASS
# =============================================================================

class AstroBot(commands.Bot):
    """
    Core bot class.

    ## RESPONSIBILITIES #########################################################

    - Maintain shared resources (session, cache)
    - Load commands
    """

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(command_prefix="!", intents=intents)

        self.session: Optional[aiohttp.ClientSession] = None
        self.cache = CacheManager(Config.CACHE_TTL_HOURS)
        self.rate_limiter = RateLimiter(Config.RATE_LIMIT_SECONDS)

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()

    async def close(self):
        if self.session:
            await self.session.close()

        self.cache.clear()
        await super().close()


bot = AstroBot()
gemini_client = genai.Client(api_key=Config.GEMINI_API_KEY)


# =============================================================================
# COMMANDS
# =============================================================================

@bot.command()
@with_rate_limit(bot.rate_limiter)
async def apod(ctx, count: int = 1):
    """
    Fetch Astronomy Picture of the Day.
    """

    count = max(1, min(count, Config.MAX_APOD_COUNT))

    async with ctx.typing():

        url = f"https://api.nasa.gov/planetary/apod?api_key={Config.NASA_API_KEY}&count={count}"

        data = await fetch_nasa_data(url, bot.session, bot.cache)

        apods = data if isinstance(data, list) else [data]

        simplified = await simplify_with_llm(
            apods[0].get("explanation", ""),
            bot.cache,
            gemini_client
        )

        embed = discord.Embed(
            title=apods[0].get("title"),
            description=simplified
        )

        embed.set_image(url=apods[0].get("url"))

        view = APODPaginationView(apods, ctx.author.id) if len(apods) > 1 else None

        await ctx.send(embed=embed, view=view)


# =============================================================================
# ERROR HANDLING
# =============================================================================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, RateLimitError):
        return

    logger.error(error)
    await ctx.send("❌ Something went wrong.")


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    if not Config.validate():
        exit(1)

    bot.run(Config.DISCORD_TOKEN)