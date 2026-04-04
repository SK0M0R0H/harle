package commands

import (
	"github.com/skm/harle/harle-cli/internal/client"
	"github.com/skm/harle/harle-cli/internal/config"
	"github.com/skm/harle/harle-cli/internal/session"
	"github.com/spf13/cobra"
)

func NewRootCommand() *cobra.Command {
	var (
		serverURL    string
		apiToken     string
		contextValue string
		themeValue   string
	)

	command := &cobra.Command{
		Use:   "harle",
		Short: "Launch a Harle session",
		Long:  "Session-first CLI for Harle. Run with no arguments to start interactive mode.",
		PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
			serverURL = config.ResolveServerURL(serverURL, cmd.Flags().Changed("server"))
			apiToken = config.ResolveAPIToken(apiToken, cmd.Flags().Changed("token"))
			return nil
		},
		RunE: func(cmd *cobra.Command, args []string) error {
			httpClient := client.NewHTTPClient(serverURL, apiToken)
			manager := session.NewManager(httpClient, contextValue, themeValue)
			return manager.Run()
		},
	}

	command.PersistentFlags().StringVar(&serverURL, "server", "http://127.0.0.1:8000", "Orchestrator server URL")
	command.PersistentFlags().StringVar(&apiToken, "token", "", "API bearer token (optional; overrides HARLE_API_TOKEN and cli.yaml api_token)")
	command.PersistentFlags().StringVarP(&contextValue, "context", "c", "personal", "Context scope: personal or work")
	command.PersistentFlags().StringVar(&themeValue, "theme", "auto", "Display theme: auto, dark, light, plain")
	command.AddCommand(newExecCommand(&serverURL, &apiToken, &contextValue))
	command.AddCommand(newInitCommand(&serverURL, &apiToken))
	command.AddCommand(newCaptureCommand(&serverURL, &apiToken))
	command.AddCommand(newImportCommand(&serverURL, &apiToken))

	return command
}
