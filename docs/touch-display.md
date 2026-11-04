# Pantalla táctil siempre encendida

Opciones → Administración incluye el botón «Pantalla táctil siempre encendida».
Sirve tanto en la laptop como desde un mando autorizado. Sí mantiene la pantalla
al 100%; No restaura la bajada al 20% a los 20 segundos y al 0% al minuto.
Cambiar de modo despierta la pantalla y comienza un nuevo periodo de inactividad.
La salida HDMI conserva su control independiente.

La selección se guarda como marcador privado `touch-always-on` en el directorio
de estado `orgm-home` del usuario media. Se conserva al reiniciar el agente,
launcher o equipo y no modifica el fondo ni las autorizaciones.

El agente reinicia únicamente `orgm-home-idle`: su wrapper despierta la pantalla
antes de iniciar los temporizadores. El helper de atenuación consulta el marcador
antes de acceder al brillo o a `bl_power`, de modo que las llamadas de los
segundos 20 y 60 no atenúan en modo continuo. Al desactivarlo se retira el marcador
y se reinician los tiempos; tocar sigue despertando la pantalla como antes.

POST `/api/display/touch-always-on` acepta `{"enabled": true}` o false. Exige
sesión autorizada, CSRF y booleano estricto. Si falla el reinicio de la unidad,
el agente revierte la selección guardada. `touch_always_on` en el estado del
mando mantiene el botón sincronizado entre dispositivos.
