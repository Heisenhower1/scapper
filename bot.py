import os
import asyncio
import logging
import json
import re
from datetime import datetime
from telethon import TelegramClient, events, errors, types

# Configuración de logging:
DEBUG = os.environ.get("DEBUG", "False").lower() in ("true", "1", "t")
LOG_LEVEL = logging.DEBUG if DEBUG else logging.WARNING

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=LOG_LEVEL
)
logger = logging.getLogger(__name__)

class TelegramScraperBot:
    def __init__(self):
        # Credenciales y configuración
        self.api_id = 28133985
        self.api_hash = "89727e35e2c9274affc69c31804059c1"
        self.bot_token = "7545673746:AAGuKQ1Qe4zHgpG3RvaFyEmq1ZTuBt8goLk"
        
        # Datos de dueño: solo tú puedes ejecutar comandos
        self.owner_id = 1450818544
        self.owner_username = "@zaza_Bernocchi"
        # Destino fijo para enviar los mensajes (chat_id como entero)
        self.chat_id = -1001756393608

        # Nombre de sesión para el cliente de usuario (asegúrate de tener el archivo .session)
        self.session_name = "telegram_scraper_session.session"
        
        # Clientes: uno para scraping (usuario) y otro para recibir comandos (bot)
        self.user_client = TelegramClient(
            self.session_name,
            self.api_id,
            self.api_hash,
            connection_retries=15,
            retry_delay=2,
            timeout=30,
            auto_reconnect=True
        )
        self.bot_client = TelegramClient("bot_session", self.api_id, self.api_hash)
        
        self.entity = None
        self.grupo_actual = None
        self.listener_active = False
        self.message_count = 0
        self.start_time = None
        self.grupos_previos = []

    async def start_clients(self):
        # Inicia ambos clientes: usuario y bot
        await self.user_client.start()
        await self.bot_client.start(bot_token=self.bot_token)
        self.start_time = datetime.now()
        logger.info("Clientes iniciados correctamente")
    
    # ----------------- Funcionalidad de scraping -----------------
    
    async def conectar_grupo(self, grupo_input):
        grupo_input = grupo_input.strip()
        try:
            for intento in range(3):
                try:
                    self.entity = await self.user_client.get_entity(grupo_input)
                    break
                except errors.FloodWaitError as e:
                    await asyncio.sleep(e.seconds + 1)
                except errors.UsernameInvalidError:
                    return "❌ <b>Nombre de usuario inválido.</b>"
                except Exception as e:
                    if intento < 2:
                        await asyncio.sleep(2)
            if not self.entity:
                return "❌ <b>No se pudo acceder al grupo tras varios intentos.</b>"
            if isinstance(self.entity, (types.Channel, types.Chat)):
                self.grupo_actual = getattr(self.entity, 'title', 'Grupo desconocido')
                info_grupo = {
                    "id": grupo_input,
                    "nombre": self.grupo_actual,
                    "accedido": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                if not any(g.get("id") == grupo_input for g in self.grupos_previos):
                    self.grupos_previos.append(info_grupo)
                    if len(self.grupos_previos) > 10:
                        self.grupos_previos.pop(0)
                return f"✅ <b>Accediendo al grupo:</b> {self.grupo_actual}"
            else:
                return "❌ <b>La entidad no es un grupo o canal válido.</b>"
        except errors.ChatAdminRequiredError:
            return "❌ <b>Se requieren permisos de administrador para este grupo.</b>"
        except errors.ChannelPrivateError:
            return "❌ <b>Este es un grupo privado. Debes ser miembro para acceder.</b>"
        except Exception as e:
            logger.error(f"Error al conectar con el grupo: {e}")
            return f"❌ <b>Error:</b> {e}"
    
    async def capturar_mensajes_antiguos(self, limite=100):
        if not self.entity:
            return "❌ <b>No hay grupo seleccionado.</b>"
        contador = 0
        mensajes_capturados = []
        try:
            async for mensaje in self.user_client.iter_messages(self.entity, limit=limite, reverse=True):
                if mensaje and mensaje.text:
                    mensajes_capturados.append(f"[{mensaje.sender_id}] {mensaje.text}")
                    contador += 1
                    self.message_count += 1
                    if contador % 100 == 0:
                        await asyncio.sleep(0.5)
            # Reenvía los mensajes capturados al chat destino (self.chat_id)
            for msg in mensajes_capturados:
                await self.bot_client.send_message(self.chat_id, msg)
            return f"✅ <b>Se capturaron y enviaron {contador} mensajes.</b>"
        except errors.FloodWaitError as e:
            await asyncio.sleep(e.seconds + 1)
            return f"⏳ <b>FloodWait:</b> {e.seconds} segundos."
        except Exception as e:
            logger.error(f"Error al capturar mensajes: {e}")
            return f"❌ <b>Error:</b> {e}"
    
    async def escuchar_mensajes_nuevos(self):
        if not self.entity:
            return "❌ <b>No hay grupo seleccionado.</b>"
        await self.desactivar_listener()  # Asegura que no haya otro listener activo

        async def handler(event):
            try:
                mensaje = event.message
                if mensaje and mensaje.text:
                    texto_limpio = re.sub(r'\[\[.*?\]\(https?:\/\/.*?\)\]', '', mensaje.text)
                    texto_limpio = re.sub(r'[`\*\[\]]', '', texto_limpio)
                    texto_limpio = re.sub(r'\n{2,}', '\n', texto_limpio).strip()
                    texto_final = f"[{mensaje.sender_id}] {texto_limpio}"
                    await self.bot_client.send_message(self.chat_id, texto_final)
                    logger.info(f"Mensaje reenviado: {texto_final}")
            except Exception as e:
                logger.error(f"Error en handler: {e}")

        self._event_handler = handler
        self.user_client.add_event_handler(handler, events.NewMessage(chats=self.entity))
        self.listener_active = True
        return f"✅ <b>Listener activado en:</b> {self.grupo_actual}"

    async def desactivar_listener(self):
        if hasattr(self, '_event_handler') and self._event_handler:
            self.user_client.remove_event_handler(self._event_handler)
            self._event_handler = None
            self.listener_active = False
            return "✅ <b>Listener desactivado.</b>"
        return "ℹ️ <b>No hay listener activo.</b>"
    
    async def obtener_info_grupo(self):
        if not self.entity:
            return "❌ <b>No hay grupo seleccionado.</b>"
        try:
            info = {
                'Nombre': getattr(self.entity, 'title', 'Desconocido'),
                'ID': getattr(self.entity, 'id', 'Desconocido'),
                'Tipo': 'Canal' if isinstance(self.entity, types.Channel) and getattr(self.entity, 'broadcast', False)
                        else ('Supergrupo' if isinstance(self.entity, types.Channel) else 'Grupo'),
                'Descripción': getattr(self.entity, 'about', 'No disponible')
            }
            try:
                full_chat = await self.user_client(types.functions.channels.GetFullChannel(channel=self.entity))
                info['Miembros'] = getattr(full_chat.full_chat, 'participants_count', 'No disponible')
            except:
                info['Miembros'] = 'No disponible'
            return "<pre>" + json.dumps(info, indent=2, ensure_ascii=False) + "</pre>"
        except Exception as e:
            logger.error(f"Error obteniendo info del grupo: {e}")
            return f"❌ <b>Error:</b> {e}"
    
    async def listar_usuarios_grupo(self, limite=50):
        if not self.entity:
            return "❌ <b>No hay grupo seleccionado.</b>"
        usuarios = []
        try:
            async for participante in self.user_client.iter_participants(self.entity, limit=limite):
                nombre = participante.first_name or ''
                if participante.last_name:
                    nombre += f" {participante.last_name}"
                usuarios.append({
                    'id': participante.id,
                    'nombre': nombre,
                    'username': participante.username or 'No disponible',
                    'bot': 'Sí' if participante.bot else 'No'
                })
            return "<pre>" + json.dumps(usuarios, indent=2, ensure_ascii=False) + "</pre>"
        except errors.ChatAdminRequiredError:
            return "❌ <b>Se requieren permisos de administrador para listar usuarios.</b>"
        except Exception as e:
            return f"❌ <b>Error:</b> {e}"

    # ----------------- Comandos del Bot -----------------
    
    def register_handlers(self):
        # Función auxiliar para permitir solo al dueño
        def is_owner(event):
            return event.sender_id == self.owner_id

        @self.bot_client.on(events.NewMessage(pattern=r'^/start'))
        async def start_handler(event):
            if not is_owner(event):
                return
            mensaje = (
                "<b>👋 ¡Hola! Soy tu Scraper Bot.</b>\n\n"
                "<b>Comandos:</b>\n"
                "<code>/grupo &lt;ID_o_username&gt;</code> - Seleccionar grupo\n"
                "<code>/capturar &lt;número&gt;</code> - Capturar mensajes antiguos\n"
                "<code>/escuchar</code> - Activar listener en vivo\n"
                "<code>/parar</code> - Desactivar listener\n"
                "<code>/info</code> - Información del grupo\n"
                "<code>/usuarios</code> - Listar usuarios\n"
                "<code>/estado</code> - Estado de la sesión"
            )
            await event.respond(mensaje, parse_mode="HTML")
        
        @self.bot_client.on(events.NewMessage(pattern=r'^/grupo\s+(.*)'))
        async def grupo_handler(event):
            if not is_owner(event):
                return
            grupo = event.pattern_match.group(1).strip()
            respuesta = await self.conectar_grupo(grupo)
            await event.respond(respuesta, parse_mode="HTML")
        
        @self.bot_client.on(events.NewMessage(pattern=r'^/capturar(?:\s+(\d+))?'))
        async def capturar_handler(event):
            if not is_owner(event):
                return
            limite = event.pattern_match.group(1)
            limite = int(limite) if limite and limite.isdigit() else 100
            respuesta = await self.capturar_mensajes_antiguos(limite=limite)
            await event.respond(respuesta, parse_mode="HTML")
        
        @self.bot_client.on(events.NewMessage(pattern=r'^/escuchar'))
        async def escuchar_handler(event):
            if not is_owner(event):
                return
            respuesta = await self.escuchar_mensajes_nuevos()
            await event.respond(respuesta, parse_mode="HTML")
        
        @self.bot_client.on(events.NewMessage(pattern=r'^/parar'))
        async def parar_handler(event):
            if not is_owner(event):
                return
            respuesta = await self.desactivar_listener()
            await event.respond(respuesta, parse_mode="HTML")
        
        @self.bot_client.on(events.NewMessage(pattern=r'^/info'))
        async def info_handler(event):
            if not is_owner(event):
                return
            respuesta = await self.obtener_info_grupo()
            await event.respond(f"📌 <b>Información del grupo:</b>\n{respuesta}", parse_mode="HTML")
        
        @self.bot_client.on(events.NewMessage(pattern=r'^/usuarios(?:\s+(\d+))?'))
        async def usuarios_handler(event):
            if not is_owner(event):
                return
            limite = event.pattern_match.group(1)
            limite = int(limite) if limite and limite.isdigit() else 50
            respuesta = await self.listar_usuarios_grupo(limite=limite)
            await event.respond(f"👥 <b>Usuarios del grupo:</b>\n{respuesta}", parse_mode="HTML")
        
        @self.bot_client.on(events.NewMessage(pattern=r'^/estado'))
        async def estado_handler(event):
            if not is_owner(event):
                return
            duracion = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
            horas = int(duracion // 3600)
            minutos = int((duracion % 3600) // 60)
            segundos = int(duracion % 60)
            estado = (
                f"👤 <b>Grupo actual:</b> {self.grupo_actual or 'Ninguno'}\n"
                f"✉️ <b>Mensajes capturados:</b> {self.message_count}\n"
                f"⏱ <b>Tiempo de sesión:</b> {horas:02}:{minutos:02}:{segundos:02}\n"
                f"📡 <b>Listener:</b> {'Activo' if self.listener_active else 'Inactivo'}"
            )
            await event.respond(estado, parse_mode="HTML")
    
    async def run(self):
        await self.start_clients()
        self.register_handlers()
        logger.info("Scraper Bot iniciado. Esperando comandos...")
        await self.bot_client.run_until_disconnected()

if __name__ == "__main__":
    scraper_bot = TelegramScraperBot()
    try:
        asyncio.run(scraper_bot.run())
    except KeyboardInterrupt:
        logger.info("Proceso interrumpido manualmente")
