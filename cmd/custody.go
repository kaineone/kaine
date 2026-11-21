// SPDX-FileCopyrightText: 2023 The KAINE Authors
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"github.com/spf13/cobra"
)

var custodyCmd = &cobra.Command{
	Use:   "custody",
	Short: "Operations related to escrow bundles",
}

func init() {
	rootCmd.AddCommand(custodyCmd)
}