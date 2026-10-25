# ORGM HOME — Plan técnico de implementación

**Versión:** 1.0 · **Fecha:** 25 de octubre de 2026  
**Alcance contractual de esta entrega:** Fase 1 — Sistema multimedia NixOS autoiniciado y control remoto web responsive.  
**Infraestructura existente:** proyector HDMI, laptop NixOS dedicada, host `jarq` con Nginx/cloudflared y ruta `home.or-gm.com` ya asignada.  
**Restricción:** sin compras, sin GNOME/KDE, sin panel administrativo, sin base de datos, sin backend/frontend duplicados.

## 1. Resultado esperado

1. Se energiza la laptop y arranca NixOS sin interacción **después de cualquier desbloqueo de cifrado de disco que aplique**.
2. `greetd` inicia automáticamente la sesión gráfica del usuario limitado `media` con Sway.
3. El proyector HDMI muestra una pantalla local de inicio ORGM Home a pantalla completa. El equipo no presenta escritorio tradicional.
4. Cualquier teléfono iPhone/Android o PC autorizado abre `https://home.or-gm.com`, servido por el proxy ya existente en `jarq`, y obtiene un mando responsive.
5. Desde ese mando se selecciona YouTube TV (VacuumTube), Spotify, Netflix, Max, Crunchyroll, navegador genérico o reproductor local; si la aplicación está abierta se enfoca, y si no se inicia.
6. Flechas, OK, Atrás, Home, teclado, volumen, play/pausa y enlace web funcionan en el motor que corresponda, **con capacidades variables según el servicio**.
7. La última aplicación puede permanecer viva en su workspace para reanudarla; al cambiar se intenta pausar/silenciar para impedir audio simultáneo.
8. Al reiniciar, los servicios vuelven automáticamente, sin administrador, terminal, ratón ni teclado físico.

## 2. Decisión de compositor: Sway principal, i3 contingencia

| Criterio | Sway / Wayland | i3 / X11 |
|---|---|---|
| RAM/CPU del gestor | Muy bajo | Muy bajo |
| IPC de ventanas/workspaces | `swaymsg` y socket IPC | `i3-msg` y socket IPC |
| HDMI | `output` y wlroots | `xrandr` |
| Atajos/programas Flatpak | Bien; algunos requieren XWayland | Bien |
| Teclado/ratón a distancia | `wtype` para texto/teclas y alternativas uinput para ratón | `xdotool` directo, más sencillo |
| Compatibilidad a futuro con Quickshell | Natural | Posible |

**Se elige Sway** para aprovechar Wayland, la configuración mínima y el IPC. **No se incorpora Quickshell en fase 1**: una única ventana de Chrome kiosk con el menú local basta. Si la entrada remota en una aplicación concreta falla, se valora cambiar esa aplicación de backend de entrada o, en último término, usar i3 sin rehacer el servidor y la web.

## 3. Componentes que sí se instalan

| Componente | Origen | Función |
|---|---|---|
| NixOS, systemd | Sistema | Arranque, servicios declarativos |
| `greetd` | NixOS | Autologin real del usuario `media` |
| `sway`, `swaymsg` | NixOS | Compositor, workspaces, ventanas, HDMI |
| `xwayland` | NixOS | Compatibilidad de aplicaciones que lo necesiten |
| PipeWire, WirePlumber, `wpctl` | NixOS | Audio predeterminado HDMI y volumen |
| `xdg-desktop-portal`, `xdg-desktop-portal-wlr`, `xdg-desktop-portal-gtk` | NixOS | Integración Wayland y Flatpak |
| `flatpak` | NixOS | Instalación de aplicaciones Flathub |
| VacuumTube (`rocks.shy.VacuumTube`) | Flathub | YouTube Leanback/TV, mando nativo |
| Spotify (`com.spotify.Client`) | Flathub | Música, Spotify Connect si aplica |
| `google-chrome` | NixOS | Netflix, Max, Crunchyroll, páginas personalizadas |
| `mpv` | NixOS | Archivos locales/enlaces directos compatibles |
| `wtype` | NixOS | Entrada de teclas y texto con soporte Wayland |
| `ydotool` + `ydotoold` | Opcional, solo cuando se necesite | Cursor/clic vía uinput: requiere permisos y aislamiento |
| `python3`, FastAPI, Uvicorn, Jinja2 | Entorno de app fijado por Nix/uv | Servidor API y control HTML responsive |
| `swaymsg`, `jq` | NixOS | Descubrimiento/enfoque de aplicaciones |
| Nginx, cloudflared | **En jarq, ya existente** | Publicación HTTPS, sin instalar otro túnel en la laptop |

**No instalar inicialmente:** Plasma Bigscreen, i3, Quickshell, Next.js, Node para runtime, Kodi, Plex, Jellyfin, VNC, bases de datos, Redis, Docker ni aplicaciones Linux no oficiales para Netflix. Se evalúan en fases posteriores si existe una necesidad real.

## 4. Arranque sin interacción

### 4.1 Usuario de medios

Crear `media` como usuario normal **sin sudo**. Mantener perfil de Chrome, cookies y Flatpaks bajo `/home/media`. El usuario administrador habitual permanece separado. La laptop debe estar alimentada y tener refrigeración adecuada si operará con tapa cerrada.

### 4.2 NixOS: opciones base de referencia

```nix
{ pkgs, ... }:
{
  programs.sway = {
    enable = true;
    wrapperFeatures.gtk = true;
  };

  services.greetd = {
    enable = true;
    settings = {
      initial_session = {
        command = "${pkgs.sway}/bin/sway";
        user = "media";
      };
      default_session = {
        command = "${pkgs.sway}/bin/sway";
        user = "media";
      };
    };
  };

  users.users.media = {
    isNormalUser = true;
    createHome = true;
    home = "/home/media";
    extraGroups = [ "audio" "video" "render" ];
  };

  services.flatpak.enable = true;
  security.rtkit.enable = true;
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    pulse.enable = true;
  };

  xdg.portal = {
    enable = true;
    wlr.enable = true;
    extraPortals = [ pkgs.xdg-desktop-portal-gtk ];
  };

  environment.systemPackages = with pkgs; [
    google-chrome mpv wtype jq wireplumber
  ];
  nixpkgs.config.allowUnfree = true;
}
```

**Nota:** la forma exacta de opciones de `logind` y el módulo de Flatpak/portals se verificará contra la versión NixOS instalada; este fragmento es de referencia, no reemplaza sin inspección la configuración existente. Desactivar suspensión por tapa y por inactividad con `services.logind.settings.Login.HandleLidSwitch = "ignore"`, `HandleLidSwitchExternalPower = "ignore"`, y política de energía adecuada. Si `/` está cifrada, el desbloqueo durante boot sigue requiriendo su solución propia; greetd solo elimina la contraseña del escritorio. Autologin supone riesgo de acceso local a cuentas comerciales.

### 4.3 Al iniciar la sesión Sway

Archivo declarativo `config/sway/config`, instalado a `~media/.config/sway/config` o generado por Home Manager:

```text
set $mod Mod4
output * bg #090b10 solid_color
# Sustituir * por el conector HDMI real detectado usando swaymsg -t get_outputs
# output HDMI-A-1 mode 1920x1080@60Hz scale 1
workspace 1 output *
exec_always --no-startup-id /run/current-system/sw/bin/systemctl --user import-environment WAYLAND_DISPLAY SWAYSOCK XDG_CURRENT_DESKTOP
exec --no-startup-id /home/media/.local/bin/orgm-start-session
bindsym $mod+1 workspace number 1
bindsym $mod+Shift+e exit
```

Script de arranque `orgm-start-session`:

- Espera respuesta HTTP del servidor local `127.0.0.1:8765` con tope y reintentos.
- Lanza Google Chrome con perfil persistente separado, `--kiosk http://127.0.0.1:8765/`.
- No lanza aplicaciones comerciales hasta que se pidan desde el mando.
- Gestiona arranque/reintento con systemd de usuario, **no mediante un bucle infinito dentro de Sway**.

### 4.4 Servicio web local

FastAPI/Uvicorn se ejecutará mediante un `systemd` system service con `User=media`, `WorkingDirectory=/opt/orgm-home`, `ExecStart` apuntando al Python bloqueado con Nix/uv y `Restart=on-failure`. Escuchará **solo en la IP LAN designada y/o localhost** según la topología Nginx y no se abrirá indiscriminadamente en interfaces externas. El servicio web es independiente de la sesión gráfica; las acciones de Sway se ejecutarán mediante un **agente de sesión** bajo `media`, comunicándose con la API a través de un socket Unix autenticado o el socket IPC, evitando confiar en variables de sesión adivinadas.

## 5. Catálogo fijo declarado desde NixOS

Las aplicaciones se declaran en `config/apps.json` o se generan con `pkgs.writeText` / `pkgs.formats.json`. No hay base de datos ni panel Admin.

```json
{
  "apps": [
    {"id":"home", "type":"internal", "name":"ORGM Home", "workspace":"1"},
    {"id":"youtube", "type":"flatpak", "name":"YouTube", "appId":"rocks.shy.VacuumTube", "workspace":"2", "control":"native"},
    {"id":"spotify", "type":"flatpak", "name":"Spotify", "appId":"com.spotify.Client", "workspace":"3", "control":"mpris"},
    {"id":"netflix", "type":"chrome", "name":"Netflix", "url":"https://www.netflix.com", "workspace":"4", "control":"keyboard"},
    {"id":"max", "type":"chrome", "name":"Max", "url":"https://www.max.com", "workspace":"5", "control":"keyboard"},
    {"id":"crunchyroll", "type":"chrome", "name":"Crunchyroll", "url":"https://www.crunchyroll.com", "workspace":"6", "control":"keyboard"},
    {"id":"browser", "type":"chrome", "name":"Navegador", "url":"about:blank", "workspace":"7", "control":"pointer"},
    {"id":"videos", "type":"mpv", "name":"Videos locales", "workspace":"8", "control":"mpv"}
  ]
}
```

Para Chrome: cada servicio se abre como `--app=<url>` con un perfil persistente por aplicación (`--user-data-dir` separado); **no compartir dos procesos usando simultáneamente un mismo perfil**. Los navegadores protegidos conservan sesión, pero la resolución/DRM se valida en hardware. No automatizar credenciales.

Para Flatpak: ejecutar `flatpak run <ID>`; configurar Flathub e instalar bajo la cuenta o de manera global, fijando las versiones de despliegue si se quiere reproducibilidad completa. La instalación declarativa estricta puede implementarse después con `nix-flatpak`, sin añadir interfaz gráfica de tienda.

## 6. Ciclo de vida de ventanas y workspaces

Un registro simple en memoria relaciona `{app_id, workspace, PID, window_id, last_focus, media_state}`. No confía únicamente en PID (Chrome reutiliza procesos); obtiene árbol real mediante `swaymsg -t get_tree -r`, identificando `app_id`, `class`, título y marcas/criterios. El detector espera la aparición de la ventana con timeout antes de enfocarla.

**Abrir aplicación:** validar el ID contra el catálogo → comprobar ventana existente → si existe, enviar `swaymsg` para enfocar → si no, arrancar proceso predefinido y esperar ventana → mover al workspace configurado → pantalla completa. **Home:** ir al workspace 1 y enfocar el menú; las demás apps permanecen abiertas. **Cambiar:** solicitar pausa MPRIS o tecla específica a la anterior cuando proceda, silenciar cuando sea viable y enfocar la nueva. **Cerrar:** acción explícita; no usar `killall chrome` ni terminar procesos genéricos.

Todos los comandos se ejecutan con argumentos construidos internamente desde configuración fiable, **sin shell interpolado de entrada HTTP**.

## 7. Mando responsive: HTML/CSS/JS ligero

La misma app FastAPI sirve `GET /` con Jinja2 y archivos CSS/JS estáticos. Sin React/Next.js, Quickshell ni compilación frontend en fase 1. Diseño mobile-first, iconos táctiles y soporte de teclas de navegador PC.

**Vistas:**

- Inicio: cuadrícula con YouTube, Spotify, Netflix, Max, Crunchyroll, Navegador y Videos.
- Mando: ↑ ↓ ← →, OK, Atrás, Home, Play/Pausa, Mute, Volumen +/-.
- Teclado: campo de texto para introducir búsquedas en el foco actual.
- Navegador: campo para enviar una URL HTTP(S) al perfil web dedicado; validación de esquema y destino para evitar usarlo como puente a recursos privados.
- Estado: online/offline, aplicación enfocada, título de ventana si está disponible, volumen; evitar inventar el estado de play de plataformas DRM.

**API mínima:**

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Salud del proceso |
| GET | `/api/apps` | Catálogo fijo |
| GET | `/api/status` | Aplicación en foco, audio, sesión |
| POST | `/api/apps/{id}/activate` | Lanzar o enfocar |
| POST | `/api/remote/key` | Tecla de lista permitida |
| POST | `/api/remote/text` | Escribir texto limitado en el foco |
| POST | `/api/remote/pointer` | Movimiento/clic validados, cuando esté habilitado |
| POST | `/api/remote/home` | Regresar al launcher |
| POST | `/api/audio/volume` | Fijar volumen dentro de límites |
| POST | `/api/browser/open-url` | Abrir URL en navegador genérico |
| WS | `/api/events` | Estado en tiempo real, opcional inicialmente |

**Entrada en Wayland:** `swaymsg` controla ventanas, pero **no introduce teclas dentro de otras aplicaciones**. Para texto/teclas probar `wtype` en clientes que implementen virtual keyboard, bajo Sway/wlroots; para puntero/clic usar mecanismo uinput (`ydotoold`) restringido y documentado, o controladores propios por aplicación. `playerctl`/MPRIS solo para apps compatibles. Mantener en el mando botones deshabilitados si una integración todavía no funciona. En Chrome, Escape, Space, flechas y Enter son controles de mejor esfuerzo; cada web puede manejar eventos de forma distinta.

## 8. Red existente: home.or-gm.com → jarq → laptop

```text
iPhone / tablet / NixOS
        HTTPS
home.or-gm.com
        |
Cloudflare Tunnel + Access
        |
cloudflared ya activo en jarq
        |
Nginx existente en jarq
        |
Red LAN: ORGM laptop :8765
        |
FastAPI / UI --> agente local media --> Sway --> HDMI
```

**No se crea otro cloudflared en la laptop.** Configurar/revisar destino de Nginx en `jarq` hacia la **IP LAN estable de la laptop** o una ruta privada equivalente; el hecho de que el hostname ya apunte a `jarq` **no significa** que el control llegue automáticamente a la laptop. Si el servidor web de `jarq` ya termina la ruta, se reutiliza su upstream. No dar por conocida la IP de la laptop.

**Seguridad obligatoria:** `home.or-gm.com` es un hostname público si está publicado por Cloudflare Tunnel. Aplicar Cloudflare Access con usuarios familiares autorizados y validar tokens en el origen cuando corresponda, más autenticación/autorización y controles CSRF/origen en el backend para cualquier acción mutante. Endpoints de control nunca se deben dejar abiertos solo porque "son del hogar". Mantener websocket autenticado, rate limit y registro mínimo. El agente Sway no debe aceptar comandos externos directos; FastAPI solamente acciones en allowlist. No exponer VNC, socket Sway ni uinput por red.

**Nginx, ejemplo ilustrativo del upstream existente:**

```nginx
location / {
  proxy_pass http://IP_LAN_LAPTOP:8765;
  proxy_http_version 1.1;
  proxy_set_header Host $host;
  proxy_set_header X-Real-IP $remote_addr;
  proxy_set_header X-Forwarded-Proto $scheme;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection "upgrade";
}
```

Sustituir `IP_LAN_LAPTOP` tras descubrimiento. Si `cloudflared` termina directamente contra otro servicio, adaptar la cadena sin duplicar proxies. Usar configuración distinta de WebSocket y timeouts si se despliega producción; ejemplo no constituye una configuración Nginx completa.

## 9. Fase única de entrega: actividades y verificación

| Orden | Trabajo | Hecho cuando... |
|---|---|---|
| 1 | Inspeccionar NixOS actual, GPU, HDMI, red LAN y audio | Salida y dispositivo de audio identificados |
| 2 | Cuenta `media`, greetd autologin y Sway | Enciende y entra a sesión sin contraseña gráfica |
| 3 | Inicio kiosk local y FastAPI con service systemd | Menú visible tras reinicio, API vuelve si falla |
| 4 | Declarar catálogo Nix y Flatpak | VacuumTube, Spotify, Chrome y mpv arrancan |
| 5 | Construir launcher backend con Sway IPC | Desde web abre o enfoca y vuelve a Home |
| 6 | Control remoto responsive | iPhone y PC accionan teclas, volumen, URL y Home |
| 7 | Rutar `jarq`/Nginx/Cloudflare Access | `home.or-gm.com` protegido controla la laptop |
| 8 | Ensayos finales | Reboot/HDMI/audio/DRM/navegación/seguridad comprobados |

### Pruebas obligatorias de aceptación

- Encendido sin intervención y retorno automático al menú; verificar también tras desconectar/reconectar proyector.
- Autologin sin pedir contraseña gráfica; si hay cifrado, documentar el paso de desbloqueo.
- VacuumTube con flechas/OK/atrás y reproducción sin mouse.
- Spotify: abrir, reproducir, pausar y verificar Spotify Connect si está disponible en la cuenta y el cliente.
- Netflix, Max y Crunchyroll: login manual inicial, video, audio, DRM, resolución real y reproducción fullscreen. No declarar compatibilidad hasta probar en la laptop.
- El teléfono entra por `home.or-gm.com`; acceso no autorizado bloqueado por Cloudflare Access y backend.
- Tocar Home recupera pantalla principal sin cerrar aplicaciones; las ventanas existentes se reutilizan.
- Audio de aplicación anterior no sigue sonando simultáneamente, cuando la integración permita pausa; documentar excepciones.
- La API no acepta comandos de shell, URL `file:`, acciones arbitrarias ni IDs desconocidos.
- Tras reinicio y caída/reinicio de la API los servicios se recuperan.

## 10. Lo que se pospone expresamente

1. **Quickshell**: reemplazo gráfico del menú solo si se necesita launcher QML nativo, animaciones, overlay o mando por HDMI-CEC.
2. **Administración web dinámica**: alta de aplicaciones, iconos, orden, perfiles y permisos. En fase 1, el catálogo es inmutable desde NixOS.
3. **Extensión de navegación espacial HTML**: detección de botones DOM, selectores JSON por dominio y resaltado visual; mientras tanto usamos teclado nativo y modo ratón si hace falta.
4. **Clientes comunitarios de Netflix/Max/Crunchyroll**: evaluar tras comprobar DRM en Chrome, sin comprometer credenciales en aplicaciones no auditadas.
5. **Kodi/Jellyfin/Plex**, biblioteca de medios, cast, AirPlay, VNC, captura de pantalla y streaming remoto de la imagen.
6. **Plasma Bigscreen e i3**: alternativas técnicas, no dependencias activas.

## 11. Fuentes técnicas verificadas

- NixOS greetd / autologin: https://wiki.nixos.org/wiki/Greetd
- NixOS Sway: https://wiki.nixos.org/wiki/Sway
- NixOS i3: https://wiki.nixos.org/wiki/I3
- Flathub y NixOS: https://flathub.org/es/setup/NixOS
- VacuumTube: https://github.com/shy1132/VacuumTube
- Flatpak VacuumTube: https://flathub.org/apps/rocks.shy.VacuumTube
- Cloudflare Access: https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/

---

**Decisión de arquitectura de Fase 1:** NixOS + greetd → Sway → Chrome kiosk local + VacuumTube / Spotify / Chrome webapps / mpv → controlador IPC/entrada → FastAPI + HTML/CSS/JS → Nginx y cloudflared existentes en `jarq` → `home.or-gm.com`.
