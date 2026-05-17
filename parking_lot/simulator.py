"""Synthetic occupancy simulator for AWS IoT Core (no camera / OpenCV).

Drives the same :class:`IoTPublisher` used by the real detector, but toggles
spot occupancy in software so you can validate MQTT topics, payloads, Device
Shadow documents, and IoT Rules without image recognition or hardware.
"""

import argparse
import logging
import random
import time

import yaml

from iot_publisher import add_iot_args, build_iot_publisher

logger = logging.getLogger(__name__)


class OccupancySimulator:
    """Simulate parking-spot state changes and publish them to AWS IoT Core."""

    def __init__(
        self,
        publisher,
        num_spots,
        interval=5.0,
        flip_prob=0.2,
        initial_occupancy_prob=0.0,
        script=None,
        seed=None,
        max_events=None,
    ):
        self.publisher = publisher
        self.num_spots = int(num_spots)
        self.interval = float(interval)
        self.flip_prob = float(flip_prob)
        self.initial_occupancy_prob = float(initial_occupancy_prob)
        self.script = script
        self.max_events = max_events
        self._rng = random.Random(seed)
        self._events_published = 0

    def run(self):
        """Run until interrupted, the script ends, or *max_events* is reached."""
        statuses = self._initial_statuses()
        self.publisher.publish_initial_snapshot(statuses)
        logger.info(
            "Initial occupancy: %d free, %d occupied (of %d spots).",
            sum(1 for s in statuses if s),
            sum(1 for s in statuses if not s),
            len(statuses),
        )

        try:
            if self.script is not None:
                self._run_scripted(statuses)
            else:
                self._run_random(statuses)
        except KeyboardInterrupt:
            logger.info("Simulator stopped by user.")

    def _initial_statuses(self):
        """Build statuses list (True = empty, False = occupied)."""
        statuses = []
        for _ in range(self.num_spots):
            occupied = self._rng.random() < self.initial_occupancy_prob
            statuses.append(not occupied)
        return statuses

    def _run_random(self, statuses):
        while not self._should_stop():
            time.sleep(self.interval)
            if self._rng.random() < self.flip_prob:
                spot_id = self._rng.randrange(self.num_spots)
                self._apply_and_publish(statuses, spot_id)
            self.publisher.publish_summary_if_due(statuses, time.time())

    def _run_scripted(self, statuses):
        events = sorted(self.script, key=lambda e: float(e["t"]))
        start = time.time()
        for event in events:
            if self._should_stop():
                break
            target = start + float(event["t"])
            delay = target - time.time()
            if delay > 0:
                time.sleep(delay)
            spot_id = int(event["spot"])
            if spot_id < 0 or spot_id >= self.num_spots:
                raise ValueError(
                    "Script event spot %d out of range (0..%d)"
                    % (spot_id, self.num_spots - 1)
                )
            occupied = bool(event["occupied"])
            statuses[spot_id] = not occupied
            self._publish_change(statuses, spot_id)
            self.publisher.publish_summary_if_due(statuses, time.time())

        logger.info("Script finished (%d events).", len(events))

    def _apply_and_publish(self, statuses, spot_id):
        statuses[spot_id] = not statuses[spot_id]
        self._publish_change(statuses, spot_id)

    def _publish_change(self, statuses, spot_id):
        occupied = not statuses[spot_id]
        self.publisher.publish_spot(
            spot_id=spot_id,
            occupied=occupied,
            statuses=statuses,
        )
        self._events_published += 1
        logger.info(
            "Spot %d -> %s (event %s)",
            spot_id,
            "occupied" if occupied else "free",
            self._events_published,
        )

    def _should_stop(self):
        if self.max_events is not None and self._events_published >= self.max_events:
            logger.info("Reached --max-events=%d; stopping.", self.max_events)
            return True
        return False


def _load_script(path):
    with open(path, "r") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, list):
        raise SystemExit("Script file must contain a YAML list of events.")
    for index, event in enumerate(data):
        if not isinstance(event, dict):
            raise SystemExit("Script event %d must be a mapping." % index)
        for key in ("t", "spot", "occupied"):
            if key not in event:
                raise SystemExit(
                    "Script event %d missing required key %r." % (index, key)
                )
    return data


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Simulate parking occupancy and publish to AWS IoT Core "
            "(no camera or image recognition)."
        )
    )
    sim_group = parser.add_argument_group("simulator")
    sim_group.add_argument(
        "--spots",
        type=int,
        default=8,
        help="Number of simulated parking spots. Default: 8.",
    )
    sim_group.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Seconds between ticks in random mode. Default: 5.",
    )
    sim_group.add_argument(
        "--flip-prob",
        type=float,
        default=0.2,
        help=(
            "Random mode: probability per tick that a random spot toggles. "
            "Ignored when --script is set. Default: 0.2."
        ),
    )
    sim_group.add_argument(
        "--initial-occupancy-prob",
        type=float,
        default=0.0,
        help="Fraction of spots that start occupied (0.0–1.0). Default: 0.",
    )
    sim_group.add_argument(
        "--script",
        default=None,
        help=(
            "Path to a YAML script of timed events "
            "(fields: t, spot, occupied). Mutually exclusive with random "
            "flip behaviour; --flip-prob is ignored when set."
        ),
    )
    sim_group.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed for reproducible random runs.",
    )
    sim_group.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Stop after publishing this many spot state changes.",
    )

    add_iot_args(parser)
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO)
    args = parse_args()

    if args.spots < 1:
        raise SystemExit("--spots must be at least 1.")
    if not 0.0 <= args.initial_occupancy_prob <= 1.0:
        raise SystemExit("--initial-occupancy-prob must be between 0 and 1.")
    if args.script is not None:
        logging.info(
            "Using scripted events from %s; --flip-prob is ignored.",
            args.script,
        )

    script = _load_script(args.script) if args.script else None
    publisher = build_iot_publisher(args, required=True)

    simulator = OccupancySimulator(
        publisher=publisher,
        num_spots=args.spots,
        interval=args.interval,
        flip_prob=args.flip_prob,
        initial_occupancy_prob=args.initial_occupancy_prob,
        script=script,
        seed=args.seed,
        max_events=args.max_events,
    )

    try:
        simulator.run()
    finally:
        publisher.disconnect()


if __name__ == "__main__":
    main()
