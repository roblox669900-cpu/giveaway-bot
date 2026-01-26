import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True  # required

bot = commands.Bot(
    command_prefix="$",   # your prefix
    intents=intents
)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

bot.run(os.getenv("TOKEN"))
