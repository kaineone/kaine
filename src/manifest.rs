pub const EXPECTED_CEILING: u32 = 300;
pub const EXPECTED_RATE: u32 = 8000;
pub const EXPECTED_CODEC: &str = "FLAC";
pub const EXPECTED_PCM_FORMAT: &str = "PCM_16";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AudioManifest {
    pub ceiling: u32,
    pub rate: u32,
    pub codec: String,
    pub pcm_format: String,
}

pub fn validate_manifest_field_agreement(manifest: &AudioManifest) -> Result<(), String> {
    if manifest.ceiling != EXPECTED_CEILING {
        return Err(format!(
            "manifest ceiling mismatch: expected {}, found {}",
            EXPECTED_CEILING, manifest.ceiling
        ));
    }
    if manifest.rate != EXPECTED_RATE {
        return Err(format!(
            "manifest rate mismatch: expected {}, found {}",
            EXPECTED_RATE, manifest.rate
        ));
    }
    if manifest.codec != EXPECTED_CODEC {
        return Err(format!(
            "manifest codec mismatch: expected {}, found {}",
            EXPECTED_CODEC, manifest.codec
        ));
    }
    if manifest.pcm_format != EXPECTED_PCM_FORMAT {
        return Err(format!(
            "manifest PCM format mismatch: expected {}, found {}",
            EXPECTED_PCM_FORMAT, manifest.pcm_format
        ));
    }
    Ok(())
}