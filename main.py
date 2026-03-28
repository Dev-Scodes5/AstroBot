import discord
from discord.ext import commands
from discord.ui import View, Button
import aiohttp
import os
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
NASA_KEY = os.getenv('NASA_API_KEY')
GEMINI_KEY = os.getenv('GEMINI_API_KEY')

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Pagination views

class APODPaginationView(View):
    """Pagination view for APOD images."""

    def __init__(self, apod_list, user_id: int, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.apod_list = apod_list
        self.current_index = 0
        self.user_id = user_id

    def get_embed(self):
        """Generate embed for current APOD."""
        apod = self.apod_list[self.current_index]
        embed = discord.Embed(
            title=apod.get('title', 'Untitled'),
            description=apod.get('explanation', 'No explanation available'),
            color=discord.Color.from_rgb(70, 130, 180)
        )

        if 'url' in apod and apod['url']:
            embed.set_image(url=apod['url'])

        if 'media_type' in apod:
            embed.add_field(name="Type", value=apod['media_type'], inline=True)

        if 'copyright' in apod:
            embed.set_footer(text=f"© {apod['copyright']}")

        embed.add_field(
            name="Navigation",
            value=f"Image {self.current_index + 1} of {len(self.apod_list)}",
            inline=False
        )

        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the command user can interact with buttons."""
        return interaction.user.id == self.user_id

    @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index > 0:
            self.current_index -= 1
            await interaction.response.edit_message(embed=self.get_embed())
        else:
            await interaction.response.defer()

    @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index < len(self.apod_list) - 1:
            self.current_index += 1
            await interaction.response.edit_message(embed=self.get_embed())
        else:
            await interaction.response.defer()

class AsteroidPaginationView(View):
    """Pagination view for asteroid list."""

    def __init__(self, asteroid_list, user_id: int, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.asteroid_list = asteroid_list
        self.current_index = 0
        self.user_id = user_id

    def get_embed(self):
        """Generate embed for current asteroid."""
        asteroid = self.asteroid_list[self.current_index]
        embed = discord.Embed(
            title=asteroid['name'],
            color=discord.Color.from_rgb(184, 134, 11)
        )

        # Safely extract data
        diameter_km = asteroid.get('diameter_km', 'Unknown')
        velocity_kmh = asteroid.get('velocity_kmh', 'Unknown')
        hazardous = asteroid.get('hazardous', False)
        miss_distance = asteroid.get('miss_distance', 'Unknown')

        embed.add_field(name="Diameter (km)", value=str(diameter_km), inline=True)
        embed.add_field(name="Velocity (km/h)", value=str(velocity_kmh), inline=True)
        embed.add_field(name="Hazardous", value="⚠️ Yes" if hazardous else "✅ No", inline=True)
        embed.add_field(name="Miss Distance (km)", value=str(miss_distance), inline=False)

        embed.set_footer(text=f"Asteroid {self.current_index + 1} of {len(self.asteroid_list)}")

        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the command user can interact with buttons."""
        return interaction.user.id == self.user_id

    @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index > 0:
            self.current_index -= 1
            await interaction.response.edit_message(embed=self.get_embed())
        else:
            await interaction.response.defer()

    @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_index < len(self.asteroid_list) - 1:
            self.current_index += 1
            await interaction.response.edit_message(embed=self.get_embed())
        else:
            await interaction.response.defer()

class ImpactCalculator(View):
    """Interactive impact calculator view."""

    def __init__(self, asteroid_data, user_id: int):
        super().__init__(timeout=300)
        self.asteroid_data = asteroid_data
        self.user_id = user_id

    def calculate_impact(self):
        """Calculate impact metrics."""
        diameter_km = self.asteroid_data.get('diameter_km', 0)
        velocity_kmh = self.asteroid_data.get('velocity_kmh', 0)

        if diameter_km <= 0 or velocity_kmh <= 0:
            return None

        # Convert to SI units
        diameter_m = diameter_km * 1000
        velocity_ms = velocity_kmh / 3.6

        # Spherical asteroid assumption
        radius_m = diameter_m / 2
        volume_m3 = (4/3) * 3.14159 * (radius_m ** 3)
        density_kg_m3 = 2600  # Typical asteroid density
        mass_kg = volume_m3 * density_kg_m3

        # Kinetic energy: KE = 0.5 * m * v^2
        kinetic_energy_joules = 0.5 * mass_kg * (velocity_ms ** 2)

        # Convert to megatons TNT (1 megaton = 4.184e15 joules)
        kinetic_energy_megatons = kinetic_energy_joules / 4.184e15

        # Crater radius (rough estimate): r_crater ≈ 0.032 * (energy_mt)^0.33
        crater_radius_km = 0.032 * (kinetic_energy_megatons ** 0.33)

        return {
            'kinetic_energy_megatons': kinetic_energy_megatons,
            'crater_radius_km': crater_radius_km,
            'mass_kg': mass_kg
        }

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Calculate Impact", style=discord.ButtonStyle.danger)
    async def calculate_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        result = self.calculate_impact()
        if not result:
            await interaction.followup.send("❌ Invalid asteroid data for calculation.")
            return

        embed = discord.Embed(
            title=f"💥 Impact Analysis: {self.asteroid_data['name']}",
            color=discord.Color.from_rgb(255, 69, 0)
        )
        embed.add_field(
            name="Kinetic Energy",
            value=f"{result['kinetic_energy_megatons']:.2f} megatons TNT",
            inline=False
        )
        embed.add_field(
            name="Estimated Crater Radius",
            value=f"{result['crater_radius_km']:.2f} km",
            inline=False
        )
        embed.add_field(
            name="Asteroid Diameter",
            value=f"{self.asteroid_data['diameter_km']:.2f} km",
            inline=True
        )
        embed.add_field(
            name="Impact Velocity",
            value=f"{self.asteroid_data['velocity_kmh']:.0f} km/h",
            inline=True
        )
        embed.add_field(
            name="⚠️ Assumptions",
            value="Spherical asteroid · Density: 2600 kg/m³ · For reference only",
            inline=False
        )

        await interaction.followup.send(embed=embed)

# Bot events

@bot.event
async def on_ready():
    """Bot startup handler."""
    logger.info(f"Logged in as {bot.user}")
    # Optionally set activity
    # await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.playing, name="!help"))

# Apod Command

@bot.command(name='apod')
async def apod_command(ctx: commands.Context, count: int = 1) -> None:
    """
    Fetch NASA Astronomy Picture of the Day.

    Usage:
        !apod          # Today's APOD
        !apod 7        # Last 7 days
    """
    try:
        if count < 1 or count > 30:
            await ctx.send("❌ Count must be between 1 and 30.")
            return

        async with ctx.typing():
            # Calculate date range
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=count - 1)

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.nasa.gov/planetary/apod",
                    params={
                        'api_key': NASA_KEY,
                        'start_date': start_date.isoformat(),
                        'end_date': end_date.isoformat()
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        await ctx.send(f"❌ NASA API error: {resp.status}")
                        return

                    apod_list = await resp.json()

                    # Ensure it's a list
                    if isinstance(apod_list, dict):
                        apod_list = [apod_list]

            if not apod_list:
                await ctx.send("❌ No APOD data available.")
                return

            # Create pagination view
            view = APODPaginationView(apod_list, ctx.author.id)
            embed = view.get_embed()

            await ctx.send(embed=embed, view=view)

    except asyncio.TimeoutError:
        await ctx.send("❌ NASA API request timed out.")
    except Exception as e:
        logger.error(f"APOD command error: {e}")
        await ctx.send("❌ An error occurred fetching APOD data.")

# Asteroids command

@bot.command(name='asteroids')
async def asteroids_command(ctx: commands.Context, count: int = 5) -> None:
    """
    Fetch approaching near-Earth asteroids.

    Usage:
        !asteroids      # Next 5 asteroids
        !asteroids 10   # Next 10 asteroids
    """
    try:
        if count < 1 or count > 20:
            await ctx.send("❌ Count must be between 1 and 20.")
            return

        async with ctx.typing():
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.nasa.gov/neo/rest/v1/neo/browse",
                    params={'api_key': NASA_KEY},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        await ctx.send(f"❌ NASA API error: {resp.status}")
                        return

                    data = await resp.json()
                    neo_objects = data.get('near_earth_objects', [])

            if not neo_objects:
                await ctx.send("❌ No asteroid data available.")
                return

            # Limit to requested count
            neo_objects = neo_objects[:count]

            # Process asteroid data
            asteroid_list = []
            for neo in neo_objects:
                diameter_km = 0
                if 'estimated_diameter' in neo and 'kilometers' in neo['estimated_diameter']:
                    diameter_km = neo['estimated_diameter']['kilometers']['estimated_diameter_max']

                velocity_kmh = 0
                hazardous = neo.get('is_potentially_hazardous_asteroid', False)
                miss_distance = "Unknown"

                # Try to get velocity from close approach data
                if 'close_approach_data' in neo and neo['close_approach_data']:
                    approach = neo['close_approach_data'][0]
                    if 'relative_velocity' in approach and 'kilometers_per_hour' in approach['relative_velocity']:
                        velocity_kmh = float(approach['relative_velocity']['kilometers_per_hour'])
                    if 'miss_distance' in approach and 'kilometers' in approach['miss_distance']:
                        miss_distance = float(approach['miss_distance']['kilometers'])

                asteroid_list.append({
                    'name': neo.get('name', 'Unknown'),
                    'diameter_km': diameter_km,
                    'velocity_kmh': velocity_kmh,
                    'hazardous': hazardous,
                    'miss_distance': miss_distance
                })

            # Create pagination view
            view = AsteroidPaginationView(asteroid_list, ctx.author.id)
            embed = view.get_embed()

            await ctx.send(embed=embed, view=view)

    except asyncio.TimeoutError:
        await ctx.send("❌ NASA API request timed out.")
    except Exception as e:
        logger.error(f"Asteroids command error: {e}")
        await ctx.send("❌ An error occurred fetching asteroid data.")

@bot.command(name='impact')
async def impact_command(ctx: commands.Context, *, name: str) -> None:
    """
    Calculate impact energy for an asteroid.

    Usage:
        !impact Apophis
        !impact Bennu
    """
    try:
        async with ctx.typing():
            async with aiohttp.ClientSession() as session:
                # Search for asteroid
                async with session.get(
                    f"https://api.nasa.gov/neo/rest/v1/neo/sentry/{name}",
                    params={'api_key': NASA_KEY},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        # Try browse endpoint
                        async with session.get(
                            f"https://api.nasa.gov/neo/rest/v1/neo/browse",
                            params={'api_key': NASA_KEY},
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as browse_resp:
                            if browse_resp.status != 200:
                                await ctx.send(f"❌ Asteroid '{name}' not found.")
                                return

                            data = await browse_resp.json()
                            neo_objects = data.get('near_earth_objects', [])

                            # Search for asteroid by name
                            asteroid = None
                            for neo in neo_objects:
                                if name.lower() in neo.get('name', '').lower():
                                    asteroid = neo
                                    break

                            if not asteroid:
                                await ctx.send(f"❌ Asteroid '{name}' not found.")
                                return
                    else:
                        asteroid = await resp.json()

            # Extract data
            diameter_km = 0
            if 'estimated_diameter' in asteroid and 'kilometers' in asteroid['estimated_diameter']:
                diameter_km = asteroid['estimated_diameter']['kilometers']['estimated_diameter_max']

            velocity_kmh = 0
            if 'close_approach_data' in asteroid and asteroid['close_approach_data']:
                approach = asteroid['close_approach_data'][0]
                if 'relative_velocity' in approach and 'kilometers_per_hour' in approach['relative_velocity']:
                    velocity_kmh = float(approach['relative_velocity']['kilometers_per_hour'])

            asteroid_data = {
                'name': asteroid.get('name', 'Unknown'),
                'diameter_km': diameter_km,
                'velocity_kmh': velocity_kmh
            }

            # Show impact calculator
            view = ImpactCalculator(asteroid_data, ctx.author.id)
            embed = discord.Embed(
                title=f"🪨 {asteroid_data['name']}",
                description="Click 'Calculate Impact' to see impact metrics.",
                color=discord.Color.from_rgb(255, 69, 0)
            )
            embed.add_field(name="Diameter", value=f"{asteroid_data['diameter_km']:.2f} km", inline=True)
            embed.add_field(name="Velocity", value=f"{asteroid_data['velocity_kmh']:.0f} km/h", inline=True)

            await ctx.send(embed=embed, view=view)

    except asyncio.TimeoutError:
        await ctx.send("❌ NASA API request timed out.")
    except Exception as e:
        logger.error(f"Impact command error: {e}")
        await ctx.send("❌ An error occurred processing impact data.")

if __name__ == '__main__':
    bot.run(TOKEN)