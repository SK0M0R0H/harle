package commands

import (
	"context"
	"fmt"
	"time"

	"github.com/skm/harle/harle-cli/internal/client"
	"github.com/spf13/cobra"
)

func newImportCommand(serverURL *string, apiToken *string) *cobra.Command {
	command := &cobra.Command{
		Use:   "import",
		Short: "Import data from external sources into the vault",
		Long: `Import pages, databases, and other content from external
services into the Harle vault as Markdown files.

The orchestrator server must be running with the appropriate
API credentials configured (e.g. NOTION_API_TOKEN).`,
	}

	command.AddCommand(newImportNotionCommand(serverURL, apiToken))

	return command
}

func newImportNotionCommand(serverURL *string, apiToken *string) *cobra.Command {
	var (
		dryRun    bool
		contextV  string
		targetDir string
		strategy  string
		dbMode    string
	)

	command := &cobra.Command{
		Use:   "notion",
		Short: "Import pages and databases from Notion",
		Long: `Fetch all accessible Notion pages and databases and write
them to the vault as Markdown files.

Requires NOTION_API_TOKEN to be set on the server. Pages shared
with the Notion integration will be imported.

Examples:
  harle import notion                    # import everything
  harle import notion --dry-run          # preview without writing
  harle import notion --context work     # set context scope
  harle import notion --db-mode table    # databases as tables`,
		RunE: func(cmd *cobra.Command, args []string) error {
			httpClient := client.NewHTTPClient(*serverURL, *apiToken)
			httpClient.Client.Timeout = 600 * time.Second

			config := map[string]string{
				"mode":                 "api",
				"context":              contextV,
				"target_dir":           targetDir,
				"strategy":             strategy,
				"database_import_mode": dbMode,
			}

			if dryRun {
				fmt.Println("Notion import (dry run)...")
			} else {
				fmt.Println("Importing from Notion...")
			}

			response, err := httpClient.Import(context.Background(), client.ImportRequest{
				Source: "notion",
				Config: config,
				DryRun: dryRun,
			})
			if err != nil {
				return fmt.Errorf("import failed: %w", err)
			}

			fmt.Printf("Status:         %s\n", response.Status)
			fmt.Printf("Source:         %s\n", response.Source)
			fmt.Printf("Items found:    %d\n", response.ItemsFound)
			fmt.Printf("Items imported: %d\n", response.ItemsImported)
			fmt.Printf("Items skipped:  %d\n", response.ItemsSkipped)
			fmt.Printf("Items failed:   %d\n", response.ItemsFailed)

			if len(response.CreatedPaths) > 0 {
				fmt.Printf("\nCreated files (%d):\n", len(response.CreatedPaths))
				for _, p := range response.CreatedPaths {
					fmt.Printf("  + %s\n", p)
				}
			}
			if len(response.UpdatedPaths) > 0 {
				fmt.Printf("\nUpdated files (%d):\n", len(response.UpdatedPaths))
				for _, p := range response.UpdatedPaths {
					fmt.Printf("  ~ %s\n", p)
				}
			}
			if len(response.Errors) > 0 {
				fmt.Printf("\nErrors (%d):\n", len(response.Errors))
				for _, e := range response.Errors {
					fmt.Printf("  ! %s\n", e)
				}
			}

			return nil
		},
	}

	command.Flags().BoolVar(&dryRun, "dry-run", false, "Preview import without writing files")
	command.Flags().StringVar(&contextV, "context", "personal", "Context scope (personal or work)")
	command.Flags().StringVar(&targetDir, "target-dir", "knowledge/", "Target directory within the vault")
	command.Flags().StringVar(&strategy, "strategy", "skip_existing", "Write strategy: skip_existing, update_changed, force")
	command.Flags().StringVar(&dbMode, "db-mode", "pages", "Database import mode: pages (one file per row) or table (single table file)")

	return command
}
