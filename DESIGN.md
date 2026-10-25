# ORGM Home — centro multimedia cinematográfico

Referencia visual suministrada por el usuario: `/home/osmarg/Downloads/Cinematic Dark Media Center Dashboard.png`. Esta dirección sustituye la propuesta anterior de iconos en una cuadrícula.

## Dirección y jerarquía

Una sala cinematográfica: navegación lateral, ORGM Home y reloj reales, categorías en el lateral y catálogo completo deslizable con imágenes grandes, capturas de ventanas abiertas, música persistente y controles de audio a la derecha. Esta composición corresponde al kiosk local. Los navegadores vinculados de teléfono y escritorio empiezan en Mando y conservan la misma identidad oscura, tipografía e iconografía. Inicio muestra siempre todas las apps; una categoría filtra únicamente su grupo. No se inventan películas vistas, playlists, tiempos de reproducción ni progreso.

Las tarjetas usan las 22 portadas raster generadas y empaquetadas en `static/cards/`; el nombre permanece como texto accesible. Una aplicación abierta puede mostrar su captura en la tarjeta y en la fila Abiertas. La captura usa el identificador de ventana, no enfoca la app ni fotografía los controles superpuestos. El estado vacío explica que las apps abiertas aparecerán aquí.

La fila Abiertas añade una X discreta arriba a la derecha de cada captura,
con área táctil de 44 px y etiqueta «Cerrar [aplicación]». Es un botón hermano
del acceso a la fuente: cerrar no abre ni enfoca primero la aplicación. Opciones
→ Desde el teléfono explica YouTube y permite enviar enlaces de Max; sus funciones
se presentan según su compatibilidad real, sin prometer Cast para contenido DRM.

Paleta: noche #161b27, panel #0c1723, control #34415b, texto #f2f5fc, secundario #b5c2d9 y selección #8ec9ff. Manrope conserva la identidad: marca 800, títulos/nombres 600–700, texto 500. Los colores de las portadas identifican servicios, no estados inventados.

## Controles y adaptación

Home reserva 104 px para la barra nativa situada en y=12–92, por lo que nunca tapa título, Opciones ni Bomba. La barra usa nueve botones SVG de 56 px y un porcentaje de volumen; el segundo botón abre el selector de aplicaciones sobre la fuente actual. Al plegarla queda una flecha gris sobre fondo semitransparente arriba a la izquierda. No hay transporte global ni controles de brillo manual. Se conserva la atenuación 20%/20 s, retroiluminación apagada/60 s y retorno a 100% por actividad.

El dashboard local conserva solo volumen, silencio, Atrás y teclado junto a la música; la pantalla táctil sustituye flechas y OK. El lateral contiene Inicio, categorías y un único acceso a Opciones. La banda de aplicaciones permite deslizar por las 22 fuentes desde el primer arranque. Wi-Fi es un panel nativo independiente; Fondos y Administración tienen páginas propias dentro de Opciones. Los botones tienen foco visible y se respeta movimiento reducido.

El mando remoto usa una columna centrada de hasta 480 px tanto en escritorio como en teléfono. La navegación inferior fija reúne Mando, Aplicaciones y Opciones, con espacio reservado para no cubrir los controles y respeto al área segura del dispositivo. Su selección se distingue mediante fondo azul y texto claro. El catálogo remoto ocupa hasta 1024 px; a 720 px o menos sus portadas se distribuyen en dos filas deslizables y el reloj se oculta.

La cruceta circular tiene cuatro direcciones con esquinas suaves y un OK central claro, de contraste alto; mide 252 px en escritorio y 224 px en móvil. Inicio y Cambiar app preceden a la cruceta. Atrás y Teclado, navegación web anterior/siguiente y volumen forman filas debajo, con controles de al menos 48 px de alto. El nombre y el estado de la fuente son reales; las indicaciones explican Tab/Shift+Tab y las capacidades de cada aplicación. Abrir una app devuelve el navegador a Mando. Inicio cambia la pantalla de Jarq al dashboard.

Cambiar app es un diálogo de hasta 480 px, con filas de miniatura y nombre, selección marcada en azul y una X independiente de 44 px para cerrar cada fuente. Su acceso al catálogo permite abrir otra aplicación. El selector nativo conserva un panel de hasta 640 px, tarjetas en tres columnas y la marca En pantalla. Ambos muestran solo fuentes abiertas y cambian directamente a su ventana; abrir el selector conserva la aplicación actual. La X del panel nativo cierra el panel, mientras la X de su barra cierra la página. Se conservan las portadas existentes y la paleta de selección, sin introducir otra identidad visual.

## Música, conexión y equipo

Spotify conserva la reproducción en Inicio y apps silenciosas. La fuente seleccionada interrumpe la música cuando crea un stream de audio activo. El reproductor del inicio muestra metadatos MPRIS reales y Anterior, Play/Pausa y Siguiente actúan sobre Spotify sin enfocar su ventana.

Wi-Fi abre un selector local de NetworkManager, con búsqueda, reconexión y contraseña enmascarada mediante el teclado existente. La contraseña viaja por stdin y un archivo temporal privado, nunca por argumentos de proceso. AirPlay usa una pantalla de espera y UxPlay. Administración conserva rotación y reinicios; el reinicio del menú cierra los controles antes que el compositor.

Kitty es una terminal del usuario media. Claude es `https://claude.ai`, una webapp independiente, sin instalar Claude Code.
