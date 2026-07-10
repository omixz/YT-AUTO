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


def test_niches_loaded():
    config = PipelineConfig.load()
    assert len(config.niches) >= 1
    keys = [n.key for n in config.niches]
    assert len(keys) == len(set(keys)), "niche keys must be unique"


def test_formats_loaded_with_weights():
    config = PipelineConfig.load()
    assert "shorts" in config.video.formats
    assert "longform" in config.video.formats
    assert config.video.formats["shorts"].target_seconds < config.video.formats["longform"].target_seconds
