import logging

from openai import OpenAI

from podcast_processor.env_settings import populate_env_settings
from podcast_processor.transcribe import RemoteWhisperTranscriber


def test_transcribe() -> None:
    logger = logging.getLogger("global_logger")
    env_settings = populate_env_settings()
    client = OpenAI(
        base_url=env_settings.openai_base_url,
        api_key=env_settings.openai_api_key,
    )

    transcriber = RemoteWhisperTranscriber(logger, client)
    transcriber.transcribe()
