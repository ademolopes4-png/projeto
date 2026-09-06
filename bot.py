import asyncio
import datetime
import os
import random
import discord
from discord.ext import commands
from flask import Flask
from threading import Thread

# Configuração do Servidor Web Flask para o Render / UptimeRobot
app = Flask('')

@app.route('/')
def home():
    return "Bot de Partidas Online!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# Configuração do Bot do Discord
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

fila_1v1 = []
fila_pula_contra = []
ranking_vitorias = {}

LOG_CHANNEL_NAME = "logs-partidas"
RANKING_CHANNEL_NAME = "ranking"


class FilaView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  def gerar_embed(self, bot_user=None):
    embed = discord.Embed(
        title="Sistema de Partidas",
        description="Clique nos botões abaixo para gerenciar sua entrada ou saída das filas.",
        color=discord.Color.blurple(),
    )

    texto_1v1 = (
        f"({len(fila_1v1)}/2)\n"
        if not fila_1v1
        else f"({len(fila_1v1)}/2)\n"
        + "\n".join([f"• {m.mention}" for m in fila_1v1])
    )
    embed.add_field(name="🎮 Fila 1v1", value=texto_1v1, inline=False)

    texto_pc = (
        f"({len(fila_pula_contra)}/2)\n"
        if not fila_pula_contra
        else f"({len(fila_pula_contra)}/2)\n"
        + "\n".join([f"• {m.mention}" for m in fila_pula_contra])
    )
    embed.add_field(
        name="⚡ Fila Pula Contra", value=texto_pc, inline=False
    )

    if bot_user and bot_user.avatar:
      embed.set_thumbnail(url=bot_user.avatar.url)

    return embed

  @discord.ui.button(
      label="Entrar 1v1",
      style=discord.ButtonStyle.primary,
      custom_id="btn_1v1",
  )
  async def callback_1v1(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    user = interaction.user
    if user in fila_1v1:
      await interaction.response.defer()
      return

    if user in fila_pula_contra:
      fila_pula_contra.remove(user)

    fila_1v1.append(user)
    await interaction.message.edit(embed=self.gerar_embed(interaction.client.user))
    await interaction.response.defer()

    if len(fila_1v1) >= 2:
      p1 = fila_1v1.pop(0)
      p2 = fila_1v1.pop(0)
      await interaction.message.edit(embed=self.gerar_embed(interaction.client.user))
      await criar_sala_partida(interaction.guild, p1, p2, "1v1")

  @discord.ui.button(
      label="Entrar Pula Contra",
      style=discord.ButtonStyle.success,
      custom_id="btn_pula_contra",
  )
  async def callback_pula_contra(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    user = interaction.user
    if user in fila_pula_contra:
      await interaction.response.defer()
      return

    if user in fila_1v1:
      fila_1v1.remove(user)

    fila_pula_contra.append(user)
    await interaction.message.edit(embed=self.gerar_embed(interaction.client.user))
    await interaction.response.defer()

    if len(fila_pula_contra) >= 2:
      p1 = fila_pula_contra.pop(0)
      p2 = fila_pula_contra.pop(0)
      await interaction.message.edit(embed=self.gerar_embed(interaction.client.user))
      await criar_sala_partida(interaction.guild, p1, p2, "Pula Contra")

  @discord.ui.button(
      label="Sair da Fila",
      style=discord.ButtonStyle.danger,
      custom_id="btn_sair_geral",
  )
  async def callback_sair_geral(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    user = interaction.user
    saiu = False

    if user in fila_1v1:
      fila_1v1.remove(user)
      saiu = True

    if user in fila_pula_contra:
      fila_pula_contra.remove(user)
      saiu = True

    if saiu:
      await interaction.message.edit(embed=self.gerar_embed(interaction.client.user))
    
    await interaction.response.defer()

  @discord.ui.button(
      label="Ranking Geral",
      style=discord.ButtonStyle.secondary,
      custom_id="btn_ranking_geral",
  )
  async def callback_ranking(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    if not ranking_vitorias:
      await interaction.response.send_message(
          "O ranking ainda está vazio!", ephemeral=True
      )
      return

    ranking_ordenado = sorted(
        ranking_vitorias.items(), key=lambda x: x[1], reverse=True
    )
    texto = "🏆 **Ranking Geral de Vitórias**\n\n"
    for i, (uid, vitorias) in enumerate(ranking_ordenado, 1):
      texto += f"{i}º - <@{uid}>: {vitorias} vitórias\n"

    await interaction.response.send_message(texto, ephemeral=True)


class PainelPartidaView(discord.ui.View):

  def __init__(self, p1, p2, tipo_jogo):
    super().__init__(timeout=None)
    self.p1 = p1
    self.p2 = p2
    self.tipo_jogo = tipo_jogo
    self.confirmados = set()
    self.vencedor = None
    self.tipo_vitoria = None

  @discord.ui.button(
      label="Confirmar Partida",
      style=discord.ButtonStyle.blurple,
      custom_id="btn_confirma_partida",
  )
  async def confirmar_partida(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    if interaction.user not in [self.p1, self.p2]:
      await interaction.response.send_message(
          "Apenas os jogadores da partida podem confirmar.", ephemeral=True
      )
      return

    if interaction.user in self.confirmados:
      await interaction.response.send_message(
          "Você já confirmou a partida!", ephemeral=True
      )
      return

    self.confirmados.add(interaction.user)
    
    if len(self.confirmados) == 2:
      button.disabled = True
      for child in self.children:
        if isinstance(child, discord.ui.Button) and child.custom_id == "btn_confirma_partida":
          child.disabled = True

      await interaction.message.edit(view=self)
      await interaction.response.send_message("Partida confirmada por ambos!", ephemeral=True)

      cargo_admin = discord.utils.get(interaction.guild.roles, name="Administrador")
      mencao_admin = cargo_admin.mention if cargo_admin else "@administrador"
      
      await interaction.channel.send(f"Bora trabalhar seus vagabundos {mencao_admin}")
      
      self.add_item(AdminVitoriaSelect(self))
      self.add_item(FecharCanalButton(self))
      await interaction.message.edit(view=self)
    else:
      await interaction.response.send_message(
          f"Confirmação registrada! Falta apenas o outro jogador confirmar.", ephemeral=True
      )


class AdminVitoriaSelect(discord.ui.Select):

  def __init__(self, partida_view):
    self.partida_view = partida_view
    options = [
        discord.SelectOption(
            label=f"Vitória Normal ({partida_view.p1.name})",
            value=str(partida_view.p1.id),
        ),
        discord.SelectOption(
            label=f"Vitória Normal ({partida_view.p2.name})",
            value=str(partida_view.p2.id),
        ),
        discord.SelectOption(
            label=f"Vitória W.O. ({partida_view.p1.name})",
            value=f"wo_{partida_view.p1.id}",
        ),
        discord.SelectOption(
            label=f"Vitória W.O. ({partida_view.p2.name})",
            value=f"wo_{partida_view.p2.id}",
        ),
    ]
    super().__init__(
        placeholder="Definir Vencedor (Apenas Admin/Dono)",
        min_values=1,
        max_values=1,
        options=options,
    )

  async def callback(self, interaction: discord.Interaction):
    is_admin = (
        any(r.name in ["Dono", "Administrador"] for r in interaction.user.roles)
        or interaction.user.guild_permissions.administrator
    )
    if not is_admin and interaction.user != interaction.guild.owner:
      await interaction.response.send_message(
          "Apenas administradores ou o Dono podem definir o vencedor.",
          ephemeral=True,
      )
      return

    val = self.values[0]
    if val.startswith("wo_"):
      winner_id = int(val.split("_")[1])
      self.partida_view.tipo_vitoria = "W.O."
    else:
      winner_id = int(val)
      self.partida_view.tipo_vitoria = "Normal"

    self.partida_view.vencedor = interaction.guild.get_member(winner_id)

    ranking_vitorias[winner_id] = ranking_vitorias.get(winner_id, 0) + 1
    await atualizar_painel_ranking(interaction.guild)

    await interaction.response.send_message(
        f"🏆 Vencedor definido: **{self.partida_view.vencedor.name}** ("
        f"{self.partida_view.tipo_vitoria}). O canal já pode ser fechado.",
        ephemeral=False,
    )


class FecharCanalButton(discord.ui.Button):

  def __init__(self, partida_view):
    super().__init__(
        label="Fechar Canal", style=discord.ButtonStyle.danger, custom_id="btn_fechar_canal"
    )
    self.partida_view = partida_view

  async def callback(self, interaction: discord.Interaction):
    is_admin = (
        any(r.name in ["Dono", "Administrador"] for r in interaction.user.roles)
        or interaction.user.guild_permissions.administrator
    )
    if not is_admin and interaction.user != interaction.guild.owner:
      await interaction.response.send_message(
          "Apenas administradores ou o Dono podem fechar o canal.",
          ephemeral=True,
      )
      return

    log_channel = discord.utils.get(
        interaction.guild.text_channels, name=LOG_CHANNEL_NAME
    )
    if log_channel and self.partida_view.vencedor:
      agora = datetime.datetime.now().strftime("%d/%m/%Y às %H:%M")
      msg_log = (
          f"📋 **Registro de Partida Finalizada**\n"
          f"• **Tipo:** {self.partida_view.tipo_jogo}\n"
          f"• **Vencedor:** {self.partida_view.vencedor.mention}\n"
          f"• **Modo de Vitória:** {self.partida_view.tipo_vitoria}\n"
          f"• **Data/Horário:** {agora}"
      )
      await log_channel.send(msg_log)

    await interaction.response.send_message(
        "Fechando canal em 3 segundos...", ephemeral=True
    )
    await asyncio.sleep(3)
    await interaction.channel.delete()


async def criar_sala_partida(guild, p1, p2, tipo_jogo):
  overwrites = {
      guild.default_role: discord.PermissionOverwrite(view_channel=False),
      p1: discord.PermissionOverwrite(view_channel=True, send_messages=True),
      p2: discord.PermissionOverwrite(view_channel=True, send_messages=True),
      guild.me: discord.PermissionOverwrite(
          view_channel=True, send_messages=True, manage_channels=True
      ),
  }

  for role in guild.roles:
    if role.name in ["Dono", "Administrador"]:
      overwrites[role] = discord.PermissionOverwrite(
          view_channel=True, send_messages=True
      )

  categoria = discord.utils.get(
      guild.categories, name="[🎮] 1V1 & PULA CONTRA"
  )
  nome_canal = (
      f"partida-{p1.name[:4]}-{p2.name[:4]}".lower().replace(" ", "-")
  )

  canal = await guild.create_text_channel(
      name=nome_canal, category=categoria, overwrites=overwrites
  )

  view = PainelPartidaView(p1, p2, tipo_jogo)
  txt = (
      f"🎮 **Nova Partida de {tipo_jogo} criada!**\n"
      f"Jogadores: {p1.mention} vs {p2.mention}\n\n"
      "**Regra básica:**\n"
      "Full Ump & Xm8 - Primeiro round Desert\n\n"
      "Clique no botão abaixo para confirmar a partida:"
  )
  await canal.send(txt, view=view)


async def atualizar_painel_ranking(guild):
  canal_ranking = discord.utils.get(
      guild.text_channels, name=RANKING_CHANNEL_NAME
  )
  if not canal_ranking:
    return

  async for message in canal_ranking.history(limit=10):
    await message.delete()

  ranking_ordenado = sorted(
      ranking_vitorias.items(), key=lambda x: x[1], reverse=True
  )[:3]

  texto = "🏆 **PAINEL DE RANKING - TOP 3** 🏆\n\n"
  if not ranking_ordenado:
    texto += "Ainda não há partidas finalizadas."
  else:
    medalhas = ["🥇", "🥈", "🥉"]
    for i, (uid, vitorias) in enumerate(ranking_ordenado):
      texto += f"{medalhas[i]} <@{uid}> — **{vitorias} vitórias**\n"

  await canal_ranking.send(texto)


@bot.command()
@commands.has_permissions(administrator=True)
async def add(ctx, membro: discord.Member, quantidade: int):
  ranking_vitorias[membro.id] = ranking_vitorias.get(membro.id, 0) + quantidade
  await atualizar_painel_ranking(ctx.guild)
  await ctx.send(f"Adicionadas {quantidade} vitória(s) para {membro.mention}!")


@bot.command()
@commands.has_permissions(administrator=True)
async def tirar(ctx, membro: discord.Member, quantidade: int):
  atual = ranking_vitorias.get(membro.id, 0)
  novo_valor = max(0, atual - quantidade)
  ranking_vitorias[membro.id] = novo_valor
  await atualizar_painel_ranking(ctx.guild)
  await ctx.send(f"Removidas {quantidade} vitória(s) de {membro.mention}!")


@bot.event
async def on_ready():
  print(f"Bot conectado como {bot.user}!")
  bot.add_view(FilaView())


@bot.command()
@commands.has_permissions(administrator=True)
async def painel(ctx):
  view = FilaView()
  embed = view.gerar_embed(ctx.bot.user)
  await ctx.send(embed=embed, view=view)
  await ctx.message.delete()


if __name__ == "__main__":
  keep_alive()  # Inicia o servidor web em segundo plano
  bot.run(os.getenv("DISCORD_TOKEN"))

