# Enviar contenido a Jarq

Win+Alt+Y conserva el texto seleccionado como origen y envía HTTPS directamente,
sin abrir el navegador del equipo emisor. Se mantienen el ejecutable
`orgm-send-youtube` y su carpeta de autorización `orgm-home/youtube-send`; la
identidad ya aprobada sigue sirviendo. `orgm-send-media` es un nombre adicional.
No se recurre al contenido antiguo del portapapeles cuando falla la selección.

Enlaces directos reconocidos:

| Servicio | Formatos |
| --- | --- |
| YouTube | watch, Shorts, live, embed, youtu.be; conserva el tiempo |
| Netflix | title/ID, watch/ID, browse?jbv=ID |
| Disney+ | browse/entity-UUID, play/UUID, video/UUID, movies o series con ID |
| Max/HBO Max | movie, show, video, feature con ID |
| Crunchyroll | watch/ID, series/ID |
| Prime Video | primevideo.com/detail/ID o dp/ID |
| Spotify | open.spotify.com con track, album, playlist, episode, show o artist |
| Navegador | Otros enlaces HTTP(S) a destinos públicos |

Se eliminan parámetros de seguimiento de los servicios nuevos. Los enlaces de otros dominios se envían a Navegador y conservan ruta, query y
fragmento completos; no se intenta reproducirlos automáticamente. La clasificación
no sigue redirecciones ni los convierte a otra webapp: el navegador procesa el
enlace con su política de red. Se rechazan direcciones privadas, credenciales,
puertos no admitidos y texto inválido; el receptor comprueba también DNS antes de
activar una fuente. Los enlaces mal formados de servicios conocidos se siguen
rechazando para no sustituir un video por un error de selección.

El receptor reutiliza la ventana de la webapp mediante CDP. Spotify recibe su
URI nativa. El receptor intenta iniciar el reproductor o un botón primario de
reproducción durante unos segundos; nunca alterna Play/Pausa como mecanismo de
inicio, porque eso podría pausar algo que ya reproduce. El intento comprueba el
ID en la página y el foco, y se cancela al usar el mando o cambiar de aplicación.
No selecciona perfiles, inicia sesión ni acepta compras. Prime Video solo inicia
un reproductor ya cargado; no automatiza sus botones de alquiler.

La respuesta `playback: requested` confirma la solicitud, no que el proveedor
haya reproducido. Una cuenta sin iniciar, selección de perfil, DRM, disponibilidad
del título o cambios del sitio pueden requerir intervención en la sala.

El formulario Enviar contenido a Jarq del mando admite los mismos servicios.
El enlace rápido general es `/media/link/?key=URL_CODIFICADA`. El enlace antiguo
`/youtube/link/?key=...` también los admite por compatibilidad. Un GET o una vista
previa no reproduce nada; el envío requiere interacción de navegación explícita
y un dispositivo autorizado, con los mismos controles de sesión y CSRF.

Pruebas: clasificación/rechazo de enlaces, autorización persistente, envío
sin navegador, reutilización de página y arranque con identidad correcta en
Chromium aislado. Los fixtures de proveedores no certifican sus sesiones o DRM.
