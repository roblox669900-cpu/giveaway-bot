import os
import threading
import asyncio
import random
from datetime import datetime

from flask import Flask
import discord
from discord.ext import commands

# ================= FLASK (RENDER PORT FIX) =================
app = Flask(__name__)

@app.route("/")
def home():
    return "Giveaway bot is running"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ================= DISCORD BOT SETUP =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.reactions = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

# ================= DATA =================
giveaway_counter = 1
giveaways = {}

message_count = {}
vc_join_time = {}
vc_minutes = {}

# ================= EVENTS =================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    message_count[message.author.id] = message_count.get(message.author.id, 0) + 1
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    now = datetime.utcnow()
    if after.channel and not before.channel:
        vc_join_time[member.id] = now
    if before.channel and not after.channel:
        if member.id in vc_join_time:
            delta = now - vc_join_time.pop(member.id)
            vc_minutes[member.id] = vc_minutes.get(member.id, 0) + delta.total_seconds() / 60

# ================= HELP =================
@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="🎁 Giveaway Bot Help",
        description="""
**Commands**
`!giveaway <minutes> <winners> <msg_req> <vc_req> <prize> [image_url]`
`!reroll <giveaway_id>`

**Rules**
• React 🎉 to enter  
• Message OR VC requirement  
• VC counts even if joined before  
• Requirements reset every giveaway  
""",
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

# ================= GIVEAWAY =================
@bot.command()
async def giveaway(ctx, minutes: int, winners: int, msg_req: int, vc_req: int, *, prize_and_image: str):
    global giveaway_counter

    # Reset old data
    message_count.clear()
    vc_minutes.clear()
    vc_join_time.clear()

    # Track users already in VC
    now = datetime.utcnow()
    for vc in ctx.guild.voice_channels:
        for member in vc.members:
            vc_join_time.setdefault(member.id, now)

    # Split prize & image
    parts = prize_and_image.rsplit(" ", 1)
    prize = parts[0]
    image_url = parts[1] if len(parts) == 2 and parts[1].startswith("http") else None

    giveaway_id = giveaway_counter
    giveaway_counter += 1

    embed = discord.Embed(
        title="🎉 GIVEAWAY 🎉",
        description=f"""
🆔 **Giveaway ID:** {giveaway_id}

🏆 **Prize:** {prize}
⏱ **Duration:** {minutes} minute(s)
👥 **Winners:** {winners}

📋 **Requirements**
💬 Messages: {msg_req}
🎧 VC Minutes: {vc_req}

React 🎉 to enter!
""",
        color=discord.Color.gold()
    )

    if image_url:
        embed.set_image(url=image_url)

    msg = await ctx.send(embed=embed)
    await msg.add_reaction("🎉")

    giveaways[giveaway_id] = {
        "message_id": msg.id,
        "channel_id": ctx.channel.id,
        "msg_req": msg_req,
        "vc_req": vc_req,
        "winners": winners
    }

    await asyncio.sleep(minutes * 60)

    msg = await ctx.channel.fetch_message(msg.id)
    reaction = discord.utils.get(msg.reactions, emoji="🎉")

    if not reaction:
        await ctx.send("❌ Giveaway cancelled.")
        return

    users = [u async for u in reaction.users() if not u.bot]
    valid_users = []

    for user in users:
        msgs = message_count.get(user.id, 0)
        vc = vc_minutes.get(user.id, 0)

        passed = (
            (msg_req > 0 and msgs >= msg_req) or
            (vc_req > 0 and vc >= vc_req) or
            (msg_req == 0 and vc_req == 0)
        )

        if passed:
            valid_users.append(user)

    if not valid_users:
        await ctx.send("❌ **No one met the giveaway requirements.**")
        return

    winners_list = random.sample(valid_users, min(winners, len(valid_users)))
    mentions = ", ".join(u.mention for u in winners_list)

    await ctx.send(
        f"🎉 **GIVEAWAY ENDED!** 🎉\n"
        f"🆔 Giveaway ID: {giveaway_id}\n"
        f"🏆 Winner(s): {mentions}"
    )

# ================= REROLL =================
@bot.command()
async def reroll(ctx, giveaway_id: int):
    data = giveaways.get(giveaway_id)
    if not data:
        await ctx.send("❌ Invalid Giveaway ID.")
        return

    channel = bot.get_channel(data["channel_id"])
    msg = await channel.fetch_message(data["message_id"])
    reaction = discord.utils.get(msg.reactions, emoji="🎉")

    if not reaction:
        await ctx.send("❌ No 🎉 reaction found on the giveaway message.")
        return

    users = [u async for u in reaction.users() if not u.bot]
    if not users:
        await ctx.send("❌ No participants.")
        return

    winner = random.choice(users)
    await ctx.send(f"🔁 **Rerolled Winner:** {winner.mention}")

# ================= RUN =================
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN not set")

bot.run(TOKEN)
