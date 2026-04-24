# Phase 10 — Frontend

## Prerequisites

- [ ] Phase 09 complete (WebSocket deployed and working with wscat)
- [ ] You have the WSS URL from CloudFormation outputs

## Goal

A single self-contained `frontend/index.html` with vanilla JS that connects to the WebSocket, sends user messages, and displays streamed assistant responses with a typing-indicator feel. Record the final demo after this phase works.

## Context for Claude Code

- Intentionally minimal — reviewer doesn't care about CSS polish; they care that the backend behavior is visible
- Vanilla JS, no React, no build step. One HTML file.
- Hosted via `python -m http.server 8000` from the `frontend/` directory, or via S3 static website hosting if time permits
- Message format matches phase 09 output events: `text_delta`, `tool_use_start`, `end`

## Steps

### 10.1 — Create `frontend/index.html`

Structure:
- Header: "CloudKinetics Agent Demo"
- Input field for WSS URL (prefilled from a `config.js` or hardcoded after deploy)
- Connect / Disconnect buttons
- Chat history area (scrollable)
- Message input with Send button
- Status indicator (connected / connecting / disconnected)
- Subtle "tool: retrieve_knowledge" badge that appears when tool_use_start event arrives (nice-to-have, shows the agent is working)

Claude Code can one-shot this. Key requirements in the prompt:

```
Create frontend/index.html with:
- A WebSocket URL input defaulting to wss://PLACEHOLDER.execute-api.us-east-1.amazonaws.com/prod
- Connect/Disconnect buttons
- Chat display with user messages right-aligned (blue bg) and agent messages left-aligned (gray bg)
- Streaming text: when a "text_delta" event arrives, append its text to the last agent message bubble
- When "tool_use_start" arrives, show a small italicized note below the current message like "🔍 searching knowledge base..." or "🔐 checking order status..."
- When "end" arrives, finalize the message and re-enable the send button
- Handle disconnects gracefully (show red "disconnected" banner)
- No external dependencies — plain HTML/CSS/JS
- Mobile-responsive but desktop-first
```

### 10.2 — Test the frontend

```bash
cd frontend
python -m http.server 8000
```

Open `http://localhost:8000` in your browser.
1. Enter the WSS URL, click Connect. Status should go green.
2. Ask a knowledge question ("what is your return policy?"). Words should stream in.
3. Walk through the full order status flow. Confirm tool badges appear.
4. Try the multi-order case with Alice's credentials — confirm agent lists orders and asks you to pick.

### 10.3 — (Optional, ~10 min) Deploy to S3 static hosting

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
FE_BUCKET="ck-frontend-${ACCOUNT_ID}"

aws s3 mb "s3://${FE_BUCKET}" --region us-east-1
aws s3 website "s3://${FE_BUCKET}" --index-document index.html
aws s3api put-bucket-policy --bucket $FE_BUCKET --policy "$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": "*",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::${FE_BUCKET}/*"
  }]
}
EOF
)"
aws s3 cp frontend/index.html "s3://${FE_BUCKET}/"
echo "http://${FE_BUCKET}.s3-website-us-east-1.amazonaws.com"
```

Skip this if short on time. Localhost works fine for the demo recording.

### 10.4 — Record the demo video

This is critical. Do it now, even if the system isn't 100% polished — it's your insurance against anything breaking tomorrow.

**Recording setup:**
- Tool: Loom (free, generates shareable link) or OBS (local .mp4)
- Duration target: 3-5 min
- Resolution: 1080p
- Include: voice narration + webcam overlay (optional but humanizing)

**Demo script** (run through once before recording):

1. **0:00-0:20** — Intro: "Hi, I'm Matthew. This is my CloudKinetics solution architect intern assessment. I built a conversational agent for an e-commerce company that does RAG and tool-based order lookups."

2. **0:20-1:00** — Show architecture: "Here's the architecture — [show a quick slide or whiteboard]. User connects to API Gateway WebSocket, which triggers a Lambda running the agent loop. The agent uses Claude Sonnet 4.6 via Bedrock Converse API, retrieves from a Bedrock Knowledge Base for policy questions, and calls a mock order service for verified users. Everything persists to DynamoDB."

3. **1:00-1:45** — Knowledge question demo: "Let me ask about the return policy." Show streaming. "You can see it's using the retrieve_knowledge tool, and the answer is grounded in the actual policy document."

4. **1:45-3:00** — Order status flow: "Now let me check an order. [Type 'what's my order status'] — notice it asks for email first, not all three fields at once. [Type email] — now SSN. [Type SSN] — now DOB. I'll type it as natural language: 'March 15, 1990'. [Agent confirms] — and now it's calling the tool. Alice has 3 orders, so it's listing them and asking me to pick. [Pick one] — here's the specific order detail."

5. **3:00-3:30** — Security: "If I try to get order info without verifying first, it won't give me anything. [Demo this]. And if I give wrong credentials, it fails gracefully without leaking which field was wrong."

6. **3:30-4:00** — Wrap-up: "All conversation history persists to DynamoDB — here's the console [show the table briefly]. Full design doc and architecture details are in the repo README. Thanks for your time."

Save the video. Upload to Loom OR to Google Drive (set to "anyone with link can view"). Add the link to the README in phase 11 repo polish.

## Verification (human-runnable)

```bash
# Frontend loads locally
cd frontend && python -m http.server 8000 &
curl -s http://localhost:8000/ | grep -c "WebSocket"
# Expected: > 0

# Demo video exists
ls -la demo_video.* 2>/dev/null || echo "Loom link:" && cat docs/demo_link.txt
# Expected: either a video file or a link file
```

## Definition of Done

- [ ] `frontend/index.html` is a single self-contained file
- [ ] Connects to deployed WebSocket and shows streaming responses
- [ ] Displays tool-use indicators when the agent searches KB or calls order tool
- [ ] All 4 flows from phase 04 work via the UI
- [ ] **Demo video recorded** and accessible via link or local file
- [ ] Demo link saved to `docs/demo_link.txt` or video file committed

## Out of Scope

- ❌ Fancy CSS / design polish beyond "looks reasonable"
- ❌ User auth on the frontend (we're simulating an already-logged-in session)
- ❌ Conversation history in the UI beyond current session
- ❌ Mobile-specific optimizations
- ❌ Dark mode, themes, etc.

## Commit Message

```
[phase 10] Minimal frontend + demo recording

- frontend/index.html: single-file vanilla JS WebSocket client
- Streaming text display with tool-use indicators
- Connect/disconnect status UI
- Tested with all 4 agent flows (knowledge, verification, multi-order, refusal)
- Demo video recorded (link in docs/demo_link.txt)
- (Optional) Deployed to S3 static hosting
- Reference: plans/10_frontend.md
```

---

**END OF SATURDAY.** Push everything, commit, and stop working. Sleep. Sunday is for persistence, observability, CI/CD, tests, and — most importantly — the design doc.
