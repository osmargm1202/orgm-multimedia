# Una barra de entrada para el mando

La barra vive en el mando, debajo del nombre de la app, y acompaña a la vista
Pantalla ligera. Se retiraron las pantallas «Escribe desde aquí» y de búsqueda
separada. Videos locales conserva su sección propia; los enlaces siguen entrando
por Enviar contenido a Jarq.

- «Buscar en YouTube/Netflix/…»: Enter abre el buscador configurado de esa app,
  introduce la consulta y la envía. La lupa fuerza este modo y enfoca la barra
  inmediatamente para abrir el teclado del teléfono desde el gesto del usuario.
- «Campo seleccionado · …»: al seleccionar un input editable de una webapp
  Chromium, la misma barra reemplaza su texto y envía Enter. El botón Teclado
  enfoca esa barra, sin abrir otra pantalla genérica.
- En Inicio permanece deshabilitada hasta abrir una app. Una webapp sin alias
  de búsqueda acepta escritura cuando detecta un campo enfocado.

La detección consulta la página enfocada del perfil privado de cada webapp por
CDP, sin leer valores existentes. Incluye inputs, textarea, contenteditable y
shadow DOM abierto; los marcos de terceros no se recorren en esta entrega. Los
rectángulos de campos en fullscreen acompañan a la captura para enfocar la barra
sin esperar la respuesta del clic. Ese foco ocurre dentro del gesto, necesario
para los teclados móviles. Si no hay rectángulo disponible o el navegador del
móvil bloquea el foco automático, se toca directamente la barra una vez detectado
el campo. El teclado del SO no puede certificarse con un navegador de escritorio.

La escritura se envía al pulsar Buscar/Enter; no se transmite cada carácter.
El borrador permanece asociado a su app/campo, aunque la detección periódica
cambie. Si la ventana, campo, documento o token cambian, el servidor rechaza
el envío; no lo convierte silenciosamente en una búsqueda de otra app.
Se usan tokens temporales de cinco minutos, sesión autorizada, CSRF y límites
por petición. No se devuelve el texto de campos, incluidos los de contraseña.
El campo del teléfono se vacía al enviar, cambiar de app o perder la sesión.

En las webapps se usa Input.insertText y Enter real sobre el elemento enfocado.
La integración del buscador comprueba que llegó a un input, en vez de declarar
éxito por haber pulsado un icono. YouTube/VacuumTube y Spotify usan sus accesos
al buscador y el teclado nativo persistente de Jarq; no usan Ctrl+V ni cambian
el keymap con procesos de teclado efímeros. Comparten el mapa latam de la barra
de la laptop, con acentos y signos españoles. Los caracteres ajenos a ese mapa
se rechazan antes de empezar a escribir en esas dos apps; las webapps CDP admiten
Unicode. Los alias dependen de las integraciones de cada servicio y de su sesión.

La detección adicional se consulta solo con el mando o Pantalla visibles y la
pestaña activa. La captura conserva su política de detenerse al salir. No hay
servidores nuevos ni puertos públicos de depuración.
