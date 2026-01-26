import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True  # VC tracking only

bot = commands.Bot(
    command_prefix="$",
    intents=intents
)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

bot.run(os.getenv("DISCORD_TOKEN"))
