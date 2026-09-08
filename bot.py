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
fila_duplas_inscritos = []  # Lista dos capitães/representantes inscritos no painel 2
ranking_vitorias = {}
ranking_derrotas = {}
admins_em_servico = set()  # Guarda os IDs dos administradores em serviço

LOG_CHANNEL_NAME = "logs-partidas"
painel_mensagem_ref = None  # Guarda a referência da mensagem do painel principal
painel2_mensagem_ref = None # Guarda a referência da mensagem do painel 2 (duplas)


class FilaView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  def gerar_embed(self, bot_user=None):
    embed = discord.Embed(
        title="🎮 Sistema de Partidas",
        description="Clique nos botões abaixo para entrar ou sair das filas.",
        color=discord.Color.blurple(),
    )

    # --- TOP 3 VITÓRIAS (Esquerda) ---
    top_vitorias = sorted(ranking_vitorias.items(), key=lambda x: x[1], reverse=True)[:3]
    texto_vit = ""
    if not top_vitorias:
      texto_vit = "Nenhum ainda."
    else:
      medalhas = ["🥇", "🥈", "🥉"]
      for i, (uid, vit) in enumerate(top_vitorias):
        texto_vit += f"{medalhas[i]} <@{uid}>: **{vit}V**\n"

    embed.add_field(name="🏆 Top 3 Vitórias", value=texto_vit, inline=True)

    # --- TOP 3 DERROTAS (Direita) ---
    top_derrotas = sorted(ranking_derrotas.items(), key=lambda x: x[1], reverse=True)[:3]
    texto_der = ""
    if not top_derrotas:
      texto_der = "Nenhum ainda."
    else:
      medalhas = ["🥇", "🥈", "🥉"]
      for i, (uid, der) in enumerate(top_derrotas):
        texto_der += f"{medalhas[i]} <@{uid}>: **{der}D**\n"

    embed.add_field(name="💀 Top 3 Derrotas", value=texto_der, inline=True)

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    # --- FILAS ---
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
    await atualizar_painel_principal(interaction.client)
    await interaction.response.defer()

    if len(fila_1v1) >= 2:
      p1 = fila_1v1.pop(0)
      p2 = fila_1v1.pop(0)
      await atualizar_painel_principal(interaction.client)
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
    await atualizar_painel_principal(interaction.client)
    await interaction.response.defer()

    if len(fila_pula_contra) >= 2:
      p1 = fila_pula_contra.pop(0)
      p2 = fila_pula_contra.pop(0)
      await atualizar_painel_principal(interaction.client)
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
      await atualizar_painel_principal(interaction.client)
    
    await interaction.response.defer()

  @discord.ui.button(
      label="Ranking Completo",
      style=discord.ButtonStyle.secondary,
      custom_id="btn_ranking_geral",
  )
  async def callback_ranking(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    if not ranking_vitorias and not ranking_derrotas:
      await interaction.response.send_message(
          "O ranking ainda está vazio!", ephemeral=True
      )
      return

    todos_membros = set(list(ranking_vitorias.keys()) + list(ranking_derrotas.keys()))
    texto = "🏆 **Ranking Geral Completo**\n\n"
    for uid in todos_membros:
      v = ranking_vitorias.get(uid, 0)
      d = ranking_derrotas.get(uid, 0)
      texto += f"• <@{uid}> — **{v}** Vitórias | **{d}** Derrotas\n"

    await interaction.response.send_message(texto, ephemeral=True)


class FilaDuplaView(discord.ui.View):
  """Painel 2: Inscrição de Capitães para o Evento de Duplas / Sorteio"""
  def __init__(self):
    super().__init__(timeout=None)

  def gerar_embed_duplas(self):
    embed = discord.Embed(
        title="🏆 Inscrição - Torneio de Duplas (Capitães)",
        description=(
            "Clique nos botões abaixo para gerenciar sua inscrição.\n"
            "⚠️ **Apenas o capitão/representante** deve se inscrever.\n\n"
            "**Capitães Inscritos:**"
        ),
        color=discord.Color.dark_gold(),
    )

    if not fila_duplas_inscritos:
      texto_inscritos = "Nenhum capitão inscrito ainda."
    else:
      texto_inscritos = "\n".join([f"{i+1}. {m.mention}" for i, m in enumerate(fila_duplas_inscritos)])

    embed.add_field(name=f"Total Inscritos: ({len(fila_duplas_inscritos)})", value=texto_inscritos, inline=False)
    return embed

  @discord.ui.button(
      label="Entrar na Fila",
      style=discord.ButtonStyle.primary,
      custom_id="btn_entrar_fila_dupla",
  )
  async def entrar_fila_dupla(self, interaction: discord.Interaction, button: discord.ui.Button):
    user = interaction.user
    if user in fila_duplas_inscritos:
      await interaction.response.send_message("Você já está inscrito na fila de duplas!", ephemeral=True)
      return

    fila_duplas_inscritos.append(user)
    await atualizar_painel_duplas(interaction.client)
    await interaction.response.send_message("Inscrição realizada com sucesso! Seu @ foi adicionado ao painel.", ephemeral=True)

  @discord.ui.button(
      label="Sair da Fila",
      style=discord.ButtonStyle.danger,
      custom_id="btn_sair_fila_dupla",
  )
  async def sair_fila_dupla(self, interaction: discord.Interaction, button: discord.ui.Button):
    user = interaction.user
    if user not in fila_duplas_inscritos:
      await interaction.response.send_message("Você não está inscrito nesta fila.", ephemeral=True)
      return

    fila_duplas_inscritos.remove(user)
    await atualizar_painel_duplas(interaction.client)
    await interaction.response.send_message("Você saiu da lista de capitães inscritos.", ephemeral=True)

  @discord.ui.button(
      label="🎲 Realizar Sorteio de Confrontos",
      style=discord.ButtonStyle.success,
      custom_id="btn_sorteio_duplas",
  )
  async def sortear_confrontos(self, interaction: discord.Interaction, button: discord.ui.Button):
    is_dono = (
        any(r.name == "Dono" for r in interaction.user.roles)
        or interaction.user == interaction.guild.owner
    )
    if not is_dono:
      await interaction.response.send_message("Apenas o **Dono** pode realizar o sorteio do torneio!", ephemeral=True)
      return

    if len(fila_duplas_inscritos) < 2:
      await interaction.response.send_message("É preciso ter pelo menos 2 capitães inscritos para realizar o sorteio!", ephemeral=True)
      return

    capitaes = list(fila_duplas_inscritos)
    random.shuffle(capitaes)

    confrontos_texto = "🎲 **Sorteio de Confrontos - Capitão vs Capitão** 🎲\n\n"
    
    for i in range(0, len(capitaes) - 1, 2):
      c1 = capitaes[i]
      c2 = capitaes[i+1]
      confrontos_texto += f"⚔️ {c1.mention} **VS** {c2.mention}\n"

    if len(capitaes) % 2 != 0:
      sobra = capitaes[-1]
      confrontos_texto += f"\n🔄 {sobra.mention} avançou com **Bye** (aguarda a próxima fase ou adversário).\n"

    await interaction.channel.send(confrontos_texto)
    await interaction.response.send_message("Sorteio realizado com sucesso no chat!", ephemeral=True)


# --- SISTEMA DE TICKETS ---

class TicketSelectView(discord.ui.View):
  """Painel principal do Ticket (Mensagem fixa enviada por !painelticket)"""
  def __init__(self):
    super().__init__(timeout=None)
    self.add_item(TicketSelectDropdown())

class TicketSelectDropdown(discord.ui.Select):
  def __init__(self):
    options = [
        discord.SelectOption(
            label="Abrir Chamado",
            description="Clique aqui para iniciar um atendimento.",
            emoji="🎫",
            value="abrir_chamado"
        )
    ]
    super().__init__(
        placeholder="Selecione uma função...",
        min_values=1,
        max_values=1,
        options=options,
        custom_id="ticket_dropdown_menu"
    )

  async def callback(self, interaction: discord.Interaction):
    if self.values[0] == "abrir_chamado":
      await criar_sala_ticket(interaction)


class TicketControlView(discord.ui.View):
  """Painel interno dentro da sala privada do Ticket"""
  def __init__(self, criador_id, horario_abertura):
    super().__init__(timeout=None)
    self.criador_id = criador_id
    self.horario_abertura = horario_abertura
    self.assumido_por = None

  @discord.ui.button(
      label="Assumir Chamado",
      style=discord.ButtonStyle.success,
      custom_id="btn_assumir_chamado"
  )
  async def assumir_chamado(self, interaction: discord.Interaction, button: discord.ui.Button):
    is_admin = (
        any(r.name in ["Dono", "Administrador"] for r in interaction.user.roles)
        or interaction.user.guild_permissions.administrator
        or interaction.user == interaction.guild.owner
    )
    if not is_admin:
      await interaction.response.send_message("Apenas administradores ou o Dono podem assumir o chamado.", ephemeral=True)
      return

    if self.assumido_por:
      await interaction.response.send_message(f"Este chamado já foi assumido por <@{self.assumido_por}>.", ephemeral=True)
      return

    self.assumido_por = interaction.user.id
    button.disabled = True
    await interaction.message.edit(view=self)

    # Oculta o canal para todos os cargos normais/staff, deixando visível apenas para o Dono e o criador
    guild = interaction.guild
    canal = interaction.channel
    criador = guild.get_member(self.criador_id)

    # Remove permissão do @everyone
    await canal.set_permissions(guild.default_role, view_channel=False)

    # Restaura permissão exata para o criador e para quem assumiu
    if criador:
      await canal.set_permissions(criador, view_channel=True, send_messages=True)
    await canal.set_permissions(interaction.user, view_channel=True, send_messages=True)

    # Garante que o Dono do servidor também continue vendo se houver
    if guild.owner:
      await canal.set_permissions(guild.owner, view_channel=True, send_messages=True)

    await interaction.response.send_message(
        f"🛡️ Chamado assumido por {interaction.user.mention}! O canal foi ocultado para os demais administradores."
    )

  @discord.ui.button(
      label="Fechar Chamado",
      style=discord.ButtonStyle.danger,
      custom_id="btn_fechar_chamado"
  )
  async def fechar_chamado(self, interaction: discord.Interaction, button: discord.ui.Button):
    is_admin = (
        any(r.name in ["Dono", "Administrador"] for r in interaction.user.roles)
        or interaction.user.guild_permissions.administrator
        or interaction.user == interaction.guild.owner
    )
    if not is_admin:
      await interaction.response.send_message("Apenas administradores ou o Dono podem fechar o chamado.", ephemeral=True)
      return

    guild = interaction.guild
    canal = interaction.channel
    criador = guild.get_member(self.criador_id)
    assumidor = guild.get_member(self.assumido_por) if self.assumido_por else interaction.user

    horario_fim = datetime.datetime.now().strftime("%d/%m/%Y às %H:%M")
    log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)

    if log_channel:
      msg_log = (
          f"📋 **Registro de Chamado / Ticket Fechado**\n"
          f"• **Criador do Chamado:** {criador.mention if criador else f'<@{self.criador_id}>'}\n"
          f"• **Assumido por:** {assumidor.mention if assumidor else 'Ninguém assumiu'}\n"
          f"• **Fechado por:** {interaction.user.mention}\n"
          f"• **Data de Abertura:** {self.horario_abertura}\n"
          f"• **Data de Fechamento:** {horario_fim}"
      )
      await log_channel.send(msg_log)

    await interaction.response.send_message("Fechando e apagando o canal do ticket...", ephemeral=True)
    await asyncio.sleep(2)
    await canal.delete()


async def criar_sala_ticket(interaction: discord.Interaction):
  guild = interaction.guild
  user = interaction.user

  overwrites = {
      guild.default_role: discord.PermissionOverwrite(view_channel=False),
      user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
      guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
  }

  # Permite que todos os administradores vejam inicialmente antes de alguém assumir
  cargo_admin = discord.utils.get(guild.roles, name="Administrador")
  if cargo_admin:
    overwrites[cargo_admin] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
  if guild.owner:
    overwrites[guild.owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

  categoria = discord.utils.get(guild.categories, name="[🎫] TICKETS")
  if not categoria:
    categoria = await guild.create_category("[🎫] TICKETS")

  nome_canal = f"ticket-{user.name[:10]}".lower().replace(" ", "-")
  canal = await guild.create_text_channel(name=nome_canal, category=categoria, overwrites=overwrites)

  horario_abertura = datetime.datetime.now().strftime("%d/%m/%Y às %H:%M")
  view = TicketControlView(user.id, horario_abertura)

  embed = discord.Embed(
      title="Atendimento de Chamado",
      description=f"Olá {user.mention}, um atendente/administrador irá te atender em breve.\nUtilize os botões abaixo para gerenciar este chamado.",
      color=discord.Color.green()
  )

  await canal.send(f"{user.mention} seu ticket foi aberto aqui!", embed=embed, view=view)
  await interaction.response.send_message(f"Seu canal de atendimento foi criado: {canal.mention}", ephemeral=True)


class ServicoAdminView(discord.ui.View):
  def __init__(self):
    super().__init__(timeout=None)

  def gerar_embed_servico(self):
    embed = discord.Embed(
        title="Painel de Atendimento - Staff",
        description="Clique abaixo para entrar ou sair de serviço como mediador de partidas.",
        color=discord.Color.gold(),
    )
    
    if not admins_em_servico:
      texto_staff = "Nenhum administrador em serviço no momento."
    else:
      texto_staff = "\n".join([f"• <@{uid}>" for uid in admins_em_servico])

    embed.add_field(name="🛡️ Admins em Serviço:", value=texto_staff, inline=False)
    return embed

  @discord.ui.button(
      label="Entrar em Serviço",
      style=discord.ButtonStyle.success,
      custom_id="btn_entrar_servico",
  )
  async def entrar_servico(self, interaction: discord.Interaction, button: discord.ui.Button):
    is_admin = (
        any(r.name in ["Dono", "Administrador"] for r in interaction.user.roles)
        or interaction.user.guild_permissions.administrator
    )
    if not is_admin and interaction.user != interaction.guild.owner:
      await interaction.response.send_message("Apenas administradores podem entrar em serviço.", ephemeral=True)
      return

    if interaction.user.id in admins_em_servico:
      await interaction.response.send_message("Você já está em serviço!", ephemeral=True)
      return

    admins_em_servico.add(interaction.user.id)
    await interaction.message.edit(embed=self.gerar_embed_servico())
    await interaction.response.send_message("Você entrou em serviço com sucesso!", ephemeral=True)

  @discord.ui.button(
      label="Sair de Serviço",
      style=discord.ButtonStyle.danger,
      custom_id="btn_sair_servico",
  )
  async def sair_servico(self, interaction: discord.Interaction, button: discord.ui.Button):
    if interaction.user.id not in admins_em_servico:
      await interaction.response.send_message("Você não está em serviço.", ephemeral=True)
      return

    admins_em_servico.remove(interaction.user.id)
    await interaction.message.edit(embed=self.gerar_embed_servico())
    await interaction.response.send_message("Você saiu de serviço.", ephemeral=True)


class PainelPartidaView(discord.ui.View):

  def __init__(self, p1, p2, tipo_jogo, mediador, horario_inicio):
    super().__init__(timeout=None)
    self.p1 = p1
    self.p2 = p2
    self.tipo_jogo = tipo_jogo
    self.mediador = mediador
    self.horario_inicio = horario_inicio
    self.confirmados = set()
    self.vencedor = None
    self.perdedor = None
    self.tipo_vitoria = None
    self.finalizador = None

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
      for child in self.children:
        if isinstance(child, discord.ui.Button) and child.custom_id == "btn_confirma_partida":
          child.disabled = True

      await interaction.message.edit(view=self)
      await interaction.response.send_message("Partida confirmada por ambos!", ephemeral=True)

      mencao_med = self.mediador.mention if self.mediador else "@administrador"
      await interaction.channel.send(f"Bora trabalhar seu vagabundo {mencao_med}")
      
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
        placeholder="Definir Vencedor (Apenas Mediador/Dono)",
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
    self.partida_view.perdedor = self.partida_view.p2 if self.partida_view.vencedor == self.partida_view.p1 else self.partida_view.p1
    self.partida_view.finalizador = interaction.user

    ranking_vitorias[self.partida_view.vencedor.id] = ranking_vitorias.get(self.partida_view.vencedor.id, 0) + 1
    ranking_derrotas[self.partida_view.perdedor.id] = ranking_derrotas.get(self.partida_view.perdedor.id, 0) + 1

    await atualizar_painel_principal(interaction.client)

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
      horario_fim = datetime.datetime.now().strftime("%d/%m/%Y às %H:%M")
      mediador_mencao = self.partida_view.mediador.mention if self.partida_view.mediador else "Nenhum"
      finalizador_mencao = self.partida_view.finalizador.mention if self.partida_view.finalizador else "Desconhecido"

      msg_log = (
          f"📋 **Registro de Partida Finalizada**\n"
          f"• **Tipo de Jogo:** {self.partida_view.tipo_jogo}\n"
          f"• **Jogadores:** {self.partida_view.p1.mention} vs {self.partida_view.p2.mention}\n"
          f"• **Vencedor:** {self.partida_view.vencedor.mention} ({self.partida_view.tipo_vitoria})\n"
          f"• **Derrotado:** {self.partida_view.perdedor.mention}\n"
          f"• **Mediador Responsável:** {mediador_mencao}\n"
          f"• **Finalizado por:** {finalizador_mencao}\n"
          f"• **Horário de Início:** {self.partida_view.horario_inicio}\n"
          f"• **Horário de Término:** {horario_fim}"
      )
      await log_channel.send(msg_log)

    await interaction.response.send_message(
        "Fechando canal em 3 segundos...", ephemeral=True
    )
    await asyncio.sleep(3)
    await interaction.channel.delete()


async def criar_sala_partida(guild, p1, p2, tipo_jogo):
  mediador = None
  if admins_em_servico:
    admin_id_sorteado = random.choice(list(admins_em_servico))
    mediador = guild.get_member(admin_id_sorteado)

  overwrites = {
      guild.default_role: discord.PermissionOverwrite(view_channel=False),
      p1: discord.PermissionOverwrite(view_channel=True, send_messages=True),
      p2: discord.PermissionOverwrite(view_channel=True, send_messages=True),
      guild.me: discord.PermissionOverwrite(
          view_channel=True, send_messages=True, manage_channels=True
      ),
  }

  if mediador:
    overwrites[mediador] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
  else:
    cargo_admin = discord.utils.get(guild.roles, name="Administrador")
    if cargo_admin:
      overwrites[cargo_admin] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

  categoria = discord.utils.get(
      guild.categories, name="[🎮] 1V1 & PULA CONTRA"
  )
  nome_canal = (
      f"partida-{p1.name[:4]}-{p2.name[:4]}".lower().replace(" ", "-")
  )

  canal = await guild.create_text_channel(
      name=nome_canal, category=categoria, overwrites=overwrites
  )

  horario_inicio = datetime.datetime.now().strftime("%d/%m/%Y às %H:%M")
  view = PainelPartidaView(p1, p2, tipo_jogo, mediador, horario_inicio)
  
  mencao_mediador_txt = mediador.mention if mediador else "Nenhum (Nenhum admin em serviço)"
  txt = (
      f"🎮 **Nova Partida de {tipo_jogo} criada!**\n"
      f"Jogadores: {p1.mention} vs {p2.mention}\n"
      f"🛡️ **Mediador Sorteado:** {mencao_mediador_txt}\n\n"
      "**Regra básica:**\n"
      "Full Ump & Xm8 - Primeiro round Desert\n\n"
      "Clique no botão abaixo para confirmar a partida:"
  )
  await canal.send(txt, view=view)


async def atualizar_painel_principal(client):
  global painel_mensagem_ref
  if painel_mensagem_ref:
    try:
      view = FilaView()
      embed = view.gerar_embed(client.user)
      await painel_mensagem_ref.edit(embed=embed, view=view)
    except Exception:
      pass


async def atualizar_painel_duplas(client):
  global painel2_mensagem_ref
  if painel2_mensagem_ref:
    try:
      view = FilaDuplaView()
      embed = view.gerar_embed_duplas()
      await painel2_mensagem_ref.edit(embed=embed, view=view)
    except Exception:
      pass


# --- COMANDOS ADMINISTRATIVOS ---

@bot.command()
@commands.has_permissions(administrator=True)
async def add(ctx, membro: discord.Member, quantidade: int):
  ranking_vitorias[membro.id] = ranking_vitorias.get(membro.id, 0) + quantidade
  await atualizar_painel_principal(ctx.bot)
  await ctx.send(f"Adicionadas {quantidade} vitória(s) para {membro.mention}!")


@bot.command()
@commands.has_permissions(administrator=True)
async def tirar(ctx, membro: discord.Member, quantidade: int):
  atual = ranking_vitorias.get(membro.id, 0)
  novo_valor = max(0, atual - quantidade)
  ranking_vitorias[membro.id] = novo_valor
  await atualizar_painel_principal(ctx.bot)
  await ctx.send(f"Removidas {quantidade} vitória(s) de {membro.mention}!")


@bot.command()
@commands.has_permissions(administrator=True)
async def adddupla(ctx, membro: discord.Member):
  if membro in fila_duplas_inscritos:
    await ctx.send(f"{membro.mention} já está na lista do painel de duplas!")
    return
  
  fila_duplas_inscritos.append(membro)
  await atualizar_painel_duplas(ctx.bot)
  await ctx.send(f"Capitão {membro.mention} adicionado à força na fila de duplas!")


@bot.command()
@commands.has_permissions(administrator=True)
async def tirardupla(ctx, membro: discord.Member):
  if membro not in fila_duplas_inscritos:
    await ctx.send(f"{membro.mention} não está na lista do painel de duplas.")
    return
  
  fila_duplas_inscritos.remove(membro)
  await atualizar_painel_duplas(ctx.bot)
  await ctx.send(f"Capitão {membro.mention} removido da fila de duplas!")


@bot.event
async def on_ready():
  print(f"Bot conectado como {bot.user}!")
  bot.add_view(FilaView())
  bot.add_view(FilaDuplaView())
  bot.add_view(ServicoAdminView())
  bot.add_view(TicketSelectView())


@bot.command()
@commands.has_permissions(administrator=True)
async def painel(ctx):
  global painel_mensagem_ref
  view = FilaView()
  embed = view.gerar_embed(ctx.bot.user)
  painel_mensagem_ref = await ctx.send(embed=embed, view=view)
  await ctx.message.delete()


@bot.command()
@commands.has_permissions(administrator=True)
async def painel2(ctx):
  global painel2_mensagem_ref
  view = FilaDuplaView()
  embed = view.gerar_embed_duplas()
  painel2_mensagem_ref = await ctx.send(embed=embed, view=view)
  await ctx.message.delete()


@bot.command()
@commands.has_permissions(administrator=True)
async def painelticket(ctx):
  view = TicketSelectView()
  embed = discord.Embed(
      title="Dz resolve teu B.O 🫡",
      description="Selecione uma das opções abaixo para abrir um ticket. Um de nossos atendentes irá te ajudar em breve!",
      color=discord.Color.dark_purple()
  )
  await ctx.send(embed=embed, view=view)
  await ctx.message.delete()


@bot.command()
@commands.has_permissions(administrator=True)
async def painel_staff(ctx):
  view = ServicoAdminView()
  embed = view.gerar_embed_servico()
  await ctx.send(embed=embed, view=view)
  await ctx.message.delete()


if __name__ == "__main__":
  keep_alive()
  bot.run(os.getenv("DISCORD_TOKEN"))

