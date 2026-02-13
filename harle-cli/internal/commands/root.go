package commands

import (
	"context"

	"github.com/skm/harle/harle-cli/internal/client"
	"github.com/skm/harle/harle-cli/internal/session"
	"github.com/spf13/cobra"
)

func NewRootCommand() *cobra.Command {
	var (
		serverURL    string
		contextValue string
	)

	command := &cobra.Command{
		Use:   "harle",
		Short: "Launch a Harle session",
		Long:  "Session-first CLI for Harle. Run with no arguments to start interactive mode.",
		RunE: func(cmd *cobra.Command, args []string) error {
			httpClient := client.NewHTTPClient(serverURL)
			manager := session.NewManager(httpClient, contextValue)
			return manager.Run(context.Background())
		},
	}

	command.PersistentFlags().StringVar(&serverURL, "server", "http://127.0.0.1:8000", "Orchestrator server URL")
	command.PersistentFlags().StringVarP(&contextValue, "context", "c", "personal", "Context scope: personal or work")
	command.AddCommand(newExecCommand(&serverURL, &contextValue))

	return command
}
