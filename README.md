# YouTube Automation — Faceless Channel Pipeline

Generates one short-form (or long-form) video end to end and uploads it to YouTube:

1. **Topic** — pulled from `config/topics.yaml`, or brainstormed by Claude once the queue is empty.
2. **Script** — Claude writes a scene-by-scene script with a hook → connected-facts → insight structure (title, description, tags, narration, visual keywords) - not a bare fact-list, see "Monetization" below for why that distinction matters.
3. **Quality gate** — a cheap heuristic (`quality_check.py`) checks the script has enough substance and the right shape before anything gets published; see below.
4. **Narration** — synthesized with Microsoft Edge's free neural voices (`edge-tts`), with word-level timing.
5. **Visuals** — stock video/photos fetched from Pexels per scene's visual keywords.
6. **Branding** — a consistent intro card (channel name) and outro card (subscribe CTA) get stitched onto every video (`branding.py`).
7. **Assembly** — `ffmpeg` stitches it all together (Ken Burns zoom on stills, scale/crop/loop on video), burns in captions, and mixes narration (+ optional background music).
8. **Thumbnail** — a bold-title thumbnail generated with Pillow.
9. **Upload** — pushed to YouTube via the Data API v3 (OAuth), publishing live by default (`privacy_status: public`) so scheduled runs are truly hands-off; set it to `private`/`unlisted` in `config/channel.yaml` if you'd rather review each video before it goes live.

Everything after step 1 is deterministic code, not another AI call pretending to "run a channel" — you get a real, inspectable video file before anything is uploaded.

## Setup

### 1. Install dependencies

```bash
cd youtube-automation
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

You also need `ffmpeg` on PATH (`apt-get install ffmpeg` / `brew install ffmpeg`).

### 2. API keys

Copy `.env.example` to `.env` and fill in:

- **`ANTHROPIC_API_KEY`** — from [console.anthropic.com](https://console.anthropic.com). Powers script writing and topic brainstorming.
- **`PEXELS_API_KEY`** — free from [pexels.com/api](https://www.pexels.com/api/). Powers stock footage search.

### 3. YouTube OAuth

1. In [Google Cloud Console](https://console.cloud.google.com), create a project, enable the **YouTube Data API v3**, and create an OAuth client of type **Desktop app**.
2. Download the client secret JSON and save it as `youtube-automation/client_secret.json` (or point `YOUTUBE_CLIENT_SECRET_FILE` at it).
3. On the first real run, `run_pipeline.py` opens a browser for you to grant access, then caches a refresh token in `token.json` so future runs (including CI) don't need interactive login.
4. Note: while your OAuth consent screen is in "Testing" mode, only test users you add in Cloud Console can authorize it, and uploaded videos count against a small daily quota (10,000 units/day; one upload ≈ 1,600 units, so roughly 6 uploads/day). Apply for quota increase or verification if you need more.

### 4. Configure the channel

Edit `config/channel.yaml` — niche, tone, target length, voice, video format (`shorts` vs `longform`), upload privacy, etc. Seed `config/topics.yaml` with topic ideas, or leave it empty to let Claude brainstorm from the niche.

## Running it

```bash
# Build a video and review it locally without uploading
python run_pipeline.py --dry-run

# Force a specific topic
python run_pipeline.py --topic "Why octopuses have three hearts" --dry-run

# Real upload, scheduled to go live later
python run_pipeline.py --publish-at 2026-07-15T15:00:00Z
```

Output for each run lands in `output/<timestamp>/`: `final.mp4`, `thumbnail.jpg`, `captions.srt`, `manifest.json`.

## Automating it (GitHub Actions)

`.github/workflows/publish.yml` runs the pipeline on a schedule (default: weekly) or on demand via `workflow_dispatch`. It needs these repo secrets:

| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | same as `.env` |
| `PEXELS_API_KEY` | same as `.env` |
| `YOUTUBE_CLIENT_SECRET_B64` | `base64 -w0 client_secret.json` |
| `YOUTUBE_TOKEN_B64` | `base64 -w0 token.json` (generate this once by running the pipeline locally through the OAuth flow first) |

The workflow commits the updated `config/topics.yaml` / `config/topic_history.json` back to the branch after each run so the topic queue keeps progressing across ephemeral runners. Because a refresh token doesn't expire from use, you generally only need to regenerate `YOUTUBE_TOKEN_B64` if you revoke access or it goes unused for 6+ months.

## Monetization: what this does and doesn't get you

YouTube Partner Program (YPP) eligibility has two independent gates, and this pipeline can only help with one of them.

**Gate 1: the numbers bar.** 1,000 subscribers + 4,000 public watch hours in 12 months, or 1,000 subscribers + 10M Shorts views in 90 days. No code can force this — it depends on real audience growth. Consistent branding (the intro/outro cards) and better retention from more substantial scripts help your odds, but there's no engineering shortcut around it.

**Gate 2: the "reused/duplicative content" policy.** This is the one that specifically targets what a naive version of this pipeline would produce — mass-produced, formulaic slideshows of TTS-over-stock-footage with no added value. This build takes concrete steps against that:

- **Narrative structure, not a fact-list.** The script prompt requires a `hook` scene, 4+ connected `build` scenes with actual transitions ("but here's the twist..."), and a closing `insight` scene that synthesizes *why it matters* — real analysis, not one more trivia item.
- **Consistent channel branding.** Every video opens and closes with the same intro/outro cards (`branding.py`), a concrete "this is a produced show" signal, not a generic template.
- **A quality gate (`quality_check.py`)** runs before every upload: minimum word count, minimum scene count, and the hook/insight structure. A script that fails gets uploaded as `private` (configurable via `quality.fallback_privacy_status`) instead of published live, so a weak episode doesn't go out on autopilot — it waits for you to look at it.

None of this is a guarantee. Whether a specific channel passes YPP review is a human judgment call on YouTube's end, and policy details change. What this pipeline gives you is content that's built to the shape of channels that *do* get monetized, plus a safety valve so bad output doesn't publish itself — not certainty.

Also worth knowing:

- **Accuracy** — the script prompt tells Claude not to fabricate facts, but nothing here fact-checks output. Review scripts periodically, especially in `education`/`science` niches.
- **Stock footage licensing** — Pexels' license permits this kind of use, but always check current Pexels license terms, and avoid keywords likely to surface identifiable people, trademarks, or news footage.
- **`made_for_kids`** — set honestly in `config/channel.yaml`; COPPA compliance is determined by YouTube/FTC rules, not by this flag alone.

## Running this truly unattended ("set and forget")

Two things have to be true for this to actually run without you touching it:

### 1. `privacy_status: public`

Set by default in `config/channel.yaml`. With `private` (the safer starting point), videos upload but sit unpublished until you manually flip them in Studio — that's a manual step, so it isn't hands-off. Switch back to `private`/`unlisted` any time you want a review buffer instead.

### 2. Publish your Google OAuth consent screen (do this once, or automation silently dies in ~7 days)

By default, a newly created OAuth client sits in **Testing** status in Google Cloud Console. Refresh tokens issued while in Testing status **expire after 7 days**, no matter what — so the pipeline would work fine for about a week, then every scheduled run would start failing with an auth error, and nothing would tell you unless you're watching GitHub Actions.

Fix it once:

1. Google Cloud Console → **APIs & Services → OAuth consent screen**.
2. Click **Publish App** to move it from *Testing* to *Production*.
3. Since the app requesting `youtube.upload` isn't formally verified, the one-time browser consent flow will show an **"Google hasn't verified this app"** warning. That's expected for a personal-use script — click **Advanced → Go to \[app name\] (unsafe)** to proceed. You only see this once, when `run_pipeline.py` first opens the browser to mint `token.json`.
4. Regenerate `token.json` after publishing (delete the old one, run the pipeline once locally, complete the consent flow again) — a token minted *before* publishing keeps the old 7-day expiry.

After this, the refresh token is long-lived (effectively indefinite until you revoke access or leave it unused for 6+ months), which is what the scheduled GitHub Actions workflow depends on.

### What's already handled for you

- The topic queue self-refills via Claude brainstorming — it never runs dry.
- A failed run (bad API key, transient network error, quota hit) just skips that week's video; it doesn't corrupt state or require intervention. The topic queue only advances/commits on a fully successful run.
- The quality gate catches thin/malformed scripts and holds them at `private` instead of publishing them live — see "Monetization" above.
- GitHub notifies you by email when a scheduled workflow run fails (default GitHub behavior for repos you watch) — that's your safety net for noticing real problems (expired key, quota exhausted, etc.) without watching it actively.

### What's still on you, even unattended

- YouTube's ~10,000 unit/day API quota (≈6 uploads/day) caps how often you can realistically schedule this — weekly (the workflow default) is comfortably inside it.
- Nothing here fact-checks scripts or guarantees YPP monetization eligibility (see above) — "unattended" means it won't need your hands, not that its output is risk-free to run forever with zero spot-checks.
- Worth periodically skimming a `private`-fallback video in `output/` when the quality gate does trip, both to fix whatever made it fail and to catch anything the gate itself can't judge (factual accuracy, tone).

## Project layout

```
youtube-automation/
  run_pipeline.py            CLI entrypoint
  config/
    channel.yaml              niche, voice, video format, upload settings
    topics.yaml                topic queue (auto-drained, auto-refilled)
    topic_history.json         topics already produced (avoids repeats)
  youtube_automation/
    script_writer.py           Claude script (hook/build/insight) + topic brainstorming
    quality_check.py            pre-upload heuristic gate (word/scene count, structure)
    topic_store.py               queue/history management
    tts.py                        edge-tts narration + word timing
    subtitles.py                   SRT caption generation
    visuals.py                      Pexels stock footage/photo search
    branding.py                      intro/outro channel-identity cards
    fonts.py                          shared bold-font lookup
    assembler.py                       ffmpeg scene assembly + captions + audio mix
    thumbnail.py                        Pillow thumbnail generation
    youtube_uploader.py                  OAuth + resumable upload
    pipeline.py                           orchestrates all of the above
  .github/workflows/publish.yml  scheduled/on-demand CI run
  tests/                          unit tests (config + topic queue logic)
```
