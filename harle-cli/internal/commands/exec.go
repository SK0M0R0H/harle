package commands

import (
	"errors"
	"fmt"
	"strings"

	"github.com/skm/harle/harle-cli/internal/client"
	"github.com/spf13/cobra"
)

func newExecCommand(serverURL *string, apiToken *string, contextValue *string) *cobra.Command {
	command := &cobra.Command{
		Use:   "exec <message>",
		Short: "Run one non-interactive task",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			httpClient := client.NewHTTPClient(*serverURL, *apiToken)
			message := strings.Join(args, " ")
			response, err := httpClient.ChatWithPolling(
				cmd.Context(),
				client.RunRequest{
					Message: message,
					Context: *contextValue,
				},
				client.PollConfigFromEnvironment(),
			)
			if err != nil {
				switch {
				case errors.Is(err, client.ErrServerUnreachable),
					errors.Is(err, client.ErrProcessingLost):
					return err
				case errors.Is(err, client.ErrChatServerTimeout):
					return fmt.Errorf("server timed out processing the request (took too long): %w", err)
				default:
					return err
				}
			}
			fmt.Println(response.Result)
			return nil
		},
	}

	return command
}
