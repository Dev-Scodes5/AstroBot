import discord
from discord.ext import commands
from discord.ui import Button, View
import aiohttp
import logging
from typing import Optional, List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

# Pagination view for asteroids

class AsteroidPaginationView(View):
    """Navigation buttons for browsing asteroid list."""

    def __init__(self, asteroids: List[Dict], owner_id: int, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.asteroids = asteroids
        self.owner_id = owner_id
        self.current_index = 0

    def get_embed(self) -> discord.Embed:
        """Generate embed for current asteroid."""
        ast = self.asteroids[self.current_index]

        embed = discord.Embed(
            title=f"🪨 {ast.get('name', 'Unknown')}",
            description=f"**Estimated Diameter:** {ast.get('diameter', 'N/A')} m",
            color=discord.Color.from_rgb(184, 134, 11)
        )

        embed.add_field(
            name="Hazardous",
            value="⚠️ Yes" if ast.get('hazardous') else "✅ No",
            inline=True
        )
        embed.add_field(
            name="Relative Velocity",
            value=f"{ast.get('velocity', 'N/A')} km/s",
            inline=True
        )
        embed.add_field(
            name="Miss Distance",
            value=f"{ast.get('miss_distance', 'N/A')} km",
            inline=False
        )
        embed.add_field(
            name="Close Approach",
            value=ast.get('close_approach', 'N/A'),
            inline=False
        )
        embed.set_footer(
            text=f"Asteroid {self.current_index + 1}/{len(self.asteroids)} | "
                 f"Data: NASA NEO"
        )

        return embed

    def update_buttons(self) -> None:
        """Enable/disable buttons based on position."""
        self.prev_button.disabled = (self.current_index == 0)
        self.next_button.disabled = (self.current_index == len(self.asteroids) - 1)

    @discord.ui.button(label="◀️ Prev", style=discord.ButtonStyle.primary)
    async def prev_button(self, interaction: discord.Interaction, button: Button):
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

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ You can't control someone else's pagination!",
                ephemeral=True
            )
            return

        if self.current_index < len(self.asteroids) - 1:
            self.current_index += 1
            self.update_buttons()
            await interaction.response.edit_message(
                embed=self.get_embed(),
                view=self
            )

# Impact Calculator

class ImpactCalculator:
    """Calculate impact energy and effects for asteroids."""

    # Modeling assumptions
    ASTEROID_DENSITY = 2600  # kg/m³ (typical rocky asteroid)
    TNT_EQUIVALENT = 4.184e9  # Joules per ton of TNT

    @staticmethod
    def calculate_volume(diameter_m: float) -> float:
        """Calculate volume of spherical asteroid."""
        import math
        radius = diameter_m / 2
        return (4/3) * math.pi * (radius ** 3)

    @staticmethod
    def calculate_mass(diameter_m: float) -> float:
        """Calculate mass using density assumption."""
        volume = ImpactCalculator.calculate_volume(diameter_m)
        return volume * ImpactCalculator.ASTEROID_DENSITY

    @staticmethod
    def calculate_kinetic_energy(mass_kg: float, velocity_m_s: float) -> float:
        """Calculate kinetic energy: KE = 0.5 * m * v²"""
        return 0.5 * mass_kg * (velocity_m_s ** 2)

    @staticmethod
    def energy_to_tnt(energy_joules: float) -> float:
        """Convert energy to TNT equivalent (megatons)."""
        return energy_joules / ImpactCalculator.TNT_EQUIVALENT / 1e6

    @staticmethod
    def estimate_crater_radius(energy_megatons: float) -> float:
        """Rough estimate of crater radius in km (empirical formula)."""
        # Simplified: crater_radius ≈ 0.066 * (energy^0.33)
        import math
        return 0.066 * (energy_megatons ** (1/3))

# Space Systems COG

class SpaceSystems(commands.Cog):
    """Asteroid tracking and impact calculations."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.nasa_api_key = None

    async def cog_load(self) -> None:
        """Load NASA API key from bot config."""
        from main import Config
        self.nasa_api_key = Config.NASA_API_KEY
        logger.info("SpaceSystems cog loaded")

    async def fetch_neo_data(self, url: str) -> Optional[Dict]:
        """Fetch NASA NEO data with error handling."""
        try:
            async with self.bot.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"NASA NEO API returned {response.status}")
                    return None
        except asyncio.TimeoutError:
            logger.error("NEO API timeout")
            return None
        except Exception as e:
            logger.error(f"Error fetching NEO data: {e}")
            return None

    def parse_asteroids(self, data: Dict) -> List[Dict]:
        """Parse NASA NEO data into list of asteroid dicts."""
        asteroids = []

        try:
            for date, ast_list in data.get('near_earth_objects', {}).items():
                for ast in ast_list:
                    try:
                        diameter_m = (
                            ast['estimated_diameter']['meters']['estimated_diameter_max'] +
                            ast['estimated_diameter']['meters']['estimated_diameter_min']
                        ) / 2

                        close_approaches = ast.get('close_approach_data', [])
                        if close_approaches:
                            ca = close_approaches[0]  # First close approach
                            velocity = float(ca['relative_velocity']['kilometers_per_second'])
                            miss_dist = float(ca['miss_distance']['kilometers'])
                            ca_date = ca['close_approach_date']
                        else:
                            velocity = 0
                            miss_dist = 0
                            ca_date = "N/A"

                        asteroids.append({
                            'name': ast['name'],
                            'diameter': round(diameter_m, 2),
                            'hazardous': ast['is_potentially_hazardous_asteroid'],
                            'velocity': round(velocity, 2),
                            'miss_distance': round(miss_dist, 0),
                            'close_approach': ca_date
                        })
                    except (KeyError, ValueError, TypeError) as e:
                        logger.warning(f"Error parsing asteroid: {e}")
                        continue
        except Exception as e:
            logger.error(f"Error parsing NEO response: {e}")

        return asteroids

    @commands.command(name='asteroids')
    async def asteroids_command(self, ctx: commands.Context, count: int = 5) -> None:
        """
        Fetch near-Earth asteroids approaching Earth.

        Usage:
            !asteroids           # Next 5 approaching asteroids
            !asteroids 10        # Next 10 approaching asteroids
        """
        if count < 1 or count > 20:
            await ctx.send("⚠️ Count must be 1–20. Using count=5.")
            count = 5

        async with ctx.typing():
            try:
                url = (
                    f"https://api.nasa.gov/neo/rest/v1/feed?"
                    f"start_date={datetime.now().strftime('%Y-%m-%d')}&"
                    f"api_key={self.nasa_api_key}"
                )

                data = await self.fetch_neo_data(url)
                if not data:
                    await ctx.send("🚨 Failed to fetch asteroid data from NASA.")
                    return

                asteroids = self.parse_asteroids(data)

                if not asteroids:
                    await ctx.send("❌ No asteroids found for the requested period.")
                    return

                asteroids = asteroids[:count]

                view = AsteroidPaginationView(asteroids, ctx.author.id)
                view.update_buttons()

                embed = view.get_embed()
                await ctx.send(embed=embed, view=view)

                logger.info(f"Asteroid command: fetched {len(asteroids)} asteroids")

            except Exception as e:
                logger.exception(f"Error in asteroids_command: {e}")
                await ctx.send("❌ Something went wrong. Check logs.")

    @commands.command(name='impact')
    async def impact_command(self, ctx: commands.Context, *, asteroid_name: str) -> None:
        """
        Calculate impact energy for a named asteroid.

        Usage:
            !impact Apophis
            !impact 2023 DW
        """
        async with ctx.typing():
            try:
                # Fetch asteroid data
                url = (
                    f"https://api.nasa.gov/neo/rest/v1/neo/{asteroid_name}?"
                    f"api_key={self.nasa_api_key}"
                )

                data = await self.fetch_neo_data(url)
                if not data:
                    await ctx.send(f"❌ Asteroid '{asteroid_name}' not found.")
                    return

                # Extract data
                diameter_m = (
                    data['estimated_diameter']['meters']['estimated_diameter_max'] +
                    data['estimated_diameter']['meters']['estimated_diameter_min']
                ) / 2

                close_approaches = data.get('close_approach_data', [])
                if not close_approaches:
                    await ctx.send(f"⚠️ No close approach data for '{asteroid_name}'.")
                    return

                ca = close_approaches[0]
                velocity_km_s = float(ca['relative_velocity']['kilometers_per_second'])
                velocity_m_s = velocity_km_s * 1000

                # Calculate
                mass_kg = ImpactCalculator.calculate_mass(diameter_m)
                energy_j = ImpactCalculator.calculate_kinetic_energy(mass_kg, velocity_m_s)
                energy_mt = ImpactCalculator.energy_to_tnt(energy_j)
                crater_km = ImpactCalculator.estimate_crater_radius(energy_mt)

                # Build embed
                embed = discord.Embed(
                    title=f"💥 Impact Analysis: {data['name']}",
                    color=discord.Color.from_rgb(255, 69, 0)
                )
                embed.add_field(
                    name="Diameter",
                    value=f"{diameter_m:.0f} m",
                    inline=True
                )
                embed.add_field(
                    name="Velocity",
                    value=f"{velocity_km_s:.2f} km/s",
                    inline=True
                )
                embed.add_field(
                    name="Mass",
                    value=f"{mass_kg:.2e} kg",
                    inline=False
                )
                embed.add_field(
                    name="Kinetic Energy",
                    value=f"{energy_mt:.3f} megatons TNT",
                    inline=True
                )
                embed.add_field(
                    name="Est. Crater Radius",
                    value=f"{crater_km:.1f} km",
                    inline=True
                )
                embed.set_footer(
                    text="Assumes spherical asteroid, average density 2600 kg/m³. For reference only."
                )

                await ctx.send(embed=embed)
                logger.info(f"Impact calculation for {asteroid_name}: {energy_mt:.3f} MT")

            except Exception as e:
                logger.exception(f"Error in impact_command: {e}")
                await ctx.send("❌ Something went wrong. Check logs.")

async def setup(bot: commands.Bot) -> None:
    """Load this cog into the bot."""
    await bot.add_cog(SpaceSystems(bot))
    logger.info("SpaceSystems cog registered")