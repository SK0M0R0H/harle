package commands

import (
	"github.com/spf13/cobra"
)

func newCaptureCommand(serverURL *string, apiToken *string) *cobra.Command {
	command := &cobra.Command{
		Use:   "capture",
		Short: "Capture personal knowledge into your vault",
		Long:  "Commands for capturing knowledge from your head into the Harle vault via interviews, quick profiles, and more.",
	}

	command.AddCommand(newInterviewCommand(serverURL, apiToken))

	return command
}
