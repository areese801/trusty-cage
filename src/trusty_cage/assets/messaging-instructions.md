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

### progress_update
Send periodically during long tasks so the host knows you're working.
```bash
cage-send progress_update '{"status":"running tests","detail":"3 of 5 passing"}'
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

## Checking for Responses

The host can send messages to your inbox. Check it with:
```bash
ls ~/.cage/inbox/ 2>/dev/null && cat ~/.cage/inbox/*.json 2>/dev/null
```

## Rules

1. **Always send `task_complete`** when you are done, with `exit_code` 0 for success or non-zero for failure.
2. Send `progress_update` at least every few minutes during long tasks.
3. If you encounter a blocker you cannot resolve, send `error` with `recoverable: true` and then `going_idle`.
