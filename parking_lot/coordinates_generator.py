import cv2 as open_cv
import numpy as np
import yaml
from colors import COLOR_WHITE
from drawing_utils import draw_contours

# Hotkey help shown in the upper-left of the marking window.
_HOTKEY_LINES = [
    "Click 4 corners to mark a spot",
    "u: undo last spot",
    "r: reset all spots",
    "q: quit and save",
]


class CoordinatesGenerator:
    KEY_RESET = ord("r")
    KEY_QUIT = ord("q")
    KEY_UNDO = ord("u")

    def __init__(self, image, output, color, window_name=None):
        self.output = output
        self.color = color

        # The marking frame is always provided as an in-memory numpy array
        # (captured live from the webcam by ``main.py``).
        if not isinstance(image, np.ndarray):
            raise TypeError(
                "CoordinatesGenerator expects a numpy ndarray frame, got %r"
                % type(image).__name__
            )
        self.original_image = image.copy()

        # ``window_name`` becomes the OpenCV window title. Sharing a single
        # window with the subsequent detection phase keeps the window from
        # closing and reopening between phases.
        self.caption = window_name if window_name is not None else "coordinates"

        # Working canvas. Re-rendered from `original_image` whenever spots
        # change (undo/reset), so we never need to "erase" pixels.
        self.image = self.original_image.copy()
        self._render_overlay()

        self.click_count = 0
        # In-progress corners for the spot currently being clicked.
        self.coordinates = []
        # All completed spots: list of {"id": int, "coordinates": [[x,y], ...]}.
        self.spots = []

        open_cv.namedWindow(self.caption, open_cv.WINDOW_GUI_EXPANDED)
        open_cv.setMouseCallback(self.caption, self.__mouse_callback)

    def generate(self, keep_window_open=False):
        """Run the interactive marking loop until the user presses ``q``.

        Parameters
        ----------
        keep_window_open : bool
            If True, leave the OpenCV window open after the user quits
            so a subsequent stage (e.g. live detection) can reuse the
            same window without it closing and reopening.
        """
        while True:
            open_cv.imshow(self.caption, self.image)
            key = open_cv.waitKey(0)

            if key == CoordinatesGenerator.KEY_RESET:
                self.__reset()
            elif key == CoordinatesGenerator.KEY_UNDO:
                self.__undo()
            elif key == CoordinatesGenerator.KEY_QUIT:
                break
        if not keep_window_open:
            open_cv.destroyWindow(self.caption)
        self.__write_output()

    # ------------------------------------------------------------------
    # Mouse handling
    # ------------------------------------------------------------------

    def __mouse_callback(self, event, x, y, flags, params):
        if event == open_cv.EVENT_LBUTTONDOWN:
            self.coordinates.append((x, y))
            self.click_count += 1

            if self.click_count >= 4:
                self.__handle_done()
            elif self.click_count > 1:
                self.__handle_click_progress()

            open_cv.imshow(self.caption, self.image)

    def __handle_click_progress(self):
        open_cv.line(
            self.image, self.coordinates[-2], self.coordinates[-1], (255, 0, 0), 1
        )

    def __handle_done(self):
        # Close the polygon visually.
        open_cv.line(
            self.image, self.coordinates[2], self.coordinates[3], self.color, 1
        )
        open_cv.line(
            self.image, self.coordinates[3], self.coordinates[0], self.color, 1
        )

        spot_id = len(self.spots)
        spot_coords = [list(pt) for pt in self.coordinates]
        self.spots.append({"id": spot_id, "coordinates": spot_coords})

        draw_contours(
            self.image,
            np.array(self.coordinates),
            str(spot_id + 1),
            COLOR_WHITE,
        )

        self.coordinates = []
        self.click_count = 0

    # ------------------------------------------------------------------
    # Undo / reset
    # ------------------------------------------------------------------

    def __undo(self):
        """Remove the most recently completed spot, or any in-progress clicks."""
        if self.coordinates:
            # Drop in-progress corners first.
            self.coordinates = []
            self.click_count = 0
            self.__rerender()
            return
        if not self.spots:
            return
        self.spots.pop()
        # Renumber so IDs stay consecutive.
        for index, spot in enumerate(self.spots):
            spot["id"] = index
        self.__rerender()

    def __reset(self):
        """Clear all completed spots and any in-progress clicks."""
        self.spots = []
        self.coordinates = []
        self.click_count = 0
        self.__rerender()

    def __rerender(self):
        """Redraw the canvas from the original image plus current spots."""
        self.image = self.original_image.copy()
        self._render_overlay()
        for spot in self.spots:
            pts = np.array(spot["coordinates"])
            # Outline + label, matching the look of __handle_done.
            open_cv.line(self.image, tuple(pts[0]), tuple(pts[1]), (255, 0, 0), 1)
            open_cv.line(self.image, tuple(pts[1]), tuple(pts[2]), (255, 0, 0), 1)
            open_cv.line(self.image, tuple(pts[2]), tuple(pts[3]), self.color, 1)
            open_cv.line(self.image, tuple(pts[3]), tuple(pts[0]), self.color, 1)
            draw_contours(self.image, pts, str(spot["id"] + 1), COLOR_WHITE)
        open_cv.imshow(self.caption, self.image)

    # ------------------------------------------------------------------
    # Overlay & output
    # ------------------------------------------------------------------

    def _render_overlay(self):
        """Draw the hotkey legend in the top-left corner of `self.image`."""
        font = open_cv.FONT_HERSHEY_SIMPLEX
        scale = 0.45
        thickness = 1
        line_height = 18
        padding = 6

        # Measure the widest line so we can size the background box.
        widths = [
            open_cv.getTextSize(line, font, scale, thickness)[0][0]
            for line in _HOTKEY_LINES
        ]
        box_w = max(widths) + 2 * padding
        box_h = line_height * len(_HOTKEY_LINES) + 2 * padding

        # Semi-transparent black background for legibility on any image.
        overlay = self.image.copy()
        open_cv.rectangle(overlay, (0, 0), (box_w, box_h), (0, 0, 0), thickness=-1)
        open_cv.addWeighted(overlay, 0.55, self.image, 0.45, 0, dst=self.image)

        for i, line in enumerate(_HOTKEY_LINES):
            y = padding + line_height * (i + 1) - 4
            open_cv.putText(
                self.image,
                line,
                (padding, y),
                font,
                scale,
                COLOR_WHITE,
                thickness,
                lineType=open_cv.LINE_AA,
            )

    def __write_output(self):
        """Write all completed spots to the output file in canonical YAML.

        The top-level structure is a YAML block sequence (``- id: ...``),
        with each spot's ``coordinates`` rendered as a single inline flow
        list for readability. Example::

            - id: 0
              coordinates: [[120, 340], [260, 340], [260, 470], [120, 470]]
        """
        # Normalize the coordinates to plain Python ints so PyYAML doesn't
        # tag them with !!python/object types.
        spots = [
            {
                "id": int(spot["id"]),
                "coordinates": [[int(x), int(y)] for x, y in spot["coordinates"]],
            }
            for spot in self.spots
        ]

        yaml.safe_dump(
            spots,
            self.output,
            default_flow_style=None,
            sort_keys=False,
        )
