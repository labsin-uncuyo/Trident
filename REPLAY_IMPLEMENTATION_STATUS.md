# Replay Dashboard Implementation Status

## Overview
Implementing a replay feature for the Trident dashboard that allows replaying historical logs with timeline and playback controls. The replay should feed data to existing pages (Agents, Alerts, Traffic) instead of being a separate page.

## Current State

### What Works
- Backend API endpoints are functional:
  - `POST /api/replay/load` - Loads replay metadata and initial events
  - `GET /api/replay/runs` - Lists available runs
  - `GET /api/replay/{replay_id}/events` - Gets events in time range
  - `WS /api/replay/{replay_id}/ws` - WebSocket for playback control

- Backend correctly parses:
  - Timeline JSONL files
  - OpenCode API messages JSON files (legacy and canonical formats)
  - Alerts NDJSON files
  - Timestamps from various formats (ISO, Unix seconds, milliseconds)

- Frontend files created:
  - `contexts/ReplayContext.tsx` - Global replay state management
  - `hooks/useReplay.ts` - Replay hook (now unused, replaced by context)
  - `components/TimelineControls.tsx` - Timeline UI component (unused)
  - `pages/ReplayPage.tsx` - Separate replay page (not used in current approach)

### What Should Work (Based on Implementation)
- Replay context provides global state to all pages
- When replay is active, `useOpenCodeStream` returns replay data instead of live data
- `useTimelineStream` returns replay timeline entries when active
- Layout shows replay controls at bottom when replay is loaded
- Agents page should display replay messages

## Issues Found

### 1. File Permissions in Container
**Problem**: Files copied to container have wrong permissions (`-rw-------` or wrong ownership `1005:1005`)

**Files affected**:
```
/app/backend/routers/replay.py
/app/backend/services/replay_client.py
/app/frontend/dist/* (ownership issue)
```

**Fix attempted**:
```bash
docker exec lab_dashboard chmod 644 /app/backend/routers/replay.py
docker exec lab_dashboard chown -R root:root /app/frontend/dist/
```

**Why not persistent**: Files are copied from host to container on startup or via `docker cp`. The source files on host have correct permissions, but when copied into container they inherit wrong permissions.

**Location of source files**:
- Backend: `/home/diego/Trident_new/images/dashboard/backend/`
- Frontend: `/home/diego/Trident_new/images/dashboard/frontend/dist/`

**Mount point in container**: `/app/`

### 2. Frontend Build Not Persisted
**Problem**: After `docker cp`, changes are lost on container rebuild.

**Reason**: The `docker cp` command copies files into the container's filesystem, but when the container is rebuilt (e.g., `docker compose up --build`), it uses the original image which doesn't include the new files.

**Solution needed**: Either:
1. Mount frontend dist as a volume
2. Rebuild the Docker image
3. Use `docker compose build` to rebuild the image with new files

### 3. Docker Compose Configuration
The dashboard is defined in docker compose and may need to be rebuilt:

```yaml
lab_dashboard:
  image: lab/dashboard:latest
  # This needs to be rebuilt with new code
```

## Files That Need to Be in the Docker Image

### Backend (already copied to container, permissions fixed):
```
images/dashboard/backend/routers/replay.py
images/dashboard/backend/services/replay_client.py
```

### Backend modifications:
```
images/dashboard/backend/app.py - Added replay router import and registration
```

### Frontend (needs to be built into image):
```
images/dashboard/frontend/src/contexts/ReplayContext.tsx (NEW)
images/dashboard/frontend/src/hooks/useReplay.ts (NEW)
images/dashboard/frontend/src/hooks/useOpenCodeStream.ts (MODIFIED)
images/dashboard/frontend/src/hooks/useTimelineStream.ts (MODIFIED)
images/dashboard/frontend/src/components/Layout.tsx (MODIFIED)
images/dashboard/frontend/src/components/TimelineControls.tsx (NEW)
images/dashboard/frontend/src/pages/ReplayPage.tsx (NEW - not used)
images/dashboard/frontend/src/main.tsx (MODIFIED - removed Replay route)
images/dashboard/frontend/src/types/index.ts (MODIFIED - added ReplayEvent types)
images/dashboard/frontend/src/api.ts (MODIFIED - added replay API methods)
images/dashboard/frontend/dist/* (BUILD OUTPUT)
```

## What Needs to Be Done for Persistent Fix

### Option 1: Rebuild Docker Image (Recommended)
```bash
cd /home/diego/Trident_new
docker compose build dashboard
docker compose up -d dashboard
```

This will rebuild the image with all the new code included.

### Option 2: Volume Mount for Development
Add volume mount to docker-compose.yml:
```yaml
volumes:
  - ./images/dashboard/frontend:/app/frontend
```

### Option 3: In-Container Build
```bash
docker exec -it lab_dashboard bash
cd /app/frontend
npm install
npm run build
```

## Current File Permissions Issue

The copied files have:
- User ID 1005 (likely the host user)
- Wrong permissions for the container to read

Fix that works temporarily:
```bash
docker exec lab_dashboard chmod 644 /app/backend/routers/replay.py
docker exec lab_dashboard chmod 644 /app/backend/services/replay_client.py
docker exec lab_dashboard chown -R root:root /app/frontend/dist/
docker compose restart dashboard
```

But this must be done after every container restart/rebuild.

## Summary of Changes Made

### Backend:
1. Created `services/replay_client.py` - Replay data loading service
2. Created `routers/replay.py` - Replay API + WebSocket endpoints
3. Modified `app.py` - Registered replay router

### Frontend:
1. Created `contexts/ReplayContext.tsx` - Global replay state
2. Modified `components/Layout.tsx` - Added replay controls and provider
3. Modified `hooks/useOpenCodeStream.ts` - Return replay data when active
4. Modified `hooks/useTimelineStream.ts` - Return replay timeline when active
5. Modified `pages/AgentsPage.tsx` - Added replay indicator
6. Modified `types/index.ts` - Added replay types
7. Created `components/TimelineControls.tsx` - Timeline UI
8. Created `pages/ReplayPage.tsx` - Standalone replay page (not used)
9. Created `hooks/useReplay.ts` - Replay hook (merged into context)
10. Modified `main.tsx` - Route updates
11. Modified `api.ts` - Replay API methods

## Testing

To verify the replay works after rebuild:
1. Open dashboard at http://localhost:8888
2. Click "Load Replay" at bottom
3. Select a run (e.g., `logs_20260502_170512`)
4. Navigate to /agents page
5. Should see replay messages displayed
6. Use timeline controls (play/pause/seek/speed) to navigate
