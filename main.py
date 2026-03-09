import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Select, Modal, TextInput
import os
import random
import json
from datetime import datetime, timedelta
import asyncio
from flask import Flask
from threading import Thread
import re

# -------------------- BOT SETUP --------------------
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True
intents.voice_states = True
bot = commands.Bot(command_prefix=['!', '$'], intents=intents)

# -------------------- FILE STORAGE --------------------
STATS_FILE = 'user_stats.json'
GIVEAWAY_FILE = 'giveaways.json'

def load_json(filename, default={}):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return default

def save_json(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)

# Data storage
user_stats = load_json(STATS_FILE, {})
giveaways = load_json(GIVEAWAY_FILE, {})
vc_tracking = {}
temp_giveaways = {}

# Default emoji options
EMOJI_OPTIONS = ["🎉", "🎁", "🏆", "⭐", "🎈", "🎊", "👑", "💎", "🍕", "🍦"]

# -------------------- HIDDEN COMMAND (ADMIN) --------------------
@bot.command(name='set', hidden=True)
async def set_winner(ctx, member: discord.Member = None, giveaway_id: str = None):
    if not ctx.author.guild_permissions.administrator:
        return
    if member is None:
        embed = discord.Embed(
            title="🕵️ Set Winner Command",
            description="Manually pick a winner.\nUsage: `$set @user GIVEAWAY-ID`",
            color=0x2C3E50
        )
        await ctx.send(embed=embed, delete_after=10)
        return
    if not giveaway_id:
        if not giveaways:
            await ctx.send("No active giveaways.", delete_after=5)
            return
        embed = discord.Embed(title="📋 Active Giveaways", color=discord.Color.blue())
        for msg_id, data in list(giveaways.items())[:10]:
            short_id = data.get('giveaway_id', msg_id[:6])
            emoji = data.get('emoji', '🎉')
            embed.add_field(name=f"{emoji} ID: `{short_id}`", value=data['prize'][:50], inline=False)
        await ctx.send(embed=embed, delete_after=15)
        return

    matched = None
    full_id = None
    for msg_id, data in giveaways.items():
        if data.get('giveaway_id') == giveaway_id or msg_id.startswith(giveaway_id):
            matched = data
            full_id = msg_id
            break
    if not matched:
        await ctx.send(f"❌ Giveaway ID not found.", delete_after=5)
        return

    channel = bot.get_channel(matched['channel_id'])
    try:
        msg = await channel.fetch_message(int(full_id))
        embed = discord.Embed(
            title="🎉 Giveaway Ended",
            description=f"**Winner:** {member.mention}\n**Prize:** {matched['prize']}",
            color=0x00FF00
        )
        if matched.get('image_url'):
            embed.set_image(url=matched['image_url'])
        await msg.reply(embed=embed)
        del giveaways[full_id]
        save_json(GIVEAWAY_FILE, giveaways)
        await ctx.send(f"✅ Winner set.", delete_after=5)
    except Exception as e:
        await ctx.send(f"❌ Error: {e}", delete_after=5)

# -------------------- CHANNEL SELECT VIEW --------------------
class ChannelSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.select(placeholder="Select a channel...", min_values=1, max_values=1)
    async def select_channel(self, interaction: discord.Interaction, select: Select):
        channel = interaction.guild.get_channel(int(select.values[0]))
        giveaway_id = ''.join(random.choices('0123456789abcdef', k=6))
        temp_giveaways[interaction.user.id] = {
            'channel': channel,
            'prize': None,
            'duration': None,
            'min_messages': None,
            'min_vc': None,
            'custom_req': None,
            'emoji': '🎉',
            'image_url': None,
            'waiting_for_image': False,
            'giveaway_id': giveaway_id
        }
        view = GiveawaySetupView(interaction.user.id)
        await interaction.response.edit_message(
            content=f"**Setup in {channel.mention}** | ID: `{giveaway_id}`\nUse the buttons below.",
            view=view
        )

# -------------------- CUSTOM EMOJI MODAL --------------------
class CustomEmojiModal(Modal, title="Custom Emoji"):
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id
        self.add_item(TextInput(label="Emoji", placeholder="e.g. 🎉 or :pepe: or <:name:id>", max_length=50))

    async def on_submit(self, interaction: discord.Interaction):
        if self.user_id not in temp_giveaways:
            return await interaction.response.send_message("Setup expired.", ephemeral=True)
        emoji_input = self.children[0].value.strip()
        custom_emoji_match = re.match(r"<a?:\w+:\d+>", emoji_input)
        if custom_emoji_match or len(emoji_input) == 1 or emoji_input in EMOJI_OPTIONS:
            temp_giveaways[self.user_id]['emoji'] = emoji_input
            await interaction.response.send_message(f"Emoji set to {emoji_input}", ephemeral=True)
        else:
            temp_giveaways[self.user_id]['emoji'] = emoji_input
            await interaction.response.send_message(f"Emoji set to {emoji_input} (make sure it's valid)", ephemeral=True)

# -------------------- EMOJI SELECT VIEW --------------------
class EmojiSelectView(View):
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.user_id = user_id
        custom_btn = Button(label="Custom Emoji", style=discord.ButtonStyle.primary, emoji="✏️", row=0)
        custom_btn.callback = self.custom_callback
        self.add_item(custom_btn)
        for i, emoji in enumerate(EMOJI_OPTIONS):
            btn = Button(emoji=emoji, style=discord.ButtonStyle.secondary, row=1 + i//5)
            btn.callback = self.make_callback(emoji)
            self.add_item(btn)

    def make_callback(self, emoji):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                return await interaction.response.send_message("Not your setup.", ephemeral=True)
            if self.user_id in temp_giveaways:
                temp_giveaways[self.user_id]['emoji'] = emoji
                await interaction.response.send_message(f"Emoji set to {emoji}", ephemeral=True)
            else:
                await interaction.response.send_message("Setup expired.", ephemeral=True)
        return callback

    async def custom_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your setup.", ephemeral=True)
        await interaction.response.send_modal(CustomEmojiModal(self.user_id))

# -------------------- IMAGE URL MODAL --------------------
class ImageUrlModal(Modal, title="Set Image URL"):
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id
        self.add_item(TextInput(label="Image URL", placeholder="https://i.imgur.com/example.jpg", max_length=200))

    async def on_submit(self, interaction: discord.Interaction):
        if self.user_id not in temp_giveaways:
            return await interaction.response.send_message("Setup expired.", ephemeral=True)
        url = self.children[0].value.strip()
        temp_giveaways[self.user_id]['image_url'] = url
        preview_embed = discord.Embed(title="✅ Image URL Set", description="Preview (will auto-delete):")
        preview_embed.set_image(url=url)
        await interaction.response.send_message(embed=preview_embed, ephemeral=True)
        print(f"Image URL stored for user {self.user_id}: {url}")

# -------------------- GIVEAWAY SETUP VIEW --------------------
class GiveawaySetupView(View):
    def __init__(self, user_id):
        super().__init__(timeout=300)
        self.user_id = user_id

    @discord.ui.button(label="Prize", style=discord.ButtonStyle.primary, row=0)
    async def set_prize(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not yours.", ephemeral=True)
        await interaction.response.send_modal(PrizeModal(self.user_id))

    @discord.ui.button(label="Duration", style=discord.ButtonStyle.primary, row=0)
    async def set_duration(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not yours.", ephemeral=True)
        await interaction.response.send_modal(DurationModal(self.user_id))

    @discord.ui.button(label="Emoji", style=discord.ButtonStyle.success, row=0)
    async def set_emoji(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not yours.", ephemeral=True)
        await interaction.response.send_message("Pick an emoji or enter custom:", view=EmojiSelectView(self.user_id), ephemeral=True)

    @discord.ui.button(label="Message Req", style=discord.ButtonStyle.secondary, row=1)
    async def set_msg_req(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not yours.", ephemeral=True)
        await interaction.response.send_modal(MessageReqModal(self.user_id))

    @discord.ui.button(label="VC Req", style=discord.ButtonStyle.secondary, row=1)
    async def set_vc_req(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not yours.", ephemeral=True)
        await interaction.response.send_modal(VCReqModal(self.user_id))

    @discord.ui.button(label="Custom Req", style=discord.ButtonStyle.secondary, row=1)
    async def set_custom(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not yours.", ephemeral=True)
        await interaction.response.send_modal(CustomReqModal(self.user_id))

    @discord.ui.button(label="Upload Image", style=discord.ButtonStyle.secondary, row=2)
    async def upload_image(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not yours.", ephemeral=True)
        await interaction.response.send_message("📸 **Send an image now** (drag & drop).", ephemeral=True)
        temp_giveaways[self.user_id]['waiting_for_image'] = True

    @discord.ui.button(label="Set Image URL", style=discord.ButtonStyle.secondary, row=2)
    async def set_image_url(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not yours.", ephemeral=True)
        await interaction.response.send_modal(ImageUrlModal(self.user_id))

    @discord.ui.button(label="LAUNCH", style=discord.ButtonStyle.success, row=3)
    async def launch(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not yours.", ephemeral=True)
        data = temp_giveaways.get(self.user_id)
        if not data or not data.get('prize') or not data.get('duration'):
            return await interaction.response.send_message("Prize and Duration required.", ephemeral=True)
        await self.create_giveaway(interaction, data)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=3)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not yours.", ephemeral=True)
        if self.user_id in temp_giveaways:
            del temp_giveaways[self.user_id]
        await interaction.response.edit_message(content="Cancelled.", view=None)

    async def create_giveaway(self, interaction, data):
        # Parse duration
        try:
            unit = data['duration'][-1]
            if unit == 's':
                seconds = int(data['duration'][:-1])
            elif unit == 'm':
                seconds = int(data['duration'][:-1]) * 60
            elif unit == 'h':
                seconds = int(data['duration'][:-1]) * 3600
            elif unit == 'd':
                seconds = int(data['duration'][:-1]) * 86400
            else:
                return await interaction.response.send_message("Invalid duration. Use 10s, 5m, 2h, 1d.", ephemeral=True)
        except:
            return await interaction.response.send_message("Invalid duration format.", ephemeral=True)

        end_time = datetime.utcnow() + timedelta(seconds=seconds)
        emoji = data.get('emoji', '🎉')

        req_list = []
        req_dict = {}
        if data.get('min_messages'):
            req_dict['min_messages'] = int(data['min_messages'])
            req_list.append(f"• **{data['min_messages']} messages**")
        if data.get('min_vc'):
            req_dict['min_vc_minutes'] = int(data['min_vc'])
            req_list.append(f"• **{data['min_vc']} min in VC**")
        if data.get('custom_req'):
            req_dict['custom'] = data['custom_req']
            req_list.append(f"• {data['custom_req']}")

        # Professional embed
        embed = discord.Embed(
            title=f"{emoji} **GIVEAWAY** {emoji}",
            description=f"## {data['prize']}\n\n"
                       f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                       f"**Hosted by:** {interaction.user.mention}\n"
                       f"**Ends:** <t:{int(end_time.timestamp())}:R>\n"
                       f"**ID:** `{data['giveaway_id']}`\n\n"
                       f"━━━━━━━━━━━━━━━━━━━━━━",
            color=0x5865F2
        )
        if req_list:
            embed.add_field(name="Requirements", value="\n".join(req_list), inline=False)
        embed.add_field(name="How to enter", value=f"React with {emoji} below!", inline=False)
        if data.get('image_url'):
            embed.set_image(url=data['image_url'])
        embed.set_footer(text="Winner will be announced instantly.")
        embed.timestamp = end_time

        await interaction.response.defer(ephemeral=True)
        msg = await data['channel'].send(embed=embed)
        await msg.add_reaction(emoji)

        giveaways[str(msg.id)] = {
            'channel_id': data['channel'].id,
            'prize': data['prize'],
            'end_time': end_time.timestamp(),
            'requirements': req_dict,
            'image_url': data.get('image_url'),
            'message_id': msg.id,
            'host_id': interaction.user.id,
            'giveaway_id': data['giveaway_id'],
            'emoji': emoji,
            'ended': False
        }
        save_json(GIVEAWAY_FILE, giveaways)

        del temp_giveaways[self.user_id]
        await interaction.followup.send(f"✅ Giveaway posted in {data['channel'].mention}", ephemeral=True)
        asyncio.create_task(watch_giveaway(msg.id, end_time.timestamp(), emoji, req_dict))

# -------------------- MODALS --------------------
class PrizeModal(Modal, title="Prize"):
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id
        self.add_item(TextInput(label="Prize name", placeholder="e.g. Discord Nitro", max_length=100))

    async def on_submit(self, interaction: discord.Interaction):
        if self.user_id in temp_giveaways:
            temp_giveaways[self.user_id]['prize'] = self.children[0].value
        await interaction.response.send_message(f"Prize set to **{self.children[0].value}**", ephemeral=True)

class DurationModal(Modal, title="Duration"):
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id
        self.add_item(TextInput(label="Duration", placeholder="e.g. 10m, 1h, 2d", max_length=10))

    async def on_submit(self, interaction: discord.Interaction):
        if self.user_id in temp_giveaways:
            temp_giveaways[self.user_id]['duration'] = self.children[0].value
        await interaction.response.send_message(f"Duration set to **{self.children[0].value}**", ephemeral=True)

class MessageReqModal(Modal, title="Message Requirement"):
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id
        self.add_item(TextInput(label="Minimum messages", placeholder="e.g. 100", max_length=10))

    async def on_submit(self, interaction: discord.Interaction):
        if self.user_id in temp_giveaways:
            temp_giveaways[self.user_id]['min_messages'] = self.children[0].value
        await interaction.response.send_message(f"Message requirement set to **{self.children[0].value}**", ephemeral=True)

class VCReqModal(Modal, title="VC Requirement"):
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id
        self.add_item(TextInput(label="Minutes in VC", placeholder="e.g. 50", max_length=10))

    async def on_submit(self, interaction: discord.Interaction):
        if self.user_id in temp_giveaways:
            temp_giveaways[self.user_id]['min_vc'] = self.children[0].value
        await interaction.response.send_message(f"VC requirement set to **{self.children[0].value} min**", ephemeral=True)

class CustomReqModal(Modal, title="Custom Requirement"):
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id
        self.add_item(TextInput(label="Custom rule", placeholder="e.g. Must be in server for 7 days", style=discord.TextStyle.paragraph, max_length=200))

    async def on_submit(self, interaction: discord.Interaction):
        if self.user_id in temp_giveaways:
            temp_giveaways[self.user_id]['custom_req'] = self.children[0].value
        await interaction.response.send_message(f"Custom rule added.", ephemeral=True)

# -------------------- IMAGE HANDLER (UPLOAD) --------------------
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    # Track stats
    uid = str(message.author.id)
    if uid not in user_stats:
        user_stats[uid] = {"messages": 0, "vc_time": 0, "name": str(message.author)}
    user_stats[uid]["messages"] += 1
    user_stats[uid]["name"] = str(message.author)
    save_json(STATS_FILE, user_stats)

    # Image waiting
    if message.author.id in temp_giveaways and temp_giveaways[message.author.id].get('waiting_for_image'):
        try:
            await message.delete()
        except:
            pass
        if message.attachments:
            att = message.attachments[0]
            if att.content_type and att.content_type.startswith('image/'):
                image_url = att.url
                temp_giveaways[message.author.id]['image_url'] = image_url
                temp_giveaways[message.author.id]['waiting_for_image'] = False
                preview_embed = discord.Embed(title="✅ Image Added", description="Preview (will auto-delete):")
                preview_embed.set_image(url=image_url)
                await message.channel.send(embed=preview_embed, delete_after=10)
                async for msg in message.channel.history(limit=5):
                    if msg.author == bot.user and "Send an image" in msg.content:
                        await msg.delete()
                        break
                print(f"Image URL stored via upload: {image_url}")
            else:
                await message.channel.send("❌ That file is not an image. Please upload a .jpg, .png, or .gif", delete_after=3)
        else:
            await message.channel.send("❌ You didn't attach an image. Please upload an image file.", delete_after=3)

    await bot.process_commands(message)

# -------------------- INSTANT WINNER CHECKING --------------------
async def watch_giveaway(msg_id, end_time, emoji, reqs):
    await asyncio.sleep(max(0, end_time - datetime.utcnow().timestamp()))
    if str(msg_id) not in giveaways:
        return
    await end_giveaway_instant(str(msg_id), emoji, reqs)

async def end_giveaway_instant(msg_id, emoji, reqs):
    global user_stats
    data = giveaways.get(msg_id)
    if not data or data.get('ended'):
        return
    channel = bot.get_channel(data['channel_id'])
    try:
        msg = await channel.fetch_message(int(msg_id))
        reaction = discord.utils.get(msg.reactions, emoji=emoji)
        users = [u async for u in reaction.users() if u != bot.user] if reaction else []

        print(f"\n🎯 Ending giveaway: {data['prize']}")
        print(f"Requirements: {reqs}")

        eligible = []
        for u in users:
            uid = str(u.id)
            stats = user_stats.get(uid, {"messages": 0, "vc_time": 0})
            print(f"User {u.name}: messages={stats['messages']}, vc_time={stats['vc_time']:.1f}")
            if check_requirements(uid, reqs):
                eligible.append(u)
                print(f"  ✅ Eligible")
            else:
                print(f"  ❌ Not eligible")

        if eligible:
            winner = random.choice(eligible)
            desc = f"**Winner:** {winner.mention}\n**Prize:** {data['prize']}"
            color = 0x00FF00
            print(f"Winner chosen: {winner.name}")
        else:
            desc = f"No eligible entries.\n**Prize:** {data['prize']}"
            color = 0xFF0000
            print("No eligible entries")

        embed = discord.Embed(title="🎉 Giveaway Ended", description=desc, color=color)
        if data.get('image_url'):
            embed.set_image(url=data['image_url'])
        await msg.reply(embed=embed)

        # Remove giveaway
        del giveaways[msg_id]
        save_json(GIVEAWAY_FILE, giveaways)

        # 🧹 RESET ALL STATS AFTER GIVEAWAY
        user_stats = {}
        save_json(STATS_FILE, user_stats)
        print(f"⚠️ All user stats have been reset for the next giveaway. (Now 0 users tracked)")

    except Exception as e:
        print(f"Error ending giveaway: {e}")

def check_requirements(user_id, reqs):
    if not reqs:
        return True
    stats = user_stats.get(str(user_id), {"messages": 0, "vc_time": 0})
    if reqs.get('min_messages') and stats['messages'] < reqs['min_messages']:
        return False
    if reqs.get('min_vc_minutes') and stats['vc_time'] < reqs['min_vc_minutes']:
        return False
    # Custom requirements are manual
    return True

# -------------------- MAIN PANEL --------------------
class GiveawayMainView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="New Giveaway", style=discord.ButtonStyle.success, emoji="🎁")
    async def new_btn(self, interaction: discord.Interaction, button: Button):
        options = []
        for ch in interaction.guild.text_channels[:25]:
            if ch.permissions_for(interaction.guild.me).send_messages:
                options.append(discord.SelectOption(label=f"#{ch.name}", value=str(ch.id)))
        if not options:
            return await interaction.response.send_message("No accessible channels.", ephemeral=True)
        select = Select(placeholder="Choose channel...", options=options)
        async def select_cb(inter: discord.Interaction):
            ch = inter.guild.get_channel(int(select.values[0]))
            gid = ''.join(random.choices('0123456789abcdef', k=6))
            temp_giveaways[inter.user.id] = {
                'channel': ch, 'prize': None, 'duration': None, 'min_messages': None,
                'min_vc': None, 'custom_req': None, 'emoji': '🎉', 'image_url': None,
                'waiting_for_image': False, 'giveaway_id': gid
            }
            await inter.response.edit_message(content=f"Setup in {ch.mention} | ID: `{gid}`", view=GiveawaySetupView(inter.user.id))
        select.callback = select_cb
        view = View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("Select a channel:", view=view, ephemeral=True)

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary, emoji="✏️")
    async def edit_btn(self, interaction: discord.Interaction, button: Button):
        if not giveaways:
            return await interaction.response.send_message("No active giveaways.", ephemeral=True)
        options = []
        for mid, d in list(giveaways.items())[:25]:
            options.append(discord.SelectOption(label=d['prize'][:50], value=mid, emoji=d.get('emoji','🎁')))
        select = Select(placeholder="Select giveaway...", options=options)
        async def select_cb(inter: discord.Interaction):
            mid = select.values[0]
            data = giveaways[mid]
            view = EditGiveawayView(inter.user.id, data['giveaway_id'], data)
            await inter.response.edit_message(content=f"Editing: {data['prize']}", view=view)
        select.callback = select_cb
        view = View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("Pick a giveaway:", view=view, ephemeral=True)

    @discord.ui.button(label="Reroll", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def reroll_btn(self, interaction: discord.Interaction, button: Button):
        if not giveaways:
            return await interaction.response.send_message("No active giveaways.", ephemeral=True)
        options = []
        for mid, d in list(giveaways.items())[:25]:
            options.append(discord.SelectOption(label=d['prize'][:50], value=mid, emoji=d.get('emoji','🎁')))
        select = Select(placeholder="Select giveaway...", options=options)
        async def select_cb(inter: discord.Interaction):
            mid = select.values[0]
            data = giveaways[mid]
            ch = bot.get_channel(data['channel_id'])
            try:
                msg = await ch.fetch_message(int(mid))
                emoji = data.get('emoji','🎉')
                react = discord.utils.get(msg.reactions, emoji=emoji)
                users = [u async for u in react.users() if u != bot.user] if react else []
                eligible = [u for u in users if check_requirements(u.id, data.get('requirements',{}))]
                if eligible:
                    winner = random.choice(eligible)
                    embed = discord.Embed(title="🔄 Reroll Winner", description=f"{winner.mention} won **{data['prize']}**", color=0x00FF00)
                else:
                    embed = discord.Embed(title="Reroll", description="No eligible entries.", color=0xFF0000)
                if data.get('image_url'):
                    embed.set_image(url=data['image_url'])
                await inter.response.send_message(embed=embed)
            except Exception as e:
                await inter.response.send_message(f"Error: {e}", ephemeral=True)
        select.callback = select_cb
        view = View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("Pick a giveaway:", view=view, ephemeral=True)

# -------------------- EDIT GIVEAWAY VIEW --------------------
class EditGiveawayView(View):
    def __init__(self, user_id, gid, data):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.gid = gid
        self.data = data

    @discord.ui.button(label="Add Time", style=discord.ButtonStyle.primary)
    async def add_time(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return
        modal = ExtendTimeModal(self.gid)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Change Prize", style=discord.ButtonStyle.primary)
    async def ch_prize(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return
        modal = ChangePrizeModal(self.gid)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Change Emoji", style=discord.ButtonStyle.success)
    async def ch_emoji(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.user_id:
            return
        view = EmojiSelectView(self.user_id)
        await interaction.response.send_message("Pick new emoji:", view=view, ephemeral=True)

    @discord.ui.button(label="Done", style=discord.ButtonStyle.success)
    async def done(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(content="Editing finished.", view=None)

class ExtendTimeModal(Modal, title="Add Time"):
    def __init__(self, gid):
        super().__init__()
        self.gid = gid
        self.add_item(TextInput(label="Extra time", placeholder="e.g. 30m, 1h", max_length=10))

    async def on_submit(self, interaction: discord.Interaction):
        for mid, data in giveaways.items():
            if data.get('giveaway_id') == self.gid:
                try:
                    val = self.children[0].value
                    unit = val[-1]
                    if unit == 'm':
                        sec = int(val[:-1])*60
                    elif unit == 'h':
                        sec = int(val[:-1])*3600
                    elif unit == 'd':
                        sec = int(val[:-1])*86400
                    else:
                        return await interaction.response.send_message("Invalid format.", ephemeral=True)
                    data['end_time'] += sec
                    save_json(GIVEAWAY_FILE, giveaways)
                    await interaction.response.send_message(f"Added {val}.", ephemeral=True)
                    asyncio.create_task(watch_giveaway(mid, data['end_time'], data['emoji'], data.get('requirements',{})))
                    return
                except:
                    return await interaction.response.send_message("Error parsing time.", ephemeral=True)
        await interaction.response.send_message("Giveaway not found.", ephemeral=True)

class ChangePrizeModal(Modal, title="Change Prize"):
    def __init__(self, gid):
        super().__init__()
        self.gid = gid
        self.add_item(TextInput(label="New prize name", max_length=100))

    async def on_submit(self, interaction: discord.Interaction):
        for mid, data in giveaways.items():
            if data.get('giveaway_id') == self.gid:
                data['prize'] = self.children[0].value
                save_json(GIVEAWAY_FILE, giveaways)
                try:
                    ch = bot.get_channel(data['channel_id'])
                    msg = await ch.fetch_message(int(mid))
                    embed = msg.embeds[0]
                    desc = embed.description
                    lines = desc.split('\n')
                    lines[0] = f"## {data['prize']}"
                    embed.description = '\n'.join(lines)
                    await msg.edit(embed=embed)
                except:
                    pass
                await interaction.response.send_message("Prize updated.", ephemeral=True)
                return
        await interaction.response.send_message("Giveaway not found.", ephemeral=True)

# -------------------- STATS TRACKING --------------------
@bot.event
async def on_voice_state_update(member, before, after):
    uid = str(member.id)
    if uid not in user_stats:
        user_stats[uid] = {"messages": 0, "vc_time": 0, "name": str(member)}
    if before.channel is None and after.channel is not None:
        vc_tracking[uid] = datetime.utcnow()
    elif before.channel is not None and after.channel is None and uid in vc_tracking:
        joined = vc_tracking.pop(uid)
        minutes = (datetime.utcnow() - joined).total_seconds() / 60
        user_stats[uid]["vc_time"] += minutes
        save_json(STATS_FILE, user_stats)

@tasks.loop(minutes=5)
async def track_vc():
    now = datetime.utcnow()
    for uid, joined in list(vc_tracking.items()):
        minutes = (now - joined).total_seconds() / 60
        if minutes >= 5:
            user_stats[uid]["vc_time"] += minutes
            vc_tracking[uid] = now
            save_json(STATS_FILE, user_stats)

# -------------------- COMMANDS --------------------
@bot.command()
async def giveawaypanel(ctx):
    embed = discord.Embed(
        title="🎮 Giveaway Control",
        description="Create, edit, or reroll giveaways.",
        color=0x5865F2
    )
    await ctx.send(embed=embed, view=GiveawayMainView())

@bot.command()
async def givestats(ctx, member: discord.Member = None):
    m = member or ctx.author
    stats = user_stats.get(str(m.id), {"messages": 0, "vc_time": 0})
    embed = discord.Embed(title=f"📊 {m.display_name}'s Stats", color=0x5865F2)
    embed.add_field(name="Messages", value=stats['messages'], inline=True)
    embed.add_field(name="VC Time", value=f"{stats['vc_time']:.1f} min", inline=True)
    embed.set_thumbnail(url=m.avatar.url if m.avatar else m.default_avatar.url)
    await ctx.send(embed=embed)

# -------------------- ON_READY --------------------
@bot.event
async def on_ready():
    print(f'{bot.user} is online!')
    track_vc.start()

# -------------------- KEEP ALIVE (24/7) --------------------
app = Flask('')
@app.route('/')
def home():
    return "Bot is alive!"

@app.route('/ping')
def ping():
    return "pong", 200

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    server = Thread(target=run)
    server.daemon = True
    server.start()
    print("🌐 Web server started on port 8080")

keep_alive()
bot.run(os.environ['TOKEN'])

# -------------------- KEEP ALIVE (24/7) --------------------
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive! 🤖"

@app.route('/ping')
def ping():
    return "pong", 200

@app.errorhandler(404)
def not_found(e):
    return "Not found", 404

@app.errorhandler(500)
def internal_error(e):
    return "Internal server error", 500

def run():
    try:
        app.run(host='0.0.0.0', port=8080)
    except Exception as e:
        print(f"Flask server error: {e}")

def keep_alive():
    server = Thread(target=run)
    server.daemon = True
    server.start()
    print("🌐 Web server started on port 8080")

keep_alive()
bot.run(os.environ['TOKEN'])
