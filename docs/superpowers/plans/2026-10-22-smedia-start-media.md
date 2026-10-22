# Plan — `/smedia` owner command + DB-backed start media

**Date:** 2026-10-22
**Status:** approved (design reviewed in chat)

## Goal

Replace the `START_PIC` environment variable with an owner-only `/smedia` command that
sets the start image or start GIF at runtime, stored in MongoDB so it survives restarts.

## Files

| File | Change |
|---|---|
| `config.py` | remove `START_PIC`; add `ASK_TIMEOUT` (env, default 300) and `MEDIA_NAMES` |
| `database/database.py` | add `get_start_media` / `set_start_media` / `del_start_media` over a `start_media` collection |
| `plugins/smedia.py` | **new** — `/smedia` command, inline menu, media listener, save/remove |
| `helper_func.py` | add `send_start_message()` — sends the saved media (photo / animation / plain text) |
| `plugins/start.py` | use `send_start_message()` instead of `START_PIC` |
| `plugins/useless.py` | **bug fix** — catch-all must not swallow `/commands` (shadowed `/start`) |
| `plugins/channel_post.py` | **bug fix** — add `smedia` to the excluded commands |
| `plugins/cbb.py` | **bug fix** — hand unknown callback data on with `ContinuePropagation` |
| `app.json` | drop the `START_PIC` env entry |
| `README.md` | drop `START_PIC`, document `/smedia` |

## Behaviour

- `/smedia` is owner-only (`OWNER_ID`).
- Menu: `📷 Set Start Image` · `🎬 Set Start GIF` · `🗑 Remove Current` (only when set) · `❌ Close`.
- Choosing image/GIF prompts the owner and waits up to `ASK_TIMEOUT` seconds (default 300).
- A photo or GIF is stored by `file_id`. A file sent as a document is downloaded and
  re-uploaded (Telegram binds a `file_id` to its type, so a document id cannot be used
  as a photo); a non-image document is rejected and the bot keeps waiting.
- Sending the other kind than the one chosen still saves it, with a warning.
- Timeout saves nothing and refreshes the menu.
- `/start` shows the saved media, or plain text when nothing is set.

## Tests

`tests/` (pytest + pytest-asyncio + mongomock-motor):

- `test_start_media_db.py` — save / read / overwrite / delete against an in-memory Mongo
- `test_smedia_media.py` — photo / animation / document classification
- `test_smedia_flow.py` — the whole flow: tap a button, send the media, save it
- `test_start_message.py` — `/start` picks photo vs animation vs text
- `test_filters.py` — `not_command` and the `sm_` callback filter
- `test_dispatch_order.py` — commands reach their own handler, in any file order

Run them with `pip install -r requirements-dev.txt` and `pytest`.

## Bugs found while building this

Pyrofork runs **only the first matching handler per group**
(`pyrogram/dispatcher.py:391` — `break` after one match) and registers handlers
in `os.walk` order, which is filesystem order and not the same on every
machine. Three handlers were greedy enough to swallow other handlers' work:

1. `plugins/useless.py` — a catch-all for every private message, which
   answered `/start`, `/users` and `/broadcast` before their own handler ran.
2. `plugins/channel_post.py` — the admin file-upload handler, which matched
   the owner's `/smedia` (its command exclusion list did not mention it).
3. `plugins/cbb.py` — a catch-all for every callback query, which swallowed
   the `/smedia` menu's own buttons.

All three are fixed, and `tests/test_dispatch_order.py` checks that commands
and callback buttons reach their own handler with the plugin files in any
order.
