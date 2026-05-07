import argparse
import logging
import os
import time

import cv2 as open_cv
import numpy as np
import yaml
from colors import *
from coordinates_generator import CoordinatesGenerator
from motion_detector import MotionDetector
from webcam_controls import (
    CONTROLS,
    AutoBrightnessController,
    apply_controls,
    has_any,
)

# Single OpenCV window title shared between the spot-marking phase and the
# live detection phase, so the window stays put across the transition.
WINDOW_NAME = "Parking Lot"


def main():
    logging.basicConfig(level=logging.INFO)

    args = parse_args()

    data_file = args.data_file
    start_frame = args.start_frame
    snapshot_path = args.snapshot
    remark = args.remark

    # Allow --video to be either a file path or a webcam device index (e.g. 0).
    video_source = _coerce_source(args.video_file)

    # Collect hardware webcam controls from the CLI (e.g. --brightness 192).
    cam_controls = {name: getattr(args, name) for name, _, _ in CONTROLS}
    if has_any(cam_controls) and not isinstance(video_source, int):
        logging.warning(
            "Webcam controls (--brightness etc.) only apply to webcams; "
            "ignoring them for video file input."
        )
        cam_controls = {}

    # Build the auto-brightness controller if requested.
    auto_brightness = None
    if args.auto_brightness:
        if isinstance(video_source, int):
            auto_brightness = AutoBrightnessController(
                target=args.auto_brightness_target,
                prop=args.auto_brightness_prop,
            )
        else:
            logging.warning(
                "--auto-brightness only applies to webcams; ignoring for "
                "video file input."
            )

    # Decide what (if anything) to use as the still image for marking spots.
    image_source = _resolve_image_source(
        args.image_file, video_source, data_file, remark
    )

    if image_source is not None:
        # If image_source is an int, capture one frame live from that camera.
        if isinstance(image_source, int):
            frame = _capture_frame(image_source, cam_controls)
            if snapshot_path:
                open_cv.imwrite(snapshot_path, frame)
                logging.info("Saved webcam snapshot to %s", snapshot_path)
            image_for_generator = frame
        else:
            image_for_generator = image_source

        with open(data_file, "w+") as points:
            generator = CoordinatesGenerator(
                image_for_generator,
                points,
                COLOR_RED,
                window_name=WINDOW_NAME,
            )
            # Keep the marking window open so the detection phase below
            # can render into the same window instead of spawning a new
            # one (which would otherwise look like a close+reopen flash).
            generator.generate(keep_window_open=True)

    with open(data_file, "r") as data:
        points = yaml.safe_load(data)
        detector = MotionDetector(
            video_source,
            points,
            int(start_frame),
            cam_controls=cam_controls,
            auto_brightness=auto_brightness,
            window_name=WINDOW_NAME,
        )
        detector.detect_motion()


def _coerce_source(value):
    """Convert a string CLI value to an int if it looks like a device index."""
    if value is None:
        return None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def _resolve_image_source(image_arg, video_source, data_file, remark=False):
    """Figure out where the still image for spot marking should come from.

    Priority:
      1. Explicit --image argument (path or device index).
      2. If --video is a webcam *and* the data file doesn't exist yet
         (or --remark was passed), reuse the webcam to grab a snapshot.
      3. Otherwise, no spot-marking step (reuse existing data file).
    """
    if image_arg is not None:
        return _coerce_source(image_arg)

    data_missing = not os.path.exists(data_file) or os.path.getsize(data_file) == 0
    if isinstance(video_source, int) and (data_missing or remark):
        if remark and not data_missing:
            logging.info(
                "--remark requested; capturing a frame from webcam %d to "
                "re-mark spots (overwriting %s).",
                video_source,
                data_file,
            )
        else:
            logging.info(
                "No --image given and %s is empty; capturing a frame from "
                "webcam %d to mark spots.",
                data_file,
                video_source,
            )
        return video_source

    if remark and not isinstance(video_source, int):
        logging.warning(
            "--remark only takes effect when --video is a webcam device "
            "index; pass --image to re-mark spots from a file."
        )

    return None


def _capture_frame(
    device_index,
    cam_controls=None,
    warmup_frames=30,
    min_mean_luminance=10.0,
    max_attempts=60,
    settle_seconds=0.5,
):
    """Grab a single frame from the given webcam device index.

    Most webcams return solid-black (or near-black) frames for the first
    handful of reads after being opened, especially when auto-exposure
    has just been (re)engaged or hardware controls were changed. We
    therefore:

    1. Sleep briefly after applying controls so the driver can settle.
    2. Discard at least ``warmup_frames`` reads.
    3. Keep reading until we get a frame whose mean luminance is above
       ``min_mean_luminance`` (i.e. not effectively black), up to
       ``max_attempts`` total reads.
    """
    capture = open_cv.VideoCapture(device_index)
    if not capture.isOpened():
        raise RuntimeError(
            "Could not open webcam device %d for snapshot." % device_index
        )
    apply_controls(capture, cam_controls or {})

    # Give the driver a moment to apply controls and let auto-exposure
    # start converging before we trust any frames.
    if settle_seconds > 0:
        time.sleep(settle_seconds)

    frame = None
    last_frame = None
    for attempt in range(max_attempts):
        ok, current = capture.read()
        if not ok or current is None:
            continue
        last_frame = current
        # Always discard the first few reads as warm-up.
        if attempt < warmup_frames:
            continue
        gray = open_cv.cvtColor(current, open_cv.COLOR_BGR2GRAY)
        mean = float(np.mean(gray))
        if mean >= min_mean_luminance:
            frame = current
            logging.info(
                "Webcam snapshot captured after %d frames (mean luminance %.1f).",
                attempt + 1,
                mean,
            )
            break
        logging.debug(
            "Discarding dark webcam frame %d (mean luminance %.1f < %.1f).",
            attempt + 1,
            mean,
            min_mean_luminance,
        )

    capture.release()

    if frame is None:
        if last_frame is not None:
            logging.warning(
                "Webcam device %d only produced dark frames after %d attempts; "
                "using the last one anyway. Try increasing brightness/exposure "
                "or pointing the camera at a better-lit scene.",
                device_index,
                max_attempts,
            )
            return last_frame
        raise RuntimeError(
            "Could not read a frame from webcam device %d." % device_index
        )
    return frame


def parse_args():
    parser = argparse.ArgumentParser(description="Generates Coordinates File")

    parser.add_argument(
        "--image",
        dest="image_file",
        required=False,
        help=(
            "Image to generate coordinates on. Can be a file path or a "
            "webcam device index (e.g. 0) to capture a snapshot live. "
            "If omitted and --video is a webcam, a snapshot is captured "
            "automatically when no coordinates file exists yet."
        ),
    )

    parser.add_argument(
        "--video",
        dest="video_file",
        required=True,
        help=(
            "Video source to detect motion on. Either a path to a video "
            "file or a webcam device index (e.g. 0)."
        ),
    )

    parser.add_argument(
        "--data",
        dest="data_file",
        required=True,
        help="Data file to be used with OpenCV",
    )

    parser.add_argument(
        "--start-frame",
        dest="start_frame",
        required=False,
        default=1,
        help="Starting frame on the video (ignored for webcams)",
    )

    parser.add_argument(
        "--snapshot",
        dest="snapshot",
        required=False,
        default=None,
        help=(
            "Optional path to save the webcam snapshot used for marking "
            "spots, so it can be reused later as --image."
        ),
    )

    parser.add_argument(
        "--remark",
        dest="remark",
        action="store_true",
        help=(
            "Force the spot-marking step to run even if the coordinates "
            "file already exists. When --video is a webcam, a fresh "
            "snapshot is captured automatically."
        ),
    )

    cam_group = parser.add_argument_group(
        "webcam hardware controls",
        "Set V4L2-style camera properties (equivalent to "
        "`v4l2-ctl --set-ctrl=<name>=<value>` on Linux). Only applied "
        "when --video is a webcam device index. Value ranges depend on "
        "the camera/driver.",
    )
    cam_group.add_argument(
        "--brightness",
        dest="brightness",
        type=float,
        default=None,
        help="Webcam brightness (e.g. 192).",
    )
    cam_group.add_argument(
        "--contrast",
        dest="contrast",
        type=float,
        default=None,
        help="Webcam contrast.",
    )
    cam_group.add_argument(
        "--saturation",
        dest="saturation",
        type=float,
        default=None,
        help="Webcam saturation.",
    )
    cam_group.add_argument(
        "--gain",
        dest="gain",
        type=float,
        default=None,
        help="Webcam gain.",
    )
    cam_group.add_argument(
        "--exposure",
        dest="exposure",
        type=float,
        default=None,
        help=(
            "Webcam exposure (manual). Many V4L2 drivers require "
            "--auto-exposure 1 first to take effect."
        ),
    )
    cam_group.add_argument(
        "--auto-exposure",
        dest="auto_exposure",
        type=float,
        default=None,
        help=(
            "Auto-exposure mode. On most V4L2 UVC cameras, 3 = auto and "
            "1 = manual; check `v4l2-ctl -L` for your specific device."
        ),
    )
    cam_group.add_argument(
        "--auto-brightness",
        dest="auto_brightness",
        action="store_true",
        help=(
            "Continuously adjust a hardware control (exposure, gain, or "
            "brightness) to keep the mean frame luminance near "
            "--auto-brightness-target. Pair with --auto-exposure 1 if "
            "you want to drive --exposure manually."
        ),
    )
    cam_group.add_argument(
        "--auto-brightness-target",
        dest="auto_brightness_target",
        type=float,
        default=128.0,
        help=(
            "Target mean luminance (0–255) for --auto-brightness. "
            "Default: 128 (neutral midtone)."
        ),
    )
    cam_group.add_argument(
        "--auto-brightness-prop",
        dest="auto_brightness_prop",
        choices=["exposure", "gain", "brightness"],
        default=None,
        help=(
            "Which hardware control --auto-brightness should drive. "
            "Default: auto-detect the first one the camera accepts."
        ),
    )

    return parser.parse_args()


if __name__ == "__main__":
    main()
