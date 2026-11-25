import asyncio
from collections import deque
from dataclasses import dataclass
import os
from typing import Dict, Optional
import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands
import imageio_ffmpeg
import yt_dlp

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
AUDIO_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "audio")

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

FFMPEG_STREAM_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

AMBIENCE_PRESETS = {
    "gregoriano": "Gregorian Chants 1 hour monastery ambience",
    "mosteiro_chuva": "Medieval Monastery rain ambience 1 hour",
    "scriptorium": "Medieval ambient music lute harp monastery",
}


@dataclass
class Track:
    title: str
    source: str
    webpage_url: Optional[str] = None
    is_local: bool = False
    requester: str = "Desconhecido"


class GuildMusicState:
    def __init__(self):
        self.queue: deque[Track] = deque()
        self.current: Optional[Track] = None
        self.volume: float = 0.5
        self.loop: bool = False
        self.lock = asyncio.Lock()


def _extract_track(query: str, requester: str) -> Track:
    local_path = os.path.join(AUDIO_DIR, query)
    if os.path.isfile(local_path):
        return Track(title=os.path.basename(local_path), source=local_path, is_local=True, requester=requester)

    with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            entries = [e for e in info["entries"] if e]
            if not entries:
                raise ValueError("Nenhum resultado encontrado.")
            info = entries[0]
        return Track(
            title=info.get("title", "Faixa sem título"),
            source=info["url"],
            webpage_url=info.get("webpage_url"),
            is_local=False,
            requester=requester,
        )


class Music(commands.Cog):
    """Player de voz com comandos padrão (/play, /skip, /stop, etc.) e ambientação medieval."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: Dict[int, GuildMusicState] = {}

    def _get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self.states:
            self.states[guild_id] = GuildMusicState()
        return self.states[guild_id]

    async def _ensure_voice(self, interaction: discord.Interaction) -> Optional[discord.VoiceClient]:
        if not interaction.user.voice or not interaction.user.voice.channel:
            msg = "❌ Você precisa estar conectado a um canal de voz."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return None

        target_channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client
        if vc is None:
            return await target_channel.connect()
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
            ffmpeg_opts = {"options": "-vn"} if next_track.is_local else FFMPEG_STREAM_OPTIONS
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

    @app_commands.command(name="play", description="Toca uma música, canto gregoriano ou ambientação (busca, URL ou arquivo local).")
    @app_commands.describe(busca="Nome da música, link do YouTube/stream ou nome do arquivo em assets/audio")
    async def play(self, interaction: discord.Interaction, busca: str):
        await interaction.response.defer(thinking=True)
        vc = await self._ensure_voice(interaction)
        if not vc:
            return

        try:
            track = await asyncio.to_thread(_extract_track, busca, interaction.user.display_name)
        except Exception as e:
            await interaction.followup.send(f"❌ Não foi possível carregar o áudio: `{e}`", ephemeral=True)
            return

        state = self._get_state(interaction.guild_id)
        state.queue.append(track)

        if not vc.is_playing() and not vc.is_paused():
            await self._play_next(interaction.guild, interaction.channel)
            await interaction.followup.send(f"🎶 Tocando agora: **{track.title}**")
        else:
            await interaction.followup.send(f"📜 Adicionado à fila: **{track.title}**")

    @app_commands.command(name="ambiente", description="Inicia uma ambientação medieval/gregoriana em loop contínuo.")
    @app_commands.choices(
        preset=[
            Choice(name="Cantos Gregorianos", value="gregoriano"),
            Choice(name="Mosteiro Medieval com Chuva", value="mosteiro_chuva"),
            Choice(name="Scriptorium & Alaúde Medieval", value="scriptorium"),
        ]
    )
    @app_commands.describe(preset="Escolha o clima sonoro do Mosteiro")
    async def ambiente(self, interaction: discord.Interaction, preset: Choice[str]):
        await interaction.response.defer(thinking=True)
        vc = await self._ensure_voice(interaction)
        if not vc:
            return

        query = AMBIENCE_PRESETS[preset.value]
        try:
            track = await asyncio.to_thread(_extract_track, query, interaction.user.display_name)
        except Exception as e:
            await interaction.followup.send(f"❌ Erro ao iniciar ambientação: `{e}`", ephemeral=True)
            return

        state = self._get_state(interaction.guild_id)
        state.queue.clear()
        state.current = None
        state.loop = True
        if vc.is_playing() or vc.is_paused():
            vc.stop()
        state.queue.append(track)
        await self._play_next(interaction.guild, interaction.channel)
        await interaction.followup.send(f"🕯️ Ambientação **{preset.name}** iniciada em modo loop: **{track.title}**")

    @app_commands.command(name="pause", description="Pausa a reprodução atual.")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Reprodução pausada.")
        else:
            await interaction.response.send_message("❌ Nada está tocando no momento.", ephemeral=True)

    @app_commands.command(name="resume", description="Retoma a reprodução pausada.")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Reprodução retomada.")
        else:
            await interaction.response.send_message("❌ A reprodução não está pausada.", ephemeral=True)

    @app_commands.command(name="skip", description="Pula para a próxima faixa da fila.")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or (not vc.is_playing() and not vc.is_paused()):
            await interaction.response.send_message("❌ Nada está tocando no momento.", ephemeral=True)
            return
        state = self._get_state(interaction.guild_id)
        was_loop = state.loop
        state.loop = False
        vc.stop()
        state.loop = was_loop
        await interaction.response.send_message("⏭️ Faixa pulada.")

    @app_commands.command(name="stop", description="Para a música, limpa a fila e desconecta do canal de voz.")
    async def stop(self, interaction: discord.Interaction):
        state = self._get_state(interaction.guild_id)
        state.loop = False
        state.current = None
        state.queue.clear()
        vc = interaction.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
            await interaction.response.send_message("⏹️ Reprodução encerrada e bot desconectado.")
        else:
            await interaction.response.send_message("❌ O bot não está em um canal de voz.", ephemeral=True)

    @app_commands.command(name="queue", description="Exibe a faixa atual e a fila de reprodução.")
    async def queue(self, interaction: discord.Interaction):
        state = self._get_state(interaction.guild_id)
        if not state.current and not state.queue:
            await interaction.response.send_message("📭 A fila está vazia.", ephemeral=True)
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
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="volume", description="Ajusta o volume do player (0 a 100).")
    @app_commands.describe(nivel="Volume de 0 a 100")
    async def volume(self, interaction: discord.Interaction, nivel: app_commands.Range[int, 0, 100]):
        state = self._get_state(interaction.guild_id)
        state.volume = nivel / 100.0
        vc = interaction.guild.voice_client
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = state.volume
        await interaction.response.send_message(f"🔊 Volume ajustado para **{nivel}%**.")

    @app_commands.command(name="loop", description="Ativa ou desativa a repetição contínua da faixa atual.")
    async def loop(self, interaction: discord.Interaction):
        state = self._get_state(interaction.guild_id)
        state.loop = not state.loop
        status = "ativado 🔁" if state.loop else "desativado"
        await interaction.response.send_message(f"Modo loop **{status}**.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
