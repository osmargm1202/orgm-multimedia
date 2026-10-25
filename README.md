# ORGM Home

Launcher multimedia y mando web para una sesión Sway dedicada. Fase 1 del [plan original](docs/phase1-plan.md).

Un único proceso FastAPI sirve HTML, CSS, JavaScript y la API. Un agente de la sesión `media` ejecuta una lista fija de acciones por socket Unix privado y verifica el UID del cliente. No hay base de datos, panel administrativo, runtime Node ni túnel adicional.

## Instalación NixOS

La infraestructura vive en [`osmargm1202/nixos`](https://github.com/osmargm1202/nixos): output `jarq-multimedia`, módulo `nixos/profiles/multimedia.nix` y catálogo `nixos/profiles/multimedia/apps.nix`. Este repositorio contiene la aplicación y su empaquetado Python/Nix. El input NixOS fija una revisión de esta fuente.

El perfil crea `media` sin sudo y conserva el administrador `jarq`. greetd inicia Sway, importa las variables reales al gestor systemd de usuario y arranca agente, kiosk y seguimiento HDMI. El servidor web vive en un servicio de sistema independiente. Chrome conserva un perfil por servicio en `~media/.local/share/orgm-home/chrome`.

```bash
nix build .#nixosConfigurations.jarq-multimedia.config.system.build.toplevel
sudo ./result/bin/switch-to-configuration switch
```

Revisar antes el hardware y los cambios de servicios de la máquina concreta. La configuración en ejecución de Jarq puede provenir de un checkout distinto. El cambio sustituye su sesión gráfica; las generaciones previas deben conservarse para rollback.

## Vincular un mando

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
- `wtype` introduce teclas/texto. El perfil NixOS aplica un parche local de keycodes para Chrome ([referencia upstream](https://github.com/atx/wtype/pull/74)). El texto usa una selección Wayland temporal y un atajo con códigos físicos estables; se borra esa selección al terminar. La prueba real verifica acentos, signos, emojis y otros alfabetos sin basarse únicamente en el exit code. Spotify usa MPRIS; mpv su socket propio. Chrome usa teclas de mejor esfuerzo, sin inventar estado de reproducción.
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

Las 44 pruebas unitarias verifican autenticación, CSRF, límites de entrada, allowlists, URL/destinos privados, HDMI y reutilización de ventanas. `tests/browser_smoke.py` prueba la UI con un agente simulado; `tests/session_smoke.py` usa Sway, Chrome y wtype reales en una sesión aislada. El check NixOS `multimedia-boot` verifica greetd autologin, kiosk, nftables, reinicios de servicios y retorno al inicio tras apagar/arrancar una VM. No certifican el hardware de Jarq, HDMI hotplug físico, cuentas comerciales, DRM, teléfono ni la configuración externa de Cloudflare. Registrar esas comprobaciones en el informe de despliegue de NixOS antes de marcar Fase 1 aceptada.
