import discord
from discord.ext import commands
import aiohttp
import os
import math
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level constants
ASTEROID_DENSITY_KG_M3 = 3000  # Rocky asteroid; range ~2700–3500
TNT_PER_JOULE = 1 / (4.184e15)  # MT TNT = 4.184e15 J
BUTTON_TIMEOUT_S = 3600

class ImpactCalculator(discord.ui.View):
    """Interactive button for kinetic impact energy calculation.
    Assumes spherical asteroid with rocky density (~3000 kg/m³).
    Accuracy depends on actual composition and shape.
    """
    
    def __init__(self, velocity_kph: float, diameter_m: float):
        super().__init__(timeout=BUTTON_TIMEOUT_S)
        self.velocity_kph = velocity_kph
        self.diameter_m = diameter_m
    
    @discord.ui.button(label="Calculate Kinetic Impact Energy", style=discord.ButtonStyle.danger, emoji="💥")
    async def calculate_impact(self, interaction: discord.Interaction, button: discord.ui.Button):
        radius_m = self.diameter_m / 2
        volume_m3 = (4/3) * math.pi * (radius_m ** 3)
        mass_kg = volume_m3 * ASTEROID_DENSITY_KG_M3
        velocity_ms = self.velocity_kph / 3.6
        kinetic_energy_j = 0.5 * mass_kg * (velocity_ms ** 2)
        megatons_tnt = kinetic_energy_j * TNT_PER_JOULE
        
        embed = discord.Embed(
            title="💥 Impact Physics Analysis",
            description="Theoretical energy release if this object impacted Earth.",
            color=discord.Color.red()
        )
        embed.add_field(name="Estimated Mass", value=f"{mass_kg:,.0f} kg", inline=True)
        embed.add_field(name="Impact Velocity", value=f"{velocity_ms:,.0f} m/s", inline=True)
        embed.add_field(name="Energy Yield", value=f"**{megatons_tnt:,.2f} MT TNT**", inline=False)
        
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(embed=embed)

class SpaceSystems(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.nasa_key = os.getenv('NASA_API_KEY')
        if not self.nasa_key:
            logger.warning("NASA_API_KEY not set; using DEMO_KEY (rate-limited)")
            self.nasa_key = 'DEMO_KEY'
    
    @commands.command(name='asteroids')
    async def asteroid_tracker(self, ctx: commands.Context) -> None:
        """Fetch and display closest hazardous near-Earth object for today."""
        async with ctx.typing():
            today = datetime.now().strftime('%Y-%m-%d')
            url = f"https://api.nasa.gov/neo/rest/v1/feed?start_date={today}&end_date={today}&api_key={self.nasa_key}"
            
            try:
                async with self.bot.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        logger.error(f"NASA API returned {response.status}")
                        await ctx.send("🚨 Telemetry lost. Cannot reach NASA NeoWs databases.")
                        return
                    data = await response.json()
            except asyncio.TimeoutError:
                logger.error("NASA API timeout")
                await ctx.send("⏱️ Request timeout. Try again in a moment.")
                return
            except Exception as e:
                logger.exception(f"Network error fetching asteroids: {e}")
                await ctx.send(f"Network error: {type(e).__name__}")
                return
            
            asteroids = data.get('near_earth_objects', {}).get(today, [])
            if not asteroids:
                await ctx.send("✅ No near-Earth asteroids detected today. The skies are clear!")
                return
            
            # Prefer hazardous asteroid, fallback to closest
            hazardous = [a for a in asteroids if a.get('is_potentially_hazardous_asteroid')]
            target = hazardous[0] if hazardous else asteroids[0]
            
            # Safely extract telemetry with validation
            try:
                name = target.get('name', 'Unknown')
                diameter_max = float(target['estimated_diameter']['meters']['estimated_diameter_max'])
                close_approaches = target.get('close_approach_data', [])
                
                if not close_approaches:
                    logger.warning(f"No close approach data for {name}")
                    await ctx.send(f"⚠️ Asteroid **{name}** has no close approach data today.")
                    return
                
                speed_kph = float(close_approaches[0]['relative_velocity']['kilometers_per_hour'])
                miss_distance_km = float(close_approaches[0]['miss_distance']['kilometers'])
                is_threat = target.get('is_potentially_hazardous_asteroid', False)
            except (KeyError, ValueError, IndexError) as e:
                logger.error(f"Malformed NASA response: {e}")
                await ctx.send("🔴 Could not parse asteroid telemetry. Try again later.")
                return
            
            color = discord.Color.from_rgb(252, 61, 33) if is_threat else discord.Color.green()
            embed = discord.Embed(
                title=f"☄️ Orbital Threat Assessment: {name}",
                description="Live telemetry from NASA CNEOS.",
                color=color
            )
            embed.add_field(name="Estimated Diameter", value=f"{diameter_max:,.2f} m", inline=True)
            embed.add_field(name="Relative Velocity", value=f"{speed_kph:,.2f} km/h", inline=True)
            embed.add_field(name="Miss Distance", value=f"{miss_distance_km:,.2f} km", inline=False)
            embed.add_field(
                name="Hazard Classification",
                value="⚠️ Potentially Hazardous" if is_threat else "✅ Safe Trajectory",
                inline=False
            )
            embed.set_footer(text="Data: NASA NeoWs API")
            
            view = ImpactCalculator(speed_kph, diameter_max)
            await ctx.send(embed=embed, view=view)

async def setup(bot: commands.Bot) -> None:
    """Load SpaceSystems cog."""
    await bot.add_cog(SpaceSystems(bot))