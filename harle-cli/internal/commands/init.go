package commands

import (
	"context"
	"fmt"

	"github.com/skm/harle/harle-cli/internal/client"
	"github.com/spf13/cobra"
)

func newInitCommand(serverURL *string) *cobra.Command {
	command := &cobra.Command{
		Use:   "init",
		Short: "Initialise PostgreSQL database and seed the dataset",
		Long: `Create database tables, write starter files to the dataset
directory, and run initial indexing. The orchestrator server
must be running and configured with DATABASE_URL and
HARLE_DATASET_PATH.

Alternatively, run "harle-init" (Python) directly if the
server is not yet started.`,
		RunE: func(cmd *cobra.Command, args []string) error {
			httpClient := client.NewHTTPClient(*serverURL)

			fmt.Println("Initialising Harle data layer...")
			response, err := httpClient.Init(context.Background())
			if err != nil {
				return fmt.Errorf("init failed: %w", err)
			}

			fmt.Printf("Status:        %s\n", response.Status)
			fmt.Printf("Tables:        created = %v\n", response.TablesCreated)
			fmt.Printf("Seed files:    %d written\n", response.FilesSeeded)
			fmt.Printf("Files indexed: %d\n", response.FilesIndexed)
			fmt.Printf("Total files:   %d\n", response.TotalFiles)
			fmt.Printf("Dataset path:  %s\n", response.DatasetPath)
			return nil
		},
	}

	return command
}
