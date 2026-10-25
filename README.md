# ORGM Home

Launcher multimedia y mando web para una sesión Sway dedicada. Fase 1 del [plan original](docs/phase1-plan.md).

El inicio actual sigue una referencia cinematográfica del usuario: navegación lateral, pestañas, 22 portadas locales, capturas de ventanas abiertas y Spotify con Play/Pausa sin abandonar el menú. Los prompts de las portadas están en [docs/service-covers.md](docs/service-covers.md).

Spotify continúa en Inicio y en aplicaciones silenciosas; se pausa cuando la fuente seleccionada empieza a reproducir audio. Las capturas se obtienen por identificador de ventana con `grim -T`, incluso si están en otro workspace, sin cambiar el foco. Se almacenan en el directorio privado del servicio y requieren vinculación para descargarlas por la API.

El catálogo añade AirPlay/UxPlay, Kitty, Disney+, Prime Video, Immich en fotos.or-gm.com, Claude en claude.ai, ChatGPT, Uber Eats, Twitch y Kick. Kitty se ejecuta como media; no recibe privilegios de administrador. El pegado usa Ctrl+Shift+V en la terminal. Las cuentas de cada webapp se vinculan manualmente en su perfil independiente.

Opciones permite conectar Wi-Fi desde la pantalla local: buscar redes, reconectar y escribir la contraseña con el teclado táctil. Las claves viajan por el socket local y un archivo temporal modo 0600; no aparecen en argv ni en respuestas de estado. El reinicio de Administración detiene primero el launcher y los portales para que el teclado deje Wayland antes que Sway.

AirPlay se inicia desde su tarjeta y anuncia el nombre configurado por NixOS. Requiere la misma red local; Jarq permite los puertos TCP/UDP 7000–7002 desde 10.0.0.0/24 y usa Avahi para descubrimiento. El receptor se cierra con la X. Referencia del servidor: [FDH2/UxPlay](https://github.com/FDH2/UxPlay).

Las tarjetas de «Abiertas en tu sala» tienen una X independiente para cerrar esa
aplicación y sus ventanas desde Inicio. El foco de las demás fuentes se conserva;
si se cierra la fuente que estaba en pantalla, vuelve a Inicio. Cerrar Spotify
termina también su sandbox para que no quede audio sin ventana. La X de la barra
superior sigue cerrando únicamente la página actual.

## Desde el teléfono

En YouTube, conecta el teléfono al mismo Wi-Fi y selecciona **ORGM Jarq · YouTube**
en Transmitir. El servicio `orgm-home-cast` anuncia DIAL por UDP 1900 y ofrece su
entrada HTTP en TCP 8766, incluso con VacuumTube cerrado. Una solicitud de inicio
abre/enfoca YouTube mediante la API autenticada y entrega el emparejamiento a su
receptor nativo. Las consultas de estado no cambian el foco. La compatibilidad
final con Android/iOS se comprueba con un teléfono real.

El servicio corre con un usuario dinámico diferente de `media`, recibe la clave
por `LoadCredential` y solo permite la LAN declarada, rutas fijas de YouTube y
cuerpos limitados. La política de salida privada de `media` permanece intacta;
no se abren los puertos variables de VacuumTube ni se publica DIAL por Internet.
Variables: `ORGM_DIAL_NETWORKS` contiene las subredes IPv4 autorizadas y
`ORGM_DIAL_NAME` el nombre anunciado. VacuumTube necesita Device Discoverability
activado; viene activado en la instalación comprobada de Jarq.

En Jarq, el mando tiene además una entrada privada por Wi-Fi en
`http://10.0.0.98`, con la misma vinculación y protección CSRF. El nombre
`home.or-gm.com` sigue resolviendo a la IP de Tailscale. El dominio padre aplica
HSTS con `includeSubDomains`: un navegador que lo haya visitado exige HTTPS
también para Home. El perfil sirve `https://home.or-gm.com` con certificado ACME
validado por DNS de Cloudflare y renovación automática. HTTP del dominio redirige
a HTTPS; la IP local conserva su entrada HTTP independiente.

UxPlay recibe video directo de YouTube con `-hls`. Al aparecer una ventana nativa
de video AirPlay, el launcher muestra esa fuente automáticamente; la pantalla de
espera y los popups web en segundo plano no cambian el foco. El receptor arranca
con la sesión; cerrarlo con la X lo detiene hasta volver a abrir AirPlay.

**Max:** Opciones → Desde el teléfono permite enviar un enlace HTTPS de
`max.com` o `hbomax.com` a su webapp, usando el perfil y la sesión de Max en Jarq.
Requiere un mando vinculado. No emula un Chromecast ni un receptor certificado
para contenido protegido; iniciar sesión y reproducir siguen dependiendo de Max.

Un único proceso FastAPI sirve HTML, CSS, JavaScript y la API. Un agente de la sesión `media` ejecuta una lista fija de acciones por socket Unix privado y verifica el UID del cliente. No hay base de datos, runtime Node ni túnel adicional.

## Instalación NixOS

La infraestructura vive en [`osmargm1202/nixos`](https://github.com/osmargm1202/nixos): output `jarq-multimedia`, módulo `nixos/profiles/multimedia.nix` y catálogo `nixos/profiles/multimedia/apps.nix`. Este repositorio contiene la aplicación y su empaquetado Python/Nix. El input NixOS fija una revisión de esta fuente.

El perfil crea `media` sin sudo y conserva el administrador `jarq`. greetd inicia Sway, importa las variables reales al gestor systemd de usuario y arranca agente, kiosk y seguimiento HDMI. El servidor web vive en un servicio de sistema independiente. Chrome conserva un perfil por servicio en `~media/.local/share/orgm-home/chrome`.

```bash
nix build .#nixosConfigurations.jarq-multimedia.config.system.build.toplevel
sudo ./result/bin/switch-to-configuration switch
```

Revisar antes el hardware y los cambios de servicios de la máquina concreta. La configuración en ejecución de Jarq puede provenir de un checkout distinto. El cambio sustituye su sesión gráfica; las generaciones previas deben conservarse para rollback.

## Vincular un mando

En la pantalla de Jarq: **Opciones → Desde el teléfono → Generar código**.
Escribir esos seis dígitos en el teléfono. El código dura dos minutos, se usa
una vez y se invalida tras diez intentos incorrectos o al generar otro. Solo
la pantalla local ya vinculada puede emitirlo; el mando remoto no expone la
clave permanente. El registro de un código no modifica las sesiones existentes.

En el equipo, `orgm-home-pair` muestra mediante sudo la clave aleatoria generada en `/var/lib/orgm-home/control-token`. Introducirla en el mando autorizado; dura 12 horas la sesión de ese dispositivo. El kiosk recibe la clave por fragmento de URL (no se envía en rutas ni logs HTTP) y la intercambia por una cookie HttpOnly. La aplicación elimina el fragmento de inmediato.

No reutilizar contraseñas de cuentas. Para revocar todos los mandos: reemplazar el archivo de clave por otro valor aleatorio de al menos 32 caracteres, conservar propietario media y modo 0600, reiniciar API y kiosk. El archivo nunca pertenece al repositorio ni al Nix store.

## Red y Cloudflare Access

Por defecto la API escucha **solo 127.0.0.1:8765**. Para probar remotamente sin publicar:

```bash
ssh -L 8765:127.0.0.1:8765 jarq@jarq
# Abrir http://127.0.0.1:8765 en ese mismo cliente.
```

El modo público requiere, además de vincular el mando, un JWT Cloudflare Access firmado y válido para la audiencia e issuer configurados. El usuario confirmó usar `http://home.or-gm.com` por ahora y que el nombre apunta a la IP Tailscale de Jarq: en ese despliegue privado Nginx escucha únicamente en esa dirección, el firewall permite su puerto solo por `tailscale0` y la autenticación usa vinculación + CSRF. `ORGM_REQUIRE_ACCESS=false` se configura exclusivamente para ese modo privado; nunca deshabilitarlo en un origen publicado por Internet. Sin configuración, el control público responde 503. El hostname no demuestra que Access esté habilitado: verificar la política de usuarios en Cloudflare antes de anunciar la publicación.

Un administrador crea `/var/lib/orgm-home/access.env`, propietario root, modo 0600:

```dotenv
ORGM_ACCESS_TEAM=https://NOMBRE.cloudflareaccess.com
ORGM_ACCESS_AUD=AUDIENCIA_DE_LA_APLICACION
ORGM_ACCESS_EMAILS=familiar1@example.com,familiar2@example.com
```

Reiniciar `orgm-home.service`. Estos valores se toman de la aplicación Access real; no adivinarlos. La lista de correos restringe adicionalmente la autorización en el origen. [Validación oficial de JWT](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/).

Si Nginx existente está en el mismo Jarq, `orgm.multimedia.nginx = true` proporciona el virtualhost loopback 127.0.0.1:8085 para reutilizar el túnel. Ver [ejemplo de proxy](docs/nginx.conf). Si el proxy reside en otra máquina, configurar un listener en una IP LAN/VPN concreta y un firewall limitado a ese proxy; el perfil no abre 8765 en toda la red. Inspeccionar primero el despliegue existente y conservar sus otros hosts. No copiar credenciales de cloudflared a este repositorio.

El backend exige cookie firmada, token CSRF y Origin exacto para mutaciones; aplica límites de peticiones, cuerpo y texto. No confía en `X-Forwarded-*` como autenticación. No recibe comandos de shell. Los enlaces aceptan únicamente HTTP(S), puertos 80/443 y resoluciones públicas. El perfil añade filtrado nftables de conexiones nuevas de media hacia redes privadas para cubrir redirecciones y DNS rebinding. Esa política puede limitar Spotify Connect en LAN; comprobarlo y documentar cualquier excepción concreta antes de ampliarla.

## Aplicaciones y controles

- VacuumTube y Spotify se instalan desde Flathub con reintento systemd. Los commits Flatpak no están fijados; Chrome y las dependencias Python sí siguen la revisión nixpkgs del perfil.
- Netflix, Max y Crunchyroll usan Chrome con perfiles independientes. El inicio de sesión comercial es manual; DRM, resolución y reproducción requieren aceptación en el hardware real.
- El agente busca marcas/app_id/clase en el árbol Sway, reutiliza ventanas y conserva workspaces. Home no las cierra. Cerrar termina solo la ventana seleccionada.
- La barra táctil superior incluye una X para cerrar la página/ventana actual. Al cerrar una ventana adicional se recupera la original de esa webapp; si era la última, se vuelve a Inicio. Las ventanas nuevas de la webapp en uso se muestran en fullscreen. Una página de una aplicación en segundo plano no cambia la fuente seleccionada.
- Al plegar la barra con la flecha hacia arriba queda una flecha gris hacia abajo, sobre fondo semitransparente arriba a la izquierda. Esa flecha recupera los controles; tocar el contenido no anula el plegado manual.
- Un motor Wayland persistente con mapa español introduce las teclas. El perfil conserva el parche local de keycodes para la compatibilidad de wtype con Chrome ([referencia upstream](https://github.com/atx/wtype/pull/74)). El texto usa una selección Wayland temporal y un atajo con códigos físicos estables; se borra esa selección al terminar. La prueba real verifica acentos, signos, emojis y otros alfabetos sin basarse únicamente en el exit code. Spotify usa MPRIS; mpv su socket propio. Chrome usa teclas de mejor esfuerzo, sin inventar estado de reproducción.
- Al cambiar se intenta pausar con MPRIS/mpv y silenciar únicamente los streams Pulse que se puedan atribuir a la app anterior. Si no se confirma, se devuelve un aviso. La reanudación de una app pausada es explícita con Play.
- El puntero remoto está deshabilitado y su endpoint responde 409. No se instala uinput/ydotoold en fase 1.
- Copiar archivos a `/home/media/Videos`, legibles por media. La lista es plana, limita extensiones/cantidad y rechaza symlinks y rutas arbitrarias.

## Desarrollo y pruebas

```bash
uv sync --locked --extra test
uv run pytest -q
```

Para ejecutar la UI se necesita un catálogo con el formato del módulo NixOS y un archivo de clave fuera del repositorio:

```bash
export ORGM_CATALOG=/ruta/apps.json
export ORGM_TOKEN_FILE=/ruta/privada/control-token
export ORGM_AGENT_SOCKET=/ruta/privada/agent.sock
uv run orgm-home
# En la sesión Sway real del usuario media, con las mismas rutas:
uv run orgm-home-agent
```

La UI mostrará sesión no disponible mientras no exista un agente conectado. Un health HTTP 200 verifica el proceso web, no la pantalla ni el audio.

## Estado de aceptación

Las pruebas unitarias verifican autenticación, CSRF, límites de entrada, allowlists, URL/destinos privados, HDMI y reutilización de ventanas. `tests/browser_smoke.py` prueba la UI con un agente simulado; `tests/session_smoke.py` usa Sway, Chrome y wtype reales en una sesión aislada. El check NixOS `multimedia-boot` verifica greetd autologin, kiosk, nftables, reinicios de servicios y retorno al inicio tras apagar/arrancar una VM. No certifican el hardware de Jarq, HDMI hotplug físico, cuentas comerciales, DRM, teléfono ni la configuración externa de Cloudflare. Registrar esas comprobaciones en el informe de despliegue de NixOS antes de marcar Fase 1 aceptada.


## Pantallas y control táctil fijo

La indicación final del usuario fija duplicación a 1080p: `eDP-1` permanece como fuente táctil y `HDMI-A-1` muestra su copia mediante wl-mirror. Las aplicaciones y workspaces 1–12 permanecen en la pantalla interna; el espejo ocupa exclusivamente el workspace 99 del HDMI. El proyector se reconecta automáticamente y, al retirarlo, la laptop conserva la sesión. Se prioriza audio HDMI cuando está disponible.

La barra de símbolos aparece arriba al tocar, con Inicio, Atrás, volumen, mute, teclado y Opciones. Se retira tras ocho segundos y no queda ningún tirador. El teclado español conserva el foco de la aplicación. Se reutilizan el layout y el motor existentes, bajo GPL, con una superficie Quickshell dedicada. Opciones muestra cinco fondos y Administración para Voltear, reiniciar el launcher y reiniciar el equipo. El reinicio requiere confirmación en la interfaz y la autorización de logind se limita a `media` en este perfil.

El agente reconcilia el mute de los flujos de audio de cada aplicación para recuperar flujos tardíos que PipeWire restauró silenciados; respeta el mute global del usuario. Atrás usa códigos físicos del motor de teclado: Alt+Izquierda para páginas web y Escape para navegación nativa. El nuevo catálogo añade Poki, StreamEast, la web oficial NBA y RetroArch; no incluye juegos ni ROMs.

La política de luz pertenece a NixOS: 20% a los 20 segundos y cero al minuto. Además se apaga la retroiluminación con `bl_power=4`, manteniendo activas la salida eDP y su copia HDMI. Actividad restaura `bl_power=0`, brillo 100% y controles. La preferencia de fondo y la rotación se conservan en el estado de `media`.

El inicio muestra todo el catálogo en una banda deslizable y las categorías viven en el lateral. Wi-Fi, fondos y administración tienen vistas independientes. Spotify ofrece anterior, Play/Pausa y siguiente sin cambiar el foco. Los reproductores MPRIS se asocian a su aplicación mediante el PID de D-Bus y el cgroup de Flatpak: al salir se pausan todos los videos en segundo plano, y al volver solo se reanudan las pausas realizadas por el launcher. Una pausa manual se conserva.

«Reconectar» vuelve a asociar el perfil Wi-Fi guardado aunque NetworkManager todavía lo marque conectado; recupera enlaces Broadcom que responden a ping pero dejan de transportar DNS/HTTP. Conserva el perfil y no cambia contraseñas ni permisos de sistema.
