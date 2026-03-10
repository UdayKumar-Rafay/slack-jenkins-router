# Slack → Jenkins Pipeline Automation
## Design Document & Implementation Guide

> **Status:** Ready to implement — credentials pending (Monday)  
> **Author:** Uday (SDET, Rafay Systems)  
> **Jenkins:** https://jenkins.qa.rafay-edge.net/  
> **Channel:** #jenkins-runs  

---

## The Problem We're Solving

Right now triggering a regression looks like this:

```
Kalyan:     "can someone run regression on qc? v4.1.x, vikings squad, api"
...silence...
Shobhit:    "anyone free?"
Junior dev: "on it! which params again?"
Kalyan:     "qc, v4.1.x, vikings, api  (same as last time btw 🙄)"
...build runs...
Shobhit:    "someone check results and update confluence pls"
...3 hours later, no update...
```

**The fix:** One slash command. Everything else is automatic.

```
Kalyan: /regression qc v4.1.x vikings api
Bot:    ✅ Build #142 triggered → https://jenkins.qa.rafay-edge.net/job/qc-regression/142
Bot:    Hey @uday — tests done! Please analyse failures & update Confluence 🔗
        cc @kalyan @shobhit
```

---

## Command Anatomy

```
/regression   qc        v4.1.x     vikings    api
     │          │           │          │        │
  run_type  environment  version    squad   interface
```

### Valid Values

| Param | Valid Values |
|-------|-------------|
| `run_type` | `regression`, `smoke`, `sanity` (comes from the slash command itself) |
| `environment` | `qc`, `stage`, `prod`, `master` |
| `version` | `v4.1.x`, `master`, any semver tag |
| `squad` | `vikings`, `spartans`, `ninjas`, `titans` (expand as needed) |
| `interface` | `api`, `ui`, `mobile` |

---

## Architecture

```
User types slash command in #jenkins-runs
            │
            ▼
    Slack App (slash command)
            │  POST with: command, text, user_name, channel_id
            ▼
    Jenkins Generic Webhook Trigger
    https://jenkins.qa.rafay-edge.net/generic-webhook-trigger/invoke?token=slack-router
            │
            ▼
    ┌─────────────────────────────────┐
    │     Router Job (Job A)          │
    │  - Parses slash command params  │
    │  - Maps squad → assignee        │
    │  - Maps env → target job        │
    │  - Triggers correct pipeline    │
    │  - Posts result back to Slack   │
    └─────────────────────────────────┘
            │
            ▼
    ┌─────────────────────────────────┐
    │   Target Pipeline (Job B/C/D)   │
    │  - Actual regression/smoke run  │
    │  - Sends email on completion    │
    │  - Reports status back          │
    └─────────────────────────────────┘
            │
            ▼
    Slack notification in #jenkins-runs
    @assignee tagged for analysis + Confluence update
    cc @kalyan @shobhit for oversight
```

---

## What's Needed (Credentials & Setup)

### Jenkins Credentials to Add
Go to: **Manage Jenkins → Credentials → System → Global → Add Credentials**

| Credential ID | Kind | Value | Notes |
|---|---|---|---|
| `SLACK_BOT_TOKEN` | Secret text | `xoxb-...` (new token) | From Slack App → OAuth & Permissions |
| `SLACK_SIGNING_SECRET` | Secret text | signing secret | From Slack App → Basic Information |

### Jenkins Plugins to Install
Go to: **Manage Jenkins → Plugins → Available**

- [x] `Generic Webhook Trigger` — allows Slack to POST directly to Jenkins
- [x] `Slack Notification` — allows Jenkins to post back to Slack

### Jenkins Global Slack Config
Go to: **Manage Jenkins → System → Slack section**

- Workspace: `rafay` (your Slack workspace)
- Credential: `SLACK_BOT_TOKEN`
- Default channel: `#jenkins-runs`
- Click **Test Connection** → should say Success

### Slack App Config
Go to: **https://api.slack.com/apps → your app**

Set Request URL for each slash command to:
```
https://jenkins.qa.rafay-edge.net/generic-webhook-trigger/invoke?token=slack-router
```

Slash commands to create:
- `/regression`
- `/smoke`
- `/sanity`

Bot Token Scopes needed (OAuth & Permissions):
- `chat:write`
- `commands`

---

## The Router Job (Jenkinsfile.router)

> This is the heart of the system. Create a new Jenkins Pipeline job called `slack-router` and point it at `Jenkinsfile.router` in this repo.

See `Jenkinsfile.router` in this repo for the full implementation.

---

## Squad → Assignee Mapping

Update this map in `Jenkinsfile.router` with real Slack user IDs:

```groovy
def squadMap = [
    "vikings":  ["@uday",   "@priya"],
    "spartans": ["@arjun",  "@meera"],
    "ninjas":   ["@rahul",  "@divya"],
    "titans":   ["@kiran",  "@sana"],
]
```

To get a Slack user ID: click their profile → three dots → Copy member ID (starts with `U`)

For tagging to work in Slack, use `<@UXXXXXXXX>` format instead of `@username`.

---

## Environment → Job Mapping

Update this map to match your actual Jenkins job names:

```groovy
def jobMap = [
    "qc":     "regression-qc",
    "stage":  "regression-stage",
    "prod":   "regression-prod",
    "master": "regression-master",
]
```

---

## The Notification Format

What the team sees in #jenkins-runs after a build:

```
Jenkins Bot APP  9:47 AM

✅  Build #142 — PASSED
🌿  Env: QC  |  v4.1.x  |  vikings  |  api
⏱  Duration: 14m 32s
🔗  https://jenkins.qa.rafay-edge.net/job/regression-qc/142

Hey @uday — tests are done 👇
Can you:
  1. Analyse the results
  2. Update the Confluence page
  3. Flag any failures in this thread

cc @kalyan @shobhit 👀
```

---

## Optional: Claude as Channel Helper

Add Claude to `#jenkins-runs` as a Slack bot to answer questions like:
- "which squads are valid?"
- "what's the command format?"
- "explain this failure to me"

This uses the existing Claude Team plan — no extra cost.
Setup: Create a separate Slack app with Claude API integration, add to channel.
This is a Phase 2 nice-to-have, not required for core functionality.

---

## Monday TODO Checklist

- [ ] Get Jenkins admin access (or ask DevOps to add credentials)
- [ ] Add `SLACK_BOT_TOKEN` to Jenkins credentials
- [ ] Add `SLACK_SIGNING_SECRET` to Jenkins credentials  
- [ ] Install `Generic Webhook Trigger` plugin
- [ ] Install `Slack Notification` plugin
- [ ] Configure Slack in Jenkins global settings + test connection
- [ ] Create new Jenkins Pipeline job called `slack-router`
- [ ] Point it at `Jenkinsfile.router` in this repo
- [ ] Update squad → assignee map with real Slack user IDs
- [ ] Update env → job map with real Jenkins job names
- [ ] Update Slack app slash command URLs to Jenkins webhook URL
- [ ] Do a test run: `/regression qc v4.1.x vikings api`
- [ ] Verify Slack notification fires with correct @tag
- [ ] Show Kalyan 🎉

---

## Estimated Build Time

| Phase | Time | Who |
|---|---|---|
| Credentials + plugin setup | 45 mins | You + DevOps |
| Router Job wired up + first test | 2–3 hrs | Claude writes, you supervise |
| Notification + squad tagging working | 1–2 hrs | Claude writes, you supervise |
| Edge cases + polish | 1–2 hrs | Claude writes, you supervise |
| **Total** | **~1 day** | |

Your hands-on time: ~2–3 hours total across the day.
