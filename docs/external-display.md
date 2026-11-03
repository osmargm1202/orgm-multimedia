# Encendido de la pantalla externa

En Encendido, tanto en el dashboard como en el mando autorizado, el botón
«Apagar pantalla externa» corta la salida HDMI. Cambia a «Activar pantalla
externa» para recuperar la imagen. No apaga la computadora ni la pantalla táctil,
y conserva las ventanas y aplicaciones. El audio por HDMI puede dejar de estar
disponible mientras la salida está apagada.

El servicio de pantallas respeta esta selección, incluso si se reinicia el
launcher. Se guarda en un marcador privado del directorio de ejecución del
usuario media; se restablece al reiniciar el equipo. Una desconexión HDMI real
seguida de una conexión recupera la señal automáticamente. El sondeo ocurre
cada dos segundos y no detecta cambios de alimentación de monitores que mantienen
HDMI conectado en reposo.

Que el monitor o proyector entre en reposo o se apague al perder señal depende
de su configuración. No se envían órdenes HDMI-CEC de encendido/apagado: si
está apagado físicamente hay que encenderlo; si no anuncia una nueva conexión,
se recupera la salida con «Activar pantalla externa».

Se usa `output HDMI-A-1 power off/on` de Sway, conservando los workspaces.
No se usa `disable`, que movería sus ventanas. La salida interna no se modifica
por esta acción. El endpoint `/api/display/external` exige emparejamiento,
CSRF y un booleano estricto; el agente rechaza salidas ausentes o no válidas.

Referencia: https://man.archlinux.org/man/sway-output.5.en
