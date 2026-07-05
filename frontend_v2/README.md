# MiNi Frontend v2 Debug UI

A simple backend testing UI for MiNi.

## Features

- View sessions
- Create/delete/select sessions
- Send simple chat messages
- Upload data-owner approval images/PDFs
- Validate uploaded approval files
- See backend debug state after each action
- Inspect raw API responses, session fields, resources, and helper state

## Run

Start backend from `backend_v3`:

```powershell
python -m uvicorn api:app --host 0.0.0.0 --port 8000
```

Start this frontend:

```powershell
cd frontend_v2
npm install
npm run dev
```

Open http://localhost:5174.

## API base

Defaults to `http://localhost:8000`. Override with:

```powershell
$env:VITE_API_BASE="http://localhost:8000"
npm run dev
```
