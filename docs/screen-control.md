# Pantalla ligera

En Mando → Pantalla se pide una captura de la salida Sway enfocada. Tocar la
imagen envía un clic izquierdo a ese punto, actualiza la imagen y conserva la
aplicación abierta. Volver al mando termina la actualización y elimina la captura.
Se puede ampliar la página o girar el teléfono para apuntar con más precisión.

Por defecto hay una imagen fija. Actualizar pide otra; Auto cada 2 s es opcional
y se pausa cuando la pestaña deja de estar visible. No se captura audio ni se
mantiene un stream. JPEG de calidad 55, escala máxima 0,5 y lado máximo aproximado
1024 px; una sola imagen vigente y un límite de una captura cada 750 ms.

La imagen y el clic requieren el mismo mando autorizado y el CSRF existente para
las mutaciones. No hay un servicio ni puerto adicionales. Una captura tiene un
identificador temporal de 30 s. El clic lleva coordenadas normalizadas de la
imagen y comprueba que no hayan cambiado ventana, salida, escala o rotación.
Los botones siempre se liberan aunque falle una operación. La captura privada
vive en el directorio compartido de previews; su ruta no se expone por archivos
estáticos ni por las tarjetas de aplicaciones.

Implementación: grim para la imagen y cursor/BTN_LEFT de Sway IPC para la entrada.
Referencias: https://github.com/emersion/grim/blob/master/grim.1.scd y
https://github.com/swaywm/sway/blob/master/sway/sway-input.5.scd.
No es un receptor RFB/VNC ni ofrece arrastre; esta entrega resuelve ver, hacer un
clic y volver. El vídeo protegido puede tener restricciones de captura del proveedor.

Pruebas: límites y coordenadas, cambio de contexto, caducidad/identidad,
autorización, CSRF, liberación del botón, entrada/salida de la vista y ausencia
de capturas periódicas después de salir. tests/screen_session.py localiza un
botón en el JPEG de una sesión Sway aislada y lo activa por la ruta nativa real.
Los datos de latencia de esa sesión son sintéticos y no certifican Jarq físico.
