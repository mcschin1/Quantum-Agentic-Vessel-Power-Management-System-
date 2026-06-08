# ⚓ Quantum-Agentic Vessel Power Management System

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![Qiskit](https://img.shields.io/badge/Qiskit-2.4+-6929C4?style=flat-square&logo=ibm&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0+-000000?style=flat-square&logo=flask&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)
![Status](https://img.shields.io/badge/Status-Active-14b8a6?style=flat-square)

**A full-stack Python implementation of quantum-enhanced agentic AI for autonomous vessel power management.**  
Combines QAOA (Quantum Approximate Optimisation Algorithm) with a multi-agent architecture for real-time power distribution, fault detection, and fuel optimisation — all without human intervention.

[Overview](#overview) · [Architecture](#architecture) · [Quick Start](#quick-start) · [Agents](#agents) · [Quantum Layer](#quantum-layer) · [Dashboard](#dashboard) · [API](#api-reference) · [Results](#simulation-results)

---

*Developed at the [Newcastle University–NVIDIA Joint Laboratory](https://www.ncl.ac.uk), Singapore*  
*Prof. Cheng Siong Chin · Chair Professor of Intelligent Systems Modelling & Simulation*

</div>

---

## Overview

Modern vessels operate one of the most electrically demanding environments on earth. Propulsion drives swing demand by megawatts within seconds. Safety systems demand uninterrupted power. Diesel generators carry efficiency curves that punish both underloading and overloading. And all of this must balance — continuously — without a grid to lean on.

Classical rule-based Power Management Systems (PMS) handle this with deterministic logic written at commissioning time. They do not adapt to aging equipment, changing operational profiles, or the multi-objective tradeoffs between fuel economy, reserve margins, and emissions.

This project replaces that logic with **five autonomous agents** coordinated by a **quantum-optimised decision core**:

- **QAOA** solves the power allocation problem across priority-weighted loads every 5 seconds
- **Quantum amplitude estimation** detects electrical anomalies across 10 monitoring channels
- **Autonomous load shedding** preserves critical systems during generation shortfalls
- **Willans-line SFC modelling** finds the fuel-optimal generator combination for any demand level
- **Real-time SocketIO dashboard** streams system state at 1-second resolution

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                  VesselPMSOrchestratorAgent                          │
│                                                                      │
│  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────────┐  │
│  │ PowerGeneration │  │ LoadManagement   │  │ FaultDetection    │  │
│  │     Agent       │  │     Agent        │  │     Agent         │  │
│  │  4× DG | 2× ESS │  │ 17 loads 5 tiers │  │ 10 ch · Quantum  │  │
│  └────────┬────────┘  └────────┬─────────┘  └───────────────────┘  │
│           │                    │ demand vector                       │
│           │             ┌──────▼──────────────┐                     │
│           │             │   VesselPowerQAOA   │  ← Qiskit Aer       │
│           │             │   6 qubits · p=2    │    512 shots        │
│           │             └──────┬──────────────┘                     │
│           │ update_demand      │ allocation MW                       │
│           ◄────────────────────┘                                     │
│           │      ┌──────────────────┐                               │
│           └─────►│ FuelEfficiency   │  Willans SFC · merit order    │
│                  │     Agent        │                                │
│                  └──────────────────┘                               │
└─────────────────────────────────────────────────────────────────────┘
              │
     Flask REST API + SocketIO  (:5000)
              │
     dashboard/index.html  ── Chart.js · live tables · alerts
```

### Decision Cycle

| Cycle | Period | What happens |
|---|---|---|
| Status tick | 1 s | Collect agent states, run load shedding check, update fuel counters |
| QAOA optimisation | 5 s | Run quantum power allocation, push results to load agent |
| State broadcast | 1 s | Emit full system snapshot to all SocketIO clients |

---

## Quick Start

### Prerequisites

```bash
pip install qiskit qiskit-aer flask flask-socketio numpy scipy
```

### Run simulation (no server needed)

```bash
git clone https://github.com/cschin/quantum-vessel-pms
cd quantum-vessel-pms
python run_simulation.py --ticks 30 --report-every 5
```

Expected output:
```
tick=   5 | demand=  6.84 MW | gen=  6.35 MW | bal=+0.51 | fuel= 987.3 kg/h | SFC=246 g/kWh | Q_util=72.4%
tick=  10 | demand=  7.12 MW | gen=  7.01 MW | bal=-0.11 | fuel=1421.8 kg/h | SFC=248 g/kWh | Q_util=81.3%
...
  QAOA calls             : 6
  Avg QAOA utilisation   : 76.8%
  Avg QAOA solve time    : 0.11s
```

### Start the full API server

```bash
python api_server.py
# API:       http://localhost:5000/api/state
# Dashboard: open dashboard/index.html in a browser
```

> **Standalone dashboard:** `dashboard/index.html` runs entirely in a browser with no server required. It automatically simulates all five agents and the quantum optimiser locally using JavaScript.

---

## Project Structure

```
quantum_vessel_pms/
├── quantum/
│   └── quantum_optimizer.py     # VesselPowerQAOA + QuantumAnomalyDetector
├── agents/
│   ├── orchestrator.py          # Master multi-agent coordinator (asyncio)
│   ├── generation_agent.py      # Generator & ESS management
│   ├── load_agent.py            # 17-load roster + priority shedding
│   ├── fault_agent.py           # 10-channel quantum anomaly detection
│   └── fuel_agent.py            # SFC optimisation & merit-order dispatch
├── dashboard/
│   └── index.html               # Self-contained real-time HTML5 dashboard
├── config/
│   └── config.json              # System configuration
├── api_server.py                # Flask + SocketIO server
└── run_simulation.py            # Standalone simulation runner + report
```

---

## Agents

### PowerGenerationAgent

Manages the vessel's four diesel generators and two energy storage systems. Autonomously starts or stops generators to maintain a **15% spinning reserve** above total demand. Handles fault injection and recovery. Dispatches ESS units to bridge transient supply–demand gaps.

```python
# Autonomous fleet decision — runs every 1 second
def _fleet_management(self) -> None:
    required = self.target_demand_mw * (1 + self.RESERVE_MARGIN)
    if self.total_online_capacity_mw < required:
        next_gen = next((g for g in self.generators if g.state == GeneratorState.OFFLINE), None)
        if next_gen:
            self._start_generator(next_gen)   # 3-second start delay
```

### LoadManagementAgent

Simulates 17 vessel loads across five priority tiers using sinusoidal demand profiles with Gaussian noise. Applies QAOA-computed allocations. Performs **automatic load shedding** from FLEXIBLE upward when generation is insufficient, and restores loads as capacity recovers.

| Priority | Loads | Sheddable |
|---|---|---|
| `CRITICAL` | Navigation, communications, fire safety, emergency standby | Never |
| `ESSENTIAL` | Propulsion ×2, steering gear, bow thruster | Never |
| `IMPORTANT` | HVAC, cooling pumps, bilge/ballast pumps, fuel pumps | Last resort |
| `DEFERRABLE` | Galley, laundry, general lighting | Yes |
| `FLEXIBLE` | Cargo refrigeration, crew hotel loads | First |

### FaultDetectionAgent

Monitors 10 electrical channels (bus voltages, generator currents, frequency, power factor, thermal readings) using `QuantumAnomalyDetector`. Each reading is normalised to a Z-score, encoded as a rotation angle in a parameterised quantum circuit, and measured to produce a `p_anomaly` probability.

```python
def _quantum_threshold_circuit(self, z_score: float) -> QuantumCircuit:
    angle = float(np.arctan(abs(z_score)) * 2)
    qc.h(range(n))
    for i in range(n):
        qc.ry(angle / (i + 1), i)   # encode z-score as rotation
    for i in range(n - 1):
        qc.cx(i, i + 1)             # entangle for interference
    qc.measure(n - 1, 0)
```

### FuelEfficiencyAgent

Models each generator's specific fuel consumption (SFC) using the **Willans-line approximation**: `SFC = a/x + b + cx` where `x` is load fraction. Evaluates all generator subset combinations to find the merit-order dispatch minimising aggregate fuel rate at any given demand.

### VesselPMSOrchestratorAgent

Coordinates all agents via `asyncio.gather()`. Runs a 1-second status loop and a 5-second quantum decision loop. Broadcasts complete system state snapshots to all connected dashboard clients. Handles load shedding decisions and fuel tracking.

---

## Quantum Layer

### QAOA Power Allocation (`VesselPowerQAOA`)

The Quantum Approximate Optimisation Algorithm encodes the power allocation problem as a Hamiltonian over `n=6` qubits. Each qubit represents one load. The cost Hamiltonian penalises both under-allocation and capacity violations; load priorities are encoded as multiplicative weights.

```python
# p=2 QAOA layers over 6 qubits
for layer in range(self.n_layers):
    # Cost unitary: pairwise RZZ + single-qubit RZ
    for i in range(n):
        for j in range(i + 1, n):
            coupling = cost_weights[i] * cost_weights[j]
            qc.rzz(2.0 * gamma[layer] * coupling, i, j)
        qc.rz(2.0 * gamma[layer] * cost_weights[i], i)
    # Mixing unitary
    for i in range(n):
        qc.rx(2.0 * beta[layer], i)
```

Optimal angles γ and β are found by classical grid search (6×6 = 36 evaluations at 512 shots each). The highest-probability bitstring is decoded to MW allocations scaled to available capacity.

**Backend:** Qiskit `AerSimulator` (classical simulation). Migration to real IBM Quantum hardware requires only swapping the backend — circuit structure is unchanged.

### Quantum Anomaly Detection (`QuantumAnomalyDetector`)

Uses amplitude estimation on a 4-qubit circuit to classify sensor readings. Historical baselines are fitted per channel; live readings are Z-scored and encoded as rotation angles. Measurement interference produces `p_anomaly ∈ [0,1]`:

- `p > 0.85` → `critical` alert
- `p > 0.60` → `warning` alert
- `p ≤ 0.60` → `normal`

---

## Dashboard

`dashboard/index.html` is a self-contained single-file dashboard. Open it directly in any browser — no server required.

**Panels:**
- **Power flow history** — 60-sample rolling Chart.js line chart (demand vs. generation)
- **Generator fleet** — state, output, efficiency, fuel rate per unit
- **Energy storage** — SoC%, output direction, animated bar
- **QAOA result** — utilisation %, best energy, solve time, per-load allocation bars, utilisation trend chart
- **Fault alerts** — quantum-detected anomalies with severity, channel, and timestamp
- **Load roster** — all 17 loads with priority, demand, allocation, and active state

When `api_server.py` is running, the dashboard auto-detects it and switches from simulation mode to live SocketIO streaming.

---

## API Reference

Base URL: `http://localhost:5000`

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Service health check |
| `GET` | `/api/state` | Full system state snapshot |
| `GET` | `/api/quantum/results?n=10` | Last N QAOA optimisation results |
| `GET` | `/api/faults/alerts` | Active unacknowledged alerts |
| `POST` | `/api/faults/acknowledge/<id>` | Acknowledge a fault alert |
| `GET` | `/api/loads` | Full load roster with current demand |
| `POST` | `/api/loads/<id>/toggle` | Toggle a load on or off |
| `GET` | `/api/fuel/merit_order` | Optimal generator dispatch plan |
| `GET` | `/api/generation` | Generator and ESS status |

**SocketIO:** namespace `/pms`, event `system_state` — full state JSON emitted every second.

---

## Simulation Results

18-tick verification run (all subsystems active):

| Metric | Value |
|---|---|
| Average demand | 6.68 MW |
| Average generation | 5.95 MW |
| QAOA calls | 3 |
| Mean QAOA solve time | 0.11 s |
| Generator boot to online | &lt; 9 s |
| Monitoring channels | 10 |
| Loads managed | 17 |

---

## Extending to Real Hardware

**Real quantum hardware:** Replace `AerSimulator` with an authenticated `IBMBackend`:

```python
from qiskit_ibm_runtime import QiskitRuntimeService
service = QiskitRuntimeService(channel="ibm_quantum", token="YOUR_TOKEN")
backend = service.least_busy(operational=True, simulator=False)
self.simulator = backend
```

**Real vessel telemetry:** Integrate IEC 61850 GOOSE messages for switchboard and generator telemetry; NMEA 2000 for propulsion demand. With 2–3 seconds of propulsion lookahead from waypoint + sea state data, the QAOA optimiser can pre-position the fleet rather than reacting after load surges.

---

## Dependencies

```
qiskit>=2.0.0
qiskit-aer>=0.17.0
flask>=3.0.0
flask-socketio>=5.0.0
numpy>=1.26.0
scipy>=1.12.0
```

---

## Citation

If you use this work in your research, please cite:

```bibtex
@software{chin2025quantum_vessel_pms,
  author    = {Chin, Cheng Siong},
  title     = {Quantum-Agentic Vessel Power Management System},
  year      = {2025},
  publisher = {GitHub},
  url       = {https://github.com/cschin/quantum-vessel-pms},
  note      = {Newcastle University--NVIDIA Joint Laboratory, Singapore}
}
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

<div align="center">

Developed at **Newcastle University–NVIDIA Joint Laboratory**, Singapore  
Prof. Cheng Siong Chin · NVIDIA Certified Instructor & DLI Ambassador · 170+ publications

</div>
