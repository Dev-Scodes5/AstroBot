import discord
from discord.ext import commands
from discord.ui import View, Button
from datetime import datetime
from typing import List, Dict, Optional

from main import fetch_nasa_data, simplify_with_llm, Config, bot


# ============================================================
#   PAGINATION VIEW FOR MARS ROVER IMAGES
# ============================================================
class MarsPaginationView(View):
    """
    Interactive pagination UI for browsing multiple Mars rover photos.

    This view mirrors the UX patterns used in APODPaginationView to ensure
    consistency across the bot. Each page displays:
        - Rover name
        - Camera name
        - Earth date
        - Sol (Martian day)
        - Full-resolution image
        - Simplified description (via Gemini)
    """

    def __init__(self, photos: List[Dict], owner_id: int, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.photos = photos
        self.owner_id = owner_id
        self.index = 0

    def build_embed(self) -> discord.Embed:
        """
        Construct a Discord embed for the current photo index.
        NASA's Mars Rover API does not provide descriptions, so we generate
        a short contextual explanation using Gemini.
        """
        photo = self.photos[self.index]

        rover = photo["rover"]["name"]
        camera = photo["camera"]["full_name"]
        earth_date = photo["earth_date"]
        sol = photo["sol"]
        img_url = photo["img_src"]

        # Generate a short contextual description using the LLM
        technical_context = (
            f"This is a raw image captured by NASA's Mars rover {rover} "
            f"using the {camera} camera on sol {sol} (Earth date {earth_date}). "
            "Explain what the rover is doing on Mars and what this type of camera is used for."
        )

        simplified = bot.cache.get(f"mars_desc:{hash(technical_context)}")
        if not simplified:
            simplified = "Processing description..."
        # The actual LLM call happens asynchronously in the command

        embed = discord.Embed(
            title=f"📸 Mars Rover: {rover}",
            description=simplified,
            color=discord.Color.from_rgb(255, 99, 71)
        )

        embed.set_image(url=img_url)
        embed.add_field(name="Camera", value=camera, inline=True)
        embed.add_field(name="Sol", value=str(sol), inline=True)
        embed.add_field(name="Earth Date", value=earth_date, inline=True)
        embed.add_field(name="Page", value=f"{self.index + 1}/{len(self.photos)}", inline=False)
        embed.set_footer(text="Data: NASA Mars Rover API | Summary: Gemini AI")

        return embed

    def update_buttons(self) -> None:
        """Enable/disable navigation buttons based on current index."""
        self.prev_button.disabled = (self.index == 0)
        self.next_button.disabled = (self.index == len(self.photos) - 1)

    @discord.ui.button(label="◀️ Prev", style=discord.ButtonStyle.primary)
    async def prev_button(self, interaction: discord.Interaction, button: Button):
        """Navigate to the previous image."""
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message(
                "❌ You cannot control another user's gallery.",
                ephemeral=True
            )

        if self.index > 0:
            self.index -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        """Navigate to the next image."""
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message(
                "❌ You cannot control another user's gallery.",
                ephemeral=True
            )

        if self.index < len(self.photos) - 1:
            self.index += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)


# ============================================================
#   MARS ROVER COG
# ============================================================
class MarsCog(commands.Cog):
    """
    Cog providing the `!mars` command, which retrieves the latest Mars rover
    photos from NASA's public API.

    Features:
        - Pulls the most recent images from Curiosity, Perseverance, or Opportunity
        - Uses caching to reduce API load
        - Generates simplified explanations using Gemini
        - Provides a polished pagination UI for browsing multiple images
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="mars")
    async def mars_command(self, ctx: commands.Context, rover: str = "perseverance", count: int = 5):
        """
        Fetch the latest Mars rover photos.

        Usage:
            !mars
            !mars curiosity
            !mars perseverance 10

        Parameters:
            rover (str): Name of the rover (perseverance, curiosity, opportunity)
            count (int): Number of images to fetch (1–50)
        """
        rover = rover.lower()
        valid = ["perseverance", "curiosity", "opportunity"]

        if rover not in valid:
            return await ctx.send(
                f"⚠️ Invalid rover. Choose from: {', '.join(valid)}"
            )

        count = max(1, min(count, 50))

        async with ctx.typing():
            try:
                # Build NASA API URL
                url = (
                    f"https://api.nasa.gov/mars-photos/api/v1/rovers/{rover}/latest_photos"
                    f"?api_key={Config.NASA_API_KEY}"
                )

                data = await fetch_nasa_data(url)
                photos = data.get("latest_photos", [])[:count]

                if not photos:
                    return await ctx.send("📭 No recent photos found for this rover.")

                # Pre‑generate LLM summaries asynchronously
                for p in photos:
                    context = (
                        f"Image from rover {p['rover']['name']} using {p['camera']['full_name']} "
                        f"on sol {p['sol']} (Earth date {p['earth_date']})."
                    )
                    cache_key = f"mars_desc:{hash(context)}"
                    if not bot.cache.get(cache_key):
                        summary = await simplify_with_llm(context)
                        bot.cache.set(cache_key, summary)

                # Build pagination UI
                view = MarsPaginationView(photos, ctx.author.id)
                view.update_buttons()

                await ctx.send(embed=view.build_embed(), view=view)

            except Exception as e:
                await ctx.send(f"❌ Error fetching Mars rover data: {e}")


# ============================================================
#   SETUP FUNCTION FOR DISCORD.PY EXTENSION LOADER
# ============================================================
async def setup(bot: commands.Bot):
    """Required entry point for loading this Cog."""
    await bot.add_cog(MarsCog(bot))
