/* SPDX-License-Identifier: MIT */
package kaine.hearing;

public enum HearingStageGainGate {
    G1("1/5"),
    G2("2/5"),
    G3("3/5"),
    G4("4/5"),
    G5("5/5");

    private final String displayName;

    HearingStageGainGate(String displayName) {
        this.displayName = displayName;
    }

    @Override
    public String toString() {
        return displayName;
    }
}