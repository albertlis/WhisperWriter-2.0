import time
import traceback
from typing import override

import numpy as np
import sounddevice as sd
import webrtcvad
from PyQt6.QtCore import QThread, QMutex, pyqtSignal
from collections import deque
from threading import Event

from transcription import transcribe
from utils import ConfigManager
from media_controller import MediaController


class ResultThread(QThread):
    """
    A thread class for handling audio recording, transcription, and result processing.

    This class manages the entire process of:
    1. Recording audio from the microphone
    2. Detecting speech and silence
    3. Saving the recorded audio as numpy array
    4. Transcribing the audio
    5. Emitting the transcription result

    Signals:
        statusSignal: Emits the current status of the thread (e.g., 'recording', 'transcribing', 'idle')
        resultSignal: Emits the transcription result
    """

    statusSignal: pyqtSignal = pyqtSignal(str, bool)
    resultSignal: pyqtSignal = pyqtSignal(str)
    levelSignal: pyqtSignal = pyqtSignal(float)  # RMS of each 30 ms frame, 0..1 — drives the status meter

    def __init__(self, local_model: object | None = None, use_llm: bool = False) -> None:
        super().__init__()
        self.local_model: object | None = local_model
        self.use_llm: bool = use_llm
        self.is_recording: bool = False
        self.is_running: bool = True
        self.sample_rate: int | None = None
        self.mutex: QMutex = QMutex()
        self.stop_event: Event = Event()
        self.media_controller: MediaController = MediaController()
        self.last_audio_time: float = time.time()
        self.is_transcribing: bool = False
        # Kept for the training-data recorder — read by main.on_transcription_complete
        self.last_audio: np.ndarray | None = None

    def stop_recording(self) -> None:
        """Stop the current recording session."""
        self.mutex.lock()
        self.is_recording = False
        self.mutex.unlock()

    def stop(self) -> None:
        """Stop the entire thread execution."""
        self.mutex.lock()
        self.is_running = False
        self.mutex.unlock()
        self.statusSignal.emit('idle', False)
        self.wait()

    @override
    def run(self) -> None:
        """Main execution method for the thread."""
        try:
            if not self.is_running:
                return

            # Only control media if the setting is enabled
            if ConfigManager.get_config_value('misc', 'pause_media_during_recording'):
                self.media_controller.pause_media()
                self.media_controller.was_playing = True

            self.mutex.lock()
            self.is_recording = True
            self.mutex.unlock()

            audio_data = self._record_audio()
            self.last_audio = audio_data

            if not self.is_running:
                return

            if audio_data is None or len(audio_data) == 0:
                self.statusSignal.emit('idle', self.use_llm)
                return

            self.is_transcribing = True  # Set transcribing flag
            self.statusSignal.emit('transcribing', self.use_llm)
            ConfigManager.console_print('Transcribing...')

            # Time the transcription process
            start_time = time.time()
            result = transcribe(audio_data, self.local_model)
            end_time = time.time()

            transcription_time = end_time - start_time
            ConfigManager.console_print(f'Transcription completed in {transcription_time:.2f} seconds. Post-processed line: {result}')

            if not self.is_running:
                return

            self.statusSignal.emit('idle', self.use_llm)
            self.resultSignal.emit(result)

            # Reset transcribing flag and update last_audio_time after successful transcription
            self.is_transcribing = False
            self.last_audio_time = time.time()

            # Only resume media if the setting is enabled
            if ConfigManager.get_config_value('misc', 'pause_media_during_recording'):
                self.media_controller.resume_media()

        except Exception as e:
            ConfigManager.console_print(f"Error in ResultThread: {str(e)}")
            traceback.print_exc()
            self.statusSignal.emit('error', self.use_llm)
            self.resultSignal.emit('')
        finally:
            self.is_transcribing = False  # Ensure flag is reset

    def _record_audio(self) -> np.ndarray | None:
        recording_options = ConfigManager.get_config_section('recording_options') or {}
        self.sample_rate = recording_options.get('sample_rate') or 16000
        frame_duration_ms = 30
        frame_size = int(self.sample_rate * (frame_duration_ms / 1000.0))
        silence_duration_ms = recording_options.get('silence_duration') or 900
        silence_frames = int(silence_duration_ms / frame_duration_ms)
        continuous_timeout = ConfigManager.get_config_value('recording_options', 'continuous_timeout')
        recording_mode = recording_options.get('recording_mode') or 'continuous'

        vad = None
        speech_detected = False
        silent_frame_count = 0
        if recording_mode in ('voice_activity_detection', 'continuous'):
            vad = webrtcvad.Vad(2)

        audio_buffer = deque(maxlen=frame_size)
        recording = []
        last_speech_time = time.time()
        data_ready = Event()

        def audio_callback(indata, frames, time, status):
            if status:
                ConfigManager.console_print(f"Audio callback status: {status}")
            audio_buffer.extend(indata[:, 0])
            data_ready.set()

        # Open per recording (like Teams/Zoom): the headset leaves HFP when idle and a
        # reconnected device is picked up next time. Frames are kept from the first one —
        # a quiet start while the device settles costs Whisper nothing.
        with sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype='int16',
            blocksize=frame_size, device=recording_options.get('sound_device'),
            callback=audio_callback,
        ):
            # UI-only: 'recording' once the device delivers a non-zero frame (BT sends pure
            # zeros while switching to HFP) or after 1 s. Frames are recorded either way.
            self.statusSignal.emit('warming_up', self.use_llm)
            mic_ready = False
            opened_at = time.time()
            # Prepend silence so Whisper doesn't clip the first word
            recording.extend(np.zeros(int(0.3 * self.sample_rate), dtype=np.int16))

            while self.is_running and self.is_recording:
                if not data_ready.wait(timeout=1.0):
                    continue
                data_ready.clear()

                if len(audio_buffer) < frame_size:
                    continue

                frame = np.array(list(audio_buffer), dtype=np.int16)
                audio_buffer.clear()
                recording.extend(frame)
                if not mic_ready and (frame.any() or time.time() - opened_at >= 1.0):
                    mic_ready = True
                    self.statusSignal.emit('recording', self.use_llm)
                    ConfigManager.console_print(f'Recording... (mic ready after {time.time() - opened_at:.2f}s)')
                self.levelSignal.emit(float(np.sqrt(np.mean(frame.astype(np.float32) ** 2))) / 32768.0)

                if recording_mode in ('voice_activity_detection', 'continuous'):
                    if vad and vad.is_speech(frame.tobytes(), self.sample_rate):
                        last_speech_time = time.time()
                        if recording_mode == 'continuous':
                            silent_frame_count = 0
                        if not speech_detected:
                            ConfigManager.console_print("Speech detected.")
                            speech_detected = True
                    else:
                        if recording_mode == 'continuous':
                            silent_frame_count += 1

                if (recording_mode == 'continuous' and
                        continuous_timeout is not None and continuous_timeout > 0 and
                        time.time() - last_speech_time > continuous_timeout):
                    ConfigManager.console_print(f"[DEBUG] No audio detected for {continuous_timeout} seconds. Stopping continuous recording.")
                    self.is_running = False
                    self.is_recording = False
                    self.statusSignal.emit('idle', False)
                    return None

                if recording_mode in ('voice_activity_detection', 'continuous'):
                    if speech_detected and silent_frame_count > silence_frames:
                        break

        audio_data = np.array(recording, dtype=np.int16)
        duration = len(audio_data) / self.sample_rate

        ConfigManager.console_print(f'Recording finished. Size: {audio_data.size} samples, Duration: {duration:.2f} seconds')

        min_duration_ms = (recording_options.get('min_duration') if recording_options else None) or 100
        if (duration * 1000) < min_duration_ms:
            ConfigManager.console_print('Discarded due to being too short.')
            return None

        return audio_data