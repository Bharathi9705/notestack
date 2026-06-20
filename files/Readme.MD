# NoteStack

A fast, keyboard-driven notes workspace with a premium dark enterprise UI. Built with a Flask REST API backend and a single-file vanilla JS frontend — no build step, no framework, no dependencies to install on the client side.

![Theme](https://img.shields.io/badge/theme-dark%20premium-6366F1) ![Backend](https://img.shields.io/badge/backend-Flask-0D1526) ![Frontend](https://img.shields.io/badge/frontend-vanilla%20JS-8B5CF6) ![License](https://img.shields.io/badge/license-MIT-10B981)

## Features

- Create, edit, pin, and delete notes — all without a page refresh
- Live search across titles and content with debounced input
- Filter by All Notes / Pinned
- Six accent colors per note with gradient indicators
- Server-side pagination with "Load more"
- Optimistic UI updates with automatic rollback on failure (pin, delete)
- Light / dark theme toggle, persisted across sessions
- Editable profile name and animation preferences, stored locally
- Keyboard shortcuts: `N` new note, `⌘/Ctrl + K` search, `⌘/Ctrl + Enter` save, `Esc` close
- Fully responsive — collapsible sidebar on mobile

## Tech Stack

**Backend:** Flask, Flask-CORS, SQLite (via `sqlite3`, no ORM)
**Frontend:** Vanilla JavaScript, inline CSS — single `index.html` file, zero build tooling

## Project Structure

```
notestack/
├── app.py              # Flask REST API + app factory
├── index.html           # Complete frontend (HTML + CSS + JS inline)
├── requirements.txt      # Python dependencies
├── notestack.db          # SQLite database (auto-created on first run)
├── README.md
├── LICENSE
└── .gitignore
```

## Getting Started

### Prerequisites
- Python 3.9+

### Installation

```bash
git clone https://github.com/<your-username>/notestack.git
cd notestack
pip install -r requirements.txt
```

### Run

```bash
python app.py
```

Open **http://127.0.0.1:5000** in your browser. The SQLite database (`notestack.db`) is created automatically on first launch.

## API Reference

All responses follow a consistent envelope: `{ "ok": bool, "data" | "error": ..., "meta"?: {...} }`

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/notes/` | List notes — supports `?q=`, `?page=`, `?per_page=`, `?pinned=1` |
| `GET` | `/notes/counts` | Returns `{ all, pinned }` totals |
| `GET` | `/notes/<id>` | Fetch a single note |
| `POST` | `/notes/` | Create a note |
| `PUT` | `/notes/<id>` | Update a note (full replace) |
| `PATCH` | `/notes/<id>/pin` | Toggle pinned state |
| `DELETE` | `/notes/<id>` | Delete a note |
| `GET` | `/health` | Health check |

### Note Schema

```json
{
  "id": 1,
  "title": "string, required, ≤120 chars",
  "content": "string, required, ≤10000 chars",
  "color": "#8B5CF6 | #F43F5E | #10B981 | #F59E0B | #38BDF8 | #EC4899",
  "pinned": false,
  "created_at": "ISO 8601 UTC",
  "updated_at": "ISO 8601 UTC"
}
```

## Design System

- **Background:** `#050816` → `#0B1020` deep navy
- **Accent:** `#6366F1` → `#8B5CF6` indigo-violet gradient
- **Typography:** Plus Jakarta Sans (UI), DM Mono (timestamps/meta)
- Solid enterprise-style surfaces — no glassmorphism, no blur, no glow orbs

## Roadmap Ideas

- Multi-user authentication
- Rich text / markdown note content
- Tags and folders
- Export notes to PDF/Markdown

## License

Released under the [MIT License](LICENSE).