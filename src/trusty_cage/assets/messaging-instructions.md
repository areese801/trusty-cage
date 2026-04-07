# Cage Messaging Instructions

You are running inside a trusty-cage container. Use the `cage-send` command to communicate status back to the host.

## Sending Messages

```bash
cage-send <type> '<json_payload>'
```

## Message Types

### task_complete (REQUIRED when done)
Always send this when your work is finished, whether successful or not.
```bash
cage-send task_complete '{"summary":"Implemented feature X and added tests","exit_code":0}'
cage-send task_complete '{"summary":"Failed: missing dependency ffmpeg","exit_code":1}'
```

### progress_update (REQUIRED every 3 minutes during long tasks)
You MUST send a `progress_update` at least every 3 minutes while working. If the host does not hear from you for more than 5 minutes, it will assume you are stuck. Include what you are currently doing and any measurable progress.
```bash
cage-send progress_update '{"status":"running tests","detail":"3 of 5 passing"}'
cage-send progress_update '{"status":"implementing feature","detail":"refactored 2 of 4 modules"}'
```

### error
Report errors that may need host intervention.
```bash
cage-send error '{"error_type":"missing_dep","message":"need ffmpeg installed","recoverable":true}'
```

### info_request
Ask the host for information you don't have access to.
```bash
cage-send info_request '{"request_id":"req-001","description":"Need the production database schema","paths":[]}'
```

### going_idle
Signal that you have no more work to do but haven't completed the task.
```bash
cage-send going_idle '{"reason":"Waiting for host to provide API credentials"}'
```

## Waiting for Responses

After sending `task_complete`, the host may send revised instructions. Use `cage-wait` to block until a message arrives:
```bash
cage-wait
```
This polls your inbox with adaptive intervals and prints the message JSON when one arrives. If no message arrives within 2 hours, it prints `POLL_TIMEOUT`.

For one-off inbox checks (e.g., after `info_request`):
```bash
ls ~/.cage/inbox/ 2>/dev/null && cat ~/.cage/inbox/*.json 2>/dev/null
```

## Rules

1. **Always send `task_complete`** when you are done, with `exit_code` 0 for success or non-zero for failure.
2. **You MUST send `progress_update` at least every 3 minutes** during long tasks. If you don't, the host will assume you are stuck and may interrupt your work.
3. If you encounter a blocker you cannot resolve, send `error` with `recoverable: true` and then `going_idle`.
