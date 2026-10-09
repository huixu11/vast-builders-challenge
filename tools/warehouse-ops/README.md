# Warehouse Ops Copilot

A real-time video agent for warehouse safety and operations, built in one day at the Real-Time Video Agents Hack
(New York, October 9, 2026) on top of the pre-deployed VSS video search stack.

It watches every camera in the archive, catches near misses between people and machines, finds idle labor and idle
machines, estimates what that idle time costs per shift, and answers questions with citations. Every alert and every
number links back to the video moment it came from.

**Demo video:** _link added at submission_ (recorded by `demo/record_demo.py`: Playwright drives the app in Edge
with its caption track, `?tour`)

## What it does

| Page | What you see |
| --- | --- |
| Overview | People on the floor, idle ratio, machines moving, the idle-cost estimate with editable assumptions, and the video agent's status and activity log |
| Video library | All 60 indexed videos (33 camera views) with thumbnails, hover previews and a player with per-video stats |
| Safety alerts | Near misses confirmed across camera views, with the clip, the moment and the motion evidence |
| Resources & bottlenecks | Idle labor, idle machines, congestion and underused zones, with recommendations tied to the evidence |
| Multi-camera replay | All views of a scene, in sync |
| Ask | Grounded Q&A over the analyzer's facts and VSS search hits; answers cite alert and flag ids |
| Shift report | An LLM-written shift report whose numbers are checked against the data before it is shown |

## How it works

```
VSS ingest (pre-deployed): upload -> segmenter -> YOLO detector -> Cosmos Reason captions -> embedder -> VastDB
                                                        |
analyzer/                                               v
  inventory.py      lists the indexed chunks per site and camera (VSS explore API)
  kinematics.py     person and machine tracks from the YOLO detections: speed, idle time, sudden evasive motion
  vlm.py            Cosmos Reason calls: one description per 5 s segment, targeted checks of candidate moments
  fusion.py         motion proposes candidate moments, Cosmos verifies the exact window and region, views vote
  utilization.py    idle labor, idle machines, congestion and zone occupancy flags
  recommend.py      recommendations and the shift report from the facts (W&B Inference)
  watch.py          the real-time agent loop: polls VSS and analyzes new footage once it is fully indexed
  export_vastdb.py  writes alerts, flags and segment metrics back to VastDB, keyed by the segment's S3 URI
app/                FastAPI + vanilla JS: serves the results, proxies clips and detections, runs Ask and reports
```

The agent loop is what makes it real time: every 30 s `watch.py` compares what VSS has indexed with what the app has
analyzed. When a video is fully indexed it runs the analyzer on that site, the app reloads within seconds, and new
alerts appear with a NEW badge and a toast. The results also land in VastDB (`warehouse_ops.alerts`, `.flags`,
`.segment_metrics`); every row carries `source`, the key of the VSS segment table, so alerts join with the
pipeline's captions and embeddings (`python analyzer/export_vastdb.py --join`).

## Why the alerts can be trusted

Asking Cosmos Reason directly "is there a near miss in this clip?" returned yes for 168 of 180 clips from the main
warehouse floor. So the agent does not ask that question. Instead it:

1. lets motion tracks propose candidate moments (a worker stops and then moves suddenly; a person and a moving
   machine converge),
2. asks Cosmos a neutral question about that time window and image region, defaulting to "no interaction",
3. asks the same question about random control moments, and
4. requires agreement across camera views.

Measured on this archive: 0 of 12 random control moments flagged; 0 of 6 motion candidates on the main floor
confirmed; single-view checks recognized 5 of 9 known near-miss moments, and with multi-view voting all 3 drill near
misses were caught (9 of 10 views agreed in runs 3 and 7).

Every number the LLM writes in a shift report is checked against the data before it is shown
(`verify_numbers` in `app/app_copilot.py`), and answers cite the alert and flag ids they rely on.

## Measured performance

- **Text reasoning:** NVIDIA Nemotron-3-Ultra through W&B Inference. On the app's real prompts it answered Ask
  questions in 2-3 s (gpt-oss-120b: 9-12 s) and wrote the shift report in 48 s (gpt-oss-120b: 69 s); no number
  failed the check for either model.
- **Video reasoning:** the Cosmos Reason endpoint handled 41 five-second clips per minute one request at a time and
  123 per minute with 6 requests in parallel, about 10 s of video per second, or roughly 10 cameras analyzed in real
  time (small sample).

## Built with

- **NVIDIA:** Cosmos Reason for video reasoning, Nemotron-3-Ultra for the agent's text reasoning
- **VAST Data:** S3 video archive, the DataEngine ingest pipeline, VastDB for the VSS index and our results
- **CoreWeave:** GPUs serving Cosmos Reason, YOLO11 and the embedding model
- **Weights & Biases:** W&B Inference for Nemotron
- **Cursor:** used to build all of it during the hack

## Data

- Footage: NVIDIA PhysicalAI-SmartSpaces `Warehouse_017` (AI City Challenge 2025, 3 cameras, 5 minutes each) and
  three synthetic forklift-safety drills (10 camera views each).
- `app/data_*.json`: the analyzer's output for the 60 indexed videos (240 segments), so the UI runs without
  re-running the analysis. `mock_data/` holds synthetic data for offline UI work.

## Run it

You need access to a VSS deployment from the Builders Challenge (a team config file with the endpoints and
credentials; nothing is hardcoded here).

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r app/requirements.txt imageio-ffmpeg pillow   # export to VastDB also needs: vastdb pyarrow
export VSS_CONFIG=/path/to/<team>.config                    # default: the single *.config in /config
export GPU_HOST=<GPU host from the workshop docs>           # or COSMOS3_REASON_URL=http://<host>:8001

python app/main.py                          # http://localhost:8080 (set PORT to change)
python analyzer/run_analysis.py             # re-run the analysis (Cosmos calls are cached)
python analyzer/watch.py --interval 30      # the real-time agent loop; its status shows on the Overview
python analyzer/export_vastdb.py            # write the results to VastDB (needs the data VIP)
bash deploy.sh                              # deploy to the team's Kubernetes namespace (workshop VM)
```

## Limitations

- The footage is synthetic, and the AI City Challenge 2025 test split withholds its ground truth, so the accuracy
  above comes from controls and known positives rather than labels.
- "Idle" means stationary on camera, and some of that is real work at a station. The cost estimate is a starting
  point with editable assumptions.
- The agent polls the VSS explore API, since no ingest event is exposed to team apps, so it reacts within one scan
  after VSS finishes indexing.
- The VastDB data VIP resolves only inside the event network, so the export runs from the workshop VM or the cluster.

## Team

Team 35, Builders Challenge.
