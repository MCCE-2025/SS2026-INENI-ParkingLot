import argparse
import logging
import os

import cv2 as open_cv
import yaml
from colors import *
from coordinates_generator import CoordinatesGenerator
from motion_detector import MotionDetector


def main():
    logging.basicConfig(level=logging.INFO)

    args = parse_args()

    data_file = args.data_file
    start_frame = args.start_frame
    snapshot_path = args.snapshot
    remark = args.remark

    # Allow --video to be either a file path or a webcam device index (e.g. 0).
    video_source = _coerce_source(args.video_file)

    # Decide what (if anything) to use as the still image for marking spots.
    image_source = _resolve_image_source(
        args.image_file, video_source, data_file, remark
    )

    if image_source is not None:
        # If image_source is an int, capture one frame live from that camera.
        if isinstance(image_source, int):
            frame = _capture_frame(image_source)
            if snapshot_path:
                open_cv.imwrite(snapshot_path, frame)
                logging.info("Saved webcam snapshot to %s", snapshot_path)
            image_for_generator = frame
        else:
            image_for_generator = image_source

        with open(data_file, "w+") as points:
            generator = CoordinatesGenerator(image_for_generator, points, COLOR_RED)
            generator.generate()

    with open(data_file, "r") as data:
        points = yaml.load(data)
        detector = MotionDetector(video_source, points, int(start_frame))
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


def _capture_frame(device_index):
    """Grab a single frame from the given webcam device index."""
    capture = open_cv.VideoCapture(device_index)
    if not capture.isOpened():
        raise RuntimeError(
            "Could not open webcam device %d for snapshot." % device_index
        )
    # Some webcams need a few reads before they return a usable frame.
    frame = None
    for _ in range(5):
        ok, frame = capture.read()
        if ok and frame is not None:
            break
    capture.release()
    if frame is None:
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

    return parser.parse_args()


if __name__ == "__main__":
    main()
