package commands

import (
	"context"
	"fmt"
	"strings"

	"github.com/skm/harle/harle-cli/internal/client"
	"github.com/spf13/cobra"
)

func newExecCommand(serverURL *string, contextValue *string) *cobra.Command {
	command := &cobra.Command{
		Use:   "exec <message>",
		Short: "Run one non-interactive task",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			httpClient := client.NewHTTPClient(*serverURL)
			message := strings.Join(args, " ")
			response, err := httpClient.Chat(
				context.Background(),
				client.RunRequest{
					Message: message,
					Context: *contextValue,
				},
			)
			if err != nil {
				return err
			}
			fmt.Println(response.Result)
			return nil
		},
	}

	return command
}
