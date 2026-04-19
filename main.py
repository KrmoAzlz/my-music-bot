import os
import asyncio
from threading import Thread
from collections import deque

import discord
from discord.ext import commands
from flask import Flask
import yt_dlp

# =========================
# Flask keep_alive
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is Online!"

def run_web():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    thread = Thread(target=run_web, daemon=True)
    thread.start()

# =========================
# Discord bot setup
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = "P1"

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is not set.")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# =========================
# yt-dlp / ffmpeg options
# =========================
YDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

# =========================
# Guild state
# =========================
queues = {}
volumes = {}
player_messages = {}
current_songs = {}

def get_queue(guild_id: int) -> deque:
    if guild_id not in queues:
        queues[guild_id] = deque()
    return queues[guild_id]

def get_volume(guild_id: int) -> float:
    return volumes.get(guild_id, 1.0)

def clear_guild_state(guild_id: int):
    queues.pop(guild_id, None)
    volumes.pop(guild_id, None)
    player_messages.pop(guild_id, None)
    current_songs.pop(guild_id, None)

# =========================
# Helpers
# =========================
def search_song(query: str) -> dict:
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(query, download=False)

        if not info:
            raise ValueError("لم يتم العثور على نتائج.")

        if "entries" in info:
            entries = info.get("entries") or []
            if not entries:
                raise ValueError("لم يتم العثور على نتائج.")
            info = entries[0]

        url = info.get("url")
        title = info.get("title")
        if not url or not title:
            raise ValueError("تعذر استخراج بيانات الأغنية.")

        return {
            "url": url,
            "title": title,
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail"),
            "webpage_url": info.get("webpage_url", ""),
        }

def format_duration(seconds: int) -> str:
    if not seconds:
        return "00:00"
    minutes, sec = divmod(int(seconds), 60)
    return f"{minutes:02d}:{sec:02d}"

def build_embed(song: dict, requester, queue_size: int, volume: float) -> discord.Embed:
    duration_text = format_duration(song.get("duration", 0))
    queue_text = f"{queue_size} track{'s' if queue_size != 1 else ''} in queue"

    embed = discord.Embed(
        description=f"**[{song['title']}]({song.get('webpage_url', '')})**\n`[{duration_text}]`",
        color=0x2B2D31,
    )
    embed.set_author(name=queue_text)

    thumbnail = song.get("thumbnail")
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)

    requester_mention = requester.mention if requester else "غير معروف"
    embed.add_field(name="Requested by -", value=requester_mention, inline=True)
    embed.add_field(name="Volume:", value=f"{int(volume * 100)}%", inline=True)
    return embed

async def send_or_update_player(ctx, song_data: dict):
    guild_id = ctx.guild.id
    queue = get_queue(guild_id)
    vol = get_volume(guild_id)

    embed = build_embed(song_data["song"], song_data.get("requester"), len(queue), vol)
    view = MusicControls()

    old_msg = player_messages.get(guild_id)
    if old_msg:
        try:
            await old_msg.edit(embed=embed, view=view)
            return
        except Exception:
            pass

    msg = await ctx.send(embed=embed, view=view)
    player_messages[guild_id] = msg

async def play_next_song(ctx):
    guild_id = ctx.guild.id
    vc = ctx.voice_client

    if not vc:
        return

    queue = get_queue(guild_id)
    if not queue:
        current_songs.pop(guild_id, None)
        return

    song_data = queue.popleft()
    song = song_data["song"]
    vol = get_volume(guild_id)

    source = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(song["url"], **FFMPEG_OPTIONS),
        volume=vol,
    )

    current_songs[guild_id] = song_data

    def after_play(error):
        if error:
            print(f"Playback error: {error}")
        future = asyncio.run_coroutine_threadsafe(play_next_song(ctx), bot.loop)
        try:
            future.result()
        except Exception as exc:
            print(f"Error while scheduling next song: {exc}")

    vc.play(source, after=after_play)
    await send_or_update_player(ctx, song_data)

# =========================
# UI Controls
# =========================
class MusicControls(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.secondary, row=0)
    async def play_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("❌ البوت ليس في قناة صوتية.", ephemeral=True)

        if vc.is_playing():
            vc.pause()
            return await interaction.response.send_message("⏸️ تم الإيقاف المؤقت.", ephemeral=True)

        if vc.is_paused():
            vc.resume()
            return await interaction.response.send_message("▶️ تم الاستئناف.", ephemeral=True)

        await interaction.response.send_message("❌ لا يوجد شيء يُشغَّل حالياً.", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("⏭️ تم التخطي!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ لا توجد أغنية حالياً.", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.secondary, row=0)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            guild_id = interaction.guild.id
            queues[guild_id] = deque()
            current_songs.pop(guild_id, None)
            vc.stop()
            await interaction.response.send_message("⏹️ تم الإيقاف ومسح الطابور.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ البوت ليس في قناة صوتية.", ephemeral=True)

    @discord.ui.button(emoji="🔇", style=discord.ButtonStyle.secondary, row=1)
    async def mute_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.source:
            vc.source.volume = 0.0
            volumes[interaction.guild.id] = 0.0
            await interaction.response.send_message("🔇 تم كتم الصوت.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ لا يوجد مصدر صوت.", ephemeral=True)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, row=1)
    async def vol_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.source:
            current = get_volume(interaction.guild.id)
            new_vol = max(0.0, current - 0.1)
            vc.source.volume = new_vol
            volumes[interaction.guild.id] = new_vol
            await interaction.response.send_message(f"🔉 الصوت: {int(new_vol * 100)}%", ephemeral=True)
        else:
            await interaction.response.send_message("❌ لا يوجد مصدر صوت.", ephemeral=True)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, row=1)
    async def vol_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.source:
            current = get_volume(interaction.guild.id)
            new_vol = min(1.0, current + 0.1)
            vc.source.volume = new_vol
            volumes[interaction.guild.id] = new_vol
            await interaction.response.send_message(f"🔊 الصوت: {int(new_vol * 100)}%", ephemeral=True)
        else:
            await interaction.response.send_message("❌ لا يوجد مصدر صوت.", ephemeral=True)

# =========================
# Commands
# =========================
@bot.command(name="join")
async def join(ctx):
    if not ctx.author.voice:
        return await ctx.send("❌ يجب أن تكون في قناة صوتية أولاً!")

    channel = ctx.author.voice.channel
    if ctx.voice_client:
        await ctx.voice_client.move_to(channel)
    else:
        await channel.connect()

    await ctx.send(f"✅ انضممت إلى **{channel.name}**")

@bot.command(name="play")
async def play(ctx, *, query: str):
    if not ctx.author.voice:
        return await ctx.send("❌ يجب أن تكون في قناة صوتية!")

    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()

    search_msg = await ctx.send(f"🔍 أبحث عن: `{query}`...")

    try:
        song = await asyncio.get_running_loop().run_in_executor(
            None, lambda: search_song(query)
        )
    except Exception as e:
        return await search_msg.edit(content=f"❌ حدث خطأ: {e}")

    try:
        await search_msg.delete()
    except Exception:
        pass

    guild_id = ctx.guild.id
    queue = get_queue(guild_id)

    song_data = {
        "song": song,
        "requester": ctx.author,
    }

    vc = ctx.voice_client
    if vc.is_playing() or vc.is_paused():
        queue.append(song_data)
        embed = discord.Embed(
            description=f"📋 أُضيف للطابور: **{song['title']}**\nالرقم **{len(queue)}** في الانتظار",
            color=0x2B2D31,
        )
        if song.get("thumbnail"):
            embed.set_thumbnail(url=song["thumbnail"])
        await ctx.send(embed=embed, delete_after=10)
        return

    queue.append(song_data)
    await play_next_song(ctx)

@bot.command(name="skip")
async def skip(ctx):
    if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        ctx.voice_client.stop()
        await ctx.send("⏭️ تم التخطي!", delete_after=5)
    else:
        await ctx.send("❌ لا توجد أغنية تُشغَّل حالياً.")

@bot.command(name="stop")
async def stop(ctx):
    if ctx.voice_client:
        queues[ctx.guild.id] = deque()
        current_songs.pop(ctx.guild.id, None)
        ctx.voice_client.stop()
        await ctx.send("⏹️ تم الإيقاف ومسح الطابور.", delete_after=5)
    else:
        await ctx.send("❌ البوت ليس في قناة صوتية.")

@bot.command(name="pause")
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ تم الإيقاف المؤقت.", delete_after=5)
    else:
        await ctx.send("❌ لا توجد أغنية تُشغَّل حالياً.")

@bot.command(name="resume")
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ تم الاستئناف.", delete_after=5)
    else:
        await ctx.send("❌ الأغنية ليست متوقفة مؤقتاً.")

@bot.command(name="volume")
async def volume(ctx, vol: int):
    if not ctx.voice_client:
        return await ctx.send("❌ البوت ليس في قناة صوتية.")

    if not 0 <= vol <= 100:
        return await ctx.send("❌ الصوت يجب أن يكون بين 0 و 100.")

    volumes[ctx.guild.id] = vol / 100

    if ctx.voice_client.source:
        ctx.voice_client.source.volume = vol / 100

    await ctx.send(f"🔊 تم ضبط الصوت على **{vol}%**", delete_after=5)

@bot.command(name="leave")
async def leave(ctx):
    if ctx.voice_client:
        guild_id = ctx.guild.id
        clear_guild_state(guild_id)
        await ctx.voice_client.disconnect()
        await ctx.send("👋 وداعاً!")
    else:
        await ctx.send("❌ البوت ليس في قناة صوتية.")

@bot.command(name="queue")
async def show_queue(ctx):
    queue = get_queue(ctx.guild.id)
    if not queue:
        return await ctx.send("📋 الطابور فارغ حالياً.")

    lines = [f"`{i + 1}.` {item['song']['title']}" for i, item in enumerate(queue)]
    embed = discord.Embed(
        title=f"📋 الطابور — {len(queue)} أغنية",
        description="\n".join(lines),
        color=0x2B2D31,
    )
    await ctx.send(embed=embed)

@bot.command(name="help_music")
async def help_music(ctx):
    embed = discord.Embed(title="🎵 أوامر البوت", color=0x2B2D31)
    commands_list = [
        ("P1play [اسم/رابط]", "تشغيل أغنية أو إضافتها للطابور"),
        ("P1skip", "تخطي الأغنية الحالية"),
        ("P1pause", "إيقاف مؤقت"),
        ("P1resume", "استئناف التشغيل"),
        ("P1volume [0-100]", "ضبط مستوى الصوت"),
        ("P1stop", "إيقاف وتفريغ الطابور"),
        ("P1queue", "عرض الطابور"),
        ("P1join / P1leave", "انضمام / مغادرة القناة"),
    ]
    for name, value in commands_list:
        embed.add_field(name=name, value=value, inline=False)
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"✅ البوت جاهز: {bot.user}")

# =========================
# Run
# =========================
keep_alive()
bot.run(TOKEN)
