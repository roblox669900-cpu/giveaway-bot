import discord
from discord.ext import commands
import asyncio
import random
from datetime import datetime
import os

# ================= BOT SETUP =================
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

# ================= HELP COMMAND =================
@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="🎁 Giveaway Bot Help",
        description="""
**Commands**
`!giveaway <minutes> <winners> <msg_req> <vc_req> <prize>`
`!reroll <giveaway_id>`

**Rules**
• React 🎉 to enter  
• Message OR VC requirement (OR logic)  
• VC time counts even if user joined before  
• Data resets every giveaway  
""",
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

# ================= GIVEAWAY COMMAND =================
@bot.command()
async def giveaway(ctx, minutes: int, winners: int, msg_req: int, vc_req: int, *, prize: str):
    global giveaway_counter

    message_count.clear()
    vc_minutes.clear()
    vc_join_time.clear()

    now = datetime.utcnow()
    for vc in ctx.guild.voice_channels:
        for member in vc.members:
            vc_join_time.setdefault(member.id, now)

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

        passed = False
        if msg_req > 0 and vc_req > 0:
            passed = msgs >= msg_req or vc >= vc_req
        elif msg_req > 0:
            passed = msgs >= msg_req
        elif vc_req > 0:
            passed = vc >= vc_req
        else:
            passed = True

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

    users = [u async for u in reaction.users() if not u.bot]
    if not users:
        await ctx.send("❌ No participants.")
        return

    winner = random.choice(users)
    await ctx.send(f"🔁 **Rerolled Winner:** {winner.mention}")

# ================= RUN =================
bot.run(os.environ["TOKEN"])
