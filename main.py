import os
import threading
import asyncio
import random
from datetime import datetime, timedelta

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

# ================= TIME PARSER =================
def parse_time(arg):
    arg = arg.lower()
    if arg.endswith("m"):
        return int(arg[:-1])
    elif arg.endswith("h"):
        return int(arg[:-1]) * 60
    elif arg.endswith("d"):
        return int(arg[:-1]) * 1440
    else:
        return None

def format_time_left(seconds):
    mins = int(seconds // 60)
    days = mins // 1440
    hours = (mins % 1440) // 60
    minutes = mins % 60
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    return " ".join(parts) if parts else "0m"

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
**Command**
`!giveaway <time> <winners> <msg_req> <vc_req_time> <prize> [image_url]`

**Examples**
!giveaway 10m 1 1 1m Yeti
!giveaway 2h 2 5 30m Nitro
!giveaway 1d 1 0 0 Robux

**Other**
!reroll <id>
!setwinner <id> @user
""",
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

# ================= GIVEAWAY =================
@bot.command()
async def giveaway(ctx, duration: str, winners: int, msg_req: int, vc_req_time: str, *, prize_and_image: str):
    global giveaway_counter

    minutes = parse_time(duration)
    if minutes is None:
        await ctx.send("❌ Invalid duration format. Use m/h/d.")
        return

    vc_req = parse_time(vc_req_time)
    if vc_req is None:
        await ctx.send("❌ Invalid VC time format. Use m/h/d.")
        return

    message_count.clear()
    vc_minutes.clear()
    vc_join_time.clear()

    now = datetime.utcnow()
    for vc in ctx.guild.voice_channels:
        for member in vc.members:
            vc_join_time.setdefault(member.id, now)

    parts = prize_and_image.rsplit(" ", 1)
    prize = parts[0]
    image_url = parts[1] if len(parts) == 2 and parts[1].startswith("http") else None

    giveaway_id = giveaway_counter
    giveaway_counter += 1

    end_time = datetime.utcnow() + timedelta(minutes=minutes)

    embed = discord.Embed(
        title="🎉 GIVEAWAY 🎉",
        description=f"""
🆔 **Giveaway ID:** {giveaway_id}

🏆 **Prize:** {prize}
⏳ **Time Left:** {duration}
👥 **Winners:** {winners}

📋 **Requirements**
💬 Messages: {msg_req}
🎧 VC Minutes: {vc_req}min

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
        "winners": winners,
        "end_time": end_time,
        "secret_winner": None
    }

    async def countdown_task():
        while True:
            remaining = (end_time - datetime.utcnow()).total_seconds()
            if remaining <= 0:
                break
            time_left = format_time_left(remaining)
            embed.description = f"""
🆔 **Giveaway ID:** {giveaway_id}

🏆 **Prize:** {prize}
⏳ **Time Left:** {time_left}
👥 **Winners:** {winners}

📋 **Requirements**
💬 Messages: {msg_req}
🎧 VC Minutes: {vc_req}min

React 🎉 to enter!
"""
            try:
                await msg.edit(embed=embed)
            except:
                pass
            await asyncio.sleep(60)

    bot.loop.create_task(countdown_task())
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
        await ctx.send("❌ No one met the requirements.")
        return

    data = giveaways[giveaway_id]
    if data["secret_winner"] and data["secret_winner"] in valid_users:
        winners_list = [data["secret_winner"]]
    else:
        winners_list = random.sample(valid_users, min(winners, len(valid_users)))

    mentions = ", ".join(u.mention for u in winners_list)

    await ctx.send(
        f"🎉 **GIVEAWAY ENDED!** 🎉\n"
        f"🆔 Giveaway ID: {giveaway_id}\n"
        f"🏆 Winner(s): {mentions}"
    )

# ================= SECRET WINNER =================
@bot.command()
@commands.has_permissions(administrator=True)
async def setwinner(ctx, giveaway_id: int, user: discord.Member):
    if giveaway_id not in giveaways:
        await ctx.send("❌ Invalid giveaway ID.")
        return
    giveaways[giveaway_id]["secret_winner"] = user
    await ctx.send("✅ Secret winner set.")

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
        await ctx.send("❌ No 🎉 reaction found.")
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
