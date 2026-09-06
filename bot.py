import asyncio
import datetime
import os
import random
import discord
from discord.ext import commands

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

  @discord.ui.button(
      label="Entrar na Fila 1v1",
      style=discord.ButtonStyle.primary,
      custom_id="btn_1v1",
  )
  async def callback_1v1(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    user = interaction.user
    if user in fila_1v1:
      await interaction.response.send_message(
          "Você já está na fila 1v1!", ephemeral=True
      )
      return

    if user in fila_pula_contra:
      fila_pula_contra.remove(user)

    fila_1v1.append(user)
    await interaction.response.send_message(
        f"{user.mention} entrou na fila **1v1**! ({len(fila_1v1)}/2)",
        ephemeral=True,
    )

    if len(fila_1v1) >= 2:
      p1 = fila_1v1.pop(0)
      p2 = fila_1v1.pop(0)
      await criar_sala_partida(
          interaction.guild, p1, p2, "1v1", "Full ump & Xm8 - Primeira só desert"
      )

  @discord.ui.button(
      label="Entrar na Fila Pula Contra",
      style=discord.ButtonStyle.success,
      custom_id="btn_pula_contra",
  )
  async def callback_pula_contra(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    user = interaction.user
    if user in fila_pula_contra:
      await interaction.response.send_message(
          "Você já está na fila Pula Contra!", ephemeral=True
      )
      return

    if user in fila_1v1:
      fila_1v1.remove(user)

    fila_pula_contra.append(user)
    await interaction.response.send_message(
        f"{user.mention} entrou na fila **Pula Contra**! ({len(fila_pula_contra)}/2)",
        ephemeral=True,
    )

    if len(fila_pula_contra) >= 2:
      p1 = fila_pula_contra.pop(0)
      p2 = fila_pula_contra.pop(0)
      await criar_sala_partida(
          interaction.guild,
          p1,
          p2,
          "Pula Contra",
          "Full ump & Xm8 - Primeira só desert",
      )

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

  def __init__(self, admin, p1, p2, tipo_jogo):
    super().__init__(timeout=None)
    self.admin = admin
    self.p1 = p1
    self.p2 = p2
    self.tipo_jogo = tipo_jogo
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

    button.disabled = True
    await interaction.response.edit_message(
        content=(
            "✅ **Partida Confirmada!** Boa sorte aos jogadores. O admin"
            f" {self.admin.mention} está no comando."
        ),
        view=self,
    )

    self.add_item(AdminVitoriaSelect(self))
    self.add_item(FecharCanalButton(self))
    await interaction.message.edit(view=self)


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
    if (
        interaction.user != self.partida_view.admin
        and not is_admin
        and interaction.user != interaction.guild.owner
    ):
      await interaction.response.send_message(
          "Apenas o Administrador sorteado ou o Dono podem definir o vencedor.",
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
    if (
        interaction.user != self.partida_view.admin
        and not is_admin
        and interaction.user != interaction.guild.owner
    ):
      await interaction.response.send_message(
          "Apenas o Admin da partida ou o Dono podem fechar o canal.",
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
          f"• **Admin Responsável:** {self.partida_view.admin.mention}\n"
          f"• **Data/Horário:** {agora}"
      )
      await log_channel.send(msg_log)

    await interaction.response.send_message(
        "Fechando canal em 3 segundos...", ephemeral=True
    )
    await asyncio.sleep(3)
    await interaction.channel.delete()


async def criar_sala_partida(guild, p1, p2, tipo_jogo, regras):
  admins = [
      m
      for m in guild.members
      if any(r.name == "Administrador" for r in m.roles)
      and m.status != discord.Status.offline
  ]
  if not admins:
    admins = [
        m for m in guild.members if any(r.name == "Administrador" for r in m.roles)
    ]

  admin_sorteado = random.choice(admins) if admins else guild.owner

  overwrites = {
      guild.default_role: discord.PermissionOverwrite(view_channel=False),
      p1: discord.PermissionOverwrite(view_channel=True, send_messages=True),
      p2: discord.PermissionOverwrite(view_channel=True, send_messages=True),
      admin_sorteado: discord.PermissionOverwrite(
          view_channel=True, send_messages=True
      ),
      guild.me: discord.PermissionOverwrite(
          view_channel=True, send_messages=True, manage_channels=True
      ),
  }

  for role in guild.roles:
    if role.name == "Dono":
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

  view = PainelPartidaView(admin_sorteado, p1, p2, tipo_jogo)
  txt = (
      f"🎮 **Nova Partida de {tipo_jogo} criada!**\n"
      f"Jogadores: {p1.mention} vs {p2.mention}\n"
      f"Admin Responsável: {admin_sorteado.mention}\n\n"
      "**Regras locais:**\n"
      f"{regras}\n"
      "Sem jota Go macaquitos?\n\n"
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


@bot.event
async def on_ready():
  print(f"Bot conectado como {bot.user}!")
  bot.add_view(FilaView())


@bot.command()
@commands.has_permissions(administrator=True)
async def painel(ctx):
  view = FilaView()
  await ctx.send(
      "⚔️ **SISTEMA DE PARTIDAS 1V1 E PULA CONTRA** ⚔️\nClique no botão"
      " correspondente para entrar na fila:",
      view=view,
  )
  await ctx.message.delete()


# Puxa o token de forma segura da hospedagem
bot.run(os.getenv("DISCORD_TOKEN"))

