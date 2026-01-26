import os
import json
import random
import asyncio
import time
from datetime import datetime
from threading import Thread
from flask import Flask

import discord
from discord.ext import commands

# ================= FLASK (KEEP ALIVE) =================
app = Flask(__name__)

@app.route("/")
def home():
    return "Giveaway bot is running"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ================= DISCORD SETUP =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.reactions = True

bot = commands.Bot(command_prefix="$", intents=intents, help_command=None)

DATA_GIVEAWAYS = "data/giveaways.json"
DATA_USERS = "data/users.json"

# ================= FILE HELPERS =================
def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

# ================= USER TRACKING =================
voice_join_time = {}

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    users = load_json(DATA_USERS)
    uid = str(message.author.id)

    if uid not in users:
        users[uid] = {"messages": 0, "vc_minutes": 0}

    users[uid]["messages"] += 1
    save_json(DATA_USERS, users)

    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    users = load_json(DATA_USERS)
    uid = str(member.id)

    if uid not in users:
        users[uid] = {"messages": 0, "vc_minutes": 0}

    if after.channel and not before.channel:
        voice_join_time[uid] = time.time()

    if before.channel and not after.channel:
        if uid in voice_join_time:
            minutes = int((time.time() - voice_join_time[uid]) / 60)
            users[uid]["vc_minutes"] += minutes
            voice_join_time.pop(uid, None)
            save_json(DATA_USERS, users)

# ================= GIVEAWAY COMMAND =================
@bot.command()
async def giveaway(ctx, minutes: int, winners: int, msg_req: int, vc_req: int, image: str, *, prize: str):
    """
    $giveaway <minutes> <winners> <msg_req> <vc_req> <image|none> <prize>
    """

    giveaways = load_json(DATA_GIVEAWAYS)
    gid = str(int(max(giveaways.keys(), default="0")) + 1)

    embed = discord.Embed(
        title="🎉 GIVEAWAY 🎉",
        description=(
            f"🏆 **Prize:** {prize}\n"
            f"👥 **Winners:** {winners}\n"
            f"💬 **Messages Required:** {msg_req}\n"
            f"🎧 **VC Minutes Required:** {vc_req}\n"
            f"⏳ **Duration:** {minutes} minute(s)\n\n"
            f"🆔 **Giveaway ID:** {gid}\n"
            f"React 🎉 to enter!"
        ),
        color=discord.Color.gold()
    )

    if image.lower() != "none":
        embed.set_image(url=image)

    msg = await ctx.send(embed=embed)
    await msg.add_reaction("🎉")

    giveaways[gid] = {
        "channel_id": ctx.channel.id,
        "message_id": msg.id,
        "winners": winners,
        "msg_req": msg_req,
        "vc_req": vc_req,
        "end_time": time.time() + minutes * 60
    }

    save_json(DATA_GIVEAWAYS, giveaways)

    await asyncio.sleep(minutes * 60)
    await end_giveaway(gid)

# ================= END GIVEAWAY =================
async def end_giveaway(gid):
    giveaways = load_json(DATA_GIVEAWAYS)
    users = load_json(DATA_USERS)

    if gid not in giveaways:
        return

    g = giveaways[gid]
    channel = bot.get_channel(g["channel_id"])
    msg = await channel.fetch_message(g["message_id"])

    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    if not reaction:
        await channel.send("❌ Giveaway cancelled (no reactions).")
        giveaways.pop(gid)
        save_json(DATA_GIVEAWAYS, giveaways)
        return

    valid_users = []
    bot_top_role = channel.guild.me.top_role

    async for user in reaction.users():
        if user.bot:
            continue

        member = channel.guild.get_member(user.id)
        if not member:
            continue

        # Staff cannot win
        if member.top_role >= bot_top_role:
            continue

        stats = users.get(str(user.id), {"messages": 0, "vc_minutes": 0})
        msgs = stats["messages"]
        vc = stats["vc_minutes"]

        passed = False
        if g["msg_req"] == 0 and g["vc_req"] == 0:
            passed = True
        elif g["msg_req"] > 0 and g["vc_req"] > 0:
            passed = msgs >= g["msg_req"] or vc >= g["vc_req"]
        elif g["msg_req"] > 0:
            passed = msgs >= g["msg_req"]
        elif g["vc_req"] > 0:
            passed = vc >= g["vc_req"]

        if passed:
            valid_users.append(user)

    if not valid_users:
        await channel.send("❌ No one met the giveaway requirements.")
        giveaways.pop(gid)
        save_json(DATA_GIVEAWAYS, giveaways)
        return

    winners = random.sample(valid_users, min(len(valid_users), g["winners"]))
    mentions = ", ".join(w.mention for w in winners)

    await channel.send(
        f"🎉 **GIVEAWAY ENDED!** 🎉\n"
        f"🆔 Giveaway ID: {gid}\n"
        f"🏆 Winner(s): {mentions}"
    )

    giveaways.pop(gid)
    save_json(DATA_GIVEAWAYS, giveaways)

# ================= REROLL =================
@bot.command()
async def reroll(ctx, giveaway_id: str):
    giveaways = load_json(DATA_GIVEAWAYS)
    if giveaway_id not in giveaways:
        await ctx.send("❌ Invalid Giveaway ID or already ended.")
        return

    g = giveaways[giveaway_id]
    channel = bot.get_channel(g["channel_id"])
    msg = await channel.fetch_message(g["message_id"])

    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    if not reaction:
        await ctx.send("❌ No reactions found.")
        return

    users = [u async for u in reaction.users() if not u.bot]
    if not users:
        await ctx.send("❌ No valid users.")
        return

    winner = random.choice(users)
    await ctx.send(f"🔁 **Rerolled Winner:** {winner.mention}")

# ================= START BOT =================
if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    TOKEN = os.getenv("TOKEN")
    if not TOKEN:
        raise RuntimeError("TOKEN not set")
    bot.run(TOKEN)
