package session

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/skm/harle/harle-cli/internal/client"
)

type Manager struct {
	Client  *client.HTTPClient
	Context string
}

func NewManager(httpClient *client.HTTPClient, contextValue string) *Manager {
	return &Manager{
		Client:  httpClient,
		Context: contextValue,
	}
}

func (m *Manager) Run(ctx context.Context) error {
	fmt.Printf("Harle v0.1.0 | context: %s\n", m.Context)
	fmt.Println("Type a message, /help, or /quit.")

	scanner := bufio.NewScanner(os.Stdin)
	for {
		fmt.Print("harle> ")
		if !scanner.Scan() {
			fmt.Println()
			return nil
		}

		input := strings.TrimSpace(scanner.Text())
		if input == "" {
			continue
		}

		switch input {
		case "/quit", "/exit":
			fmt.Println("Session closed.")
			return nil
		case "/help":
			fmt.Println("Slash commands: /help, /quit, /exit")
			continue
		}

		response, err := m.Client.Run(
			ctx,
			client.RunRequest{
				Message: input,
				Context: m.Context,
			},
		)
		if err != nil {
			fmt.Printf("Error: %v\n", err)
			continue
		}
		fmt.Println(response.Result)
	}
}
