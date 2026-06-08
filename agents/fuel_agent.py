"""
Fuel Efficiency Agent
Tracks fuel consumption, computes SFC curves, and advises the generation
agent on which generator combination achieves the lowest specific fuel
consumption for the current load level.
"""

import asyncio
import math
import time
import logging
import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


@dataclass
class GeneratorSFCModel:
    """
    Specific Fuel Consumption model: SFC = a/x + b + c*x (Willans line)
    where x = load fraction (0-1), SFC in g/kWh.
    """
    gen_id: str
    rated_mw: float
    a: float = 40.0   # part-load penalty coefficient
    b: float = 195.0  # minimum SFC at optimal load (~0.7)
    c: float = 15.0   # overload penalty

    def sfc_g_per_kwh(self, load_fraction: float) -> float:
        x = max(0.01, min(1.0, load_fraction))
        return self.a / x + self.b + self.c * x

    def fuel_rate_kg_h(self, output_mw: float) -> float:
        lf = output_mw / self.rated_mw
        sfc = self.sfc_g_per_kwh(lf)
        return (sfc * output_mw * 1000) / 1e6  # MW → kW, g → kg


class FuelEfficiencyAgent:
    """
    Monitors and optimises fuel consumption across the generator fleet.
    Uses a merit order dispatch: prefer generators at their sweet-spot
    load fraction (~0.70–0.80) to minimise aggregate SFC.
    """

    OPTIMAL_LOAD_FRACTION = 0.75

    def __init__(self):
        self.models: List[GeneratorSFCModel] = [
            GeneratorSFCModel("DG1", 4.0, a=38, b=192, c=14),
            GeneratorSFCModel("DG2", 4.0, a=40, b=195, c=15),
            GeneratorSFCModel("DG3", 3.0, a=35, b=188, c=16),
            GeneratorSFCModel("DG4", 3.0, a=42, b=198, c=14),  # standby — less maintained
        ]
        self.fuel_consumed_kg: float = 0.0
        self.energy_generated_mwh: float = 0.0
        self.tick: int = 0
        self._history: List[Dict] = []
        self._running: bool = False
        logger.info("FuelEfficiencyAgent initialised")

    # ------------------------------------------------------------------
    # Merit order dispatch
    # ------------------------------------------------------------------

    def compute_merit_order(self, total_demand_mw: float) -> Dict:
        """
        Determine the optimal set of generators and their loading
        to minimise total SFC for the given demand.

        Returns the recommended dispatch plan.
        """
        n = len(self.models)
        best_total_fuel = float("inf")
        best_plan: Dict = {}

        # Try all non-empty subsets (2^n combinations, feasible for n=4)
        for mask in range(1, 1 << n):
            selected = [self.models[i] for i in range(n) if mask & (1 << i)]
            total_cap = sum(m.rated_mw for m in selected)

            if total_cap < total_demand_mw:
                continue  # infeasible

            # Equal sharing weighted by rated capacity
            plan_fuel = 0.0
            plan = {}
            for m in selected:
                share = total_demand_mw * (m.rated_mw / total_cap)
                fuel = m.fuel_rate_kg_h(share)
                plan_fuel += fuel
                plan[m.gen_id] = {
                    "output_mw": round(share, 3),
                    "load_fraction": round(share / m.rated_mw, 3),
                    "sfc_g_kwh": round(m.sfc_g_per_kwh(share / m.rated_mw), 1),
                    "fuel_rate_kg_h": round(fuel, 3),
                }

            if plan_fuel < best_total_fuel:
                best_total_fuel = plan_fuel
                best_plan = plan

        aggregate_sfc = (best_total_fuel / max(total_demand_mw, 0.01)) * 1000 if best_plan else 0
        return {
            "demand_mw": round(total_demand_mw, 3),
            "optimal_dispatch": best_plan,
            "total_fuel_rate_kg_h": round(best_total_fuel, 3),
            "aggregate_sfc_g_kwh": round(aggregate_sfc, 1),
            "generators_used": list(best_plan.keys()),
        }

    # ------------------------------------------------------------------
    # Real-time tracking
    # ------------------------------------------------------------------

    def record_generation(self, gen_outputs: Dict[str, float], dt_s: float) -> None:
        """Update cumulative fuel and energy counters."""
        dt_h = dt_s / 3600.0
        for m in self.models:
            output = gen_outputs.get(m.gen_id, 0.0)
            if output > 0:
                self.fuel_consumed_kg += m.fuel_rate_kg_h(output) * dt_h
                self.energy_generated_mwh += output * dt_h

    def overall_sfc(self) -> float:
        if self.energy_generated_mwh < 1e-9:
            return 0.0
        return (self.fuel_consumed_kg / self.energy_generated_mwh) * 1000  # g/kWh

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self, dt_s: float = 1.0) -> None:
        self._running = True
        while self._running:
            self.tick += 1
            await asyncio.sleep(dt_s)

    def get_status(self) -> Dict:
        return {
            "fuel_consumed_kg": round(self.fuel_consumed_kg, 2),
            "energy_generated_mwh": round(self.energy_generated_mwh, 4),
            "overall_sfc_g_kwh": round(self.overall_sfc(), 1),
            "sfc_models": [
                {"id": m.gen_id, "rated_mw": m.rated_mw, "optimal_sfc": round(m.sfc_g_per_kwh(0.75), 1)}
                for m in self.models
            ],
            "tick": self.tick,
        }
