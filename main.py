import discord
from flask import Flask
from threading import Thread

app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    Thread(target=run).start()

from discord.ext import commands
import yt_dlp
import asyncio
from collections import deque

# --- الإعدادات الأساسية ---
import os
TOKEN = os.getenv('DISCORD_TOKEN')
PREFIX = "P1"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# --- إعدادات yt-dlp ---
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

# --- إدارة الطابور والصوت والرسائل ---
queues = {}
volumes = {}
player_messages = {}
current_songs = {}

def get_queue(guild_id):
    if guild_id not in queues:
        queues[guild_id] = deque()
    return queues[guild_id]

def get_volume(guild_id):
    return volumes.get(guild_id, 1.0)

# --- دالة البحث ---
def search_song(query):
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(query, download=False)
        if 'entries' in info:
            info = info['entries'][0]
        return {
            'url': info['url'],
            'title': info['title'],
            'duration': info.get('duration', 0),
            'thumbnail': info.get('thumbnail', None),
            'webpage_url': info.get('webpage_url', ''),
        }

# --- تحويل الثواني لـ mm:ss ---
def format_duration(seconds):
    if not seconds:
        return "00:00"
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"

# --- بناء الـ Embed ---
def build_embed(song, requester, queue_size, volume):
    dur = format_duration(song['duration'])
    queue_text = f"{queue_size} track{'s' if queue_size != 1 else ''} in queue"

    embed = discord.Embed(
        description=f"**[{song['title']}]({song['webpage_url']})**\n`[{dur}]`",
        color=0x2B2D31
    )
    embed.set_author(name=queue_text)
    if song['thumbnail']:
        embed.set_thumbnail(url=song['thumbnail'])
    embed.add_field(name="Requested by -", value=f"{requester.mention}", inline=True)
    embed.add_field(name="Volume:", value=f"{int(volume * 100)}", inline=True)
    return embed

# --- أزرار التحكم ---
class MusicControls(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=None)
        self.ctx = ctx

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary, row=0)
    async def play_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            if vc.is_playing():
                vc.pause()
                await interaction.response.send_message("⏸️ تم الإيقاف المؤقت.", ephemeral=True)
            elif vc.is_paused():
                vc.resume()
                await interaction.response.send_message("▶️ تم الاستئناف.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ لا يوجد شيء يُشغَّل.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ البوت مش في قناة.", ephemeral=True)

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏮️ لا يوجد رجوع للأغنية السابقة.", ephemeral=True)

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.secondary, row=0)
    async def pause_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ تم الإيقاف المؤقت.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ الأغنية مش شغّالة.", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("⏭️ تم التخطي!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ لا توجد أغنية.", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.secondary, row=0)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            queues[interaction.guild.id] = deque()
            vc.stop()
            await interaction.response.send_message("⏹️ تم الإيقاف ومسح الطابور.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ البوت مش في قناة.", ephemeral=True)

    @discord.ui.button(emoji="🔇", style=discord.ButtonStyle.secondary, row=1)
    async def mute_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.source:
            vc.source.volume = 0
            volumes[interaction.guild.id] = 0
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

    @discord.ui.button(emoji="❤️", style=discord.ButtonStyle.danger, row=1)
    async def like_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❤️ أُضيفت للمفضلة!", ephemeral=True)

    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.secondary, row=1)
    async def fast_forward(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏩ التقديم السريع غير مدعوم حالياً.", ephemeral=True)

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

# --- دالة تشغيل الأغنية التالية ---
def play_next(ctx):
    queue = get_queue(ctx.guild.id)
    if queue:
        song = queue.popleft()
        vol = get_volume(ctx.guild.id)
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTIONS),
            volume=vol
        )
        current_songs[ctx.guild.id] = song
        ctx.voice_client.play(
            source,
            after=lambda e: asyncio.run_coroutine_threadsafe(
                update_player(ctx, song), bot.loop
            )
        )

async def update_player(ctx, song):
    queue = get_queue(ctx.guild.id)
    vol = get_volume(ctx.guild.id)
    embed = build_embed(song, ctx.author, len(queue), vol)
    view = MusicControls(ctx)

    if ctx.guild.id in player_messages:
        try:
            await player_messages[ctx.guild.id].edit(embed=embed, view=view)
        except:
            msg = await ctx.send(embed=embed, view=view)
            player_messages[ctx.guild.id] = msg
    else:
        msg = await ctx.send(embed=embed, view=view)
        player_messages[ctx.guild.id] = msg

    play_next(ctx)

# --- الأوامر ---

@bot.command(name='join')
async def join(ctx):
    if not ctx.author.voice:
        return await ctx.send("❌ يجب أن تكون في قناة صوتية أولاً!")
    channel = ctx.author.voice.channel
    if ctx.voice_client:
        await ctx.voice_client.move_to(channel)
    else:
        await channel.connect()
    await ctx.send(f"✅ انضممت إلى **{channel.name}**")

@bot.command(name='play')
async def play(ctx, *, query: str):
    if not ctx.author.voice:
        return await ctx.send("❌ يجب أن تكون في قناة صوتية!")

    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()

    search_msg = await ctx.send(f"🔍 أبحث عن: `{query}`...")

    try:
        song = await asyncio.get_event_loop().run_in_executor(
            None, lambda: search_song(query)
        )
    except Exception as e:
        return await search_msg.edit(content=f"❌ حدث خطأ: {e}")

    await search_msg.delete()

    queue = get_queue(ctx.guild.id)
    vol = get_volume(ctx.guild.id)

    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        queue.append(song)
        embed = discord.Embed(
            description=f"📋 أُضيف للطابور: **{song['title']}**\nالرقم **{len(queue)}** في الانتظار",
            color=0x2B2D31
        )
        if song['thumbnail']:
            embed.set_thumbnail(url=song['thumbnail'])
        await ctx.send(embed=embed, delete_after=10)
    else:
        current_songs[ctx.guild.id] = song
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTIONS),
            volume=vol
        )
        ctx.voice_client.play(
            source,
            after=lambda e: play_next(ctx)
        )
        embed = build_embed(song, ctx.author, len(queue), vol)
        view = MusicControls(ctx)
        msg = await ctx.send(embed=embed, view=view)
        player_messages[ctx.guild.id] = msg

@bot.command(name='skip')
async def skip(ctx):
    if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        ctx.voice_client.stop()
        await ctx.send("⏭️ تم التخطي!", delete_after=5)
    else:
        await ctx.send("❌ لا توجد أغنية تُشغَّل حالياً.")

@bot.command(name='stop')
async def stop(ctx):
    if ctx.voice_client:
        queues[ctx.guild.id] = deque()
        ctx.voice_client.stop()
        await ctx.send("⏹️ تم الإيقاف ومسح الطابور.", delete_after=5)
    else:
        await ctx.send("❌ البوت ليس في قناة صوتية.")

@bot.command(name='pause')
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ تم الإيقاف المؤقت.", delete_after=5)
    else:
        await ctx.send("❌ لا توجد أغنية تُشغَّل حالياً.")

@bot.command(name='resume')
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ تم الاستئناف.", delete_after=5)
    else:
        await ctx.send("❌ الأغنية مش موقوفة.")

@bot.command(name='volume')
async def volume(ctx, vol: int):
    if not ctx.voice_client:
        return await ctx.send("❌ البوت مش في قناة صوتية.")
    if not 0 <= vol <= 100:
        return await ctx.send("❌ الصوت يجب أن يكون بين 0 و 100.")
    volumes[ctx.guild.id] = vol / 100
    if ctx.voice_client.source:
        ctx.voice_client.source.volume = vol / 100
    await ctx.send(f"🔊 تم ضبط الصوت على **{vol}%**", delete_after=5)

@bot.command(name='leave')
async def leave(ctx):
    if ctx.voice_client:
        queues.pop(ctx.guild.id, None)
        volumes.pop(ctx.guild.id, None)
        player_messages.pop(ctx.guild.id, None)
        current_songs.pop(ctx.guild.id, None)
        await ctx.voice_client.disconnect()
        await ctx.send("👋 وداعاً!")
    else:
        await ctx.send("❌ البوت ليس في قناة صوتية.")

@bot.command(name='queue')
async def show_queue(ctx):
    queue = get_queue(ctx.guild.id)
    if not queue:
        return await ctx.send("📋 الطابور فارغ حالياً.")
    lines = [f"`{i+1}.` {s['title']}" for i, s in enumerate(queue)]
    embed = discord.Embed(
        title=f"📋 الطابور — {len(queue)} أغنية",
        description="\n".join(lines),
        color=0x2B2D31
    )
    await ctx.send(embed=embed)

@bot.command(name='help_music')
async def help_music(ctx):
    embed = discord.Embed(title="🎵 أوامر البوت", color=0x2B2D31)
    cmds = [
        ("P1play [اسم/رابط]", "تشغيل أغنية أو إضافتها للطابور"),
        ("P1skip", "تخطي الأغنية الحالية"),
        ("P1pause", "إيقاف مؤقت"),
        ("P1resume", "استئناف التشغيل"),
        ("P1volume [0-100]", "ضبط مستوى الصوت"),
        ("P1stop", "إيقاف وتفريغ الطابور"),
        ("P1queue", "عرض الطابور"),
        ("P1join / P1leave", "انضمام / مغادرة القناة"),
    ]
    for name, value in cmds:
        embed.add_field(name=name, value=value, inline=False)
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"✅ البوت جاهز: {bot.user}")
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "I'm alive"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# أضف هذا السطر قبل bot.run
keep_alive()

bot.run(TOKEN)