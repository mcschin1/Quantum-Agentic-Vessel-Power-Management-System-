"""
Standalone Simulation Runner
Runs the full quantum-agentic vessel PMS for a fixed number of ticks
and writes a JSON report. Use this to verify all subsystems work
before starting the Flask API server.

Usage:
    python run_simulation.py [--ticks 30]
"""

import asyncio
import argparse
import json
import logging
import sys
import os
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from agents.orchestrator import VesselPMSOrchestratorAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-30s] %(levelname)s %(message)s",
)
logger = logging.getLogger("simulation")


async def run(max_ticks: int = 20, report_every: int = 5) -> dict:
    """Run simulation for max_ticks seconds and return final state."""

    snapshots = []

    def capture(state):
        snapshots.append({
            "tick":       state.get("tick"),
            "demand_mw":  state.get("system", {}).get("total_demand_mw"),
            "gen_mw":     state.get("system", {}).get("total_generation_mw"),
            "balance_mw": state.get("system", {}).get("power_balance_mw"),
            "fuel_kg_h":  state.get("system", {}).get("fuel_rate_kg_h"),
            "sfc_g_kwh":  state.get("system", {}).get("overall_sfc_g_kwh"),
            "alerts":     len(state.get("faults", {}).get("active_alerts", [])),
            "q_util_pct": state.get("quantum", {}).get("utilisation_pct"),
            "q_solve_s":  state.get("quantum", {}).get("solve_time_s"),
        })
        if state.get("tick", 0) % report_every == 0:
            s = snapshots[-1]
            logger.info(
                f"tick={s['tick']:4d} | "
                f"demand={s['demand_mw']:6.2f} MW | "
                f"gen={s['gen_mw']:6.2f} MW | "
                f"bal={s['balance_mw']:+.2f} | "
                f"fuel={s['fuel_kg_h']:6.1f} kg/h | "
                f"SFC={s['sfc_g_kwh']} g/kWh | "
                f"alerts={s['alerts']} | "
                f"Q_util={s['q_util_pct']}%"
            )

    orch = VesselPMSOrchestratorAgent(n_quantum_loads=6, on_state_update=capture)

    async def stop_after(n):
        await asyncio.sleep(n)
        orch.stop()

    await asyncio.gather(
        orch.run(),
        stop_after(max_ticks),
        return_exceptions=True,
    )
    return {"snapshots": snapshots, "final_state": orch.system_state}


def main():
    parser = argparse.ArgumentParser(description="Vessel PMS Simulation Runner")
    parser.add_argument("--ticks", type=int, default=20, help="Simulation ticks (seconds)")
    parser.add_argument("--report-every", type=int, default=5, help="Print every N ticks")
    parser.add_argument("--output", type=str, default="simulation_report.json")
    args = parser.parse_args()

    logger.info(f"Starting {args.ticks}-tick simulation...")
    t0 = time.time()

    result = asyncio.run(run(args.ticks, args.report_every))

    elapsed = time.time() - t0
    logger.info(f"Simulation complete in {elapsed:.1f}s")

    # Write report
    report_path = os.path.join(os.path.dirname(__file__), args.output)
    with open(report_path, "w") as f:
        json.dump(result["snapshots"], f, indent=2, default=str)
    logger.info(f"Report written to {report_path}")

    # Print summary
    snaps = result["snapshots"]
    if snaps:
        valid = [s for s in snaps if s["demand_mw"] is not None]
        if valid:
            avg_demand = sum(s["demand_mw"] for s in valid) / len(valid)
            avg_gen    = sum(s["gen_mw"]    for s in valid) / len(valid)
            q_solves   = [s for s in valid if s["q_util_pct"] is not None]

            print("\n" + "="*60)
            print("  SIMULATION SUMMARY")
            print("="*60)
            print(f"  Total ticks simulated  : {len(snaps)}")
            print(f"  Avg demand             : {avg_demand:.2f} MW")
            print(f"  Avg generation         : {avg_gen:.2f} MW")
            print(f"  QAOA calls             : {len(q_solves)}")
            if q_solves:
                avg_util = sum(s["q_util_pct"] for s in q_solves) / len(q_solves)
                avg_st   = sum(s["q_solve_s"]  for s in q_solves) / len(q_solves)
                print(f"  Avg QAOA utilisation   : {avg_util:.1f}%")
                print(f"  Avg QAOA solve time    : {avg_st:.2f}s")
            print(f"  Report saved to        : {report_path}")
            print("="*60)


if __name__ == "__main__":
    main()
