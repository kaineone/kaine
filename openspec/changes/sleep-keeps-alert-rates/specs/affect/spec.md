## ADDED Requirements

### Requirement: The sleep reset keeps the habituation, learning-progress and intent estimates
`affective_reset()` SHALL leave the perceptual alert rates `r_f` and `r_s`, the per-source fast and slow error means with their latest report times, the intent rate `r_int` and the intent count since the last broadcast unchanged (paper A.4 item 4). They SHALL continue to change only by their own rules: the alert rates decay at each update with their time constants, the error means are re-weighted by the elapsed time at the next report, and `r_int` updates at each broadcast. The reset SHALL still return valence, arousal and dominance to baseline, set every drive to 0 and re-arm its crossing, set the categorical emotion to neutral, clear the active goals and a speaker's perceived emotion, and keep the last wellness.

#### Scenario: A habituated stream stays habituated after sleep
- **WHEN** a module has habituated to an alert every 5 s for 600 s, is reset by sleep, and the same alerts continue
- **THEN** the habituation factor of the next alert is below 1e-6 and that alert raises arousal by less than 0.001

#### Scenario: The reset does not relieve boredom
- **WHEN** the habituated module is reset and the base-rate alerts continue for 60 s
- **THEN** the alert excess stays 0 throughout

#### Scenario: The estimates survive the reset
- **WHEN** a module with nonzero alert rates, error means and intent rate is reset
- **THEN** each of them equals its value just before the reset, while arousal is at baseline and every drive is 0

#### Scenario: A long quiet still restores the first-presentation response
- **WHEN** the habituated module is reset and then 600 s pass with no alert before one alert with change ratio 3.0
- **THEN** that alert's habituation factor is above 0.9
