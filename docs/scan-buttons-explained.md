# Scan Buttons, Explained for Software Developers

Plain-software explanations of three beamline GUI buttons — no physics required.
All three are just **read/write operations on named hardware variables** ("PVs"),
which behave like remote key/value entries you access over HTTP and WebSocket via
the `direct_control_service` backend.

## The shared mental model

The (simulated) hardware exposes two things you care about:

- A **dial** — a number that ramps from one value to another over time.
  This is the monochromator "energy." PV: `XF:23ID2-OP{Mono}Enrgy-I` (read),
  with `Enrgy:Start-SP`, `Enrgy:Stop-SP`, `Enrgy:FlyVelo-SP` to configure the ramp.
- A **counter** — a set of numbers that tick up while acquiring.
  This is the "scaler." PVs: `XF:23ID2-ES{Sclr:1}.CNT` (1=start/0=stop),
  `.TP` (how long to count, seconds), `.T` (elapsed), and the channels
  `.S1` (clock), `.S2` (I0), `.S3` (photodiode / "PD"), `.S4` (aumesh).

Backend access used by all three buttons:

- `POST /api/control/pv/set` and `/pv/set/batch` — write PVs (HTTP)
- `GET /api/control/pv/{name}/value` — read a PV (HTTP)
- `ws://…/api/v1/pv-socket` — subscribe to PVs for live updates (WebSocket)

---

## 1. PD Scan

**What it is in software terms:** start turning the *dial* from X to Y, and while it
turns, stream the *counter* at each moment, then draw a graph of counter-value vs.
dial-value. A form-submit that kicks off a job, plus a live-updating line chart driven
by a WebSocket, with a status field telling you when the job ends.

**Inputs (from the selected element's preset):** `start`, `stop`, `velocity`.

**Steps on click:**

1. **Write the settings** (one batch HTTP call):
   ```
   Enrgy:Start-SP   = start      // dial from-value
   Enrgy:Stop-SP    = stop       // dial to-value
   Enrgy:FlyVelo-SP = velocity   // dial speed
   .TP              = <duration> // counter run time (≈ fly duration)
   ```
2. **Open a live feed** (WebSocket): subscribe to the dial (`Enrgy-I`) and the
   photodiode counter (`.S3`). Now the browser gets a message whenever either changes.
3. **Press "go"** (two writes):
   ```
   .CNT = 1                     // start the counter
   Cmd:FlyStart-Cmd.PROC = 1    // start turning the dial
   ```
4. **Collect + draw:** on each WebSocket message, push `{ x: dial, y: counter }` into
   an array and re-render the chart as it grows.
5. **Detect completion:** poll/subscribe the status PV `Sts:Scan-Sts`. It reads
   `"Scanning"` while running and flips to `"Idle"` when done — then freeze the chart.
6. **Stop (optional, anytime):** write `Cmd:Stop-Cmd = 1` to abort.

**Pseudo-flow:**

```
onClick:
  POST settings (batch)
  open WebSocket(Enrgy-I, S3)
  POST .CNT=1, FlyStart=1
  on each WS message: points.push({x: energy, y: pd}); redraw
  when Scan-Sts == "Idle": close feed, done
```

**Output:** a 2D spectrum — photodiode counts vs. energy.

---

## 2. Single Scan

**What it is in software terms:** fire the counter **once** for a fixed amount of time,
then read the final numbers. The dial does **not** move. It's "run one acquisition and
show me the result" — no streaming chart required, just a single before/after read.

This is the classic EPICS scaler **one-shot count** (the scaler record's "OneShot"
mode). Our simulated scaler is one-shot only.

**Steps on click:**

1. **Set the duration** (HTTP): `.TP = <seconds>` (how long to count).
2. **Start the count** (HTTP): `.CNT = 1`. The IOC zeros the channels, counts up for
   `.TP` seconds, then **auto-clears** `.CNT` back to `0` when finished.
3. **Wait for done:** either poll `.CNT` until it reads `0` again, or poll `.T`
   (elapsed) until it reaches `.TP`.
4. **Read the results** (HTTP GET, once): `.S1`, `.S2`, `.S3`, `.S4` — the final counts.
   Display them as numbers (optionally with their names `.NM1`–`.NM4`).

**Pseudo-flow:**

```
onClick:
  POST .TP = duration
  POST .CNT = 1
  wait until .CNT == 0      // count finished
  GET .S1..S4               // read final values
  show the numbers
```

**Difference from PD Scan:** PD Scan moves the dial *and* counts → a graph
(2D: counter vs dial). Single Scan keeps the dial fixed and counts once → a handful of
final numbers (0D: just totals). No fly, no live plot needed.

**Output:** one set of channel totals.

---

## 3. Erase/Start

**What it is in software terms:** **reset the counters to zero, then begin acquiring** —
and watch the numbers climb live from 0. This is the classic EPICS MCA/scaler
"Erase/Start" button: "erase" clears the previous data, "start" begins a fresh count.

In our simulated scaler the **erase is implicit**: writing `.CNT = 1` makes the IOC
zero `.S1`–`.S4` and `.T` *before* it starts counting. So a single write does both the
"erase" and the "start."

**Steps on click:**

1. **(Optional) set duration** (HTTP): `.TP = <seconds>`.
2. **Open a live feed** (WebSocket): subscribe to the channels you want to watch,
   e.g. `.S2`, `.S3`, `.S4` (and `.T` for elapsed time).
3. **Erase + start** (one HTTP write): `.CNT = 1`. The IOC zeros the channels and begins
   counting; your subscribed values start streaming upward from 0.
4. **Live display:** on each WebSocket message, update the on-screen counters (a small
   live readout, not necessarily a chart).
5. **Stop:** the count auto-stops when `.T` reaches `.TP` (`.CNT` self-clears to `0`),
   or the user can stop early by writing `.CNT = 0`.

**Pseudo-flow:**

```
onClick:
  POST .TP = duration            // optional
  open WebSocket(S2, S3, S4, T)
  POST .CNT = 1                  // erase (zero) + start, in one write
  on each WS message: update live counter display
  when .CNT == 0: done           // auto-stopped at .TP (or user stopped)
```

**Difference from the others:**

- vs **Single Scan:** Single Scan reads totals **once at the end**; Erase/Start shows the
  counts **climbing live** and emphasizes the "reset-then-go" framing. (On real hardware
  Erase/Start is often used in a repeating/continuous-acquire context; our sim is
  one-shot, so it stops at `.TP`.)
- vs **PD Scan:** no dial movement, so there's no spectrum graph — just live counter
  values at the current energy.

**Output:** live-updating channel counts that grow from 0.

---

## Quick comparison

| Button       | Moves the dial? | Counter behavior            | Live UI             | Result shape                |
|--------------|-----------------|-----------------------------|---------------------|-----------------------------|
| PD Scan      | Yes (ramps)     | counts during the ramp      | live line chart     | spectrum (counts vs energy) |
| Single Scan  | No              | one-shot count for `.TP`    | none (read at end)  | a few final numbers         |
| Erase/Start  | No              | zero, then count (to `.TP`) | live number readout | numbers climbing from 0     |

All three reduce to the same two operations: **write some PVs to configure/trigger**,
and **read/subscribe to PVs to observe the result.** The only differences are *which*
PVs and *whether you stream or read once*.
