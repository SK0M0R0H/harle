package commands

import (
	"context"

	"github.com/skm/harle/harle-cli/internal/client"
	"github.com/skm/harle/harle-cli/internal/config"
	"github.com/skm/harle/harle-cli/internal/session"
	"github.com/spf13/cobra"
)

func NewRootCommand() *cobra.Command {
	var (
		serverURL    string
		contextValue string
		themeValue   string
	)

	command := &cobra.Command{
		Use:   "harle",
		Short: "Launch a Harle session",
		Long:  "Session-first CLI for Harle. Run with no arguments to start interactive mode.",
		PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
			serverURL = config.ResolveServerURL(serverURL, cmd.Flags().Changed("server"))
			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			httpClient := client.NewHTTPClient(serverURL)
			manager := session.NewManager(httpClient, contextValue, themeValue)
			return manager.Run(context.Background())
		},
	}

	command.PersistentFlags().StringVar(&serverURL, "server", "http://127.0.0.1:8000", "Orchestrator server URL")
	command.PersistentFlags().StringVarP(&contextValue, "context", "c", "personal", "Context scope: personal or work")
	command.PersistentFlags().StringVar(&themeValue, "theme", "auto", "Display theme: auto, dark, light, plain")
	command.AddCommand(newExecCommand(&serverURL, &contextValue))
	command.AddCommand(newInitCommand(&serverURL))
	command.AddCommand(newCaptureCommand(&serverURL))
	command.AddCommand(newImportCommand(&serverURL))

	return command
}
