# Slack Bot Setup Guide

End-to-end steps to get `/regression`, `/smoke`, and `/sanity` slash commands working in Slack, routing through Lambda to Jenkins, and posting results back to the channel.

---

## Credential ID Note

This guide uses `slackins-bot-token` as the Jenkins credential ID throughout.

**If you want a different ID (e.g. `slackins-bot-token`), you need to change it in two places:**

1. The credential ID itself when creating it in Step 1.
2. Every `slackSend()` call in `Jenkinsfile.router` and `Jenkinsfile.notifier` — find and replace `tokenCredentialId: 'slackins-bot-token'` with your new ID in both files.

The Jenkinsfiles use `tokenCredentialId` inline (not the global config), so each bot has its own explicit credential and they do not interfere with each other.

---

## Step 1 — Create Jenkins Credential

`Manage Jenkins → Credentials → System → Global credentials → Add Credential`

| Field | Value |
|---|---|
| Kind | Secret text |
| Secret | `xoxb-...` (Bot User OAuth Token from Slack app) |
| ID | `slackins-bot-token` *(or your preferred ID — see note above)* |
| Description | Slack bot token for qa-jenkins |

---

## Step 2 — Install Jenkins Plugins

`Manage Jenkins → Plugins → Available` — install if not already present:

| Plugin | Purpose |
|---|---|
| **Generic Webhook Trigger** | Receives the Slack POST and triggers `slack-router` |
| **Slack Notification** | Powers `slackSend()` in router and notifier |
| **Pipeline** | Jenkinsfile pipeline support (likely already installed) |
| **Robot Framework** | Publishes `output.xml`; exposes pass/fail counts |

---

## Step 3 — Configure Slack Notification Plugin (Global)

> **If there is already a Slack credential configured in Jenkins for a different bot — skip this step entirely.** Do not touch the global config or you will break the existing bot's notifications.
>
> The Jenkinsfiles use `tokenCredentialId: 'slackins-bot-token'` inline in every `slackSend()` call, so they are completely independent of the global config.

If there is no existing global config, optionally set it up for convenience:

`Manage Jenkins → Configure System → Slack`

| Field | Value |
|---|---|
| Workspace | your Slack workspace name |
| Default channel | `#jenkins-runs` |
| Credential | select `slackins-bot-token` (created in Step 1) |

Click **Test Connection** — should say `Success`.

---

## Step 4 — Update Lambda Environment Variable

The Lambda proxy is already deployed. Only the Jenkins URL needs updating — no code deploy required.

```bash
aws lambda update-function-configuration \
  --region us-east-1 \
  --function-name slack-jenkins-proxy \
  --environment "Variables={
    JENKINS_WEBHOOK_URL=https://<real-jenkins-url>/generic-webhook-trigger/invoke?token=slack-router,
    ACK_MESSAGE=⏳ On it — triggering now...
  }"
```

Lambda API Gateway URL (give this to Slack slash commands):
```
https://0tx582z14j.execute-api.us-east-1.amazonaws.com/prod/
```

> **Google OAuth note:** If Jenkins rejects the Lambda call with 401/302, the GWT endpoint needs auth.
> Generate an API token from your Jenkins profile (`Profile → Configure → API Token → Add new Token`) and update the URL to:
> `https://your.email@company.com:API_TOKEN@<jenkins-url>/generic-webhook-trigger/invoke?token=slack-router`

---

## Step 5 — Create `slack-router` Pipeline Job

`New Item → Pipeline`

| Field | Value |
|---|---|
| Name | `slack-router` |
| Definition | Pipeline script from SCM |
| SCM | Git |
| Repository URL | `https://github.com/UdayKumar-Rafay/slack-jenkins-router.git` |
| Branch | `main` |
| Script Path | `Jenkinsfile.router` |

Under **Build Triggers → Generic Webhook Trigger**:

| Field | Value |
|---|---|
| Token | `slack-router` |

> JSONPath variable extraction is already configured inside `Jenkinsfile.router` — nothing extra to configure in the job UI.

---

## Step 6 — Create `slack-notifier` Pipeline Job

`New Item → Pipeline`

| Field | Value |
|---|---|
| Name | `slack-notifier` |
| Definition | Pipeline script from SCM |
| SCM | Git |
| Repository URL | `https://github.com/UdayKumar-Rafay/slack-jenkins-router.git` |
| Branch | `main` |
| Script Path | `Jenkinsfile.notifier` |
| Build Triggers | None — triggered programmatically by target pipelines |

---

## Step 7 — Configure Slack Slash Commands

`api.slack.com/apps → qa-jenkins → Slash Commands`

Add (or update) three commands, all pointing to the same Lambda URL:

| Command | Request URL | Description |
|---|---|---|
| `/regression` | `https://0tx582z14j.execute-api.us-east-1.amazonaws.com/prod/` | Trigger regression run |
| `/smoke` | `https://0tx582z14j.execute-api.us-east-1.amazonaws.com/prod/` | Trigger smoke run |
| `/sanity` | `https://0tx582z14j.execute-api.us-east-1.amazonaws.com/prod/` | Trigger sanity run |

Also invite the Slack bot to `#jenkins-runs`:
```
/invite @qa-jenkins
```

---

## Step 8 — Changes in Existing Pipelines (rauto repo)

Four Jenkinsfiles need a `slack-notifier` call added to `post { always { } }`.

> **Important:** Do NOT declare `triggered_by` or `triggered_by_id` in the `parameters {}` block of these pipelines. They are injected by the router via `build(parameters: [...])` and are intentionally hidden from the manual "Build with Parameters" form.

### Files to update

| Jenkins Job | Jenkinsfile path |
|---|---|
| `QC-Staging` | `build/pipeline_qc_stage/Jenkinsfile` |
| `Staging` | `build/pipeline_stage/Jenkinsfile` |
| `Production-Regression` | `build/pipeline_production/regression/Jenkinsfile` |
| `Master-Sanity` | `build/pipeline_master_sanity/Jenkinsfile` |

### What to add in `post { always { } }`

```groovy
post {
    always {
        script {
            // ... your existing sh commands (email, s3 upload, sync-results) stay here ...

            // Read Robot Framework test counts
            def passed = 0
            def total  = 0
            try {
                def robotAction = currentBuild.rawBuild.getAction(hudson.plugins.robot.RobotBuildAction.class)
                if (robotAction) {
                    passed = robotAction.overallPassedCount ?: 0
                    total  = robotAction.overallTotalCount  ?: 0
                }
            } catch (e) { echo "Robot results unavailable: ${e.message}" }

            // Squads onboarded to Slack notifications.
            // - Slack-triggered runs (triggered_by is set): always notify, regardless of squad.
            // - Manual runs: only notify if squad is in this list.
            // Add squads here as rollout expands.
            def slackEnabledSquads = ['vikings', 'alpha', 'avengers', 'mavericks']

            if (params.triggered_by || slackEnabledSquads.contains(params.squad_name?.toLowerCase())) {
                build(
                    job: 'slack-notifier',
                    wait: false,
                    propagate: false,
                    parameters: [
                        string(name: 'build_result',    value: currentBuild.result ?: 'SUCCESS'),
                        string(name: 'build_url',       value: env.BUILD_URL),
                        string(name: 'build_number',    value: env.BUILD_NUMBER),
                        string(name: 'build_duration',  value: currentBuild.durationString),
                        string(name: 'squad_name',      value: params.squad_name),
                        string(name: 'environment',     value: env.JOB_NAME),
                        string(name: 'rcloud_version',  value: params.rcloud_version),
                        string(name: 'rafay_interface', value: params.rafay_interface),
                        string(name: 'test_type',       value: params.test_type),
                        string(name: 'triggered_by',    value: params.triggered_by ?: ''),
                        string(name: 'triggered_by_id', value: params.triggered_by_id ?: ''),
                        string(name: 'passed_count',    value: passed.toString()),
                        string(name: 'total_count',     value: total.toString()),
                    ]
                )
            }
        }
    }
}
```

### Multibranch pipeline note

These are multibranch pipelines. The `slack-notifier` job above is a regular pipeline so `job: 'slack-notifier'` is fine.

However, if `slack-notifier` is ever converted to multibranch, update the call to `job: 'slack-notifier/main'`.

---

## Step 9 — Confirm Target Job Paths in `Jenkinsfile.router`

Since the target pipelines are **multibranch**, the router uses `<job-name>/master` paths. These are already set in `Jenkinsfile.router`:

```groovy
def jobMap = [
    "qc":     "QC-Staging/master",
    "stage":  "Staging/master",
    "prod":   "Production-Regression/master",
    "master": "Master-Sanity/master",
]
```

> **If the pipelines are nested inside a Jenkins folder**, the path must include the folder name.
> For example, if `QC-Staging` lives inside a folder called `QC-Staging (Integration)`, the path would be:
> `QC-Staging (Integration)/QC-Staging/master`
> Update the `jobMap` in `Jenkinsfile.router` accordingly before going live.

---

## Step 10 — Script Security Approvals (one-time)

Jenkins sandboxes Groovy by default. Two method signatures need admin approval.

**First run `slack-router`** → it will fail → go to `Manage Jenkins → Script Approval` → approve:
```
staticMethod org.codehaus.groovy.runtime.DefaultGroovyMethods getText java.net.URL
```
Re-run `slack-router` — it will succeed.

**First run of any target pipeline** → it will fail → same process → approve:
```
method hudson.model.Run getAction java.lang.Class
```
Re-run — works permanently after that.

---

## Step 11 — Switch Notification Channel from Demo to Prod

In `Jenkinsfile.notifier`, change line 61:

```groovy
// Before
channel: '#jenkins-runs-demo',

// After
channel: '#jenkins-runs',
```

Commit and push to `main`. Both `slack-router` and `slack-notifier` jobs pull from SCM so they pick up the change automatically on next run.

---

## Summary — Who Does What

| # | Action | Owner |
|---|---|---|
| 1 | Create Jenkins credential `slackins-bot-token` | Ops |
| 2 | Install 4 Jenkins plugins | Ops |
| 3 | Configure Slack Notification global config | Ops |
| 4 | Update Lambda `JENKINS_WEBHOOK_URL` env var | Ops |
| 5 | Create `slack-router` pipeline job | Ops |
| 6 | Create `slack-notifier` pipeline job | Ops |
| 7 | Point 3 slash commands at Lambda URL | You (Slack app dashboard) |
| 8 | Invite bot to `#jenkins-runs` | Anyone |
| 9 | Add `slack-notifier` call to 4 Jenkinsfiles in rauto repo | Dev team |
| 10 | Confirm/update `jobMap` paths for multibranch + folder nesting | Dev team |
| 11 | Approve 2 script signatures after first run | Ops |
| 12 | Change channel from `#jenkins-runs-demo` → `#jenkins-runs` | Dev team (this repo) |
