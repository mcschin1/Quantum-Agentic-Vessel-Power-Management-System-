"""
Load Management Agent
Tracks all vessel electrical loads, classifies them by priority,
simulates realistic demand curves, and interfaces with the quantum optimizer
to obtain optimal power allocation decisions.
"""

import asyncio
import random
import math
import time
import logging
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class LoadPriority(Enum):
    CRITICAL   = 1   # navigation, safety, comms — never shed
    ESSENTIAL  = 2   # propulsion, steering
    IMPORTANT  = 3   # accommodation HVAC, pumps
    DEFERRABLE = 4   # hotel loads, galley, non-essential
    FLEXIBLE   = 5   # EV charging, ballast, optional


@dataclass
class VesselLoad:
    id: str
    name: str
    priority: LoadPriority
    rated_mw: float
    current_demand_mw: float = 0.0
    allocated_mw: float = 0.0
    active: bool = True
    shedding_allowed: bool = True

    # Demand profile parameters
    base_fraction: float = 0.70    # base load as fraction of rated
    variation: float = 0.15        # random variation ±
    period_s: float = 60.0         # sinusoidal fluctuation period

    def simulate_demand(self, t: float) -> None:
        if not self.active:
            self.current_demand_mw = 0.0
            return
        sine_comp = self.variation * math.sin(2 * math.pi * t / self.period_s)
        noise = random.gauss(0, self.variation * 0.3)
        fraction = max(0.1, min(1.0, self.base_fraction + sine_comp + noise))
        self.current_demand_mw = round(self.rated_mw * fraction, 4)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["priority"] = self.priority.name
        d["priority_level"] = self.priority.value
        return d


class LoadManagementAgent:
    """
    Agentic load controller for the vessel.

    Responsibilities:
      - Simulate realistic demand profiles for all loads
      - Apply quantum-optimised power allocations
      - Perform automatic load shedding when generation is insufficient
      - Restore loads as generation recovers
      - Report demand forecasts to orchestrator
    """

    def __init__(self):
        self.loads: List[VesselLoad] = self._create_vessel_loads()
        self.tick: int = 0
        self._running: bool = False
        self.last_allocation: Optional[Dict] = None
        self.shed_history: List[Dict] = []
        logger.info(f"LoadManagementAgent initialised with {len(self.loads)} loads")

    # ------------------------------------------------------------------
    # Load definitions — realistic vessel power consumers
    # ------------------------------------------------------------------

    def _create_vessel_loads(self) -> List[VesselLoad]:
        return [
            # ---- CRITICAL (never shed) ----
            VesselLoad("NAV",  "Navigation & ECDIS",    LoadPriority.CRITICAL,   0.08, base_fraction=0.95, variation=0.03),
            VesselLoad("COMM", "Communications",        LoadPriority.CRITICAL,   0.05, base_fraction=0.90, variation=0.05),
            VesselLoad("FIRE", "Fire & safety systems", LoadPriority.CRITICAL,   0.12, base_fraction=0.85, variation=0.05, shedding_allowed=False),
            VesselLoad("STBY", "Emergency standby",     LoadPriority.CRITICAL,   0.04, base_fraction=0.70, variation=0.05, shedding_allowed=False),

            # ---- ESSENTIAL ----
            VesselLoad("PROP1","Main propulsion P1",    LoadPriority.ESSENTIAL,  3.50, base_fraction=0.75, variation=0.15, period_s=120),
            VesselLoad("PROP2","Main propulsion P2",    LoadPriority.ESSENTIAL,  3.50, base_fraction=0.70, variation=0.15, period_s=100),
            VesselLoad("STEER","Steering gear",         LoadPriority.ESSENTIAL,  0.40, base_fraction=0.60, variation=0.20, period_s=30),
            VesselLoad("BOW",  "Bow thruster",          LoadPriority.ESSENTIAL,  1.20, base_fraction=0.30, variation=0.30, period_s=45),

            # ---- IMPORTANT ----
            VesselLoad("HVAC", "HVAC — accommodation",  LoadPriority.IMPORTANT,  1.20, base_fraction=0.80, variation=0.10, period_s=300),
            VesselLoad("PUMP", "Cooling water pumps",   LoadPriority.IMPORTANT,  0.30, base_fraction=0.85, variation=0.08),
            VesselLoad("BILGE","Bilge & ballast pumps", LoadPriority.IMPORTANT,  0.25, base_fraction=0.40, variation=0.25, period_s=90),
            VesselLoad("FUEL", "Fuel oil service pumps",LoadPriority.IMPORTANT,  0.18, base_fraction=0.70, variation=0.10),

            # ---- DEFERRABLE ----
            VesselLoad("GAL",  "Galley & catering",     LoadPriority.DEFERRABLE, 0.60, base_fraction=0.65, variation=0.25, period_s=180),
            VesselLoad("LAUN", "Laundry",               LoadPriority.DEFERRABLE, 0.15, base_fraction=0.50, variation=0.30),
            VesselLoad("LIT",  "General lighting",      LoadPriority.DEFERRABLE, 0.20, base_fraction=0.80, variation=0.10, period_s=600),

            # ---- FLEXIBLE ----
            VesselLoad("CRGO", "Cargo refrigeration",   LoadPriority.FLEXIBLE,   0.80, base_fraction=0.60, variation=0.20, period_s=240),
            VesselLoad("BUNK", "Crew hotel loads",      LoadPriority.FLEXIBLE,   0.35, base_fraction=0.70, variation=0.20),
        ]

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def total_demand_mw(self) -> float:
        return sum(l.current_demand_mw for l in self.loads if l.active)

    @property
    def critical_demand_mw(self) -> float:
        return sum(
            l.current_demand_mw for l in self.loads
            if l.active and l.priority == LoadPriority.CRITICAL
        )

    # ------------------------------------------------------------------
    # Allocation and shedding
    # ------------------------------------------------------------------

    def apply_allocation(self, allocation_mw: List[float]) -> None:
        """
        Apply quantum-optimised allocation to loads.
        allocation_mw corresponds to the first N loads by priority order.
        """
        for i, load in enumerate(self.loads[:len(allocation_mw)]):
            load.allocated_mw = max(0.0, allocation_mw[i])
        self.last_allocation = {"time": time.time(), "values": allocation_mw}

    def auto_shed(self, available_mw: float) -> List[str]:
        """
        Shed non-critical loads until total demand <= available.
        Returns list of shed load IDs.
        """
        shed_ids = []
        current = self.total_demand_mw

        # Shed from lowest priority upward
        for priority in [LoadPriority.FLEXIBLE, LoadPriority.DEFERRABLE, LoadPriority.IMPORTANT]:
            if current <= available_mw * 0.95:
                break
            for load in self.loads:
                if (load.priority == priority and load.active and load.shedding_allowed):
                    load.active = False
                    current -= load.current_demand_mw
                    load.current_demand_mw = 0.0
                    shed_ids.append(load.id)
                    logger.warning(f"Shed load {load.id} ({load.name}), available={available_mw:.2f} MW")
                    if current <= available_mw * 0.95:
                        break

        if shed_ids:
            self.shed_history.append({"tick": self.tick, "shed": shed_ids, "available_mw": available_mw})
        return shed_ids

    def restore_loads(self, available_mw: float) -> List[str]:
        """Restore previously shed loads if capacity allows."""
        restored = []
        for priority in [LoadPriority.IMPORTANT, LoadPriority.DEFERRABLE, LoadPriority.FLEXIBLE]:
            for load in self.loads:
                if (load.priority == priority and not load.active and load.shedding_allowed):
                    headroom = available_mw - self.total_demand_mw
                    if headroom > load.rated_mw * 0.5:
                        load.active = True
                        restored.append(load.id)
                        logger.info(f"Restored load {load.id}")
        return restored

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self, dt_s: float = 1.0) -> None:
        self._running = True
        while self._running:
            t = self.tick * dt_s
            for load in self.loads:
                load.simulate_demand(t)
            self.tick += 1
            await asyncio.sleep(dt_s)

    def get_demand_vector(self, n: int) -> List[float]:
        """Return demand for first n loads (for quantum optimizer input)."""
        return [l.current_demand_mw for l in self.loads[:n]]

    def get_status(self) -> Dict:
        return {
            "loads": [l.to_dict() for l in self.loads],
            "total_demand_mw": round(self.total_demand_mw, 3),
            "critical_demand_mw": round(self.critical_demand_mw, 3),
            "active_loads": sum(1 for l in self.loads if l.active),
            "shed_loads": sum(1 for l in self.loads if not l.active),
            "tick": self.tick,
        }
