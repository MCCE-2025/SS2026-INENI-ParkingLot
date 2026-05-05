import argparse
import logging

import yaml
from colors import *
from coordinates_generator import CoordinatesGenerator
from motion_detector import MotionDetector


def main():
    logging.basicConfig(level=logging.INFO)

    args = parse_args()

    image_file = args.image_file
    data_file = args.data_file
    start_frame = args.start_frame

    # Allow --video to be either a file path or a webcam device index (e.g. 0).
    video_source = args.video_file
    if video_source is not None and video_source.isdigit():
        video_source = int(video_source)

    if image_file is not None:
        with open(data_file, "w+") as points:
            generator = CoordinatesGenerator(image_file, points, COLOR_RED)
            generator.generate()

    with open(data_file, "r") as data:
        points = yaml.load(data)
        detector = MotionDetector(video_source, points, int(start_frame))
        detector.detect_motion()


def parse_args():
    parser = argparse.ArgumentParser(description="Generates Coordinates File")

    parser.add_argument(
        "--image",
        dest="image_file",
        required=False,
        help="Image file to generate coordinates on",
    )

    parser.add_argument(
        "--video",
        dest="video_file",
        required=True,
        help="Video file to detect motion on",
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
        help="Starting frame on the video",
    )

    return parser.parse_args()


if __name__ == "__main__":
    main()
