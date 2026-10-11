## ADDED Requirements

### Requirement: Reports name the broadcast that preceded their prediction
Topos (`topos.report`), Audition (`audition.perception`) and Soma (`soma.report`) SHALL put on every report `prediction_broadcast_tick`, the tick index of the latest broadcast the processor had received, accessed or inhibited, when it formed the prediction the report scores, and `prediction_context_age_s`, the age in entity seconds of the context that prediction used, read when the prediction was formed. Both SHALL be null when the report scores no prediction (the first report, or the first after a skipped reading), and `prediction_context_age_s` SHALL be null when the processor held no context when forming the prediction. The curated research log SHALL copy both fields, and the range sweep SHALL bound both below by 0. The contrast at threshold groups reports by the broadcast whose receipt preceded the formation of their prediction and bins them by the age of the context they used (paper Appendix A.8).

#### Scenario: An inhibited broadcast arrives between two reports
- **WHEN** a processor forms a prediction after receiving accessed broadcast 7, then receives inhibited broadcast 8, then reports
- **THEN** the report carries `prediction_broadcast_tick` 7 and the context age read when the prediction was formed, and the next report carries `prediction_broadcast_tick` 8

#### Scenario: A skipped reading
- **WHEN** a processor skips a non-finite reading
- **THEN** the next report carries `prediction_broadcast_tick` and `prediction_context_age_s` null
