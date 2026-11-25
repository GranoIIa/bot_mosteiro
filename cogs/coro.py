import asyncio
from collections import deque
from dataclasses import dataclass
import io
import json
import math
import os
import platform
import shutil
import struct
from typing import Dict, Optional
import urllib.parse
import urllib.request
import discord
from discord import app_commands
from discord.ext import commands
import imageio_ffmpeg
import yt_dlp
from database.connection import db

try:
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_EXE = shutil.which("ffmpeg") or "ffmpeg"
AUDIO_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "audio")

COOKIES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cookies.txt")

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "no_color": True,
    "default_search": "scsearch5",
    "socket_timeout": 10,
    "source_address": "0.0.0.0",
}

FFMPEG_STREAM_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

AMBIENCE_PRESETS = {
    "gregoriano": "scsearch5:gregorian chant",
    "mosteiro_chuva": "scsearch5:rain monastery",
    "scriptorium": "scsearch5:medieval lute music",
}


@dataclass
class Track:
    title: str
    source: str
    webpage_url: Optional[str] = None
    is_local: bool = False
    is_hls: bool = False
    requester: str = "Desconhecido"


class GuildMusicState:
    def __init__(self):
        self.queue: deque[Track] = deque()
        self.current: Optional[Track] = None
        self.volume: float = 0.5
        self.loop: bool = False
        self.lock = asyncio.Lock()


def _fetch_youtube_title(url: str) -> Optional[str]:
    try:
        oembed = "https://www.youtube.com/oembed?url=" + urllib.parse.quote(url, safe="") + "&format=json"
        with urllib.request.urlopen(oembed, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("title")
    except Exception:
        return None


def _extract_track(query: str, requester: str) -> Track:
    local_path = os.path.join(AUDIO_DIR, query)
    if os.path.isfile(local_path):
        return Track(title=os.path.basename(local_path), source=local_path, is_local=True, requester=requester)

    opts = dict(YTDL_OPTIONS)
    if os.path.isfile(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE

    def _run_ydl(target_query: str) -> Track:
        is_direct_url = target_query.startswith(("http://", "https://"))
        run_opts = dict(opts)
        if not is_direct_url:
            run_opts["ignoreerrors"] = True
            if target_query.startswith("scsearch:"):
                target_query = "scsearch5:" + target_query[len("scsearch:"):]

        with yt_dlp.YoutubeDL(run_opts) as ydl:
            info = ydl.extract_info(target_query, download=False)
            if not info:
                raise ValueError("Nenhum resultado reproduzível encontrado.")
            if "entries" in info:
                entries = [e for e in info["entries"] if e and e.get("url")]
                if not entries:
                    raise ValueError("Nenhum resultado reproduzível encontrado (faixas bloqueadas ou com DRM).")
                info = entries[0]
            url = info["url"]
            protocol = info.get("protocol", "")
            is_hls = "m3u8" in protocol or ".m3u8" in url
            return Track(
                title=info.get("title", "Faixa sem título"),
                source=url,
                webpage_url=info.get("webpage_url"),
                is_local=False,
                is_hls=is_hls,
                requester=requester,
            )

    try:
        return _run_ydl(query)
    except Exception as exc:
        err_str = str(exc)
        is_bot_block = "Sign in to confirm" in err_str or "bot" in err_str.lower() or "Nenhum resultado" in err_str
        if not is_bot_block:
            raise

        search_term = query
        if query.startswith(("http://", "https://")) and ("youtube.com" in query or "youtu.be" in query):
            yt_title = _fetch_youtube_title(query)
            if not yt_title:
                raise
            search_term = yt_title
        elif query.startswith(("http://", "https://", "scsearch:", "ytsearch:")):
            raise

        try:
            return _run_ydl(f"scsearch:{search_term}")
        except Exception:
            short_q = " ".join(search_term.split()[:3])
            if short_q and short_q != search_term:
                return _run_ydl(f"scsearch:{short_q}")
            raise


class Music(commands.Cog):
    """Player de voz com comandos híbridos (!play e /play, !skip e /skip, etc.) e ambientação medieval."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: Dict[int, GuildMusicState] = {}

    def _get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self.states:
            self.states[guild_id] = GuildMusicState()
        return self.states[guild_id]

    async def _check_music_channel(self, ctx: commands.Context) -> bool:
        settings = await db.get_guild_settings(ctx.guild.id)
        music_channel_id = settings.get("music_channel")
        if music_channel_id and ctx.guild.get_channel(music_channel_id) and ctx.channel.id != music_channel_id:
            await ctx.send(f"🎶 Use os comandos de música apenas no canal <#{music_channel_id}>.")
            return False
        return True

    async def _ensure_voice(self, ctx: commands.Context) -> Optional[discord.VoiceClient]:
        if not discord.opus.is_loaded() and os.name == "posix":
            machine = platform.machine().lower()
            arch_folder = "aarch64" if machine in ("aarch64", "arm64") else "x86_64"
            bundled = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib", arch_folder, "libopus.so.0")
            if os.path.isfile(bundled):
                try:
                    discord.opus.load_opus(bundled)
                except Exception:
                    pass

        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("❌ Você precisa estar conectado a um canal de voz.")
            return None

        target_channel = ctx.author.voice.channel
        vc = ctx.guild.voice_client
        if vc is None:
            return await target_channel.connect(timeout=30.0, self_deaf=True)
        if vc.channel != target_channel:
            await vc.move_to(target_channel)
        return vc

    async def _play_next(self, guild: discord.Guild, text_channel: Optional[discord.abc.Messageable]):
        state = self._get_state(guild.id)
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            state.current = None
            state.queue.clear()
            return

        async with state.lock:
            if state.loop and state.current is not None:
                next_track = state.current
                if not next_track.is_local and next_track.webpage_url:
                    try:
                        next_track = await asyncio.to_thread(_extract_track, next_track.webpage_url, next_track.requester)
                    except Exception:
                        pass
            elif state.queue:
                next_track = state.queue.popleft()
            else:
                state.current = None
                return

            state.current = next_track
            if next_track.is_local or next_track.is_hls:
                ffmpeg_opts = {"options": "-vn"}
            else:
                ffmpeg_opts = FFMPEG_STREAM_OPTIONS
            raw_source = discord.FFmpegPCMAudio(next_track.source, executable=FFMPEG_EXE, **ffmpeg_opts)
            audio = discord.PCMVolumeTransformer(raw_source, volume=state.volume)

            def after_play(error):
                if error:
                    print(f"❌ Erro no player de voz ({guild.id}): {error}")
                fut = asyncio.run_coroutine_threadsafe(self._play_next(guild, text_channel), self.bot.loop)
                try:
                    fut.result()
                except Exception:
                    pass

            vc.play(audio, after=after_play)

    @commands.hybrid_command(name="play", description="Toca uma música, canto gregoriano ou ambientação (busca, URL ou arquivo local).")
    @app_commands.describe(busca="Nome da música, link do YouTube/stream ou nome do arquivo em assets/audio")
    async def play(self, ctx: commands.Context, *, busca: str):
        if not await self._check_music_channel(ctx):
            return
        await ctx.defer()
        try:
            try:
                vc = await self._ensure_voice(ctx)
            except asyncio.TimeoutError:
                await ctx.send("❌ Tempo esgotado ao conectar ao canal de voz. Verifique as permissões do bot e tente novamente.")
                return
            if not vc:
                return

            try:
                track = await asyncio.wait_for(
                    asyncio.to_thread(_extract_track, busca, ctx.author.display_name),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                await ctx.send("❌ Tempo esgotado ao buscar a música. Tente outro nome ou link.")
                return

            state = self._get_state(ctx.guild.id)
            state.queue.append(track)

            if not vc.is_playing() and not vc.is_paused():
                await self._play_next(ctx.guild, ctx.channel)
                await ctx.send(f"🎶 Tocando agora: **{track.title}**")
            else:
                await ctx.send(f"📜 Adicionado à fila: **{track.title}**")
        except Exception as e:
            await ctx.send(f"❌ Não foi possível tocar o áudio: `{type(e).__name__}: {e}`")

    @commands.hybrid_command(name="ambiente", description="Inicia uma ambientação medieval/gregoriana em loop contínuo.")
    @app_commands.describe(preset="Escolha a ambientação do mosteiro")
    @app_commands.choices(
        preset=[
            app_commands.Choice(name="Canto Gregoriano", value="gregoriano"),
            app_commands.Choice(name="Chuva no Mosteiro", value="mosteiro_chuva"),
            app_commands.Choice(name="Scriptorium & Alaúde Medieval", value="scriptorium"),
        ]
    )
    async def ambiente(self, ctx: commands.Context, preset: str = "gregoriano"):
        if not await self._check_music_channel(ctx):
            return
        if preset not in AMBIENCE_PRESETS:
            await ctx.send(f"❌ Preset inválido. Opções: `{', '.join(AMBIENCE_PRESETS.keys())}`")
            return
        await ctx.defer()
        try:
            try:
                vc = await self._ensure_voice(ctx)
            except asyncio.TimeoutError:
                await ctx.send("❌ Tempo esgotado ao conectar ao canal de voz. Verifique as permissões do bot e tente novamente.")
                return
            if not vc:
                return

            query = AMBIENCE_PRESETS[preset]
            try:
                track = await asyncio.wait_for(
                    asyncio.to_thread(_extract_track, query, ctx.author.display_name),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                await ctx.send("❌ Tempo esgotado ao buscar a ambientação. Tente novamente.")
                return

            state = self._get_state(ctx.guild.id)
            state.queue.clear()
            state.current = None
            state.loop = True
            if vc.is_playing() or vc.is_paused():
                vc.stop()
            state.queue.append(track)
            await self._play_next(ctx.guild, ctx.channel)
            await ctx.send(f"🕯️ Ambientação **{preset}** iniciada em modo loop: **{track.title}**")
        except Exception as e:
            await ctx.send(f"❌ Erro ao iniciar ambientação: `{type(e).__name__}: {e}`")

    @commands.hybrid_command(name="pause", description="Pausa a reprodução atual.")
    async def pause(self, ctx: commands.Context):
        if not await self._check_music_channel(ctx):
            return
        vc = ctx.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await ctx.send("⏸️ Reprodução pausada.")
        else:
            await ctx.send("❌ Nada está tocando no momento.")

    @commands.hybrid_command(name="resume", description="Retoma a reprodução pausada.")
    async def resume(self, ctx: commands.Context):
        if not await self._check_music_channel(ctx):
            return
        vc = ctx.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await ctx.send("▶️ Reprodução retomada.")
        else:
            await ctx.send("❌ A reprodução não está pausada.")

    @commands.hybrid_command(name="skip", description="Pula para a próxima faixa da fila.")
    async def skip(self, ctx: commands.Context):
        if not await self._check_music_channel(ctx):
            return
        vc = ctx.guild.voice_client
        if not vc or (not vc.is_playing() and not vc.is_paused()):
            await ctx.send("❌ Nada está tocando no momento.")
            return
        state = self._get_state(ctx.guild.id)
        was_loop = state.loop
        state.loop = False
        vc.stop()
        state.loop = was_loop
        await ctx.send("⏭️ Faixa pulada.")

    @commands.hybrid_command(name="stop", description="Para a música, limpa a fila e desconecta do canal de voz.")
    async def stop(self, ctx: commands.Context):
        if not await self._check_music_channel(ctx):
            return
        state = self._get_state(ctx.guild.id)
        state.loop = False
        state.current = None
        state.queue.clear()
        vc = ctx.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
            await ctx.send("⏹️ Reprodução encerrada e bot desconectado.")
        else:
            await ctx.send("❌ O bot não está em um canal de voz.")

    @commands.hybrid_command(name="queue", aliases=["fila"], description="Exibe a faixa atual e a fila de reprodução.")
    async def queue(self, ctx: commands.Context):
        if not await self._check_music_channel(ctx):
            return
        state = self._get_state(ctx.guild.id)
        if not state.current and not state.queue:
            await ctx.send("📭 A fila está vazia.")
            return
        desc = []
        if state.current:
            loop_tag = " 🔁" if state.loop else ""
            desc.append(f"**Tocando agora:** {state.current.title}{loop_tag}")
        if state.queue:
            desc.append("\n**Próximas na fila:**")
            for idx, item in enumerate(list(state.queue)[:10], start=1):
                desc.append(f"`{idx}.` {item.title} *(pedido por {item.requester})*")
        embed = discord.Embed(title="🎶 Fila do Coro", description="\n".join(desc), color=discord.Color.dark_gold())
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="volume", description="Ajusta o volume do player (0 a 100).")
    @app_commands.describe(nivel="Volume de 0 a 100")
    async def volume(self, ctx: commands.Context, nivel: int = 50):
        if not await self._check_music_channel(ctx):
            return
        nivel = max(0, min(100, nivel))
        state = self._get_state(ctx.guild.id)
        state.volume = nivel / 100.0
        vc = ctx.guild.voice_client
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = state.volume
        await ctx.send(f"🔊 Volume ajustado para **{nivel}%**.")

    @commands.hybrid_command(name="loop", description="Ativa ou desativa a repetição contínua da faixa atual.")
    async def loop(self, ctx: commands.Context):
        if not await self._check_music_channel(ctx):
            return
        state = self._get_state(ctx.guild.id)
        state.loop = not state.loop
        status = "ativado 🔁" if state.loop else "desativado"
        await ctx.send(f"Modo loop **{status}**.")

    @commands.command(name="testaudio")
    @commands.is_owner()
    async def testaudio(self, ctx: commands.Context):
        """Diagnostica o áudio de voz tocando um bipe puro (sem FFmpeg/yt-dlp)."""
        vc = await self._ensure_voice(ctx)
        if not vc:
            return
        if vc.is_playing() or vc.is_paused():
            vc.stop()

        # Gera 2 segundos de tom 440Hz estéreo 48kHz s16le
        sample_rate = 48000
        duration = 2
        amp = 8000
        buf = bytearray()
        for i in range(sample_rate * duration):
            val = int(amp * math.sin(2.0 * math.pi * 440.0 * i / sample_rate))
            sample = struct.pack("<hh", val, val)
            buf.extend(sample)

        try:
            import davey
            davey_ver = getattr(davey, "__version__", "ok")
        except Exception as e:
            davey_ver = f"erro: {e}"

        info_msg = (
            f"🔧 **Diagnóstico de Voz**\n"
            f"• `opus.is_loaded()`: `{discord.opus.is_loaded()}`\n"
            f"• `davey`: `{davey_ver}`\n"
            f"• `ffmpeg`: `{FFMPEG_EXE}`\n"
            f"• `vc.is_connected()`: `{vc.is_connected()}` | `latency`: `{vc.latency * 1000:.0f}ms`\n"
            f"🔊 Tocando tom de teste (440Hz por 2s)..."
        )
        await ctx.send(info_msg)
        vc.play(discord.PCMAudio(io.BytesIO(bytes(buf))))


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
