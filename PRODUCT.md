# ORGM Home

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

El plan proporcionado fija Python, FastAPI, Uvicorn, Jinja2 y HTML/CSS/JavaScript ligero, sin runtime Node, framework frontend ni base de datos. Nix fija las dependencias en producción; uv.lock fija el entorno de desarrollo.

## Users

Familiares autorizados que usan un teléfono iPhone/Android o un PC para manejar una laptop conectada por HDMI a un proyector.

## Product Purpose

Al encender, mostrar un inicio ORGM Home y permitir abrir, enfocar y controlar las aplicaciones multimedia desde el teléfono, conservando sus sesiones.

## Operating Context

Una sesión Sway dedicada con usuario media sin sudo. La misma aplicación sirve el inicio en Chrome kiosk y el mando responsive. Nginx y cloudflared existentes deben reutilizarse cuando se verifique su ubicación. El usuario solicita el perfil jarq-multimedia en el host Jarq; la topología real todavía debe inspeccionarse.

## Capabilities and Constraints

Catálogo fijo declarado desde NixOS: YouTube/VacuumTube, Spotify, Netflix, Max, Crunchyroll, navegador y mpv. Home recupera el inicio conservando ventanas. Teclas, texto, volumen, archivos locales y enlaces públicos. Capacidades variables por aplicación. Sin panel administrativo, compras, escritorios GNOME/KDE, automatización de credenciales ni segundo túnel. La ampliación final del usuario pide pantallas internas/HDMI duplicadas a 1080p, touch y teclado digital; autoriza reutilizar el teclado existente con una superficie Quickshell local dedicada. El HDMI fijo es HDMI-A-1 y el touch ELAN USB está en la pantalla eDP-1. Cloudflare Access y autenticación/origen obligatorios para el control público. DRM y audio se validan en hardware, sin afirmaciones de compatibilidad previas.

## Brand Commitments

Nombre ORGM Home. No se proporcionaron logotipos ni una identidad visual obligatoria.

## Evidence on Hand

Plan original en docs/phase1-plan.md. El repositorio NixOS conserva configuración y reportes previos del hardware de Jarq. No hay capturas ni medios de reproducción que certifiquen aceptación.

## Open Decisions

El usuario confirma seguir el plan, resolver el diseño y usar botones grandes y texto en español. No se ha establecido una preferencia permanente de flujo visual.

## Product Principles

- El mando debe poder usarse desde el sofá.
- El estado mostrado procede del sistema real.
- Una aplicación abierta se reutiliza.
- Las acciones son fijas y autenticadas.
