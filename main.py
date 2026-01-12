import os
import threading
import asyncio
import random
from datetime import datetime, timedelta

from flask import Flask
import discord
from discord.ext import commands

# ================= FLASK =================
app = Flask(__name__)

@app.route("/")
def home():
    return "Giveaway bot is running"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ================= DISCORD =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# ================= DATA =================
giveaway_counter = 1
giveaways = {}

message_count = {}
vc_join_time = {}
vc_minutes = {}

# ================= TIME HELPERS =================
def parse_time(arg: str):
    arg = arg.lower()
    if arg.endswith("m"):
        return int(arg[:-1])
    if arg.endswith("h"):
        return int(arg[:-1]) * 60
    if arg.endswith("d"):
        return int(arg[:-1]) * 1440
    return None

def format_time_left(seconds):
    mins = int(seconds // 60)
    d = mins // 1440
    h = (mins % 1440) // 60
    m = mins % 60
    out = []
    if d: out.append(f"{d}d")
    if h: out.append(f"{h}h")
    if m: out.append(f"{m}m")
    return " ".join(out) if out else "0m"

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

# ================= GIVEAWAY =================
@bot.command()
async def giveaway(ctx, duration: str, winners: int, msg_req: int, vc_req_time: str, *, prize_and_image: str):
    global giveaway_counter

    minutes = parse_time(duration)
    vc_req = parse_time(vc_req_time)

    if minutes is None or vc_req is None:
        await ctx.send("❌ Use time format like 10m / 2h / 1d")
        return

    # reset per-giveaway data
    message_count.clear()
    vc_minutes.clear()
    vc_join_time.clear()

    now = datetime.utcnow()

    # register users already in VC
    for vc in ctx.guild.voice_channels:
        for member in vc.members:
            vc_join_time[member.id] = now

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
        "secret_winner": None,
        "guild_id": ctx.guild.id
    }

    async def countdown():
        while True:
            left = (end_time - datetime.utcnow()).total_seconds()
            if left <= 0:
                break
            embed.description = f"""
🆔 **Giveaway ID:** {giveaway_id}

🏆 **Prize:** {prize}
⏳ **Time Left:** {format_time_left(left)}
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

    bot.loop.create_task(countdown())
    await asyncio.sleep(minutes * 60)

    # ================= FINAL VC FIX =================
    now = datetime.utcnow()
    guild = ctx.guild

    # force count users still in VC
    for vc in guild.voice_channels:
        for member in vc.members:
            if member.id in vc_join_time:
                delta = now - vc_join_time[member.id]
                vc_minutes[member.id] = vc_minutes.get(member.id, 0) + delta.total_seconds() / 60
                vc_join_time.pop(member.id, None)

    # ================= PICK WINNERS =================
    msg = await ctx.channel.fetch_message(msg.id)
    reaction = discord.utils.get(msg.reactions, emoji="🎉")

    users = [u async for u in reaction.users() if not u.bot]
    valid_users = []

    for user in users:
        msgs = message_count.get(user.id, 0)
        vc = vc_minutes.get(user.id, 0)

        if (
            (msg_req > 0 and msgs >= msg_req) or
            (vc_req > 0 and vc >= vc_req) or
            (msg_req == 0 and vc_req == 0)
        ):
            valid_users.append(user)

    if not valid_users:
        await ctx.send("❌ **No one met the giveaway requirements.**")
        return

    data = giveaways[giveaway_id]
    if data["secret_winner"] and data["secret_winner"] in valid_users:
        winners_list = [data["secret_winner"]]
    else:
        winners_list = random.sample(valid_users, min(winners, len(valid_users)))

    await ctx.send(
        f"🎉 **GIVEAWAY ENDED!** 🎉\n"
        f"🆔 Giveaway ID: {giveaway_id}\n"
        f"🏆 Winner(s): {', '.join(u.mention for u in winners_list)}"
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

# ================= RUN =================
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN not set")

bot.run(TOKEN)
