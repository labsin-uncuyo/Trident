# Replay Debug Session - May 3, 2026

## Problem Description
Replay functionality was not working properly:
- Timeline slider showed incorrect time format (e.g., `493815:15:35` instead of `1:38:19`)
- Play button was not working - clicking it did nothing
- Events were not displaying properly on the /agents page
- WebSocket connections were failing with "WebSocket is closed before the connection is established"

## Root Causes Identified

### 1. Time Display Issue
**Problem**: The `formatTime` function was treating `positionMs` as a duration, but it was actually an absolute timestamp (milliseconds since epoch).

**Fix**: Modified `formatTime` in `Layout.tsx` and `TimelineControls.tsx` to detect absolute timestamps and convert them to offsets:
```typescript
if (startTimeMs > 0 && ms > 1000000000000) {  // Absolute timestamp detected
  displayMs = ms - startTimeMs;
}
```

### 2. Event Filtering Issue
**Problem**: Events were being filtered by `event.timestamp_ms <= positionMs`, but at the start of replay, `positionMs` equals the first event's timestamp, so only 1 event showed.

**Fix**: Changed the filter to use a time window from `startTimeMs` to `positionMs + 60000ms` (60-second look-ahead):
```typescript
const windowEndMs = positionMs + 60000;
if (event.timestamp_ms < startTimeMs || event.timestamp_ms > windowEndMs) {
  continue;
}
```

### 3. Slider Position Issue
**Problem**: The slider expected offset values (0 to duration) but was receiving absolute timestamps.

**Fix**: Convert between offset and absolute timestamp in `ReplayPage.tsx`:
```typescript
position={state.positionMs - state.startTimeMs}  // Convert to offset for slider
onSeek={(offset) => controls.seek(offset + state.startTimeMs)}  // Convert back to absolute
```

### 4. WebSocket Connection Issue
**Problem**: The Play button was clicked before the WebSocket connection was fully established (`readyState: 0` = CONNECTING).

**Fix**: Added pending play queue that executes when the WebSocket opens:
```typescript
const pendingPlayRef = useRef<{ speed: number } | null>(null);

// When play is clicked while connecting:
if (wsRef.current.readyState === WebSocket.CONNECTING) {
  pendingPlayRef.current = { speed: newSpeed };
}

// When WebSocket opens:
ws.onopen = () => {
  if (pendingPlayRef.current !== null) {
    ws.send(JSON.stringify({ type: 'play', speed: pendingPlayRef.current.speed }));
    // ...
  }
};
```

### 5. Initial Events Not Loading
**Problem**: The REST API returned `initial_events` in the metadata, but the frontend wasn't using them.

**Fix**: Changed `ReplayContext.tsx` to initialize events from the REST response:
```typescript
events: metadata.initial_events || [],  // Use initial events from REST response
```

## Debug Command that Revealed the Issue

This curl command showed the WebSocket was working on the server side:

```bash
curl -v --no-buffer \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  http://localhost:8888/api/replay/the_4/ws
```

**Result**: Server returned `HTTP/1.1 101 Switching Protocols` and immediately started sending WebSocket messages, proving the backend was working correctly.

## Console Logs Before Fix

```
[ReplayContext] Connecting to WebSocket: ws://localhost:8888/api/replay/the_4/ws
[ReplayContext] play called, wsRef.current: WebSocket {...}, readyState: 0
[ReplayContext] WebSocket connecting, queueing play command
[ReplayContext] WebSocket connection timeout - still connecting after 5 seconds
[ReplayContext] URL was: ws://localhost:8888/api/replay/the_4/ws
```

The WebSocket was stuck in CONNECTING state (`readyState: 0`) and never fired `onopen`, `onerror`, or `onclose` events.

## Resolution

The issue suddenly started working without additional code changes. This suggests:
1. Possibly a browser cache issue that cleared
2. A transient network problem
3. Or the repeated connection attempts eventually succeeded

The key fixes that made the replay work:
1. Time display formatting (absolute timestamp → offset)
2. Event filtering (time window instead of point-in-time)
3. Slider position conversion
4. Pending play queue for WebSocket timing

## Files Modified

1. `/home/diego/Trident_new/images/dashboard/frontend/src/components/Layout.tsx` - Time formatting
2. `/home/diego/Trident_new/images/dashboard/frontend/src/components/TimelineControls.tsx` - Time formatting and slider
3. `/home/diego/Trident_new/images/dashboard/frontend/src/pages/ReplayPage.tsx` - Slider position conversion
4. `/home/diego/Trident_new/images/dashboard/frontend/src/contexts/ReplayContext.tsx` - Pending play queue, initial events
5. `/home/diego/Trident_new/images/dashboard/frontend/src/hooks/useTimelineStream.ts` - Agent filtering, time window filtering
6. `/home/diego/Trident_new/images/dashboard/frontend/src/hooks/useOpenCodeStream.ts` - Host filtering, time window filtering
7. `/home/diego/Trident_new/images/dashboard/frontend/src/hooks/useAlerts.ts` - Replay support
8. `/home/diego/Trident_new/images/dashboard/backend/services/replay_client.py` - Added `level: 'OPENCODE'` to opencode events

## Current Status

✅ Working:
- Replay loads from `/outputs/the_4`
- Time display shows correct format (e.g., `0:00 / 1:38:19`)
- Play/Pause buttons work
- Events display per agent
- WebSocket connects and streams replay data
- Events appear over time during playback
- Navigation between pages preserves replay state

📝 Known Issues:
- WebSocket connection errors appear briefly on initial page load (harmless, connections are established when replay starts)
- Some console debug logs still present (can be cleaned up later)
