"""
Master Orchestrator Agent
Top-level agentic controller that coordinates:
  - PowerGenerationAgent
  - LoadManagementAgent
  - FaultDetectionAgent
  - FuelEfficiencyAgent
  - VesselPowerQAOA (quantum optimizer)

Runs a continuous decision cycle:
  1. Collect status from all sub-agents
  2. Feed load demand to quantum optimizer
  3. Apply optimal allocation to load agent
  4. Update generation agent with total demand
  5. Request fuel-optimal dispatch plan
  6. Broadcast system state
"""

import asyncio
import time
import logging
import json
import sys
import os
from typing import Dict, Optional, Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agents.generation_agent import PowerGenerationAgent
from agents.load_agent       import LoadManagementAgent
from agents.fault_agent      import FaultDetectionAgent
from agents.fuel_agent       import FuelEfficiencyAgent
from quantum.quantum_optimizer import VesselPowerQAOA

import numpy as np

logger = logging.getLogger(__name__)


class VesselPMSOrchestratorAgent:
    """
    Quantum-Agentic Vessel Power Management System orchestrator.

    Decision cycle period: configurable (default 5 s between quantum calls,
    1 s between status updates).
    """

    QUANTUM_CYCLE_S = 5      # how often to invoke the QAOA optimizer
    STATUS_CYCLE_S  = 1      # how often to refresh state

    def __init__(self, n_quantum_loads: int = 6, on_state_update: Optional[Callable] = None):
        self.generation_agent = PowerGenerationAgent()
        self.load_agent       = LoadManagementAgent()
        self.fault_agent      = FaultDetectionAgent()
        self.fuel_agent       = FuelEfficiencyAgent()
        self.quantum_opt      = VesselPowerQAOA(n_loads=n_quantum_loads, n_layers=2, shots=512)

        self.n_quantum_loads  = n_quantum_loads
        self.on_state_update  = on_state_update   # optional websocket callback
        self.system_state: Dict = {}
        self.quantum_results: list = []
        self.tick: int = 0
        self._running: bool = False
        self._last_quantum_tick: int = 0

        logger.info("VesselPMSOrchestratorAgent ready")

    # ------------------------------------------------------------------
    # Core decision cycle
    # ------------------------------------------------------------------

    async def _quantum_decision(self) -> None:
        """Run QAOA optimisation and push results to load agent."""
        demands = np.array(self.load_agent.get_demand_vector(self.n_quantum_loads))
        available = self.generation_agent.total_generation_mw

        if demands.sum() < 0.01 or available < 0.01:
            return

        # Priority weights: invert priority level so critical=1 → highest weight
        priorities = np.array([
            1.0 / l.priority.value
            for l in self.load_agent.loads[:self.n_quantum_loads]
        ])

        result = self.quantum_opt.optimise(demands, available, priorities)
        self.load_agent.apply_allocation(result["allocation_mw"])
        self.quantum_results.append({**result, "tick": self.tick})

        # Keep last 100 results
        if len(self.quantum_results) > 100:
            self.quantum_results = self.quantum_results[-100:]

        logger.info(
            f"[QAOA tick={self.tick}] alloc={[round(x,2) for x in result['allocation_mw']]} "
            f"util={result['utilisation_pct']:.1f}%"
        )

    def _load_shedding_check(self) -> None:
        """Automatic load shedding / restoration."""
        available = self.generation_agent.total_generation_mw
        demand    = self.load_agent.total_demand_mw
        headroom  = available - demand

        if headroom < -0.3:
            shed = self.load_agent.auto_shed(available)
            if shed:
                logger.warning(f"Load shed activated: {shed}")
        elif headroom > 1.0:
            restored = self.load_agent.restore_loads(available)
            if restored:
                logger.info(f"Loads restored: {restored}")

    def _fuel_tracking(self) -> None:
        """Update fuel efficiency agent with current generator outputs."""
        gen_outputs = {
            g["id"]: g["output_mw"]
            for g in self.generation_agent.get_status()["generators"]
        }
        self.fuel_agent.record_generation(gen_outputs, self.STATUS_CYCLE_S)

    # ------------------------------------------------------------------
    # State aggregation
    # ------------------------------------------------------------------

    def _build_system_state(self) -> Dict:
        gen_status  = self.generation_agent.get_status()
        load_status = self.load_agent.get_status()
        fault_status = self.fault_agent.get_status()
        fuel_status = self.fuel_agent.get_status()

        latest_quantum = self.quantum_results[-1] if self.quantum_results else {}

        total_demand = load_status["total_demand_mw"]
        total_gen    = gen_status["total_generation_mw"]
        balance      = total_gen - total_demand

        return {
            "timestamp": time.time(),
            "tick": self.tick,
            "system": {
                "total_demand_mw":     round(total_demand, 3),
                "total_generation_mw": round(total_gen, 3),
                "power_balance_mw":    round(balance, 3),
                "frequency_ok":        abs(balance) < 0.5,
                "n_active_loads":      load_status["active_loads"],
                "n_shed_loads":        load_status["shed_loads"],
                "fuel_rate_kg_h":      gen_status["fuel_rate_kg_h"],
                "overall_sfc_g_kwh":   fuel_status["overall_sfc_g_kwh"],
            },
            "generation":  gen_status,
            "loads":       load_status,
            "faults":      fault_status,
            "fuel":        fuel_status,
            "quantum":     latest_quantum,
        }

    # ------------------------------------------------------------------
    # Main orchestration loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        self._running = True
        logger.info("Orchestrator starting all sub-agents...")

        # Launch sub-agent coroutines
        await asyncio.gather(
            self._run_orchestration_loop(),
            self.generation_agent.run(dt_s=self.STATUS_CYCLE_S),
            self.load_agent.run(dt_s=self.STATUS_CYCLE_S),
            self.fault_agent.run(dt_s=self.STATUS_CYCLE_S),
            self.fuel_agent.run(dt_s=self.STATUS_CYCLE_S),
        )

    async def _run_orchestration_loop(self) -> None:
        quantum_countdown = self.QUANTUM_CYCLE_S

        while self._running:
            await asyncio.sleep(self.STATUS_CYCLE_S)
            self.tick += 1

            # Update generation agent with current total demand
            self.generation_agent.update_demand(self.load_agent.total_demand_mw)

            # Load shedding check every tick
            self._load_shedding_check()

            # Fuel tracking every tick
            self._fuel_tracking()

            # Quantum optimisation every N ticks
            quantum_countdown -= self.STATUS_CYCLE_S
            if quantum_countdown <= 0:
                await self._quantum_decision()
                quantum_countdown = self.QUANTUM_CYCLE_S

            # Build and broadcast system state
            self.system_state = self._build_system_state()
            if self.on_state_update:
                try:
                    self.on_state_update(self.system_state)
                except Exception as e:
                    logger.debug(f"State callback error: {e}")

    def get_state(self) -> Dict:
        return self.system_state

    def stop(self) -> None:
        self._running = False
        self.generation_agent._running = False
        self.load_agent._running = False
        self.fault_agent._running = False
        self.fuel_agent._running = False
        logger.info("Orchestrator stopped")
