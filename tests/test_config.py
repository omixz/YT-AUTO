from youtube_automation.config import PipelineConfig


def test_load_default_config():
    config = PipelineConfig.load()
    assert config.channel.name
    assert config.video.format in ("shorts", "longform")
    assert config.video.resolution == tuple(config.video.resolution_shorts)


def test_longform_resolution_switch():
    config = PipelineConfig.load()
    config.video.format = "longform"
    assert config.video.resolution == tuple(config.video.resolution_longform)
