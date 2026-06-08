# Quantum-Agentic Vessel Power Management System

**MV Newcastle Quantum — Autonomous Power Management**

A full-stack Python implementation of a quantum-enhanced agentic AI system
for autonomous vessel power management. Combines QAOA (Quantum Approximate
Optimisation Algorithm) with a multi-agent architecture for real-time power
distribution, fault detection, and fuel optimisation.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│              VesselPMSOrchestratorAgent                  │
│  ┌────────────┐  ┌────────────┐  ┌────────────────────┐ │
│  │ Generation │  │    Load    │  │  Fault Detection   │ │
│  │   Agent    │  │   Agent    │  │      Agent         │ │
│  │  4× DG     │  │  17 loads  │  │  10 channels       │ │
│  │  2× ESS    │  │  5 levels  │  │  Quantum anomaly   │ │
│  └─────┬──────┘  └─────┬──────┘  └────────────────────┘ │
│        │               │  demand vector                  │
│        │        ┌──────▼──────────┐                      │
│        │        │  VesselPowerQAOA│ ← QAOA optimiser     │
│        │        │  6-qubit, p=2   │   (Qiskit Aer)       │
│        │        └──────┬──────────┘                      │
│        │ update_demand │ allocation                      │
│        ◄───────────────┘                                 │
│        │         ┌──────────────┐                        │
│        └────────►│  Fuel Agent  │  merit-order dispatch  │
│                  └──────────────┘                        │
└─────────────────────────────────────────────────────────┘
          │
   Flask REST API + SocketIO
          │
   dashboard/index.html (real-time)
```

---

## File Structure

```
quantum_vessel_pms/
├── quantum/
│   └── quantum_optimizer.py     # QAOA power allocator + quantum anomaly detector
├── agents/
│   ├── orchestrator.py          # Master multi-agent coordinator
│   ├── generation_agent.py      # Generator & ESS management
│   ├── load_agent.py            # 17-load vessel roster + shedding
│   ├── fault_agent.py           # 10-channel quantum fault detection
│   └── fuel_agent.py            # SFC optimisation & merit order
├── dashboard/
│   └── index.html               # Real-time HTML5 dashboard
├── config/
│   └── config.json              # System configuration
├── api_server.py                # Flask + SocketIO API server
├── run_simulation.py            # Standalone simulation runner
└── simulation_report.json       # Output from last simulation run
```

---

## Quantum Components

### VesselPowerQAOA (QAOA Power Allocation)
- **Algorithm**: QAOA with p=2 layers over 6 qubits
- **Problem**: Weighted power allocation across priority loads
- **Solver**: Classical grid search over γ/β angles → expectation value minimisation
- **Backend**: Qiskit Aer `AerSimulator` (512 shots per evaluation)
- **Trigger**: Every 5 seconds of real-time simulation

### QuantumAnomalyDetector
- **Algorithm**: Amplitude estimation via parameterised quantum circuit
- **Input**: Z-score of each sensor reading vs historical baseline
- **Output**: `p_anomaly` (0–1) → severity classification
- **Channels**: Bus voltages, generator currents, frequency, power factor, temperatures

---

## Agents

| Agent | Role | Decision cycle |
|---|---|---|
| `PowerGenerationAgent` | Start/stop generators, dispatch ESS | 1 s |
| `LoadManagementAgent` | Simulate demand, apply allocations, shed loads | 1 s |
| `FaultDetectionAgent` | Quantum anomaly detection on 10 channels | 1 s |
| `FuelEfficiencyAgent` | SFC tracking, merit-order dispatch advice | 1 s |
| `VesselPMSOrchestratorAgent` | Coordinates all agents, calls QAOA | 5 s (QAOA) / 1 s (status) |

---

## Vessel Load Roster

| Priority | Loads |
|---|---|
| CRITICAL | Navigation, Communications, Fire & safety, Emergency standby |
| ESSENTIAL | Propulsion ×2, Steering gear, Bow thruster |
| IMPORTANT | HVAC, Cooling pumps, Bilge/ballast pumps, Fuel pumps |
| DEFERRABLE | Galley, Laundry, General lighting |
| FLEXIBLE | Cargo refrigeration, Crew hotel loads |

---

## Running

### Quick simulation test (no server required)
```bash
cd quantum_vessel_pms
python run_simulation.py --ticks 30 --report-every 5
```

### Full API server + dashboard
```bash
python api_server.py
# Server at http://localhost:5000
# Dashboard at http://localhost:5000  (serve dashboard/index.html separately)
```

### REST API endpoints
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/state` | Full system state snapshot |
| GET | `/api/quantum/results?n=10` | Last N QAOA results |
| GET | `/api/faults/alerts` | Active alerts |
| POST | `/api/faults/acknowledge/<id>` | Acknowledge alert |
| GET | `/api/loads` | Load roster + demand |
| POST | `/api/loads/<id>/toggle` | Toggle load on/off |
| GET | `/api/fuel/merit_order` | Optimal dispatch plan |
| GET | `/api/generation` | Generator + ESS status |

---

## Dependencies
```
qiskit >= 2.0
qiskit-aer >= 0.17
flask >= 3.0
flask-socketio >= 5.0
numpy, scipy, matplotlib, pandas
```

---

## Reference

This system demonstrates:
- **QAOA** for combinatorial power allocation (maritime IEC 60092 context)
- **Multi-agent coordination** with autonomous fault response
- **Quantum amplitude estimation** for anomaly detection
- **Agentic AI** decision loops (generation ↔ load ↔ fuel ↔ fault)

Developed at Newcastle University–NVIDIA Joint Laboratory.
