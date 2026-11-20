// SPDX-FileCopyrightText: 2023 The KAINE Authors
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"os"

	"github.com/spf13/cobra"
)

var rootCmd = &cobra.Command{
	Use:   "kaine",
	Short: "KAINE is a tool for managing escrow bundles on GitHub",
}

func Execute() {
	if err := rootCmd.Execute(); err != nil {
		os.Exit(1}
	}
}