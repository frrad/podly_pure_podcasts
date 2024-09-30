import logging
import math
import os
import shutil
from abc import ABC, abstractmethod
from typing import Any, List

from openai import OpenAI
from pydub import AudioSegment  # type: ignore[import-untyped]

Segment = Any


# Abstract Transcriber Class
class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, path: str) -> List[Segment]:
        pass


class RemoteWhisperTranscriber(Transcriber):
    def __init__(self, logger: logging.Logger, openai_client: OpenAI):
        self.logger = logger
        self.openai_client = openai_client

    def transcribe(self, audio_path: str) -> List[Segment]:
        self.logger.info("Using remote whisper")
        self.split_file(audio_path)
        all_segments = []
        for i in range(0, len(os.listdir(f"{audio_path}_parts")), 1):
            segments = self.get_segments_for_chunk(f"{audio_path}_parts/{i}.mp3")
            all_segments.extend(segments)
        # clean up
        shutil.rmtree(f"{audio_path}_parts")
        return all_segments

    def split_file(
        self, audio_path: str, chunk_size_bytes: int = 24 * 1024 * 1024
    ) -> None:
        if not os.path.exists(audio_path + "_parts"):
            os.makedirs(audio_path + "_parts")
        audio = AudioSegment.from_mp3(audio_path)
        duration_milliseconds = len(audio)
        chunk_duration = (
            chunk_size_bytes / os.path.getsize(audio_path)
        ) * duration_milliseconds
        chunk_duration = int(chunk_duration)

        num_chunks = math.ceil(duration_milliseconds / chunk_duration)
        for i in range(num_chunks):
            start_time = i * chunk_duration
            end_time = (i + 1) * chunk_duration
            chunk = audio[start_time:end_time]
            chunk.export(f"{audio_path}_parts/{i}.mp3", format="mp3")

    def get_segments_for_chunk(self, chunk_path: str) -> List[Segment]:
        with open(chunk_path, "rb") as f:
            model_extra = self.openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                timestamp_granularities=["segment"],
                language="en",
                response_format="verbose_json",
            ).model_extra

            assert model_extra is not None

            return model_extra["segments"]
