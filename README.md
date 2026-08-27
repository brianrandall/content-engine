# Content Engine

Automated faceless short-form video production and publishing pipeline.

The project currently runs as two production modes:

- `pipeline.py` — produces **one video**.
- `pipeline_batch.py` — produces the **4-video morning batch**.

Both production pipelines can publish completed videos to Instagram and YouTube.

---

## 1. Project Setup

Project directory:

```text
~/Dropbox/PROJECTS/content-engine
```

The project-specific Python virtual environment is:

```text
contentVenv
```

Activate it from the project directory:

```bash
source contentVenv/bin/activate
```

You should then see `(contentVenv)` at the beginning of your shell prompt.

---

# 2. Start Everything

The normal way to start the system is:

```bash
./run.sh
```

`run.sh` handles:

1. Tailscale Funnel availability check.
2. `app.media_server`.
3. `app.telegram_bot`.
4. The production scheduler.

The media server and Telegram bot are kept running in the background.

**The scheduler stays in the foreground when `./run.sh` is launched manually.** Do not close that terminal if you want scheduled production to continue.

The scheduler does not create or manage production directories. `pipeline.py` and `pipeline_batch.py` handle their own output directories.

### Scheduler

The current schedule is anchored to 10:00 AM local Mac time:

```text
10:00 AM  → pipeline_batch      (4 videos)
4:00 PM   → pipeline             (1 video)
10:00 PM  → pipeline             (1 video)
4:00 AM   → pipeline             (1 video)
10:00 AM  → pipeline_batch      (4 videos)
```

So after the morning batch, a single video is produced every six hours until the next morning batch.

`run.sh` prevents a second scheduler instance from being started while one is already running.

---

## 3. Telegram Scheduler Control

The Telegram bot can start and stop the scheduler without opening a terminal.

### `/run`

Send:

```text
/run
```

This starts:

```bash
./run.sh
```

in the background. It starts the scheduler; it does **not** immediately run a production job unless the next scheduled time has arrived.

If the scheduler is already running, `/run` reports the existing scheduler PID instead of starting a duplicate.

### `/stop`

Send:

```text
/stop
```

This stops the scheduler started by `/run`.

The media server and Telegram bot remain running.

If `/run` started the scheduler, `/stop` also terminates an in-progress scheduled pipeline child so a scheduled production job is not left running after the scheduler is stopped.

If `./run.sh` was started manually from a terminal, `/stop` only signals the scheduler process itself rather than risking the terminal's process group.

### `/status`

Send:

```text
/status
```

The bot reports whether the scheduler is running and, when available, its PID.

### Automatic publication notifications

When a scheduled run finishes, the scheduler sends a Telegram report containing each completed video's publication status. Successful YouTube and Instagram uploads include their permalinks when the platform APIs provide them.

The Telegram bot records the chat ID used with `/run` in:

```text
/tmp/content-engine-telegram-chat-id
```

This lets later scheduled jobs notify the same Telegram chat even though the scheduler itself runs independently of the bot's command handler.

---

# 4. Run the Single-Video Pipeline Manually

Normal production run:

```bash
python3 -m app.pipeline
```

This will:

- collect current trends
- select one topic
- research it
- generate the content package
- create the video
- publish the completed video to Instagram
- publish the completed video to YouTube

The output directory is named from the selected topic.

---

## Single Pipeline Troubleshooting Flags

Skip Instagram publishing:

```bash
python3 -m app.pipeline --noinstagram
```

Skip YouTube publishing:

```bash
python3 -m app.pipeline --noyoutube
```

Skip both platforms:

```bash
python3 -m app.pipeline --noinstagram --noyoutube
```

These flags affect publishing only. Video production still runs normally.

---

# 5. Run the Four-Video Batch Manually

Normal batch run:

```bash
python3 -m app.pipeline_batch
```

The batch intentionally produces exactly four videos.

The batch collects trends once, selects four topics, applies the technology-topic diversity cap, then produces and publishes the four videos.

The batch output directory is:

```text
output/runs/<timestamp>_batch/
```

Each video gets its own topic directory underneath the batch directory.

---

## Batch Troubleshooting Flags

Skip Instagram publishing:

```bash
python3 -m app.pipeline_batch --noinstagram
```

Skip YouTube publishing:

```bash
python3 -m app.pipeline_batch --noyoutube
```

Skip both platforms:

```bash
python3 -m app.pipeline_batch --noinstagram --noyoutube
```

Again, these flags only disable publishing. Production continues normally.

---

# 6. Publish an Existing Video to Instagram

Instagram publishing is intentionally available as a standalone module so a failed publisher does **not** require rerunning the entire content pipeline.

Run:

```bash
python3 -m app.publish_instagram "/absolute/path/to/final_short.mp4"
```

Example:

```bash
python3 -m app.publish_instagram "/Users/brianrandall/Dropbox/PROJECTS/content-engine/output/runs/20260827_112049_batch/01_menace_ii_society_actor_dies_at_52_meningitis_claimed_his_li/final_short.mp4"
```

The publisher locates the video's `manifest.json` and uses the media server/Tailscale Funnel URL to make the video available to Instagram.

---

# 7. Publish an Existing Video to YouTube

YouTube publishing is also standalone for easy troubleshooting.

Run:

```bash
python3 -m app.publish_youtube "/absolute/path/to/final_short.mp4"
```

Example:

```bash
python3 -m app.publish_youtube "/Users/brianrandall/Dropbox/PROJECTS/content-engine/output/runs/20260827_112049_batch/04_fed_talks_crypto_bitcoin_eyes_80k_resistance/final_short.mp4"
```

The YouTube publisher reads the video's manifest for its title/metadata and uploads the video.

Vertical short-form videos are uploaded through the normal YouTube video-upload flow; YouTube subsequently categorizes eligible short-form uploads as Shorts after processing.

---

# 8. Test the Publishers Without Running Production

If a video has already been created, **do not rerun the pipeline just to troubleshoot publishing.**

Instagram only:

```bash
python3 -m app.publish_instagram "/path/to/final_short.mp4"
```

YouTube only:

```bash
python3 -m app.publish_youtube "/path/to/final_short.mp4"
```

This makes the publisher components independently testable.

---

# 9. Verify the Services

Check that the media server is running:

```bash
ps -axo pid=,command= | grep 'app.media_server' | grep -v grep
```

Check that the Telegram bot is running:

```bash
ps -axo pid=,command= | grep 'app.telegram_bot' | grep -v grep
```

Check Tailscale Funnel:

```bash
tailscale funnel status
```

Check the scheduler:

```bash
cat /tmp/content-engine-scheduler.pid
```

Then verify that PID is alive:

```bash
kill -0 "$(cat /tmp/content-engine-scheduler.pid)"
```

View scheduler output:

```bash
tail -50 /tmp/content-engine-scheduler.log
```

`run.sh` performs the service checks automatically when it starts.

---

# 10. Telegram Publication Notifications

The scheduled pipelines run independently of the Telegram bot, but publication results are reported back through Telegram after each scheduled run.

The notification layer is:

```text
app/telegram_notify.py
```

It reads completed run manifests and reports:

- video title
- YouTube upload status and permalink
- Instagram upload status and permalink when available
- platform failures without marking a successful video generation as failed

Run the notifier manually for an existing production run if needed:

```bash
python3 -m app.telegram_notify "/path/to/output/runs/<run-directory>"
```

If no Telegram chat ID has been recorded yet, the notifier safely skips the message. Send `/run` from the Telegram bot once to establish the notification destination.

---

# 11. Service Logs

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

View the latest media-server log output:

```bash
tail -50 /tmp/content-engine-media-server.log
```

View the latest Telegram log output:

```bash
tail -50 /tmp/content-engine-telegram-bot.log
```

View the latest scheduler output:

```bash
tail -50 /tmp/content-engine-scheduler.log
```

---

# 12. Output Structure

Production runs live under:

```text
output/runs/
```

Single-video runs use the selected topic in the run directory name.

Batch runs use:

```text
<timestamp>_batch/
```

A completed video normally ends at:

```text
.../final_short.mp4
```

The same video directory contains its:

```text
manifest.json
```

The manifest is used by the publishing components for metadata and publishing state.

---

# 13. Typical Daily Workflow

### Start the system from a terminal

```bash
cd ~/Dropbox/PROJECTS/content-engine
source contentVenv/bin/activate
./run.sh
```

Leave that terminal running when starting `run.sh` manually.

### Or start the scheduler from Telegram

If the media server and Telegram bot are already running:

```text
/run
```

Then the scheduler runs in the background and the terminal does not need to remain open for that scheduler process.

### Scheduler behavior

At 10:00 AM:

```bash
python3 -m app.pipeline_batch
```

At 4:00 PM, 10:00 PM, and 4:00 AM:

```bash
python3 -m app.pipeline
```

The scheduler invokes the virtual-environment Python directly, so scheduled jobs do not depend on the shell currently having `contentVenv` activated.

---

# 14. Manual Production Commands

Single:

```bash
python3 -m app.pipeline
```

Single without Instagram:

```bash
python3 -m app.pipeline --noinstagram
```

Single without YouTube:

```bash
python3 -m app.pipeline --noyoutube
```

Single without either publisher:

```bash
python3 -m app.pipeline --noinstagram --noyoutube
```

Batch:

```bash
python3 -m app.pipeline_batch
```

Batch without Instagram:

```bash
python3 -m app.pipeline_batch --noinstagram
```

Batch without YouTube:

```bash
python3 -m app.pipeline_batch --noyoutube
```

Batch without either publisher:

```bash
python3 -m app.pipeline_batch --noinstagram --noyoutube
```

---

# 15. Telegram Commands

```text
/run
```

Start `./run.sh` and the production scheduler.

```text
/stop
```

Stop the scheduler started by `/run`. Media server and Telegram bot stay online.

```text
/status
```

Show Telegram, scheduler, and direct-run status.

```text
/runlocal
```

Run the legacy direct local-test production path without publishing.

```text
/research <topic>
```

Search the web and send the research to local Ollama.

```text
/content <topic>
```

Research a topic and generate a content package directly through the bot.

```text
/ask <question>
```

Send a question to local Ollama.

---

# 16. Troubleshooting Philosophy

The pipeline is deliberately split into independently testable components.

If **topic selection** fails, troubleshoot the production pipeline.

If **research/content generation** fails, troubleshoot the production pipeline and Qwen/research inputs.

If **video creation** succeeds but Instagram fails, run:

```bash
python3 -m app.publish_instagram "/path/to/final_short.mp4"
```

If **video creation** succeeds but YouTube fails, run:

```bash
python3 -m app.publish_youtube "/path/to/final_short.mp4"
```

If the **scheduler** fails, inspect:

```text
/tmp/content-engine-scheduler.log
```

and verify:

```bash
cat /tmp/content-engine-scheduler.pid
```

Do not regenerate an already-successful video just because a publishing step failed.

---

# 17. Important Operational Notes

- `run.sh` is the long-running service/scheduler entry point.
- `run.sh` does not create production directories.
- `pipeline.py` produces one video.
- `pipeline_batch.py` produces four videos.
- Instagram and YouTube publishers are separate modules.
- `--noinstagram` and `--noyoutube` are production-pipeline troubleshooting switches.
- Telegram `/run` starts `./run.sh`; it does not duplicate the scheduler logic.
- Telegram `/stop` stops the scheduler while leaving media server and Telegram online.
- Scheduled publication results are reported back to the Telegram chat that last used `/run`.
- The scheduler is a foreground shell process when launched manually; when launched by Telegram it is detached into the background.
- Keep the Mac awake/available for scheduled production. The scheduler is not a replacement for a system-level `launchd` service yet.
- Do not start multiple copies of `run.sh`.

---

# 18. Quick Reference

```bash
# Activate environment
source contentVenv/bin/activate

# Start services + scheduler from terminal
./run.sh

# One video
python3 -m app.pipeline

# One video, no Instagram
python3 -m app.pipeline --noinstagram

# One video, no YouTube
python3 -m app.pipeline --noyoutube

# One video, no publishing
python3 -m app.pipeline --noinstagram --noyoutube

# Four-video batch
python3 -m app.pipeline_batch

# Four-video batch, no Instagram
python3 -m app.pipeline_batch --noinstagram

# Four-video batch, no YouTube
python3 -m app.pipeline_batch --noyoutube

# Four-video batch, no publishing
python3 -m app.pipeline_batch --noinstagram --noyoutube

# Publish existing video to Instagram
python3 -m app.publish_instagram "/path/to/final_short.mp4"

# Publish existing video to YouTube
python3 -m app.publish_youtube "/path/to/final_short.mp4"

# Send publication report for an existing run
python3 -m app.telegram_notify "/path/to/output/runs/<run-directory>"

# Check Tailscale Funnel
tailscale funnel status
```

### Telegram quick reference

```text
/run       Start ./run.sh + scheduler
/stop      Stop scheduler
/status    Show system/scheduler status
/runlocal  Legacy direct local test
/research  Research a topic
/content   Generate a content package
/ask       Ask local Ollama
```
