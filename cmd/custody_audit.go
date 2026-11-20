// SPDX-FileCopyrightText: 2023 The KAINE Authors
// SPDX-License-Identifier: Apache-2.0

package cmd

import (
	"context"
	"fmt"
	"os"

	"github.com/kaine/kaine/internal/custody"
	"github.com/spf13/cobra"
)

var custodyAuditCmd = &cobra.Command{
	Use:   "audit",
	Short: "Report which entities have escrow bundles present on GitHub",
	RunE:  runCustodyAudit,
}

func init() {
	custodyCmd.AddCommand(custodyAuditCmd)
}

func runCustodyAudit(cmd *cobra.Command, args []string) error {
	escrows, err := custody.ListEscrows()
	if err != nil {
		return err
	}
	if len(escrows) == 0 {
		fmt.Fprintln(os.Stderr, "No escrows found")
		return nil
	}

	ctx := context.Background()
	hasAny := false
	for _, e := range escrows {
		has, err := custody.HasEscrowBundle(ctx, e)
		if err != nil {
			// Print error but continue with other escrows
			fmt.Fprintf(os.Stderr, "Error checking escrow for entity %s: %v\n", e.Entity, err)
			continue
		}
		if has {
			fmt.Printf("%s: present\n", e.Entity)
			hasAny = true
		} else {
			fmt.Printf("%s: absent\n", e.Entity)
		}
	}
	if !hasAny {
		fmt.Fprintln(os.Stderr, "No escrow bundles present on GitHub")
	}
	return nil
}