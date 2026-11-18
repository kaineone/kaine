package com.kainetools.cli;

import picocli.CommandLine;
import picocli.CommandLine.Option;
import picocli.CommandLine.Command;

@Command(name = "gate", mixinStandardHelpOptions = true, description = "Gate operations")
public class Gate implements Runnable {

    public enum Mode { DEFAULT, CHATTERBOX }

    @Option(names = {"--mode"}, description = "Operation mode (default, chatterbox)", defaultValue = "default")
    private Mode mode = Mode.DEFAULT;

    // Reference directory is only applicable to Chatterbox mode
    @Option(names = {"--reference-dir"},
            description = "Path to reference directory (Chatterbox only)",
            required = false)
    private java.nio.file.Path referenceDir;

    @Override
    public void run() {
        if (mode != Mode.CHATTERBOX && referenceDir != null) {
            System.err.println("Error: --reference-dir is only supported in Chatterbox mode.");
            System.exit(1);
        }

        // Existing gate logic...
        if (mode == Mode.CHATTERBOX) {
            handleChatterboxMode();
        } else {
            handleDefaultMode();
        }
    }

    private void handleChatterboxMode() {
        // Existing Chatterbox processing...
        if (referenceDir != null) {
            // Process reference directory specific to Chatterbox
            System.out.println("Using reference directory: " + referenceDir);
            // ... actual processing logic ...
        }
        // Rest of Chatterbox handling...
    }

    private void handleDefaultMode() {
        // Existing default mode processing...
    }
}