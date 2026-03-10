# Slack → Jenkins Router

Trigger regression, smoke, and sanity runs directly from Slack with a single slash command. Results are posted back to the channel automatically.

```
/regression qc 4.1 72 vikings api
```

---

## Architecture

```
┌─────────────┐     POST      ┌─────────────────┐     POST      ┌──────────────────────────────┐
│  Slack      │ ─────────────▶│  Lambda Proxy   │ ─────────────▶│  Jenkins                     │
│  /regression│               │  (us-east-1)    │               │                              │
│  /smoke     │◀─────────────│  Returns clean  │               │  slack-router                │
│  /sanity    │  ⏳ "On it"   │  ack to Slack   │               │  ├─ Parse command            │
└─────────────┘               └─────────────────┘               │  ├─ Fetch squad tags (Dynamo)│
                                                                 │  ├─ 🚀 "Triggering..." msg  │
                                                                 │  └─ Trigger target job       │
                                                                 │                              │
                                                                 │  QC-Staging / Staging /      │
                                                                 │  Production-Regression /     │
                                                                 │  Master-Sanity               │
                                                                 │  └─ Runs tests               │
                                                                 │  └─ Calls slack-notifier     │
                                                                 │                              │
                                                                 │  slack-notifier              │
                                                                 │  └─ Posts result to Slack    │
                                                                 └──────────────────────────────┘
                                                                              │
                                                                              ▼
                                                                 ┌─────────────────────────────┐
                                                                 │  #jenkins-runs              │
                                                                 │                             │
                                                                 │  ✅ Build #42 — SUCCESS     │
                                                                 │  🌿 QC  | 4.1 | vikings     │
                                                                 │  📊 34/38 passed (89.47%)   │
                                                                 │  ⏱ 2 hr 14 min             │
                                                                 │  🔗 https://jenkins/job/... │
                                                                 └─────────────────────────────┘
```

**Two Slack messages per run** — `🚀 Triggering...` when the job starts, final result when it finishes. Nothing else.

---

## Slash Command Format

```
/<type> <env> <version> <rctl_buildnum> <squad> <interface> [terraform_version]
```

| Arg | Values | Example |
|-----|--------|---------|
| `type` | `regression` `smoke` `sanity` | `/regression` |
| `env` | `qc` `stage` `prod` `master` | `qc` |
| `version` | rcloud version | `4.1` or `4.1-Patch` |
| `rctl_buildnum` | rctl image build number | `72` |
| `squad` | `vikings` `avengers` `alpha` `mavericks` | `vikings` |
| `interface` | `api` `cli` `terraform` | `api` |
| `terraform_version` | required only for terraform interface | `1.1.57` or `v4.1.x:6` |

**Examples:**
```
/regression qc 4.1 72 vikings api
/smoke      stage 4.1-Patch 84 alpha cli
/sanity     qc 4.1 72 mavericks terraform v4.1.x:6
/regression stage 4.1 72 mavericks terraform 1.1.57
```

> `/sanity` maps to `mini-sanity` internally.
> Terraform version bare semver (e.g. `1.1.57`) is expanded to `RafaySystems/rafay:1.1.57` automatically.

---

## Production Setup Checklist

### 1. Lambda Proxy

Already deployed in `us-east-1`. One change needed:

**Update the Jenkins URL env var** (no code deploy required):
```bash
aws lambda update-function-configuration \
  --region us-east-1 \
  --function-name slack-jenkins-proxy \
  --environment "Variables={
    JENKINS_WEBHOOK_URL=https://<real-jenkins-url>/generic-webhook-trigger/invoke?token=slack-router,
    ACK_MESSAGE=⏳ On it — triggering now...
  }"
```

Lambda Function URL (API Gateway endpoint — give this to Slack):
```
https://0tx582z14j.execute-api.us-east-1.amazonaws.com/prod/
```

---

### 2. Slack App

Add 3 slash commands to the **existing** `qa-jenkins` Slack app (`api.slack.com/apps` → select the app → **Slash Commands** → **Create New Command**):

| Command | Request URL | Description |
|---------|-------------|-------------|
| `/regression` | `https://0tx582z14j.execute-api.us-east-1.amazonaws.com/prod/` | Trigger regression run |
| `/smoke` | `https://0tx582z14j.execute-api.us-east-1.amazonaws.com/prod/` | Trigger smoke run |
| `/sanity` | `https://0tx582z14j.execute-api.us-east-1.amazonaws.com/prod/` | Trigger sanity run |

All three point to the same Lambda URL. The Lambda forwards the full Slack payload to Jenkins, and the router reads `SLACK_COMMAND` to distinguish between them. No other changes to the Slack app needed.

---

### 3. Jenkins — Plugins

Ensure these are installed (`Manage Jenkins → Plugins`):

| Plugin | Purpose |
|--------|---------|
| **Generic Webhook Trigger** | Receives Slack POST, extracts fields, triggers `slack-router` |
| **Slack Notification** | `slackSend()` step used by router and notifier |
| **Pipeline** | Jenkinsfile pipeline support (likely already installed) |
| **Robot Framework** | Publishes `output.xml` results; exposes pass/fail counts |

---

### 4. Jenkins — Credentials

**Nothing to do here.** If the existing Jenkins bot (`qa-jenkins`) is already posting Slack notifications, the credential is already configured and working. The new jobs reuse the same setup automatically.

---

### 5. Jenkins — New Jobs

Create two new Pipeline jobs:

#### `slack-router`
- **Definition:** Pipeline script from SCM
- **SCM:** `https://github.com/UdayKumar-Rafay/slack-jenkins-router.git`
- **Branch:** `main`
- **Script Path:** `Jenkinsfile.router`
- **Build Triggers:** Generic Webhook Trigger
  - Token: `slack-router`
  - JSONPath variables: already configured inside the Jenkinsfile

#### `slack-notifier`
- **Definition:** Pipeline script from SCM
- **SCM:** `https://github.com/UdayKumar-Rafay/slack-jenkins-router.git`
- **Branch:** `main`
- **Script Path:** `Jenkinsfile.notifier`
- **Build Triggers:** none (triggered programmatically by target pipelines)

---

### 6. Jenkins — Script Security Approvals

Jenkins sandboxes Groovy pipelines by default. The first time a pipeline uses a method that isn't pre-approved, it blocks the build and queues the signature for an admin to review.

**How it works:** run the job once → it fails → go to `Manage Jenkins → Script Approval` → click **Approve** next to the flagged signature → re-run. That's it, one-time per signature, works forever after.

Two signatures need approval:

```
staticMethod org.codehaus.groovy.runtime.DefaultGroovyMethods getText java.net.URL
```
*(Triggered by `slack-router` on first run — used to fetch squad tags from DynamoDB)*

```
method hudson.model.Run getAction java.lang.Class
```
*(Triggered by a target pipeline on first run — used to read Robot Framework pass/fail counts via `currentBuild.rawBuild`)*

---

### 7. Existing Pipelines — Required Changes

All four target pipelines need two additions:

**a) Add `triggered_by` parameter** (at the top of the `parameters { }` block):
```groovy
string(name: 'triggered_by', defaultValue: '', description: 'Slack username who triggered this run')
```

**b) Add `slack-notifier` call** to `post { always { } }`:
```groovy
post {
    always {
        script {
            // ... existing sh commands (email, s3 upload, sync-results) stay here ...

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
                    string(name: 'passed_count',    value: passed.toString()),
                    string(name: 'total_count',     value: total.toString()),
                ]
            )
        }
    }
}
```

**Pipelines to update:**

| Jenkins Job | Jenkinsfile location |
|-------------|---------------------|
| `QC-Staging` | `build/pipeline_qc_stage/Jenkinsfile` |
| `Staging` | `build/pipeline_stage/Jenkinsfile` |
| `Production-Regression` | `build/pipeline_production/regression/Jenkinsfile` |
| `Master-Sanity` | `build/pipeline_master_sanity/Jenkinsfile` |

---

### 8. Update Squad & Channel Mapping

In `Jenkinsfile.router` and `Jenkinsfile.notifier`, two maps use Slack user IDs. Verify or update if membership changes:

```groovy
def squadMap = [
    "vikings":   ["U07E5MPLE7K", "U09FH2AANM9"],  // Uday, Amarnath
    "avengers":  ["U077D7ZJMJQ", "U0A7LJ03JKA"],  // Manish, Mora Bhargav
    "alpha":     ["U03JC5J0LDU", "U03JC5J0LDU"],  // Shobhit
    "mavericks": ["U07E5MPLE7K", "U03JC5J0LDU"],  // Uday, Shobhit
]
```

To find a Slack user ID: click their profile → `⋮` → **Copy member ID**.

Also update the hardcoded channel in `Jenkinsfile.notifier`:
```groovy
// Change from demo channel to real channel
channel: '#jenkins-runs',   // was '#jenkins-runs-demo'
```

---

## Files in This Repo

```
slack-jenkins-router/
├── Jenkinsfile.router       # slack-router job — parses command, triggers target pipeline
├── Jenkinsfile.notifier     # slack-notifier job — posts final result to Slack
└── stub-jobs/               # Demo-only stubs (not needed in production)
    ├── Jenkinsfile.QC-Staging
    ├── Jenkinsfile.Staging
    ├── Jenkinsfile.Production-Regression
    └── Jenkinsfile.Master-Sanity
```

---

## What Ops Needs to Do (Summary)

| # | Action | Where |
|---|--------|--------|
| 1 | Update Lambda env var `JENKINS_WEBHOOK_URL` to real Jenkins URL | AWS Console or CLI |
| 2 | Point `/regression`, `/smoke`, `/sanity` slash commands at the API Gateway URL | Slack App dashboard |
| 3 | ~~Slack credentials~~ — already working via `qa-jenkins` bot, nothing to do | — |
| 4 | Install Generic Webhook Trigger + Slack Notification plugins (if not present) | Jenkins → Plugin Manager |
| 5 | Create `slack-router` pipeline job | Jenkins |
| 6 | Create `slack-notifier` pipeline job | Jenkins |
| 7 | Approve 2 script signatures after first run | Jenkins → Script Approval |
| 8 | Add `triggered_by` param + `slack-notifier` call to 4 Jenkinsfiles | rauto repo |
| 9 | Change channel from `#jenkins-runs-demo` → `#jenkins-runs` in `Jenkinsfile.notifier` | This repo |
| 10 | Invite the Slack bot to `#jenkins-runs` | Slack |
