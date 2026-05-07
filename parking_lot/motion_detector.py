import logging
import time

import cv2 as open_cv
import numpy as np
from colors import COLOR_BLUE, COLOR_GREEN, COLOR_WHITE
from drawing_utils import draw_contours
from webcam_controls import apply_controls


class MotionDetector:
    LAPLACIAN = 1.4
    DETECT_DELAY = 1

    def __init__(
        self,
        video,
        coordinates,
        start_frame,
        cam_controls=None,
        auto_brightness=None,
        window_name=None,
    ):
        self.video = video
        self.coordinates_data = coordinates
        self.start_frame = start_frame
        self.cam_controls = cam_controls or {}
        self.auto_brightness = auto_brightness
        # When provided, render into this existing window instead of one
        # named after the video source. Lets callers reuse the marking
        # window so it doesn't close and reopen between phases.
        self.window_name = window_name if window_name is not None else str(video)
        self.contours = []
        self.bounds = []
        self.mask = []

    def detect_motion(self):
        capture = open_cv.VideoCapture(self.video)
        if not capture.isOpened():
            raise CaptureReadError(
                "Could not open video source %r for detection." % (self.video,)
            )
        # When self.video is an int we are reading from a webcam, which has no
        # seekable timeline, so skip frame seeking and CAP_PROP_POS_MSEC.
        is_webcam = isinstance(self.video, int)
        if is_webcam:
            apply_controls(capture, self.cam_controls)
            if self.auto_brightness is not None:
                self.auto_brightness.attach(capture)
            # Some UVC drivers (notably on Raspberry Pi) need a few reads
            # before the first usable frame, especially right after the
            # snapshot capture released and re-opened the device.
            self._warmup_capture(capture)
        else:
            capture.set(open_cv.CAP_PROP_POS_FRAMES, self.start_frame)
        start_time = time.time()

        coordinates_data = self.coordinates_data
        logging.debug("coordinates data: %s", coordinates_data)

        for p in coordinates_data:
            coordinates = self._coordinates(p)
            logging.debug("coordinates: %s", coordinates)

            rect = open_cv.boundingRect(coordinates)
            logging.debug("rect: %s", rect)

            new_coordinates = coordinates.copy()
            new_coordinates[:, 0] = coordinates[:, 0] - rect[0]
            new_coordinates[:, 1] = coordinates[:, 1] - rect[1]
            logging.debug("new_coordinates: %s", new_coordinates)

            self.contours.append(coordinates)
            self.bounds.append(rect)

            mask = open_cv.drawContours(
                np.zeros((rect[3], rect[2]), dtype=np.uint8),
                [new_coordinates],
                contourIdx=-1,
                color=255,
                thickness=-1,
                lineType=open_cv.LINE_8,
            )

            mask = mask == 255
            self.mask.append(mask)
            logging.debug("mask: %s", self.mask)

        statuses = [False] * len(coordinates_data)
        times = [None] * len(coordinates_data)

        empty_frames = 0
        max_empty_frames = 30  # ~1–2 seconds of dropped reads on a webcam
        while capture.isOpened():
            result, frame = capture.read()
            if not result or frame is None:
                if is_webcam:
                    # Webcams can drop a frame here and there; only bail
                    # if it keeps happening, in which case the device
                    # likely went away.
                    empty_frames += 1
                    if empty_frames >= max_empty_frames:
                        logging.error(
                            "Webcam returned %d empty frames in a row; giving up.",
                            empty_frames,
                        )
                        break
                    open_cv.waitKey(30)
                    continue
                # For a video file, an empty read means EOF.
                break
            empty_frames = 0

            if is_webcam and self.auto_brightness is not None:
                self.auto_brightness.update(capture, frame, time.time())

            blurred = open_cv.GaussianBlur(frame.copy(), (5, 5), 3)
            grayed = open_cv.cvtColor(blurred, open_cv.COLOR_BGR2GRAY)
            new_frame = frame.copy()
            logging.debug("new_frame: %s", new_frame)

            if is_webcam:
                position_in_seconds = time.time() - start_time
            else:
                position_in_seconds = capture.get(open_cv.CAP_PROP_POS_MSEC) / 1000.0

            for index, c in enumerate(coordinates_data):
                status = self.__apply(grayed, index, c)

                if times[index] is not None and self.same_status(
                    statuses, index, status
                ):
                    times[index] = None
                    continue

                if times[index] is not None and self.status_changed(
                    statuses, index, status
                ):
                    if (
                        position_in_seconds - times[index]
                        >= MotionDetector.DETECT_DELAY
                    ):
                        statuses[index] = status
                        times[index] = None
                    continue

                if times[index] is None and self.status_changed(
                    statuses, index, status
                ):
                    times[index] = position_in_seconds

            for index, p in enumerate(coordinates_data):
                coordinates = self._coordinates(p)

                color = COLOR_GREEN if statuses[index] else COLOR_BLUE
                draw_contours(
                    new_frame, coordinates, str(p["id"] + 1), COLOR_WHITE, color
                )

            open_cv.imshow(self.window_name, new_frame)
            k = open_cv.waitKey(1)
            if k == ord("q"):
                break
        capture.release()
        open_cv.destroyAllWindows()

    def __apply(self, grayed, index, p):
        coordinates = self._coordinates(p)
        logging.debug("points: %s", coordinates)

        rect = self.bounds[index]
        logging.debug("rect: %s", rect)

        roi_gray = grayed[rect[1] : (rect[1] + rect[3]), rect[0] : (rect[0] + rect[2])]
        laplacian = open_cv.Laplacian(roi_gray, open_cv.CV_64F)
        logging.debug("laplacian: %s", laplacian)

        coordinates[:, 0] = coordinates[:, 0] - rect[0]
        coordinates[:, 1] = coordinates[:, 1] - rect[1]

        status = (
            np.mean(np.abs(laplacian * self.mask[index])) < MotionDetector.LAPLACIAN
        )
        logging.debug("status: %s", status)

        return status

    @staticmethod
    def _coordinates(p):
        return np.array(p["coordinates"])

    @staticmethod
    def same_status(coordinates_status, index, status):
        return status == coordinates_status[index]

    @staticmethod
    def status_changed(coordinates_status, index, status):
        return status != coordinates_status[index]

    @staticmethod
    def _warmup_capture(capture, max_attempts=15, delay_ms=30):
        """Read and discard frames until one comes through, or we give up."""
        for attempt in range(max_attempts):
            ok, frame = capture.read()
            if ok and frame is not None:
                logging.debug(
                    "Webcam warm-up: usable frame after %d attempt(s).",
                    attempt + 1,
                )
                return
            open_cv.waitKey(delay_ms)
        logging.warning(
            "Webcam warm-up: no usable frame after %d attempts; "
            "detection loop will keep trying.",
            max_attempts,
        )


class CaptureReadError(Exception):
    pass
