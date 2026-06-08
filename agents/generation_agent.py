"""
Power Generation Agent
Autonomous agent that monitors diesel generators and energy storage,
decides which units to start/stop, and reports generation capacity.
"""

import asyncio
import random
import time
import logging
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class GeneratorState(Enum):
    OFFLINE  = "offline"
    STARTING = "starting"
    ONLINE   = "online"
    STOPPING = "stopping"
    FAULT    = "fault"


@dataclass
class Generator:
    id: str
    rated_mw: float
    state: GeneratorState = GeneratorState.OFFLINE
    output_mw: float = 0.0
    fuel_rate_kg_h: float = 0.0
    runtime_h: float = 0.0
    efficiency: float = 0.92          # degrades over runtime
    fault_probability: float = 0.002  # per tick

    def tick(self, dt_s: float = 1.0) -> None:
        """Advance simulation by dt_s seconds."""
        if self.state == GeneratorState.ONLINE:
            self.runtime_h += dt_s / 3600.0
            # Efficiency degrades slowly
            self.efficiency = max(0.70, 0.92 - self.runtime_h * 5e-5)
            self.fuel_rate_kg_h = (self.output_mw / self.efficiency) * 220  # kg/MWh * MW
            # Random fault injection
            if random.random() < self.fault_probability:
                self.state = GeneratorState.FAULT
                self.output_mw = 0.0
                logger.warning(f"Generator {self.id} FAULT triggered")

    def set_output(self, mw: float) -> None:
        if self.state == GeneratorState.ONLINE:
            self.output_mw = max(0.0, min(mw, self.rated_mw))

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["state"] = self.state.value
        return d


@dataclass
class EnergyStorage:
    id: str
    capacity_mwh: float
    soc: float = 0.80              # state of charge 0-1
    max_charge_mw: float = 2.0
    max_discharge_mw: float = 2.0
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    output_mw: float = 0.0         # positive = discharging

    def tick(self, dt_s: float = 1.0) -> None:
        dt_h = dt_s / 3600.0
        if self.output_mw > 0:  # discharging
            delta = (self.output_mw * dt_h) / (self.discharge_efficiency * self.capacity_mwh)
            self.soc = max(0.0, self.soc - delta)
        elif self.output_mw < 0:  # charging
            delta = (abs(self.output_mw) * self.charge_efficiency * dt_h) / self.capacity_mwh
            self.soc = min(1.0, self.soc + delta)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "capacity_mwh": self.capacity_mwh,
            "soc_pct": round(self.soc * 100, 1),
            "output_mw": round(self.output_mw, 3),
            "max_charge_mw": self.max_charge_mw,
            "max_discharge_mw": self.max_discharge_mw,
        }


class PowerGenerationAgent:
    """
    Agentic controller for vessel power generation.

    Decision loop:
      1. Assess total demand from load agent
      2. Determine minimum generation fleet to meet demand + 15% reserve
      3. Start/stop generators as needed
      4. Dispatch energy storage to cover transient gaps
      5. Report generation status
    """

    RESERVE_MARGIN = 0.15  # 15% spinning reserve

    def __init__(self):
        self.generators: List[Generator] = [
            Generator("DG1", rated_mw=4.0),
            Generator("DG2", rated_mw=4.0),
            Generator("DG3", rated_mw=3.0),
            Generator("DG4", rated_mw=3.0),  # emergency standby
        ]
        self.storage: List[EnergyStorage] = [
            EnergyStorage("ESS1", capacity_mwh=4.0),
            EnergyStorage("ESS2", capacity_mwh=2.0),
        ]
        self.target_demand_mw: float = 0.0
        self.tick_count: int = 0
        self._running: bool = False
        logger.info("PowerGenerationAgent initialised")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def total_online_capacity_mw(self) -> float:
        return sum(g.rated_mw for g in self.generators if g.state == GeneratorState.ONLINE)

    @property
    def total_generation_mw(self) -> float:
        gen = sum(g.output_mw for g in self.generators if g.state == GeneratorState.ONLINE)
        ess = sum(s.output_mw for s in self.storage)
        return gen + ess

    @property
    def total_fuel_rate_kg_h(self) -> float:
        return sum(g.fuel_rate_kg_h for g in self.generators if g.state == GeneratorState.ONLINE)

    # ------------------------------------------------------------------
    # Agent actions
    # ------------------------------------------------------------------

    def _required_capacity(self) -> float:
        return self.target_demand_mw * (1 + self.RESERVE_MARGIN)

    def _start_generator(self, gen: Generator) -> None:
        if gen.state == GeneratorState.OFFLINE:
            gen.state = GeneratorState.STARTING
            asyncio.get_event_loop().call_later(3, self._finish_start, gen)

    def _finish_start(self, gen: Generator) -> None:
        if gen.state == GeneratorState.STARTING:
            gen.state = GeneratorState.ONLINE
            logger.info(f"{gen.id} online ({gen.rated_mw} MW)")

    def _stop_generator(self, gen: Generator) -> None:
        if gen.state == GeneratorState.ONLINE:
            gen.state = GeneratorState.STOPPING
            gen.output_mw = 0.0
            asyncio.get_event_loop().call_later(2, self._finish_stop, gen)

    def _finish_stop(self, gen: Generator) -> None:
        if gen.state == GeneratorState.STOPPING:
            gen.state = GeneratorState.OFFLINE

    def _dispatch_generation(self) -> None:
        """Distribute target demand among online generators evenly."""
        online = [g for g in self.generators if g.state == GeneratorState.ONLINE]
        if not online:
            return
        share = self.target_demand_mw / len(online)
        for g in online:
            g.set_output(share)

    def _manage_storage(self) -> None:
        """Charge ESS if surplus; discharge if deficit."""
        gap = self.target_demand_mw - sum(
            g.output_mw for g in self.generators if g.state == GeneratorState.ONLINE
        )
        for s in self.storage:
            if gap > 0 and s.soc > 0.20:
                s.output_mw = min(gap, s.max_discharge_mw)
                gap -= s.output_mw
            elif gap < -0.5 and s.soc < 0.90:
                s.output_mw = max(-s.max_charge_mw, gap)
            else:
                s.output_mw = 0.0

    def _fleet_management(self) -> None:
        """Start/stop generators based on required capacity."""
        required = self._required_capacity()
        online_cap = self.total_online_capacity_mw

        if online_cap < required:
            # Need more capacity — start next available generator
            for g in self.generators:
                if g.state == GeneratorState.OFFLINE:
                    logger.info(f"Starting {g.id} (cap={online_cap:.1f}, need={required:.1f} MW)")
                    self._start_generator(g)
                    break

        elif online_cap > required * 1.5 and len(
            [g for g in self.generators if g.state == GeneratorState.ONLINE]
        ) > 1:
            # Excess capacity — stop least-loaded generator
            online = [g for g in self.generators if g.state == GeneratorState.ONLINE]
            lightest = min(online, key=lambda g: g.output_mw)
            logger.info(f"Stopping {lightest.id} (cap={online_cap:.1f}, need={required:.1f} MW)")
            self._stop_generator(lightest)

        # Reset faulted units after 10 ticks
        for g in self.generators:
            if g.state == GeneratorState.FAULT:
                g.state = GeneratorState.OFFLINE
                logger.info(f"{g.id} reset from fault")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self, dt_s: float = 1.0) -> None:
        self._running = True
        # Ensure at least one generator starts online
        self._start_generator(self.generators[0])
        await asyncio.sleep(3)

        while self._running:
            self._fleet_management()
            self._dispatch_generation()
            self._manage_storage()
            for g in self.generators:
                g.tick(dt_s)
            for s in self.storage:
                s.tick(dt_s)
            self.tick_count += 1
            await asyncio.sleep(dt_s)

    def update_demand(self, demand_mw: float) -> None:
        self.target_demand_mw = max(0.0, demand_mw)

    def get_status(self) -> Dict:
        return {
            "generators": [g.to_dict() for g in self.generators],
            "storage": [s.to_dict() for s in self.storage],
            "total_generation_mw": round(self.total_generation_mw, 3),
            "total_capacity_mw": round(self.total_online_capacity_mw, 3),
            "fuel_rate_kg_h": round(self.total_fuel_rate_kg_h, 2),
            "tick": self.tick_count,
        }
