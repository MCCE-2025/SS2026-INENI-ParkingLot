import logging

import cv2 as open_cv

# Room for title bar, borders, and taskbar when sizing the initial window.
_MARGIN_W = 64
_MARGIN_H = 96
_MIN_WINDOW_W = 320
_MIN_WINDOW_H = 240


def _screen_size():
    """Return (width, height) of the primary display, or None if unknown."""
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        size = root.winfo_screenwidth(), root.winfo_screenheight()
        root.destroy()
        if size[0] > 0 and size[1] > 0:
            return size
    except Exception:
        logging.debug("Could not read screen size via tkinter", exc_info=True)
    return None


def _max_window_size():
    """Largest client area we should use so the window fits on screen."""
    screen = _screen_size()
    if screen is None:
        return None, None
    screen_w, screen_h = screen
    return (
        max(_MIN_WINDOW_W, screen_w - _MARGIN_W),
        max(_MIN_WINDOW_H, screen_h - _MARGIN_H),
    )


def fit_window_size(image_w, image_h, max_w, max_h):
    """Scale down (never up) to fit within max_w x max_h, keeping aspect ratio."""
    image_w, image_h = int(image_w), int(image_h)
    max_w, max_h = int(max_w), int(max_h)
    if image_w <= max_w and image_h <= max_h:
        return image_w, image_h
    scale = min(max_w / image_w, max_h / image_h)
    return max(1, int(image_w * scale)), max(1, int(image_h * scale))


def setup_display_window(window_name, width, height):
    """Open a resizable window sized to the image, scaled down if needed for the display."""
    w, h = int(width), int(height)
    max_w, max_h = _max_window_size()
    if max_w is not None:
        w, h = fit_window_size(w, h, max_w, max_h)
    open_cv.namedWindow(window_name, open_cv.WINDOW_NORMAL)
    open_cv.resizeWindow(window_name, w, h)
