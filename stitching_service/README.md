# BIMA Stitching Engine

This directory vendors the production stitching engine from
`BIMA-TAIL-SITTER/VISION-LIVESTITCH`.

The REST API, WebSocket, and live stream intake now run inside the main Ground
Station backend in `app/routers/stitching.py`. Do not start a separate service
from this directory.

Runtime sessions are stored in `sessions/` by default, or in the path configured
by `STITCH_SESSIONS_DIR`.
