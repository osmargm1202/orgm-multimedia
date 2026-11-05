# Pantalla en directo y ventana central

La vista **Pantalla** del mando usa noVNC con WayVNC, hasta 20 fps. Se transmite solo mientras está visible; salir al mando, ocultar la pestaña o cerrar la página desconecta el visor. La alternativa **Captura ligera** conserva las imágenes cada dos segundos. VNC no transmite audio.

La imagen pasa por un WebSocket del mismo origen y la autorización del mando. El backend VNC escucha únicamente en un socket Unix privado; no se abre un puerto VNC. Cada conexión comprueba cookie, Host y Origin, y vuelve a comprobar la autorización cada ocho segundos. El último visor detiene WayVNC; las concesiones abandonadas vencen a los 25 segundos. Máximo dos visores simultáneos. El servicio depende del agente y termina cuando este se reinicia.

Los clics y el desplazamiento se envían por la API existente, con coordenadas y ventana verificadas. En móvil se puede deslizar sobre la imagen. La barra del teléfono conserva la escritura contextual. WayVNC captura sin crear otro teclado virtual, para evitar cambios de mapa que pueden romper Chromium/Electron. El portapapeles permanece separado. Esta vista permite clic y desplazamiento; no implementa arrastrar objetos ni enviar combinaciones arbitrarias del teclado.

Las webapps Chrome conservan una sola ventana y una sola página. El agente cierra las ventanas adicionales de cada perfil, incluso en segundo plano. La selección de la ventana central prioriza la marca existente y después el identificador más antiguo. Las aplicaciones nativas, Home y el receptor AirPlay quedan fuera de esta política.

El guardián CDP conserva el identificador de la página principal en `browser-primary.json`, con permisos 0600; no guarda títulos ni URLs. Esto permite cerrar pestañas nuevas incluso después de reiniciar el agente, sin cambiar la página principal al recibir foco un popup. Las navegaciones y redirecciones dentro de esa página continúan funcionando. Cuando no hay estado y existen varias pestañas independientes antiguas, conserva esa sesión ambigua para no adivinar cuál contiene la película; cerrar y reabrir esa webapp establece una página principal inequívoca.

Los enlaces que intentan abrir otra ventana o pestaña se cierran, incluidos los flujos de acceso que dependan de una ventana adicional. La navegación dentro de la ventana principal sigue permitida.

Validación: pruebas unitarias, navegador del mando, cierre real de popup/pestaña en Chromium y compositor Sway privado con WayVNC/noVNC, actualización de imagen, clic nativo y liberación del visor.
