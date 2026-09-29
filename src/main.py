import os
import sys
import time
from audioplayer import AudioPlayer
from pynput.keyboard import Controller, Key
from PyQt6.QtCore import QObject, QProcess
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
import ctypes
import win32clipboard
import win32con

from key_listener import KeyListener
from result_thread import ResultThread, SharedMicStream
from ui.settings_window import SettingsWindow
from ui.status_window import StatusWindow
from ui.review_window import ReviewDialog
import dataset_recorder
from transcription import create_local_model
from input_simulation import InputSimulator
from utils import ConfigManager
from llm_processor import LLMProcessor


class WhisperWriterApp(QObject):
    def __init__(self):
        """
        Initialize the application, opening settings window if no configuration file is found.
        """
        super().__init__()
        # Initialize all instance vars before any listener/callback can fire
        self.input_simulator: InputSimulator | None = None
        self.key_listener: KeyListener | None = None
        self.local_model = None
        self.result_thread: ResultThread | None = None
        self.llm_processor: LLMProcessor | None = None
        self._mic_stream: SharedMicStream | None = None
        self.status_window: StatusWindow | None = None
        self.tray_icon: QSystemTrayIcon | None = None
        self.use_llm: bool = False
        self.is_instruction_mode: bool = False
        self._reviewing: bool = False

        self.app = QApplication(sys.argv)
        self.app.setWindowIcon(QIcon(os.path.join("assets", "ww-logo.png")))
        # Tray-only app: closing a transient dialog (e.g. ReviewDialog) must not quit it.
        self.app.setQuitOnLastWindowClosed(False)

        ConfigManager.initialize()

        self.settings_window = SettingsWindow()
        self.settings_window.settings_closed.connect(self.on_settings_closed)
        self.settings_window.settings_saved.connect(self.restart_app)

        if ConfigManager.config_file_exists():
            self.initialize_components()
            # Start listening immediately instead of showing main window
            self.key_listener.start()
        else:
            print("No valid configuration file found. Opening settings window...")
            self.settings_window.show()

    def initialize_components(self):
        """
        Initialize the components of the application.
        """
        self.input_simulator = InputSimulator()

        self.key_listener = KeyListener()
        self.key_listener.add_callback("on_activate", self.on_activation)
        self.key_listener.add_callback(
            "on_activate_with_llm", self.on_activation_with_llm_cleanup
        )
        self.key_listener.add_callback(
            "on_activate_with_llm_instruction", self.on_activation_with_llm_instruction
        )
        self.key_listener.add_callback("on_deactivate", self.on_deactivation)
        self.key_listener.add_callback(
            "on_deactivate_with_llm", self.on_deactivation_with_llm
        )
        self.key_listener.add_callback(
            "on_deactivate_with_llm_instruction",
            self.on_deactivation_with_llm_instruction,
        )
        self.key_listener.add_callback("on_text_cleanup", self.handle_text_cleanup)

        model_options = ConfigManager.get_config_section("model_options")
        self.local_model = (
            create_local_model() if not model_options.get("use_api") else None
        )

        self.result_thread = None
        self.llm_processor = (
            LLMProcessor()
            if ConfigManager.get_config_value("llm_post_processing", "enabled")
            else None
        )

        # Close previous stream if initialize_components() is called a second time (on_settings_closed path)
        _prev = getattr(self, "_mic_stream", None)
        if _prev is not None:
            try:
                _prev.close()
            except Exception:
                pass
        self._mic_stream = None
        if ConfigManager.get_config_value("misc", "fast_start_mic"):
            try:
                _ro = ConfigManager.get_config_section("recording_options") or {}
                _sr = _ro.get("sample_rate") or 16000
                self._mic_stream = SharedMicStream(
                    _sr, int(_sr * 30 / 1000), _ro.get("sound_device")
                )
            except Exception as e:
                ConfigManager.console_print(
                    f"Shared mic stream failed, cold-open fallback active: {e}"
                )
                self._mic_stream = None

        if not ConfigManager.get_config_value("misc", "hide_status_window"):
            self.status_window = StatusWindow()

        self.create_tray_icon()

    def create_tray_icon(self):
        """
        Create the system tray icon and its context menu.
        """
        self.tray_icon = QSystemTrayIcon(
            QIcon(os.path.join("assets", "ww-logo.png")), self.app
        )

        self.tray_menu = QMenu()

        settings_action = QAction("Settings", self.app)
        settings_action.triggered.connect(self.settings_window.show)
        self.tray_menu.addAction(settings_action)

        exit_action = QAction("Exit", self.app)
        exit_action.triggered.connect(self.exit_app)
        self.tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()

    def cleanup(self):
        if getattr(self, "key_listener", None):
            self.key_listener.stop()
        if getattr(self, "input_simulator", None):
            self.input_simulator.cleanup()
        if getattr(self, "_mic_stream", None) is not None:
            try:
                self._mic_stream.close()
            except Exception:
                pass

    def exit_app(self):
        """
        Exit the application.
        """
        self.cleanup()
        QApplication.quit()

    def restart_app(self):
        """Restart the application to apply the new settings."""
        self.cleanup()
        _release_single_instance()
        QProcess.startDetached(sys.executable, sys.argv)
        QApplication.quit()

    def on_settings_closed(self):
        """
        If settings is closed without saving on first run, initialize the components with default values.
        """
        if not os.path.exists(os.path.join("src", "config.yaml")):
            QMessageBox.information(
                self.settings_window,
                "Using Default Values",
                "Settings closed without saving. Default values are being used.",
            )
            self.initialize_components()

    def on_activation(self, use_llm=False, is_instruction_mode=False):
        """
        Called when the activation key combination is pressed.
        Args:
            use_llm (bool): Whether to use LLM processing for this activation
            is_instruction_mode (bool): Whether to use instruction mode for LLM processing
        """
        if self.result_thread and self.result_thread.isRunning():
            recording_mode = ConfigManager.get_config_value(
                "recording_options", "recording_mode"
            )
            if recording_mode == "press_to_toggle":
                self.result_thread.stop_recording()
            elif recording_mode == "continuous":
                self.stop_result_thread()
            return

        # If we get here, no thread is running, so start one
        self.use_llm = use_llm
        self.is_instruction_mode = is_instruction_mode
        self.start_result_thread()

    def on_activation_with_llm_cleanup(self):
        """Activation with LLM cleanup based on recording mode"""
        self.on_activation(use_llm=True, is_instruction_mode=False)

    def on_activation_with_llm_instruction(self):
        """Activation with LLM instruction processing"""
        self.on_activation(use_llm=True, is_instruction_mode=True)

    def on_deactivation(self, use_llm=False, is_instruction_mode=False):
        """
        Called when the activation key combination is released.
        Args:
            use_llm (bool): Whether to use LLM processing for this deactivation
            is_instruction_mode (bool): Whether to use instruction mode for LLM processing
        """
        # Set the flags just like in on_activation
        self.use_llm = use_llm
        self.is_instruction_mode = is_instruction_mode

        ConfigManager.console_print(
            f"Deactivation called - use_llm: {use_llm}, is_instruction_mode: {is_instruction_mode}"
        )
        ConfigManager.console_print(
            f"Recording mode: {ConfigManager.get_config_value('recording_options', 'recording_mode')}"
        )
        ConfigManager.console_print(
            f"Result thread running: {self.result_thread and self.result_thread.isRunning()}"
        )

        if (
            ConfigManager.get_config_value("recording_options", "recording_mode")
            == "hold_to_record"
        ):
            if self.result_thread and self.result_thread.isRunning():
                ConfigManager.console_print("Stopping recording...")
                self.result_thread.stop_recording()

    def on_deactivation_with_llm(self):
        """Called when the LLM cleanup activation key combination is released."""
        ConfigManager.console_print("LLM cleanup deactivation triggered")
        self.on_deactivation(use_llm=True, is_instruction_mode=False)

    def on_deactivation_with_llm_instruction(self):
        """Called when the LLM instruction activation key combination is released."""
        ConfigManager.console_print("LLM instruction deactivation triggered")
        self.on_deactivation(use_llm=True, is_instruction_mode=True)

    def start_result_thread(self):
        """
        Start the result thread to record audio and transcribe it.
        """
        if self.result_thread and self.result_thread.isRunning():
            return

        self.result_thread = ResultThread(
            self.local_model, self.use_llm, getattr(self, "_mic_stream", None)
        )
        if not ConfigManager.get_config_value("misc", "hide_status_window"):
            self.result_thread.statusSignal.connect(self.status_window.updateStatus)
            self.result_thread.levelSignal.connect(self.status_window.push_level)
            self.status_window.closeSignal.connect(self.stop_result_thread)
        self.result_thread.resultSignal.connect(self.on_transcription_complete)
        self.result_thread.start()

    def stop_result_thread(self):
        """
        Stop the result thread.
        """
        if self.result_thread and self.result_thread.isRunning():
            self.result_thread.stop()

    def on_transcription_complete(self, result):
        """Process transcription with or without LLM based on activation type."""
        try:
            # Temporarily disable key listener
            if self.key_listener:
                self.key_listener.stop()

            raw_result = result
            llm_applied = False
            if not result.strip():
                ConfigManager.console_print(
                    "Empty transcription, nothing to review or save."
                )
                return

            recording_mode = ConfigManager.get_config_value(
                "recording_options", "recording_mode"
            )
            if (
                self.use_llm
                and self.llm_processor
                and recording_mode
                in (
                    "press_to_toggle",
                    "hold_to_record",
                    "continuous",
                    "voice_activity_detection",
                )
            ):
                try:
                    # Get the system message based on the mode
                    if self.is_instruction_mode:
                        base_message = ConfigManager.get_config_value(
                            "llm_post_processing", "instruction_system_message"
                        )
                        file_path = ConfigManager.get_config_value(
                            "llm_post_processing",
                            "instruction_system_message_file_path",
                        )
                        mode_name = "instruction"
                    else:
                        base_message = ConfigManager.get_config_value(
                            "llm_post_processing", "system_prompt"
                        )
                        file_path = ConfigManager.get_config_value(
                            "llm_post_processing", "system_prompt_file_path"
                        )
                        mode_name = "cleanup"

                    # Start with a clean system message
                    system_message = base_message.strip() if base_message else ""

                    ConfigManager.console_print(
                        f"Retrieved {mode_name} base message from settings: {system_message}"
                    )

                    if not file_path:
                        ConfigManager.console_print(
                            "No file path set, using only the system message from settings"
                        )
                    elif not os.path.exists(file_path):
                        ConfigManager.console_print(
                            f"File path set but file not found: {file_path}, using only the system message from settings"
                        )

                    # Append file contents if file path exists and is not empty
                    if file_path and os.path.exists(file_path):
                        try:
                            with open(file_path, "r", encoding="utf-8") as file:
                                file_content = file.read().strip()
                                if file_content:  # Only append if file has content
                                    if system_message:
                                        system_message = (
                                            f"{system_message}\n\n{file_content}"
                                        )
                                    else:
                                        system_message = file_content
                                    ConfigManager.console_print(
                                        f"Added fresh file content from {file_path}"
                                    )
                        except Exception as e:
                            ConfigManager.console_print(
                                f"Error reading system message file: {str(e)}"
                            )

                    if not system_message:
                        ConfigManager.console_print(
                            "Warning: No system message found, using original transcription"
                        )
                        return result

                    ConfigManager.console_print(
                        f"Final system message being sent to LLM: {system_message}"
                    )
                    processed_result = self.llm_processor.process_text(
                        result, system_message
                    )
                    if processed_result:
                        result = processed_result.strip()
                        llm_applied = True
                    else:
                        ConfigManager.console_print(
                            "LLM processing failed, using original transcription"
                        )

                except Exception as e:
                    ConfigManager.console_print(
                        f"Error processing text through LLM: {str(e)}"
                    )
                    return result

            # Review shows the final text (after LLM, if any).
            if ConfigManager.get_config_value("training_data", "review_before_paste"):
                # ReviewDialog.exec() spins a nested event loop, so a resultSignal from a
                # second recording would stack another dialog on top of this one. Drop it.
                if self._reviewing:
                    ConfigManager.console_print(
                        "Review already open, dropping transcription."
                    )
                    return
                self._reviewing = True
                try:
                    reviewed = ReviewDialog.get_text(
                        result,
                        self.result_thread.last_audio if self.result_thread else None,
                        (self.result_thread.sample_rate if self.result_thread else None)
                        or 16000,
                    )
                finally:
                    self._reviewing = False
                if reviewed is None:
                    ConfigManager.console_print("Review cancelled, nothing typed.")
                    return
                result = reviewed

            # LLM output is not valid ground truth for the recorded audio — skip it.
            if (
                ConfigManager.get_config_value("training_data", "save_recordings")
                and self.result_thread
                and not llm_applied
            ):
                dataset_recorder.save_sample(
                    self.result_thread.last_audio,
                    self.result_thread.sample_rate,
                    result,
                    raw_result,
                )

            # Type the result
            self.input_simulator.typewrite(result)

            if ConfigManager.get_config_value("misc", "noise_on_completion"):
                AudioPlayer(os.path.join("assets", "beep.wav")).play(block=True)

            if (
                ConfigManager.get_config_value("recording_options", "recording_mode")
                == "continuous"
            ):
                self.start_result_thread()

        finally:
            # Re-enable key listener
            if getattr(self, "key_listener", None):
                self.key_listener.start()

    def handle_text_cleanup(self):
        """Handle the text selection cleanup shortcut."""
        if not self.llm_processor:
            return

        # Store all clipboard formats
        saved_formats = {}
        win32clipboard.OpenClipboard()

        try:
            # Get the list of available formats
            format_id = win32clipboard.EnumClipboardFormats(0)
            while format_id:
                try:
                    data = win32clipboard.GetClipboardData(format_id)
                    saved_formats[format_id] = data
                except Exception:
                    pass  # Skip formats we can't handle
                format_id = win32clipboard.EnumClipboardFormats(format_id)

            # Get the text content
            clipboard_text = saved_formats.get(win32con.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()

            if not clipboard_text:
                ConfigManager.console_print("No text in clipboard")
                return

            ConfigManager.console_print(
                f"Processing clipboard text: {clipboard_text[:100]}..."
            )

            # Get the base system message
            base_message = ConfigManager.get_config_value(
                "llm_post_processing", "text_cleanup_system_message"
            )
            file_path = ConfigManager.get_config_value(
                "llm_post_processing", "text_cleanup_system_message_file_path"
            )

            # Start with a clean system message
            system_message = base_message.strip() if base_message else ""

            ConfigManager.console_print(
                f"Base cleanup system message: {system_message}"
            )

            # Append file contents if file path exists and is not empty
            if file_path and os.path.exists(file_path):
                try:
                    ConfigManager.console_print(
                        f"Reading cleanup instructions from file: {file_path}"
                    )
                    with open(file_path, "r", encoding="utf-8") as file:
                        file_content = file.read().strip()
                        if file_content:  # Only append if file has content
                            if system_message:
                                system_message = f"{system_message}\n\n{file_content}"
                            else:
                                system_message = file_content
                            ConfigManager.console_print(
                                "Successfully added file content to cleanup instructions"
                            )
                except Exception as e:
                    ConfigManager.console_print(
                        f"Error reading cleanup system message file: {str(e)}"
                    )

            if not system_message:
                ConfigManager.console_print("Warning: No cleanup system message found")
                return

            ConfigManager.console_print(
                f"Final cleanup system message: {system_message}"
            )

            # Run through LLM cleanup
            cleaned_text = self.llm_processor.process_text(
                clipboard_text, system_message
            )

            if cleaned_text and cleaned_text != clipboard_text:
                try:
                    # Simulate keyboard events with proper cleanup
                    keyboard = Controller()

                    # First set the cleaned text to clipboard
                    win32clipboard.OpenClipboard()
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardText(
                        cleaned_text, win32con.CF_UNICODETEXT
                    )
                    win32clipboard.CloseClipboard()

                    try:
                        # Delete selected text and paste cleaned text
                        keyboard.press(Key.delete)
                        keyboard.release(Key.delete)
                        time.sleep(0.1)  # Small delay after delete

                        with keyboard.pressed(Key.ctrl):
                            keyboard.press("v")
                            keyboard.release("v")

                        if ConfigManager.get_config_value(
                            "misc", "noise_on_completion"
                        ):
                            AudioPlayer(os.path.join("assets", "beep.wav")).play(
                                block=True
                            )

                    finally:
                        # Ensure all keys are released
                        keyboard.release(Key.ctrl)
                        keyboard.release("v")
                        keyboard.release(Key.delete)

                        # Restore original clipboard content
                        time.sleep(0.1)  # Wait for paste to complete
                        win32clipboard.OpenClipboard()
                        win32clipboard.EmptyClipboard()
                        for format_id, data in saved_formats.items():
                            try:
                                win32clipboard.SetClipboardData(format_id, data)
                            except Exception:
                                pass  # Skip if we can't restore a particular format
                        win32clipboard.CloseClipboard()

                    # Clear the key chord state
                    self.key_listener.text_cleanup_chord.pressed_keys.clear()

                except Exception as e:
                    ConfigManager.console_print(f"Error simulating keyboard: {str(e)}")
            else:
                ConfigManager.console_print("Text unchanged after LLM processing")

        except Exception as e:
            ConfigManager.console_print(f"Error cleaning text: {str(e)}")
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass  # Ensure clipboard is closed even if an error occurred
            # Ensure key listener is restarted
            self.key_listener.start()

    def run(self):
        """
        Start the application.
        """
        sys.exit(self.app.exec())


_INSTANCE_MUTEX = "Local\\WhisperWriterSingleInstance"
_ERROR_ALREADY_EXISTS = 183
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_instance_lock: int | None = None


def _acquire_single_instance() -> bool:
    """Named mutex held for the process lifetime; a second instance finds it and exits.

    Two instances each own a key listener and a mic, so one hotkey press toggles both and
    the pill seems stuck recording.
    """
    global _instance_lock
    _instance_lock = _kernel32.CreateMutexW(None, False, _INSTANCE_MUTEX)
    return ctypes.get_last_error() != _ERROR_ALREADY_EXISTS


def _release_single_instance() -> None:
    """Called before restart_app spawns the successor, which would otherwise exit at once."""
    global _instance_lock
    if _instance_lock is not None:
        _kernel32.CloseHandle(_instance_lock)
        _instance_lock = None


if __name__ == "__main__":
    if not _acquire_single_instance():
        print("WhisperWriter is already running — exiting.")
        sys.exit(0)
    app = WhisperWriterApp()
    app.run()
