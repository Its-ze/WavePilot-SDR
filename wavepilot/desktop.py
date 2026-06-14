"""Native desktop UI for WavePilot SDR."""

from __future__ import annotations

import argparse
import math
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .live_audio import stream_audio
from .presets import PRESET_GROUPS
from .radio import manager
from .updater import UpdateError, apply_update, check_for_update, restart_application

ASSETS_ROOT = Path(__file__).resolve().parent / "assets"
APP_ICON = ASSETS_ROOT / "wavepilot-icon.png"
BRAND_TAGLINE = "Signal scanner + live RF receiver"


class WorkerSignals(QObject):
    result = Signal(str, object)
    error = Signal(str, str)
    finished = Signal(object)


class FunctionWorker(QRunnable):
    def __init__(self, tag, fn):
        super().__init__()
        self.setAutoDelete(False)
        self.tag = tag
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.signals.result.emit(self.tag, self.fn())
        except Exception as exc:
            try:
                self.signals.error.emit(self.tag, str(exc))
            except RuntimeError:
                pass
        finally:
            try:
                self.signals.finished.emit(self)
            except RuntimeError:
                pass


class AudioStreamWorker(QRunnable):
    def __init__(self, settings):
        super().__init__()
        self.setAutoDelete(False)
        self.settings = settings
        self.stop_event = threading.Event()
        self.signals = WorkerSignals()

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            stream_audio(
                **self.settings,
                stop_event=self.stop_event,
                on_status=lambda payload: self.signals.result.emit("audio-status", payload),
                on_spectrum=lambda payload: self.signals.result.emit("audio-spectrum", payload),
                on_transcript=lambda payload: self.signals.result.emit("transcript", payload),
            )
            self.signals.result.emit("audio-stopped", {"stopped": True})
        except Exception as exc:
            try:
                self.signals.error.emit("audio-stream", str(exc))
            except RuntimeError:
                pass
        finally:
            try:
                self.signals.finished.emit(self)
            except RuntimeError:
                pass


class SpectrumView(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(240)
        self.bins = []
        self.payload = {}

    def set_payload(self, payload):
        self.payload = payload
        incoming = list(payload.get("bins", []))
        if not self.bins or len(self.bins) != len(incoming):
            self.bins = incoming
        else:
            self.bins = [old * 0.72 + new * 0.28 for old, new in zip(self.bins, incoming)]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect()
        painter.fillRect(rect, QColor("#07090a"))
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(124, 183, 255, 42), 1))
        for idx in range(1, 6):
            y = rect.top() + rect.height() * idx / 6
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))
        if len(self.bins) < 2:
            painter.setPen(QColor("#a7b0aa"))
            painter.drawText(rect.adjusted(12, 12, -12, -12), Qt.AlignLeft | Qt.AlignTop, "Waiting for samples")
            return

        minimum = min(self.bins)
        maximum = max(self.bins)
        span = max(8.0, maximum - minimum)
        points = []
        for idx, value in enumerate(self.bins):
            x = rect.left() + idx * rect.width() / max(1, len(self.bins) - 1)
            y = rect.bottom() - ((value - minimum) / span) * (rect.height() - 18) - 9
            points.append((int(x), int(y)))
        painter.setPen(QPen(QColor("#42e8d2"), 2))
        for first, second in zip(points, points[1:]):
            painter.drawLine(first[0], first[1], second[0], second[1])


class WaterfallView(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(220)
        self.image = QImage(900, 260, QImage.Format_RGB32)
        self.image.fill(QColor("#07090a"))

    def add_bins(self, bins):
        if not bins:
            return
        if self.image.width() != max(1, self.width()) or self.image.height() != max(1, self.height()):
            self.image = QImage(max(1, self.width()), max(1, self.height()), QImage.Format_RGB32)
            self.image.fill(QColor("#07090a"))
        scrolled = self.image.copy(0, 0, self.image.width(), self.image.height() - 1)
        painter = QPainter(self.image)
        painter.drawImage(0, 1, scrolled)
        minimum = min(bins)
        span = max(8.0, max(bins) - minimum)
        for x in range(self.image.width()):
            idx = min(len(bins) - 1, int(x / max(1, self.image.width()) * len(bins)))
            v = max(0.0, min(1.0, (bins[idx] - minimum) / span))
            color = QColor(int(18 + 230 * max(0, v - 0.35)), int(45 + 190 * v), int(58 + 150 * (1 - abs(v - 0.65))))
            painter.setPen(color)
            painter.drawPoint(x, 0)
        painter.end()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawImage(self.rect(), self.image)


class WavePilotWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"WavePilot SDR {__version__}")
        if APP_ICON.exists():
            self.setWindowIcon(QIcon(str(APP_ICON)))
        self.resize(1320, 840)
        self.thread_pool = QThreadPool.globalInstance()
        self.spectrum_busy = False
        self.audio_running = False
        self.audio_worker = None
        self.pending_audio_restart = False
        self.suppress_receiver_change = False
        self.running = True
        self.latest_update = None
        self.user_requested_update_check = False
        self.closing = False
        self.active_workers = []

        self.audio_restart_timer = QTimer(self)
        self.audio_restart_timer.setSingleShot(True)
        self.audio_restart_timer.timeout.connect(self.restart_audio_stream)

        self.build_ui()
        self.apply_style()
        self.load_presets()
        QApplication.instance().aboutToQuit.connect(self.shutdown_workers)

        self.spectrum_timer = QTimer(self)
        self.spectrum_timer.timeout.connect(self.queue_spectrum)
        self.spectrum_timer.start(320)
        QTimer.singleShot(50, self.queue_status)
        QTimer.singleShot(1400, lambda: self.queue_update_check(False))

    def build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        top = QHBoxLayout()
        logo = QLabel()
        logo.setObjectName("BrandIcon")
        if APP_ICON.exists():
            pixmap = QPixmap(str(APP_ICON))
            logo.setPixmap(pixmap.scaled(54, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setFixedSize(58, 58)
        top.addWidget(logo)
        title_box = QVBoxLayout()
        title = QLabel("WavePilot SDR")
        title.setObjectName("Title")
        tagline = QLabel(BRAND_TAGLINE)
        tagline.setObjectName("Tagline")
        self.device_label = QLabel("Checking receiver")
        self.device_label.setObjectName("Muted")
        title_box.addWidget(title)
        title_box.addWidget(tagline)
        title_box.addWidget(self.device_label)
        top.addLayout(title_box, 1)
        self.state_label = QLabel("Starting")
        self.state_label.setObjectName("Pill")
        self.peak_label = QLabel("Peak -- MHz")
        self.peak_label.setObjectName("PillMuted")
        self.update_button = QPushButton("Updates")
        self.update_button.clicked.connect(self.toggle_update_panel)
        top.addWidget(self.state_label)
        top.addWidget(self.peak_label)
        top.addWidget(self.update_button)
        layout.addLayout(top)

        controls = QHBoxLayout()
        self.freq = QDoubleSpinBox()
        self.freq.setRange(24.0, 1766.0)
        self.freq.setDecimals(4)
        self.freq.setSingleStep(0.0125)
        self.freq.setValue(162.55)
        self.mode = QComboBox()
        self.mode.addItems(["nfm", "wfm", "am"])
        self.sample_rate = QComboBox()
        for label, value in [("1.024 MS/s", 1024000), ("1.536 MS/s", 1536000), ("2.048 MS/s", 2048000)]:
            self.sample_rate.addItem(label, value)
        self.auto_gain = QCheckBox("Auto gain")
        self.auto_gain.setChecked(True)
        self.mute_audio = QCheckBox("Mute")
        self.mute_audio.setChecked(False)
        self.auto_listen = QCheckBox("Auto listen")
        self.auto_listen.setChecked(True)
        self.squelch_audio = QCheckBox("Squelch")
        self.squelch_audio.setChecked(False)
        self.transcript_enabled = QCheckBox("Transcript")
        self.transcript_enabled.setChecked(True)
        self.gain = QDoubleSpinBox()
        self.gain.setRange(0.0, 49.6)
        self.gain.setSingleStep(0.1)
        self.gain.setValue(28.0)
        self.gain.setEnabled(False)
        self.auto_gain.toggled.connect(self.gain.setDisabled)
        self.freq.valueChanged.connect(self.receiver_settings_changed)
        self.mode.currentTextChanged.connect(self.receiver_settings_changed)
        self.sample_rate.currentIndexChanged.connect(self.receiver_settings_changed)
        self.auto_gain.toggled.connect(self.receiver_settings_changed)
        self.gain.valueChanged.connect(self.receiver_settings_changed)
        self.mute_audio.toggled.connect(self.receiver_settings_changed)
        self.squelch_audio.toggled.connect(self.receiver_settings_changed)
        self.transcript_enabled.toggled.connect(self.receiver_settings_changed)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.toggle_running)
        self.listen_button = QPushButton("Listen Live")
        self.listen_button.clicked.connect(self.toggle_audio)
        self.scan_button = QPushButton("Scan")
        self.scan_button.clicked.connect(self.queue_scan)
        for label, widget in [
            ("Frequency MHz", self.freq),
            ("Mode", self.mode),
            ("Sample rate", self.sample_rate),
            ("Gain dB", self.gain),
        ]:
            box = QVBoxLayout()
            box.addWidget(QLabel(label))
            box.addWidget(widget)
            controls.addLayout(box)
        controls.addWidget(self.auto_gain)
        controls.addWidget(self.auto_listen)
        controls.addWidget(self.mute_audio)
        controls.addWidget(self.squelch_audio)
        controls.addWidget(self.transcript_enabled)
        controls.addWidget(self.pause_button)
        controls.addWidget(self.listen_button)
        controls.addWidget(self.scan_button)
        layout.addLayout(controls)

        self.update_panel = self.build_update_panel()
        self.update_panel.hide()
        layout.addWidget(self.update_panel)

        self.preset_tabs = QTabWidget()
        layout.addWidget(self.preset_tabs)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        spectrum_box = QGroupBox("Live Spectrum")
        spectrum_layout = QVBoxLayout(spectrum_box)
        self.scope_meta = QLabel("Waiting for samples")
        self.scope_meta.setObjectName("Muted")
        self.spectrum = SpectrumView()
        spectrum_layout.addWidget(self.scope_meta)
        spectrum_layout.addWidget(self.spectrum)
        waterfall_box = QGroupBox("Waterfall")
        waterfall_layout = QVBoxLayout(waterfall_box)
        self.waterfall = WaterfallView()
        waterfall_layout.addWidget(self.waterfall)
        left_layout.addWidget(spectrum_box, 3)
        left_layout.addWidget(waterfall_box, 2)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.strong_list = QListWidget()
        self.strong_list.itemClicked.connect(self.activate_channel_item)
        self.scan_list = QListWidget()
        self.scan_list.itemClicked.connect(self.activate_channel_item)
        transcript_header = QHBoxLayout()
        transcript_label = QLabel("Live Transcript")
        self.transcript_state = QLabel("Idle")
        self.transcript_state.setObjectName("Muted")
        self.clear_transcript_button = QPushButton("Clear")
        self.clear_transcript_button.clicked.connect(self.clear_transcript)
        transcript_header.addWidget(transcript_label, 1)
        transcript_header.addWidget(self.transcript_state)
        transcript_header.addWidget(self.clear_transcript_button)
        self.transcript_partial = QLabel("Start Listen Live to transcribe analog speech.")
        self.transcript_partial.setWordWrap(True)
        self.transcript_partial.setObjectName("Muted")
        self.transcript_log = QPlainTextEdit()
        self.transcript_log.setObjectName("TranscriptLog")
        self.transcript_log.setReadOnly(True)
        self.transcript_log.setPlaceholderText("Transcript lines appear here when speech is detected.")
        self.transcript_log.document().setMaximumBlockCount(240)
        right_layout.addWidget(QLabel("Strong Signals"))
        right_layout.addWidget(self.strong_list, 1)
        right_layout.addWidget(QLabel("Scan Results"))
        right_layout.addWidget(self.scan_list, 1)
        right_layout.addLayout(transcript_header)
        right_layout.addWidget(self.transcript_partial)
        right_layout.addWidget(self.transcript_log, 1)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        self.setCentralWidget(root)

    def build_update_panel(self):
        box = QFrame()
        box.setObjectName("UpdatePanel")
        layout = QHBoxLayout(box)
        text_box = QVBoxLayout()
        self.update_title = QLabel("Updates")
        self.update_title.setObjectName("PanelTitle")
        self.update_detail = QLabel("Check for a published WavePilot SDR update.")
        self.update_detail.setWordWrap(True)
        self.update_detail.setObjectName("Muted")
        text_box.addWidget(self.update_title)
        text_box.addWidget(self.update_detail)
        layout.addLayout(text_box, 1)
        self.check_update_button = QPushButton("Check")
        self.check_update_button.clicked.connect(lambda: self.queue_update_check(True))
        self.apply_update_button = QPushButton("Apply")
        self.apply_update_button.clicked.connect(self.queue_apply_update)
        self.apply_update_button.setEnabled(False)
        self.restart_button = QPushButton("Restart")
        self.restart_button.clicked.connect(self.restart_now)
        self.restart_button.setEnabled(False)
        close_button = QPushButton("Close")
        close_button.clicked.connect(box.hide)
        layout.addWidget(self.check_update_button)
        layout.addWidget(self.apply_update_button)
        layout.addWidget(self.restart_button)
        layout.addWidget(close_button)
        return box

    def apply_style(self):
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #0b0d0f; color: #f3f7f2; font-family: Segoe UI, Arial; font-size: 13px; }
            #Title { font-size: 31px; font-weight: 780; color: #f3f7f2; }
            #Tagline { color: #42e8d2; font-size: 12px; font-weight: 720; letter-spacing: 1px; text-transform: uppercase; }
            #Muted { color: #a7b0aa; }
            #BrandIcon { border: 1px solid #313a3e; border-radius: 10px; background: #0f1315; padding: 2px; }
            #PanelTitle { font-size: 15px; font-weight: 720; }
            #Pill, #PillMuted { border: 1px solid #313a3e; border-radius: 6px; padding: 7px 10px; background: #1c2225; min-width: 104px; }
            #PillMuted { color: #a7b0aa; }
            #UpdatePanel, QGroupBox, QListWidget, QPlainTextEdit, QTabWidget::pane { border: 1px solid #313a3e; border-radius: 8px; background: #15191b; }
            QGroupBox { margin-top: 10px; padding: 10px; font-weight: 700; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QPushButton { border: 1px solid #313a3e; border-radius: 6px; background: #14191b; min-height: 34px; padding: 0 12px; }
            QPushButton:hover, QPushButton:checked { border-color: #42e8d2; color: #42e8d2; }
            QPushButton:disabled { color: #717b75; border-color: #2e3639; }
            QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox { border: 1px solid #313a3e; border-radius: 6px; background: #0f1315; min-height: 32px; padding: 2px 8px; }
            QListWidget::item { border-bottom: 1px solid #263035; padding: 7px; }
            #TranscriptLog { padding: 8px; line-height: 1.35; }
            QTabBar::tab { background: #14191b; border: 1px solid #313a3e; border-bottom: 0; padding: 8px 12px; border-top-left-radius: 6px; border-top-right-radius: 6px; }
            QTabBar::tab:selected { color: #42e8d2; border-color: #42e8d2; }
            """
        )

    def load_presets(self):
        for group in PRESET_GROUPS:
            page = QWidget()
            outer = QVBoxLayout(page)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            inner = QWidget()
            grid = QGridLayout(inner)
            grid.setSpacing(8)
            for idx, channel in enumerate(group["channels"]):
                button = QPushButton(f"{channel['name']}\n{channel['mhz']:.4f} MHz")
                button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                button.clicked.connect(
                    lambda checked=False, ch=channel, mode=group["mode"]: self.tune(
                        ch["mhz"],
                        mode,
                        start_audio=self.auto_listen.isChecked(),
                    )
                )
                grid.addWidget(button, idx // 6, idx % 6)
            scroll.setWidget(inner)
            outer.addWidget(scroll)
            self.preset_tabs.addTab(page, group["name"])

    def worker(self, tag, fn):
        if self.closing:
            return
        job = FunctionWorker(tag, fn)
        job.signals.result.connect(self.on_worker_result)
        job.signals.error.connect(self.on_worker_error)
        job.signals.finished.connect(self.on_worker_finished)
        self.active_workers.append(job)
        self.thread_pool.start(job)

    def on_worker_finished(self, job):
        if job in self.active_workers:
            self.active_workers.remove(job)
        if job is self.audio_worker:
            self.audio_worker = None
            if self.pending_audio_restart and not self.closing:
                self.pending_audio_restart = False
                QTimer.singleShot(60, self.start_audio_stream)

    def shutdown_workers(self):
        self.closing = True
        self.running = False
        self.stop_audio_stream(update_state=False)
        if hasattr(self, "spectrum_timer"):
            self.spectrum_timer.stop()
        self.thread_pool.waitForDone(9000)

    def radio_kwargs(self):
        return {
            "center_hz": int(self.freq.value() * 1_000_000),
            "sample_rate": int(self.sample_rate.currentData()),
            "gain_tenths_db": int(self.gain.value() * 10) if not self.auto_gain.isChecked() else None,
            "auto_gain": self.auto_gain.isChecked(),
        }

    def queue_status(self):
        self.worker("status", manager.status)

    def queue_spectrum(self):
        if not self.running or self.spectrum_busy or self.audio_running:
            return
        self.spectrum_busy = True
        kwargs = self.radio_kwargs()
        self.worker("spectrum", lambda: manager.get().spectrum(**kwargs, fft_size=2048))

    def queue_scan(self):
        if self.audio_running:
            self.stop_audio_stream(update_state=False)
        self.scan_button.setEnabled(False)
        self.state_label.setText("Scanning")
        group = PRESET_GROUPS[self.preset_tabs.currentIndex()]
        channels = []
        for channel in group["channels"]:
            item = dict(channel)
            item["group"] = group["name"]
            item["group_id"] = group["id"]
            item["mode"] = group["mode"]
            item["hz"] = int(round(float(channel["mhz"]) * 1_000_000))
            channels.append(item)
        self.worker("scan", lambda: manager.get().scan_channels(channels, max_channels=60))

    def queue_update_check(self, user_requested=True):
        self.user_requested_update_check = bool(user_requested)
        self.check_update_button.setEnabled(False)
        if user_requested or self.update_panel.isVisible():
            self.update_title.setText("Checking updates")
        self.worker("update-check", check_for_update)

    def queue_apply_update(self):
        self.apply_update_button.setEnabled(False)
        self.check_update_button.setEnabled(False)
        self.update_panel.show()
        self.update_title.setText("Installing update")
        self.update_detail.setText("Downloading and installing the published WavePilot SDR update.")
        self.worker("update-apply", apply_update)

    def tune(self, mhz, mode, start_audio=False):
        was_listening = self.audio_running
        if was_listening:
            self.stop_audio_stream(update_state=False)
            self.pending_audio_restart = True
        self.suppress_receiver_change = True
        try:
            self.freq.setValue(float(mhz))
            self.mode.setCurrentText(mode)
        finally:
            self.suppress_receiver_change = False
        self.spectrum.bins = []
        self.state_label.setText("Listening" if start_audio or was_listening else "Tuned")
        if not was_listening:
            if start_audio:
                QTimer.singleShot(80, self.start_audio_stream)
            else:
                self.queue_spectrum()

    def receiver_settings_changed(self):
        if self.suppress_receiver_change:
            return
        if self.audio_running:
            self.audio_restart_timer.start(360)
        elif self.running:
            self.queue_spectrum()

    def toggle_running(self):
        self.running = not self.running
        self.pause_button.setText("Pause" if self.running else "Run")
        self.state_label.setText("Live" if self.running else "Paused")
        if self.running:
            self.queue_spectrum()

    def toggle_audio(self):
        if self.audio_running:
            self.stop_audio_stream()
            return
        kwargs = self.radio_kwargs()
        settings = {
            "center_hz": kwargs["center_hz"],
            "mode": self.mode.currentText(),
            "gain_tenths_db": kwargs["gain_tenths_db"],
            "auto_gain": kwargs["auto_gain"],
            "muted": self.mute_audio.isChecked(),
            "squelch": self.squelch_audio.isChecked(),
            "transcript": self.transcript_enabled.isChecked(),
        }
        self.start_audio_stream(settings)

    def start_audio_stream(self, settings=None):
        if self.closing:
            return
        if self.audio_worker is not None:
            self.stop_audio_stream(update_state=False)
            self.pending_audio_restart = True
            return
        if settings is None:
            kwargs = self.radio_kwargs()
            settings = {
                "center_hz": kwargs["center_hz"],
                "mode": self.mode.currentText(),
                "gain_tenths_db": kwargs["gain_tenths_db"],
                "auto_gain": kwargs["auto_gain"],
                "muted": self.mute_audio.isChecked(),
                "squelch": self.squelch_audio.isChecked(),
                "transcript": self.transcript_enabled.isChecked(),
            }
        self.audio_running = True
        self.listen_button.setText("Stop Audio")
        self.state_label.setText("Starting audio")
        if settings.get("transcript"):
            self.transcript_state.setText("Starting")
            self.transcript_partial.setText("Loading transcript model.")
        self.spectrum_busy = False
        job = AudioStreamWorker(settings)
        job.signals.result.connect(self.on_worker_result)
        job.signals.error.connect(self.on_worker_error)
        job.signals.finished.connect(self.on_worker_finished)
        self.audio_worker = job
        self.active_workers.append(job)
        self.thread_pool.start(job)

    def stop_audio_stream(self, update_state=True):
        self.audio_restart_timer.stop()
        self.pending_audio_restart = False
        self.audio_running = False
        self.listen_button.setText("Listen Live")
        if self.audio_worker is not None:
            self.audio_worker.stop()
        if not self.pending_audio_restart and not self.closing:
            self.transcript_state.setText("Idle")
        if update_state and not self.closing:
            self.state_label.setText("Live" if self.running else "Paused")

    def restart_audio_stream(self):
        if not self.audio_running:
            return
        self.state_label.setText("Retuning")
        self.stop_audio_stream(update_state=False)
        self.pending_audio_restart = True

    def render_spectrum_payload(self, payload):
        self.spectrum.set_payload(payload)
        self.waterfall.add_bins(payload.get("bins", []))
        self.scope_meta.setText(f"{payload['center_hz'] / 1_000_000:.3f} MHz center | {payload['sample_rate'] / 1_000_000:.3f} MS/s | {payload['snr_db']:.1f} dB SNR")
        self.peak_label.setText(f"Peak {payload['peak_hz'] / 1_000_000:.3f} MHz")
        self.strong_list.clear()
        for peak in payload.get("peaks", [])[:8]:
            item = QListWidgetItem(f"{peak['mhz']:.3f} MHz   {peak['snr']:.1f} dB")
            item.setData(Qt.UserRole, {"mhz": float(peak["mhz"]), "mode": self.mode.currentText()})
            self.strong_list.addItem(item)

    def activate_channel_item(self, item):
        data = item.data(Qt.UserRole)
        if not isinstance(data, dict):
            return
        mhz = float(data.get("mhz") or (float(data.get("hz", 0)) / 1_000_000.0))
        if mhz <= 0:
            return
        self.tune(mhz, data.get("mode") or self.mode.currentText(), start_audio=True)

    def on_worker_result(self, tag, payload):
        if self.closing:
            return
        if tag == "status":
            self.device_label.setText(payload.get("device", {}).get("name") if payload.get("radio_available") else payload.get("error", "Receiver unavailable"))
            self.state_label.setText("Live" if payload.get("radio_available") else "Driver needed")
        elif tag == "spectrum":
            self.spectrum_busy = False
            self.render_spectrum_payload(payload)
            if self.running and not self.audio_running:
                self.state_label.setText("Live")
        elif tag == "scan":
            self.scan_button.setEnabled(True)
            self.scan_list.clear()
            for item in payload.get("results", []):
                row = QListWidgetItem(f"{item['mhz']:.4f} MHz   {item['name']}   {item['snr_db']:.1f} dB")
                row.setData(
                    Qt.UserRole,
                    {
                        "mhz": float(item["mhz"]),
                        "mode": item.get("mode") or self.mode.currentText(),
                        "name": item.get("name", ""),
                    },
                )
                self.scan_list.addItem(row)
            self.state_label.setText("Scan done")
        elif tag == "audio-spectrum":
            self.render_spectrum_payload(payload)
        elif tag == "audio-status":
            if self.audio_running:
                self.state_label.setText("Real-time")
                seconds = float(payload.get("seconds", 0.0))
                audio_state = "Muted" if payload.get("muted") else "Audio"
                squelch_state = " | squelch" if payload.get("squelch") else ""
                self.scope_meta.setText(
                    f"Real-time {audio_state.lower()} | {payload.get('mode', self.mode.currentText()).upper()} | "
                    f"{payload.get('audio_rate', 48000) / 1000:.0f} kHz stream{squelch_state} | {seconds:.1f}s"
                )
        elif tag == "audio-stopped":
            if not self.audio_running and not self.pending_audio_restart:
                self.state_label.setText("Live" if self.running else "Paused")
        elif tag == "transcript":
            self.handle_transcript(payload)
        elif tag == "update-check":
            self.check_update_button.setEnabled(True)
            self.latest_update = payload
            self.render_update(payload)
        elif tag == "update-apply":
            self.check_update_button.setEnabled(True)
            self.restart_button.setEnabled(bool(payload.get("restart_required")))
            self.update_title.setText("Update installed" if payload.get("installed") else "Already current")
            self.update_detail.setText(payload.get("message", "Update complete."))

    def on_worker_error(self, tag, message):
        if self.closing:
            return
        if tag == "spectrum":
            self.spectrum_busy = False
            self.scope_meta.setText(message)
            self.device_label.setText(message)
            self.state_label.setText("Waiting")
        elif tag == "scan":
            self.scan_button.setEnabled(True)
            self.state_label.setText("Scan failed")
            self.scan_list.clear()
            self.scan_list.addItem(message)
        elif tag == "audio-stream":
            self.audio_running = False
            self.listen_button.setText("Listen Live")
            self.state_label.setText("Audio error")
            self.scope_meta.setText(message)
        elif tag.startswith("update"):
            self.check_update_button.setEnabled(True)
            self.apply_update_button.setEnabled(False)
            if self.user_requested_update_check or tag == "update-apply":
                self.update_panel.show()
            self.update_title.setText("Update unavailable")
            self.update_detail.setText(message)
        else:
            self.state_label.setText("Error")

    def clear_transcript(self):
        self.transcript_log.clear()
        self.transcript_partial.setText("Transcript cleared.")

    def handle_transcript(self, payload):
        kind = payload.get("type")
        text = (payload.get("text") or "").strip()
        if kind == "status":
            ok = bool(payload.get("ok"))
            if payload.get("loading"):
                self.transcript_state.setText("Loading")
            else:
                self.transcript_state.setText("Ready" if ok else "Model needed")
            self.transcript_partial.setText(text or ("Transcript ready." if ok else "Transcript unavailable."))
            if text:
                self.transcript_log.appendPlainText(f"[{self.transcript_state.text()}] {text}")
        elif kind == "partial":
            self.transcript_state.setText("Hearing")
            self.transcript_partial.setText(text)
        elif kind == "final" and text:
            self.transcript_state.setText("Transcript")
            self.transcript_partial.setText("")
            timestamp = time.strftime("%H:%M:%S", time.localtime(float(payload.get("time") or time.time())))
            self.transcript_log.appendPlainText(f"{timestamp}  {text}")

    def render_update(self, payload):
        current = payload.get("current_version", __version__)
        latest = payload.get("latest_version", current)
        if payload.get("update_available"):
            self.update_button.setText(f"Update {latest}")
            self.update_title.setText(f"WavePilot SDR {latest} available")
            notes = payload.get("notes") or []
            detail = " ".join(notes) if notes else f"Current version is {current}."
            if not payload.get("can_apply"):
                detail = payload.get("apply_blocker") or detail
            self.update_detail.setText(detail)
            self.apply_update_button.setEnabled(bool(payload.get("can_apply")))
        else:
            self.update_button.setText("Up to date")
            self.update_title.setText("WavePilot SDR is up to date")
            self.update_detail.setText(f"Current version: {current}.")
            self.apply_update_button.setEnabled(False)

    def toggle_update_panel(self):
        self.update_panel.setVisible(not self.update_panel.isVisible())
        if self.update_panel.isVisible():
            self.queue_update_check(True)

    def restart_now(self):
        try:
            restart_application()
        except Exception as exc:
            QMessageBox.warning(self, "Restart failed", str(exc))
            return
        QApplication.instance().quit()

def main(argv=None):
    parser = argparse.ArgumentParser(description="Run WavePilot SDR desktop app")
    parser.parse_args(argv)
    app = QApplication([])
    if APP_ICON.exists():
        app.setWindowIcon(QIcon(str(APP_ICON)))
    window = WavePilotWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
