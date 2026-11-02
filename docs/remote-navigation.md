# Mando por aplicación — 2026-11-01

Estado: implementación local preparada. No se ha conectado ni modificado la
sesión multimedia de Jarq durante esta tarea. La compilación se hace en una
copia temporal de Lenovo, sin activar sistemas ni tocar su checkout habitual.

## Incluido

- Seis accesos permanentes, Buscar y Play/Pausa en el mando del teléfono.
- Selección espacial en Chrome con borde visible y OK/Enter contextual.
- Perfiles actualizables para Netflix, Disney+, Max y Crunchyroll.
- Búsqueda nativa de VacuumTube y Spotify; MPRIS de Spotify conservado.
- Transporte CDP limitado a localhost y página enfocada; API autenticada existente.
- Pruebas de transporte real Chromium, selección/activación, selectores por
  servicio con fixtures, errores y acceso al endpoint autenticado.

## Pendiente para esta entrega

1. Avisar antes de aplicar en Jarq y acordar una pausa en el uso de la sala.
2. Publicar/fijar la revisión de aplicación en el flake NixOS y compilar la
   generación definitiva en Lenovo antes de transferirla.
3. Desplegar sin reiniciar el equipo. Los agentes/launcher pueden reiniciarse;
   las webapps abiertas necesitan reabrirse para habilitar su canal de control.
4. Validar Netflix, Disney+, Max y Crunchyroll con sus sesiones reales: catálogo,
   perfiles, filas, detalles, buscador, resultados, Enter, atrás y reproducción.
   Los fixtures no prueban el DOM actual del proveedor ni su DRM.
5. Ajustar selectores y soportar reproductores en iframe si los utiliza la sesión
   real (especialmente Crunchyroll). No declarar compatibilidad sin comprobarlo.
6. Confirmar Buscar dentro de reproducción en VacuumTube: upstream tiene reportes
   sobre S durante un video. Confirmar Ctrl+L en la versión instalada de Spotify.
7. Verificar teléfono: seis accesos, búsqueda con tildes, Play/Pausa, cambio de
   aplicación y conservación de la música y autorizaciones.

## Otros pendientes identificados en los informes anteriores

- La duplicación AirPlay tuvo aceptación de imagen estable; enviar un video de
  YouTube mediante AirPlay no tiene aceptación de imagen+audio. Son flujos distintos.
- DIAL de YouTube fue probado en el servidor; falta confirmación concluyente del
  teléfono reproduciendo por ese destino, sin confundirlo con AirPlay. Enviar un
  enlace YouTube sí tiene aceptación documentada.
- Max tiene envío de enlaces; no es receptor Google Cast certificado.
- DRM/resolución y las cuentas comerciales necesitan validación por servicio.

No se atribuye al estado actual del hardware un fallo que solo figure en un
informe anterior. HTTPS, autorización de dispositivos y enlace rápido YouTube
constan implementados y no se presentan como pendientes.

## Referencias

- VacuumTube (interfaz TV para YouTube): https://github.com/shy1132/VacuumTube
- Protocolo de Chrome: https://chromedevtools.github.io/devtools-protocol/
- Atajos de Spotify: https://support.spotify.com/us/article/keyboard-shortcuts/

No se encontró una referencia guardada que identifique con certeza el otro
proyecto mencionado en la conversación. VacuumTube resuelve YouTube; no se afirma
que resuelva automáticamente Netflix, Disney+, Max ni Crunchyroll.

## Evidencia de preparación

- Suite Nix en Lenovo: 255 pruebas aprobadas.
- Chromium aislado: transporte CDP real, selección en cuatro direcciones, OK,
  búsqueda y reproducción con los cuatro perfiles de fixtures aprobados.
- Mando en navegador: 133 acciones, escritorio y teléfono, sin errores JavaScript.
- Paquete Nix construido y derivación de `jarq-multimedia` evaluada en Lenovo.
- El sistema completo aún no se ha compilado para despliegue ni se ha activado.
- Cambios todavía sin commit/push y pin NixOS sin modificar.
