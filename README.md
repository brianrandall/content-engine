# Content Engine

Automated faceless short-form video production and publishing pipeline.

## What It Does

The system discovers current topics, researches them, generates short-form videos, and publishes completed videos to Instagram and YouTube.

Production is split into two modes:

- `pipeline.py` — one video
- `pipeline_batch.py` — four-video batch

Publishing is separated into independently testable modules:

- `app/publish_instagram.py`
- `app/publish_youtube.py`

Telegram provides remote scheduler control, status, and publication notifications.

---

## 1. Setup

The project uses a dedicated Python virtual environment named `contentVenv`.

Activate it from the project directory:

```bash
source contentVenv/bin/activate
```

---

## 2. Start Everything

The normal entry point is:

```bash
./run.sh
```

`run.sh` is responsible for exactly these services:

1. Tailscale Funnel availability check
2. `app.media_server`
3. `app.telegram_bot`
4. The production scheduler

It does **not** create or manage production directories. The production pipelines handle their own output structure.

The media server and Telegram bot run in the background. The scheduler remains attached to the terminal when `run.sh` is started manually, so keep that terminal open if you want the schedule to continue.

### Scheduler

The schedule repeats every day:

```text
10:00 AM  → pipeline_batch  (4 videos)
4:00 PM   → pipeline         (1 video)
10:00 PM  → pipeline         (1 video)
4:00 AM   → pipeline         (1 video)
```

The scheduler is anchored to local Mac time. It prevents duplicate scheduler instances.

---

## 3. Telegram Controls

The Telegram bot runs independently of the production scheduler.

### `/run`

```text
/run
```

Starts `./run.sh` in the background if the scheduler is not already running.

If the scheduler is already running, the existing scheduler PID is reported instead of starting another copy.

### `/stop`

```text
/stop
```

Stops the scheduler.

The media server and Telegram bot remain running.

If `/run` started the scheduler, `/stop` also terminates an in-progress scheduled pipeline child so production is not left running behind the stopped scheduler.

### `/status`

```text
/status
```

Reports Telegram status, scheduler status/PID, local LLM status, and publishing status.

### `/runlocal`

```text
/runlocal
```

Runs the legacy direct local production/test path without publishing.

### Other commands

```text
/research <topic>
```

Searches the web and sends the research through local Ollama.

```text
/content <topic>
```

Researches a topic and generates a content package.

```text
/ask <question>
```

Sends a question to local Ollama.

---

## 4. Automatic Telegram Publication Notifications

Scheduled production runs do **not** need to be started from Telegram in order to send notifications.

The notification layer is:

```text
app/telegram_notify.py
```

After a scheduled production run, the notification reports the videos created and the publication results, including platform permalinks when available.

The intended notification contents are:

```text
Videos created

Title 1
Title 2
...

Instagram publish complete
<permalink(s)>

YouTube publish complete
<permalink(s)>
```

The notification system reads each video's `manifest.json` and reports successful and failed publication states independently of video generation.

The Telegram notification destination is stored in a temporary chat-ID file used by the running system. A chat ID can also be supplied through the `CONTENT_ENGINE_TELEGRAM_CHAT_ID` environment variable.

---

## 5. Run the Single-Video Pipeline

Normal run:

```bash
python3 -m app.pipeline
```

The pipeline discovers a current trend, researches it, generates the video, and publishes it to both platforms.

### Troubleshooting flags

Disable Instagram publishing:

```bash
python3 -m app.pipeline --noinstagram
```

Disable YouTube publishing:

```bash
python3 -m app.pipeline --noyoutube
```

Disable both publishers:

```bash
python3 -m app.pipeline --noinstagram --noyoutube
```

These flags disable publishing only. Video production continues normally.

---

## 6. Run the Four-Video Batch

Normal batch:

```bash
python3 -m app.pipeline_batch
```

The batch collects trends once, selects four topics, produces four videos, and publishes them.

### Troubleshooting flags

```bash
python3 -m app.pipeline_batch --noinstagram
```

```bash
python3 -m app.pipeline_batch --noyoutube
```

```bash
python3 -m app.pipeline_batch --noinstagram --noyoutube
```

Again, these flags affect publishing only.

---

## 7. Publish an Existing Video to Instagram

The Instagram publisher is intentionally standalone so publishing can be tested without rerunning production.

```bash
python3 -m app.publish_instagram "/path/to/final_short.mp4"
```

It locates the video's manifest and uses the media server/Tailscale Funnel URL to make the video available to Instagram.

---

## 8. Publish an Existing Video to YouTube

The YouTube publisher is also standalone:

```bash
python3 -m app.publish_youtube "/path/to/final_short.mp4"
```

It reads the video's manifest for title/metadata and uploads the video.

Eligible vertical short-form uploads are categorized by YouTube as Shorts after processing.

---

## 9. Troubleshoot Publishers Independently

If video generation succeeds but publishing fails, **do not rerun the entire production pipeline.**

Test Instagram directly:

```bash
python3 -m app.publish_instagram "/path/to/final_short.mp4"
```

Test YouTube directly:

```bash
python3 -m app.publish_youtube "/path/to/final_short.mp4"
```

This separation is intentional: generation and publication can be debugged independently.

---

## 10. Verify Services

Check the media server:

```bash
ps -axo pid=,command= | grep 'app.media_server' | grep -v grep
```

Check Telegram:

```bash
ps -axo pid=,command= | grep 'app.telegram_bot' | grep -v grep
```

Check Tailscale Funnel:

```bash
tailscale funnel status
```

Check scheduler PID:

```bash
cat /tmp/content-engine-scheduler.pid
```

Check whether the scheduler PID is alive:

```bash
kill -0 "$(cat /tmp/content-engine-scheduler.pid)"
```

---

## 11. Logs

Media server:

```text
/tmp/content-engine-media-server.log
```

Telegram bot:

```text
/tmp/content-engine-telegram-bot.log
```

Scheduler:

```text
/tmp/content-engine-scheduler.log
```

Useful commands:

```bash
tail -50 /tmp/content-engine-media-server.log
```

```bash
tail -50 /tmp/content-engine-telegram-bot.log
```

```bash
tail -50 /tmp/content-engine-scheduler.log
```

---

## 12. Output Structure

Production output lives under:

```text
output/runs/
```

Each production run contains one or more video directories. Completed videos normally end in:

```text
final_short.mp4
```

Each video directory also contains:

```text
manifest.json
```

The manifest stores metadata and publication state used by the publisher and notification layers.

---

## 13. Typical Daily Workflow

### Start from the terminal

```bash
source contentVenv/bin/activate
./run.sh
```

Leave the terminal open while the scheduler is running in the foreground.

### Start the scheduler from Telegram

If the media server and Telegram bot are already running:

```text
/run
```

The scheduler is then detached and continues in the background.

### Stop the scheduler

```text
/stop
```

### Check everything

```text
/status
```

---

## 14. Manual Production Reference

### Single

```bash
python3 -m app.pipeline
```

### Single, no Instagram

```bash
python3 -m app.pipeline --noinstagram
```

### Single, no YouTube

```bash
python3 -m app.pipeline --noyoutube
```

### Single, no publishing

```bash
python3 -m app.pipeline --noinstagram --noyoutube
```

### Batch

```bash
python3 -m app.pipeline_batch
```

### Batch, no Instagram

```bash
python3 -m app.pipeline_batch --noinstagram
```

### Batch, no YouTube

```bash
python3 -m app.pipeline_batch --noyoutube
```

### Batch, no publishing

```bash
python3 -m app.pipeline_batch --noinstagram --noyoutube
```

---

## 15. Telegram Quick Reference

```text
/run
Start ./run.sh + scheduler

/stop
Stop scheduler; leave media server and Telegram bot running

/status
Show Telegram, scheduler, LLM, and publishing status

/runlocal
Legacy direct local test without publishing

/research <topic>
Research a topic with local Ollama

/content <topic>
Generate a content package

/ask <question>
Ask local Ollama
```

---

## 16. Troubleshooting Philosophy

The system is deliberately modular.

**Trend/topic selection fails:** troubleshoot the research/trends layer.

**Research or content generation fails:** troubleshoot the research/content pipeline and local Ollama.

**Video generation succeeds but Instagram fails:** run the standalone Instagram publisher.

**Video generation succeeds but YouTube fails:** run the standalone YouTube publisher.

**Telegram stops responding:** inspect the Telegram log first.

**Scheduler fails:** inspect the scheduler log and scheduler PID.

Do not regenerate a successful video merely because a publication step failed.

---

## 17. Operational Notes

- `run.sh` is the service and scheduler entry point.
- `run.sh` does not manage production directories.
- `pipeline.py` produces one video.
- `pipeline_batch.py` produces four videos.
- Instagram and YouTube publishing are separate modules.
- `--noinstagram` and `--noyoutube` are publishing troubleshooting switches.
- `/run` starts the scheduler; it does not duplicate scheduler logic.
- `/stop` stops the scheduler while leaving the media server and Telegram bot running.
- Scheduled runs can notify Telegram independently of an interactive `/run` command.
- YouTube uploads are configured for public visibility.
- Keep the Mac awake and available for scheduled production.
- Do not run multiple copies of `run.sh`.

---

## 18. Phase 1 Status

The current Phase 1 system includes:

- automated trend discovery
- topic ranking/selection
- research and content generation
- single-video production
- four-video batch production
- Instagram publishing
- YouTube publishing
- standalone Instagram publisher
- standalone YouTube publisher
- scheduler
- Telegram remote scheduler controls
- Telegram status reporting
- Telegram publication notifications
- publisher troubleshooting flags

The next major development phase is analytics-driven optimization: collect performance data from active videos, identify patterns in successful content, and use those signals to improve topic selection and content strategy while preserving the core focus on current news and timely stories.
