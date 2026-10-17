"""Speech-gated end-of-utterance detection on the processed microphone channel."""

import numpy as np


class SpeechEndpoint:
    def __init__(self, sample_rate, silence_seconds=0.6, start_timeout=3.0,
                 min_speech_seconds=0.12, start_rms=700, continue_rms=450):
        self.sample_rate = sample_rate
        self.silence_samples = round(silence_seconds * sample_rate)
        self.start_timeout_samples = round(start_timeout * sample_rate)
        self.min_speech_samples = round(min_speech_seconds * sample_rate)
        self.start_rms = start_rms
        self.continue_rms = continue_rms
        self.total_samples = 0
        self.voiced_samples = 0
        self.quiet_samples = 0
        self.started = False

    def feed(self, samples, speech_detected=None):
        if not samples.size:
            return None
        self.total_samples += samples.size
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
        threshold = self.continue_rms if self.started else self.start_rms
        if rms >= threshold and speech_detected is not False:
            self.voiced_samples += samples.size
            self.quiet_samples = 0
            if self.voiced_samples >= self.min_speech_samples:
                self.started = True
        elif self.started:
            self.quiet_samples += samples.size
        else:
            self.voiced_samples = 0
        if self.started and self.quiet_samples >= self.silence_samples:
            return "silence"
        if not self.started and self.total_samples >= self.start_timeout_samples:
            return "no_speech"
        return None
